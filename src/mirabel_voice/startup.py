"""Current-user Windows startup preference, no administrator access required."""
import subprocess
import sys
from pathlib import Path


def set_enabled(enabled):
    import winreg
    key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
    root = Path(sys.executable).parent.parent
    launcher = root / 'Launch.ps1'
    if launcher.exists():
        command = subprocess.list2cmdline(['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-File', str(launcher)])
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
