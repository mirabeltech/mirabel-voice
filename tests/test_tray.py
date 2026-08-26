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
            hotkey="insert",
        )
        self.signin = None
        self.state = "idle"
        self.last_text = ""
        self.chosen = []

    def set_language(self, code):
        self.chosen.append(code)
        self.config.language = code


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
