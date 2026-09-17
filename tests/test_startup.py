"""The Start with Windows entry, without touching the real registry."""
import sys
from types import SimpleNamespace

import pytest

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

    def query(key, name):
        if name not in written:
            raise FileNotFoundError(name)
        return written[name], 1

    return SimpleNamespace(
        HKEY_CURRENT_USER=object(), REG_SZ=1,
        CreateKey=lambda root, path: FakeKey(), OpenKey=lambda root, path: FakeKey(),
        SetValueEx=set_value, DeleteValue=delete_value, QueryValueEx=query,
    )


def installed_app(monkeypatch, tmp_path, written):
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg(written))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "Mirabel Voice"
    (root / "python").mkdir(parents=True)
    (root / "Launch.ps1").write_text("# launcher")
    monkeypatch.setattr(sys, "executable", str(root / "python" / "python.exe"))
    return root


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


# --- the running app repairs entries written before the bypass -------------


def no_shortcuts(command, **kwargs):
    return SimpleNamespace(stdout="", returncode=0)


def test_an_old_start_with_windows_entry_is_rewritten_on_start(monkeypatch, tmp_path):
    written = {}
    root = installed_app(monkeypatch, tmp_path, written)
    written["Mirabel Voice"] = f'powershell.exe -NoProfile -WindowStyle Hidden -File "{root / "Launch.ps1"}"'
    changed = startup.repair_launch_entries(run=no_shortcuts)
    assert changed == ["Start with Windows"]
    assert "-ExecutionPolicy Bypass" in written["Mirabel Voice"]


def test_a_repaired_or_absent_entry_is_left_alone(monkeypatch, tmp_path):
    written = {}
    root = installed_app(monkeypatch, tmp_path, written)
    assert startup.repair_launch_entries(run=no_shortcuts) == []
    assert "Mirabel Voice" not in written  # an absent entry means "off"; respect it
    good = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{root / "Launch.ps1"}"'
    written["Mirabel Voice"] = good
    assert startup.repair_launch_entries(run=no_shortcuts) == []
    assert written["Mirabel Voice"] == good


def test_a_developer_checkout_repairs_nothing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv" / "python.exe"))
    assert startup.repair_launch_entries(run=lambda *a, **k: calls.append(a)) == []
    assert calls == []


def test_the_shortcut_repair_runs_powershell_with_the_bypass(monkeypatch, tmp_path):
    written = {}
    installed_app(monkeypatch, tmp_path, written)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="C:\\Users\\x\\Desktop\\Mirabel Voice.lnk\n", returncode=0)

    changed = startup.repair_launch_entries(folders=[tmp_path], run=run)
    assert changed == ["C:\\Users\\x\\Desktop\\Mirabel Voice.lnk"]
    command = calls[0]
    assert command[:5] == ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert command[6:] == ["-Folders", str(tmp_path)]


def test_a_failing_repair_never_raises(monkeypatch, tmp_path):
    written = {}
    installed_app(monkeypatch, tmp_path, written)

    def explode(*args, **kwargs):
        raise OSError("no powershell")

    assert startup.repair_launch_entries(run=explode) == []


@pytest.mark.skipif(sys.platform != "win32", reason="edits a real .lnk through Windows")
def test_a_real_old_shortcut_gets_the_bypass(monkeypatch, tmp_path):
    import subprocess

    written = {}
    root = installed_app(monkeypatch, tmp_path, written)
    folder = tmp_path / "menu"
    folder.mkdir()
    link = folder / "Mirabel Voice.lnk"
    make = (
        "$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut('" + str(link) + "'); "
        "$l.TargetPath = 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe'; "
        "$l.Arguments = '-NoProfile -WindowStyle Hidden -File \"" + str(root / "Launch.ps1") + "\"'; $l.Save()"
    )
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", make], check=True, capture_output=True)

    changed = startup.repair_launch_entries(folders=[folder])
    assert changed == [str(link)]

    read = "$s = New-Object -ComObject WScript.Shell; $s.CreateShortcut('" + str(link) + "').Arguments"
    arguments = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", read], check=True, capture_output=True, text=True).stdout.strip()
    assert arguments == '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + str(root / "Launch.ps1") + '"'
    assert startup.repair_launch_entries(folders=[folder]) == []  # second run: nothing left to fix
