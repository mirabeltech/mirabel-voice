"""The hot microphone: the ring, the pre-roll, the supervisor, swaps.

A real InputStream is never opened. The fake below answers as the test
dictates, and feed() delivers synthetic blocks to the recorder's
callback the way PortAudio would.
"""

import sys
import threading
import time

import numpy as np
import pytest

from mirabel_voice import audio
from mirabel_voice.audio import MicrophoneTimeout, Recorder, Recording

RATE = 16000


class FakeSounddevice:
    """A sounddevice whose InputStream behaves as the test dictates."""

    def __init__(self, block=None, fail=None):
        self.block = block or threading.Event()
        self.block.set()  # answer at once unless a test clears it
        self.fail = fail
        self.streams = []
        # Runs inside InputStream.start, the way PortAudio can deliver
        # the first callback before the open call returns.
        self.on_start = None
        outer = self

        class InputStream:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.callback = kwargs.get("callback")
                self.started = False
                self.stopped = False
                self.closed = False
                outer.streams.append(self)

            def start(self):
                outer.block.wait()
                if outer.fail is not None:
                    raise outer.fail
                self.started = True
                if outer.on_start is not None:
                    outer.on_start(self)

            def stop(self):
                self.stopped = True

            def close(self):
                self.closed = True

        self.InputStream = InputStream

    def feed(self, samples):
        """Deliver one block to the newest stream, as PortAudio would."""
        block = np.asarray(samples, dtype=np.int16).reshape(-1, 1)
        self.streams[-1].callback(block, len(block), None, None)


@pytest.fixture
def rig(monkeypatch):
    """Build hot recorders on a fake device; shut them down afterwards.

    The teardown runs before monkeypatch restores sys.modules, so a
    supervisor still ticking can never reach the real sounddevice.
    """
    made = []

    def build(fake, **kwargs):
        monkeypatch.setitem(sys.modules, "sounddevice", fake)
        kwargs.setdefault("hot", True)
        kwargs.setdefault("sample_rate", RATE)
        recorder = Recorder(**kwargs)
        made.append(recorder)
        return recorder

    yield build
    for recorder in made:
        recorder.shutdown()


def open_stream(recorder):
    """Install a live stream the way a finished open worker would."""
    recorder._open(recorder._generation)
    assert recorder._stream is not None


def wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("the condition was not met in time")


