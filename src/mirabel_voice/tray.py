"""The system tray icon.

The glyph is a monochrome microphone that follows the taskbar theme,
the way the system network and volume icons do. The state sits in a
small colour badge in its corner:

* no badge - ready
* red - the microphone is open
* blue - the transcript is in progress
* orange - the last cycle failed

The badge changes; the glyph never does. Whole-icon colour swaps read
as a different app, and a mid-grey disc reads as a dimmed one.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from .app import (
    LANGUAGES,
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_STARTING,
    STATE_WORKING,
    VoiceApp,
)
from .config import config_dir, config_path
from .palette import STATE_COLOURS, system_uses_light_theme

log = logging.getLogger(__name__)

# The one set of state colours, shared with the status panel's dot.
COLOURS = STATE_COLOURS

LABELS = {
    STATE_IDLE: "Ready",
    STATE_STARTING: "Starting",
    STATE_RECORDING: "Recording",
    STATE_WORKING: "Writing",
    STATE_ERROR: "Error",
}

ICON_SIZE = 64

# Every shape below is a ratio of the canvas, so the same drawing works
# at any size the caller asks for.
SUPERSAMPLE = 4  # draw big, shrink with Lanczos: crisp edges at 16 px

# The states that earn a badge. Ready is the absence of one.
BADGED = (STATE_RECORDING, STATE_WORKING, STATE_ERROR)

# The Mirabel brand disc of the app icon: --color-ocean-600.
OCEAN_RGB = (2, 132, 199)


def _draw_microphone(draw, size: int, colour, stroke: float) -> None:  # noqa: ANN001
    """Draw the capsule, cradle, and stand at ratios of the canvas."""
    width = max(round(size * stroke), 1)
    draw.rounded_rectangle(
        (size * 0.375, size * 0.094, size * 0.625, size * 0.563),
        radius=size * 0.125,
        fill=colour,
    )
    draw.arc(
        (size * 0.219, size * 0.188, size * 0.781, size * 0.75),
        start=0,
        end=180,
        fill=colour,
        width=width,
    )
    draw.line(
        (size * 0.5, size * 0.75, size * 0.5, size * 0.906),
        fill=colour,
        width=width,
    )


# There are only eight possible tray images (four badge looks, two
# taskbar themes). Drawing one costs a supersampled render, and pystray
# re-serializes every assigned image through a temp file - so each look
# is drawn once and reused, and update() skips identical assignments.
_ICON_CACHE: dict = {}


def make_icon_image(state: str, light_taskbar: bool | None = None):  # noqa: ANN201
    """Return the tray icon: a theme-aware mic, plus the state's badge.

    The taskbar follows the SYSTEM theme, so the glyph is near-black on
    a light taskbar and white on a dark one. The badge ring matches the
    taskbar colour, so the badge separates from the glyph at 16 px.
    Identical (badge, theme) pairs return the same cached image object.
    """
    if light_taskbar is None:
        light_taskbar = system_uses_light_theme()
    badge = state if state in BADGED else STATE_IDLE
    key = (badge, light_taskbar)
    cached = _ICON_CACHE.get(key)
    if cached is None:
        cached = _ICON_CACHE[key] = _draw_icon(badge, light_taskbar)
    return cached


def _draw_icon(state: str, light_taskbar: bool):  # noqa: ANN201
    """Draw one tray image. make_icon_image caches the results."""
    from PIL import Image, ImageDraw

    glyph = (27, 27, 27, 255) if light_taskbar else (255, 255, 255, 255)
    ring = (243, 243, 243, 255) if light_taskbar else (32, 32, 32, 255)

    size = ICON_SIZE * SUPERSAMPLE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _draw_microphone(draw, size, glyph, stroke=0.094)
    if state in BADGED:
        colour = COLOURS.get(state, COLOURS[STATE_ERROR]) + (255,)
        centre, radius = size * 0.781, size * 0.2
        edge = max(round(size * 0.031), 1)
        draw.ellipse(
            (
                centre - radius - edge,
                centre - radius - edge,
                centre + radius + edge,
                centre + radius + edge,
            ),
            fill=ring,
        )
        draw.ellipse(
            (centre - radius, centre - radius, centre + radius, centre + radius),
            fill=colour,
        )
    return image.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)


def make_app_icon(size: int):  # noqa: ANN201 - returns a PIL image
    """Draw the app icon: the ocean disc with the Mirabel M in the mic.

    The M is knocked out of the capsule at 48 px and up; the small
    sizes drop it for a clean mic. Per-size detail in one .ico is
    standard practice - the small entries must stay legible.
    """
    from PIL import Image, ImageDraw

    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    disc = OCEAN_RGB + (255,)
    white = (255, 255, 255, 255)
    draw.ellipse((canvas * 0.063, canvas * 0.063, canvas * 0.938, canvas * 0.938), fill=disc)
    stroke = max(round(canvas * 0.07), 1)
    draw.rounded_rectangle(
        (canvas * 0.391, canvas * 0.203, canvas * 0.609, canvas * 0.563),
        radius=canvas * 0.109,
        fill=white,
    )
    if size >= 48:
        m_width = max(round(canvas * 0.038), 1)
        points = [
            (canvas * 0.438, canvas * 0.469),
            (canvas * 0.438, canvas * 0.352),
            (canvas * 0.5, canvas * 0.414),
            (canvas * 0.563, canvas * 0.352),
            (canvas * 0.563, canvas * 0.469),
        ]
        draw.line(points, fill=disc, width=m_width, joint="curve")
    draw.arc(
        (canvas * 0.297, canvas * 0.297, canvas * 0.703, canvas * 0.703),
        start=0,
        end=180,
        fill=white,
        width=stroke,
    )
    draw.line(
        (canvas * 0.5, canvas * 0.703, canvas * 0.5, canvas * 0.797),
        fill=white,
        width=stroke,
    )
    return image.resize((size, size), Image.LANCZOS)


def _picker_command() -> list[str] | None:
    """Return the command that runs the key picker, or None.

    The installed app and a copy running from the source tree need
    different commands, and both need a program that owns a console.
    """
    if getattr(sys, "frozen", False):
        # The installed app ships a console twin beside itself.
        console = Path(sys.executable).with_name("MirabelVoiceConsole.exe")
        return [str(console), "--pick-hotkey"] if console.exists() else None

    # From source the app usually runs under pythonw.exe, which has no
    # console. Its python.exe neighbour does.
    python = Path(sys.executable)
    if python.stem.lower() == "pythonw":
        python = python.with_name("python.exe")
    if not python.exists():
        return None
    return [str(python), "-m", "mirabel_voice", "--pick-hotkey"]


class Tray:
    """Show the app in the Windows notification area."""

    def __init__(self, app: VoiceApp, flyout=None) -> None:  # noqa: ANN001
        from .updater import Updater, endorsement_for

        self.app = app
        self.flyout = flyout
        self.icon = None
        self.detail = ""
        self._last_image = None
        # None outside the installed bundle, and the menu item hides.
        self.updater = Updater.discover(
            endorsement=endorsement_for(app.config, app.signin)
        )
        app._on_state = self.update  # noqa: SLF001 - the tray owns the display

    def _title(self) -> str:
        """Return the text of the icon tooltip.

        Windows caps a tray tooltip at 128 characters and cuts the rest
        mid-word. The longest error details go past that, so the cut
        happens here, with an ellipsis, instead of wherever it lands.
        """
        label = LABELS.get(self.app.state, "Ready")
        hotkey = self.app.config.hotkey
        line = f"Mirabel Voice - {label} (hold {hotkey})"
        title = f"{line}\n{self.detail}" if self.detail else line
        if len(title) > 127:
            title = title[:126] + "…"
        return title

    def update(self, state: str, detail: str = "") -> None:
        """Change the badge and the tooltip.

        The image is re-picked on every state change, and the pick reads
        the taskbar theme each time - so a theme switch lands on the
        next state change without any listener of its own. The icon is
        only re-assigned when the image really changed: assignment makes
        pystray re-serialize the icon through a temp file, and this runs
        synchronously in the press-to-microphone gap.
        """
        self.detail = detail
        if self.icon is None:
            return
        image = make_icon_image(state)
        if image is not self._last_image:
            self.icon.icon = image
            self._last_image = image
        self.icon.title = self._title()

    def _menu(self):  # noqa: ANN202
        """Build the right-click menu.

        With a flyout, the menu holds only what the flyout does not:
        identity and status, the way in, maintenance, and the exit
        Windows requires of every tray app. Everyday controls live in
        the flyout alone - nothing appears in both. Without a flyout
        (no Tkinter), the old full menu stays, so nothing is lost.
        """
        import pystray

        if self.flyout is not None:
            return pystray.Menu(
                pystray.MenuItem(
                    lambda _: self._title().replace("\n", " - "),
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                # The default item also runs on a left-click of the icon.
                pystray.MenuItem(
                    "Open controls", self._open_controls, default=True
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Check for updates",
                    self._check_updates,
                    visible=lambda _: self.updater is not None,
                ),
                pystray.MenuItem("Open the settings folder", self._open_config),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )
        return pystray.Menu(
            pystray.MenuItem(lambda _: self._title().replace("\n", " - "), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Sign in with Google",
                self._sign_in,
                visible=lambda _: self.app.signin is not None,
            ),
            pystray.MenuItem(
                "Language",
                pystray.Menu(
                    *[self._language_item(label, code) for code, label in LANGUAGES],
                    self._language_item("Detect automatically", None),
                    pystray.Menu.SEPARATOR,
                    self._translate_item(),
                ),
            ),
            self._microphone_menu(),
            pystray.MenuItem(
                "Check for updates",
                self._check_updates,
                visible=lambda _: self.updater is not None,
            ),
            pystray.MenuItem("Copy the last text", self._copy_last),
            pystray.MenuItem("Change my dictation key", self._pick_hotkey),
            pystray.MenuItem("Open the settings folder", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _language_item(self, label: str, code):  # noqa: ANN001, ANN202
        """One radio entry of the Language submenu."""
        import pystray

        # pystray calls an action as action(icon, item), and it only adapts
        # callables that expose __code__. A functools.partial has none, so it
        # would receive both extra arguments and raise before set_language
        # runs. The closure takes them explicitly.
        def choose(icon, item):  # noqa: ANN001, ARG001
            self.app.set_language(code)

        return pystray.MenuItem(
            label,
            choose,
            checked=lambda _, code=code: self.app.config.language == code,
            radio=True,
        )

    def _microphone_menu(self):  # noqa: ANN202
        """The submenu that picks the microphone.

        The entries are built each time the menu refreshes, so a
        microphone plugged in after the start still appears. Windows
        reports every device once per audio API; WASAPI lists each
        active device once, under its full name, so when WASAPI
        entries exist only those are shown.
        """
        import pystray

        def entries():
            from .audio import list_input_devices

            try:
                devices = list_input_devices()
            except Exception:  # noqa: BLE001 - a broken listing must not kill the menu
                log.exception("The microphones could not be listed.")
                devices = []
            wasapi = [d for d in devices if d.get("hostapi") == "Windows WASAPI"]
            yield self._microphone_item("System default", None)
            for device in wasapi or devices:
                yield self._microphone_item(device["name"], device["index"])

        return pystray.MenuItem("Microphone", pystray.Menu(entries))

    def _microphone_item(self, label: str, index):  # noqa: ANN001, ANN202
        """One radio entry of the Microphone submenu."""
        import pystray

        # A closure for the same reason as the language items: pystray
        # calls the action as action(icon, item).
        def choose(icon, item):  # noqa: ANN001, ARG001
            self.app.set_input_device(index)

        return pystray.MenuItem(
            label,
            choose,
            checked=lambda _, index=index: self.app.config.input_device == index,
            radio=True,
        )

    def _translate_item(self):  # noqa: ANN202
        """The checkable entry that turns translation to English on or off."""
        import pystray

        # A closure for the same reason as the language items: pystray
        # calls the action as action(icon, item).
        def toggle(icon, item):  # noqa: ANN001, ARG001
            self.app.set_translate(not self.app.config.translate_to_english)

        return pystray.MenuItem(
            "Translate to English",
            toggle,
            checked=lambda _: self.app.config.translate_to_english,
        )

    def _sign_in(self) -> None:
        """Open the Google sign-in in the browser, off the menu thread.

        This is the repair for a dead sign-in: the icon went orange and
        told the user to come here. It also works while signed in, for
        switching accounts.
        """

        def run() -> None:
            try:
                email = self.app.signin.sign_in()
            except Exception as error:  # noqa: BLE001 - the menu must survive a refusal
                log.warning("The sign-in did not complete: %s", error)
                self.update(STATE_ERROR, f"The sign-in did not complete: {error}")
                return
            self.update(STATE_IDLE, f"Signed in as {email}.")

        threading.Thread(
            target=run, name="mirabel-voice-signin", daemon=True
        ).start()

    def _open_controls(self) -> None:
        """Open the flyout. The left-click default and the menu row."""
        if self.flyout is not None:
            self.flyout.show()

    def _copy_last(self) -> None:
        """Put the last dictated text on the clipboard."""
        self.app.copy_last()

    def _pick_hotkey(self) -> None:
        """Open the key picker in its own console window.

        The picker has to read a keypress, so it cannot run inside this
        app: this app is already listening for the dictation key.
        """
        command = _picker_command()
        if command is None:
            log.warning("The key picker could not be found.")
            return
        try:
            # CREATE_NEW_CONSOLE. The app itself has no console to use.
            subprocess.Popen(command, creationflags=0x00000010)  # noqa: S603
        except OSError:
            log.exception("The key picker did not start.")

    def _open_config(self) -> None:
        """Open the settings folder in File Explorer."""
        folder = config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if not config_path().exists():
            self.app.config.save()
        try:
            os.startfile(folder)  # noqa: S606 - Windows only
        except AttributeError:
            subprocess.Popen(["explorer", str(folder)])  # noqa: S607

    def _check_updates(self) -> None:
        """Fetch and apply the newest release, then restart into it.

        Off the menu thread, like the sign-in: the download can take a
        while, and the menu must stay alive through it.
        """

        def run() -> None:
            updater = self.updater
            if updater is None:
                return
            self.update(self.app.state, "Checking for updates...")
            release = updater.latest()
            if release is None:
                self.update(self.app.state, "The update check could not reach GitHub.")
                return
            installed = updater.installed_version()
            if installed and release[0] <= installed:
                self.update(self.app.state, "Already up to date.")
                return
            version = updater.apply_latest()
            if version and updater.start_new_copy():
                self.stop()
            elif not version:
                self.update(
                    self.app.state,
                    "This update needs the full download. Paste the install "
                    "line from the README after fetching the new zip.",
                )

        threading.Thread(
            target=run, name="mirabel-voice-update", daemon=True
        ).start()

    def _quit(self) -> None:
        """Stop the app."""
        self.stop()

    def stop(self) -> None:
        """Stop the app and close the icon. Safe from any thread."""
        self.app.stop()
        if self.icon is not None:
            self.icon.stop()

    def run(self) -> None:
        """Show the icon and block until the user quits."""
        import pystray

        self._last_image = make_icon_image(self.app.state)
        self.icon = pystray.Icon(
            "mirabel_voice",
            icon=self._last_image,
            title=self._title(),
            menu=self._menu(),
        )
        self.icon.run()
