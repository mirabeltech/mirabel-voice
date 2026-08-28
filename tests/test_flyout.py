"""The controls flyout, and the tray menu that shrinks beside it.

The window itself gets one real-Tk smoke test, like the status panel.
Everything else - the choices offered, the key capture, the menu
shapes - is logic, and runs without a desktop.
"""

import threading
from types import SimpleNamespace

import pytest

from mirabel_voice import flyout as card
from mirabel_voice.config import LANGUAGES
from mirabel_voice.tray import Tray


class FakeApp:
    """The slice of VoiceApp the flyout and the tray touch."""

    def __init__(self):
        self.config = SimpleNamespace(
            language="en",
            relay_url=None,
            relay_token=None,
            cleanup_enabled=True,
            translate_to_english=False,
            input_device=None,
            hotkey="insert",
            mode="toggle",
        )
        self.signin = None
        self.state = "idle"
        self.last_text = ""
        self.hotkeys = []
        self.suspended = 0
        self.resumed = 0

    def set_hotkey(self, key):
        self.hotkeys.append(key)
        self.config.hotkey = key

    def suspend_hotkeys(self):
        self.suspended += 1

    def resume_hotkeys(self):
        self.resumed += 1


class FakeOverlay:
    """Runs queued UI actions at once, on this thread."""

    def call(self, action):
        action()


# --- the choices the card offers -------------------------------------------


def test_the_language_choices_mirror_the_menu():
    names = card.language_names()
    assert names[0] == card.AUTO_DETECT
    assert set(names[1:]) == {label for _, label in LANGUAGES}
    assert card.language_code(card.AUTO_DETECT) is None
    assert card.language_code("Telugu") == "te"


def test_the_microphone_choices_show_each_device_once():
    devices = [
        {"index": 1, "name": "Microphone (Blue Yeti", "hostapi": "MME"},
        {"index": 5, "name": "Microphone (Blue Yeti)", "hostapi": "Windows WASAPI"},
    ]
    assert card.microphone_names(devices) == [
        card.SYSTEM_DEFAULT,
        "Microphone (Blue Yeti)",
    ]


def test_no_devices_still_offers_the_default():
    assert card.microphone_names([]) == [card.SYSTEM_DEFAULT]


# --- the key capture --------------------------------------------------------


def capture_flyout():
    flyout = card.Flyout(FakeOverlay(), FakeApp())
    flyout._capturing = True
    flyout._widgets = {
        "change": SimpleNamespace(configure=lambda **kwargs: None),
    }
    flyout._show_state = lambda: None
    return flyout


def test_a_captured_key_becomes_the_hotkey():
    flyout = capture_flyout()
    flyout._end_capture("f13")
    assert flyout.app.hotkeys == ["f13"]
    assert not flyout._capturing


def test_escape_keeps_the_old_key_and_resumes_listening():
    # The suspend happened at capture start; Esc must undo it, or the
    # dictation key is dead until a restart.
    flyout = capture_flyout()
    flyout._end_capture(None)
    assert flyout.app.hotkeys == []
    assert flyout.app.resumed == 1


def test_a_refused_key_keeps_the_old_one_and_resumes_listening():
    flyout = capture_flyout()

    def refuse(key):
        raise ValueError("not a key")

    flyout.app.set_hotkey = refuse
    flyout._end_capture("definitely-not-a-key")
    assert flyout.app.resumed == 1
    assert not flyout._capturing


# --- the menu beside the card ----------------------------------------------


def test_with_a_flyout_the_menu_shrinks_to_the_windows_minimum():
    tray = Tray(app=FakeApp(), flyout=object())
    labels = [str(item.text) for item in tray._menu().items]
    named = [
        t
        for t in labels
        if t and "Mirabel Voice" not in t and set(t) != {"-", " "}
    ]
    assert named == [
        "Open controls",
        "Check for updates",
        "Open the settings folder",
        "Quit",
    ]


def test_open_controls_is_the_default_action():
    # pystray runs the default item on a left-click of the icon: the
    # flyout must open without the menu.
    tray = Tray(app=FakeApp(), flyout=object())
    item = next(
        item for item in tray._menu().items if str(item.text) == "Open controls"
    )
    assert item.default


