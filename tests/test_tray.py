"""The tray menu wiring.

The app-level tests call set_language directly. These tests go through
pystray itself, because pystray calls every action as action(icon, item)
and adapts only callables that expose __code__. A wiring that survives
its own unit test can still break under that convention - the Language
menu did exactly that with a functools.partial.
"""

from types import SimpleNamespace

from mirabel_voice.tray import Tray


class FakeApp:
    """The slice of VoiceApp that the tray touches."""

    def __init__(self):
        self.config = SimpleNamespace(
            language="en",
            relay_url=None,
            relay_token=None,
            cleanup_enabled=True,
            translate_to_english=False,
            input_device=None,
            hotkey="insert",
        )
        self.signin = None
        self.state = "idle"
        self.last_text = ""
        self.chosen = []
        self.translated = []
        self.devices = []

    def set_language(self, code):
        self.chosen.append(code)
        self.config.language = code

    def set_translate(self, on):
        self.translated.append(on)
        self.config.translate_to_english = on

    def set_input_device(self, index):
        self.devices.append(index)
        self.config.input_device = index


def test_clicking_a_language_entry_reaches_set_language():
    tray = Tray(app=FakeApp())
    item = tray._language_item("Telugu", "te")
    # This is the exact call pystray makes on a click: the item receives
    # the icon and passes (icon, item) on to the action.
    item(None)
    assert tray.app.chosen == ["te"]
    assert tray.app.config.language == "te"


def test_the_clicked_entry_shows_as_chosen():
    tray = Tray(app=FakeApp())
    telugu = tray._language_item("Telugu", "te")
    english = tray._language_item("English", "en")
    telugu(None)
    assert telugu.checked
    assert not english.checked


def test_detect_automatically_passes_none():
    tray = Tray(app=FakeApp())
    item = tray._language_item("Detect automatically", None)
    item(None)
    assert tray.app.chosen == [None]


def test_clicking_translate_reaches_set_translate():
    tray = Tray(app=FakeApp())
    item = tray._translate_item()
    item(None)
    assert tray.app.translated == [True]
    item(None)
    assert tray.app.translated == [True, False]


def test_the_translate_entry_shows_its_state():
    tray = Tray(app=FakeApp())
    item = tray._translate_item()
    assert not item.checked
    item(None)
    assert item.checked


def test_the_cleanup_toggle_is_gone_and_translate_lives_under_language():
    """v0.6.4 cut the cleanup toggle - with translate on it sat greyed
    and looked unchecked - and moved translate into the Language menu,
    where the two settings that shape the text sit together."""
    menu = Tray(app=FakeApp())._menu()
    top = [str(item.text) for item in menu.items]
    assert "Clean up with Claude" not in top
    assert "Translate to English" not in top
    language = next(item for item in menu.items if str(item.text) == "Language")
    inner = [str(item.text) for item in language.submenu.items]
    assert "Translate to English" in inner


def test_clicking_a_microphone_reaches_set_input_device():
    tray = Tray(app=FakeApp())
    item = tray._microphone_item("Blue Yeti", 5)
    item(None)
    assert tray.app.devices == [5]
    assert tray.app.config.input_device == 5


def test_system_default_passes_none():
    tray = Tray(app=FakeApp())
    item = tray._microphone_item("System default", None)
    item(None)
    assert tray.app.devices == [None]


def test_the_chosen_microphone_shows_as_chosen():
    tray = Tray(app=FakeApp())
    yeti = tray._microphone_item("Blue Yeti", 5)
    default = tray._microphone_item("System default", None)
    yeti(None)
    assert yeti.checked
    assert not default.checked


def test_the_microphone_menu_shows_each_device_once(monkeypatch):
    """Windows lists a microphone once per audio API. The menu keeps
    the WASAPI entries, which carry full names, and drops the rest."""
    monkeypatch.setattr(
        "mirabel_voice.audio.list_input_devices",
        lambda: [
            {"index": 1, "name": "Microphone (Blue Yeti", "channels": 2, "hostapi": "MME"},
            {"index": 5, "name": "Microphone (Blue Yeti)", "channels": 2, "hostapi": "Windows WASAPI"},
        ],
    )
    submenu = Tray(app=FakeApp())._microphone_menu().submenu
    labels = [str(item.text) for item in submenu.items]
    assert labels == ["System default", "Microphone (Blue Yeti)"]


def test_a_broken_device_listing_still_offers_the_default(monkeypatch):
    def boom():
        raise RuntimeError("no sound device")

    monkeypatch.setattr("mirabel_voice.audio.list_input_devices", boom)
    submenu = Tray(app=FakeApp())._microphone_menu().submenu
    labels = [str(item.text) for item in submenu.items]
    assert labels == ["System default"]
