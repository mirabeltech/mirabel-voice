"""The colours every surface shares, and the theme they follow.

The tray icon, the status panel, and the controls flyout must never
disagree about what a state looks like. This module is the one place
their colours live. It also answers the two theme questions Windows
splits across two registry values: the taskbar follows the SYSTEM
theme, and app windows follow the APPS theme.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# One colour per pipeline state. The tray badge and the panel dot both
# read from here, so the two can never say different things.
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_RECORDING = "recording"
STATE_WORKING = "working"
STATE_ERROR = "error"

STATE_COLOURS = {
    STATE_IDLE: (110, 110, 118),
    STATE_STARTING: (110, 110, 118),
    STATE_RECORDING: (220, 60, 60),
    STATE_WORKING: (60, 130, 220),
    STATE_ERROR: (230, 150, 40),
}

# The Mirabel brand blue: --color-ocean-600 from the UI60 design tokens.
OCEAN = "#0284C7"
# The same accent, lifted for dark surfaces where ocean-600 is too dim.
OCEAN_ON_DARK = "#38BDF8"


@dataclass(frozen=True)
class Palette:
    """The surface colours of one theme."""

    background: str
    foreground: str
    border: str
    hint: str
    success: str


DARK = Palette(
    background="#171B22",
    foreground="#E9EDF2",
    border="#333B47",
    hint="#7F8C99",
    success="#3CB46E",
)

LIGHT = Palette(
    background="#FBFBFC",
    foreground="#1B1F26",
    border="#D9DEE5",
    hint="#6B7684",
    # The dark theme's green fails 3:1 on a light surface.
    success="#2E9159",
)


def _light_theme_value(name: str) -> bool:
    """Read one of the two theme switches from the registry.

    Windows without the value, or without a registry, counts as light:
    that is the Windows default theme.
    """
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        with key:
            value, _ = winreg.QueryValueEx(key, name)
        return bool(value)
    except OSError:
        return True


def apps_use_light_theme() -> bool:
    """Return True when app windows should be light.

    This governs the status panel and the flyout.
    """
    return _light_theme_value("AppsUseLightTheme")


def system_uses_light_theme() -> bool:
    """Return True when the taskbar is light.

    This governs the tray icon, which sits on the taskbar and follows
    the SYSTEM theme, not the apps theme.
    """
    return _light_theme_value("SystemUsesLightTheme")


def panel_palette() -> Palette:
    """Return the palette the panel and flyout should draw with now."""
    return LIGHT if apps_use_light_theme() else DARK


def hex_of(rgb: tuple[int, int, int]) -> str:
    """Turn an (r, g, b) triple into "#RRGGBB"."""
    return "#%02X%02X%02X" % rgb
