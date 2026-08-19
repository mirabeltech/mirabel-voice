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
CLIPBOARD_RESTORE_SECONDS = 0.35


class TextInjector:
    """Send text to the active window."""

    def __init__(
        self,
        method: str = "paste",
        restore_clipboard: bool = True,
        keyboard=None,  # noqa: ANN001 - a pynput controller, or None to build one
        clipboard=None,  # noqa: ANN001 - a pyperclip-like module, or None
    ) -> None:
        self.method = method
        self.restore_clipboard = restore_clipboard
        self._keyboard = keyboard
        self._clipboard = clipboard
        # One paste at a time: the dictation worker and a paste-last press
        # must not interleave their clipboard copy/paste/restore steps.
        self._send_lock = threading.Lock()

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
        """Copy the text and send Ctrl+V."""
        previous = None
        if self.restore_clipboard:
            try:
                previous = self.clipboard.paste()
            except Exception:  # noqa: BLE001 - an empty or binary clipboard is not an error
                previous = None

        self.clipboard.copy(text)
        time.sleep(PASTE_SETTLE_SECONDS)
        self._press_paste_combination()

        if previous is not None:
            time.sleep(CLIPBOARD_RESTORE_SECONDS)
            try:
                self.clipboard.copy(previous)
            except Exception as error:  # noqa: BLE001
                log.warning("Could not restore the clipboard: %s", error)

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

    def backspace(self, count: int) -> None:
        """Delete the given number of characters before the cursor."""
        if count <= 0:
            return
        from pynput.keyboard import Key

        for _ in range(count):
            self.keyboard.press(Key.backspace)
            self.keyboard.release(Key.backspace)


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


class LiveTyper:
    """Type words into the focused field while the user is still speaking.

    The typer remembers exactly what it typed. That memory is what makes
    the correction at the end safe: it removes its own characters only,
    and never more than it wrote.
    """

    def __init__(self, injector: TextInjector) -> None:
        self.injector = injector
        self.typed = ""

    def show(self, text: str) -> None:
        """Make the field show this text, changing as little as possible."""
        if text == self.typed:
            return
        shared = _common_prefix(self.typed, text)
        self.injector.backspace(len(self.typed) - shared)
        remainder = text[shared:]
        if remainder:
            self.injector.keyboard.type(remainder)
        self.typed = text

    def clear(self) -> None:
        """Remove every character this typer wrote."""
        self.injector.backspace(len(self.typed))
        self.typed = ""

    def replace_with(self, text: str) -> None:
        """Swap the typed words for the finished ones."""
        self.clear()
        self.injector.send(text)


def _common_prefix(left: str, right: str) -> int:
    """Return the number of characters the two strings share at the start."""
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    return limit
