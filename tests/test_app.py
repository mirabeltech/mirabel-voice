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


def test_cancel_discards_the_recording():
    app = make_app()
    app.start_recording()
    app.cancel_recording()
    assert app.state == STATE_IDLE
    assert app.recorder.cancelled is True
