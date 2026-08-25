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
    """Return a message for each credential this machine is missing.

    A relay machine holds one token and no provider keys, so the token is
    the only thing to look for. A direct machine holds the two keys.
    """
    if config.relay_url:
        if config.google_client_id and config.google_client_secret:
            return []  # the sign-in flow is the credential
        if not config.relay_token:
            return [
                "This machine dictates through the relay but holds no token. "
                "Ask Tommy for yours, then run setup.ps1 again."
            ]
        return []

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
        f"{message}\n\n{_how_to_fix_keys()}",
        icon=0x10,  # MB_ICONERROR
    )


def _how_to_fix_keys() -> str:
    """Return the repair step that suits how this copy was installed."""
    if getattr(sys, "frozen", False):
        # The installed app has no setup.ps1 beside it. The installer is
        # the only thing that stores a token, so send the user back to it.
        return (
            "Run the Mirabel Voice installer again and enter your token. "
            "Ask Tommy for it."
        )
    return "Run setup.ps1 to store your token, then start Mirabel Voice again."


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
        "--check-keys",
        action="store_true",
        help="Test this machine's credentials and exit.",
    )
    parser.add_argument(
        "--set-relay",
        nargs="+",
        metavar="URL TOKEN",
        help="Point this machine at the relay, and exit. The token is "
             "optional: pass the address alone to keep the stored token.",
    )
    parser.add_argument(
        "--forget-relay-token",
        action="store_true",
        help="Remove the stored relay token, keeping every other setting.",
    )
    parser.add_argument(
        "--set-google",
        nargs=2,
        metavar=("CLIENT_ID", "CLIENT_SECRET"),
        help="Store the Google sign-in client, and exit. From then on the "
             "app signs in with the work account instead of a token.",
    )
    parser.add_argument(
        "--has-relay-token",
        action="store_true",
        help="Exit 0 when this machine already holds a relay token.",
    )
    parser.add_argument(
        "--check-audio",
        action="store_true",
        help="Test that the audio encoder works and exit.",
    )
    parser.add_argument(
        "--pick-hotkey",
        action="store_true",
        help="Press a key to choose your dictation key, then exit.",
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

    if args.set_relay:
        # The installer calls this. It writes only these two settings, so a
        # person's hotkey, words, and preferences survive an update. The
        # token is optional, so that an update install can refresh the
        # address without knowing the token that is already stored.
        if len(args.set_relay) > 2:
            print("--set-relay takes the address, and optionally the token.",
                  file=sys.stderr)
            return 2
        config = Config.load()
        config.relay_url = args.set_relay[0].strip()
        if len(args.set_relay) == 2:
            config.relay_token = args.set_relay[1].strip()
        config.save()
        print(f"This machine now dictates through {config.relay_url}")
        return 0

    if args.forget_relay_token:
        # A flag, not an empty argument: PowerShell drops an empty string
        # on its way to a program, which left a refused token in place.
        config = Config.load()
        config.relay_token = None
        config.save()
        print("This machine no longer holds a relay token.")
        return 0

    if args.set_google:
        # The installer calls this beside --set-relay. Two settings only,
        # so the person's own preferences survive an update.
        config = Config.load()
        config.google_client_id = args.set_google[0].strip()
        config.google_client_secret = args.set_google[1].strip()
        config.save()
        print("This machine now signs in with the Mirabel Google account.")
        return 0

    if args.has_relay_token:
        # The installers ask this before deciding whether to prompt.
        return 0 if Config.load().relay_token else 1

    if args.check_keys:
        from .keycheck import check_keys

        ok, message = check_keys()
        print(message)
        return 0 if ok else 1

    if args.check_audio:
        # A packaged copy that cannot load the encoder still dictates, but
        # sends nine times more audio and never says so. This is how you
        # find that out.
        from .audio import check_encoder

        ok, message = check_encoder()
        print(message)
        return 0 if ok else 1

    if args.pick_hotkey:
        from .picker import pick_hotkey

        return pick_hotkey()

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
    # A missing Anthropic key costs only the cleanup, so it is a warning.
    # Anything else means no dictation at all.
    if [p for p in problems if "ANTHROPIC_API_KEY" not in p]:
        # Under pythonw (the Desktop shortcut) stderr is invisible, so a
        # silent exit would look like the app simply not starting.
        _show_error_box("\n\n".join(problems))
        return 2

    app = VoiceApp(config)

    if app.signin is not None and not app.signin.signed_in():
        # First run: the browser opens once, the person signs in with the
        # account they already have, and that is the whole setup.
        print("Opening the Google sign-in page in your browser...")
        try:
            email = app.signin.sign_in()
        except Exception as error:  # noqa: BLE001 - explain, do not crash
            message = (
                f"The Google sign-in did not complete: {error}\n\n"
                "Start Mirabel Voice again to retry, or right-click the "
                "icon near the clock and choose Sign in with Google."
            )
            print(message, file=sys.stderr)
            if not args.no_tray:
                _show_box(message, icon=0x30)  # MB_ICONWARNING
        else:
            print(f"Signed in as {email}.")

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

    overlay = None
    # One window serves two jobs. The status panel runs for everybody. The
    # live words need streaming, and also cover the times when typing into
    # the field is impossible, such as while a modifier hotkey is held.
    wants_words = config.streaming_enabled and (config.show_overlay or config.live_insert)
    if config.show_status or wants_words:
        from .overlay import Overlay

        overlay = Overlay()
        if overlay.start():
            if wants_words:
                app.on_partial = overlay.update
            if config.show_status:
                app.on_status = overlay.status
        else:
            overlay = None

    tray = Tray(app)
    app.start()
    try:
        tray.run()
    finally:
        app.stop()
        if overlay is not None:
            overlay.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
