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
from .inject import TextInjector
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
    ) -> None:
        self.config = config
        self.recorder = recorder or Recorder(
            sample_rate=config.sample_rate,
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
        self.state = STATE_IDLE
        self.last_text = ""
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
        try:
            self.recorder.start()
        except Exception as error:  # noqa: BLE001
            log.exception("The microphone did not open.")
            self._set_state(STATE_ERROR, f"Microphone error: {error}")
            return False
        self._set_state(STATE_RECORDING)
        self._beep(880, 60)
        return True

    def stop_recording(self) -> None:
        """Close the microphone and process the audio in a worker thread."""
        if self.state != STATE_RECORDING:
            return
        recording = self.recorder.stop()
        self._beep(660, 60)

        if recording.duration < self.config.min_seconds:
            self._set_state(STATE_IDLE, "That was too short.")
            return
        if recording.peak < SILENCE_PEAK:
            self._set_state(STATE_IDLE, "The microphone captured no sound.")
            return

        self._set_state(STATE_WORKING)
        self._worker = threading.Thread(
            target=self._process,
            args=(recording,),
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
        self._set_state(STATE_IDLE, "Cancelled.")

    def _process(self, recording) -> None:  # noqa: ANN001
        """Transcribe, clean, and inject one recording."""
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
            self.injector.send(text)
        except Exception as error:  # noqa: BLE001
            log.exception("The text did not reach the window.")
            self._set_state(STATE_ERROR, f"Could not insert the text: {error}")
            return

        words = len(text.split())
        self._set_state(STATE_IDLE, f"Inserted {words} words.")

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
        log.info(
            "Ready. Hotkey: %s (%s mode).", self.config.hotkey, self.config.mode
        )

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
