"""The small window that shows your words while you speak.

The window has no border, sits above other windows, and never takes the
keyboard focus. It must not: the text has to go to the program you are
typing in, not to us.

Tkinter needs one thread that owns the window and does all the work on it.
This module keeps that thread private. The app calls show, update, and
hide from any thread.
"""

from __future__ import annotations

import logging
import queue
import threading

log = logging.getLogger(__name__)

WIDTH = 460
MARGIN = 24
BOTTOM_GAP = 90
FONT = ("Segoe UI", 12)
BACKGROUND = "#1F2730"
FOREGROUND = "#F2F5F7"
HINT = "#7F8C99"
POLL_MS = 40


class Overlay:
    """Show the live words near the bottom of the screen."""

    def __init__(self) -> None:
        self._commands: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._root = None
        self._label = None
        self._started = threading.Event()

    def start(self) -> bool:
        """Open the hidden window. Return False when Tkinter is missing."""
        try:
            import tkinter  # noqa: F401
        except ImportError:
            log.info("Tkinter is not available. The live overlay is off.")
            return False
        self._thread = threading.Thread(
            target=self._run, name="mirabel-voice-overlay", daemon=True
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        return self._started.is_set()

    def update(self, text: str) -> None:
        """Show the words, or hide the window when the text is empty."""
        self._commands.put(("text", text))

    def hide(self) -> None:
        """Hide the window."""
        self._commands.put(("text", ""))

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
            self._started.set()
            self._root.after(POLL_MS, self._drain)
            self._root.mainloop()
        except Exception:  # noqa: BLE001 - the overlay is never essential
            log.warning("The live overlay stopped.", exc_info=True)
        finally:
            # Release the window here, on the thread that created it.
            self._label = None
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
                self._apply(value)
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            log.debug("An overlay update failed.", exc_info=True)
        if self._root is not None:
            self._root.after(POLL_MS, self._drain)

    def _apply(self, text: str) -> None:
        """Show the text, or hide the window when there is none."""
        if not text:
            self._root.withdraw()
            return
        self._label.configure(
            text=text, fg=FOREGROUND if text.strip() else HINT
        )
        self._root.update_idletasks()
        height = max(self._root.winfo_reqheight(), 48)
        screen_width = self._root.winfo_screenwidth()
        screen_height = self._root.winfo_screenheight()
        x = (screen_width - WIDTH) // 2
        y = screen_height - height - BOTTOM_GAP
        self._root.geometry(f"{WIDTH}x{height}+{x}+{y}")
        self._root.deiconify()
        # Keep the window above others without ever taking the focus.
        self._root.attributes("-topmost", True)
