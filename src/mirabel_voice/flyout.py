"""The controls flyout: the small card a left-click on the tray opens.

The everyday controls live here - microphone, language, translation,
copy-last, and the dictation key - so the right-click menu can shrink
to the Windows minimum. Unlike the status pill this window is
interactive: it takes focus while open and closes on an outside mouse click.
Dropdowns and other controls can temporarily move keyboard focus safely.

The overlay owns the one Tkinter thread, so every touch of a widget
goes through Overlay.call.
"""

from __future__ import annotations

import logging
import threading
import time

from . import winui
from .app import STATE_RECORDING, STATE_STARTING
from .config import LANGUAGES
from .palette import OCEAN, OCEAN_ON_DARK, apps_use_light_theme, panel_palette
from .tray import LABELS
from .overlay import DOTS, Overlay

log = logging.getLogger(__name__)

PAD = 16
MARGIN = 12  # from the corner of the work area

# A key capture that nobody answers gives the keyboard back on its own.
CAPTURE_TIMEOUT_S = 15.0
# Ignore duplicate tray callbacks immediately after opening the card.
JUST_SHOWN_S = 0.3

AUTO_DETECT = "Detect automatically"
SYSTEM_DEFAULT = "System default"
CAPTURE_PROMPT = "Press a key…"
CHANGE_KEY = "Change key…"


def version_from_markers(site) -> str:  # noqa: ANN001 - a Path
    """The version by the newest dist-info folder name, or nothing.

    The updater records each source update by RENAMING the dist-info
    folder; the METADATA file inside still says whatever pip wrote at
    the original install. importlib reads that file, so it answers
    with the version pip installed, not the one running. The folder
    name is the truth.
    """
    try:
        from .updater import parse_version

        markers = list(site.glob("mirabel_voice-*.dist-info"))
        versions = [parse_version(marker.name) for marker in markers]
        versions = [v for v in versions if v]
        if versions:
            return "v" + ".".join(str(part) for part in max(versions))
    except Exception:  # noqa: BLE001 - a strange layout answers nothing
        pass
    return ""


def app_version() -> str:
    """The running version, or nothing when it cannot be known."""
    from pathlib import Path
    marker = Path(__file__).with_name("_version.txt")
    if marker.exists():
        return "v" + marker.read_text(encoding="utf-8").strip()
    try:
        from pathlib import Path

        marked = version_from_markers(Path(__file__).resolve().parent.parent)
        if marked:
            return marked
    except Exception:  # noqa: BLE001
        pass
    source_project = Path(__file__).resolve().parents[2] / 'pyproject.toml'
    if source_project.exists():
        import tomllib
        return 'v' + tomllib.loads(source_project.read_text(encoding='utf-8'))['project']['version']
    # Fall back for other installed layouts.
    try:
        from importlib.metadata import version

        return f"v{version('mirabel-voice')}"
    except Exception:  # noqa: BLE001 - a missing dist-info is fine
        return ""


def language_names() -> list[str]:
    """The language choices, in menu order."""
    return [AUTO_DETECT] + [label for _, label in LANGUAGES]


def idle_hint(config) -> str:  # noqa: ANN001 - a Config
    """The one-line how-to for the mode the person is actually in.

    "Hold" instructions on a toggle-mode machine teach the wrong habit,
    so the words follow the setting.
    """
    from .hotkey import MODE_TOGGLE

    if config.mode == MODE_TOGGLE:
        return f"Tap {config.hotkey} to start and stop · Esc cancels"
    return f"Hold {config.hotkey} to dictate · Esc cancels"


def language_code(name: str) -> str | None:
    """The settings code behind a menu name."""
    for code, label in LANGUAGES:
        if label == name:
            return code
    return None


