import threading

import numpy as np

from fakes import FakeAnthropic, FakeOpenAI, text_response
from mirabel_voice.app import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    VoiceApp,
)
from mirabel_voice.audio import Recording
from mirabel_voice.cleanup import Cleaner
from mirabel_voice.config import Config
from mirabel_voice.inject import TextInjector
from mirabel_voice.transcribe import Transcriber


def loud_recording(seconds=2.0):
    samples = (np.ones(int(16000 * seconds)) * 8000).astype(np.int16)
    return Recording(samples=samples, sample_rate=16000)


def silent_recording(seconds=2.0):
    return Recording(
        samples=np.zeros(int(16000 * seconds), dtype=np.int16), sample_rate=16000
    )


class FakeRecorder:
    def __init__(self, recording):
        self.recording = recording
        self.recording_now = False
        self.cancelled = False

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
        self.cancelled = True


class CapturingInjector:
    def __init__(self, error=None):
        self.sent = []
        self.error = error

    def send(self, text):
        if self.error is not None:
            raise self.error
        self.sent.append(text)


def make_app(
    recording=None,
    transcript="um hello world",
    cleaned="Hello world.",
    injector=None,
    cleanup_enabled=True,
    transcribe_error=None,
):
    config = Config(play_sounds=False, cleanup_enabled=cleanup_enabled)
    openai_client = FakeOpenAI(text=transcript, error=transcribe_error)
    anthropic_client = FakeAnthropic(response=text_response(cleaned))
    app = VoiceApp(
        config=config,
        recorder=FakeRecorder(recording or loud_recording()),
        transcriber=Transcriber(client=openai_client),
        cleaner=Cleaner(client=anthropic_client),
        injector=injector if injector is not None else CapturingInjector(),
    )
    # Pin the focus. The paste path refuses to deliver into a window other
    # than the one the dictation started in, and the real focus on the
    # machine that runs the tests can change at any moment.
    app._focus = lambda: 111
    return app


def run_cycle(app):
    app.start_recording()
    assert app.state == STATE_RECORDING
    app.stop_recording()
    if app._worker is not None:
        app._worker.join(timeout=5)


def test_a_dictation_lands_as_cleaned_text():
    injector = CapturingInjector()
    app = make_app(injector=injector)
    run_cycle(app)
    assert injector.sent == ["Hello world."]
    assert app.state == STATE_IDLE
    assert app.last_text == "Hello world."


def test_cleanup_off_pastes_the_raw_transcript():
    injector = CapturingInjector()
    app = make_app(injector=injector, cleanup_enabled=False)
    run_cycle(app)
    assert injector.sent == ["um hello world"]


def test_a_transcription_failure_reports_an_error_and_pastes_nothing():
    injector = CapturingInjector()
    app = make_app(injector=injector, transcribe_error=RuntimeError("api down"))
    run_cycle(app)
    assert injector.sent == []
    assert app.state == STATE_ERROR


def test_a_silent_recording_is_dropped_before_any_api_call():
    injector = CapturingInjector()
    app = make_app(recording=silent_recording(), injector=injector)
    run_cycle(app)
    assert injector.sent == []
    assert app.state == STATE_IDLE


def test_a_too_short_recording_is_dropped():
    injector = CapturingInjector()
    app = make_app(recording=loud_recording(seconds=0.1), injector=injector)
    run_cycle(app)
    assert injector.sent == []
    assert app.state == STATE_IDLE


def test_an_injection_failure_reports_an_error():
    injector = CapturingInjector(error=RuntimeError("no paste"))
    app = make_app(injector=injector)
    run_cycle(app)
    assert app.state == STATE_ERROR


def test_paste_last_sends_the_previous_transcript_again(monkeypatch):
    import mirabel_voice.app as app_module

    monkeypatch.setattr(app_module, "PASTE_LAST_DELAY_SECONDS", 0)
    injector = CapturingInjector()
    app = make_app(injector=injector)
    run_cycle(app)
    app.paste_last()
    app._paste_thread.join(timeout=5)
    assert injector.sent == ["Hello world.", "Hello world."]


def test_paste_last_before_any_dictation_does_nothing():
    injector = CapturingInjector()
    app = make_app(injector=injector)
    app.paste_last()
    assert app._paste_thread is None
    assert injector.sent == []
    assert app.state == STATE_IDLE


def test_a_changed_window_blocks_the_paste():
    """The paste can land seconds after the hotkey. By then the user may
    sit in another window, and the text would go to the wrong place."""
    injector = CapturingInjector()
    app = make_app(injector=injector)
    handles = [111, 222]  # focus at the start, focus at delivery
    app._focus = lambda: handles.pop(0) if handles else 222
    run_cycle(app)
    assert injector.sent == []
    assert app.state == STATE_ERROR
    assert app.last_text == "Hello world."  # paste-last can still deliver it


def test_an_unknown_window_does_not_block_the_paste():
    """A focus of 0 means Windows could not tell us. The paste deletes
    nothing, so losing the dictation would be the worse outcome."""
    injector = CapturingInjector()
    app = make_app(injector=injector)
    handles = [111]
    app._focus = lambda: handles.pop(0) if handles else 0
    run_cycle(app)
    assert injector.sent == ["Hello world."]
    assert app.state == STATE_IDLE


