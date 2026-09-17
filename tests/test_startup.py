"""The Start with Windows entry, without touching the real registry."""
import sys
from types import SimpleNamespace

from mirabel_voice import startup


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_winreg(written):
    def set_value(key, name, reserved, kind, value):
        written[name] = value

    def delete_value(key, name):
        written.pop(name)

    return SimpleNamespace(
        HKEY_CURRENT_USER=object(), REG_SZ=1,
        CreateKey=lambda root, path: FakeKey(),
        SetValueEx=set_value, DeleteValue=delete_value,
    )


def test_start_with_windows_bypasses_the_execution_policy(monkeypatch, tmp_path):
    # Restricted is the Windows default. Without a per-process bypass the
    # entry runs at every sign-in and silently does nothing.
    written = {}
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg(written))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "Mirabel Voice"
    (root / "python").mkdir(parents=True)
    (root / "Launch.ps1").write_text("# launcher")
    monkeypatch.setattr(sys, "executable", str(root / "python" / "python.exe"))

    startup.set_enabled(True)
    command = written["Mirabel Voice"]
    assert command.startswith("powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ")
    assert command.endswith('Launch.ps1"')

    startup.set_enabled(False)
    assert "Mirabel Voice" not in written
