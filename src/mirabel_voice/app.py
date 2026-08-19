"""The dictation pipeline.

One cycle runs in this order:

1. The hotkey goes down. The recorder opens the microphone.
2. The hotkey comes up. The recorder returns the audio.
3. A worker thread sends the audio to Whisper.
4. The same thread sends the transcript to Claude for a cleanup.
5. The injector puts the text into the active window.

Steps 3 to 5 run off the keyboard thread. The hotkey therefore stays
responsive while a transcript is in progress.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .audio import Recorder
from .cleanup import Cleaner
from .config import Config
from .dictionary import all_words
from .hotkey import HotkeyListener, UnknownHotkeyError
from .inject import (
    LiveTyper,
    TextInjector,
    foreground_window,
    modifiers_held,
)
from .streaming import SAMPLE_RATE as STREAM_RATE
from .streaming import StreamingSession
from .streaming import available as streaming_available
from .transcribe import TranscriptionError, Transcriber

log = logging.getLogger(__name__)

# The wait before a re-paste, so the user can release the combo keys.
# A paste sent while Shift and Alt are still down becomes Ctrl+Shift+Alt+V.
PASTE_LAST_DELAY_SECONDS = 0.4

STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_WORKING = "working"
STATE_ERROR = "error"

SILENCE_PEAK = 0.01  # Below this level the microphone captured nothing.


class _FocusMoved(Exception):
    """The user changed window, so the app must not edit any text."""


class VoiceApp:
    """Hold the parts together and run one dictation cycle at a time."""

    def __init__(
        self,
        config: Config,
        recorder: Recorder | None = None,
        transcriber: Transcriber | None = None,
        cleaner: Cleaner | None = None,
        injector: TextInjector | None = None,
        on_state: Callable[[str, str], None] | None = None,
        stream=None,  # noqa: ANN001 - a StreamingSession, or None to build one
    ) -> None:
        self.config = config
        self._stream = stream
        self.streaming = config.streaming_enabled and (
            stream is not None or streaming_available()
        )
        # The live socket accepts one sample rate only.
        rate = STREAM_RATE if self.streaming else config.sample_rate
        self.recorder = recorder or Recorder(
            sample_rate=rate,
            device=config.input_device,
            max_seconds=config.max_seconds,
        )
        words = all_words(config.custom_words)
        self.transcriber = transcriber or Transcriber(
            model=config.transcribe_model,
            language=config.language,
            custom_words=words,
        )
        self.cleaner = cleaner or Cleaner(
            model=config.cleanup_model,
            timeout=config.cleanup_timeout,
            custom_words=words,
        )
        self.injector = injector or TextInjector(
            method=config.inject_method,
            restore_clipboard=config.restore_clipboard,
        )
        self._on_state = on_state
        self.on_partial: Callable[[str], None] | None = None
        self.live_insert = config.live_insert and self.streaming
        self.typer = LiveTyper(self.injector) if self.live_insert else None
        self._focus = foreground_window
        self._focus_at_start = 0
        self.state = STATE_IDLE
        self.last_text = ""
        self._session = None
        self._listener: HotkeyListener | None = None
        self._worker: threading.Thread | None = None
        self._paste_thread: threading.Thread | None = None

    def _set_state(self, state: str, detail: str = "") -> None:
        """Record the new state and tell the tray icon about it."""
        self.state = state
        if self._on_state is not None:
            try:
                self._on_state(state, detail)
            except Exception:  # noqa: BLE001 - the icon must not break the pipeline
                log.exception("A status update failed.")

    def _beep(self, frequency: int, duration_ms: int) -> None:
        """Play a short tone, if the settings allow it."""
        if not self.config.play_sounds:
            return
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception:  # noqa: BLE001 - sound is optional
            pass

    def start_recording(self) -> bool:
        """Open the microphone. Return True when a recording started."""
        if self.state == STATE_RECORDING:
            return True
        if self._worker is not None and self._worker.is_alive():
            log.info("The previous transcript is still in progress.")
            return False
        # The microphone opens first and the socket connects beside it.
        # Nothing may delay the recording: the first word matters most.
        self._session = None
        self.recorder.on_chunk = None
        # Remember the window we type into. If it changes, we must not
        # delete anything: those characters belong to somebody else now.
        self._focus_at_start = self._focus()
        try:
            self.recorder.start()
        except Exception as error:  # noqa: BLE001
            log.exception("The microphone did not open.")
            self._set_state(STATE_ERROR, f"Microphone error: {error}")
            return False
        self._open_stream()
        self._warm_cleanup()
        self._set_state(STATE_RECORDING)
        self._beep(880, 60)
        return True

    def _warm_cleanup(self) -> None:
        """Open the cleanup connection while the user is still speaking.

        A connection goes cold after a few idle minutes, and reopening it
        costs more than the cleanup call itself. Speaking gives us free
        time to pay that cost.
        """
        if not self.config.cleanup_enabled:
            return

        def ping() -> None:
            try:
                self.cleaner.client.messages.count_tokens(
                    model=self.cleaner.model,
                    messages=[{"role": "user", "content": "hi"}],
                )
            except Exception:  # noqa: BLE001 - warming up is best-effort
                log.debug("The cleanup warm-up failed.", exc_info=True)

        threading.Thread(
            target=ping, name="mirabel-voice-warm-cleanup", daemon=True
        ).start()

    def _open_stream(self) -> None:
        """Begin the live socket and feed it the microphone, if enabled.

        Audio captured before the socket is ready is held and sent on
        connect, so no speech is lost to connection time.
        """
        if not self.streaming:
            return
        session = self._stream or StreamingSession(
            model=self.config.streaming_model,
            keywords=self.transcriber.custom_words,
            language=self.config.language,
        )
        session.on_delta = self._show_partial
        try:
            if not session.start():
                return
        except Exception:  # noqa: BLE001 - the upload path is the safety net
            log.warning("The live socket did not start.", exc_info=True)
            return
        self._session = session
        self.recorder.on_chunk = session.send

    def _close_stream(self) -> None:
        """Drop the live socket without asking for a transcript."""
        self.recorder.on_chunk = None
        session, self._session = self._session, None
        if session is not None:
            session.cancel()
        self._erase_live_words()
        if self.on_partial is not None:
            self._show_partial("")

    def _erase_live_words(self) -> None:
        """Take back the words the app typed, if it may still do so."""
        if self.typer is None or not self.typer.typed:
            return
        if self._focus() != self._focus_at_start:
            self.typer.typed = ""  # another window owns them now
            return
        try:
            self.typer.clear()
        except Exception:  # noqa: BLE001
            log.debug("The live words were not removed.", exc_info=True)

    def _show_partial(self, text: str) -> None:
        """Show the words heard so far, in the field or in the overlay.

        Typing into the field only works while no modifier key is held.
        With a hotkey such as Ctrl+Win that means it works in hands-free
        mode, after a double-tap, and not while the keys are held down.
        The overlay covers the rest, so words are always visible.
        """
        if self._can_type_live(text):
            try:
                self.typer.show(text)
                self._notify_overlay("")
                return
            except Exception:  # noqa: BLE001 - typing must not break dictation
                log.debug("A live keystroke failed.", exc_info=True)
        self._notify_overlay(text)

    def _can_type_live(self, text: str) -> bool:
        """Return True when the words may go straight into the field."""
        return bool(
            text
            and self.typer is not None
            and not modifiers_held()
            and self._focus() == self._focus_at_start
        )

    def _notify_overlay(self, text: str) -> None:
        """Send the words to the small preview window, if there is one."""
        if self.on_partial is None:
            return
        try:
            self.on_partial(text)
        except Exception:  # noqa: BLE001 - the overlay must not break dictation
            log.debug("A live word update failed.", exc_info=True)

    def stop_recording(self) -> None:
        """Close the microphone and process the audio in a worker thread."""
        if self.state != STATE_RECORDING:
            return
        recording = self.recorder.stop()
        self.recorder.on_chunk = None
        self._beep(660, 60)
        session, self._session = self._session, None

        if recording.duration < self.config.min_seconds:
            if session is not None:
                session.cancel()
            self._show_partial("")
            self._set_state(STATE_IDLE, "That was too short.")
            return
        if recording.peak < SILENCE_PEAK:
            if session is not None:
                session.cancel()
            self._show_partial("")
            self._set_state(STATE_IDLE, "The microphone captured no sound.")
            return

        self._set_state(STATE_WORKING)
        self._worker = threading.Thread(
            target=self._process,
            args=(recording, session),
            name="mirabel-voice-worker",
            daemon=True,
        )
        self._worker.start()

    def paste_last(self) -> None:
        """Send the previous transcript to the active window again.

        The paste runs on its own thread after a short wait, so the user
        can release the combo keys and the keyboard hook stays responsive.
        """
        if not self.last_text:
            return

        def worker() -> None:
            time.sleep(PASTE_LAST_DELAY_SECONDS)
            try:
                self.injector.send(self.last_text)
            except Exception:  # noqa: BLE001 - a re-paste must never crash the app
                log.exception("The re-paste failed.")

        self._paste_thread = threading.Thread(
            target=worker, name="mirabel-voice-paste-last", daemon=True
        )
        self._paste_thread.start()

    def cancel_recording(self) -> None:
        """Throw away the current recording."""
        if self.state != STATE_RECORDING:
            return
        self.recorder.cancel()
        self._close_stream()
        self._set_state(STATE_IDLE, "Cancelled.")

    def _process(self, recording, session=None) -> None:  # noqa: ANN001
        """Transcribe, clean, and inject one recording.

        The live socket usually has the words already. The upload path
        runs whenever it does not, so no dictation depends on the socket.
        """
        text = ""
        if session is not None:
            try:
                text = session.finish() or ""
            except Exception:  # noqa: BLE001 - fall back to the upload
                log.warning("The live transcript failed.", exc_info=True)
            if not text:
                log.info("No live transcript. Uploading the audio instead.")
        self._show_partial("")

        if not text:
            try:
                text = self.transcriber.transcribe(recording)
            except TranscriptionError as error:
                log.error("Transcription failed: %s", error)
                self._set_state(STATE_ERROR, f"Transcription failed: {error}")
                return

        if not text:
            self._set_state(STATE_IDLE, "No words were heard.")
            return

        if self.config.cleanup_enabled:
            text = self.cleaner.clean(text)

        self.last_text = text
        try:
            self._deliver(text)
        except _FocusMoved:
            return  # _deliver already explained what happened
        except Exception as error:  # noqa: BLE001
            log.exception("The text did not reach the window.")
            self._set_state(STATE_ERROR, f"Could not insert the text: {error}")
            return

        words = len(text.split())
        self._set_state(STATE_IDLE, f"Inserted {words} words.")

    def _deliver(self, text: str) -> None:
        """Put the finished text where the user was typing.

        When the app typed words live, it swaps its own words for the
        clean ones. If the focus moved to another window, it changes
        nothing at all: the spoken words stay where they landed, and we
        never delete characters in a window we did not write to.
        """
        if self.typer is None:
            self.injector.send(text)
            return
        if self._focus() != self._focus_at_start:
            log.warning("The window changed. Leaving the spoken words as they are.")
            self.typer.typed = ""
            self._set_state(
                STATE_ERROR,
                "You changed window, so the words were left as spoken. "
                "Press the paste-last hotkey for the clean version.",
            )
            raise _FocusMoved
        self.typer.replace_with(text)

    def start(self) -> None:
        """Begin to listen for the hotkey."""
        self._listener = HotkeyListener(
            hotkey=self.config.hotkey,
            mode=self.config.mode,
            on_start=self.start_recording,
            on_stop=self.stop_recording,
            on_cancel=self.cancel_recording,
            on_lock=self._show_hands_free,
        )
        spec = self.config.paste_last_hotkey
        if spec:
            try:
                self._listener.add_binding(spec, self.paste_last)
            except UnknownHotkeyError as error:
                log.warning("The paste-last hotkey is not valid: %s", error)
        self._listener.start()
        self._warm_connections()
        log.info(
            "Ready. Hotkey: %s (%s mode).", self.config.hotkey, self.config.mode
        )

    def _warm_connections(self) -> None:
        """Open the network connections before the first dictation.

        The first request to each API pays one to two extra seconds for
        connection setup. A cheap background call at startup pays that cost
        while the user is not waiting.
        """

        def ping() -> None:
            try:
                self.transcriber.client.models.list()
            except Exception:  # noqa: BLE001 - warming up is best-effort
                log.debug("The OpenAI warm-up call failed.", exc_info=True)
            try:
                self.cleaner.client.messages.count_tokens(
                    model=self.cleaner.model,
                    messages=[{"role": "user", "content": "hi"}],
                )
            except Exception:  # noqa: BLE001
                log.debug("The Anthropic warm-up call failed.", exc_info=True)

        threading.Thread(
            target=ping, name="mirabel-voice-warmup", daemon=True
        ).start()

    def _show_hands_free(self) -> None:
        """Update the tray only when a recording is really running."""
        if self.state == STATE_RECORDING:
            self._set_state(STATE_RECORDING, "Hands-free. Press the hotkey to stop.")

    def stop(self) -> None:
        """Stop the hotkey listener and close the microphone."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self.recorder.is_recording:
            self.recorder.cancel()

    def join(self) -> None:
        """Block until the listener stops."""
        if self._listener is not None:
            self._listener.join()
