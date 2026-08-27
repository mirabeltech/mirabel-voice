"""The controls flyout: the small card a left-click on the tray opens.

The everyday controls live here - microphone, language, translation,
copy-last, and the dictation key - so the right-click menu can shrink
to the Windows minimum. Unlike the status pill this window is
interactive: it takes the focus while open and goes away the moment
the focus leaves it, like every other taskbar flyout.

The overlay owns the one Tkinter thread, so every touch of a widget
goes through Overlay.call.
"""

from __future__ import annotations

import logging
import threading

from . import winui
from .config import LANGUAGES
from .palette import OCEAN, OCEAN_ON_DARK, apps_use_light_theme, panel_palette
from .tray import LABELS
from .overlay import DOTS, Overlay

log = logging.getLogger(__name__)

WIDTH = 300
PAD = 16
MARGIN = 12  # from the corner of the work area

AUTO_DETECT = "Detect automatically"
SYSTEM_DEFAULT = "System default"
CAPTURE_PROMPT = "Press a key…"
CHANGE_KEY = "Change key…"


def app_version() -> str:
    """The installed version, or nothing when it cannot be known."""
    try:
        from importlib.metadata import version

        return f"v{version('mirabel-voice')}"
    except Exception:  # noqa: BLE001 - a missing dist-info is fine
        return ""


def language_names() -> list[str]:
    """The language choices, in menu order."""
    return [AUTO_DETECT] + [label for _, label in LANGUAGES]


def language_code(name: str) -> str | None:
    """The settings code behind a menu name."""
    for code, label in LANGUAGES:
        if label == name:
            return code
    return None


def microphone_names(devices: list[dict]) -> list[str]:
    """The microphone choices: the default, then each device once.

    Windows lists a device once per audio API; the WASAPI entries carry
    the full names, so when any exist only those are offered.
    """
    wasapi = [d for d in devices if d.get("hostapi") == "Windows WASAPI"]
    return [SYSTEM_DEFAULT] + [d["name"] for d in (wasapi or devices)]


