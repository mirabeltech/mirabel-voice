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


def type_unicode(text: str) -> bool:
    """Type text as raw characters, ignoring any key the user is holding.

    Normal typing sends a virtual key for each letter. Windows joins that
    letter with any modifier the user still holds, so dictating the word
    "tab" while Ctrl is down opens a new tab. This sends the characters
    themselves instead, as VK_PACKET. There is no letter key for Ctrl to
    join, so no shortcut can fire.

    Returns False when the characters could not be sent, so the caller
    can fall back to ordinary typing.
    """
    if not text:
        return True
    try:
        return _send_unicode(text)
    except Exception:  # noqa: BLE001 - not Windows, or the call was refused
        log.debug("Unicode typing did not work.", exc_info=True)
        return False


def _send_unicode(text: str) -> bool:
    """Send one SendInput call holding every character of the text."""
    import ctypes
    from ctypes import wintypes

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class _KeyInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _MouseInput(ctypes.Structure):
        # Present only so the union is the size Windows expects. A wrong
        # size makes SendInput refuse the whole call.
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _HardwareInput(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _InputUnion(ctypes.Union):
        _fields_ = [("ki", _KeyInput), ("mi", _MouseInput), ("hi", _HardwareInput)]

    class _Input(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]

    # Characters beyond the basic range need two units in UTF-16.
    units = text.encode("utf-16-le")
    codes = [
        int.from_bytes(units[i : i + 2], "little") for i in range(0, len(units), 2)
    ]

    events = []
    for code in codes:
        for extra in (0, KEYEVENTF_KEYUP):
            item = _Input()
            item.type = INPUT_KEYBOARD
            item.ki = _KeyInput(
                wVk=0,  # a character, not a key
                wScan=code,
                dwFlags=KEYEVENTF_UNICODE | extra,
                time=0,
                dwExtraInfo=0,
            )
            events.append(item)

    # A private handle. Setting argtypes on the shared ctypes.windll.user32
    # would change it for every other library in the process, including
    # pynput, and break their own SendInput calls.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (
        wintypes.UINT,
        ctypes.POINTER(_Input),
        ctypes.c_int,
    )
    user32.SendInput.restype = wintypes.UINT
    array = (_Input * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(_Input))
    if sent != len(events):
        log.warning(
            "Windows accepted %s of %s characters (error %s).",
            sent, len(events), ctypes.get_last_error(),
        )
    return sent == len(events)


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

    def backspace(self, count: int) -> None:
        """Delete the given number of characters before the cursor."""
        if count <= 0:
            return
        from pynput.keyboard import Key

        for _ in range(count):
            self.keyboard.press(Key.backspace)
            self.keyboard.release(Key.backspace)


def modifiers_held() -> bool:
    """Return True while Ctrl, Alt, Shift, or Windows is physically down.

    Text cannot be typed while a modifier is held. Windows turns every
    character into a control code, so a text field receives nothing and a
    browser reads the result as a shortcut. The caller must show the words
    somewhere else until the user lets go.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # Ctrl, Alt, Shift, left Windows, right Windows.
        return any(
            user32.GetAsyncKeyState(code) & 0x8000
            for code in (0x11, 0x12, 0x10, 0x5B, 0x5C)
        )
    except Exception:  # noqa: BLE001 - not Windows
        return False


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

    def __init__(self, injector: TextInjector, use_unicode: bool = True) -> None:
        self.injector = injector
        self.use_unicode = use_unicode
        self.typed = ""
        # Live words arrive on the socket thread while the finished text
        # arrives on the worker thread. Without this lock the two can
        # interleave, and the user is left with half the raw words still
        # on screen followed by the clean ones.
        self._lock = threading.Lock()
        self._closed = False

    def reopen(self) -> None:
        """Allow live words again, at the start of the next dictation."""
        with self._lock:
            self._closed = False
            self.typed = ""

    def _emit(self, text: str) -> None:
        """Put characters on screen without pressing any letter key."""
        if self.use_unicode and type_unicode(text):
            return
        self.injector.keyboard.type(text)

    def show(self, text: str, allow_delete: bool = False) -> None:
        """Add the words heard so far to the field.

        While the user holds the hotkey, this only ever adds characters.
        It never deletes, because a delete key can join with the held
        modifier and eat a whole word. A transcript that revises itself
        is left alone here; the correction at the end fixes everything.
        """
        with self._lock:
            if self._closed or text == self.typed:
                return
            shared = _common_prefix(self.typed, text)
            if shared < len(self.typed):
                if not allow_delete:
                    return  # wait for the final correction
                self.injector.backspace(len(self.typed) - shared)
            remainder = text[shared:]
            if remainder:
                self._emit(remainder)
            self.typed = text

    def clear(self) -> None:
        """Remove every character this typer wrote."""
        with self._lock:
            self._closed = True
            self.injector.backspace(len(self.typed))
            self.typed = ""

    def replace_with(self, text: str) -> None:
        """Put the finished words in place of the typed ones.

        Only the part that differs is touched. The cleanup often returns
        the same words that were already on screen, and deleting and
        retyping them would make the text flicker for no reason.
        """
        with self._lock:
            # No more live words after this point. A late one would land
            # after the finished text and read as a stutter.
            self._closed = True
            if not self.typed:
                self.injector.send(text)
                return
            shared = _common_prefix(self.typed, text)
            self.injector.backspace(len(self.typed) - shared)
            remainder = text[shared:]
            if remainder:
                self._emit(remainder)
            self.typed = ""


def _common_prefix(left: str, right: str) -> int:
    """Return the number of characters the two strings share at the start."""
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            return index
    return limit
