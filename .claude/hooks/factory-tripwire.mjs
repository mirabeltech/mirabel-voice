#!/usr/bin/env node
/**
 * factory-tripwire.mjs — PreToolUse tripwires for software-factory repos
 * (plan §3 and §6). Copy into the repo as .claude/hooks/factory-tripwire.mjs
 * and wire it with templates/factory/claude-settings.json, which sets
 * `onFailure: block` so a crashed or timed-out hook blocks the call too.
 *
 * Blocks, in Bash and PowerShell tool calls:
 *   1. `git push` that updates a protected branch: the default branch, `main`,
 *      `master`, anything in FACTORY_PROTECTED_BRANCHES (comma list), a bare
 *      push from one of them, `--all`/`--mirror`, and wildcard refspecs.
 *   2. Merging a PR (`gh pr merge`, or the merge endpoints through `gh api`)
 *      unless the session's own environment has FACTORY_AUTOMERGE=allowed.
 *      An inline `FACTORY_AUTOMERGE=allowed gh pr merge` does not count: the
 *      agent could type that itself.
 *   3. Answering an Archon gate (`archon workflow approve|reject|respond|answer`,
 *      or the same through Archon's local HTTP API). The engine accepts a CLI
 *      answer from any process, so this is what keeps an AI node from passing
 *      `approve-plan` on the dev's behalf.
 *   4. Adding or removing the record labels `plan-approved`, `auto-merge` or
 *      `factory-pr`. Only the workflow's deterministic nodes change those.
 *      Removing `auto-merge` silently turns a run into owner-merges, and
 *      removing `factory-pr` would drop the audit factory-gate requires.
 *   5. Searching from a filesystem or drive root (`/`, `/c`, `/mnt/c`, `C:\`):
 *      `find`, recursive `grep`, `rg`, `ls -R`, `Get-ChildItem -Recurse` (and
 *      its aliases `gci`, `dir`, `ls`) and cmd's `dir /s`. In the pilot one
 *      such search ran 32 minutes and another hung a run for 30. Only these
 *      commands are checked (not `fd`, `tree`, `du`, `git grep` or
 *      `Select-String`), and a path held in an unknown variable is allowed.
 *   6. Posting an `Owner check:` comment through `gh` (an inline body or field).
 *      It is the owner's sign-off that factory-gate accepts for an audit only a
 *      person can settle. A body read from a file is not seen.
 *   7. On Windows, in Bash, Python code that names `/tmp` (in `-c` code or a
 *      heredoc fed to Python). Windows Python opens it as C:\tmp, not Git Bash's
 *      /tmp, so a file written in one is missing or stale in the other.
 *
 * It reads nested shells (`bash -lc`, `pwsh -Command`, `eval`), command
 * substitutions, wrappers (`env`, `sudo`, `timeout`) and `cd` earlier on the
 * line. It ignores heredoc bodies and quoted text, which are data.
 *
 * This is a tripwire, not the control. It matches commands as written:
 * a script file, an alias or a Makefile that runs the same command is not
 * seen. Branch protection and `factory-gate` are the controls.
 *
 * Unlike templates/hooks/pre-tool-use.mjs, this hook FAILS CLOSED: any error
 * blocks the call. Contract (Claude Code hooks): JSON on stdin; exit 2 with a
 * reason on stderr blocks; exit 0 allows. Only local `git` calls, no network.
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// The first line of an owner check, as factory-gate reads it.
const OWNER_CHECK = /^\s*Owner check:/i

// ---------------------------------------------------------------------------
// CONFIG — edit when copying into a repo.
// ---------------------------------------------------------------------------
const CONFIG = {
  // Always protected, besides origin's default branch.
  protectedBranches: ['main', 'master'],
  // Labels agents never add or remove: plan-approved and auto-merge record a
  // human decision, and factory-pr tells factory-gate to require the audit.
  recordLabels: ['plan-approved', 'auto-merge', 'factory-pr'],
  // Archon subcommands that answer a paused gate.
  archonAnswerVerbs: ['approve', 'reject', 'respond', 'answer'],
  // Shown when a search starts at a filesystem or drive root.
  rootSearchMessage: 'Searching the whole disk is blocked: it took 32 minutes in the pilot and hung a run. Search the repo, its node_modules, or ~/.claude/plugins instead.',
  // Shown when, on Windows, Python code names /tmp.
  posixTmpMessage: 'On Windows, Python opens `/tmp` as C:\\tmp, a different folder from Git Bash\'s /tmp, and every run shares it. Put scratch files under $ARTIFACTS_DIR, or pass Python the path as an argument, which Git Bash converts.',
}
// ---------------------------------------------------------------------------

const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'pwsh', 'powershell', 'cmd'])
const HTTP_CLIENTS = new Set(['curl', 'wget', 'invoke-webrequest', 'invoke-restmethod', 'iwr', 'irm'])
// Commands that run the rest of the line as another command, with those of
// their flags that take a value. `timeout` also takes a duration first.
const WRAPPERS = {
  sudo: ['-u', '--user', '-g', '--group', '-C', '--close-from', '-h', '--host', '-p', '--prompt', '-D', '--chdir', '-r', '--role', '-t', '--type', '-U', '--other-user'],
  env: ['-u', '--unset', '-C', '--chdir'],
  exec: ['-a'],
  nice: ['-n', '--adjustment'],
  timeout: ['-s', '--signal', '-k', '--kill-after'],
  command: [], nohup: [], time: [], call: [], '&': [], '.': [],
}
const CD = new Set(['cd', 'pushd', 'chdir', 'set-location', 'sl'])
// Substitutions that only name the current branch; read as HEAD.
const CURRENT_BRANCH_SUBST = /^\s*git\s+(?:branch\s+--show-current|rev-parse\s+--abbrev-ref\s+HEAD|symbolic-ref\s+(?:--short\s+)?HEAD)\s*$/
// Stands in for the output of a substitution inside a word: unknown text.
const DYNAMIC = '\u0000'
const SEPARATORS = ';&|(){}'

class Blocked extends Error {}
const deny = (reason) => { throw new Blocked(reason) }

/** Index of the `)` closing the `$(` whose body starts at `i`, skipping quoted text. */
function closeParen(s, i) {
  let depth = 1
  let quote = null
  for (; i < s.length; i++) {
    const c = s[i]
    if (quote) {
      if (c === '\\' && quote === '"') i++
      else if (c === quote) quote = null
    } else if (c === '"' || c === "'") quote = c
    else if (c === '\\') i++
    else if (c === '(') depth++
    else if (c === ')' && --depth === 0) return i
  }
  return -1
}

