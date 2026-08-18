"""Command line entry point for Mirabel Voice."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .app import VoiceApp
from .config import Config, config_path, load_api_keys

LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(message)s"


def _check_keys(config: Config) -> list[str]:
    """Return a message for each API key that is missing."""
    problems = []
    if not os.environ.get("OPENAI_API_KEY"):
        problems.append(
            "OPENAI_API_KEY is not set. Speech to text needs this key."
        )
    if config.cleanup_enabled and not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append(
            "ANTHROPIC_API_KEY is not set. The Claude cleanup needs this key. "
            "Set cleanup_enabled to false to run without it."
        )
    return problems


_instance_mutex = None


def already_running(name: str = "Local\\MirabelVoiceSingleInstance") -> bool:
    """Return True when another Mirabel Voice process holds the app mutex.

    The mutex handle stays open for the life of this process, so the next
    launch sees it. A second running copy would paste every dictation twice.
    """
    global _instance_mutex  # noqa: PLW0603 - the handle must outlive this call
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        _instance_mutex = kernel32.CreateMutexW(None, False, name)
        return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 - never block startup over the guard
        return False


def _show_error_box(message: str) -> None:
    """Show a Windows message box, so errors are visible without a console."""
    _show_box(
        f"{message}\n\nRun setup.ps1 to store the keys, then start "
        "Mirabel Voice again.",
        icon=0x10,  # MB_ICONERROR
    )


def _show_info_box(message: str) -> None:
    """Show an informational Windows message box."""
    _show_box(message, icon=0x40)  # MB_ICONINFORMATION


def _show_box(message: str, icon: int) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, message, "Mirabel Voice", icon
        )
    except Exception:  # noqa: BLE001 - a failed dialog must not mask the exit code
        pass


def main(argv: list[str] | None = None) -> int:
    """Start the app. Return the process exit code."""
    parser = argparse.ArgumentParser(
        prog="mirabel-voice",
        description="Hold a key, speak, and the text appears in any program.",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Run in the console without a tray icon.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print the microphones and exit.",
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Print the path of the settings file and exit.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print debug messages."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
    )

    if args.config:
        print(config_path())
        return 0

    if args.list_devices:
        from .audio import list_input_devices

        for device in list_input_devices():
            print(f"[{device['index']}] {device['name']}")
        return 0

    if already_running():
        message = (
            "Mirabel Voice is already running. Look for the microphone "
            "icon near the clock (click the ^ arrow if it is hidden)."
        )
        print(message, file=sys.stderr)
        if not args.no_tray:
            _show_info_box(message)
        return 0

    load_api_keys()
    config = Config.load()
    problems = _check_keys(config)
    for problem in problems:
        print(f"Setup problem: {problem}", file=sys.stderr)
    if any("OPENAI_API_KEY" in p for p in problems):
        # Under pythonw (the Desktop shortcut) stderr is invisible, so a
        # silent exit would look like the app simply not starting.
        _show_error_box("\n\n".join(problems))
        return 2

    app = VoiceApp(config)

    if args.no_tray:
        app._on_state = lambda state, detail: print(  # noqa: SLF001
            f"[{state}] {detail}".rstrip()
        )
        app.start()
        print(
            f"Ready. Hold {config.hotkey} and speak. Press Ctrl+C to quit."
        )
        try:
            app.join()
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            app.stop()
        return 0

    from .tray import Tray

    tray = Tray(app)
    app.start()
    try:
        tray.run()
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
