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

    load_api_keys()
    config = Config.load()
    for problem in _check_keys(config):
        print(f"Setup problem: {problem}", file=sys.stderr)
    if any("OPENAI_API_KEY" in p for p in _check_keys(config)):
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
