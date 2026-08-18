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

from .app import STATE_ERROR, STATE_IDLE, STATE_RECORDING, STATE_WORKING, VoiceApp
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


class Tray:
    """Show the app in the Windows notification area."""

    def __init__(self, app: VoiceApp) -> None:
        self.app = app
        self.icon = None
        self.detail = ""
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
                "Clean up with Claude",
                self._toggle_cleanup,
                checked=lambda _: self.app.config.cleanup_enabled,
            ),
            pystray.MenuItem("Copy the last text", self._copy_last),
            pystray.MenuItem("Open the settings folder", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

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

    def _quit(self) -> None:
        """Stop the app."""
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
