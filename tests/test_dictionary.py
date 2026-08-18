from mirabel_voice.config import Config
from mirabel_voice.dictionary import all_words, seed_words


def test_the_seed_list_ships_with_the_package():
    words = seed_words()
    assert "ChargeBrite" in words
    assert "MagHub" in words
    assert "Magazine Manager" in words
    assert len(words) >= 10


def test_personal_words_merge_after_the_seed_list():
    merged = all_words(["Acme Publishing"])
    assert "ChargeBrite" in merged
    assert merged[-1] == "Acme Publishing"


def test_duplicates_are_removed_case_insensitively():
    merged = all_words(["chargebrite", "Acme"])
    lowered = [w.lower() for w in merged]
    assert lowered.count("chargebrite") == 1


def test_the_app_feeds_the_merged_list_to_both_models():
    config = Config(play_sounds=False, custom_words=["Acme Publishing"])
    from mirabel_voice.app import VoiceApp

    app = VoiceApp(config)
    assert "ChargeBrite" in app.transcriber.custom_words
    assert "Acme Publishing" in app.transcriber.custom_words
    assert "ChargeBrite" in app.cleaner.custom_words
    assert "Acme Publishing" in app.cleaner.custom_words


def test_the_app_passes_the_language_setting_to_the_transcriber():
    config = Config(play_sounds=False, language="hi")
    from mirabel_voice.app import VoiceApp

    app = VoiceApp(config)
    assert app.transcriber.language == "hi"
