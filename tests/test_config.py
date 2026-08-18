from mirabel_voice.config import Config


def test_load_writes_defaults_when_no_file_exists(tmp_path):
    target = tmp_path / "config.json"
    config = Config.load(target)
    assert target.exists()
    assert config.hotkey == "ctrl_r"
    assert config.mode == "hold"
    assert config.cleanup_enabled is True


def test_save_and_load_round_trip(tmp_path):
    target = tmp_path / "config.json"
    Config(hotkey="f9", mode="toggle", custom_words=["Mirabel", "Whisper"]).save(target)
    config = Config.load(target)
    assert config.hotkey == "f9"
    assert config.mode == "toggle"
    assert config.custom_words == ["Mirabel", "Whisper"]


def test_load_ignores_unknown_keys(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"hotkey": "f8", "colour_of_the_moon": "grey"}', encoding="utf-8")
    config = Config.load(target)
    assert config.hotkey == "f8"
    assert not hasattr(config, "colour_of_the_moon")
