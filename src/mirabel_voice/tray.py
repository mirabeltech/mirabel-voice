"""The system tray icon.

The icon colour shows the state:

* grey - ready
* red - the microphone is open
* blue - the transcript is in progress
* orange - the last cycle failed
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
    STATE_WORKING,
    VoiceApp,
)
from .config import config_dir, config_path

log = logging.getLogger(__name__)

COLOURS = {
    STATE_IDLE: (110, 110, 118),
    STATE_RECORDING: (220, 60, 60),
    STATE_WORKING: (60, 130, 220),
    STATE_ERROR: (230, 150, 40),
}

LABELS = {
    STATE_IDLE: "Ready",
    STATE_RECORDING: "Recording",
    STATE_WORKING: "Writing",
    STATE_ERROR: "Error",
}

ICON_SIZE = 64


def make_icon_image(state: str):  # noqa: ANN201 - returns a PIL image
    """Draw a round icon in the colour of the state."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    colour = COLOURS.get(state, COLOURS[STATE_IDLE])
    draw.ellipse((6, 6, ICON_SIZE - 6, ICON_SIZE - 6), fill=colour + (255,))
    # A small microphone shape in white.
    draw.rounded_rectangle((27, 17, 37, 36), radius=5, fill=(255, 255, 255, 255))
    draw.arc((21, 28, 43, 46), start=0, end=180, fill=(255, 255, 255, 255), width=4)
    draw.line((32, 44, 32, 50), fill=(255, 255, 255, 255), width=4)
    return image


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

    def __init__(self, app: VoiceApp) -> None:
        from .updater import Updater, endorsement_for

        self.app = app
        self.icon = None
        self.detail = ""
        # None outside the installed bundle, and the menu item hides.
        self.updater = Updater.discover(
            endorsement=endorsement_for(app.config, app.signin)
        )
        app._on_state = self.update  # noqa: SLF001 - the tray owns the display

    def _title(self) -> str:
        """Return the text of the icon tooltip."""
        label = LABELS.get(self.app.state, "Ready")
        hotkey = self.app.config.hotkey
        line = f"Mirabel Voice - {label} (hold {hotkey})"
        return f"{line}\n{self.detail}" if self.detail else line

    def update(self, state: str, detail: str = "") -> None:
        """Change the icon colour and the tooltip."""
        self.detail = detail
        if self.icon is None:
            return
        self.icon.icon = make_icon_image(state)
        self.icon.title = self._title()

    def _menu(self):  # noqa: ANN202
        """Build the right-click menu."""
        import pystray

        return pystray.Menu(
            pystray.MenuItem(lambda _: self._title().replace("\n", " - "), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Sign in with Google",
                self._sign_in,
                visible=lambda _: self.app.signin is not None,
            ),
            self._cleanup_item(),
            pystray.MenuItem(
                "Language",
                pystray.Menu(
                    *[self._language_item(label, code) for code, label in LANGUAGES],
                    self._language_item("Detect automatically", None),
                ),
            ),
            self._translate_item(),
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

    def _cleanup_item(self):  # noqa: ANN202
        """The checkable entry that turns the Claude cleanup on or off.

        Translation lives in the cleanup pass, so while translate is on
        the pass always runs: the checkmark shows that, and the entry
        greys out rather than pretend a click could change it.
        """
        import pystray

        return pystray.MenuItem(
            "Clean up with Claude",
            self._toggle_cleanup,
            checked=lambda _: self.app.config.cleanup_enabled
            or self.app.config.translate_to_english,
            enabled=lambda _: not self.app.config.translate_to_english,
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

    def _toggle_cleanup(self) -> None:
        """Switch the Claude cleanup on or off and save the setting."""
        self.app.config.cleanup_enabled = not self.app.config.cleanup_enabled
        self.app.config.save()

    def _copy_last(self) -> None:
        """Put the last dictated text on the clipboard."""
        if not self.app.last_text:
            return
        try:
            import pyperclip

            pyperclip.copy(self.app.last_text)
        except Exception:  # noqa: BLE001
            log.exception("The clipboard did not accept the text.")

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

        self.icon = pystray.Icon(
            "mirabel_voice",
            icon=make_icon_image(self.app.state),
            title=self._title(),
            menu=self._menu(),
        )
        self.icon.run()
