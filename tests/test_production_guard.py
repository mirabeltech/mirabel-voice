"""The factory's production guard (.claude/hooks/production-guard.mjs) blocks
relay deploys, AWS, credentials, tags and releases, and lets ordinary work run."""

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
])
def test_ordinary_work_runs(command):
    result = run(command)
    assert result.returncode == 0, result.stderr


def test_other_tools_are_ignored():
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "relay.json"}})
    result = subprocess.run([NODE, str(HOOK)], input=payload, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0


def test_bad_input_blocks():
    result = subprocess.run([NODE, str(HOOK)], input="not json", capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "blocking to be safe" in result.stderr