def shrink_timings(monkeypatch):
    """Make the supervisor's clock small enough for a sub-second test."""
    monkeypatch.setattr(audio, "WATCHDOG_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(audio, "DEAD_STREAM_SECONDS", 0.05)
    monkeypatch.setattr(audio, "REOPEN_BACKOFF_START_SECONDS", 0.02)
    monkeypatch.setattr(audio, "REOPEN_BACKOFF_CAP_SECONDS", 0.5)


# --- the ring and the pre-roll ----------------------------------------------


def test_the_ring_keeps_at_most_ring_seconds_evicting_the_oldest(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    # RING_SECONDS at this rate is 32000 frames; five 8000-frame blocks
    # overflow it by exactly one block.
    for value in range(1, 6):
        fake.feed(np.full(8000, value, dtype=np.int16))
    assert recorder._ring_frames == 32000
    assert [int(block[0]) for block in recorder._ring] == [2, 3, 4, 5]


def test_arming_seeds_exactly_the_pre_roll_trimmed_to_the_frame(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)  # pre_roll_seconds 0.4 is 6400 frames here
    open_stream(recorder)
    for value in range(1, 5):
        fake.feed(np.full(4000, value, dtype=np.int16))
    recorder.start()
    assert recorder._pre_roll_frames == 6400
    assert recorder._chunk_frames == 6400
    # The oldest kept block is trimmed to the frame, not kept whole.
    assert len(recorder._chunks[0]) == 2400
    assert int(recorder._chunks[0][0]) == 3
    assert int(recorder._chunks[-1][0]) == 4


def test_arming_with_a_short_ring_keeps_what_is_there(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.ones(1000, dtype=np.int16))
    recorder.start()
    assert recorder._pre_roll_frames == 1000
    assert recorder._chunk_frames == 1000


def test_pre_roll_seconds_is_clamped_to_the_ring(rig):
    fake = FakeSounddevice()
    assert rig(fake, pre_roll_seconds=9.0)._pre_roll_seconds == audio.RING_SECONDS
    assert rig(fake, pre_roll_seconds=-1.0)._pre_roll_seconds == 0.0


def test_stop_returns_pre_roll_plus_the_press_and_keeps_the_stream(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(6400, 1, dtype=np.int16))
    recorder.start()
    fake.feed(np.full(3200, 2, dtype=np.int16))
    recording = recorder.stop()
    assert len(recording.samples) == 9600
    assert recording.pre_roll_frames == 6400
    assert int(recording.samples[0]) == 1
    assert int(recording.samples[-1]) == 2
    assert abs(recording.duration - 0.6) < 0.001
    # The too-short guard judges this: the press, not the padded clip.
    assert abs(recording.press_duration - 0.2) < 0.001
    assert recorder._stream is not None
    assert not fake.streams[0].closed
    assert recorder.hot_ready


def test_cancel_discards_the_audio_and_keeps_the_stream(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(6400, 1, dtype=np.int16))
    recorder.start()
    fake.feed(np.full(3200, 2, dtype=np.int16))
    recorder.cancel()
    assert recorder._chunks == []
    assert not recorder.is_recording
    assert recorder._stream is not None
    assert not fake.streams[0].closed


def test_back_to_back_recordings_both_get_pre_roll(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(8000, 1, dtype=np.int16))
    recorder.start()
    first = recorder.stop()
    fake.feed(np.full(8000, 2, dtype=np.int16))
    recorder.start()
    second = recorder.stop()
    assert first.pre_roll_frames == 6400
    assert second.pre_roll_frames == 6400
    assert int(second.samples[-1]) == 2


def test_the_level_reports_only_while_armed(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(100, 16000, dtype=np.int16))
    # Hot and idle: the microphone is heard, nothing is kept or shown.
    assert recorder.level == 0.0
    recorder.start()
    fake.feed(np.full(100, 16000, dtype=np.int16))
    assert 0.4 < recorder.level < 0.6
    recorder.stop()
    assert recorder.level == 0.0


def test_max_frames_caps_the_capture_including_the_pre_roll(rig):
    fake = FakeSounddevice()
    recorder = rig(fake, max_seconds=0.5)  # 8000 frames
    # The pre-roll clamps to half of max_seconds, so it can never fill
    # the whole budget: 0.25 s here, 4000 frames.
    assert recorder._pre_roll_seconds == 0.25
    open_stream(recorder)
    fake.feed(np.full(6400, 1, dtype=np.int16))
    recorder.start()
    fake.feed(np.full(4000, 2, dtype=np.int16))
    fake.feed(np.full(4000, 3, dtype=np.int16))  # over the cap: dropped
    recording = recorder.stop()
    assert len(recording.samples) == 8000
    assert recording.pre_roll_frames == 4000
    assert int(recording.samples[0]) == 1
    assert int(recording.samples[-1]) == 2


# --- a press while the stream is not live -----------------------------------


def test_a_press_joins_a_supervisor_open_and_arms_on_success(rig):
    fake = FakeSounddevice()
    fake.block.clear()  # the device is still answering the supervisor
    recorder = rig(fake)
    worker = threading.Thread(
        target=recorder._open, args=(recorder._generation,), daemon=True
    )
    recorder._open_thread = worker
    worker.start()
    generation = recorder._generation
    threading.Timer(0.05, fake.block.set).start()
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    assert recorder._pre_roll_frames == 0  # a fresh stream has no past
    assert recorder._generation == generation


def test_a_press_on_a_wedged_supervisor_open_times_out_without_a_bump(rig):
    fake = FakeSounddevice()
    fake.block.clear()
    recorder = rig(fake)
    worker = threading.Thread(
        target=recorder._open, args=(recorder._generation,), daemon=True
    )
    recorder._open_thread = worker
    worker.start()
    generation = recorder._generation
    with pytest.raises(MicrophoneTimeout):
        recorder.start(timeout=0.1)
    # The supervisor owns that open; the press must not abandon it.
    assert recorder._generation == generation
    assert not recorder.is_recording
    fake.block.set()  # let the worker finish, for teardown


# --- the supervisor ---------------------------------------------------------


def test_the_supervisor_replaces_a_stream_that_went_quiet(rig, monkeypatch):
    shrink_timings(monkeypatch)
    fake = FakeSounddevice()
    recorder = rig(fake)
    recorder.open_hot()
    wait_until(lambda: recorder._stream is not None)
    first = recorder._stream
    fake.feed(np.full(1000, 5, dtype=np.int16))
    assert recorder._ring_frames == 1000
    # The device goes quiet. The watchdog closes the stream, clears the
    # ring, and opens a replacement.
    wait_until(lambda: first.closed)
    wait_until(
        lambda: recorder._stream is not None and recorder._stream is not first
    )
    assert recorder._ring_frames == 0


def test_a_recording_after_a_dead_stream_has_no_stale_pre_roll(rig, monkeypatch):
    shrink_timings(monkeypatch)
    fake = FakeSounddevice()
    recorder = rig(fake)
    recorder.open_hot()
    wait_until(lambda: recorder._stream is not None)
    first = recorder._stream
    fake.feed(np.full(8000, 7, dtype=np.int16))  # would have been pre-roll
    wait_until(lambda: first.closed)
    wait_until(
        lambda: recorder._stream is not None and recorder._stream is not first
    )
    recorder.start()
    assert recorder.is_recording
    assert recorder._pre_roll_frames == 0
    recorder.cancel()


def test_reopen_backoff_doubles_on_failure_and_resets_on_success(rig, monkeypatch):
    shrink_timings(monkeypatch)
    fake = FakeSounddevice(fail=RuntimeError("no device"))
    recorder = rig(fake)
    recorder.open_hot()
    # Every attempt constructs a stream and then fails to start it.
    wait_until(lambda: len(fake.streams) >= 2)
    assert recorder._reopen_backoff >= 4 * audio.REOPEN_BACKOFF_START_SECONDS
    fake.fail = None
    wait_until(
        lambda: recorder._stream is not None
        and recorder._reopen_backoff == audio.REOPEN_BACKOFF_START_SECONDS
    )


# --- device swaps -----------------------------------------------------------


def test_set_device_while_idle_cycles_the_stream(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(1000, 3, dtype=np.int16))
    recorder.set_device(3)
    assert recorder.device == 3
    assert recorder._stream is None
    assert fake.streams[0].closed
    assert recorder._ring_frames == 0
    # The old device's backoff must not delay the new device's open.
    assert recorder._reopen_backoff == audio.REOPEN_BACKOFF_START_SECONDS
    assert recorder._next_attempt == 0.0


def test_set_device_while_armed_waits_for_the_stop(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    recorder.start()
    recorder.set_device(5)
    assert recorder._stream is not None  # the recording keeps its device
    assert recorder._pending_device
    recorder.stop()
    assert recorder._stream is None
    assert fake.streams[0].closed
    assert recorder._ring_frames == 0
    assert not recorder._pending_device


# --- shutdown ---------------------------------------------------------------


def test_shutdown_closes_the_stream_and_stops_the_supervisor(rig, monkeypatch):
    shrink_timings(monkeypatch)
    fake = FakeSounddevice()
    recorder = rig(fake)
    recorder.open_hot()
    wait_until(lambda: recorder._stream is not None)
    fake.feed(np.full(1000, 1, dtype=np.int16))
    supervisor = recorder._supervisor
    recorder.shutdown()
    assert recorder._stream is None
    assert fake.streams[0].closed
    assert recorder._ring_frames == 0
    assert not supervisor.is_alive()
    recorder.shutdown()  # idempotent


def test_a_late_open_worker_self_discards_after_shutdown(rig):
    fake = FakeSounddevice()
    fake.block.clear()
    recorder = rig(fake)
    worker = threading.Thread(
        target=recorder._open, args=(recorder._generation,), daemon=True
    )
    recorder._open_thread = worker
    worker.start()
    wait_until(lambda: fake.streams)  # the open is really in flight
    recorder.shutdown()
    # The driver finally answers, long after the app quit.
    fake.block.set()
    worker.join(timeout=2.0)
    assert recorder._stream is None
    assert fake.streams[0].closed


# --- the races the review confirmed -----------------------------------------


def test_shutdown_is_sticky_a_late_press_cannot_reopen(rig):
    from mirabel_voice.audio import MicrophoneCancelled

    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    recorder.shutdown()
    opened = len(fake.streams)
    # A press that was queued behind the quit must not revive the
    # microphone: the open path refuses before it bumps the generation.
    with pytest.raises(MicrophoneCancelled):
        recorder.start(timeout=2.0)
    assert len(fake.streams) == opened
    assert recorder._stream is None
    assert not recorder.is_recording


def test_set_device_mid_open_discards_the_old_devices_stream(rig):
    fake = FakeSounddevice()
    fake.block.clear()  # the old device is still answering
    recorder = rig(fake)
    worker = threading.Thread(
        target=recorder._open, args=(recorder._generation,), daemon=True
    )
    recorder._open_thread = worker
    worker.start()
    wait_until(lambda: fake.streams)  # the open is really in flight
    recorder.set_device(3)
    # The old device finally answers, after the user already left it.
    fake.block.set()
    worker.join(timeout=2.0)
    assert recorder._stream is None
    assert fake.streams[0].closed


def test_a_cold_open_keeps_the_streams_very_first_block(rig):
    # The old recorder captured from the instant the stream started. A
    # block delivered before the caller wakes from the join must land
    # in the recording, not be dropped by the arming gate.
    fake = FakeSounddevice()
    fake.on_start = lambda stream: stream.callback(
        np.full(160, 7, dtype=np.int16).reshape(-1, 1), 160, None, None
    )
    recorder = rig(fake, hot=False)
    recorder.start(timeout=2.0)
    assert recorder._chunk_frames == 160
    recording = recorder.stop()
    assert int(recording.samples[0]) == 7


def test_a_press_keeps_audio_heard_while_the_joined_open_finished(rig):
    # The press arrived before the device answered, so everything the
    # fresh stream heard belongs to the recording - as press audio, not
    # as pre-roll.
    fake = FakeSounddevice()
    fake.block.clear()
    fake.on_start = lambda stream: stream.callback(
        np.full(320, 9, dtype=np.int16).reshape(-1, 1), 320, None, None
    )
    recorder = rig(fake)
    worker = threading.Thread(
        target=recorder._open, args=(recorder._generation,), daemon=True
    )
    recorder._open_thread = worker
    worker.start()
    threading.Timer(0.05, fake.block.set).start()
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    assert recorder._chunk_frames == 320
    assert recorder._pre_roll_frames == 0
    recording = recorder.stop()
    assert int(recording.samples[0]) == 9
    assert recording.pre_roll_frames == 0


def test_a_press_ignores_a_stream_that_went_quiet(rig):
    fake = FakeSounddevice()
    recorder = rig(fake)
    open_stream(recorder)
    fake.feed(np.full(8000, 5, dtype=np.int16))  # would have been pre-roll
    # The device died and the watchdog has not noticed yet.
    recorder._last_block_at = time.monotonic() - 10.0
    assert not recorder.hot_ready
    recorder.start(timeout=2.0)
    assert recorder.is_recording
    # The press opened cold: the dead stream is closed, its last audio
    # never became pre-roll, and the capture starts clean.
    assert fake.streams[0].closed
    assert recorder._stream is not None
    assert recorder._pre_roll_frames == 0
    assert recorder._chunk_frames == 0
    recorder.cancel()


def test_pre_roll_is_clamped_to_half_of_max_seconds(rig):
    fake = FakeSounddevice()
    recorder = rig(fake, pre_roll_seconds=0.4, max_seconds=0.5)
    assert recorder._pre_roll_seconds == 0.25


def test_a_dead_stream_zeroes_the_level(rig, monkeypatch):
    shrink_timings(monkeypatch)
    fake = FakeSounddevice()
    recorder = rig(fake)
    recorder.open_hot()
    wait_until(lambda: recorder._stream is not None)
    first = recorder._stream
    fake.feed(np.full(100, 16000, dtype=np.int16))
    recorder.start()
    fake.feed(np.full(100, 16000, dtype=np.int16))
    assert recorder.level > 0.4
    # The device goes quiet mid-recording. The bars must fall flat, not
    # keep dancing on the last loud block.
    wait_until(lambda: first.closed)
    assert recorder.is_recording
    assert recorder.level == 0.0


# --- Recording --------------------------------------------------------------


def test_press_duration_without_pre_roll_equals_duration():
    recording = Recording(samples=np.zeros(RATE, dtype=np.int16), sample_rate=RATE)
    assert recording.press_duration == recording.duration == 1.0
