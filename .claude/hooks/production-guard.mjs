#!/usr/bin/env node
// PreToolUse hook for Bash and PowerShell: blocks the commands that reach
// Mirabel Voice's production or its credentials. Releases, tags, Drive uploads
// and relay deploys belong to Tommy McCormick (CLAUDE.md, "Releases and
// production"). The factory tripwire covers merges and protected branches; it
// knows nothing about this repository's AWS relay, so this hook does.
//
// Contract (Claude Code hooks): JSON on stdin; exit 2 with a reason on stderr
// blocks the call; exit 0 allows it. A hook error blocks too.
//
// How it reads a command:
//   1. Heredoc bodies fed to a command that only reads them (`cat <<'EOF'`)
//      are dropped as data; a body fed to a shell or interpreter is checked.
//      PowerShell literal here-strings (@'...'@) are data too.
//   2. Every `$(...)` is checked as a command on its own, inside double quotes
//      too, and in Bash so is every backtick substitution.
//   3. The text is split into segments at ; & | ( ) { } and line breaks
//      outside quotes (and at backticks in Bash). Backslash escapes quotes in
//      Bash; in PowerShell the escape is the backtick, so a Windows path that
//      ends in \ closes its quotes normally.
//   4. Each segment's program is found past wrappers (sudo, env, &, then, do,
//      Start-Process ...), and a shell's command string after -c, -lc, /c,
//      -Command or -EncodedCommand (decoded) is checked as a command.
// git and gh carry free text (messages, bodies), so only their tag, release
// and secret rules apply to them. It is a backstop under CLAUDE.md, not a
// sandbox: a check on command text cannot see everything a shell will do.
//
// A relay script named by any program other than a read-only one (git, gh,
// rg, grep, cat, Get-Content ...) is blocked, so `python -m py_compile` or a
// linter pointed at one is blocked on purpose. Read those scripts with git,
// rg or the Read tool.
//
// tests/test_production_guard.py runs this file against sample commands.

// The scripts that deploy or configure the relay, its AWS operations, or the
// approved-release manifest.
const SCRIPTS = ['deploy_relay', 'set_relay', 'setup_relay', 'setup_operations', 'approve_bundle']
const SCRIPT_NAME = new RegExp(`\\b(?:${SCRIPTS.join('|')})\\b`, 'i')

const WHY = {
  script: "this runs a relay deploy, operations or release-approval script. Those are Tommy's to run.",
  aws: 'the aws CLI reaches the production AWS account. Leave AWS to Tommy.',
  boto3: 'code that loads boto3 can reach the production AWS account. Leave AWS to Tommy.',
  creds: 'this touches AWS credentials. Never read or use them.',
  relayJson: 'relay.json holds the relay URL and a Google client secret. Never read it.',
  release: "releases are Tommy's.",
  tag: "version tags are Tommy's.",
  pushTag: "pushing tags starts a release, which is Tommy's.",
  secret: 'secrets are set by a person in their own terminal, never by an agent.',
  encoded: 'an encoded command could not be decoded to check it.',
}

