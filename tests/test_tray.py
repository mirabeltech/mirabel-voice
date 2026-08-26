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
            hotkey="insert",
        )
        self.signin = None
        self.state = "idle"
        self.last_text = ""
        self.chosen = []
        self.translated = []

    def set_language(self, code):
        self.chosen.append(code)
        self.config.language = code

    def set_translate(self, on):
        self.translated.append(on)
        self.config.translate_to_english = on


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


def test_translate_on_shows_the_cleanup_as_running_and_locked():
    # Translation lives in the cleanup pass, so with translate on the
    # pass always runs. The cleanup entry must say so, not show an
    # unchecked box whose click would change nothing.
    app = FakeApp()
    app.config.cleanup_enabled = False
    app.config.translate_to_english = True
    item = Tray(app=app)._cleanup_item()
    assert item.checked
    assert not item.enabled


def test_translate_off_gives_the_cleanup_entry_back():
    app = FakeApp()
    app.config.cleanup_enabled = False
    item = Tray(app=app)._cleanup_item()
    assert not item.checked
    assert item.enabled
