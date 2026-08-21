"""The small window that shows what the app is doing.

The window has two jobs. It shows a short status line for the whole
dictation cycle, so that a wait never looks like a failure. It also shows
your words while you speak, when live streaming is on. The words win when
both want the window, because the words are the more useful thing.

The window has no border, sits above other windows, never takes the
keyboard focus, and passes clicks through to whatever is underneath. It
must not take the focus: the text has to go to the program you are
typing in, not to us.

Tkinter needs one thread that owns the window and does all the work on it.
This module keeps that thread private. The app calls update, status, and
hide from any thread.
"""

from __future__ import annotations

import logging
import queue
import threading

from .app import (
    INSERTED_PREFIX,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_WORKING,
)
from .tray import COLOURS

log = logging.getLogger(__name__)

WIDTH = 460
MARGIN = 24
BOTTOM_GAP = 90
MIN_WIDTH = 180
MIN_HEIGHT = 44
FONT = ("Segoe UI", 12)
STATUS_FONT = ("Segoe UI", 11)
DOT_FONT = ("Segoe UI", 13)
BACKGROUND = "#1F2730"
FOREGROUND = "#F2F5F7"
HINT = "#7F8C99"
POLL_MS = 40

# How long a message stays on screen when the cycle has already ended.
NOTE_MS = 2500
ERROR_MS = 4500

# The dot repeats the colour of the tray icon, so that the two can never
# say different things about the same state.
DOTS = {state: "#%02X%02X%02X" % rgb for state, rgb in COLOURS.items()}

LINES = {
    STATE_RECORDING: "Listening",
    STATE_WORKING: "Writing your text",
}


def status_line(state: str, detail: str) -> tuple[str, int]:
    """Return the words for the panel, and how long they stay.

    An empty string means show nothing. A time of 0 means the words stay
    until the state changes again.
    """
    if state in LINES:
        return LINES[state], 0
    if state == STATE_ERROR:
        return detail or "Something went wrong", ERROR_MS
    # The cycle ended. Say nothing when the text was delivered, because
    # the text is the answer. Say the reason when it was not.
    if detail and not detail.startswith(INSERTED_PREFIX):
        return detail, NOTE_MS
    return "", 0


