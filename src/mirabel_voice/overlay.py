"""The small window that shows what the app is doing.

The window shows a short status line for the whole dictation cycle, so
that a wait never looks like a failure.

The window has no border, sits above other windows, never takes the
keyboard focus, and passes clicks through to whatever is underneath. It
must not take the focus: the text has to go to the program you are
typing in, not to us.

Tkinter needs one thread that owns the window and does all the work on it.
This module keeps that thread private. The app calls status and hide from
any thread.
"""

from __future__ import annotations

import logging
import math
import queue
import threading

from . import winui
from .app import (
    INSERTED_PREFIX,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_STARTING,
    STATE_WORKING,
)
from .palette import STATE_COLOURS, hex_of, panel_palette

log = logging.getLogger(__name__)

# The status pill sizes itself to its text, between these two, so that
# "Listening" and "Writing your text" come out the same width and the
# pill does not jump between them.
WIDTH = 460
STATUS_WIDTH = 250
PAD_X = 16
PAD_Y = 11
MARGIN = 24  # above the work area, which already excludes the taskbar
BOTTOM_GAP = 90  # the old guess, kept as the fallback without a work area
DOT_SIZE = 10
DOT_GAP = 10

ALPHA = 0.95
POLL_MS = 40

# How long a message stays on screen when the cycle has already ended.
NOTE_MS = 2500
ERROR_MS = 4500
DONE_MS = 1200

# The dot breathes while the app is busy, because a still dot during a
# two second wait is the thing this panel exists to avoid.
PULSE_MS = 90
PULSE_STEPS = 14
PULSE_FLOOR = 0.35  # how far down the dot fades, as a share of full colour

# The level bars beside "Listening". Their movement proves audio is
# arriving; a flat row says the wrong microphone is selected.
BAR_HEIGHTS = (7, 13, 9, 15, 6)
BAR_WIDTH = 3
BAR_GAP = 3
BAR_FLOOR = 2

# The entrance: a short slide up from the taskbar. Four steps at the
# poll rate is about 160 ms, the Fluent "fast" duration.
SLIDE_PX = 12
SLIDE_STEPS = 4

# The default (dark) surface. blend() and the tests use this name; the
# live panel re-reads the palette on every status, so a theme change
# lands on the very next message.
BACKGROUND = "#171B22"

# The dot repeats the colour of the tray icon, so that the two can never
# say different things about the same state.
DOTS = {state: hex_of(rgb) for state, rgb in STATE_COLOURS.items()}

LINES = {
    STATE_STARTING: "Starting…",
    STATE_RECORDING: "Listening",
    STATE_WORKING: "Writing your text",
}

# The states that last until the app moves on, and so are worth animating.
# Starting belongs here: a frozen "Starting…" during a slow microphone
# open would look exactly like the hang it is reporting.
BUSY = (STATE_STARTING, STATE_RECORDING, STATE_WORKING)


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
    if state == STATE_STARTING and detail:
        # The microphone is not live yet: words spoken now are lost.
        # The second line coaches the wait; the app words it to match
        # the cue the person actually gets (beep, or the word itself).
        return f"{LINES[state]}\n{detail}", 0
    if state in LINES:
        return LINES[state], 0
    if state == STATE_ERROR:
        return detail or "Something went wrong", ERROR_MS
    # The cycle ended. A delivered dictation gets one quiet word for a
    # moment - the text on screen is the real answer - and any other
    # ending says its reason.
    if detail and detail.startswith(INSERTED_PREFIX):
        return "Done", DONE_MS
    if detail:
        return detail, NOTE_MS
    return "", 0


def is_done(state: str, text: str) -> bool:
    """Return True when the line is the delivered-dictation flash."""
    return state == STATE_IDLE and text == "Done"


