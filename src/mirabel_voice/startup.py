"""Current-user Windows startup preference, no administrator access required."""
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

BYPASS = '-ExecutionPolicy Bypass'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
CREATE_NO_WINDOW = 0x08000000

# Rewrites a shortcut that runs Launch.ps1 without the bypass. Given no
# folders it looks where the installer writes: the Start menu and the
# Desktop, which may live under OneDrive, so Windows resolves them.
REPAIR_SHORTCUTS = r"""
param([string[]]$Folders)
if (-not $Folders -or $Folders.Count -eq 0) {
    $Folders = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))
}
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $Folders) {
    $path = Join-Path $folder 'Mirabel Voice.lnk'
    if (-not (Test-Path $path)) { continue }
    $link = $shell.CreateShortcut($path)
    if ($link.Arguments -like '*Launch.ps1*' -and $link.Arguments -notlike '*-ExecutionPolicy Bypass*') {
        $link.Arguments = '-NoProfile -ExecutionPolicy Bypass ' + ($link.Arguments -replace '^\s*-NoProfile\s*', '')
        $link.Save()
        Write-Output $path
    }
}
"""


def set_enabled(enabled):
    import winreg
    key_path = RUN_KEY
    root = Path(sys.executable).parent.parent
    launcher = root / 'Launch.ps1'
    if launcher.exists():
        # Bypass is per process: the Windows default policy refuses the
        # unsigned launch script, silently, under a hidden window.
        command = subprocess.list2cmdline(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', str(launcher)])
    else:
        exe = str(Path(sys.executable).with_name('pythonw.exe')) if not getattr(sys, 'frozen', False) else sys.executable
        command = subprocess.list2cmdline([exe] + ([] if getattr(sys, 'frozen', False) else ['-m', 'mirabel_voice']))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enabled:
            winreg.SetValueEx(key, 'Mirabel Voice', 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, 'Mirabel Voice')
            except FileNotFoundError:
                pass
    # Migrate legacy shortcut-based startup to avoid duplicate launchers.
    import os
    old = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/Mirabel Voice.lnk'
    old.unlink(missing_ok=True)


def _run_key_value():
    """The current Start with Windows command, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, 'Mirabel Voice')
            return value
    except OSError:
        return None


def repair_launch_entries(folders=None, run=subprocess.run):
    """Rewrite launch entries written before the bypass. Return what changed.

    Installs before 0.9.4 wrote shortcuts and the Start with Windows entry
    without the per-process bypass. On a computer with the Windows default
    execution policy those entries silently do nothing, and a source
    update cannot reach them, so the running app repairs them itself.
    Best effort: nothing here may stop the app from starting.
    """
    changed = []
    try:
        launcher = Path(sys.executable).parent.parent / 'Launch.ps1'
        if not launcher.exists():
            return changed  # a developer checkout has no launch script
        value = _run_key_value()
        if value and 'Launch.ps1' in value and BYPASS not in value:
            set_enabled(True)
            changed.append('Start with Windows')
        with tempfile.NamedTemporaryFile('w', suffix='.ps1', delete=False, encoding='utf-8') as script:
            script.write(REPAIR_SHORTCUTS)
        try:
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script.name]
            if folders:
                command += ['-Folders'] + [str(f) for f in folders]
            result = run(command, capture_output=True, text=True, timeout=30,
                         creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0)
            changed += [line.strip() for line in (result.stdout or '').splitlines() if line.strip()]
        finally:
            Path(script.name).unlink(missing_ok=True)
        if changed:
            log.info('Repaired launch entries written before the bypass: %s.', ', '.join(changed))
    except Exception:  # noqa: BLE001 - a repair must never block the start
        log.exception('The launch entry repair failed.')
    return changed
