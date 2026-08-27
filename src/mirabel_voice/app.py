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
import queue
import threading
import time
from typing import Callable

from .audio import Recorder
from .cleanup import Cleaner
from .config import LANGUAGES, Config
from .dictionary import all_words
from .hotkey import HotkeyListener, UnknownHotkeyError
from .inject import TextInjector, foreground_window
from .transcribe import TranscriptionError, Transcriber

log = logging.getLogger(__name__)

# The wait before a re-paste, so the user can release the combo keys.
# A paste sent while Shift and Alt are still down becomes Ctrl+Shift+Alt+V.
PASTE_LAST_DELAY_SECONDS = 0.4

STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_RECORDING = "recording"
STATE_WORKING = "working"
STATE_ERROR = "error"

# The one idle message that means the cycle worked. The status panel keeps
# quiet for it, because the text on screen already says the same thing.
INSERTED_PREFIX = "Inserted "

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
        signin=None,  # noqa: ANN001 - a GoogleSignin, or None to build from config
    ) -> None:
        self.config = config
        self.signin = signin or self._build_signin(config)
        # A sign-in outranks a stored token: the token stays in the
        # settings as the escape hatch, used again the moment the
        # Google fields are removed.
        credential = self.signin.credential if self.signin else config.relay_token
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
            relay_url=config.relay_url,
            relay_token=credential,
        )
        self.cleaner = cleaner or Cleaner(
            model=config.cleanup_model,
            timeout=config.cleanup_timeout,
            custom_words=words,
            translate=config.translate_to_english,
            relay_url=config.relay_url,
            relay_token=credential,
        )
        self.injector = injector or TextInjector(
            method=config.inject_method,
            restore_clipboard=config.restore_clipboard,
        )
        self._on_state = on_state
        # The status panel listens here. The tray owns _on_state, so the
        # two displays stay independent of each other.
        self.on_status: Callable[[str, str], None] | None = None
        self._focus = foreground_window
        self._focus_at_start = 0
        self.state = STATE_IDLE
        self.last_text = ""
        self._listener: HotkeyListener | None = None
        self._hotkeys_suspended = False
        self._worker: threading.Thread | None = None
        self._paste_thread: threading.Thread | None = None
        # Hotkey presses arrive on the keyboard hook thread. Work that
        # blocks there makes the whole keyboard lag, and Windows removes
        # a hook that is slow too often. The press only queues an action;
        # this thread does the work.
        self._actions: queue.Queue = queue.Queue()
        self._dispatch_thread: threading.Thread | None = None
        self._beep_thread: threading.Thread | None = None

    @staticmethod
    def _build_signin(config: Config):  # noqa: ANN205 - a GoogleSignin, or None
        """Build the Google sign-in when the settings configure one."""
        if not (
            config.relay_url
            and config.google_client_id
            and config.google_client_secret
        ):
            return None
        from .signin import GoogleSignin

        return GoogleSignin(config.google_client_id, config.google_client_secret)

    def _cleanup_runs(self) -> bool:
        """Return True when the dictation goes through the cleanup pass.

        Translation lives in that pass, so the translate switch keeps it
        running even when the tidying is turned off. Otherwise the switch
        would be silently dead for anyone who turned the tidying off.
        """
        return self.config.cleanup_enabled or self.config.translate_to_english

    def set_language(self, code: str | None) -> None:
        """Switch the dictation language, for this dictation and the next start.

        The transcriber reads its language per call, so the switch needs
        no restart. None means the model works out each dictation's
        language itself.
        """
        self.config.language = code
        self.transcriber.language = code
        self.config.save()
        chosen = dict(LANGUAGES).get(code, "detected automatically")
        log.info("The dictation language is now %s.", chosen)
        self._set_state(self.state, f"Language: {chosen}.")

    def set_input_device(self, index: int | None) -> None:
        """Switch the microphone, for the very next recording.

        The recorder reads its device when the stream opens, so the
        switch needs no restart. None means the system default.
        """
        self.config.input_device = index
        self.recorder.device = index
        self.config.save()
        chosen = "the system default" if index is None else f"device {index}"
        log.info("The microphone is now %s.", chosen)
        self._set_state(self.state, "Microphone changed.")

    def set_translate(self, on: bool) -> None:
        """Switch the translation to English, for the very next dictation.

        The cleaner reads its flag per call, so the switch needs no
        restart. None of this touches the Language setting: that one
        stays a hint to the transcriber, and composes with this.
        """
        self.config.translate_to_english = on
        self.cleaner.translate = on
        self.config.save()
        state = "on" if on else "off"
        log.info("Translate to English is now %s.", state)
        self._set_state(self.state, f"Translate to English: {state}.")

    def set_hotkey(self, key: str) -> None:
        """Swap the dictation key, for the very next press.

        The listener parses its key at start, so the swap rebuilds it.
        A key the listener refuses leaves the old one in place.

        Raises:
            UnknownHotkeyError: The key name is not one pynput knows.
        """
        from .hotkey import parse_hotkey

        parse_hotkey(key)  # refuse a bad name before anything changes
        self.config.hotkey = key
        self.config.save()
        if self._listener is not None or self._hotkeys_suspended:
            self._stop_listener()
            self._start_listener()
            self._hotkeys_suspended = False
        log.info("The dictation key is now %s.", key)
        self._set_state(self.state, f"Dictation key: {key}.")

    def suspend_hotkeys(self) -> None:
        """Stop watching the keyboard, so another listener can have it.

        The flyout's key capture uses this: with the app still
        listening, pressing the current key mid-capture would start a
        dictation.
        """
        if self._listener is not None:
            self._stop_listener()
            self._hotkeys_suspended = True

    def resume_hotkeys(self) -> None:
        """Start watching the keyboard again after a suspend."""
        if self._hotkeys_suspended:
            self._start_listener()
            self._hotkeys_suspended = False

    def copy_last(self) -> bool:
        """Put the last dictated text on the clipboard.

        Returns whether there was anything to copy.
        """
        if not self.last_text:
            return False
        try:
            import pyperclip

            pyperclip.copy(self.last_text)
        except Exception:  # noqa: BLE001
            log.exception("The clipboard did not accept the text.")
            return False
        return True

    def _set_state(self, state: str, detail: str = "") -> None:
        """Record the new state and tell the tray icon and the panel."""
        self.state = state
        if self._on_state is not None:
            try:
                self._on_state(state, detail)
            except Exception:  # noqa: BLE001 - the icon must not break the pipeline
                log.exception("A status update failed.")
        if self.on_status is not None:
            try:
                self.on_status(state, detail)
            except Exception:  # noqa: BLE001 - the panel must not break the pipeline
                log.debug("A panel update failed.", exc_info=True)

    def _beep(self, frequency: int, duration_ms: int) -> None:
        """Play a short tone, if the settings allow it."""
        if not self.config.play_sounds:
            return
        try:
            import winsound

            winsound.Beep(frequency, duration_ms)
        except Exception:  # noqa: BLE001 - sound is optional
            pass

    def _beep_refused(self) -> None:
        """Play two low tones: the press arrived, and the app is busy.

        The tones play on their own thread. The caller can be the keyboard
        hook thread, and a blocked hook makes the whole keyboard lag.
        """

        def tones() -> None:
            self._beep(330, 60)
            self._beep(330, 60)

        self._beep_thread = threading.Thread(
            target=tones, name="mirabel-voice-beep", daemon=True
        )
        self._beep_thread.start()

    def _enqueue(self, action: Callable[[], None]) -> None:
        """Hand an action to the dispatch thread."""
        self._actions.put(action)

    def _dispatch(self) -> None:
        """Run the queued hotkey actions, one at a time, in press order."""
        while True:
            action = self._actions.get()
            if action is None:
                return
            try:
                action()
            except Exception:  # noqa: BLE001 - one bad action must not stop the rest
                log.exception("A hotkey action failed.")

    def _request_start(self) -> bool:
        """Answer a start press without blocking the keyboard hook.

        The refusal check is cheap and runs here, so the listener gets an
        honest answer at once. The slow part - opening the microphone -
        runs later on the dispatch thread. Presses stay in order because
        the queue is first in, first out.
        """
        if self.state == STATE_RECORDING:
            return True
        if self._worker is not None and self._worker.is_alive():
            log.info("The previous transcript is still in progress.")
            self._beep_refused()
            return False
        self._enqueue(self.start_recording)
        return True

    def start_recording(self) -> bool:
        """Open the microphone. Return True when a recording started."""
        if self.state == STATE_RECORDING:
            return True
        if self._worker is not None and self._worker.is_alive():
            log.info("The previous transcript is still in progress.")
            return False
        # Remember the window we paste into. If it changes, we must not
        # deliver there: that window belongs to somebody else now.
        self._focus_at_start = self._focus()
        # "Starting" until the microphone is really open. The user starts
        # to speak the moment anything says "Listening", so that word must
        # never appear before the capture is live.
        self._set_state(STATE_STARTING)
        try:
            self.recorder.start()
        except Exception as error:  # noqa: BLE001
            log.exception("The microphone did not open.")
            self._set_state(STATE_ERROR, f"Microphone error: {error}")
            self._beep_refused()
            return False
        self._warm_cleanup()
        self._warm_transcriber()
        self._set_state(STATE_RECORDING)
        self._beep(880, 60)
        return True

    def _warm_cleanup(self) -> None:
        """Open the cleanup connection while the user is still speaking.

        A connection goes cold after a few idle minutes, and reopening it
        costs more than the cleanup call itself. Speaking gives us free
        time to pay that cost.
        """
        if not self._cleanup_runs():
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

    def _warm_transcriber(self) -> None:
        """Open the transcription connection while the user is still speaking.

        The upload happens the moment the user stops, and a cold TLS
        handshake there is paid in silence, after the hotkey. The cleanup
        connection already warms this way; the transcription one did not,
        and it is the first and largest call of the pipeline.
        """

        def ping() -> None:
            try:
                self.transcriber.client.models.list()
            except Exception:  # noqa: BLE001 - warming up is best-effort
                log.debug("The transcription warm-up failed.", exc_info=True)

        threading.Thread(
            target=ping, name="mirabel-voice-warm-transcribe", daemon=True
        ).start()

    def stop_recording(self) -> None:
        """Close the microphone and process the audio in a worker thread."""
        if self.state != STATE_RECORDING:
            # The press landed, but nothing was recording. Say so, or the
            # press feels dead and the user presses again.
            self._beep_refused()
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
        """Throw away the current recording.

        Starting counts too: a cancel that lands while the microphone
        is still opening must not leave the cycle stuck.
        """
        if self.state not in (STATE_STARTING, STATE_RECORDING):
            return
        self.recorder.cancel()
        self._set_state(STATE_IDLE, "Cancelled.")

    def _process(self, recording) -> None:  # noqa: ANN001
        """Transcribe, clean, and inject one recording."""
        started = time.monotonic()
        try:
            text = self.transcriber.transcribe(recording)
        except TranscriptionError as error:
            log.error("Transcription failed: %s", error)
            self._set_state(STATE_ERROR, f"Transcription failed: {error}")
            return
        transcribed = time.monotonic()

        if not text:
            self._set_state(STATE_IDLE, "No words were heard.")
            return

        if self._cleanup_runs():
            # The settings are the one source of truth for the mode. The
            # cleaner re-reads them per dictation, so a writer that only
            # touches the settings still takes effect without a restart.
            self.cleaner.translate = self.config.translate_to_english
            text = self.cleaner.clean(text)
        cleaned = time.monotonic()

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
        # A soft high tone: the text is on screen. The insert can land
        # seconds after the hotkey, and without a signal the user starts
        # the next dictation too early or presses the hotkey again.
        self._beep(990, 50)
        self._set_state(STATE_IDLE, f"{INSERTED_PREFIX}{words} words.")
        # One line per dictation, so "it feels slow" becomes a number.
        log.info(
            "Timing: transcribe %.0f ms, cleanup %.0f ms, insert %.0f ms.",
            (transcribed - started) * 1000,
            (cleaned - transcribed) * 1000,
            (time.monotonic() - cleaned) * 1000,
        )

    def _deliver(self, text: str) -> None:
        """Put the finished text where the user was typing.

        The paste runs seconds after the hotkey, so the user may have
        moved to another window by then. A paste into that window puts
        the text in the wrong place, so the paste is held back instead.
        """
        if self._paste_focus_moved():
            log.warning("The window changed. The text was not pasted.")
            # Two lines: what happened, then what to do about it. The
            # panel shows the second line smaller and dimmer; the tray
            # tooltip carries both.
            self._set_state(
                STATE_ERROR,
                "The text was not inserted - you changed window.\n"
                "Press the paste-last hotkey to insert it here.",
            )
            self._beep_refused()
            raise _FocusMoved
        self.injector.send(text)

    def _paste_focus_moved(self) -> bool:
        """Return True when another window clearly took the focus.

        A handle of 0 means Windows could not tell us. The paste deletes
        nothing, so an unknown focus must not block it: losing a dictation
        is worse than a paste that may land one window late.
        """
        current = self._focus()
        if not current or not self._focus_at_start:
            return False
        return current != self._focus_at_start

    def _make_listener(self) -> HotkeyListener:
        """Build the keyboard listener from the settings of the moment."""
        # The listener calls these on the keyboard hook thread. Each one
        # must return at once, so the real work goes through the queue.
        listener = HotkeyListener(
            hotkey=self.config.hotkey,
            mode=self.config.mode,
            on_start=self._request_start,
            on_stop=lambda: self._enqueue(self.stop_recording),
            on_cancel=lambda: self._enqueue(self.cancel_recording),
            on_lock=lambda: self._enqueue(self._show_hands_free),
        )
        spec = self.config.paste_last_hotkey
        if spec:
            try:
                listener.add_binding(spec, self.paste_last)
            except UnknownHotkeyError as error:
                log.warning("The paste-last hotkey is not valid: %s", error)
        return listener

    def _start_listener(self) -> None:
        """Build and start the keyboard listener."""
        self._listener = self._make_listener()
        self._listener.start()

    def _stop_listener(self) -> None:
        """Stop and drop the keyboard listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def start(self) -> None:
        """Begin to listen for the hotkey."""
        self._dispatch_thread = threading.Thread(
            target=self._dispatch, name="mirabel-voice-actions", daemon=True
        )
        self._dispatch_thread.start()
        self._start_listener()
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
        # A suspend must not survive the stop: a key capture that ends
        # after the quit would otherwise restart the keyboard hook on a
        # dead app.
        self._hotkeys_suspended = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._dispatch_thread is not None:
            # The listener is silent now, so nothing new joins the queue.
            # The queued actions run, then the None ends the thread.
            self._actions.put(None)
            self._dispatch_thread.join(timeout=3.0)
            self._dispatch_thread = None
        if self.recorder.is_recording:
            self.recorder.cancel()

    def join(self) -> None:
        """Block until the listener stops."""
        if self._listener is not None:
            self._listener.join()