def test_without_a_flyout_the_full_menu_stays():
    # No Tkinter means no flyout. The everyday controls must not
    # disappear with it.
    tray = Tray(app=FakeApp(), flyout=None)
    labels = [str(item.text) for item in tray._menu().items]
    assert "Language" in labels
    assert "Microphone" in labels
    assert "Open controls" not in labels


def test_clicking_open_controls_shows_the_card():
    shown = []
    flyout = SimpleNamespace(show=lambda: shown.append(True))
    tray = Tray(app=FakeApp(), flyout=flyout)
    item = next(
        item for item in tray._menu().items if str(item.text) == "Open controls"
    )
    item(None)
    assert shown == [True]


# --- the hint follows the mode ---------------------------------------------


def test_the_hint_says_tap_in_toggle_mode():
    config = SimpleNamespace(hotkey="insert", mode="toggle")
    assert card.idle_hint(config) == "Tap insert to start and stop · Esc cancels"


def test_the_hint_says_hold_in_hold_mode():
    config = SimpleNamespace(hotkey="f13", mode="hold")
    assert card.idle_hint(config) == "Hold f13 to dictate · Esc cancels"


# --- the app side of the key swap ------------------------------------------


def test_set_hotkey_restarts_the_listener_with_the_new_key(monkeypatch, tmp_path):
    from mirabel_voice.app import VoiceApp
    from mirabel_voice.config import Config

    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))

    class FakeListener:
        def __init__(self, hotkey):
            self.hotkey = hotkey
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

    made = []
    config = Config(play_sounds=False)
    app = VoiceApp.__new__(VoiceApp)
    app.config = config
    app.state = "idle"
    app._on_state = None
    app.on_status = None
    app._listener = None
    app._hotkeys_suspended = False
    app._listener_lock = threading.Lock()
    app._stopped = False

    def make():
        listener = FakeListener(config.hotkey)
        made.append(listener)
        return listener

    app._make_listener = make

    # Not started yet: the swap saves the key and starts nothing.
    app.set_hotkey("f13")
    assert config.hotkey == "f13"
    assert made == []
    assert Config.load().hotkey == "f13"

    # Running: the swap rebuilds the listener with the new key.
    app._listener = make()
    app._listener.start()
    old = app._listener
    app.set_hotkey("scroll_lock")
    assert not old.running
    assert app._listener is not old
    assert app._listener.hotkey == "scroll_lock"
    assert app._listener.running


def test_a_bad_key_is_refused_before_anything_changes(monkeypatch, tmp_path):
    from mirabel_voice.app import VoiceApp
    from mirabel_voice.config import Config
    from mirabel_voice.hotkey import UnknownHotkeyError

    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    app = VoiceApp.__new__(VoiceApp)
    app.config = Config(play_sounds=False, hotkey="insert")
    app._listener = None
    app._hotkeys_suspended = False

    with pytest.raises(UnknownHotkeyError):
        app.set_hotkey("not a real key name")
    assert app.config.hotkey == "insert"


def test_suspend_and_resume_bracket_a_capture(monkeypatch, tmp_path):
    from mirabel_voice.app import VoiceApp
    from mirabel_voice.config import Config

    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))

    class FakeListener:
        def __init__(self):
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

    app = VoiceApp.__new__(VoiceApp)
    app.config = Config(play_sounds=False)
    app.state = "idle"
    app._on_state = None
    app.on_status = None
    app._hotkeys_suspended = False
    app._listener_lock = threading.Lock()
    app._stopped = False
    app._make_listener = FakeListener
    app._listener = FakeListener()
    app._listener.start()

    app.suspend_hotkeys()
    assert app._listener is None
    app.resume_hotkeys()
    assert app._listener is not None
    assert app._listener.running

    # Resuming twice must not stack listeners.
    listener = app._listener
    app.resume_hotkeys()
    assert app._listener is listener


# --- the real window, once --------------------------------------------------