const ANSI_C = { n: '\n', t: '\t', r: '\r', a: '\x07', b: '\b', e: '\x1b', f: '\f', v: '\v', '\\': '\\', "'": "'", '"': '"' }

/** Decode one escape in $'...' starting after the backslash; returns [text, length]. */
function ansiEscape(s, i) {
  const c = s[i]
  let m
  if (c === 'x' && (m = /^[0-9a-fA-F]{1,2}/.exec(s.slice(i + 1)))) return [String.fromCodePoint(parseInt(m[0], 16)), 1 + m[0].length]
  if (c === 'u' && (m = /^[0-9a-fA-F]{1,4}/.exec(s.slice(i + 1)))) return [String.fromCodePoint(parseInt(m[0], 16)), 1 + m[0].length]
  if (c === 'U' && (m = /^[0-9a-fA-F]{1,8}/.exec(s.slice(i + 1)))) return [String.fromCodePoint(parseInt(m[0], 16)), 1 + m[0].length]
  if ((m = /^[0-7]{1,3}/.exec(s.slice(i)))) return [String.fromCodePoint(parseInt(m[0], 8)), m[0].length]
  return [ANSI_C[c] ?? c, 1]
}

/**
 * Read a command line the way the shell would: segments of words (quotes
 * removed, escapes applied), the bodies of command substitutions, and heredoc
 * bodies with the segment that reads them. `posix` is false for PowerShell,
 * where backslash is literal and the backtick escapes.
 */
