# Hot-mic recorder with pre-roll — build spec

Status: design approved by Tommy 2026-08-28. Plan review complete the same day;
Tommy approved every recommendation. This file is the build spec for the
implementation agents. The original handoff narrative is in the PR description
and the git history of this file.

Baseline: v0.7.4, 383 tests green (verified 2026-08-28 in this worktree).
Branch: claude/quizzical-ellis-3ede25. The team merges the PR — never Claude.

## Summary

Keep one input stream open while the app runs (`hot_mic`, default true). The
callback feeds a 2-second in-memory ring buffer. The recorder discards ring
audio continuously. A press keeps the last 0.4 s of the ring (the pre-roll)
and starts the recording instantly. The cold path — `hot_mic` false, the first
open, any reopen after an error — keeps today's worker-open machinery, the
Starting state, and the coaching line.

## Final decisions (approved)

1. The ring is a bounded `collections.deque` of the callback's block copies,
   plus a running frame count. It is not a numpy circular buffer.
2. `pre_roll_seconds: float = 0.4` is a new config field, clamped to
   [0.0, 2.0]. `hot_mic: bool = True` is a new config field. Both are new
   fields, so existing config.json files get the defaults (the v0.6.2 trap
   does not apply).
3. All of the PR #57 machinery stays: worker open with deadline, generation
   counting, `MicrophoneTimeout` with `.hint`, `MicrophoneCancelled`. The hot
   path bypasses it while the stream is live. One change: in hot mode, a
   press during an in-flight open joins that worker with the press's own
   deadline instead of raising "still answering an earlier request". Cold
   mode keeps the refusal unchanged.
4. The too-short guard judges press-to-stop time, not total audio.
   `Recording` gains `pre_roll_frames: int = 0` (defaulted dataclass field)
   and a `press_duration` property. The app compares `press_duration` to
   `min_seconds`. The silence check stays whole-clip.
5. The coaching line ("Speak after the beep") shows only on the cold path.
   The hot path skips STATE_STARTING and shows "Listening" with no detail.
6. `level` reports only while a recording is armed. `is_recording` means
   armed, not "stream open".
7. Dead-stream detection: the callback stamps a monotonic time; a supervisor
   thread checks every second and declares the stream dead after 3 s without
   a callback, then closes it and reopens with backoff (1 s doubling to a
   30 s cap, reset on success). Do not use PortAudio's `finished_callback`.
8. `set_input_device` cycles the hot stream. If a recording is armed, the
   swap waits until the recording ends.
9. The system-default mic latches at open time in hot mode. Accepted;
   document it in ADMIN.md. No polling, no PortAudio reinit.
10. `cancel()` keeps the hot stream open. A new `shutdown()` closes it and
    stops the supervisor. `app.stop()` calls `shutdown()`.
11. No flyout affordance in v1. ADMIN.md and README carry the privacy copy.
12. `max_seconds` is unchanged and includes the pre-roll.

## Recorder contract (src/mirabel_voice/audio.py)

Module constants (tests monkeypatch these; keep them module-level):

    RING_SECONDS = 2.0
    WATCHDOG_INTERVAL_SECONDS = 1.0
    DEAD_STREAM_SECONDS = 3.0
    REOPEN_BACKOFF_START_SECONDS = 1.0
    REOPEN_BACKOFF_CAP_SECONDS = 30.0

`Recording` changes:

- New field `pre_roll_frames: int = 0`. Every existing constructor call
  stays valid.
- New property `press_duration -> float`: seconds captured after the press.
  `max(0.0, duration - pre_roll_frames / sample_rate)`. Guard sample_rate <= 0
  the same way `duration` does.

`Recorder.__init__` gains `hot: bool = False` and
`pre_roll_seconds: float = 0.4`. The default `hot=False` keeps every existing
test valid. Clamp pre_roll_seconds into [0.0, RING_SECONDS].

New internal state:

- `_ring: deque[np.ndarray]` and `_ring_frames: int`, guarded by `_lock`.
- `_chunk_frames: int`, a running counter that replaces the per-callback
  `sum()` in `_collected_frames`. The callback must not scan a growing list.
