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
// tests/test_production_guard.py runs this file against sample commands.

// The scripts that deploy or configure the relay, its AWS operations, or the
// approved-release manifest.
const SCRIPTS = 'deploy_relay|set_relay|setup_relay|setup_operations|approve_bundle'

// Commands that read or copy a file's contents. A file named only in a commit
// message or a search pattern is not read.
const READERS = '(?:^|[;&|(`{\\n]\\s*)(?:cat|type|gc|get-content|more|less|head|tail|sls|select-string|rg|grep|findstr|copy|cp|copy-item|python[\\d.]*|py|node)(?:\\.exe)?\\b'

const RULES = [
  {
    // python, py, pythonw or a venv's python.exe naming one of the scripts in
    // the same command segment: by path, with -m, or after interpreter flags.
    re: new RegExp(`\\b(?:python[\\d.]*|pythonw|py)(?:\\.exe)?\\b[^;&|\\n]*\\b(?:${SCRIPTS})\\b`, 'i'),
    why: 'this runs a relay deploy, operations or release-approval script. Those are Tommy\'s to run.',
  },
  // aws where a command starts, not the word inside a message or a path.
  { re: /(?:^|[;&|(`{\n]\s*)aws(?:\.exe|\.cmd)?\s+[a-z]/im, why: 'the aws CLI reaches the production AWS account. Leave AWS to Tommy.' },
  { re: /\b(?:import|from)\s+boto3\b|\bboto3\.(?:client|resource|Session)\b/i, why: 'code that loads boto3 can reach the production AWS account. Leave AWS to Tommy.' },
  { re: new RegExp(`${READERS}[^;&|\\n]*\\.aws[\\\\/]|\\bAWS_(?:SECRET_ACCESS_KEY|ACCESS_KEY_ID|SESSION_TOKEN)\\b`, 'i'), why: 'this touches AWS credentials. Never read or use them.' },
  { re: new RegExp(`${READERS}[^;&|\\n]*\\brelay\\.json\\b`, 'i'), why: 'relay.json holds the relay URL and a Google client secret. Never read it.' },
  { re: /\bgh\s+release\s+(?:create|edit|delete|upload)\b/i, why: 'releases are Tommy\'s.' },
  { re: /\bgit\s+tag\s+(?:-[asfm]\s+)*["']?v?\d/i, why: 'version tags are Tommy\'s.' },
  { re: /\bgit\s+push\b[^;&|]*(?:--tags|--follow-tags|\brefs\/tags\/|\sv\d+\.\d+)/i, why: 'pushing tags starts a release, which is Tommy\'s.' },
  { re: /\bgh\s+secret\s+(?:set|delete|remove)\b/i, why: 'secrets are set by a person in their own terminal, never by an agent.' },
]

/** The reason a command is blocked, or null when it may run. */
function blockedReason(command) {
  if (typeof command !== 'string') return 'no command to check'
  for (const rule of RULES) if (rule.re.test(command)) return rule.why
  return null
}

async function main() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (!['Bash', 'PowerShell'].includes(input.tool_name)) return null
  return blockedReason(input.tool_input?.command)
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