function scan(src, posix, { heredocBody = false } = {}) {
  const segs = []
  const subs = []
  const heredocs = []
  const herestrings = []
  let hereString = false
  let wordsOf = []
  let word = null
  let quote = heredocBody ? '"' : null
  const pending = []
  const endWord = () => {
    if (word !== null) {
      if (hereString) herestrings.push(word)
      else wordsOf.push(word)
      hereString = false
    }
    word = null
  }
  const endSeg = () => { endWord(); if (wordsOf.length) segs.push(wordsOf); wordsOf = [] }
  const add = (text) => { word = (word ?? '') + text }
  const substitution = (body) => {
    if (CURRENT_BRANCH_SUBST.test(body)) return add('HEAD')
    subs.push(body)
    add(DYNAMIC)
  }
  for (let i = 0; i < src.length; i++) {
    const c = src[i]
    const next = src[i + 1]
    if (quote === "'") {
      if (c === "'") quote = null
      else add(c)
      continue
    }
    if (quote === "$'") {
      if (c === "'") quote = null
      else if (c === '\\' && next !== undefined) { const [text, n] = ansiEscape(src, i + 1); add(text); i += n }
      else add(c)
      continue
    }
    // Live text: unquoted, double-quoted, or a heredoc body.
    if (c === '$' && next === '(') {
      const end = closeParen(src, i + 2)
      if (end === -1) deny('unbalanced $( in the command')
      substitution(src.slice(i + 2, end))
      i = end
      continue
    }
    if (posix && c === '`') {
      const end = src.indexOf('`', i + 1)
      if (end === -1) deny('unbalanced backtick in the command')
      substitution(src.slice(i + 1, end))
      i = end
      continue
    }
    if (quote === '"') {
      if (posix && c === '\\' && '\\"$`\n'.includes(next ?? '')) { if (next !== '\n') add(next); i++ }
      else if (!posix && c === '`' && next !== undefined) { add(next); i++ }
      else if (c === '"' && !heredocBody) quote = null
      else add(c)
      continue
    }
    if (c === "'") { quote = "'"; add(''); continue }
    if (c === '"') { quote = '"'; add(''); continue }
    if (posix && c === '$' && next === "'") { quote = "$'"; add(''); i++; continue }
    if (posix && c === '\\' && next !== undefined) { if (next !== '\n') add(next); i++; continue }
    if (!posix && c === '`' && next !== undefined) { if (next !== '\n') add(next); i++; continue }
    // A comment runs to the end of the line (PowerShell's <# #> to its close).
    if (c === '#' && word === null) {
      const eol = src.slice(i).search(/\r?\n/)
      i = eol === -1 ? src.length : i + eol - 1
      continue
    }
    if (!posix && c === '<' && next === '#') {
      const end = src.indexOf('#>', i + 2)
      i = end === -1 ? src.length : end + 1
      continue
    }
    if (posix && c === '<' && next === '<' && src[i + 2] === '<') { endWord(); hereString = true; i += 2; continue } // here-string: the next word is stdin
    if (posix && c === '<' && next === '<') {
      // Heredoc: read the delimiter word; its body starts after this line.
      endWord()
      let j = i + 2
      if (src[j] === '-') j++
      while (src[j] === ' ' || src[j] === '\t') j++
      // The delimiter is one shell word; any quoting or backslash in it makes the body literal.
      const m = /^(?:'[^']*'|"[^"]*"|\\.|[^\s;&|<>()])+/.exec(src.slice(j))
      if (!m) deny('cannot read the heredoc delimiter')
      const delim = m[0].replace(/'([^']*)'|"([^"]*)"|\\(.)/g, (_, a, b, e) => a ?? b ?? e)
      pending.push({ delim, quoted: /['"\\]/.test(m[0]), seg: segs.length })
      i = j + m[0].length - 1
      continue
    }
    if (c === '\n' || c === '\r') {
      endSeg()
      if (c === '\r' && next === '\n') i++
      // Consume the bodies of heredocs opened on this line.
      for (const h of pending.splice(0)) {
        const lines = []
        let k = i + 1
        while (k < src.length) {
          const eol = src.indexOf('\n', k)
          const line = src.slice(k, eol === -1 ? src.length : eol).replace(/\r$/, '')
          k = eol === -1 ? src.length : eol + 1
          if (line.replace(/^\t+/, '') === h.delim) break
          lines.push(line)
        }
        heredocs.push({ ...h, body: lines.join('\n') })
        i = k - 1
      }
      continue
    }
    if (SEPARATORS.includes(c)) { endSeg(); continue }
    if (/\s/.test(c)) { endWord(); continue }
    add(c)
  }
  if (quote && !heredocBody) deny('unterminated quote in the command')
  endSeg()
  for (const h of pending) heredocs.push({ ...h, body: '' })
  return { segs, subs, heredocs, herestrings }
}

/** Expand ~, $NAME, ${NAME} and $env:NAME; null if anything is unknown. */
function expand(word, vars) {
  if (word.includes(DYNAMIC)) return null
  let unknown = false
  const value = word.replace(/^~(?=$|[\\/])/, os.homedir()).replace(/\$\{(\w+)\}|\$env:(\w+)|\$(\w+)/gi, (_, a, b, c) => {
    const name = a ?? b ?? c
    const v = vars.has(name) ? vars.get(name) : process.env[name]
    if (v === undefined) unknown = true
    return v ?? ''
  })
  return unknown || value.includes('$') ? null : value
}

function git(cwd, args) {
  if (!cwd) return null
  const res = spawnSync('git', ['-C', cwd, ...args], { encoding: 'utf8', timeout: 5000 })
  return res.status === 0 ? res.stdout.trim() : null
}

function protectedBranches(cwd) {
  const names = new Set(CONFIG.protectedBranches.map((b) => b.toLowerCase()))
  for (const b of (process.env.FACTORY_PROTECTED_BRANCHES ?? '').split(',')) if (b.trim()) names.add(b.trim().toLowerCase())
  const originHead = git(cwd, ['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'])
  if (originHead) names.add(originHead.replace(/^origin\//, '').toLowerCase())
  return names
}

function checkGitPush(args, cwd, vars) {
  const unknownBranch = 'cannot tell which branch this `git push` updates. Name the branch literally: `git push origin <branch>`.'
  let i = 0
  let repoDir = cwd
  while (i < args.length && args[i].startsWith('-')) {
    if (args[i] === '-C') {
      const dir = expand(args[i + 1] ?? '.', vars)
      repoDir = dir && (path.isAbsolute(dir) ? dir : repoDir && path.resolve(repoDir, dir))
      i += 2
    } else if (['-c', '--git-dir', '--work-tree', '--namespace'].includes(args[i])) i += 2
    else i += 1
  }
  if (args[i] !== 'push') return
  // Without a known directory the default branch can't be read, so it
  // couldn't be protected: refuse instead.
  if (!repoDir || git(repoDir, ['rev-parse', '--git-dir']) === null) {
    deny('cannot tell which repository this `git push` runs in. Push from the worktree directly.')
  }
  const rest = args.slice(i + 1)
  const valued = new Set(['-o', '--push-option', '--receive-pack', '--exec', '--repo'])
  const flags = []
  const positionals = []
  for (let j = 0; j < rest.length; j++) {
    if (rest[j].startsWith('-')) {
      flags.push(rest[j])
      if (valued.has(rest[j])) j++
    } else positionals.push(rest[j])
  }
  if (flags.some((f) => ['--all', '--mirror', '--branches'].includes(f))) {
    deny('`git push --all/--mirror` would update protected branches. Push your feature branch by name.')
  }
  const deleting = flags.some((f) => f === '-d' || f === '--delete')
  const refspecs = positionals.slice(1)
  const guarded = protectedBranches(repoDir)
  const current = () => git(repoDir, ['symbolic-ref', '--quiet', '--short', 'HEAD']) ?? deny(unknownBranch)
  const check = (name, what) => {
    if (guarded.has(name.replace(/^refs\/heads\//i, '').toLowerCase())) {
      deny(`${what} protected branch \`${name}\`. Factory work lands through a PR from a feature branch.`)
    }
  }
  if (refspecs.length === 0) {
    if (flags.includes('--tags')) return
    check(current(), 'a bare `git push` from')
    return
  }
  for (const raw of refspecs) {
    const spec = (expand(raw, vars) ?? deny(unknownBranch)).replace(/^\+/, '')
    const colon = spec.indexOf(':')
    let dst = colon === -1 ? spec : spec.slice(colon + 1) || spec.slice(0, colon)
    if (dst === '') deny(unknownBranch)
    if (dst === 'HEAD' || dst === '@') dst = current()
    if (dst.includes('*')) deny(`wildcard refspec \`${raw}\` can update protected branches. Push branches by name.`)
    check(dst, deleting || colon === 0 ? '`git push` deleting' : '`git push` to')
  }
}

function checkGh(args) {
  const [area, action] = args
  const mergeAllowed = process.env.FACTORY_AUTOMERGE === 'allowed'
  const mergeMsg = 'merging is the owner\'s call (D9), or the workflow\'s merge-mode node after factory-gate. Leave the PR for its owner.'
  if (area === 'pr' && action === 'merge' && !mergeAllowed) deny(`\`gh pr merge\`: ${mergeMsg}`)
  const records = CONFIG.recordLabels.map((l) => l.toLowerCase())
  const joined = args.join(' ')
  // An owner check is the owner's sign-off that factory-gate accepts for an audit
  // only a person can settle; an agent posting one would sign for the owner.
  if (args.some((a) => OWNER_CHECK.test(a.replace(/^(--body|-b|body|--field|-f|--raw-field|-F)=/, '').replace(/^body=/, '')))) {
    deny('posting an `Owner check:` comment. Only the owner signs off the checks an audit left to a person.')
  }
  // The answers are the dev's, recorded by the workflow from its inputs.
  if (args.some((a) => a.includes('factory-answers'))) {
    deny('posting a `factory-answers` record. Pass the dev\'s answers as the workflow\'s `auto_merge` and `dashboard` inputs; the workflow records them.')
  }
  if (area === 'api') {
    if (!mergeAllowed && (/\/pulls\/\d+\/merge\b/i.test(joined) || /\b(mergePullRequest|enablePullRequestAutoMerge)\b/i.test(joined))) {
      deny(`merging through \`gh api\`: ${mergeMsg}`)
    }
    if (/\/labels\b/i.test(joined) && records.some((l) => joined.toLowerCase().includes(l))) {
      deny(`changing a record label through \`gh api\`. Only the workflow writes or removes ${CONFIG.recordLabels.join(', ')}.`)
    }
    // A payload read from a file or stdin can carry a record label the hook cannot
    // see, so a write that can set labels may not take one.
    const fromFile = args.some((a, j) => a === '--input' || /^--input=/.test(a) ||
      (/^(-F|-f|--field|--raw-field)$/.test(a) && /=@/.test(args[j + 1] ?? '')) || /^(-F|-f|--field|--raw-field)=.*=@/.test(a))
    const setsLabels = args.some((a) => /(^|\/)repos\/[^/\s]+\/[^/\s]+\/(issues|pulls)(\/\d+(\/labels)?)?\/?$/i.test(a))
    if (fromFile && setsLabels) {
      deny('`gh api` with a payload from a file on an endpoint that sets labels. The hook cannot see whether it changes a record label; pass the fields inline.')
    }
    return
  }
  if ((area === 'issue' || area === 'pr') && (action === 'edit' || action === 'create')) {
    const changed = []
    for (let j = 2; j < args.length; j++) {
      const m = /^(--add-label|--remove-label|--label|-l)(?:=(.*))?$/.exec(args[j])
      if (m) {
        const verb = m[1] === '--remove-label' ? 'removing' : 'adding'
        changed.push(...(m[2] ?? args[++j] ?? '').split(',').map((l) => [verb, l]))
      }
    }
    // GitHub matches label names without regard to case.
    const hit = changed.map(([v, l]) => [v, l.trim()]).find(([, l]) => records.includes(l.toLowerCase()))
    if (hit) deny(`${hit[0]} the \`${hit[1]}\` label. It records the dev's answer to a workflow gate or marks a factory PR for its audit, so only the workflow changes it.`)
  }
}

function checkArchon(args) {
  const w = args.indexOf('workflow')
  if (w === -1) return
  const verb = args.slice(w + 1).find((a) => !a.startsWith('-'))
  if (CONFIG.archonAnswerVerbs.includes(verb)) {
    deny(`\`archon workflow ${verb}\` answers a workflow gate. The dev answers it in the Archon UI or their own terminal, never an agent.`)
  }
}

function checkHttp(args) {
  const local = /^(https?:\/\/)?(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?\/\S*\b(approve|reject|respond|answer)\b/i
  if (args.some((a) => local.test(a))) deny('calling Archon\'s local API to answer a workflow gate. The dev answers it, never an agent.')
}

// A filesystem or drive root, as Git Bash, WSL, Linux or Windows write it,
// optionally with a trailing glob (`/*`, `C:\*`).
const POSIX_ROOT = /^(?:\/+|\/+(?:mnt\/+)?[a-z]\/*|[a-z]:[\\/]+)\*?$/i
const WINDOWS_ROOT = /^(?:[\\/]+|[a-z]:[\\/]+)\*?$/i

// Path rules in the style a path is written in: Git Bash on Windows tracks
// `cd /c` as `/c`, which win32 rules would read as `D:\c`.
const styleOf = (p) => (/^[a-z]:/i.test(p) || (p.includes('\\') && !p.includes('/')) ? path.win32 : path.posix)
const isAbsolutePath = (p) => path.posix.isAbsolute(p) || path.win32.isAbsolute(p)
/** `p` with `.` and `..` resolved, against `cwd` when relative; null when `cwd` is unknown. */
const resolvePath = (cwd, p) => (isAbsolutePath(p) ? styleOf(p).normalize(p) : cwd ? styleOf(cwd).resolve(cwd, p) : null)

/** True when `word` names a filesystem root, directly or after resolving `..` and `cwd`. */
function isRoot(word, cwd, vars, posix) {
  const value = expand(word, vars)
  if (value === null) return false
  const root = posix ? POSIX_ROOT : WINDOWS_ROOT
  if (root.test(value)) return true
  const resolved = resolvePath(cwd, value)
  return resolved !== null && root.test(resolved)
}

/** Positionals of `args`, skipping each flag in `valued` together with its value. */
function positionals(args, valued) {
  const out = []
  for (let j = 0; j < args.length; j++) {
    const a = args[j]
    if (a === '--') { out.push(...args.slice(j + 1)); break }
    if (a.startsWith('-') && a !== '-') { if (valued.has(a)) j++; continue }
    out.push(a)
  }
  return out
}

const GREP_VALUED = new Set(['-e', '--regexp', '-f', '--file', '-m', '--max-count', '-A', '--after-context', '-B', '--before-context', '-C', '--context', '-d', '--directories', '-D', '--devices', '--include', '--exclude', '--exclude-dir', '--exclude-from', '--label', '--color', '--colour', '--binary-files'])
const RG_VALUED = new Set(['-e', '--regexp', '-f', '--file', '-g', '--glob', '--iglob', '-t', '--type', '-T', '--type-not', '-m', '--max-count', '-A', '--after-context', '-B', '--before-context', '-C', '--context', '-j', '--threads', '-M', '--max-columns', '-E', '--encoding', '-r', '--replace', '-d', '--max-depth', '--max-filesize', '--type-add', '--sort', '--sortr', '--color', '--colors', '--path-separator', '--pre', '--pre-glob', '--ignore-file'])
const PS_RECURSE = /^-r(e(c(u(r(s(e)?)?)?)?)?)?(:\$?true)?$/i
// Parameters that take a value, including the common ones (`-ErrorAction
// SilentlyContinue`, `-ea`, `-ov`). `-File` and `-Force` are switches, so
// `-Filter` is matched only from `-filt` on.
const PS_GCI_VALUED = /^-(filt|filte|filter|include|exclude|depth|attributes|attr\w*|error\w+|warning\w+|information\w+|out\w+|pipeline\w+|ea|wa|infa|ev|wv|iv|ov|ob|pv)$/i
const PS_GCI_PATH = /^-(path|p\w*|literalpath|lp|pspath)$/i

/** Rule 5: refuse a search that starts at a filesystem or drive root. */
function checkSearch(exe, args, cwd, vars, posix, inCmd = false) {
  const block = () => deny(CONFIG.rootSearchMessage)
  const anyRoot = (paths) => {
    // No path means the working directory.
    if (!paths.length) paths = ['.']
    if (paths.some((p) => isRoot(p, cwd, vars, posix))) block()
  }
  const shortFlag = (letter) => args.some((a) => new RegExp(`^-[A-Za-z]*${letter}[A-Za-z]*$`).test(a))
  if (posix && exe === 'find') {
    let j = 0
    while (j < args.length && /^-(H|L|P|O\d*|D)$/.test(args[j])) j += args[j] === '-D' ? 2 : 1
    const starts = []
    for (; j < args.length && !/^[-(!]/.test(args[j]); j++) starts.push(args[j])
    return anyRoot(starts)
  }
  if (posix && (exe === 'grep' || exe === 'egrep' || exe === 'fgrep')) {
    // `-d recurse` (`-drecurse`, `--directories=recurse`) is `-r` spelled out.
    const recursive = shortFlag('[rR]') || args.some((a, i) => a === '--recursive' || a === '--dereference-recursive' ||
      /^(-[A-Za-z]*drecurse|--directories=recurse)$/.test(a) || (/^(-[A-Za-z]*d|--directories)$/.test(a) && args[i + 1] === 'recurse'))
    if (!recursive) return
    const pos = positionals(args, GREP_VALUED)
    const patternGiven = args.some((a) => /^(-e|-f|--regexp|--file)(=|$)/.test(a) || /^-[A-Za-z]*[ef]$/.test(a))
    return anyRoot(patternGiven ? pos : pos.slice(1))
  }
  // ripgrep is a native binary on Windows too, so it is checked in both shells.
  if (exe === 'rg' || exe === 'ripgrep') {
    const pos = positionals(args, RG_VALUED)
    const patternGiven = args.some((a) => /^(-e|-f|--regexp|--file)(=|$)/.test(a) || a === '--files' || a === '--type-list')
    return anyRoot(patternGiven ? pos : pos.slice(1))
  }
  if (posix && (exe === 'ls' || exe === 'dir')) {
    if (!shortFlag('R') && !args.includes('--recursive')) return
    return anyRoot(positionals(args, new Set(['-I', '--ignore', '--hide', '-w', '--width', '-T', '--tabsize', '--format', '--sort', '--time', '--time-style', '--color', '--block-size', '--quoting-style', '--indicator-style'])))
  }
  if (!posix && ['get-childitem', 'gci', 'dir', 'ls'].includes(exe)) {
    // Only cmd has `/` switches: `/` and one letter or digit, optionally negated
    // (`/-c`) or with a `:value` or `-value`, and run together or not (`/s/b`,
    // `/a:d`, `/o-n`, `/4`). In PowerShell every `/x` is a path under the root.
    const isCmdSwitch = (a) => inCmd && /^(?:\/-?[a-z0-9?](?:[:-]-?[a-z]+)?)+$/i.test(a)
    const cmdSwitches = args.filter(isCmdSwitch).flatMap((a) => a.split('/').filter(Boolean))
    const cmdRecursive = cmdSwitches.some((w) => /^s$/i.test(w))
    const recursive = args.some((a) => PS_RECURSE.test(a)) || cmdRecursive
    if (!recursive) return
    const paths = []
    for (let j = 0; j < args.length; j++) {
      const a = args[j]
      if (PS_GCI_PATH.test(a)) { paths.push(...(args[j + 1] ?? '').split(',')); j++; continue }
      if (PS_GCI_VALUED.test(a)) { j++; continue }
      if (a.startsWith('-') || isCmdSwitch(a)) continue
      paths.push(...a.split(','))
    }
    // A name directly under a root searches the whole root for it: `gci C:\*.mjs
    // -Recurse`, cmd's `dir /s C:\x.mjs`, and `gci C:\x.mjs -Recurse`, because
    // PowerShell reads a missing leaf as a name to find. Only a folder that
    // exists here (`gci -r C:\Users`) is a scoped search.
    const wildcardUnderRoot = /^(?:[\\/]|[a-z]:[\\/]+)[^\\/]*[*?]/i
    const leafUnderRoot = /^(?:[\\/]|[a-z]:[\\/]+)[^\\/]+[\\/]?$/i
    const isFolder = (p) => { try { return fs.statSync(p).isDirectory() } catch { return false } }
    if (paths.some((p) => {
      const value = expand(p, vars)
      if (value === null) return false
      return [value, resolvePath(cwd, value)].some((v) => v && (wildcardUnderRoot.test(v) || (leafUnderRoot.test(v) && !isFolder(v))))
    })) block()
    return anyRoot(paths.filter(Boolean))
  }
}

const PS_COMMAND = /^-(c(o(m(m(a(n(d)?)?)?)?)?)?|commandwithargs|cwa)$/i
const PS_ENCODED = /^-(ec|e(n(c(o(d(e(d(c(o(m(m(a(n(d)?)?)?)?)?)?)?)?)?)?)?)?)?)$/i
const PS_VALUED = /^-(ex\w*|executionpolicy|w\w*|windowstyle|v\w*|version|inputformat|if|outputformat|of|configurationname|config\w*|wd|workingdirectory|settingsfile)$/i

/** The command a shell runs from its arguments (`bash -lc X`, `pwsh -Command X`, `cmd /c X`), or null. */
function shellPayload(exe, args) {
  if (exe === 'cmd') {
    const k = args.findIndex((a) => /^\/[ck]$/i.test(a))
    return k === -1 ? null : args.slice(k + 1).join(' ')
  }
  if (exe === 'pwsh' || exe === 'powershell') {
    for (let k = 0; k < args.length; k++) {
      const a = args[k]
      if (PS_ENCODED.test(a)) return Buffer.from(args[k + 1] ?? '', 'base64').toString('utf16le')
      if (PS_COMMAND.test(a)) return args.slice(k + 1).join(' ')
      if (/^-(f|file)$/i.test(a)) return null
      if (PS_VALUED.test(a)) { k++; continue }
      if (a.startsWith('-')) continue
      // Windows PowerShell reads a bare argument as the command; pwsh as a file.
      return exe === 'powershell' ? args.slice(k).join(' ') : null
    }
    return null
  }
  const k = args.findIndex((a) => /^-[A-Za-z]*c[A-Za-z]*$/.test(a))
  return k === -1 ? null : args[k + 1] ?? null
}

const exeName = (word) => path.basename(word.replace(/\\/g, '/')).toLowerCase().replace(/\.(exe|cmd|bat|ps1)$/, '')

/** Drop VAR=value prefixes and wrapper commands with their flags. */
function unwrap(t, check) {
  while (t.length) {
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(t[0])) { t = t.slice(1); continue }
    const name = t[0].toLowerCase()
    const valued = WRAPPERS[name]
    if (!valued) break
    t = t.slice(1)
    while (t.length && t[0].startsWith('-')) {
      if (name === 'env' && /^(-S|--split-string)$/.test(t[0])) { check(t.slice(1).join(' ')); return [] }
      if (name === 'env' && /^(-S|--split-string=)./.test(t[0])) { check([t[0].replace(/^(-S|--split-string=)/, ''), ...t.slice(1)].join(' ')); return [] }
      t = t.slice(valued.includes(t[0]) ? 2 : 1)
    }
    if (name === 'timeout' && t.length) t = t.slice(1)
  }
  return t
}

function checkCommand(cmd, cwd, depth = 0, posix = true, vars = new Map(), inCmd = false) {
  if (depth > 4) deny('command nests shells too deeply to check')
  const nested = (text, isPosix = posix, isCmd = inCmd) => checkCommand(text, cwd, depth + 1, isPosix, vars, isCmd)
  const { segs, subs, heredocs, herestrings } = scan(cmd, posix)
  for (const body of subs) nested(body)
  // Stdin text (heredocs, here-strings) is a script when a shell on this line
  // reads its script from stdin (`bash <<EOF`, `cat <<EOF | sh`, `bash <<< x`).
  // Checked once per kind of shell reading it (POSIX or PowerShell rules).
  const stdinKinds = new Set()
  for (const words of segs) {
    const t = unwrap(words, () => {})
    const exe = t.length ? exeName(t[0]) : null
    if (!SHELLS.has(exe) || exe === 'cmd' || shellPayload(exe, t.slice(1)) !== null) continue
    const args = t.slice(1)
    const readsStdin = !args.some((a) => !a.startsWith('-')) || args.some((a) => /^-[A-Za-z]*s[A-Za-z]*$/.test(a) && a !== '-File')
    if (readsStdin) stdinKinds.add(exe === 'pwsh' || exe === 'powershell' ? 'ps' : 'posix')
  }
  const asScript = (text) => { for (const kind of stdinKinds) nested(text, kind === 'posix') }
  for (const h of heredocs) {
    if (stdinKinds.size) asScript(h.body)
    else if (!h.quoted) for (const body of scan(h.body, posix, { heredocBody: true }).subs) nested(body)
  }
  for (const text of herestrings) asScript(text)
  for (const words of segs) {
    // Assignments set variables for later words on this line: NAME=value
    // (also after export/declare/readonly/local), and PowerShell $NAME = value.
    const decl = /^(export|declare|readonly|local|typeset)$/.test(words[0]) ? words.slice(1).filter((w) => !w.startsWith('-')) : words
    if (decl.length && decl.every((w) => /^[A-Za-z_]\w*=/.test(w))) {
      for (const w of decl) {
        const [name, ...v] = w.split('=')
        vars.set(name, expand(v.join('='), vars) ?? undefined)
      }
      continue
    }
    const psVar = !posix && words.length >= 3 && words[1] === '=' && /^\$(env:)?([A-Za-z_]\w*)$/i.exec(words[0])
    if (psVar) {
      vars.set(psVar[2], expand(words.slice(2).join(' '), vars) ?? undefined)
      continue
    }
    const t = unwrap(words, (text) => nested(text))
    if (!t.length) continue
    const exe = exeName(t[0])
    const args = t.slice(1)
    if (CD.has(exe)) {
      // Later segments run in the new directory; `cd -` and unknowns are null.
      const dir = args.find((a) => !a.startsWith('-') || a === '-')
      const target = dir === undefined ? os.homedir() : dir === '-' ? null : expand(dir, vars)
      cwd = target && resolvePath(cwd, target)
      continue
    }
    if (exe === 'eval' || exe === 'invoke-expression' || exe === 'iex') { nested(args.join(' ')); continue }
    if (SHELLS.has(exe)) {
      const payload = shellPayload(exe, args)
      if (payload !== null) nested(payload, exe !== 'pwsh' && exe !== 'powershell' && exe !== 'cmd', exe === 'cmd')
      continue
    }
    if (exe === 'git') checkGitPush(args, cwd, vars)
    else if (exe === 'gh') checkGh(args)
    else if (exe === 'archon') checkArchon(args)
    else if (HTTP_CLIENTS.has(exe)) checkHttp(args)
    else checkSearch(exe, args, cwd, vars, posix, inCmd)
  }
}

// A Python launcher as a command word, and a POSIX /tmp path. Keep both, and
// pythonSeesPosixTmp, the same as in scripts/factory-eval/workflow-checks.mjs
// (eval DL15); tests/factory-tripwire.mjs runs one case list against both.
const PYTHON_WORD = /(?:^|[\s;&|("'`])(?:[\w.:~/\\-]*[/\\])?py(?:thon(?:3(?:\.\d+)?)?)?(?:\.exe)?(?=[\s;&|)"'`]|$)/
const POSIX_TMP = /(?:^|[^\w.~$/-])\/tmp(?![\w.-])/
const PYTHON_CODE = new RegExp(String.raw`${PYTHON_WORD.source}[^\n;&|]*?\s-c\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)')`, 'g')

/**
 * True when Python itself reads a `/tmp` path: in `-c` code or in a heredoc fed
 * to it. Git Bash converts a path passed as an argument, so `python x.py /tmp/a`
 * is fine, but code is not converted and Windows Python opens C:\tmp (DL15).
 */
function pythonSeesPosixTmp(cmd) {
  const lines = cmd.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!PYTHON_WORD.test(line)) continue
    for (const m of line.matchAll(PYTHON_CODE)) if (POSIX_TMP.test(m[1] ?? m[2])) return true
    const here = /<<-?\s*(["']?)([A-Za-z_]\w*)\1/.exec(line)
    if (!here) continue
    let j = i + 1
    while (j < lines.length && lines[j].trim() !== here[2]) if (POSIX_TMP.test(lines[j++])) return true
    i = j
  }
  return false
}

async function main() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!['Bash', 'PowerShell'].includes(input.tool_name)) return
  const cmd = input.tool_input?.command
  if (typeof cmd !== 'string') deny('no command to check')
  // FACTORY_TRIPWIRE_PLATFORM lets the tests check the Windows rule on any runner.
  const windows = (process.env.FACTORY_TRIPWIRE_PLATFORM || process.platform) === 'win32'
  if (windows && input.tool_name === 'Bash' && pythonSeesPosixTmp(cmd)) deny(CONFIG.posixTmpMessage)
  checkCommand(cmd, input.cwd || process.cwd(), 0, input.tool_name === 'Bash')
}

main().then(
  () => process.exit(0),
  (err) => {
    const reason = err instanceof Blocked ? err.message : `tripwire error, blocking to be safe: ${err.message}`
    process.stderr.write(`factory tripwire: ${reason}\n`)
    process.exit(2)
  },
)