- `_armed: bool`, guarded by `_lock`. True while a recording collects.
- `_pre_roll_frames: int` for the recording in progress.
- `_last_block_at: float`, monotonic, written by the callback without the
  lock (a plain float store, like `_level`).
- `_pending_device: bool` — a device swap requested while armed.
- `_supervisor: threading.Thread | None` and `_shutdown: threading.Event`.

`_callback` (PortAudio thread; keep it allocation-light, lock held briefly):

1. Copy and flatten the block (unchanged). Update `_level` (unchanged).
2. Stamp `_last_block_at = time.monotonic()`.
3. Under `_lock`:
   - If hot: append the block to `_ring`, add to `_ring_frames`, then evict
     from the left while `_ring_frames - len(_ring[0]) >= ring max frames`.
   - If `_armed` and `_chunk_frames < _max_frames`: append the block to
     `_chunks` and add to `_chunk_frames`.

`start(timeout)`:

- Hot mode, stream live: under `_lock`, if already armed return. Otherwise
  arm: seed `_chunks` from the ring tail — walk blocks from the right until
  the frames reach the pre-roll target, trim the head of the oldest kept
  block to the exact frame, record `_pre_roll_frames`, set `_chunk_frames`,
  reset `_level = 0.0`, set `_armed = True`. Return. No worker, no deadline.
- Hot mode, stream not live: if an open worker is alive, `join(timeout)` it
  instead of raising the "earlier request" refusal. Do not bump the
  generation on a join timeout — the supervisor owns that open. If the join
  times out, raise `MicrophoneTimeout` with today's message and hint. If no
  worker is alive, run today's cold open (worker with deadline). On success,
  arm with NO pre-roll: the ring must be empty because every close clears it
  (see below), and stale pre-press audio from before a stream died must
  never be kept. Set `_armed = True` under `_lock` after the open succeeds.
- Cold mode (`hot=False`): today's behavior exactly, plus set
  `_armed = True` on success and clear it in `stop()`/`cancel()`.

`stop()`:

- Under `_lock`: clear `_armed`, take `_chunks`/`_chunk_frames`, take and
  reset `_pre_roll_frames`.
- Hot mode: keep the stream open. Apply a pending device swap (below).
- Cold mode: today's behavior (bump generation, discard stream).
- Return `Recording(samples, sample_rate, pre_roll_frames=pre)` where the
  samples are capped at `_max_frames` as today. `pre` never exceeds the
  sample count in practice; clamp anyway.

`cancel()`:

- Hot mode: disarm and discard `_chunks`; keep the stream; apply a pending
  device swap.
- Cold mode: today's behavior (it may just call `stop()` and drop the
  result, as now).

`open_hot()` (new; the app calls it at startup):

- No-op unless `hot=True`. Idempotent. Starts the supervisor thread
  (daemon, name "mirabel-voice-mic-supervisor"). The supervisor performs
  the first open.

`shutdown()` (new; the app calls it at quit):