def test_the_card_really_builds_and_shows():
    pytest.importorskip("tkinter")
    from mirabel_voice.overlay import Overlay

    overlay = Overlay()
    assert overlay.start()
    try:
        flyout = card.Flyout(overlay, FakeApp())
        shown = []
        flyout.show()
        flyout.overlay.call(lambda: shown.append(flyout._top is not None))
        import time

        deadline = time.monotonic() + 5.0
        while not shown and time.monotonic() < deadline:
            time.sleep(0.05)
        assert shown == [True]
        flyout.hide()
    finally:
        overlay.stop()


# --- the review repairs ------------------------------------------------------


def test_capture_is_refused_while_a_recording_runs():
    # The listener carries the only stop for a live recording; tearing
    # it down mid-recording would strand the microphone open.
    flyout = card.Flyout(FakeOverlay(), FakeApp())
    flyout.app.state = "recording"
    hints = []
    flyout._widgets = {
        "hint": SimpleNamespace(configure=lambda **kwargs: hints.append(kwargs)),
    }
    flyout._begin_capture()
    assert not flyout._capturing
    assert flyout.app.suspended == 0
    assert hints  # the card said why


def test_a_dead_card_still_gives_the_keyboard_back():
    # The hotkeys must come back even when the widgets died while the
    # capture waited - a KeyError here used to leave dictation dead.
    flyout = card.Flyout(FakeOverlay(), FakeApp())
    flyout._capturing = True
    flyout._widgets = {}
    flyout._end_capture(None)
    assert flyout.app.resumed == 1


def test_a_second_delivery_does_not_end_the_capture_twice():
    flyout = capture_flyout()
    flyout._end_capture(None)
    flyout._end_capture("f13")  # a late duplicate delivery
    assert flyout.app.resumed == 1
    assert flyout.app.hotkeys == []


def test_the_microphone_choices_keep_name_and_index_together():
    # The same name often exists under several audio APIs with
    # different indexes; resolving a bare name against the full list
    # saved the wrong backend.
    devices = [
        {"index": 1, "name": "Krisp Microphone", "hostapi": "MME"},
        {"index": 9, "name": "Krisp Microphone", "hostapi": "Windows DirectSound"},
        {"index": 21, "name": "Krisp Microphone", "hostapi": "Windows WASAPI"},
    ]
    assert card.microphone_choices(devices) == [
        (card.SYSTEM_DEFAULT, None),
        ("Krisp Microphone", 21),
    ]


def test_stopping_the_app_clears_a_pending_suspend(monkeypatch, tmp_path):
    # A key capture that ends after the quit must not restart the
    # keyboard hook on a dead app.
    from mirabel_voice.app import VoiceApp
    from mirabel_voice.config import Config

    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    app = VoiceApp.__new__(VoiceApp)
    app.config = Config(play_sounds=False)
    app.state = "idle"
    app._on_state = None
    app.on_status = None
    app._listener = None
    app._dispatch_thread = None
    app._hotkeys_suspended = True
    app._listener_lock = threading.Lock()
    app._stopped = False
    app.recorder = SimpleNamespace(is_recording=False, cancel=lambda: None)

    app.stop()
    assert app._hotkeys_suspended is False

    # The race this guards: a resume that lands after the quit must not
    # install the keyboard hook on a stopped app.
    app._hotkeys_suspended = True
    resumed = []
    app._make_listener = lambda: resumed.append(True) or SimpleNamespace(
        start=lambda: None, stop=lambda: None
    )
    app.resume_hotkeys()
    assert resumed == []
    assert app._listener is None

    made = []
    app._make_listener = lambda: made.append(True) or SimpleNamespace(
        start=lambda: None, stop=lambda: None
    )
    app.set_hotkey("f13")
    assert made == []  # saved the key, started nothing


# --- the footer version (v0.7.1) --------------------------------------------


def test_the_version_comes_from_the_newest_marker_name(tmp_path):
    # The updater renames the dist-info folder on every source update
    # and never rewrites the METADATA inside - so the folder name is
    # the running version and the file is the originally installed one.
    (tmp_path / "mirabel_voice-0.5.1.dist-info").mkdir()
    (tmp_path / "mirabel_voice-0.7.1.dist-info").mkdir()
    assert card.version_from_markers(tmp_path) == "v0.7.1"


def test_no_markers_answer_nothing(tmp_path):
    assert card.version_from_markers(tmp_path) == ""
