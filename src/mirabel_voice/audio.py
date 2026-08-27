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

# How long the microphone gets to answer the open call. A USB device
# waking from suspend takes a second or two, and a Bluetooth headset
# renegotiating its hands-free link can take longer still; a wedged
# driver never answers, and dictation must not hang with it.
OPEN_TIMEOUT_SECONDS = 10.0


class MicrophoneTimeout(RuntimeError):
    """The device did not answer the open call in time.

    hint carries the one action the user can take, shown as the second
    line of the status pill.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class MicrophoneCancelled(RuntimeError):
    """The cycle was cancelled while the device was still opening."""

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
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._max_frames = int(max_seconds * sample_rate)
        self._level = 0.0
        # The open call runs on this worker so a wedged driver cannot
        # hang the caller. _generation says which cycle a finished open
        # belongs to; an open that arrives late is closed and dropped.
        self._open_thread: threading.Thread | None = None
        self._open_error: Exception | None = None
        self._generation = 0

    @property
    def is_recording(self) -> bool:
        """Return True while the microphone is open."""
        return self._stream is not None

    @property
    def level(self) -> float:
        """How loud the last captured block was, between 0.0 and 1.0.

        The status panel draws this as moving bars. A level that stays
        at zero while recording tells the user the wrong microphone is
        selected - faster than any message could.
        """
        return self._level if self._stream is not None else 0.0

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Store each block of audio that the sound device delivers."""
        block = indata.copy().reshape(-1)
        if len(block):
            self._level = float(np.max(np.abs(block))) / 32768.0
        with self._lock:
            if self._collected_frames() >= self._max_frames:
                return
            self._chunks.append(block)

    def _collected_frames(self) -> int:
        """Return the number of frames captured so far."""
        return sum(len(chunk) for chunk in self._chunks)

    def start(self, timeout: float = OPEN_TIMEOUT_SECONDS) -> None:
        """Open the microphone and begin to collect audio.

        The open runs on a worker with a deadline. A device that does
        not answer in time raises MicrophoneTimeout and the caller's
        thread comes straight back; whatever the driver finally
        delivers is closed and dropped, never kept.

        The caller's thread waits at most the deadline, so a queued
        cancel cannot run during the wait; a cancel from another thread
        (the app quitting) still lands, and raises MicrophoneCancelled
        here.

        Raises:
            MicrophoneTimeout: The device did not answer, or an earlier
                open is still unanswered.
            MicrophoneCancelled: stop or cancel arrived while the
                device was still opening.
            Exception: Whatever the device refused the open with.
        """
        with self._lock:
            if self._stream is not None:
                return
            if self._open_thread is not None and self._open_thread.is_alive():
                # One wedged open is one leaked worker. Piling more
                # presses onto the same dead device must not leak one
                # per press.
                raise MicrophoneTimeout(
                    "The microphone is still answering an earlier request.",
                    hint="Wait a moment, then press the key again.",
                )
            self._chunks = []
            self._generation += 1
            generation = self._generation
            self._level = 0.0
            self._open_error = None
            worker = threading.Thread(
                target=self._open,
                args=(generation,),
                name="mirabel-voice-mic-open",
                daemon=True,
            )
            self._open_thread = worker
            # Started under the lock, so no second caller can ever see
            # the worker in its not-yet-alive window.
            worker.start()
        worker.join(timeout)
        if worker.is_alive():
            # Abandon it, but keep the reference: the next start must
            # see the wedged worker and refuse instead of stacking up.
            with self._lock:
                self._generation += 1
                stream, self._stream = self._stream, None
            self._discard(stream)
            raise MicrophoneTimeout(
                "The microphone did not answer.",
                hint="Make sure the microphone is connected. Close any "
                "other program that is using it.",
            )
        self._open_thread = None
        if self._open_error is not None:
            raise self._open_error
        if self._stream is None:
            # No stream, no error: stop or cancel moved the generation
            # while the device was opening. Success here would tell the
            # caller "Listening" with no microphone open.
            raise MicrophoneCancelled(
                "The recording was cancelled while the microphone opened."
            )

    def _open(self, generation: int) -> None:
        """Open the stream, and keep it only if the cycle still wants it."""
        try:
            import sounddevice as sd

            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype="int16",
                device=self.device,
                callback=self._callback,
                blocksize=0,
            )
            # Check before arming the callback: a started stream writes
            # into _chunks and _level, and an abandoned cycle must not
            # get even a block of stray audio.
            with self._lock:
                wanted = generation == self._generation
            if not wanted:
                self._discard(stream)
                return
            stream.start()
        except Exception as error:  # noqa: BLE001 - the caller re-raises
            self._open_error = error
            return
        with self._lock:
            if generation == self._generation and self._stream is None:
                self._stream = stream
                return
        # The cycle gave up, or was cancelled, while the device
        # dawdled. A stream nobody is waiting for stays closed.
        self._discard(stream)

    @staticmethod
    def _discard(stream) -> None:  # noqa: ANN001
        """Close a stream that is no longer wanted, quietly."""
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:  # noqa: BLE001 - it is being thrown away
            pass
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> Recording:
        """Close the microphone and return the captured audio."""
        with self._lock:
            self._generation += 1
            stream, self._stream = self._stream, None
        # A driver that errors on the close must not lose the captured
        # audio, and must not leave the caller stuck mid-cycle.
        self._discard(stream)
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
    """Return the microphones that Windows reports.

    Windows reports each microphone once per audio API, so the same
    device appears several times. The hostapi name says which listing
    an entry belongs to; the tray uses it to show each device once.
    """
    import sounddevice as sd

    apis = [api.get("name", "") for api in sd.query_hostapis()]
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) > 0:
            api = info.get("hostapi", -1)
            devices.append(
                {
                    "index": index,
                    "name": info.get("name", ""),
                    "channels": info["max_input_channels"],
                    "hostapi": apis[api] if 0 <= api < len(apis) else "",
                }
            )
    return devices
