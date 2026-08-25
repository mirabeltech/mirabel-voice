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


# --- the one-token installer -----------------------------------------------

INSTALLER = (PACKAGING / "installer.iss").read_text(encoding="utf-8")


def test_set_relay_stores_the_address_and_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    from mirabel_voice.config import Config

    assert entry.main(["--set-relay", "https://relay.example.on.aws", "a-token"]) == 0

    saved = Config.load(tmp_path / "config.json")
    assert saved.relay_url == "https://relay.example.on.aws"
    assert saved.relay_token == "a-token"


def test_set_relay_keeps_every_other_setting(tmp_path, monkeypatch):
    # An update install must not cost somebody their dictation key or
    # their custom words.
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    from mirabel_voice.config import Config

    Config(hotkey="scroll_lock", custom_words=["Mirabel"], play_sounds=False).save(
        tmp_path / "config.json"
    )

    entry.main(["--set-relay", "https://relay.example.on.aws", "a-token"])

    saved = Config.load(tmp_path / "config.json")
    assert saved.hotkey == "scroll_lock"
    assert saved.custom_words == ["Mirabel"]
    assert saved.play_sounds is False
    assert saved.relay_token == "a-token"


def test_an_empty_token_clears_the_stored_one(tmp_path, monkeypatch):
    # The installer clears a refused token so that running it again asks
    # for the token instead of skipping the page.
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    from mirabel_voice.config import Config

    entry.main(["--set-relay", "https://relay.example.on.aws", "wrong-token"])
    entry.main(["--set-relay", "https://relay.example.on.aws", ""])

    assert not Config.load(tmp_path / "config.json").relay_token


def test_the_installer_asks_for_exactly_one_thing():
    assert INSTALLER.count("TokenPage.Add(") == 1


def test_the_installer_no_longer_touches_provider_keys():
    assert "keys.json" not in INSTALLER
    assert "openai_api_key" not in INSTALLER
    assert "anthropic_api_key" not in INSTALLER


def test_the_installer_stores_the_token_through_the_app():
    # Writing config.json from Inno would overwrite the other settings.
    assert "--set-relay" in INSTALLER
    assert "--check-keys" in INSTALLER


def test_a_build_without_a_relay_address_fails_loudly():
    assert "#ifndef RelayUrl" in INSTALLER
    assert "#error" in INSTALLER


def test_the_address_can_be_set_without_the_token(tmp_path, monkeypatch):
    # An update install knows the relay's address but not the token that
    # is already stored, and must not wipe it.
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    from mirabel_voice.config import Config

    entry.main(["--set-relay", "https://old.example.on.aws", "a-token"])
    entry.main(["--set-relay", "https://new.example.on.aws"])

    saved = Config.load(tmp_path / "config.json")
    assert saved.relay_url == "https://new.example.on.aws"
    assert saved.relay_token == "a-token"


ZIP_INSTALLER = (PACKAGING / "Install.ps1").read_text(encoding="utf-8")


def test_the_token_probe_reports_whether_one_is_stored(tmp_path, monkeypatch):
    # Both installers ask this before deciding whether to prompt.
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))

    assert entry.main(["--has-relay-token"]) == 1

    entry.main(["--set-relay", "https://relay.example.on.aws", "a-token"])
    assert entry.main(["--has-relay-token"]) == 0

    entry.main(["--set-relay", "https://relay.example.on.aws", ""])
    assert entry.main(["--has-relay-token"]) == 1


def test_the_zip_installer_stores_the_token_through_the_app():
    assert "--set-relay" in ZIP_INSTALLER
    assert "--check-keys" in ZIP_INSTALLER
    assert "--has-relay-token" in ZIP_INSTALLER


def test_the_zip_installer_takes_the_address_from_the_build():
    # build.ps1 substitutes this. A zip that shipped the placeholder would
    # send every dictation nowhere.
    assert "__RELAY_URL__" in ZIP_INSTALLER
    assert "http" not in ZIP_INSTALLER.replace("__RELAY_URL__", "")


def test_both_installers_clear_a_refused_token_with_a_flag():
    # An empty argument does not survive PowerShell on its way to a
    # program, which once left a refused token stored.
    assert "--forget-relay-token" in ZIP_INSTALLER
    assert "--forget-relay-token" in INSTALLER


def test_forgetting_the_token_keeps_every_other_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    from mirabel_voice.config import Config

    Config(hotkey="scroll_lock", relay_url="https://relay.example.on.aws",
           relay_token="a-token").save(tmp_path / "config.json")

    assert entry.main(["--forget-relay-token"]) == 0

    saved = Config.load(tmp_path / "config.json")
    assert saved.relay_token is None
    assert saved.relay_url == "https://relay.example.on.aws"
    assert saved.hotkey == "scroll_lock"


def test_one_installer_serves_both_downloads():
    # The packaged program and the Python bundle ship the same script.
    # Two copies of it would drift.
    assert "MirabelVoice.exe" in ZIP_INSTALLER
    assert "pythonw.exe" in ZIP_INSTALLER
    assert "-m" in ZIP_INSTALLER


def test_the_bundle_build_insists_on_a_valid_signature():
    # The bundle's whole reason to exist is that its interpreter is
    # signed. A build that shipped an unsigned one would be pointless.
    build = (PACKAGING / "build_bundle.ps1").read_text(encoding="utf-8")
    assert "Get-AuthenticodeSignature" in build
    assert '$signature.Status -ne "Valid"' in build


BOOTSTRAP = (PACKAGING.parent / "install.ps1").read_text(encoding="utf-8")


def test_the_bootstrap_unblocks_the_zip_before_unpacking_it():
    # The whole point of the pasted line: the Properties/Unblock and
    # Extract steps happen in the right order without anybody clicking.
    assert BOOTSTRAP.index("Unblock-File $zip.FullName") < BOOTSTRAP.index(
        "Expand-Archive $zip.FullName"
    )


def test_the_bootstrap_runs_the_installer_past_the_execution_policy():
    # The extracted Install.ps1 is unsigned; without Bypass a machine on
    # the default policy stops right after the unpack.
    assert "-ExecutionPolicy Bypass" in BOOTSTRAP


def test_the_bootstrap_carries_no_relay_address():
    # It lives in a public repository. Every address in it must be one
    # that is public already.
    import re

    for url in re.findall(r"https?://[^\s\"')]+", BOOTSTRAP):
        assert url.startswith(
            (
                "https://raw.githubusercontent.com/",
                "https://drive.google.com/",
                "https://api.github.com/repos/mirabeltech/",
                "https://github.com/mirabeltech/",
            )
        ), url


def test_the_bootstrap_updates_an_installed_bundle_from_the_releases():
    # An installed machine already holds the relay address, and the code
    # is public, so an update needs no zip and no shared drive.
    assert "releases/latest" in BOOTSTRAP
    assert "site-packages" in BOOTSTRAP


def test_the_update_proves_the_app_answers_or_puts_the_old_code_back():
    # A release that needs a new library must not leave a broken install:
    # the swap out comes first, the swap back stands ready after it.
    assert "--config" in BOOTSTRAP
    assert BOOTSTRAP.index("Move-Item $installed $backup") < BOOTSTRAP.index(
        "Move-Item $backup $installed"
    )