class Overlay:
    """Show a status line near the bottom of the screen."""

    def __init__(self) -> None:
        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._root = None
        self._row = None
        self._label = None
        self._hint = None
        self._side = None
        self._dot = None
        self._bars = None
        self.hwnd = 0
        self._started = threading.Event()
        self._ok = False
        # The panel reads the microphone level through this, when the
        # app wires one up. It is called on the overlay thread.
        self.level_source = None
        # Everything below is read and written on the overlay thread only.
        self._status = ""
        self._state = STATE_IDLE
        self._token = 0
        self._phase = 0
        self._pal = panel_palette()
        self._scale = 1.0
        self._animate = True
        self._rounded = False
        self._visible = False
        self._body_font = ("Segoe UI", -14)
        self._strong_font = ("Segoe UI", -14, "bold")
        self._caption_font = ("Segoe UI", -12)

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
        # _run sets _started even when it fails, so that this wait never
        # hangs. _ok says whether the window really came up; without it a
        # crashed panel thread would report success and every status
        # update would queue into a dead window forever.
        return self._started.is_set() and self._ok

    def status(self, state: str, detail: str = "") -> None:
        """Show what the app is doing now."""
        self._commands.put(("status", (state, detail)))

    def hide(self) -> None:
        """Take the window off the screen."""
        self._commands.put(("status", (STATE_IDLE, "")))

    def call(self, action) -> None:  # noqa: ANN001 - a no-argument callable
        """Run an action on the window's own thread.

        The flyout uses this: Tkinter allows only the thread that made
        the root to touch any window, and this thread is it.
        """
        self._commands.put(("call", action))

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

    def _px(self, value: int) -> int:
        """Scale a design pixel to the monitor's real pixels."""
        return round(value * self._scale)

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._root = tk.Tk()
            self._root.withdraw()
            self._root.overrideredirect(True)  # no title bar, no border
            self._root.attributes("-topmost", True)
            try:
                self._root.attributes("-alpha", ALPHA)
            except tk.TclError:
                pass
            self._make_unfocusable()
            self._scale = winui.window_scale(self.hwnd)
            self._animate = winui.animations_enabled()
            self._pick_fonts()
            self._build_widgets(tk)
            self._root.update_idletasks()
            self._shape()
            self._retheme()
            self._ok = True
            self._started.set()
            self._root.after(POLL_MS, self._drain)
            self._root.mainloop()
        except Exception:  # noqa: BLE001 - the panel is never essential
            log.warning("The status panel stopped.", exc_info=True)
        finally:
            # Release the window here, on the thread that created it.
            self._label = None
            self._hint = None
            self._side = None
            self._dot = None
            self._bars = None
            self._row = None
            self._root = None
            self._started.set()

    def _pick_fonts(self) -> None:
        """Use Segoe UI Variable where Windows 11 offers it."""
        family = "Segoe UI"
        try:
            import tkinter.font as tkfont

            if "Segoe UI Variable Text" in set(tkfont.families(self._root)):
                family = "Segoe UI Variable Text"
        except Exception:  # noqa: BLE001 - any Tk without font listing
            pass
        self._body_font = (family, -self._px(14))
        self._strong_font = (family, -self._px(14), "bold")
        self._caption_font = (family, -self._px(12))

    def _build_widgets(self, tk) -> None:  # noqa: ANN001
        """Lay the row out: dot, words, level bars, and the hint lines."""
        self._row = tk.Frame(self._root)
        self._row.pack(expand=True)
        dot = self._px(DOT_SIZE)
        self._dot = tk.Canvas(
            self._row, width=dot, height=dot, highlightthickness=0, bd=0
        )
        self._dot.grid(row=0, column=0, rowspan=2, padx=(0, self._px(DOT_GAP)))
        self._label = tk.Label(
            self._row, text="", justify="left", anchor="w", padx=0, pady=0
        )
        self._label.grid(row=0, column=1, sticky="w")
        bars_width = self._px(
            len(BAR_HEIGHTS) * BAR_WIDTH + (len(BAR_HEIGHTS) - 1) * BAR_GAP
        )
        self._bars = tk.Canvas(
            self._row,
            width=bars_width,
            height=self._px(max(BAR_HEIGHTS) + 1),
            highlightthickness=0,
            bd=0,
        )
        # The side hint sits after the words ("Esc cancels"); the block
        # hint sits under them (the second line of an error).
        self._side = tk.Label(self._row, text="", padx=0, pady=0)
        self._hint = tk.Label(
            self._row, text="", justify="left", anchor="w", padx=0, pady=0
        )

    def _retheme(self) -> None:
        """Paint every widget from the palette of the moment."""
        pal = self._pal
        self._root.configure(bg=pal.background)
        if self._rounded:
            # Keep the DWM border on the theme of the moment; set once
            # at startup it would stay dark around a light pill.
            winui.round_corners(self.hwnd, pal.border)
        else:
            # Windows 10 refused the DWM corners and border. A bare dark
            # rectangle looks half drawn, so draw our own hairline edge.
            self._root.configure(
                highlightthickness=1, highlightbackground=pal.border
            )
        self._row.configure(bg=pal.background)
        self._dot.configure(bg=pal.background)
        self._bars.configure(bg=pal.background)
        self._label.configure(bg=pal.background, fg=pal.foreground)
        self._side.configure(
            bg=pal.background, fg=pal.hint, font=self._caption_font
        )
        self._hint.configure(
            bg=pal.background, fg=pal.hint, font=self._caption_font
        )

    def _drain(self) -> None:
        """Apply the commands the app queued since the last check."""
        try:
            while True:
                action, value = self._commands.get_nowait()
                if action == "quit":
                    self._root.quit()
                    self._root.destroy()
                    return
                if action == "call":
                    value()
                    continue
                self._apply_status(*value)
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
        # A theme change lands on the very next message.
        self._pal = panel_palette()
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
        """Breathe the dot, and move the bars, while the app is busy."""
        if token != self._token or not self._status:
            return
        self._phase = (self._phase + 1) % PULSE_STEPS
        # A triangle: down for half the steps, back up for the other half.
        half = PULSE_STEPS / 2
        distance = abs(self._phase - half) / half
        self._tint(PULSE_FLOOR + (1.0 - PULSE_FLOOR) * distance)
        if self._state == STATE_RECORDING:
            self._draw_bars()
        self._root.after(PULSE_MS, lambda: self._pulse(token))

    def _tint(self, amount: float) -> None:
        """Set how strong the dot's colour is, without moving anything."""
        if self._dot is None or self._state not in BUSY:
            return
        full = DOTS.get(self._state, DOTS[STATE_IDLE])
        self._draw_dot(fill=blend(full, self._pal.background, amount))

    def _draw_dot(self, fill: str | None = None) -> None:
        """Draw the dot for the state of the moment.

        Starting gets a hollow ring - the microphone is not live yet.
        Done gets a small check in the success colour. Everything else
        is the familiar filled dot in the state's colour.
        """
        if self._dot is None:
            return
        self._dot.delete("all")
        size = self._px(DOT_SIZE)
        if is_done(self._state, self._status):
            stroke = max(self._px(2), 2)
            self._dot.create_line(
                round(size * 0.08),
                round(size * 0.58),
                round(size * 0.38),
                round(size * 0.88),
                round(size * 0.95),
                round(size * 0.15),
                fill=self._pal.success,
                width=stroke,
                capstyle="round",
                joinstyle="round",
            )
            return
        colour = fill or DOTS.get(self._state, DOTS[STATE_IDLE])
        if self._state == STATE_STARTING:
            edge = max(self._px(2), 2)
            self._dot.create_oval(
                edge // 2 + 1,
                edge // 2 + 1,
                size - edge // 2 - 2,
                size - edge // 2 - 2,
                outline=colour,
                width=edge,
            )
            return
        self._dot.create_oval(0, 0, size - 1, size - 1, fill=colour, outline="")

    def _draw_bars(self) -> None:
        """Draw the level bars from the microphone's live loudness."""
        if self._bars is None:
            return
        level = 0.0
        if self.level_source is not None:
            try:
                level = max(0.0, min(float(self.level_source()), 1.0))
            except Exception:  # noqa: BLE001 - the bars are decoration
                level = 0.0
        # Speech peaks live well under full scale, so open the curve up:
        # a normal voice should reach most of the bar height.
        amp = min(level * 6.0, 1.0)
        self._bars.delete("all")
        height = self._px(max(BAR_HEIGHTS) + 1)
        floor = self._px(BAR_FLOOR)
        for index, base in enumerate(BAR_HEIGHTS):
            wobble = 0.6 + 0.4 * math.sin(self._phase * 0.9 + index * 1.7)
            bar = floor + (self._px(base) - floor) * amp * wobble
            left = index * self._px(BAR_WIDTH + BAR_GAP)
            top = (height - bar) / 2
            self._bars.create_rectangle(
                left,
                top,
                left + self._px(BAR_WIDTH),
                top + bar,
                fill=self._pal.foreground,
                outline="",
            )

    def _render(self) -> None:
        """Put the status on screen, or nothing."""
        if self._status:
            self._draw(self._status, self._state)
        else:
            self._hide_window()

    def _draw(self, text: str, state: str) -> None:
        """Lay the row out, size the window to it, and show it."""
        primary, _, hint = text.partition("\n")
        listening = state == STATE_RECORDING and self.level_source is not None
        self._retheme()
        strong = bool(hint) or state == STATE_RECORDING
        self._label.configure(
            text=primary,
            font=self._strong_font if strong else self._body_font,
            fg=self._pal.success
            if is_done(state, text)
            else self._pal.foreground,
            wraplength=self._px(WIDTH - 2 * PAD_X) - self._px(DOT_SIZE + DOT_GAP),
        )
        self._draw_dot()
        if listening:
            self._bars.grid(row=0, column=2, padx=(self._px(8), 0))
            self._draw_bars()
            self._side.configure(text="Esc cancels")
            self._side.grid(row=0, column=3, padx=(self._px(8), 0))
        else:
            self._bars.grid_remove()
            self._side.grid_remove()
        if hint:
            self._hint.configure(
                text=hint,
                wraplength=self._px(WIDTH - 2 * PAD_X)
                - self._px(DOT_SIZE + DOT_GAP),
            )
            self._hint.grid(
                row=1, column=1, columnspan=3, sticky="w", pady=(self._px(2), 0)
            )
        else:
            self._hint.grid_remove()
        self._root.update_idletasks()

        width = min(
            max(
                self._row.winfo_reqwidth() + 2 * self._px(PAD_X),
                self._px(STATUS_WIDTH),
            ),
            self._px(WIDTH),
        )
        height = self._row.winfo_reqheight() + 2 * self._px(PAD_Y)
        x, y = self._place(width, height)
        appearing = not self._visible
        self._visible = True
        if appearing and self._animate:
            self._slide(width, height, x, y, self._token)
            return
        self._root.geometry(f"{width}x{height}+{x}+{y}")
        # Tk holds a geometry request until it next goes idle. Showing the
        # window before that lands puts it wherever it was last time.
        self._root.update_idletasks()
        self._show_without_focus()

    def _place(self, width: int, height: int) -> tuple[int, int]:
        """Choose where the pill goes: the monitor the user is typing on.

        The work area already excludes the taskbar, wherever it is
        docked. Without one - not Windows, or no monitor answered - the
        old primary-screen guess still works.
        """
        area = winui.focused_work_area()
        if area is not None:
            left, top, right, bottom = area
            x = left + max((right - left - width) // 2, 0)
            y = max(bottom - height - self._px(MARGIN), top)
            return x, y
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        return (
            (screen_width - width) // 2,
            screen_height - height - self._px(BOTTOM_GAP),
        )

    def _slide(
        self, width: int, height: int, x: int, y: int, token: int
    ) -> None:
        """Slide the pill up into place, the way taskbar flyouts arrive."""
        offset = self._px(SLIDE_PX)

        def step(remaining: int) -> None:
            if token != self._token or self._root is None:
                return
            lift = round(offset * remaining / SLIDE_STEPS)
            self._root.geometry(f"{width}x{height}+{x}+{y + lift}")
            self._root.update_idletasks()
            if remaining == SLIDE_STEPS:
                self._show_without_focus()
            if remaining > 0:
                self._root.after(POLL_MS, lambda: step(remaining - 1))

        step(SLIDE_STEPS)

    def _shape(self) -> None:
        """Ask Windows 11 to round the corners and draw a hairline edge.

        Windows 10 refuses both requests; _retheme then draws a plain
        one pixel edge instead, so the panel never ships as a bare
        rectangle on either system.
        """
        self._rounded = winui.round_corners(self.hwnd, self._pal.border)

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

            # wm_frame gives the real top level window - but only once
            # that window exists. Before the first update Tk hands back
            # the inner client window instead, and a style set there has
            # no effect: the pill then lives inside a wrapper that never
            # shows. Realize the window first.
            self._root.update_idletasks()
            try:
                self.hwnd = int(self._root.wm_frame(), 16)
            except Exception:  # noqa: BLE001
                self.hwnd = int(self._root.winfo_id())
            user32 = ctypes.windll.user32
            GA_ROOT = 2
            top = user32.GetAncestor(self.hwnd, GA_ROOT)
            if top and top != self.hwnd:
                self.hwnd = top
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
        self._visible = False
        if not self.hwnd:
            self._root.withdraw()
            return
        import ctypes

        ctypes.windll.user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
