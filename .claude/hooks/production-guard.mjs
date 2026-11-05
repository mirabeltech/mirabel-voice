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
// How it reads a command: it splits the text into segments at ; & | and line
// breaks outside quotes, then each segment into words, quotes kept together.
// Rules look at the word a segment runs (after wrappers such as sudo, env,
// & or cmd /c), so a commit message or PR body that names these things is
// not blocked. It is a backstop under CLAUDE.md, not a sandbox: text checks
// cannot see everything a shell will do.
//
// Read-only tools that name a relay script as a program to run (for example
// `python -m py_compile scripts/deploy_relay.py`) are blocked on purpose.
// Read those scripts with git, rg or the Read tool instead.
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
}

// Words that run the next word as the command.
const WRAPPERS = new Set(['sudo', 'env', 'nohup', 'time', 'exec', 'command', 'call', 'start', 'start-process', 'saps', 'invoke-expression', 'iex', '&', '.', 'xargs'])
// Shells that take a command string after -c, /c, -Command and the like.
const SHELLS = new Set(['cmd', 'powershell', 'pwsh', 'bash', 'sh', 'zsh', 'wsl'])
const SHELL_FLAGS = /^(?:\/c|\/k|-c|-command|-encodedcommand)$/i
const PYTHON = /^(?:python[\d.]*|pythonw|py)$/i
const VERSION = /^v?\d+(?:\.\d+)+/i
const CREDS_PATH = /\.aws(?:[\\/]|$|["'\s])/i
const RELAY_JSON = /\brelay\.json\b/i
const ENV_SECRET = /(?:\$env:|\$\{?|%|\bexport\s+|\bset\s+|\bprintenv\s+|\benv:)AWS_(?:SECRET_ACCESS_KEY|ACCESS_KEY_ID|SESSION_TOKEN)\b/i
const BOTO3 = /\b(?:import|from)\s+boto3\b|\bboto3\.(?:client|resource|Session)\b|\bawscli\b/i

/** Split a command into segments at ; & | and line breaks outside quotes. */
function segments(text) {
  const out = []
  let cur = ''
  let quote = null
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quote) {
      cur += c
      if (c === quote && text[i - 1] !== '\\') quote = null
    } else if (c === '"' || c === "'") {
      quote = c
      cur += c
    } else if (c === ';' || c === '|' || c === '\n' || c === '\r' || (c === '&' && !/^\s*$/.test(cur))) {
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
function words(segment) {
  const out = []
  let cur = ''
  let quote = null
  let started = false
  for (const c of segment) {
    if (quote) {
      if (c === quote) quote = null
      else cur += c
    } else if (c === '"' || c === "'") {
      quote = c
      started = true
    } else if (/\s/.test(c)) {
      if (started || cur) out.push(cur)
      cur = ''
      started = false
    } else {
      cur += c
      started = true
    }
  }
  if (started || cur) out.push(cur)
  return out
}

/** A program word as a bare lower-case name: no path, quotes or .exe/.cmd/.bat. */
function bare(word) {
  return (word.split(/[\\/]/).pop() ?? '').toLowerCase().replace(/\.(?:exe|cmd|bat|com)$/, '')
}

/** The word a segment runs and the words after it, past wrappers and VAR=value. */
function program(ws) {
  let i = 0
  while (i < ws.length) {
    const b = bare(ws[i])
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(ws[i])) i++
    else if (WRAPPERS.has(b)) {
      i++
      // The wrapper's own flags: Start-Process -FilePath x, env -i, sudo -u root.
      while (i < ws.length && ws[i].startsWith('-')) i += /^-(?:u|g)$/.test(ws[i]) ? 2 : 1
    } else break
  }
  return { name: i < ws.length ? bare(ws[i]) : '', args: ws.slice(i + 1) }
}

/** git's subcommand and its arguments, past global options such as -C dir. */
function gitSub(args) {
  let i = 0
  while (i < args.length && args[i].startsWith('-')) i += /^(?:-C|-c|--git-dir|--work-tree|--namespace)$/.test(args[i]) ? 2 : 1
  return { sub: (args[i] ?? '').toLowerCase(), rest: args.slice(i + 1) }
}

function checkGit(args) {
  const { sub, rest } = gitSub(args)
  if (sub === 'tag') {
    if (rest.some((a) => /^(?:-l|--list|-d|--delete|-v|--verify|--contains|--no-contains|--points-at|--merged|--no-merged)$/.test(a))) return null
    const positional = []
    for (let i = 0; i < rest.length; i++) {
      if (/^(?:-m|-F|-u|--message|--file|--local-user|--cleanup|--sort|--format)$/.test(rest[i])) i++
      else if (!rest[i].startsWith('-')) positional.push(rest[i])
    }
    return positional.length ? WHY.tag : null
  }
  if (sub === 'push') {
    if (rest.some((a) => /^(?:--tags|--follow-tags)$/.test(a) || /refs\/tags\//i.test(a) || VERSION.test(a.replace(/^\+/, '').split(':').pop() ?? ''))) return WHY.pushTag
  }
  return null
}

/** The reason a single segment is blocked, or null. */
function checkSegment(segment, depth) {
  const ws = words(segment)
  const { name, args } = program(ws)
  if (!name) return null

  // A shell running a command string: check that string as a command.
  if (SHELLS.has(name)) {
    const at = args.findIndex((a) => SHELL_FLAGS.test(a))
    if (at >= 0 && depth < 3) return checkCommand(args.slice(at + 1).join(' '), depth + 1)
  }

  // git and gh carry free text (messages, bodies), so only their own rules apply.
  if (name === 'git') return checkGit(args)
  if (name === 'gh') {
    if (/^release$/i.test(args[0] ?? '') && /^(?:create|edit|delete|upload)$/i.test(args[1] ?? '')) return WHY.release
    if (/^secret$/i.test(args[0] ?? '') && /^(?:set|delete|remove)$/i.test(args[1] ?? '')) return WHY.secret
    return null
  }

  if (name === 'aws') return WHY.aws
  // A relay script run by name or path (Windows runs .py files through their
  // file association), or handed to Python in any form.
  if (SCRIPTS.includes(name.replace(/\.py$/, ''))) return WHY.script
  if (PYTHON.test(name) && SCRIPT_NAME.test(args.join(' '))) return WHY.script

  // Everything else: the text itself. A `.aws` path anywhere outside git and gh
  // is blocked, which also covers `cd ~/.aws` followed by a bare file name.
  if (BOTO3.test(segment)) return WHY.boto3
  if (CREDS_PATH.test(`${segment} `) || ENV_SECRET.test(segment)) return WHY.creds
  if (RELAY_JSON.test(segment)) return WHY.relayJson
  return null
}

/** The reason a command is blocked, or null when it may run. */
function checkCommand(command, depth = 0) {
  if (typeof command !== 'string') return 'no command to check'
  // Secret variables can be read in any segment, even inside a git message.
  if (ENV_SECRET.test(command) && !/^\s*(?:git|gh)\b/i.test(command)) return WHY.creds
  for (const segment of segments(command)) {
    const reason = checkSegment(segment, depth)
    if (reason) return reason
  }
  return null
}

async function main() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!['Bash', 'PowerShell'].includes(input.tool_name)) return null
  return checkCommand(input.tool_input?.command)
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
