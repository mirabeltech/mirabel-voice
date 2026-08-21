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

# The live words get a fixed width and wrap. The status pill sizes itself
# to its text, between these two, so that "Listening" and "Writing your
# text" come out the same width and the pill does not jump between them.
WIDTH = 460
STATUS_WIDTH = 250
PAD_X = 18
PAD_Y = 12
BOTTOM_GAP = 90
DOT_SIZE = 9
DOT_GAP = 10

FONT = ("Segoe UI", 12)
STATUS_FONT = ("Segoe UI", 11)
BACKGROUND = "#171B22"
FOREGROUND = "#E9EDF2"
BORDER = "#333B47"
HINT = "#7F8C99"
ALPHA = 0.95
POLL_MS = 40

# How long a message stays on screen when the cycle has already ended.
NOTE_MS = 2500
ERROR_MS = 4500

# The dot breathes while the app is busy, because a still dot during a
# two second wait is the thing this panel exists to avoid.
PULSE_MS = 90
PULSE_STEPS = 14
PULSE_FLOOR = 0.35  # how far down the dot fades, as a share of full colour

# The dot repeats the colour of the tray icon, so that the two can never
# say different things about the same state.
DOTS = {state: "#%02X%02X%02X" % rgb for state, rgb in COLOURS.items()}

LINES = {
    STATE_RECORDING: "Listening",
    STATE_WORKING: "Writing your text",
}

# The states that last until the app moves on, and so are worth animating.
BUSY = (STATE_RECORDING, STATE_WORKING)


def blend(colour: str, background: str, amount: float) -> str:
    """Mix a colour towards a background. 1.0 keeps it, 0.0 loses it."""
    top = [int(colour[i : i + 2], 16) for i in (1, 3, 5)]
    bottom = [int(background[i : i + 2], 16) for i in (1, 3, 5)]
    mixed = [round(b + (t - b) * amount) for t, b in zip(top, bottom)]
    return "#%02X%02X%02X" % tuple(mixed)


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
        self._row = None
        self._label = None
        self._dot = None
        self._blob = None
        self.hwnd = 0
        self._started = threading.Event()
        # Everything below is read and written on the overlay thread only.
        self._words = ""
        self._status = ""
        self._state = STATE_IDLE
        self._token = 0
        self._phase = 0

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
                self._root.attributes("-alpha", ALPHA)
            except tk.TclError:
                pass
            # One row, centred in the window. The window is sized to the
            # row, so the padding around it is the same on every side.
            self._row = tk.Frame(self._root, bg=BACKGROUND)
            self._row.pack(expand=True)
            self._dot = tk.Canvas(
                self._row,
                width=DOT_SIZE,
                height=DOT_SIZE,
                bg=BACKGROUND,
                highlightthickness=0,
                bd=0,
            )
            self._blob = self._dot.create_oval(
                0, 0, DOT_SIZE - 1, DOT_SIZE - 1, fill=DOTS[STATE_IDLE], outline=""
            )
            self._label = tk.Label(
                self._row,
                text="",
                font=FONT,
                bg=BACKGROUND,
                fg=FOREGROUND,
                justify="left",
                anchor="w",
                padx=0,
                pady=0,
            )
            self._label.pack(side="left")
            self._root.update_idletasks()
            self._make_unfocusable()
            self._shape()
            self._started.set()
            self._root.after(POLL_MS, self._drain)
            self._root.mainloop()
        except Exception:  # noqa: BLE001 - the panel is never essential
            log.warning("The status panel stopped.", exc_info=True)
        finally:
            # Release the window here, on the thread that created it.
            self._label = None
            self._dot = None
            self._row = None
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
        # Every status cancels the timer and the animation of the one
        # before it.
        self._token += 1
        self._phase = 0
        self._render()
        if not text:
            return
        if milliseconds:
            token = self._token
            self._root.after(milliseconds, lambda: self._expire(token))
        elif state in BUSY:
            self._pulse(self._token)

    def _expire(self, token: int) -> None:
        """Drop a timed message, unless a newer one replaced it."""
        if token != self._token:
            return
        self._status = ""
        self._render()

    def _pulse(self, token: int) -> None:
        """Fade the dot down and back while the app is busy."""
        if token != self._token or self._words or not self._status:
            return
        self._phase = (self._phase + 1) % PULSE_STEPS
        # A triangle: down for half the steps, back up for the other half.
        half = PULSE_STEPS / 2
        distance = abs(self._phase - half) / half
        self._tint(PULSE_FLOOR + (1.0 - PULSE_FLOOR) * distance)
        self._root.after(PULSE_MS, lambda: self._pulse(token))

    def _tint(self, amount: float) -> None:
        """Set how strong the dot's colour is, without moving anything."""
        if self._dot is None:
            return
        full = DOTS.get(self._state, DOTS[STATE_IDLE])
        self._dot.itemconfigure(self._blob, fill=blend(full, BACKGROUND, amount))

    def _render(self) -> None:
        """Put the words on screen, or the status, or nothing."""
        if self._words:
            self._draw(self._words, None)
        elif self._status:
            self._draw(self._status, self._state)
        else:
            self._hide_window()

    def _draw(self, text: str, state: str | None) -> None:
        """Lay the row out, size the window to it, and show it.

        A state of None means these are the live words, which get the full
        width and no dot. A state means this is a status line, which gets
        a coloured dot and only the width it needs.
        """
        if state is None:
            self._dot.pack_forget()
            self._label.configure(
                text=text, font=FONT, wraplength=WIDTH - 2 * PAD_X
            )
            fixed = WIDTH
        else:
            self._tint(1.0)
            self._dot.pack(side="left", padx=(0, DOT_GAP), before=self._label)
            self._label.configure(
                text=text, font=STATUS_FONT, wraplength=WIDTH - 2 * PAD_X - DOT_SIZE
            )
            fixed = 0
        self._root.update_idletasks()

        width = fixed or min(
            max(self._row.winfo_reqwidth() + 2 * PAD_X, STATUS_WIDTH), WIDTH
        )
        height = self._row.winfo_reqheight() + 2 * PAD_Y
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = screen_height - height - BOTTOM_GAP
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        # Tk holds a geometry request until it next goes idle. Showing the
        # window before that lands puts it wherever it was last time.
        self._root.update_idletasks()
        self._show_without_focus()

    def _shape(self) -> None:
        """Ask Windows 11 to round the corners and draw a hairline edge.

        A borderless rectangle looks like something half drawn, and the
        panel is nearly the colour of a dark desktop without an edge to
        it. Windows 10 refuses both requests and keeps a plain square
        window, which is still perfectly readable.
        """
        if not self.hwnd:
            return
        try:
            import ctypes

            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWA_BORDER_COLOR = 34
            DWMWCP_ROUND = 2
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute(
                self.hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
                ctypes.sizeof(ctypes.c_int),
            )
            # DWM wants blue, green, red, in that order.
            red, green, blue = (int(BORDER[i : i + 2], 16) for i in (1, 3, 5))
            dwm.DwmSetWindowAttribute(
                self.hwnd,
                DWMWA_BORDER_COLOR,
                ctypes.byref(ctypes.c_int(red | (green << 8) | (blue << 16))),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:  # noqa: BLE001 - older Windows, or not Windows
            log.debug("The panel was left square and unedged.", exc_info=True)

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
