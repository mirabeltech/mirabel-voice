"""Put the finished text into the program that has the keyboard focus.

Two methods are available:

* "paste" copies the text and sends Ctrl+V. It is fast and it keeps every
  character correct. It uses the clipboard for a moment.
* "type" sends one keystroke per character. It is slow, but some programs
  block a paste.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

PASTE_SETTLE_SECONDS = 0.05
# The wait before the old clipboard content goes back. A busy program can
# read the clipboard well after the Ctrl+V arrives. A restore that comes
# first makes that program paste the old content instead of the dictation.
# The wait runs on a timer, off the critical path: the caller gets the
# paste at once, and the restore happens behind it.
CLIPBOARD_RESTORE_SECONDS = 1.0


def clipboard_sequence() -> int | None:
    """Return the counter that Windows raises on every clipboard change.

    Returns None when the counter is not available (not Windows).
    """
    try:
        import ctypes

        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:  # noqa: BLE001 - not Windows
        return None


class TextInjector:
    """Send text to the active window."""

    def __init__(
        self,
        method: str = "paste",
        restore_clipboard: bool = True,
        keyboard=None,  # noqa: ANN001 - a pynput controller, or None to build one
        clipboard=None,  # noqa: ANN001 - a pyperclip-like module, or None
        sequence=None,  # noqa: ANN001 - a clipboard-change counter, or None
    ) -> None:
        self.method = method
        self.restore_clipboard = restore_clipboard
        self._keyboard = keyboard
        self._clipboard = clipboard
        self._sequence = sequence or clipboard_sequence
        # One paste at a time: the dictation worker and a paste-last press
        # must not interleave their clipboard copy/paste/restore steps.
        self._send_lock = threading.Lock()
        self._restore_timer: threading.Timer | None = None
        self._restore_value: str | None = None

    @property
    def keyboard(self):  # noqa: ANN201
        """Return the keyboard controller. Build it on first use."""
        if self._keyboard is None:
            from pynput.keyboard import Controller

            self._keyboard = Controller()
        return self._keyboard

    @property
    def clipboard(self):  # noqa: ANN201
        """Return the clipboard module. Import it on first use."""
        if self._clipboard is None:
            import pyperclip

            self._clipboard = pyperclip
        return self._clipboard

    def send(self, text: str) -> None:
        """Insert the text at the cursor of the active window."""
        if not text:
            return
        with self._send_lock:
            if self.method == "type":
                self._send_as_keystrokes(text)
                return
            try:
                self._send_as_paste(text)
            except Exception as error:  # noqa: BLE001 - a paste can fail on locked clipboards
                log.warning("Paste failed, sending keystrokes instead: %s", error)
                self._send_as_keystrokes(text)

    def _send_as_paste(self, text: str) -> None:
        """Copy the text and send Ctrl+V.

        The restore of the old clipboard content runs on a timer, so this
        returns as soon as the paste is sent. The worker that called us can
        report the insert at once instead of standing behind the wait.
        """
        previous = None
        if self.restore_clipboard:
            # A restore may still be pending from the previous paste. Its
            # value is the user's real content; the clipboard itself holds
            # our last dictation. Carry the real content forward.
            previous = self._take_pending_restore()
            if previous is None:
                try:
                    previous = self.clipboard.paste()
                except Exception:  # noqa: BLE001 - an empty or binary clipboard is not an error
                    previous = None

        self.clipboard.copy(text)
        marker = self._sequence()
        time.sleep(PASTE_SETTLE_SECONDS)
        self._press_paste_combination()

        if previous is not None:
            self._restore_value = previous
            self._restore_timer = threading.Timer(
                CLIPBOARD_RESTORE_SECONDS, self._restore, args=(previous, marker)
            )
            self._restore_timer.daemon = True
            self._restore_timer.start()

    def _take_pending_restore(self) -> str | None:
        """Cancel a waiting restore and return the content it carried."""
        timer, self._restore_timer = self._restore_timer, None
        value, self._restore_value = self._restore_value, None
        if timer is None:
            return None
        timer.cancel()
        return value

    def _restore(self, previous: str, marker: int | None) -> None:
        """Put the old content back, unless somebody copied meanwhile."""
        self._restore_value = None
        if marker is not None and self._sequence() != marker:
            # The user or another program copied something new while
            # we waited. A restore now would destroy that copy.
            log.info("The clipboard changed, so it was not restored.")
            return
        try:
            self.clipboard.copy(previous)
        except Exception as error:  # noqa: BLE001
            log.warning("Could not restore the clipboard: %s", error)

    def flush_restore(self, timeout: float = 2.0) -> None:
        """Wait for a pending clipboard restore to finish, if there is one."""
        timer = self._restore_timer
        if timer is not None:
            timer.join(timeout)

    def _press_paste_combination(self) -> None:
        """Send the Ctrl+V key combination."""
        from pynput.keyboard import Key

        controller = self.keyboard
        controller.press(Key.ctrl)
        try:
            controller.press("v")
            controller.release("v")
        finally:
            controller.release(Key.ctrl)

    def _send_as_keystrokes(self, text: str) -> None:
        """Send the text one character at a time."""
        self.keyboard.type(text)


def foreground_window() -> int:
    """Return a number that identifies the window with the keyboard focus.

    Returns 0 when Windows cannot tell us. The caller must then assume the
    focus may have moved and must not delete anything.
    """
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:  # noqa: BLE001 - not Windows, or no window
        return 0