def microphone_choices(devices: list[dict]) -> list[tuple[str, int | None]]:
    """The microphone choices: (name, device index) pairs, default first.

    Windows lists a device once per audio API; the WASAPI entries carry
    the full names, so when any exist only those are offered. The pairs
    keep name and index together: the same name often exists under
    several APIs with different indexes, so a name alone cannot be
    resolved against the full device list.
    """
    wasapi = [d for d in devices if d.get("hostapi") == "Windows WASAPI"]
    return [(SYSTEM_DEFAULT, None)] + [
        (d["name"], d["index"]) for d in (wasapi or devices)
    ]


def microphone_names(devices: list[dict]) -> list[str]:
    """The microphone names, in the order the card offers them."""
    return [name for name, _ in microphone_choices(devices)]


class Flyout:
    """Build, show, and hide the controls card."""

    def __init__(self, overlay: Overlay, app) -> None:  # noqa: ANN001
        self.overlay = overlay
        self.app = app
        # Everything below is touched on the overlay thread only,
        # except _capture_listener, which the capture thread also sets.
        self._top = None
        self._hwnd = 0
        self._popup_hwnds = ()
        self._widgets = {}
        self._devices: list[dict] = []
        self._choices: list[tuple[str, int | None]] = []
        self._capturing = False
        self._capture_listener = None
        self._built_pal = None
        self._shown_at = 0.0
        self._dismissed_at = 0.0
        self._tick_id = None
        self._outside_listener = None
        self._outside_token = None
        # PortAudio's first enumeration costs hundreds of milliseconds.
        # Pay it here, in the background, so the first click on the tray
        # does not stall the Tk thread and the status pill with it.
        threading.Thread(
            target=self._warm_devices, name="mirabel-voice-devices", daemon=True
        ).start()

    @staticmethod
    def _warm_devices() -> None:
        try:
            from .audio import list_input_devices

            list_input_devices()
        except Exception:  # noqa: BLE001 - warming up is best-effort
            pass

    # ---- called from any thread ----

    def show(self) -> None:
        """Open the card, or bring it back to the front."""
        self.overlay.call(self._show)

    def hide(self) -> None:
        """Take the card off the screen."""
        self.overlay.call(self._hide)

    # ---- everything below runs on the overlay thread ----

    def _px(self, value: int) -> int:
        """Scale a design pixel the way the status pill does.

        The card borrows the overlay's monitor scale: without this it
        renders at two-thirds size on a 150% display, right beside a
        correctly scaled pill.
        """
        return round(value * self.overlay._scale)  # noqa: SLF001

    def _visible(self) -> bool:
        try:
            return self._top is not None and self._top.state() == "normal"
        except Exception:  # noqa: BLE001 - a window mid-destruction
            return False

    def _show(self) -> None:
        if time.monotonic() - self._dismissed_at < JUST_SHOWN_S:
            return  # the same outside tray click can also request show
        try:
            if self._visible():
                # A second tray click on an open card closes it, the
                # way every taskbar flyout behaves.
                if time.monotonic() - self._shown_at > JUST_SHOWN_S:
                    self._hide()
                return
            if self._top is not None and panel_palette() != self._built_pal:
                # The theme changed since the card was built. Its
                # colours are baked into the widgets, so rebuild.
                self._discard()
            if self._top is None:
                self._build()
            self._refresh()
            self._place()
            self._top.deiconify()
            self._top.lift()
            self._top.focus_force()
            self._shown_at = time.monotonic()
            self._watch_outside_clicks()
        except Exception:  # noqa: BLE001 - the flyout must never kill the app
            log.warning("The controls flyout did not open.", exc_info=True)
            # Throw the half-built window away, or every later click
            # would reuse it and fail the same way forever.
            self._discard()

    def _hide(self) -> None:
        self._stop_outside_clicks()
        if self._capturing:
            self._cancel_capture()
        if self._top is None:
            return
        self._top.withdraw()

    def _discard(self) -> None:
        """Destroy the card and every Tk reference to it, on this thread."""
        self._stop_outside_clicks()
        top, self._top = self._top, None
        self._widgets = {}
        self._built_pal = None
        self._hwnd = 0
        if top is not None:
            # A pending after-callback outlives the widget: it belongs
            # to the interpreter, not the card. Left alone it would fire
            # against the next card and stack one more poll chain per
            # rebuild.
            if self._tick_id is not None:
                try:
                    top.after_cancel(self._tick_id)
                except Exception:  # noqa: BLE001 - already gone
                    pass
                self._tick_id = None
            try:
                top.destroy()
            except Exception:  # noqa: BLE001 - already dying
                pass

    def _build(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        pal = panel_palette()
        self._built_pal = pal
        self._widgets = {}
        root = self.overlay._root  # noqa: SLF001 - the one Tk root
        top = tk.Toplevel(root)
        self._top = top
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=pal.background, padx=self._px(PAD), pady=self._px(PAD))

        family = "Segoe UI"
        try:
            import tkinter.font as tkfont

            if "Segoe UI Variable Text" in set(tkfont.families(root)):
                family = "Segoe UI Variable Text"
        except Exception:  # noqa: BLE001
            pass
        body = (family, -self._px(14))
        strong = (family, -self._px(14), "bold")
        caption = (family, -self._px(12))

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
        s = self._px(18)
        w["icon"] = tk.Canvas(
            header, width=s, height=s, bg=pal.background,
            highlightthickness=0, bd=0,
        )

        def ic(v: float) -> float:
            return v * s / 18.0

        w["icon"].create_oval(ic(1), ic(1), ic(17), ic(17), fill=OCEAN, outline="")
        w["icon"].create_rectangle(
            ic(7), ic(4), ic(11), ic(10), fill="white", outline=""
        )
        w["icon"].create_arc(
            ic(5), ic(6), ic(13), ic(13), start=180, extent=180, style="arc",
            outline="white", width=max(self._px(2), 2),
        )
        w["icon"].create_line(
            ic(9), ic(13), ic(9), ic(15), fill="white", width=max(self._px(2), 2)
        )
        w["icon"].pack(side="left", padx=(0, self._px(8)))
        tk.Label(
            header, text="Mirabel", bg=pal.background, fg=pal.foreground,
            font=(family, -self._px(13), "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text=" Voice",
            bg=pal.background,
            fg=OCEAN_ON_DARK if not apps_use_light_theme() else OCEAN,
            font=(family, -self._px(13), "bold"),
        ).pack(side="left")

        separator(1)

        # The status row: the pill's dot and words, at rest.
        status = tk.Frame(top, bg=pal.background)
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        dot = self._px(10)
        w["dot"] = tk.Canvas(
            status, width=dot, height=dot, bg=pal.background,
            highlightthickness=0, bd=0,
        )
        w["dot"].pack(side="left", padx=(0, self._px(8)))
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
        # A readonly combobox takes its colours from the state map, not
        # the base style - without this the theme's default grey wins
        # and the boxes look like a different decade than the card.
        style.map(
            "Mirabel.TCombobox",
            fieldbackground=[("readonly", pal.background)],
            background=[("readonly", pal.background)],
            foreground=[("readonly", pal.foreground)],
            selectbackground=[("readonly", pal.background)],
            selectforeground=[("readonly", pal.foreground)],
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
            b = tk.Button(
                parent, text=text, command=command, takefocus=True, bg=pal.background, fg=pal.foreground,
                font=caption, bd=1, relief="solid", padx=10, pady=5,
            )
            b.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 4 if column == 0 else 0))
            return b

        w["copy"] = button(buttons, "Copy last text", self._copy_last, 0)
        w["change"] = button(buttons, CHANGE_KEY, self._begin_capture, 1)

        footer = tk.Frame(top, bg=pal.background)
        footer.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        w["signin"] = tk.Button(footer, command=self._sign_in, takefocus=True, font=caption, fg=pal.hint, bg=pal.background, state="normal" if self.app.signin is not None else "disabled")
        w["signin"].pack(side="left")
        w["version"] = label(footer, text=app_version(), font=caption, fg=pal.hint)
        w["version"].pack(side="right")

        actions = tk.Frame(top, bg=pal.background)
        actions.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        w["pause"] = tk.Button(actions, text="Pause microphone", command=self._toggle_pause, takefocus=True)
        w["pause"].pack(side="left")
        tk.Button(actions, text="Retry recording", command=lambda: self.app.retry_last_recording(), takefocus=True).pack(side="left")
        tk.Button(actions, text="Discard", command=lambda: self.app.discard_last_recording(), takefocus=True).pack(side="left")
        w["startup"] = tk.Checkbutton(top, text="Start with Windows", command=self._toggle_startup,
                                      bg=pal.background, fg=pal.foreground, selectcolor=pal.background)
        w["startup"].grid(row=12, column=0, columnspan=2, sticky="w")
        w["level"] = label(top, text="Microphone level: 0%", font=caption)
        w["level"].grid(row=13, column=0, columnspan=2, sticky="w")
        w["help"] = label(top, text="Choose your microphone and key, then click below and try dictating.\nIf the level stays at 0%, check Windows microphone permissions.", font=caption)
        w["help"].grid(row=14, column=0, columnspan=2, sticky="w", pady=(6, 0))
        w["scratch"] = tk.Text(top, height=3, width=36, wrap="word", font=caption, takefocus=True)
        w["scratch"].grid(row=15, column=0, columnspan=2, sticky="ew")
        w["finish_setup"] = tk.Button(top, text="Finish setup", command=self._finish_setup, takefocus=True)
        w["finish_setup"].grid(row=16, column=0, columnspan=2, sticky="e")
        self._refresh_setup()

        top.update_idletasks()
        self._style_window()
        # ttk dropdowns are separate native windows, not consistently owned
        # by the Settings HWND. Register their client handles on the Tk thread.
        self._popup_hwnds = tuple(
            int(str(top.tk.call("winfo", "id",
                top.tk.call("ttk::combobox::PopdownWindow", str(w[key])))), 0)
            for key in ("microphone", "language")
        )
        # Focus changes alone do not dismiss Settings; mouse presses do.
        # Losing focus must still disarm global shortcut capture.
        top.bind("<FocusOut>", self._on_focus_out)
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
            self._stop_outside_clicks()
            self._cancel_capture()
            self._top = None
            self._widgets = {}
            self._built_pal = None
            self._hwnd = 0

    def _style_window(self) -> None:
        """Round the corners and keep the card out of Alt-Tab."""
        try:
            import ctypes

            try:
                hwnd = int(self._top.wm_frame(), 16)
            except Exception:  # noqa: BLE001
                hwnd = int(self._top.winfo_id())
            user32 = ctypes.windll.user32
            from ctypes import wintypes
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            hwnd = user32.GetAncestor(hwnd, 2) or hwnd
            self._hwnd = hwnd
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
        self._choices = microphone_choices(self._devices)
        w["microphone"]["values"] = [name for name, _ in self._choices]
        w["microphone"].set(self._current_microphone_name())
        w["language"]["values"] = language_names()
        code = self.app.config.language
        w["language"].set(dict(LANGUAGES).get(code, AUTO_DETECT))
        if self.app.config.translate_to_english:
            w["translate"].select()
        else:
            w["translate"].deselect()
        w["signin"].configure(text=self._signin_text())
        if getattr(self.app.config, "start_with_windows", True):
            w["startup"].select()
        else:
            w["startup"].deselect()
        self._show_state()

    def _refresh_setup(self) -> None:
        complete = getattr(self.app.config, "onboarding_complete", False)
        for key in ("help", "scratch", "finish_setup"):
            widget = self._widgets[key]
            if complete:
                widget.grid_remove()
            else:
                widget.grid()

    def _signin_text(self) -> str:
        """The footer line. Clicking it always re-runs the sign-in."""
        signin = self.app.signin
        if signin is None:
            return "Token sign-in"
        try:
            signed = signin.signed_in()
        except Exception:  # noqa: BLE001 - a broken store reads as signed out
            signed = False
        if getattr(signin, "load_problem", None):
            return "Saved sign-in unreadable. Sign in again."
        return "Signed in with Google" if signed else "Sign in with Google"

    def _current_microphone_name(self) -> str:
        index = self.app.config.input_device
        if index is None:
            return SYSTEM_DEFAULT
        for name, choice in self._choices:
            if choice == index:
                return name
        return SYSTEM_DEFAULT

    def _show_state(self) -> None:
        """The status row: dot colour, state word, and the key hint."""
        w = self._widgets
        if not w:
            return  # the card died mid-update
        state = self.app.state
        w["state"].configure(text=LABELS.get(state, "Ready"))
        if "pause" in w:
            w["pause"].configure(text="Resume microphone" if getattr(self.app, "microphone_paused", False) else "Pause microphone")
            level = min(100, int(getattr(getattr(self.app, "recorder", None), "level", 0) * 100))
            w["level"].configure(text=f"Microphone level: {level}%")
        w["dot"].delete("all")
        size = self._px(10)
        w["dot"].create_oval(
            0, 0, size - 1, size - 1,
            fill=DOTS.get(state, DOTS["idle"]),
            outline="",
        )
        if self._capturing:
            hint = "Press the key you want. Esc keeps the old one."
        else:
            hint = idle_hint(self.app.config)
        w["hint"].configure(text=hint)

    def _tick(self) -> None:
        """Keep the status row honest while the card is open."""
        self._tick_id = None
        if self._top is None:
            return
        try:
            if self._top.state() != "withdrawn":
                self._show_state()
            self._tick_id = self._top.after(400, self._tick)
        except Exception:  # noqa: BLE001 - the window is mid-destruction
            pass

    def _watch_outside_clicks(self) -> None:
        """Observe mouse presses without consuming or changing the user's click."""
        self._stop_outside_clicks()
        token = object()
        self._outside_token = token

        def on_click(x, y, _button, pressed):  # noqa: ANN001
            if not pressed or self._outside_token is not token:
                return
            # Resolve ownership on the hook thread, before Tk can unpost a
            # dropdown. Never call Tk here: all widget work stays on its thread.
            if self._click_is_inside(x, y):
                return
            self.overlay.call(lambda: self._dismiss_outside_click(token))

        try:
            from pynput import mouse

            self._outside_listener = mouse.Listener(on_click=on_click)
            self._outside_listener.start()
        except Exception:  # noqa: BLE001 - Escape/tray closing still works
            self._stop_outside_clicks()
            log.warning("Outside-click detection could not start.", exc_info=True)

    def _stop_outside_clicks(self) -> None:
        self._outside_token = None
        listener, self._outside_listener = self._outside_listener, None
        if listener is not None:
            listener.stop()

    def _dismiss_outside_click(self, token) -> None:  # noqa: ANN001
        # A queued click from a previous opening must not close a reopened card.
        if token is self._outside_token and self._visible():
            self._dismissed_at = time.monotonic()
            self._hide()

    def _click_is_inside(self, x: int, y: int) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
            return self._owns_window(hwnd)
        except Exception:  # noqa: BLE001 - uncertain clicks should not dismiss
            return True

    def _owns_window(self, hwnd: int) -> bool:
        """Include child controls and owned popup windows, such as dropdowns."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        if not self._hwnd:
            return True
        inside_roots = {self._hwnd}
        for popup in self._popup_hwnds:
            inside_roots.add(user32.GetAncestor(popup, 2) or popup)
        seen = set()
        while hwnd and hwnd not in seen:
            seen.add(hwnd)
            root = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
            if root in inside_roots:
                return True
            hwnd = user32.GetWindow(root, 4)  # GW_OWNER
        return False

    def _on_focus_out(self, _event) -> None:  # noqa: ANN001
        """Keep Settings open, but stop shortcut capture when focus leaves."""
        top = self._top
        if top is None or not self._capturing:
            return

        def check() -> None:
            if self._top is not top or not self._capturing:
                return
            try:
                # Ask Tcl directly: ttk popup widgets may not have Python
                # widget objects, so focus_get() can raise a KeyError.
                focused = str(top.tk.call("focus"))
                own_path = str(top)
                if not (focused == own_path or focused.startswith(own_path + ".")):
                    self._cancel_capture()
            except Exception:  # noqa: BLE001 - a disappearing window
                self._cancel_capture()

        top.after(150, check)

    # ---- the controls ----

    def _toggle_pause(self):
        threading.Thread(target=lambda: self.app.set_microphone_paused(not self.app.microphone_paused), daemon=True).start()

    def _toggle_startup(self):
        try:
            self.app.set_start_with_windows(not self.app.config.start_with_windows)
        except Exception:
            self._widgets["hint"].configure(text="Could not change Windows startup. Check your user permissions.")

    def _finish_setup(self):
        self.app.config.onboarding_complete = True
        self.app.config.save()
        self._refresh_setup()
        self._hide()

    def _pick_microphone(self, _event) -> None:  # noqa: ANN001
        # Resolve against the same filtered list the box displayed. The
        # full device list often carries the same name under several
        # audio APIs with different indexes, and matching there would
        # save the wrong one.
        name = self._widgets["microphone"].get()
        for choice_name, index in self._choices:
            if choice_name == name:
                self.app.set_input_device(index)
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
        if self.app.state in (STATE_STARTING, STATE_RECORDING):
            # The listener carries the only stop for a live recording.
            # Tearing it down now would strand the microphone open.
            self._widgets["hint"].configure(text="Finish dictating first.")
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

    def _card_has_foreground(self) -> bool:
        """Return whether the card is the window the user is looking at.

        The capture hook is global. Without this check, a key typed
        into any other window would become the dictation key.
        """
        if not self._hwnd:
            return True  # no hwnd to compare; do not brick the feature
        try:
            import ctypes

            return ctypes.windll.user32.GetForegroundWindow() == self._hwnd
        except Exception:  # noqa: BLE001 - not Windows
            return True

    def _capture_thread(self) -> None:
        """Listen for exactly one usable key, off the UI thread.

        The hook accepts a key only while the card holds the
        foreground, gives up after CAPTURE_TIMEOUT_S, and stops when
        _cancel_capture asks it to - so it can never outlive the card
        and grab a key later.
        """
        chosen: list[str | None] = []
        try:
            from pynput import keyboard
            from pynput.keyboard import Key

            from .picker import name_of

            def on_press(key) -> bool | None:  # noqa: ANN001
                if not self._card_has_foreground():
                    return False  # the user went elsewhere; keep the old key
                if key is Key.esc:
                    return False
                label = name_of(key)
                if label is None:
                    return None  # unusable; keep listening
                chosen.append(label)
                return False

            listener = keyboard.Listener(on_press=on_press)
            self._capture_listener = listener
            listener.start()
            listener.join(CAPTURE_TIMEOUT_S)
            if listener.is_alive():
                listener.stop()
                listener.join(1.0)
        except Exception:  # noqa: BLE001 - capture is optional, dictation is not
            log.exception("The key capture failed.")
        self.overlay.call(lambda: self._end_capture(chosen[0] if chosen else None))

    def _cancel_capture(self) -> None:
        """Stop a waiting capture and keep the old key.

        The capture thread then delivers _end_capture(None) through the
        overlay queue, which resumes the hotkeys - one path for every
        ending.
        """
        listener = self._capture_listener
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001 - already gone
                pass

    def _end_capture(self, label: str | None) -> None:
        """Apply the captured key, or put everything back.

        The hotkeys come back FIRST: a widget that died while the
        capture waited must not leave dictation suspended forever.
        """
        if not self._capturing:
            return  # already ended by an earlier delivery
        self._capturing = False
        self._capture_listener = None
        if label is None:
            self.app.resume_hotkeys()
        else:
            try:
                self.app.set_hotkey(label)
            except Exception:  # noqa: BLE001 - a refused key keeps the old one
                log.exception("pynput refused the key name.")
                self.app.resume_hotkeys()
        change = self._widgets.get("change")
        if change is not None:
            change.configure(text=CHANGE_KEY)
        self._show_state()
