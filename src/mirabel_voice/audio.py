"""Microphone capture.

The recorder collects mono 16-bit audio while the hotkey is down. It hands
the result to the speech-to-text API as Opus, which carries the same words
in about a ninth of the bytes and therefore uploads faster.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_WIDTH_BYTES = 2  # 16-bit audio
CHANNELS = 1

#: What an encoded recording is called and how it is announced to the API.
WAV_UPLOAD = ("speech.wav", "audio/wav")
OPUS_UPLOAD = ("speech.ogg", "audio/ogg")


@dataclass
class Recording:
    """One block of captured audio.

    Attributes:
        samples: The audio as 16-bit integers.
        sample_rate: The sample rate in Hz.
    """

    samples: np.ndarray
    sample_rate: int

    @property
    def duration(self) -> float:
        """Return the length of the audio in seconds."""
        if self.sample_rate <= 0:
            return 0.0
        return len(self.samples) / float(self.sample_rate)

    @property
    def peak(self) -> float:
        """Return the loudest sample as a value between 0.0 and 1.0."""
        if len(self.samples) == 0:
            return 0.0
        return float(np.max(np.abs(self.samples))) / 32768.0

    def to_wav_bytes(self) -> bytes:
        """Return the audio as the content of a WAV file."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH_BYTES)
            handle.setframerate(self.sample_rate)
            handle.writeframes(self.samples.astype("<i2").tobytes())
        return buffer.getvalue()

    def to_opus_bytes(self) -> bytes:
        """Return the audio as the content of an Ogg Opus file.

        Raises:
            RuntimeError: soundfile is missing or the encoder refused.
        """
        try:
            import soundfile
        except ImportError as error:  # pragma: no cover - import guard
            raise RuntimeError("soundfile is not installed") from error

        # libsndfile reads past the end of a read-only buffer, so the array
        # handed to it must own its memory. astype always copies.
        samples = self.samples.astype(np.int16)
        buffer = io.BytesIO()
        # OGG/VORBIS is deliberately not offered: libsndfile 1.2.2 kills the
        # process outright when asked to encode speech as Vorbis. Opus is
        # both smaller and stable.
        soundfile.write(
            buffer, samples, self.sample_rate, format="OGG", subtype="OPUS"
        )
        return buffer.getvalue()

    def for_upload(self) -> tuple[str, bytes, str]:
        """Return the file name, bytes, and type to send to the API.

        Opus carries the same words in about a ninth of the bytes, which
        makes the upload quicker. A recording that will not encode is sent
        as WAV rather than lost.
        """
        try:
            payload = self.to_opus_bytes()
        except Exception as error:  # noqa: BLE001 - never lose a dictation
            log.warning("Sending WAV because Opus encoding failed: %s", error)
            name, mime = WAV_UPLOAD
            return name, self.to_wav_bytes(), mime
        name, mime = OPUS_UPLOAD
        return name, payload, mime


def check_encoder() -> tuple[bool, str]:
    """Confirm that a recording can be encoded as Opus.

    Returns whether it worked and a line to show the user. A packaged copy
    with a missing codec falls back to WAV silently, so this is the only
    way to tell the two apart from outside.
    """
    rate = 16000
    seconds = np.linspace(0, 1.0, rate, endpoint=False)
    tone = (np.sin(2 * np.pi * 220 * seconds) * 8000).astype(np.int16)
    probe = Recording(samples=tone, sample_rate=rate)
    wav = len(probe.to_wav_bytes())
    try:
        opus = len(probe.to_opus_bytes())
    except Exception as error:  # noqa: BLE001 - report every failure the same way
        return False, (
            f"The audio encoder does not work: {error}\n"
            "Dictation still works, but it sends about nine times more "
            "audio than it needs to."
        )
    return True, (
        f"The audio encoder works. One second of sound is {wav} bytes as "
        f"WAV and {opus} bytes as Opus."
    )


class Recorder:
    """Record from the microphone between a start call and a stop call.

    The class opens the microphone only while it records. It therefore does
    not hold the device when the app is idle.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | int | None = None,
        max_seconds: float = 300.0,
        on_chunk=None,  # noqa: ANN001 - called with raw PCM16 bytes, if set
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self.on_chunk = on_chunk
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._max_frames = int(max_seconds * sample_rate)

    @property
    def is_recording(self) -> bool:
        """Return True while the microphone is open."""
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Store each block of audio that the sound device delivers.

        The whole recording is always kept, even while streaming, because
        the upload path needs it if the socket fails.
        """
        block = indata.copy().reshape(-1)
        with self._lock:
            if self._collected_frames() >= self._max_frames:
                return
            self._chunks.append(block)
        if self.on_chunk is not None:
            try:
                self.on_chunk(block.astype("<i2").tobytes())
            except Exception:  # noqa: BLE001 - a live listener must not stop recording
                pass

    def _collected_frames(self) -> int:
        """Return the number of frames captured so far."""
        return sum(len(chunk) for chunk in self._chunks)

    def start(self) -> None:
        """Open the microphone and begin to collect audio."""
        if self._stream is not None:
            return
        import sounddevice as sd

        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="int16",
            device=self.device,
            callback=self._callback,
            blocksize=0,
        )
        self._stream.start()

    def stop(self) -> Recording:
        """Close the microphone and return the captured audio."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        with self._lock:
            chunks = self._chunks
            self._chunks = []
        if chunks:
            samples = np.concatenate(chunks)[: self._max_frames]
        else:
            samples = np.zeros(0, dtype=np.int16)
        return Recording(samples=samples, sample_rate=self.sample_rate)

    def cancel(self) -> None:
        """Close the microphone and discard the audio."""
        self.stop()


def list_input_devices() -> list[dict]:
    """Return the microphones that Windows reports."""
    import sounddevice as sd

    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) > 0:
            devices.append(
                {
                    "index": index,
                    "name": info.get("name", ""),
                    "channels": info["max_input_channels"],
                }
            )
    return devices
