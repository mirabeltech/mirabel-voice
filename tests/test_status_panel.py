"""Tests for the panel that shows what the app is doing.

The window itself is not tested here. What it does is focus, z-order, and
click handling, and none of that can be judged without a real desktop.
What is tested is everything that decides what the window would show.
"""

import numpy as np

from fakes import FakeAnthropic, FakeOpenAI, text_response
from mirabel_voice import overlay as panel
from mirabel_voice.app import (
    INSERTED_PREFIX,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_WORKING,
    VoiceApp,
)
from mirabel_voice.audio import Recording
from mirabel_voice.cleanup import Cleaner
from mirabel_voice.config import Config
from mirabel_voice.transcribe import Transcriber
from mirabel_voice.tray import COLOURS


def loud_recording(seconds=2.0):
    samples = (np.ones(int(16000 * seconds)) * 8000).astype(np.int16)
    return Recording(samples=samples, sample_rate=16000)


class FakeRecorder:
    def __init__(self, recording):
        self.recording = recording
        self.recording_now = False

    @property
    def is_recording(self):
        return self.recording_now

    def start(self):
        self.recording_now = True

    def stop(self):
        self.recording_now = False
        return self.recording

    def cancel(self):
        self.recording_now = False


class CapturingInjector:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send(self, text):
        if self.error is not None:
            raise self.error
        self.sent.append(text)


def make_app(recording=None, transcript="um hello", cleaned="Hello.", injector=None,
             transcribe_error=None):
    config = Config(play_sounds=False)
    app = VoiceApp(
        config=config,
        recorder=FakeRecorder(recording or loud_recording()),
        transcriber=Transcriber(
            client=FakeOpenAI(text=transcript, error=transcribe_error)
        ),
        cleaner=Cleaner(client=FakeAnthropic(response=text_response(cleaned))),
        injector=injector if injector is not None else CapturingInjector(),
    )
    app._focus = lambda: 111
    app._focus_at_start = 111
    return app


def run_cycle(app):
    app.start_recording()
    app.stop_recording()
    if app._worker is not None:
        app._worker.join(timeout=5.0)


# --- what the panel is told ------------------------------------------------


def test_the_panel_follows_the_whole_cycle():
    # The point of the panel: something is on screen from the first press
    # until the text lands.
    seen = []
    app = make_app()
    app.on_status = lambda state, detail: seen.append(state)

    run_cycle(app)

    assert seen[0] == STATE_RECORDING
    assert STATE_WORKING in seen
    assert seen[-1] == STATE_IDLE


def test_the_panel_ships_on():
    # Unlike the live words, it costs nothing per minute, so it is on for
    # everybody rather than something to discover in a settings file.
    assert Config().show_status is True


def test_the_panel_is_silent_when_the_flag_is_off():
    app = make_app()
    run_cycle(app)  # on_status was never set
    assert app.on_status is None


def test_a_broken_panel_does_not_break_dictation():
    # The panel is decoration. It must never cost somebody their words.
    injector = CapturingInjector()
    app = make_app(injector=injector)

    def explode(state, detail):
        raise RuntimeError("the panel is on fire")

    app.on_status = explode
    run_cycle(app)

    assert injector.sent == ["Hello."]


def test_the_reason_reaches_the_panel_when_a_dictation_fails():
    seen = []
    app = make_app(transcribe_error=RuntimeError("no network"))
    app.on_status = lambda state, detail: seen.append((state, detail))

    run_cycle(app)

    failures = [detail for state, detail in seen if state == STATE_ERROR]
    assert failures and "no network" in failures[0]


# --- what the panel decides to show ----------------------------------------


def test_listening_and_writing_stay_until_the_state_changes():
    assert panel.status_line(STATE_RECORDING, "") == ("Listening", 0)
    assert panel.status_line(STATE_WORKING, "") == ("Writing your text", 0)


def test_a_delivered_dictation_shows_nothing():
    # The text arriving in the box is the message. A panel saying so too
    # would be one more thing on screen for no gain.
    text, _ = panel.status_line(STATE_IDLE, f"{INSERTED_PREFIX}12 words.")
    assert text == ""


def test_a_dictation_that_produced_nothing_says_why():
    # These are the moments the panel exists for: nothing arrived, and
    # without a reason on screen that looks like a broken app.
    text, milliseconds = panel.status_line(
        STATE_IDLE, "The microphone captured no sound."
    )
    assert text == "The microphone captured no sound."
    assert milliseconds > 0  # it goes away on its own


