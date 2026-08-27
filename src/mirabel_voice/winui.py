"""Small Windows answers the panel and the flyout both need.

Everything here degrades quietly: on an older Windows, or with no
Windows at all, each function returns its fallback and the caller
draws a plainer window. None of these calls may ever break dictation.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def enable_dpi_awareness() -> None:
    """Ask Windows not to bitmap-stretch our windows on scaled displays.

    Must run before the first window exists. Tries per-monitor V2
    first, then the older per-monitor call, then the system-wide one.
    """
    try:
        import ctypes

        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            if ctypes.windll.user32.SetProcessDpiAwarenessContext(-4):
                return
        except (AttributeError, OSError):
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except (AttributeError, OSError):
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - not Windows
        log.debug("DPI awareness was not set.", exc_info=True)


def window_scale(hwnd: int) -> float:
    """Return the scale factor of the monitor the window is on."""
    try:
        import ctypes

        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        if dpi:
            return dpi / 96.0
    except Exception:  # noqa: BLE001 - pre-1607 Windows, or not Windows
        pass
    return 1.0


def round_corners(hwnd: int, border_hex: str) -> bool:
    """Ask DWM for 8 px corners and a hairline border.

    Returns True when Windows 11 accepted. Windows 10 refuses, and the
    caller then draws its own edge instead of shipping a bare rectangle.
    """
    if not hwnd:
        return False
    try:
        import ctypes

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWCP_ROUND = 2
        dwm = ctypes.windll.dwmapi
        rounded = dwm.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
            ctypes.sizeof(ctypes.c_int),
        )
        # DWM wants blue, green, red, in that order.
        red, green, blue = (int(border_hex[i : i + 2], 16) for i in (1, 3, 5))
        dwm.DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            ctypes.byref(ctypes.c_int(red | (green << 8) | (blue << 16))),
            ctypes.sizeof(ctypes.c_int),
        )
        return rounded == 0  # S_OK
    except Exception:  # noqa: BLE001 - older Windows, or not Windows
        log.debug("The corners stayed square.", exc_info=True)
        return False


def focused_work_area() -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) of the focused monitor's work area.

    The work area excludes the taskbar, wherever it is docked. The
    monitor is the one holding the foreground window, so the panel
    appears where the user is typing, not on the primary screen.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MONITOR_DEFAULTTONEAREST = 2
        window = user32.GetForegroundWindow()
        monitor = user32.MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return (work.left, work.top, work.right, work.bottom)
    except Exception:  # noqa: BLE001 - not Windows
        return None


def animations_enabled() -> bool:
    """Return whether the user wants windows to animate.

    This is the "Show animations in Windows" accessibility switch.
    When it is off, every entrance is an instant appearance.
    """
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        value = ctypes.c_int(0)
        if ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0
        ):
            return bool(value.value)
    except Exception:  # noqa: BLE001 - not Windows
        pass
    return True
