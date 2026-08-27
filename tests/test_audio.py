import io
import wave

import numpy as np
import pytest

from mirabel_voice.audio import Recording, check_encoder


def make_tone(seconds=1.0, rate=16000, amplitude=8000):
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def test_duration_matches_the_sample_count():
    recording = Recording(samples=make_tone(2.0), sample_rate=16000)
    assert abs(recording.duration - 2.0) < 0.001


def test_peak_reports_the_loudest_sample():
    recording = Recording(samples=make_tone(amplitude=16384), sample_rate=16000)
    assert 0.49 < recording.peak < 0.51


def test_peak_of_silence_is_zero():
    recording = Recording(samples=np.zeros(1000, dtype=np.int16), sample_rate=16000)
    assert recording.peak == 0.0


def test_empty_recording_has_no_duration():
    recording = Recording(samples=np.zeros(0, dtype=np.int16), sample_rate=16000)
    assert recording.duration == 0.0


def test_wav_bytes_are_a_readable_wav_file():
    recording = Recording(samples=make_tone(0.5), sample_rate=16000)
    payload = recording.to_wav_bytes()
    assert payload[:4] == b"RIFF"
    with wave.open(io.BytesIO(payload), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 16000
        assert handle.getnframes() == 8000


def test_opus_is_far_smaller_than_wav_and_still_decodes():
    # Measured on real speech: Opus is about a ninth of the WAV size with no
    # word-level difference in the transcript. This test guards the encoder
    # working at all, not the exact ratio.
    import soundfile

    rate = 16000
    t = np.linspace(0, 2.0, rate * 2, endpoint=False)
    tone = (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)
    recording = Recording(samples=tone, sample_rate=rate)

    payload = recording.to_opus_bytes()

    assert len(payload) < len(recording.to_wav_bytes()) / 2
    decoded, decoded_rate = soundfile.read(io.BytesIO(payload))
    assert decoded_rate == rate
    assert len(decoded) > 0


def test_the_upload_is_opus_when_the_encoder_works():
    recording = Recording(samples=np.zeros(1600, dtype=np.int16), sample_rate=16000)

    name, payload, mime = recording.for_upload()

    assert name == "speech.ogg"
    assert mime == "audio/ogg"
    assert payload.startswith(b"OggS")


def test_a_failed_encoder_sends_wav_rather_than_losing_the_dictation(monkeypatch):
    # A missing codec must never cost somebody the words they just said.
    recording = Recording(samples=np.zeros(1600, dtype=np.int16), sample_rate=16000)
    monkeypatch.setattr(
        Recording,
        "to_opus_bytes",
        lambda self: (_ for _ in ()).throw(RuntimeError("no libsndfile")),
    )

    name, payload, mime = recording.for_upload()

    assert name == "speech.wav"
    assert mime == "audio/wav"
    assert payload.startswith(b"RIFF")


def test_the_encoder_check_reports_success_and_both_sizes():
    ok, message = check_encoder()
    assert ok is True
    assert "works" in message


def test_the_encoder_check_reports_a_broken_codec(monkeypatch):
    monkeypatch.setattr(
        Recording,
        "to_opus_bytes",
        lambda self: (_ for _ in ()).throw(RuntimeError("no libsndfile")),
    )
    ok, message = check_encoder()
    assert ok is False
    assert "nine times more" in message


def test_the_level_is_zero_until_a_recording_runs():
    from mirabel_voice.audio import Recorder

    recorder = Recorder()
    assert recorder.level == 0.0
    # The callback stores the loudness of each block; the property
    # reports it only while the stream is open.
    recorder._stream = object()
    recorder._callback(np.array([[8000], [-16000]], dtype=np.int16), 2, None, None)
    assert 0.4 < recorder.level < 0.6
    recorder._stream = None
    assert recorder.level == 0.0


# --- the open runs on a worker with a deadline (#57) ------------------------


class FakeSounddevice:
    """A sounddevice whose InputStream behaves as the test dictates."""

    def __init__(self, block=None, fail=None):
        import threading

        self.block = block or threading.Event()
        self.block.set()  # answer at once unless a test clears it
        self.fail = fail
        self.streams = []
        outer = self

        class InputStream:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
                self.stopped = False
                self.closed = False
                outer.streams.append(self)

            def start(self):
                outer.block.wait()
                if outer.fail is not None:
                    raise outer.fail
                self.started = True

            def stop(self):
                self.stopped = True

            def close(self):
                self.closed = True

        self.InputStream = InputStream


def recorder_with(monkeypatch, fake):
    import sys

    from mirabel_voice.audio import Recorder

    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return Recorder()


def test_a_normal_open_still_records(monkeypatch):
    fake = FakeSounddevice()
    recorder = recorder_with(monkeypatch, fake)
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    recorder.cancel()
    assert not recorder.is_recording
    assert fake.streams[0].closed


def test_a_wedged_open_times_out_and_leaves_the_recorder_idle(monkeypatch):
    import time

    from mirabel_voice.audio import MicrophoneTimeout

    fake = FakeSounddevice()
    fake.block.clear()  # the driver never answers
    recorder = recorder_with(monkeypatch, fake)

    began = time.monotonic()
    with pytest.raises(MicrophoneTimeout):
        recorder.start(timeout=0.2)
    assert time.monotonic() - began < 2.0  # the caller came back
    assert not recorder.is_recording

    # A second press while the device is still wedged is refused at
    # once, without stacking another worker onto the dead device.
    began = time.monotonic()
    with pytest.raises(MicrophoneTimeout):
        recorder.start(timeout=5.0)
    assert time.monotonic() - began < 1.0
    fake.block.set()  # let the wedged worker finish, for teardown


def test_a_late_stream_is_closed_not_kept(monkeypatch):
    from mirabel_voice.audio import MicrophoneTimeout

    fake = FakeSounddevice()
    fake.block.clear()
    recorder = recorder_with(monkeypatch, fake)
    with pytest.raises(MicrophoneTimeout):
        recorder.start(timeout=0.1)

    # The driver finally answers, long after the cycle gave up.
    fake.block.set()
    recorder._open_thread.join(timeout=5.0)
    assert fake.streams[0].closed
    assert not recorder.is_recording

    # And the recorder is healthy again: a fresh open works.
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    assert fake.streams[1].started
    recorder.cancel()


def test_a_failing_open_raises_its_error(monkeypatch):
    fake = FakeSounddevice(fail=RuntimeError("device refused"))
    recorder = recorder_with(monkeypatch, fake)
    with pytest.raises(RuntimeError, match="device refused"):
        recorder.start(timeout=2.0)
    assert not recorder.is_recording

    # The failure is not sticky: a later open on a repaired device works.
    fake.fail = None
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    recorder.cancel()


def test_a_cancel_during_the_open_discards_the_stream(monkeypatch):
    import threading
    import time

    from mirabel_voice.audio import MicrophoneCancelled

    fake = FakeSounddevice()
    fake.block.clear()
    recorder = recorder_with(monkeypatch, fake)

    outcome = []

    def open_it():
        try:
            recorder.start(timeout=5.0)
            outcome.append("started")
        except Exception as error:  # noqa: BLE001 - the outcome IS the test
            outcome.append(error)

    opener = threading.Thread(target=open_it)
    opener.start()
    # Wait until the open is really in flight - a cancel that lands
    # before it would belong to the previous cycle, not this one.
    deadline = time.monotonic() + 5.0
    while not fake.streams and time.monotonic() < deadline:
        time.sleep(0.01)
    # The user cancels while the device is still answering.
    recorder.cancel()
    fake.block.set()
    opener.join(timeout=5.0)
    assert not recorder.is_recording
    assert fake.streams[0].closed
    # The caller must hear "cancelled", not a silent success that the
    # app would announce as "Listening" with no microphone open.
    assert outcome and isinstance(outcome[0], MicrophoneCancelled)


def test_a_stop_that_errors_still_returns_the_audio(monkeypatch):
    fake = FakeSounddevice()
    recorder = recorder_with(monkeypatch, fake)
    recorder.start(timeout=2.0)

    def explode():
        raise RuntimeError("the driver went away")

    fake.streams[0].stop = explode
    recorder._chunks = [np.array([1, 2, 3], dtype=np.int16)]
    recording = recorder.stop()  # must not raise
    assert list(recording.samples) == [1, 2, 3]
    assert not recorder.is_recording