def test_an_error_shows_its_reason_for_longer():
    text, milliseconds = panel.status_line(STATE_ERROR, "Transcription failed: 401")
    assert text == "Transcription failed: 401"
    assert milliseconds > panel.NOTE_MS


def test_an_error_with_no_reason_still_says_something():
    text, _ = panel.status_line(STATE_ERROR, "")
    assert text


def test_the_panel_and_the_tray_agree_on_colour():
    # A blue icon and a red dot at the same moment would be worse than
    # either alone.
    assert set(panel.DOTS) == set(COLOURS)
    for state, rgb in COLOURS.items():
        assert panel.DOTS[state] == "#%02X%02X%02X" % rgb


# --- the window's own bookkeeping, without a window -------------------------


class FakeRoot:
    """Stands in for the Tk window, and records the timers asked for."""

    def __init__(self):
        self.timers = []

    def after(self, milliseconds, callback):
        self.timers.append((milliseconds, callback))


def make_overlay():
    overlay = panel.Overlay()
    overlay._root = FakeRoot()
    overlay.drawn = []
    overlay._draw = lambda text, state: overlay.drawn.append((text, state))
    overlay._hide_window = lambda: overlay.drawn.append((None, None))
    return overlay


def test_a_busy_state_draws_its_line():
    overlay = make_overlay()
    overlay._apply_status(STATE_RECORDING, "")
    assert overlay.drawn[-1] == ("Listening", STATE_RECORDING)


def test_a_timed_message_is_dropped_when_nothing_replaced_it():
    overlay = make_overlay()
    overlay._apply_status(STATE_IDLE, "That was too short.")
    assert overlay.drawn[-1] == ("That was too short.", STATE_IDLE)

    milliseconds, expire = overlay._root.timers[-1]
    assert milliseconds == panel.NOTE_MS
    expire()
    assert overlay.drawn[-1] == (None, None)  # hidden


def test_a_newer_status_cancels_the_timer_of_the_older_one():
    # Without this, starting a new dictation inside the message's few
    # seconds would blank "Listening" the moment the old timer fired.
    overlay = make_overlay()
    overlay._apply_status(STATE_IDLE, "That was too short.")
    _, expire = overlay._root.timers[-1]

    overlay._apply_status(STATE_RECORDING, "")
    expire()  # the stale timer arrives late

    assert overlay.drawn[-1] == ("Listening", STATE_RECORDING)


def test_a_delivered_dictation_hides_the_panel():
    overlay = make_overlay()
    overlay._apply_status(STATE_WORKING, "")
    overlay._apply_status(STATE_IDLE, f"{INSERTED_PREFIX}9 words.")
    assert overlay.drawn[-1] == (None, None)

    # The animation of the state before it was left with a timer in
    # flight. It must find nothing to do rather than wake the panel up.
    for _, timer in overlay._root.timers:
        timer()
    assert overlay.drawn[-1] == (None, None)


def test_the_dot_breathes_only_while_the_app_is_busy():
    # A still dot through a two second wait is the thing this panel
    # exists to avoid. A message that is already going away does not
    # need animating.
    overlay = make_overlay()

    overlay._apply_status(STATE_WORKING, "")
    assert overlay._root.timers, "no animation while writing"

    overlay._root.timers.clear()
    overlay._apply_status(STATE_IDLE, "That was too short.")
    milliseconds = [ms for ms, _ in overlay._root.timers]
    assert milliseconds == [panel.NOTE_MS]  # the timeout, and nothing else


def test_the_dot_fades_towards_the_background_and_back():
    full = panel.DOTS[STATE_WORKING]
    assert panel.blend(full, panel.BACKGROUND, 1.0) == full
    assert panel.blend(full, panel.BACKGROUND, 0.0) == panel.BACKGROUND
    assert panel.blend(full, panel.BACKGROUND, 0.5) not in (full, panel.BACKGROUND)


def test_the_panel_thread_really_starts():
    # Every other test here stubs the Tk thread, and a NameError inside
    # the real one once shipped unseen: start() reported success while
    # the window was dead. This test runs the real thread once.
    import pytest

    pytest.importorskip("tkinter")
    overlay = panel.Overlay()
    started = overlay.start()
    overlay.stop()
    assert started is True
