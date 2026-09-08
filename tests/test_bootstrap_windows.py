"""Run the actual PowerShell bootstrap with isolated, synthetic ZIPs and approvals."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell integration')
BOOTSTRAP = Path(__file__).resolve().parents[1] / 'install.ps1'


def run_bootstrap(tmp_path, approved=True, traversal=False, tampered=False, nested=False):
    downloads = tmp_path / 'downloads'; downloads.mkdir()
    target = tmp_path / 'target with spaces'
    archive = downloads / 'MirabelVoice-9.8.7-python (2).zip'
    with zipfile.ZipFile(archive, 'w') as z:
        installer = "param([string]$Target,[switch]$NoLaunch)\n$ErrorActionPreference = 'Stop'\nif (-not $NoLaunch) { throw 'NoLaunch did not survive child invocation' }\n"
        if nested:
            for member, content in [
                ('docs/readme.txt', 'forward slash'),
                ('python/Lib/example.txt', 'backslash'),
                ('python/Lib/' + 'nested/' * 40 + 'data.txt', 'long path'),
            ]:
                windows_member = member.replace('/', '\\')
                installer += (
                    "$path = '\\\\?\\' + $PSScriptRoot + '\\" + windows_member + "'\n"
                    "if ([IO.File]::ReadAllText($path) -ne '" + content + "') { throw 'Incorrect extracted content' }\n"
                )
        installer += "New-Item -ItemType Directory -Force $Target | Out-Null\nSet-Content (Join-Path $Target 'installed.txt') 'synthetic installer ran'\n"
        z.writestr('Install.ps1', installer)
        if nested:
            z.writestr('docs/', '')
            z.writestr('docs/readme.txt', 'forward slash')
            z.writestr('python\\Lib\\example.txt', 'backslash')
            z.writestr('python/Lib/' + 'nested/' * 40 + 'data.txt', 'long path')
        if traversal:
            z.writestr('../escaped.txt', 'should never be written')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if tampered:
        with zipfile.ZipFile(archive, 'a') as z:
            z.writestr('changed.txt', 'post-approval modification')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema': 1, 'bundles': [{'version':'9.8.7','sha256':digest,'approved':approved}]}))
    result = subprocess.run([shutil.which('powershell.exe'), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(BOOTSTRAP), '-DownloadsDir', str(downloads), '-WorkDir', str(tmp_path), '-Target', str(target), '-ManifestPath', str(manifest), '-NoLaunch'], capture_output=True, timeout=30, cwd=Path(os.environ['SystemRoot']) / 'System32')
    return result, target


def test_approved_duplicate_named_zip_installs_and_honors_no_launch(tmp_path):
    result, target = run_bootstrap(tmp_path)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (target / 'installed.txt').exists()
    assert not list(tmp_path.glob('MirabelVoiceInstall-*'))


@pytest.mark.parametrize('options', [{'approved':False}, {'traversal':True}, {'tampered':True}])
def test_rejected_zip_never_executes_its_installer(tmp_path, options):
    result, target = run_bootstrap(tmp_path, **options)
    assert result.returncode != 0
    assert not target.exists()
    assert not (tmp_path / 'escaped.txt').exists()
    assert not list(tmp_path.glob('MirabelVoiceInstall-*'))


def test_mixed_zip_separators_and_long_paths_from_system32(tmp_path):
    result, target = run_bootstrap(tmp_path, nested=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (target / 'installed.txt').exists()
    assert not list(tmp_path.glob('MirabelVoiceInstall-*'))