class Flyout:
    """Build, show, and hide the controls card."""

    def __init__(self, overlay: Overlay, app) -> None:  # noqa: ANN001
        self.overlay = overlay
        self.app = app
        # Everything below is touched on the overlay thread only.
        self._top = None
        self._widgets = {}
        self._devices: list[dict] = []
        self._capturing = False

    # ---- called from any thread ----

    def show(self) -> None:
        """Open the card, or bring it back to the front."""
        self.overlay.call(self._show)

    def hide(self) -> None:
        """Take the card off the screen."""
        self.overlay.call(self._hide)

    # ---- everything below runs on the overlay thread ----

    def _show(self) -> None:
        try:
            if self._top is None:
                self._build()
            self._refresh()
            self._place()
            self._top.deiconify()
            self._top.lift()
            self._top.focus_force()
        except Exception:  # noqa: BLE001 - the flyout must never kill the app
            log.warning("The controls flyout did not open.", exc_info=True)

    def _hide(self) -> None:
        if self._top is None:
            return
        if self._capturing:
            self._end_capture(None)
        self._top.withdraw()

    def _build(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        pal = panel_palette()
        root = self.overlay._root  # noqa: SLF001 - the one Tk root
        top = tk.Toplevel(root)
        self._top = top
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=pal.background, padx=PAD, pady=PAD)

        family = "Segoe UI"
        try:
            import tkinter.font as tkfont

            if "Segoe UI Variable Text" in set(tkfont.families(root)):
                family = "Segoe UI Variable Text"
        except Exception:  # noqa: BLE001
            pass
        body = (family, -14)
        strong = (family, -14, "bold")
        caption = (family, -12)

        w = self._widgets

        def label(parent, **kwargs):  # noqa: ANN001, ANN202
            options = {"bg": pal.background, "fg": pal.foreground, "font": body}
            options.update(kwargs)
            return tk.Label(parent, **options)

        def separator(row):  # noqa: ANN001, ANN202
            line = tk.Frame(top, bg=pal.border, height=1)
            line.grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
            return line

        top.columnconfigure(1, weight=1)

        # The lockup: the app icon beside the name, "Voice" in ocean.
        # The icon is drawn on a canvas, not loaded through ImageTk: an
        # ImageTk.PhotoImage frees its Tcl image from whatever thread
        # garbage-collects it, and that crashes Tcl at shutdown.
        header = tk.Frame(top, bg=pal.background)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        w["icon"] = tk.Canvas(
            header, width=18, height=18, bg=pal.background,
            highlightthickness=0, bd=0,
        )
        w["icon"].create_oval(1, 1, 17, 17, fill=OCEAN, outline="")
        w["icon"].create_rectangle(7, 4, 11, 10, fill="white", outline="")
        w["icon"].create_arc(
            5, 6, 13, 13, start=180, extent=180, style="arc",
            outline="white", width=2,
        )
        w["icon"].create_line(9, 13, 9, 15, fill="white", width=2)
        w["icon"].pack(side="left", padx=(0, 8))
        tk.Label(
            header, text="Mirabel", bg=pal.background, fg=pal.foreground,
            font=(family, -13, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text=" Voice",
            bg=pal.background,
            fg=OCEAN_ON_DARK if not apps_use_light_theme() else OCEAN,
            font=(family, -13, "bold"),
        ).pack(side="left")

        separator(1)

        # The status row: the pill's dot and words, at rest.
        status = tk.Frame(top, bg=pal.background)
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        w["dot"] = tk.Canvas(
            status, width=10, height=10, bg=pal.background,
            highlightthickness=0, bd=0,
        )
        w["dot"].pack(side="left", padx=(0, 8))
        w["state"] = label(status, font=strong)
        w["state"].pack(side="left")
        w["hint"] = label(top, font=caption, fg=pal.hint, anchor="w")
        w["hint"].grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

        separator(4)

        style = ttk.Style(top)
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001 - keep whatever theme exists
            pass
        style.configure(
            "Mirabel.TCombobox",
            fieldbackground=pal.background,
            background=pal.background,
            foreground=pal.foreground,
            arrowcolor=pal.hint,
            bordercolor=pal.border,
        )
        top.option_add("*TCombobox*Listbox.background", pal.background)
        top.option_add("*TCombobox*Listbox.foreground", pal.foreground)

        label(top, text="Microphone", font=caption, fg=pal.hint).grid(
            row=5, column=0, sticky="w"
        )
        w["microphone"] = ttk.Combobox(
            top, state="readonly", style="Mirabel.TCombobox", width=20,
            font=caption,
        )
        w["microphone"].grid(row=5, column=1, sticky="ew", padx=(12, 0))
        w["microphone"].bind("<<ComboboxSelected>>", self._pick_microphone)

        label(top, text="Language", font=caption, fg=pal.hint).grid(
            row=6, column=0, sticky="w", pady=(8, 0)
        )
        w["language"] = ttk.Combobox(
            top, state="readonly", style="Mirabel.TCombobox", width=20,
            font=caption,
        )
        w["language"].grid(row=6, column=1, sticky="ew", padx=(12, 0), pady=(8, 0))
        w["language"].bind("<<ComboboxSelected>>", self._pick_language)

        w["translate"] = tk.Checkbutton(
            top,
            text="Translate to English",
            bg=pal.background,
            fg=pal.foreground,
            activebackground=pal.background,
            activeforeground=pal.foreground,
            selectcolor=pal.background,
            font=caption,
            anchor="w",
            command=self._toggle_translate,
        )
        w["translate"].grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        separator(8)

        buttons = tk.Frame(top, bg=pal.background)
        buttons.grid(row=9, column=0, columnspan=2, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        def button(parent, text, command, column):  # noqa: ANN001, ANN202
            b = tk.Label(
                parent, text=text, bg=pal.background, fg=pal.foreground,
                font=caption, bd=1, relief="solid", padx=10, pady=5,
            )
            b.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 4 if column == 0 else 0))
            b.bind("<Button-1>", lambda _event: command())
            return b

        w["copy"] = button(buttons, "Copy last text", self._copy_last, 0)
        w["change"] = button(buttons, CHANGE_KEY, self._begin_capture, 1)

        footer = tk.Frame(top, bg=pal.background)
        footer.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        w["signin"] = label(footer, font=caption, fg=pal.hint)
        w["signin"].pack(side="left")
        if self.app.signin is not None:
            w["signin"].bind("<Button-1>", lambda _event: self._sign_in())
        w["version"] = label(footer, text=app_version(), font=caption, fg=pal.hint)
        w["version"].pack(side="right")

        top.update_idletasks()
        self._style_window()
        # Focus out means the user clicked elsewhere: the flyout is a
        # taskbar flyout, and those dismiss themselves.
        top.bind("<FocusOut>", self._maybe_dismiss)
        top.bind("<Escape>", lambda _event: self._hide())
        # When the window dies (the overlay is stopping), drop every Tk
        # reference HERE, on the Tk thread. Holding them from another
        # thread means the Tcl interpreter is finally freed by whatever
        # thread garbage-collects last, and Tcl aborts the process with
        # "Tcl_AsyncDelete: async handler deleted by the wrong thread".
        top.bind("<Destroy>", self._release)
        self._tick()

    def _release(self, event) -> None:  # noqa: ANN001
        if self._top is not None and event.widget is self._top:
            self._top = None
            self._widgets = {}

    def _style_window(self) -> None:
        """Round the corners and keep the card out of Alt-Tab."""
        try:
            import ctypes

            try:
                hwnd = int(self._top.wm_frame(), 16)
            except Exception:  # noqa: BLE001
                hwnd = int(self._top.winfo_id())
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
            if not winui.round_corners(hwnd, panel_palette().border):
                self._top.configure(
                    highlightthickness=1,
                    highlightbackground=panel_palette().border,
                )
        except Exception:  # noqa: BLE001 - not Windows
            pass

    def _place(self) -> None:
        """Anchor the card above the notification area."""
        self._top.update_idletasks()
        width = self._top.winfo_reqwidth()
        height = self._top.winfo_reqheight()
        area = winui.focused_work_area()
        if area is not None:
            left, top_edge, right, bottom = area
            x = right - width - MARGIN
            y = bottom - height - MARGIN
        else:
            x = self._top.winfo_screenwidth() - width - MARGIN
            y = self._top.winfo_screenheight() - height - 60
        self._top.geometry(f"+{x}+{y}")

    def _refresh(self) -> None:
        """Read the app and put its facts on the card."""
        w = self._widgets
        try:
            from .audio import list_input_devices

            self._devices = list_input_devices()
        except Exception:  # noqa: BLE001 - a broken listing must not block the card
            self._devices = []
        w["microphone"]["values"] = microphone_names(self._devices)
        w["microphone"].set(self._current_microphone_name())
        w["language"]["values"] = language_names()
        code = self.app.config.language
        w["language"].set(dict(LANGUAGES).get(code, AUTO_DETECT))
        if self.app.config.translate_to_english:
            w["translate"].select()
        else:
            w["translate"].deselect()
        w["signin"].configure(text=self._signin_text())
        self._show_state()

    def _signin_text(self) -> str:
        """The footer line. Clicking it always re-runs the sign-in."""
        signin = self.app.signin
        if signin is None:
            return "Token sign-in"
        try:
            signed = signin.signed_in()
        except Exception:  # noqa: BLE001 - a broken store reads as signed out
            signed = False
        return "Signed in with Google" if signed else "Sign in with Google"

    def _current_microphone_name(self) -> str:
        index = self.app.config.input_device
        if index is None:
            return SYSTEM_DEFAULT
        for device in self._devices:
            if device["index"] == index:
                return device["name"]
        return SYSTEM_DEFAULT

    def _show_state(self) -> None:
        """The status row: dot colour, state word, and the key hint."""
        w = self._widgets
        state = self.app.state
        w["state"].configure(text=LABELS.get(state, "Ready"))
        w["dot"].delete("all")
        w["dot"].create_oval(
            0, 0, 9, 9, fill=DOTS.get(state, DOTS["idle"]), outline=""
        )
        if self._capturing:
            hint = "Press the key you want. Esc keeps the old one."
        else:
            hint = f"Hold {self.app.config.hotkey} to dictate · Esc cancels"
        w["hint"].configure(text=hint)

    def _tick(self) -> None:
        """Keep the status row honest while the card is open."""
        if self._top is None:
            return
        try:
            if self._top.state() != "withdrawn":
                self._show_state()
            self._top.after(400, self._tick)
        except Exception:  # noqa: BLE001 - the window is mid-destruction
            pass

    def _maybe_dismiss(self, _event) -> None:  # noqa: ANN001
        """Hide when the focus truly left, not when it moved inside."""
        if self._top is None or self._capturing:
            return

        def check() -> None:
            if self._top is None:
                return
            try:
                if self._top.focus_get() is None:
                    self._hide()
            except Exception:  # noqa: BLE001 - a dying widget mid-check
                pass

        self._top.after(150, check)

    # ---- the controls ----

    def _pick_microphone(self, _event) -> None:  # noqa: ANN001
        name = self._widgets["microphone"].get()
        if name == SYSTEM_DEFAULT:
            self.app.set_input_device(None)
            return
        for device in self._devices:
            if device["name"] == name:
                self.app.set_input_device(device["index"])
                return

    def _pick_language(self, _event) -> None:  # noqa: ANN001
        self.app.set_language(language_code(self._widgets["language"].get()))

    def _toggle_translate(self) -> None:
        self.app.set_translate(not self.app.config.translate_to_english)

    def _copy_last(self) -> None:
        self.app.copy_last()

    def _sign_in(self) -> None:
        """Run the Google sign-in off the UI thread, like the tray did."""

        def run() -> None:
            try:
                email = self.app.signin.sign_in()
            except Exception as error:  # noqa: BLE001 - the card must survive
                log.warning("The sign-in did not complete: %s", error)
                return
            log.info("Signed in as %s.", email)
            self.overlay.call(
                lambda: self._widgets["signin"].configure(
                    text=self._signin_text()
                )
            )

        threading.Thread(
            target=run, name="mirabel-voice-signin", daemon=True
        ).start()

    # ---- the inline key capture ----

    def _begin_capture(self) -> None:
        """Wait for the next key press and make it the dictation key.

        The app's own listener pauses first: with it running, pressing
        the current key mid-capture would start a dictation. This is
        what retires the separate console picker window.
        """
        if self._capturing:
            return
        self._capturing = True
        self.app.suspend_hotkeys()
        self._widgets["change"].configure(text=CAPTURE_PROMPT)
        self._show_state()
        threading.Thread(
            target=self._capture_thread,
            name="mirabel-voice-pick-key",
            daemon=True,
        ).start()

    def _capture_thread(self) -> None:
        """Listen for exactly one usable key, off the UI thread."""
        chosen: list[str | None] = []
        try:
            from pynput import keyboard
            from pynput.keyboard import Key

            from .picker import name_of

            def on_press(key) -> bool | None:  # noqa: ANN001
                if key is Key.esc:
                    chosen.append(None)
                    return False
                label = name_of(key)
                if label is None:
                    return None  # unusable; keep listening
                chosen.append(label)
                return False

            with keyboard.Listener(on_press=on_press) as listener:
                listener.join()
        except Exception:  # noqa: BLE001 - capture is optional, dictation is not
            log.exception("The key capture failed.")
            chosen.append(None)
        self.overlay.call(lambda: self._end_capture(chosen[0] if chosen else None))

    def _end_capture(self, label: str | None) -> None:
        """Apply the captured key, or put everything back on Esc."""
        self._capturing = False
        self._widgets["change"].configure(text=CHANGE_KEY)
        if label is None:
            self.app.resume_hotkeys()
        else:
            try:
                self.app.set_hotkey(label)
            except Exception:  # noqa: BLE001 - a refused key keeps the old one
                log.exception("The key was refused.")
                self.app.resume_hotkeys()
        self._show_state()
