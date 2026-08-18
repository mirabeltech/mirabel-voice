"""Microphone capture.

The recorder collects mono 16-bit audio while the hotkey is down. It writes
the result to a WAV file, because the speech-to-text API reads WAV directly.
"""

from __future__ import annotations

import io
import threading
import wave
from dataclasses import dataclass

import numpy as np

SAMPLE_WIDTH_BYTES = 2  # 16-bit audio
CHANNELS = 1


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
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._max_frames = int(max_seconds * sample_rate)

    @property
    def is_recording(self) -> bool:
        """Return True while the microphone is open."""
        return self._stream is not None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Store each block of audio that the sound device delivers."""
        with self._lock:
            if self._collected_frames() >= self._max_frames:
                return
            self._chunks.append(indata.copy().reshape(-1))

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
