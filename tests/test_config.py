import json

from mirabel_voice.config import Config, load_api_keys


def test_load_writes_defaults_when_no_file_exists(tmp_path):
    target = tmp_path / "config.json"
    config = Config.load(target)
    assert target.exists()
    assert config.hotkey == "insert"
    assert config.mode == "toggle"
    assert config.cleanup_enabled is True
    assert config.cleanup_model == "claude-haiku-4-5"
    assert config.paste_last_hotkey == "shift+alt+z"
    # Insert has no modifier in it, so the words can type themselves
    # straight into the text box.
    assert config.live_insert is True
    # The live view costs about six times more per minute, so it ships off.
    # live_insert and show_overlay do nothing until someone turns it on.
    assert config.streaming_enabled is False


def test_save_and_load_round_trip(tmp_path):
    target = tmp_path / "config.json"
    Config(hotkey="f9", mode="toggle", custom_words=["Mirabel", "Whisper"]).save(target)
    config = Config.load(target)
    assert config.hotkey == "f9"
    assert config.mode == "toggle"
    assert config.custom_words == ["Mirabel", "Whisper"]


def test_keys_file_fills_missing_environment_variables(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "keys.json").write_text(
        json.dumps({"openai_api_key": "sk-test-1", "anthropic_api_key": "sk-ant-2"}),
        encoding="utf-8",
    )
    load_api_keys(tmp_path)
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-test-1"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-2"


def test_environment_variables_win_over_the_keys_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    (tmp_path / "keys.json").write_text(
        json.dumps({"openai_api_key": "sk-from-file"}), encoding="utf-8"
    )
    load_api_keys(tmp_path)
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-from-env"


def test_keys_written_by_powershell_with_a_bom_still_load(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = json.dumps({"openai_api_key": "sk-bom"}).encode("utf-8")
    (tmp_path / "keys.json").write_bytes(b"\xef\xbb\xbf" + payload)
    load_api_keys(tmp_path)
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-bom"


def test_a_missing_keys_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    load_api_keys(tmp_path)


def test_load_ignores_unknown_keys(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"hotkey": "f8", "colour_of_the_moon": "grey"}', encoding="utf-8")
    config = Config.load(target)
    assert config.hotkey == "f8"
    assert not hasattr(config, "colour_of_the_moon")
