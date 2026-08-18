import io
import wave

import numpy as np

from mirabel_voice.audio import Recording


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
