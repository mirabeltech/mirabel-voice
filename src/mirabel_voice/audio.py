"""Microphone capture.

The recorder collects mono 16-bit audio while the hotkey is down. It hands
the result to the speech-to-text API as Opus, which carries the same words
in about a ninth of the bytes and therefore uploads faster.

In hot mode the input stream stays open the whole time the app runs. The
callback feeds a short in-memory ring that is discarded continuously and
sent nowhere; a press keeps the ring's tail as pre-roll and starts the
recording at once, with no device call in the way.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import wave
from collections import deque
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

# How much just-heard audio the hot microphone keeps in memory. Anything
# older falls off the ring unheard; only a press keeps the tail.
RING_SECONDS = 2.0

# The hot stream's watchdog. PortAudio can simply stop calling back when
# a device goes away, without an error, so silence past DEAD_STREAM_SECONDS
# is the signal. Reopens back off so a missing device is not hammered.
WATCHDOG_INTERVAL_SECONDS = 1.0
DEAD_STREAM_SECONDS = 3.0
REOPEN_BACKOFF_START_SECONDS = 1.0
REOPEN_BACKOFF_CAP_SECONDS = 30.0


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
        pre_roll_frames: How many leading samples the hot microphone
            heard before the press.
    """

    samples: np.ndarray
    sample_rate: int
    pre_roll_frames: int = 0

    @property
    def duration(self) -> float:
        """Return the length of the audio in seconds."""
        if self.sample_rate <= 0:
            return 0.0
        return len(self.samples) / float(self.sample_rate)

    @property
    def press_duration(self) -> float:
        """Return the seconds captured after the press.

        The too-short guard judges this, not the whole clip: pre-roll
        padding must not let a stray tap pass for a dictation.
        """
        if self.sample_rate <= 0:
            return 0.0
        return max(
            0.0, self.duration - self.pre_roll_frames / float(self.sample_rate)
        )

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

    Cold mode opens the microphone only while it records, so the app
    does not hold the device when it is idle. Hot mode keeps one stream
    open, feeds the ring, and a press merely arms: the ring's tail
    becomes the pre-roll and the recording starts with no device call.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | int | None = None,
        max_seconds: float = 300.0,
        hot: bool = False,
        pre_roll_seconds: float = 0.4,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.max_seconds = max_seconds
        self._hot = hot
        # Clamped to the ring, and to half of max_seconds: pre-roll that
        # fills the whole recording budget would leave the callback's cap
        # refusing every live block, and the dictation itself would be
        # silently lost.
        self._pre_roll_seconds = min(
            max(pre_roll_seconds, 0.0), RING_SECONDS, max_seconds / 2.0
        )
        self._chunks: list[np.ndarray] = []
        # The callback must never scan a growing list, so the captured
        # frame count rides along as a counter.
        self._chunk_frames = 0
        self._stream = None
        self._lock = threading.Lock()
        self._max_frames = int(max_seconds * sample_rate)
        self._ring_max_frames = int(RING_SECONDS * sample_rate)
        self._level = 0.0
        # Armed means a recording is collecting. In hot mode the stream
        # is open long before the press and long after the stop.
        self._armed = False
        self._pre_roll_frames = 0
        self._ring: deque[np.ndarray] = deque()
        self._ring_frames = 0
        # Written by the callback without the lock, like _level: a plain
        # float store is atomic enough for a sign of life.
        self._last_block_at = 0.0
        self._pending_device = False
        # The open call runs on this worker so a wedged driver cannot
        # hang the caller. _generation says which cycle a finished open
        # belongs to; an open that arrives late is closed and dropped.
        self._open_thread: threading.Thread | None = None
        self._open_error: Exception | None = None
        self._generation = 0
        self._supervisor: threading.Thread | None = None
        self._shutdown = threading.Event()
        # The supervisor consumes these under _lock; set_device resets
        # them so a new device never inherits the old device's backoff.
        self._reopen_backoff = REOPEN_BACKOFF_START_SECONDS
        self._next_attempt = 0.0

    @property
    def is_recording(self) -> bool:
        """Return True while a recording is armed.

        The hot stream being open does not count: between presses the
        microphone is heard but nothing is kept.
        """
        return self._armed

    @property
    def level(self) -> float:
        """How loud the last captured block was, between 0.0 and 1.0.

        The status panel draws this as moving bars. A level that stays
        at zero while recording tells the user the wrong microphone is
        selected - faster than any message could. While no recording is
        armed the level stays zero, even with the hot stream open.
        """
        return self._level if self._armed else 0.0

    @property
    def hot_ready(self) -> bool:
        """Return True when the hot stream is open and a press is instant.

        A stream that stopped delivering blocks does not count, even
        before the watchdog has replaced it: a press on it would say
        "Listening" over a dead device.
        """
        return (
            self._hot
            and self._stream is not None
            and self._stream_is_fresh()
        )

    def _stream_is_fresh(self) -> bool:
        """Return True while the stream's callback shows signs of life."""
        return time.monotonic() - self._last_block_at <= DEAD_STREAM_SECONDS

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Store each block of audio that the sound device delivers.

        Runs on the PortAudio thread, so it allocates nothing beyond the
        block copy and holds the lock only for appends and eviction.
        """
        block = indata.copy().reshape(-1)
        if len(block):
            self._level = float(np.max(np.abs(block))) / 32768.0
        self._last_block_at = time.monotonic()
        with self._lock:
            if self._hot:
                self._ring.append(block)
                self._ring_frames += len(block)
                while (
                    self._ring_frames - len(self._ring[0])
                    >= self._ring_max_frames
                ):
                    self._ring_frames -= len(self._ring.popleft())
            if self._armed and self._chunk_frames < self._max_frames:
                self._chunks.append(block)
                self._chunk_frames += len(block)

    def start(self, timeout: float = OPEN_TIMEOUT_SECONDS) -> None:
        """Begin to collect audio, opening the microphone if it must.

        With the hot stream live there is no device call at all: the
        press arms, the ring's tail becomes the pre-roll, and the
        caller returns at once. Every other path - cold mode, the first
        hot open, a reopen after the stream died - runs the open on a
        worker with a deadline. A device that does not answer in time
        raises MicrophoneTimeout and the caller's thread comes straight
        back; whatever the driver finally delivers is closed and
        dropped, never kept.

        The caller's thread waits at most the deadline, so a queued
        cancel cannot run during the wait. A shutdown from another
        thread (the app quitting) still lands, and raises
        MicrophoneCancelled here; in cold mode a cross-thread cancel
        does the same through its generation bump. A hot-mode cancel
        deliberately touches neither the stream nor an open in flight.

        Raises:
            MicrophoneTimeout: The device did not answer, or an earlier
                open is still unanswered.
            MicrophoneCancelled: stop or cancel arrived while the
                device was still opening.
            Exception: Whatever the device refused the open with.
        """
        if self._hot and self._start_hot(timeout):
            return
        self._open_with_deadline(timeout)
        # The open armed at its spawn. This covers its early return: the
        # supervisor can install a stream between _start_hot's look and
        # the open's, and that path must still leave the press armed.
        with self._lock:
            self._armed = True

    def _clear_ring_locked(self) -> None:
        """Drop the ring's audio. The caller holds _lock."""
        self._ring.clear()
        self._ring_frames = 0

    def _reset_capture_locked(self) -> None:
        """Drop the collected recording state. The caller holds _lock."""
        self._chunks = []
        self._chunk_frames = 0
        self._pre_roll_frames = 0

    def _arm_from_ring_locked(self) -> None:
        """Seed the recording with the ring's tail and arm.

        The caller holds _lock. Blocks are shared with the ring, never
        copied here; the callback only ever appends fresh copies, and
        stop's concatenate makes the recording its own memory.
        """
        target = int(self._pre_roll_seconds * self.sample_rate)
        kept: list[np.ndarray] = []
        frames = 0
        for block in reversed(self._ring):
            if frames >= target:
                break
            kept.append(block)
            frames += len(block)
        kept.reverse()
        if frames > target:
            # Trim the head of the oldest kept block to the exact frame.
            kept[0] = kept[0][frames - target :]
            frames = target
        self._chunks = kept
        self._chunk_frames = frames
        self._pre_roll_frames = frames
        self._level = 0.0
        self._armed = True

    def _start_hot(self, timeout: float) -> bool:
        """Arm on the live stream, or wait out an open already in flight.

        Returns True when the press is handled here; False sends the
        caller on to the cold open.
        """
        stale = None
        with self._lock:
            if self._armed:
                return True
            if self._stream is not None:
                if self._stream_is_fresh():
                    self._arm_from_ring_locked()
                    return True
                # The stream stopped delivering but the watchdog has not
                # replaced it yet. Do what the watchdog would: close it,
                # and never let its last audio become pre-roll. The
                # press then opens cold, with the Starting pill and the
                # coach, because hot_ready already read False.
                stale, self._stream = self._stream, None
                self._clear_ring_locked()
                self._level = 0.0
                self._reopen_backoff = REOPEN_BACKOFF_START_SECONDS
                self._next_attempt = 0.0
            worker = self._open_thread
        self._discard(stale)
        if worker is None or not worker.is_alive():
            return False
        # The supervisor owns this open. The press joins it with its own
        # deadline instead of refusing; on a timeout the generation
        # stays put, because abandoning the supervisor's open is not the
        # press's call to make.
        worker.join(timeout)
        if worker.is_alive():
            raise MicrophoneTimeout(
                "The microphone did not answer.",
                hint="Make sure the microphone is connected. Close any "
                "other program that is using it.",
            )
        with self._lock:
            if self._stream is None:
                return False
            # The stream opened mid-press, so everything it has heard
            # belongs to this recording - and none of it is pre-roll,
            # because it all arrived after the press. Audio from before
            # a death cannot be here: every close clears the ring.
            self._chunks = list(self._ring)
            self._chunk_frames = self._ring_frames
            self._pre_roll_frames = 0
            self._level = 0.0
            self._armed = True
        return True

    def _open_with_deadline(self, timeout: float) -> None:
        """Open the microphone on a worker with a deadline, and arm.

        Arming happens at the spawn, not after the join: the callback
        then keeps the very first block the started stream delivers,
        instead of dropping whatever arrives before the caller's thread
        wakes from the join. Every failure path disarms.
        """
        with self._lock:
            if self._shutdown.is_set():
                # The app is quitting. A fresh generation bump here
                # would revive what shutdown just killed.
                raise MicrophoneCancelled("The recorder is shut down.")
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
            self._reset_capture_locked()
            self._generation += 1
            generation = self._generation
            self._level = 0.0
            self._open_error = None
            self._armed = True
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
                self._armed = False
                stream, self._stream = self._stream, None
                self._clear_ring_locked()
            self._discard(stream)
            raise MicrophoneTimeout(
                "The microphone did not answer.",
                hint="Make sure the microphone is connected. Close any "
                "other program that is using it.",
            )
        with self._lock:
            # Only this call's worker: the supervisor may have installed
            # its own by now, and dropping that reference would let
            # presses stack workers onto a wedged device.
            if self._open_thread is worker:
                self._open_thread = None
            error = self._open_error
            cancelled = self._stream is None
            if error is not None or cancelled:
                self._armed = False
        if error is not None:
            raise error
        if cancelled:
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
                # A fresh stream has delivered nothing yet; stamp it so
                # the watchdog cannot declare it dead before its first
                # block arrives.
                self._last_block_at = time.monotonic()
                self._stream = stream
                return
        # The cycle gave up, or was cancelled, while the device
        # dawdled. A stream nobody is waiting for stays closed, and
        # whatever it managed to hear stays out of the ring.
        with self._lock:
            self._clear_ring_locked()
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
        """End the recording and return the captured audio.

        Hot mode keeps the stream open for the next press; cold mode
        closes the microphone as it always has.
        """
        with self._lock:
            self._armed = False
            chunks, self._chunks = self._chunks, []
            self._chunk_frames = 0
            pre, self._pre_roll_frames = self._pre_roll_frames, 0
            pending = self._pending_device
            if self._hot:
                stream = None
            else:
                self._generation += 1
                stream, self._stream = self._stream, None
                self._clear_ring_locked()
        # A driver that errors on the close must not lose the captured
        # audio, and must not leave the caller stuck mid-cycle.
        self._discard(stream)
        if self._hot and pending:
            self._cycle_stream()
        if chunks:
            samples = np.concatenate(chunks)[: self._max_frames]
        else:
            samples = np.zeros(0, dtype=np.int16)
        return Recording(
            samples=samples,
            sample_rate=self.sample_rate,
            pre_roll_frames=min(pre, len(samples)),
        )

    def cancel(self) -> None:
        """Discard the audio. Hot mode keeps the stream for the next press."""
        if not self._hot:
            self.stop()
            return
        with self._lock:
            self._armed = False
            self._reset_capture_locked()
            pending = self._pending_device
        if pending:
            self._cycle_stream()

    def open_hot(self) -> None:
        """Start the hot stream's supervisor. A no-op in cold mode.

        Idempotent. The supervisor performs the first open, watches for
        a stream that stopped delivering blocks, and reopens it.
        """
        if not self._hot:
            return
        with self._lock:
            if self._supervisor is not None and self._supervisor.is_alive():
                return
            self._shutdown.clear()
            supervisor = threading.Thread(
                target=self._supervise,
                name="mirabel-voice-mic-supervisor",
                daemon=True,
            )
            self._supervisor = supervisor
            supervisor.start()

    def shutdown(self) -> None:
        """Release the microphone and stop the supervisor, for quitting.

        Idempotent, and safe in cold mode, where it amounts to a
        cancel. The generation bump makes an open still in flight
        discard its stream whenever the driver finally answers.
        """
        self._shutdown.set()
        with self._lock:
            self._generation += 1
            stream, self._stream = self._stream, None
            self._clear_ring_locked()
            self._armed = False
            self._reset_capture_locked()
            supervisor = self._supervisor
        if stream is not None:
            # The close runs on a worker with a deadline: a wedged
            # driver can block it forever, and the update relaunch
            # waits only 20 seconds for this process to let go of the
            # single-instance mutex. An abandoned closer is a daemon
            # and dies with the process.
            closer = threading.Thread(
                target=self._discard,
                args=(stream,),
                name="mirabel-voice-mic-close",
                daemon=True,
            )
            closer.start()
            closer.join(timeout=2.0)
        if supervisor is not None:
            supervisor.join(timeout=2.0)

    def _supervise(self) -> None:
        """Keep the hot stream alive: open it, watch it, reopen it.

        A stream can die without an error - PortAudio just goes quiet
        when a USB device unplugs - so the callback's monotonic stamp
        is the sign of life, not PortAudio's finished_callback.
        """
        while not self._shutdown.wait(WATCHDOG_INTERVAL_SECONDS):
            now = time.monotonic()
            with self._lock:
                stream = self._stream
                worker = self._open_thread
                worker_alive = worker is not None and worker.is_alive()
            if stream is not None:
                if now - self._last_block_at > DEAD_STREAM_SECONDS:
                    log.warning(
                        "The microphone stream went quiet; reopening it."
                    )
                    with self._lock:
                        # An armed recording keeps its chunks: the
                        # reopen gives it a gap, not a loss. The ring is
                        # cleared because audio from before the death
                        # must never become pre-roll, and the level is
                        # zeroed so the bars stop moving over a dead
                        # device - a flat row is their whole point.
                        dead, self._stream = self._stream, None
                        self._clear_ring_locked()
                        self._level = 0.0
                        self._next_attempt = now
                    self._discard(dead)
                else:
                    with self._lock:
                        self._reopen_backoff = REOPEN_BACKOFF_START_SECONDS
            elif not worker_alive:
                with self._lock:
                    if self._shutdown.is_set():
                        # shutdown sets the event before it takes the
                        # lock, so an opener spawned here would carry
                        # the post-bump generation and install a live
                        # microphone on a quit app.
                        return
                    if self._stream is not None or (
                        self._open_thread is not None
                        and self._open_thread.is_alive()
                    ):
                        # The snapshot above is a separate critical
                        # section: a press can open, or even install,
                        # in between. Spawning on the stale snapshot
                        # would race two opens onto one device.
                        continue
                    if now < self._next_attempt:
                        continue
                    self._open_error = None
                    opener = threading.Thread(
                        target=self._open,
                        args=(self._generation,),
                        name="mirabel-voice-mic-open",
                        daemon=True,
                    )
                    self._open_thread = opener
                    self._next_attempt = now + self._reopen_backoff
                    self._reopen_backoff = min(
                        self._reopen_backoff * 2, REOPEN_BACKOFF_CAP_SECONDS
                    )
                    opener.start()

    def set_device(self, index) -> None:  # noqa: ANN001 - index matches self.device
        """Point the recorder at another microphone.

        Hot mode cycles the stream so the supervisor reopens it on the
        new device at once, free of any backoff the old device earned.
        A swap during a recording waits for the stop or cancel; the
        words being spoken outrank the switch.
        """
        self.device = index
        if not self._hot:
            return
        self._cycle_stream()

    def _cycle_stream(self) -> None:
        """Close the hot stream so the supervisor reopens it promptly.

        The armed check lives in the same locked section as the close:
        checking first and closing later would let a press arm in the
        gap and lose its stream mid-word.
        """
        with self._lock:
            if self._armed:
                self._pending_device = True
                return
            self._pending_device = False
            # The bump makes an open still in flight discard whatever
            # it delivers: that open belongs to the old device, and
            # installing it would leave dictation on the microphone the
            # user just switched away from.
            self._generation += 1
            stream, self._stream = self._stream, None
            self._clear_ring_locked()
            self._reopen_backoff = REOPEN_BACKOFF_START_SECONDS
            self._next_attempt = 0.0
        self._discard(stream)


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
