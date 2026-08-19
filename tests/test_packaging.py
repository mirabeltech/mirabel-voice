"""Tests for the pieces the packaged installer depends on.

The installed app has no scripts folder and no .venv beside it, so the
key check and the key picker have to live in the package itself.
"""

import sys
from pathlib import Path

import pytest

from mirabel_voice import __main__ as entry
from mirabel_voice import picker, tray

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"
sys.path.insert(0, str(PACKAGING))

import prepare  # noqa: E402


def test_a_plain_key_turns_live_typing_on(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    monkeypatch.setattr(picker, "config_path", lambda: target)

    previous, live = picker.save_choice("scroll_lock")

    assert live is True
    assert previous == "insert"  # the default the file was written with
    from mirabel_voice.config import Config

    saved = Config.load(target)
    assert saved.hotkey == "scroll_lock"
    assert saved.live_insert is True


def test_a_modifier_key_turns_live_typing_off(tmp_path, monkeypatch):
    # Windows refuses typed characters while a modifier is held, so the
    # picker must never leave live typing on for such a key.
    target = tmp_path / "config.json"
    monkeypatch.setattr(picker, "config_path", lambda: target)

    _, live = picker.save_choice("ctrl_r")

    assert live is False
    from mirabel_voice.config import Config

    assert Config.load(target).live_insert is False


def test_the_installed_app_runs_the_picker_from_its_console_twin(tmp_path, monkeypatch):
    exe = tmp_path / "MirabelVoice.exe"
    exe.write_text("")
    console = tmp_path / "MirabelVoiceConsole.exe"
    console.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))

    command = tray._picker_command()

    assert command == [str(console), "--pick-hotkey"]


def test_a_source_checkout_runs_the_picker_with_a_console_python(tmp_path, monkeypatch):
    # The app normally runs under pythonw.exe, which has no console for
    # the picker to print into. Its python.exe neighbour has one.
    pythonw = tmp_path / "pythonw.exe"
    pythonw.write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(pythonw))

    command = tray._picker_command()

    assert command == [str(tmp_path / "python.exe"), "-m", "mirabel_voice", "--pick-hotkey"]


def test_check_keys_reports_the_reason_and_the_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        "mirabel_voice.keycheck.check_keys",
        lambda: (False, "The OpenAI key was not accepted: bad key"),
    )

    code = entry.main(["--check-keys"])

    assert code == 1
    assert "not accepted" in capsys.readouterr().out


def test_check_keys_returns_zero_when_both_work(monkeypatch):
    monkeypatch.setattr(
        "mirabel_voice.keycheck.check_keys", lambda: (True, "Both keys work.")
    )
    assert entry.main(["--check-keys"]) == 0


def test_the_picker_flag_runs_the_picker(monkeypatch):
    called = []
    monkeypatch.setattr("mirabel_voice.picker.pick_hotkey", lambda: called.append(1) or 0)

    assert entry.main(["--pick-hotkey"]) == 0
    assert called == [1]


@pytest.mark.parametrize(
    ("version", "expected"),
    [("0.1.0", (0, 1, 0, 0)), ("1.2.3", (1, 2, 3, 0)), ("2.0", (2, 0, 0, 0))],
)
def test_the_windows_version_resource_needs_four_numbers(version, expected):
    assert prepare.version_parts(version) == expected


def test_the_installed_app_points_people_at_the_installer(monkeypatch):
    # A packaged copy has no setup.ps1, so the old message would send
    # people looking for a file that is not there.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert "installer" in entry._how_to_fix_keys()

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert "setup.ps1" in entry._how_to_fix_keys()