def test_a_refused_start_reports_false_to_the_listener():
    app = make_app()
    app.start_recording()
    app.stop_recording()          # a worker is now processing
    app._worker.join(timeout=5)   # let it finish to keep the test honest
    assert app.start_recording() is True

    class NeverFinishing:
        def is_alive(self):
            return True

    app._worker = NeverFinishing()
    app.state = STATE_IDLE
    assert app.start_recording() is False


class NeverFinishingWorker:
    def is_alive(self):
        return True


def capture_beeps(app):
    """Replace the beeper and return the list it fills."""
    beeps = []
    app._beep = lambda frequency, duration: beeps.append(frequency)
    return beeps


def join_beep(app):
    if app._beep_thread is not None:
        app._beep_thread.join(timeout=5)


def test_a_busy_press_is_refused_with_a_low_double_beep():
    app = make_app()
    beeps = capture_beeps(app)
    app._worker = NeverFinishingWorker()
    assert app._request_start() is False
    join_beep(app)
    assert beeps == [330, 330]
    assert app._actions.empty()  # nothing was queued for later


def test_a_free_press_queues_the_start():
    app = make_app()
    assert app._request_start() is True
    action = app._actions.get_nowait()
    action()
    assert app.state == STATE_RECORDING


def test_a_stop_press_with_nothing_recording_beeps_refusal():
    app = make_app()
    beeps = capture_beeps(app)
    app.stop_recording()
    join_beep(app)
    assert beeps == [330, 330]


def test_a_finished_insert_plays_a_completion_tone():
    app = make_app()
    beeps = capture_beeps(app)
    run_cycle(app)
    assert app.state == STATE_IDLE
    assert beeps[-1] == 990


def test_hotkey_actions_run_on_the_dispatch_thread():
    app = make_app()
    ran = []
    thread = threading.Thread(
        target=app._dispatch, name="test-dispatch", daemon=True
    )
    thread.start()
    app._enqueue(lambda: ran.append(threading.current_thread().name))
    app._actions.put(None)  # end the loop
    thread.join(timeout=5)
    assert ran == ["test-dispatch"]  # not on the caller's thread


def test_a_failing_action_does_not_stop_the_dispatcher():
    app = make_app()
    ran = []
    thread = threading.Thread(target=app._dispatch, daemon=True)
    thread.start()
    app._enqueue(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    app._enqueue(lambda: ran.append("after"))
    app._actions.put(None)
    thread.join(timeout=5)
    assert ran == ["after"]


def test_cancel_discards_the_recording():
    app = make_app()
    app.start_recording()
    app.cancel_recording()
    assert app.state == STATE_IDLE
    assert app.recorder.cancelled is True


def test_a_settings_file_from_the_streaming_era_still_dictates(tmp_path):
    # The streaming path is retired. An install whose settings file still
    # carries its keys - even switched on - must dictate normally through
    # the batch path.
    import json

    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "play_sounds": False,
                "streaming_enabled": True,
                "streaming_model": "gpt-live-transcribe",
                "show_overlay": True,
                "live_insert": True,
            }
        ),
        encoding="utf-8",
    )
    injector = CapturingInjector()
    app = VoiceApp(
        config=Config.load(target),
        recorder=FakeRecorder(loud_recording()),
        transcriber=Transcriber(client=FakeOpenAI(text="um hello world")),
        cleaner=Cleaner(client=FakeAnthropic(response=text_response("Hello world."))),
        injector=injector,
    )
    app._focus = lambda: 111
    run_cycle(app)
    assert injector.sent == ["Hello world."]


def language_app(monkeypatch, tmp_path):
    monkeypatch.setenv("MIRABEL_VOICE_HOME", str(tmp_path))
    config = Config(play_sounds=False)
    return VoiceApp(
        config=config,
        recorder=FakeRecorder(loud_recording()),
        injector=CapturingInjector(),
        transcriber=Transcriber(client=FakeOpenAI()),
        cleaner=Cleaner(client=FakeAnthropic(response=text_response("Hi."))),
    )


def test_switching_language_needs_no_restart(monkeypatch, tmp_path):
    """The tray switch must reach the very next dictation."""
    app = language_app(monkeypatch, tmp_path)
    app.set_language("hi")
    assert app.transcriber.language == "hi"
    assert Config.load().language == "hi"  # and the next start agrees


def test_detect_automatically_is_a_real_choice(monkeypatch, tmp_path):
    app = language_app(monkeypatch, tmp_path)
    app.set_language(None)
    assert app.transcriber.language is None
    assert Config.load().language is None


def test_switching_language_tells_the_tray(monkeypatch, tmp_path):
    app = language_app(monkeypatch, tmp_path)
    told = []
    app._on_state = lambda state, detail: told.append(detail)
    app.set_language("te")
    assert any("Telugu" in detail for detail in told)


def test_every_offered_language_switches_and_announces_itself(monkeypatch, tmp_path):
    # The tray builds its submenu from this list, so this is the menu.
    from mirabel_voice.app import LANGUAGES

    assert dict(LANGUAGES) == {
        "en": "English",
        "hi": "Hindi",
        "hu": "Hungarian",
        "kn": "Kannada",
        "mr": "Marathi",
        "ta": "Tamil",
        "te": "Telugu",
    }

    app = language_app(monkeypatch, tmp_path)
    told = []
    app._on_state = lambda state, detail: told.append(detail)
    for code, label in LANGUAGES:
        app.set_language(code)
        assert app.transcriber.language == code
        assert any(label in detail for detail in told)