class Overlay:
    """Show a status line, or the live words, near the bottom of the screen."""

    def __init__(self) -> None:
        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._root = None
        self._label = None
        self._dot = None
        self.hwnd = 0
        self._started = threading.Event()
        # The four below are read and written on the overlay thread only.
        self._words = ""
        self._status = ""
        self._state = STATE_IDLE
        self._token = 0

    def start(self) -> bool:
        """Open the hidden window. Return False when Tkinter is missing."""
        try:
            import tkinter  # noqa: F401
        except ImportError:
            log.info("Tkinter is not available. The status panel is off.")
            return False
        self._thread = threading.Thread(
            target=self._run, name="mirabel-voice-overlay", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        return self._started.is_set()

    def update(self, text: str) -> None:
        """Show the live words, or drop them when the text is empty."""
        self._commands.put(("text", text))

    def status(self, state: str, detail: str = "") -> None:
        """Show what the app is doing now."""
        self._commands.put(("status", (state, detail)))

    def hide(self) -> None:
        """Take the window off the screen."""
        self._commands.put(("text", ""))
        self._commands.put(("status", (STATE_IDLE, "")))

    def stop(self) -> None:
        """Close the window and wait for its thread to end.

        The wait matters: Tkinter must destroy the window on the thread
        that made it, or the interpreter reports an error as it exits.
        """
        self._commands.put(("quit", ""))
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ---- everything below runs on the overlay thread ----

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._root = tk.Tk()
            self._root.withdraw()
            self._root.overrideredirect(True)  # no title bar, no border
            self._root.attributes("-topmost", True)
            self._root.configure(bg=BACKGROUND)
            try:
                self._root.attributes("-alpha", 0.94)
            except tk.TclError:
                pass
            self._dot = tk.Label(
                self._root,
                text="●",
                font=DOT_FONT,
                bg=BACKGROUND,
                fg=DOTS[STATE_IDLE],
                padx=0,
                pady=0,
            )
            self._label = tk.Label(
                self._root,
                text="",
                font=FONT,
                bg=BACKGROUND,
                fg=FOREGROUND,
                wraplength=WIDTH - 2 * MARGIN,
                justify="left",
                anchor="w",
                padx=MARGIN,
                pady=14,
            )
            self._label.pack(fill="both", expand=True)
            self._root.update_idletasks()
            self._make_unfocusable()
            self._started.set()
            self._root.after(POLL_MS, self._drain)
            self._root.mainloop()
        except Exception:  # noqa: BLE001 - the panel is never essential
            log.warning("The status panel stopped.", exc_info=True)
        finally:
            # Release the window here, on the thread that created it.
            self._label = None
            self._dot = None
            self._root = None
            self._started.set()

    def _drain(self) -> None:
        """Apply the commands the app queued since the last check."""
        try:
            while True:
                action, value = self._commands.get_nowait()
                if action == "quit":
                    self._root.quit()
                    self._root.destroy()
                    return
                if action == "status":
                    self._apply_status(*value)
                else:
                    self._words = value
                    self._render()
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            log.debug("A panel update failed.", exc_info=True)
        if self._root is not None:
            self._root.after(POLL_MS, self._drain)

    def _apply_status(self, state: str, detail: str) -> None:
        """Show the new state, and time it out when it is only a message."""
        text, milliseconds = status_line(state, detail)
        self._status = text
        self._state = state
        # Every status cancels the timer of the one before it.
        self._token += 1
        self._render()
        if text and milliseconds:
            token = self._token
            self._root.after(milliseconds, lambda: self._expire(token))

    def _expire(self, token: int) -> None:
        """Drop a timed message, unless a newer one replaced it."""
        if token != self._token:
            return
        self._status = ""
        self._render()

    def _render(self) -> None:
        """Put the words on screen, or the status, or nothing."""
        if self._words:
            self._draw(self._words, None)
        elif self._status:
            self._draw(self._status, self._state)
        else:
            self._hide_window()

    def _draw(self, text: str, state: str | None) -> None:
        """Size the window to its contents and show it.

        A state of None means these are the live words, which get a fixed
        width and no dot. A state means this is a status line, which gets
        a coloured dot and only the width it needs.
        """
        if state is None:
            self._dot.pack_forget()
            self._label.configure(
                text=text, font=FONT, fg=FOREGROUND, wraplength=WIDTH - 2 * MARGIN
            )
        else:
            self._dot.configure(fg=DOTS.get(state, DOTS[STATE_IDLE]))
            self._dot.pack(side="left", before=self._label)
            self._label.configure(
                text=text, font=STATUS_FONT, fg=FOREGROUND, wraplength=0
            )
        self._root.update_idletasks()
        width = WIDTH if state is None else max(self._root.winfo_reqwidth(), MIN_WIDTH)
        height = max(self._root.winfo_reqheight(), MIN_HEIGHT)
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = screen_height - height - BOTTOM_GAP
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        self._show_without_focus()

    def _make_unfocusable(self) -> None:
        """Stop the window taking the focus, or catching a click.

        The words must go to the program the user is typing in. A panel
        that steals the focus would also make the app believe the user had
        changed window, and it would stop typing altogether. A panel that
        swallowed a click would eat one the user meant for the window
        underneath, so clicks pass straight through it as well.
        """
        try:
            import ctypes

            # wm_frame gives the real top level window. winfo_id gives an
            # inner one, and a style set there has no effect.
            try:
                self.hwnd = int(self._root.wm_frame(), 16)
            except Exception:  # noqa: BLE001
                self.hwnd = int(self._root.winfo_id())
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                self.hwnd,
                GWL_EXSTYLE,
                style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT,
            )
        except Exception:  # noqa: BLE001 - not Windows
            self.hwnd = 0
            return
        self._prime()

    def _prime(self) -> None:
        """Show and hide the window once, out of sight, at startup.

        Windows activates a window the first time it appears, even one
        marked as never to be activated. Doing that here means it happens
        while the user is not dictating. Every later appearance then
        leaves the keyboard focus where it belongs.
        """
        try:
            import ctypes

            user32 = ctypes.windll.user32
            SW_HIDE = 0
            SW_SHOWNA = 8
            previous = user32.GetForegroundWindow()
            self._root.geometry("1x1+-200+-200")
            user32.ShowWindow(self.hwnd, SW_SHOWNA)
            self._root.update()
            user32.ShowWindow(self.hwnd, SW_HIDE)
            if previous:
                user32.SetForegroundWindow(previous)
        except Exception:  # noqa: BLE001 - priming is best-effort
            log.debug("The panel was not primed.", exc_info=True)

    def _show_without_focus(self) -> None:
        """Put the window on screen without activating it."""
        if not self.hwnd:
            self._root.deiconify()
            return
        import ctypes

        user32 = ctypes.windll.user32
        SW_SHOWNA = 8  # show, but do not activate
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        user32.ShowWindow(self.hwnd, SW_SHOWNA)
        user32.SetWindowPos(
            self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _hide_window(self) -> None:
        """Hide the window without letting Tkinter unmap it.

        Tkinter's own withdraw takes the window off the screen entirely.
        Showing it again then counts as a first appearance, and Windows
        activates it. Hiding it this way keeps that from happening.
        """
        if not self.hwnd:
            self._root.withdraw()
            return
        import ctypes

        ctypes.windll.user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