- Set `_shutdown`. Under `_lock`: bump `_generation`, take the stream,
  clear the ring, disarm, discard chunks. Discard the stream outside the
  lock. Join the supervisor briefly (<= 2 s). Idempotent. Works in cold
  mode too (where it degenerates to today's `cancel()`).

Supervisor loop (hot only):

    backoff = REOPEN_BACKOFF_START_SECONDS
    next_attempt = 0.0  # monotonic deadline; 0 means "now"
    while not self._shutdown.wait(WATCHDOG_INTERVAL_SECONDS):
        snapshot stream and open-worker liveness under _lock
        if the stream is live:
            if monotonic() - _last_block_at > DEAD_STREAM_SECONDS:
                log a warning; close the stream (take it under _lock,
                discard outside, clear the ring); keep _armed and _chunks
                as they are — a recording in flight resumes after reopen
                with a gap, not a loss; next_attempt = now
            else:
                backoff = REOPEN_BACKOFF_START_SECONDS
        elif no open worker is alive and monotonic() >= next_attempt:
            spawn the open worker (today's _open, current generation)
            next_attempt = monotonic() + backoff
            backoff = min(backoff * 2, REOPEN_BACKOFF_CAP_SECONDS)

- When `_open` installs a stream, it must also stamp `_last_block_at`
  so a fresh stream is not declared dead before its first callback.
- Every path that closes the stream clears the ring under `_lock`
  (`_ring.clear()`, `_ring_frames = 0`). Stale audio must never become
  pre-roll.
- A press-initiated open and a supervisor open share `_open_thread`; both
  spawn only under `_lock` and only when no worker is alive, as today.

`set_device(index)` (new; replaces the app's bare attribute assignment):

- Assign `self.device = index`.
- Hot mode, not armed: close the stream now (take under lock, discard,
  clear ring) and reset the supervisor backoff (set a flag or reset via
  shared state; simplest: set `_last_block_at` stale is NOT acceptable —
  add `_backoff_reset: bool` the supervisor consumes, or have set_device
  set next_attempt state via an Event the supervisor checks). Keep this
  simple; the requirement is only that the reopen on the new device is not
  delayed by a previous device's backoff.
- Hot mode, armed: set `_pending_device = True`; `stop()`/`cancel()`
  perform the close-and-clear on disarm.
- Cold mode: assignment only, exact parity with today.

`hot_ready` (new property): `self._hot and self._stream is not None`.

`level`: return `self._level` if `_armed` else 0.0.

`is_recording`: return `_armed`.

## App contract (src/mirabel_voice/app.py)

- `VoiceApp.__init__` passes `hot=config.hot_mic` and
  `pre_roll_seconds=config.pre_roll_seconds` when it builds the Recorder.
- `VoiceApp.start()` calls `self.recorder.open_hot()` after the listener
  starts. The fakes get a no-op `open_hot`.
- `start_recording()`: read `hot = self.recorder.hot_ready` once at the
  top. If not hot, set STATE_STARTING with the coach detail as today. Call
  `recorder.start()` with today's exception handling, unchanged. After
  success, `_set_state(STATE_RECORDING, "" if hot else coach)`, then the
  880 Hz beep. The microsecond race (hot_ready true, stream dies before
  start) falls through to the cold open without a Starting pill; accepted.
- `stop_recording()`: replace the duration check with
  `if recording.press_duration < self.config.min_seconds`. The silence
  check is unchanged.
- `set_input_device()`: call `self.recorder.set_device(index)` instead of
  assigning `self.recorder.device`.
- `stop()`: call `self.recorder.shutdown()` instead of
  `self.recorder.cancel()`. The comment above that call changes to match.
- Do not touch `_listener_lock`, `_stopped`, `suspend_hotkeys`,
  `resume_hotkeys` (the v0.7.2 race fix).
- `cancel_recording()` is unchanged (recorder.cancel keeps the hot stream).

## Work packages

Run tests from the worktree root with:
`C:\Dev\mirabel-voice\.venv\Scripts\python.exe -m pytest tests/ -q`
(the venv lives in the main checkout; pytest's `pythonpath = ["src"]` is
rootdir-relative, so the worktree's code is what runs).

Shared rules for every package:

- Follow the file's existing comment voice: comments state constraints the
  code cannot show. No "added X" or "new in this change" comments.
- Do not commit. The orchestrator reviews and commits per package.
- Report failures verbatim; do not weaken an existing test to pass.

### Package A — recorder core (agent, first wave)

Files: `src/mirabel_voice/audio.py`, `tests/test_audio.py`,
`tests/test_hot_mic.py` (new).

1. Implement the Recorder contract above.
2. `tests/test_audio.py`: the eight worker-open tests stay as the cold
   engine suite; do not rewrite them. One test changes:
   `test_the_level_is_zero_until_a_recording_runs` gates on `_armed` now —
   set `recorder._armed = True` instead of `recorder._stream = object()`
   and assert level is 0.0 again after clearing it.
3. `tests/test_hot_mic.py` (new), using the existing `FakeSounddevice`
   pattern (import or copy; a real InputStream is never opened). Extend the
   fake so a test can invoke the recorder's `_callback` directly with
   synthetic blocks. Cover at least:
   - The ring keeps at most RING_SECONDS of frames; the oldest block is
     evicted first.
   - Arming seeds exactly `pre_roll_seconds` of frames, trimming the
     oldest kept block to the frame.
   - Arming with less than the pre-roll in the ring keeps what is there.
   - `stop()` returns pre-roll plus armed audio, `pre_roll_frames` set,
     `press_duration` excludes the pre-roll, and the stream stays open.
   - `cancel()` discards audio and keeps the stream open.
   - Two back-to-back recordings both get pre-roll.
   - `level` is 0.0 while hot and idle, live while armed, 0.0 after stop.
   - `_max_frames` caps the armed capture, including the pre-roll.
   - A press while the supervisor's open is in flight joins it: success
     arms; a wedged open raises MicrophoneTimeout without a generation
     bump.
   - The supervisor declares a silent stream dead after
     DEAD_STREAM_SECONDS, closes it, clears the ring, and reopens; backoff
     doubles on failed reopens and resets on success (monkeypatch the
     module constants small; drive time with real short sleeps or a
     patched monotonic — pick one and keep the test under a second).
   - After a dead stream, the next recording has no stale pre-roll.
   - `set_device` while idle cycles the stream; while armed it defers to
     `stop()`.
   - `shutdown()` closes the stream, stops the supervisor, and is
     idempotent; a late open worker self-discards after shutdown
     (generation bump).
   - `Recording.press_duration` on a plain Recording (no pre-roll) equals
     `duration`.
4. Run the full suite. Everything green.

### Package B — app integration (agent, second wave, after A merges into the worktree)

Files: `src/mirabel_voice/app.py`, `tests/test_app.py`,
`tests/test_status_panel.py`, `tests/test_relay_mode.py` (import only,
verify it still passes).

1. Implement the App contract above.
2. Both `FakeRecorder` classes gain: `hot_ready = False` (class attribute),
   `device = None`, and methods `set_device(index)` (assigns device),
   `open_hot()` (no-op), `shutdown()` (clears recording_now; in
   test_app.py's fake also set `cancelled = True` only if that keeps
   `test_quitting_always_cancels_the_recorder` honest — otherwise update
   that test to assert shutdown was called).
3. `test_quitting_always_cancels_the_recorder` becomes "quitting always
   shuts the recorder down": monkeypatch `shutdown` instead of `cancel`.
4. New app tests:
   - With a fake whose `hot_ready` is True, `start_recording` never emits
     STATE_STARTING and the RECORDING detail is empty.
   - With `hot_ready` False, the cold path still emits STATE_STARTING with
     the coach and RECORDING with the coach (the existing
     `test_listening_appears_only_after_the_microphone_opened` stays as
     the cold-path guarantee).
   - A recording whose `press_duration` is under `min_seconds` is refused
     as too short even when total duration (with pre-roll) is over it.
   - `set_input_device` reaches `recorder.set_device`.
   - `VoiceApp.__init__` passes `hot` and `pre_roll_seconds` from config
     to a real Recorder (build one without injection, no stream opened).
5. Run the full suite. Everything green.

### Package C — privacy copy (agent, first wave, parallel with A)

Files: `ADMIN.md`, `README.md`.

1. ADMIN.md: document `hot_mic` and `pre_roll_seconds` in the style of the
   file's existing config table or list. Plain-language privacy statement,
   approved wording: captured to a 2-second buffer in memory, discarded
   continuously, sent nowhere until you press. Note that Windows shows
   Mirabel Voice holding the microphone the whole time (tray microphone
   indicator and Settings > Privacy). Note the escape hatch
   (`hot_mic: false` restores open-on-press and its slower start). Note
   that with the system-default microphone, the hot stream keeps the
   device that was default when it opened; pick a device in the tray's
   Microphone menu to switch.
2. README.md: one short paragraph in the appropriate section saying the
   mic stays open for instant dictation, the 2-second buffer is memory
   only and continuously discarded, and `hot_mic: false` turns it off.
3. Match each file's existing tone. Do not add headings that break the
   file's structure.

### Orchestrator (not an agent)

- Config fields land before wave 1 (done by the orchestrator).
- After A and C: review diffs, run the suite, commit per package.
- After B: full suite, then the independent adversarial review pass
  (mdk-code-review) on the whole diff, fix what it confirms, then the PR.
- The team merges. Release only when Tommy says.
