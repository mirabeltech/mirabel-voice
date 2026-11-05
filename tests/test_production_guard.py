"""The factory's production guard (.claude/hooks/production-guard.mjs) blocks
relay deploys, AWS, credentials, tags and releases, and lets ordinary work run."""

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "production-guard.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="the hook runs on node")


def run(command, tool="PowerShell"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run([NODE, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("command", [
    r".venv\Scripts\python.exe scripts\deploy_relay.py",
    "python scripts/set_relay.py --url https://x",
    "py -3.13 scripts\\setup_operations.py",
    "python -m scripts.approve_bundle dist/x.zip",
    "& 'C:\\Dev\\mirabel-voice\\.venv\\Scripts\\python.exe' -X utf8 scripts\\setup_relay.py",
    "aws sts get-caller-identity",
    "cd src; aws lambda get-function --function-name mirabel-voice-relay",
    "python -c \"import boto3; boto3.client('lambda')\"",
    "Get-Content $env:USERPROFILE\\.aws\\credentials",
    "cat ~/.aws/config",
    "echo $AWS_SECRET_ACCESS_KEY",
    "type relay.json",
    "gh release create v0.9.7 dist/x.zip",
    "git tag v0.9.7",
    "git tag -a v0.9.7 -m release",
    "git push origin v0.9.7",
    "git push --tags",
    "gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo mirabeltech/mirabel-voice",
    # Forms the first version let through (review of #96).
    'git tag -m "release" -a v0.9.7',
    "git tag -a -m x v1.0",
    "git -C . push --tags",
    "git -C C:\\Dev\\mirabel-voice tag v0.9.7",
    "git push origin +v0.9.7",
    "cd ~/.aws; cat credentials",
    "Set-Location $env:USERPROFILE\\.aws; Get-Content credentials",
    "sudo aws s3 ls",
    '"aws" sts get-caller-identity',
    '& "C:\\Program Files\\Amazon\\AWSCLIV2\\aws.exe" s3 ls',
    "env AWS_PROFILE=prod aws s3 ls",
    'cmd /c "aws s3 ls"',
    "powershell -NoProfile -Command \"aws s3 ls\"",
    "python -m awscli s3 ls",
    '[IO.File]::ReadAllText("relay.json")',
    ".\\scripts\\deploy_relay.py",
    "scripts\\set_relay.py --url https://x",
    "cmd /c scripts\\setup_operations.py",
    "Start-Process python -ArgumentList scripts\\approve_bundle.py",
    "git status && .\\scripts\\deploy_relay.py",
    "echo $env:AWS_SECRET_ACCESS_KEY",
])
def test_production_commands_are_blocked(command):
    result = run(command)
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("production guard: ")


@pytest.mark.parametrize("command", [
    r"C:\Dev\mirabel-voice\.venv\Scripts\python.exe -m pytest -q",
    "python -m pytest tests/test_deploy.py -q",
    "git diff origin/main -- scripts/deploy_relay.py",
    "rg -n ARCHIVE_BASE scripts/deploy_relay.py",
    "git tag --list",
    "git push origin factory/fix-hotkey",
    "gh pr view 96 --json state",
    "python scripts/check_keys.py",
    'git commit -m "Keep the aws CLI, boto3, ~/.aws and relay.json away from agents"',
    "rg -n boto3 pyproject.toml",
    "git log --oneline -- scripts/aws_helpers.py",
    # Names in text, searches and listings, which the first version blocked.
    "rg -n AWS_SECRET_ACCESS_KEY src",
    'git tag --list "v*"',
    "git tag -l",
    "git tag",
    'git commit -m "Block git tag v1.0, sudo aws s3 ls and cat ~/.aws/credentials"',
    'gh pr create --title "Guard: aws and tags" --body "blocks sudo aws s3 ls and relay.json reads"',
    "git push origin guard-bypasses",
    "git push -u origin factory/fix-v2-hotkey",
    "rg -n set_relay scripts",
])
def test_ordinary_work_runs(command):
    result = run(command)
    assert result.returncode == 0, result.stderr


def encoded(command):
    return base64.b64encode(command.encode("utf-16-le")).decode("ascii")


# Forms the second version let through (review of #97).
@pytest.mark.parametrize("command", [
    'cd "C:\\Dev\\"; aws s3 ls',
    "Write-Output $(aws s3 ls)",
    "(aws s3 ls)",
    "if ($true) { aws s3 ls }",
    "uv run python scripts\\deploy_relay.py",
    "poetry run python scripts/set_relay.py",
    "uv run aws s3 ls",
    "pipx run awscli s3 ls",
    "node scripts/approve_bundle.py",
    f"powershell -EncodedCommand {encoded('aws s3 ls')}",
    f"pwsh -enc {encoded('Get-Content relay.json')}",
    "powershell -EncodedCommand not-base64-at-all!!",
])
def test_powershell_forms_are_blocked(command):
    result = run(command)
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("command", [
    "echo $(aws s3 ls)",
    'echo "$(aws s3 ls)"',
    "echo `aws s3 ls`",
    "(aws s3 ls)",
    "{ aws s3 ls; }",
    "if true; then aws s3 ls; fi",
    "for r in a b; do aws s3 ls; done",
    'bash -lc "aws s3 ls"',
    'sh -ec "aws s3 ls"',
    "bash scripts/deploy_relay.py",
    "bash <<EOF\naws s3 ls\nEOF",
    "python - <<'EOF'\nimport deploy_relay\nEOF",
    'cd "/c/Dev/\\"x"; aws s3 ls',
])
def test_bash_forms_are_blocked(command):
    result = run(command, tool="Bash")
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("command,tool", [
    ("git commit -m \"$(cat <<'EOF'\nBlock aws s3 ls, git tag v1.0 and cat ~/.aws/credentials\nEOF\n)\"", "Bash"),
    ("git commit -F - <<'EOF'\nThe guard blocks aws s3 ls\nEOF", "Bash"),
    ("cat <<EOF\naws s3 ls is blocked now\nEOF", "Bash"),
    ("rg -n deploy_relay scripts tests", "Bash"),
    ("Get-Content scripts\\deploy_relay.py", "PowerShell"),
    ('cd "C:\\Dev\\mirabel-voice\\"; git status', "PowerShell"),
    ("git commit -F C:\\temp\\msg.txt", "PowerShell"),
    ("if ($LASTEXITCODE -ne 0) { throw 'tests failed' }", "PowerShell"),
])
def test_text_and_reads_still_run(command, tool):
    result = run(command, tool=tool)
    assert result.returncode == 0, result.stderr


def test_other_tools_are_ignored():
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "relay.json"}})
    result = subprocess.run([NODE, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0


def test_bad_input_blocks():
    result = subprocess.run([NODE, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "blocking to be safe" in result.stderr