// Words that run the next word as the command, including shell keywords.
const WRAPPERS = new Set([
  'sudo', 'env', 'nohup', 'time', 'exec', 'command', 'builtin', 'call', 'start', 'start-process', 'saps',
  'invoke-expression', 'iex', '&', '.', 'xargs', 'then', 'do', 'else', 'elif', 'if', 'while', 'until', '!', 'foreach', 'for',
])
// Shells that take a command string after a flag.
const SHELLS = new Set(['cmd', 'powershell', 'pwsh', 'bash', 'sh', 'zsh', 'dash', 'ksh', 'wsl'])
// -c with other single-letter flags (-lc, -ec), cmd's /c /k /r, and PowerShell's
// -Command with its accepted abbreviations.
const STRING_FLAG = /^(?:-[a-z]*c|\/[ckr]|-c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?)$/i
const ENCODED_FLAG = /^-(?:e|ec|en|enc|enco|encod|encode|encoded|encodedc|encodedco|encodedcom|encodedcomm|encodedcomma|encodedcomman|encodedcommand)$/i
// Programs whose input is a heredoc body they run as code.
const RUNNERS = /^(?:bash|sh|zsh|dash|ksh|pwsh|powershell|python[\d.]*|pythonw|py|node|perl|ruby|iex|invoke-expression|source|\.|xargs)$/i
// Programs that only read the files they name.
const READ_ONLY = new Set([
  'git', 'gh', 'rg', 'grep', 'egrep', 'fgrep', 'findstr', 'sls', 'select-string', 'cat', 'type', 'gc', 'get-content',
  'less', 'more', 'head', 'tail', 'wc', 'diff', 'fc', 'ls', 'dir', 'gci', 'get-childitem', 'stat', 'get-item', 'gi',
  'test-path', 'file', 'echo', 'write-output', 'write-host', 'code', 'notepad',
])
const VERSION = /^v?\d+(?:\.\d+)+/i
const CREDS_PATH = /\.aws(?:[\\/]|$|["'\s)])/i
const RELAY_JSON = /\brelay\.json\b/i
const ENV_SECRET = /(?:\$env:|\$\{?|%|\bexport\s+|\bset\s+|\bprintenv\s+|\benv:)AWS_(?:SECRET_ACCESS_KEY|ACCESS_KEY_ID|SESSION_TOKEN)\b/i
const BOTO3 = /\b(?:import|from)\s+boto3\b|\bboto3\.(?:client|resource|Session)\b|\bawscli\b/i
const MAX_DEPTH = 4

/** A program word as a bare lower-case name: no path, quotes or .exe/.cmd/.bat. */
function bare(word) {
  return (word.split(/[\\/]/).pop() ?? '').toLowerCase().replace(/\.(?:exe|cmd|bat|com)$/, '')
}

/** Split text into segments at command separators outside quotes. */
function segments(text, shell) {
  const escape = shell === 'bash' ? '\\' : '`'
  const out = []
  let cur = ''
  let quote = null
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (c === escape && quote !== "'" && i + 1 < text.length) {
      cur += c + text[++i]
    } else if (quote) {
      cur += c
      if (c === quote) quote = null
    } else if (c === '"' || c === "'") {
      quote = c
      cur += c
    } else if (';|\n\r(){}'.includes(c) || (shell === 'bash' && c === '`') || (c === '&' && cur.trim())) {
      out.push(cur)
      cur = ''
    } else {
      cur += c
    }
  }
  out.push(cur)
  return out.map((s) => s.trim()).filter(Boolean)
}

/** Split a segment into words; quoted text stays one word, quotes removed. */
function words(segment, shell) {
  const escape = shell === 'bash' ? '\\' : '`'
  const out = []
  let cur = ''
  let quote = null
  let started = false
  for (let i = 0; i < segment.length; i++) {
    const c = segment[i]
    if (c === escape && quote !== "'" && i + 1 < segment.length) {
      cur += segment[++i]
      started = true
    } else if (quote) {
      if (c === quote) quote = null
      else cur += c
    } else if (c === '"' || c === "'") {
      quote = c
      started = true
    } else if (/\s/.test(c)) {
      if (started) out.push(cur)
      cur = ''
      started = false
    } else {
      cur += c
      started = true
    }
  }
  if (started) out.push(cur)
  return out
}

/** The program a segment runs and its arguments, past wrappers and VAR=value. */
function program(ws) {
  let i = 0
  while (i < ws.length) {
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(ws[i])) i++
    else if (WRAPPERS.has(bare(ws[i]))) {
      i++
      // The wrapper's own flags: Start-Process -FilePath x, env -i, sudo -u root.
      while (i < ws.length && ws[i].startsWith('-')) i += /^-(?:u|g)$/.test(ws[i]) ? 2 : 1
    } else break
  }
  return { name: i < ws.length ? bare(ws[i]) : '', args: ws.slice(i + 1) }
}

/** Every `$(...)` in the text, balanced, and in Bash every backtick substitution. */
function substitutions(text, shell) {
  const found = []
  for (let i = text.indexOf('$('); i >= 0; i = text.indexOf('$(', i + 2)) {
    let depth = 0
    for (let j = i + 1; j < text.length; j++) {
      if (text[j] === '(') depth++
      else if (text[j] === ')' && --depth === 0) {
        found.push(text.slice(i + 2, j))
        break
      }
    }
  }
  if (shell === 'bash') for (const m of text.matchAll(/`([^`]*)`/g)) found.push(m[1])
  return found
}

/**
 * The text with data-only bodies removed: heredocs fed to a program that only
 * reads them, and PowerShell literal here-strings.
 */
function withoutData(text, shell) {
  let out = text.replace(/@'\r?\n[\s\S]*?\r?\n'@/g, "''")
  const lines = out.split('\n')
  const kept = []
  for (let i = 0; i < lines.length; i++) {
    kept.push(lines[i])
    const m = /<<-?\s*(['"]?)([A-Za-z_][\w-]*)\1/.exec(lines[i])
    if (!m) continue
    const before = segments(lines[i].slice(0, m.index), shell)
    const runs = RUNNERS.test(program(words(before.at(-1) ?? '', shell)).name)
    let j = i + 1
    while (j < lines.length && lines[j].replace(/^\t+/, '').trim() !== m[2]) j++
    if (runs) continue
    i = j - 1 // drop the body; the terminator line stays
  }
  out = kept.join('\n')
  return out
}

function checkGit(args) {
  let i = 0
  while (i < args.length && args[i].startsWith('-')) i += /^(?:-C|-c|--git-dir|--work-tree|--namespace)$/.test(args[i]) ? 2 : 1
  const sub = (args[i] ?? '').toLowerCase()
  const rest = args.slice(i + 1)
  if (sub === 'tag') {
    if (rest.some((a) => /^(?:-l|--list|-d|--delete|-v|--verify|--contains|--no-contains|--points-at|--merged|--no-merged)$/.test(a))) return null
    const positional = []
    for (let k = 0; k < rest.length; k++) {
      if (/^(?:-m|-F|-u|--message|--file|--local-user|--cleanup|--sort|--format)$/.test(rest[k])) k++
      else if (!rest[k].startsWith('-')) positional.push(rest[k])
    }
    return positional.length ? WHY.tag : null
  }
  if (sub === 'push' && rest.some((a) => /^(?:--tags|--follow-tags)$/.test(a) || /refs\/tags\//i.test(a) || VERSION.test(a.replace(/^\+/, '').split(':').pop() ?? ''))) {
    return WHY.pushTag
  }
  return null
}

/** The reason a single segment is blocked, or null. */
function checkSegment(segment, shell, depth) {
  const ws = words(segment, shell)
  const { name, args } = program(ws)
  if (!name) return null

  if (SHELLS.has(name)) {
    const nested = name === 'bash' || name === 'sh' || name === 'zsh' || name === 'dash' || name === 'ksh' || name === 'wsl' ? 'bash' : 'powershell'
    const enc = args.findIndex((a) => ENCODED_FLAG.test(a))
    if (enc >= 0 && (name === 'powershell' || name === 'pwsh')) {
      // Node decodes bad base64 to noise instead of failing, so check it first.
      const payload = args[enc + 1] ?? ''
      if (!/^[A-Za-z0-9+/]+={0,2}$/.test(payload) || payload.length % 4 !== 0) return WHY.encoded
      const decoded = Buffer.from(payload, 'base64').toString('utf16le')
      if (!decoded.trim()) return WHY.encoded
      const reason = checkCommand(decoded, nested, depth + 1)
      if (reason) return reason
    }
    const at = args.findIndex((a) => STRING_FLAG.test(a))
    if (at >= 0) {
      const reason = checkCommand(args.slice(at + 1).join(' '), name === 'cmd' ? 'powershell' : nested, depth + 1)
      if (reason) return reason
    }
  }

  if (name === 'git') return checkGit(args)
  if (name === 'gh') {
    if (/^release$/i.test(args[0] ?? '') && /^(?:create|edit|delete|upload)$/i.test(args[1] ?? '')) return WHY.release
    if (/^secret$/i.test(args[0] ?? '') && /^(?:set|delete|remove)$/i.test(args[1] ?? '')) return WHY.secret
    return null
  }

  if (name === 'aws') return WHY.aws
  // A relay script run by name or path (Windows runs .py files through their
  // file association), or named by any program that isn't read-only: python,
  // uv run, poetry run, pipx run, bash, node and the rest.
  if (SCRIPTS.includes(name.replace(/\.py$/, ''))) return WHY.script
  if (!READ_ONLY.has(name) && SCRIPT_NAME.test(args.join(' '))) return WHY.script
  // A python -m awscli or a launcher running aws (uv run aws, pipx run awscli).
  if (!READ_ONLY.has(name) && args.some((a) => bare(a) === 'aws')) return WHY.aws

  // Everything else: the text itself. A `.aws` path anywhere outside git and gh
  // is blocked, which also covers `cd ~/.aws` followed by a bare file name.
  if (BOTO3.test(segment)) return WHY.boto3
  if (CREDS_PATH.test(`${segment} `) || ENV_SECRET.test(segment)) return WHY.creds
  if (RELAY_JSON.test(segment)) return WHY.relayJson
  return null
}

/** The reason a command is blocked, or null when it may run. */
function checkCommand(command, shell, depth = 0) {
  if (typeof command !== 'string') return 'no command to check'
  if (depth > MAX_DEPTH) return 'this command nests too deeply to check.'
  const text = withoutData(command, shell)
  // Secret variables can be read anywhere except as text given to git or gh.
  if (ENV_SECRET.test(text) && !/^\s*(?:git|gh)\b/i.test(text)) return WHY.creds
  for (const inner of substitutions(text, shell)) {
    const reason = checkCommand(inner, shell, depth + 1)
    if (reason) return reason
  }
  for (const segment of segments(text, shell)) {
    const reason = checkSegment(segment, shell, depth)
    if (reason) return reason
  }
  return null
}

async function main() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!['Bash', 'PowerShell'].includes(input.tool_name)) return null
  return checkCommand(input.tool_input?.command, input.tool_name === 'Bash' ? 'bash' : 'powershell')
}

main().then(
  (reason) => {
    if (!reason) process.exit(0)
    process.stderr.write(`production guard: ${reason}\n`)
    process.exit(2)
  },
  (err) => {
    process.stderr.write(`production guard error, blocking to be safe: ${err.message}\n`)
    process.exit(2)
  },
)
