import io
import wave

import numpy as np

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
