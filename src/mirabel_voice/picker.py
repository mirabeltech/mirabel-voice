r"""Choose the key you want to dictate with.

The person presses the key they want and the choice is saved. This lives
in the package, not in scripts, because the installed app has no scripts
folder next to it.

Use a key that does nothing else on the computer.
"""

from __future__ import annotations

import json

from .config import Config, config_path

SUGGESTIONS = """Keys that are usually free:
  scroll_lock    pause     insert     f13 to f24
  right ctrl (ctrl_r)      right alt (alt_r)

Avoid: keys your laptop uses for volume, brightness, or screenshots."""


def name_of(key) -> str | None:  # noqa: ANN001
    """Return the settings name for a pressed key, or None if unusable."""
    from pynput.keyboard import Key, KeyCode

    if isinstance(key, Key):
        return key.name
    if isinstance(key, KeyCode) and key.char:
        return key.char
    if isinstance(key, KeyCode) and key.vk:
        return f"<{key.vk}>"
    return None


def save_choice(key: str) -> str | None:
    """Store the key in the settings file. Return the key it replaces."""
    target = config_path()
    if not target.exists():
        # A fresh install may not have written the file yet.
        Config().save(target)
    settings = json.loads(target.read_text(encoding="utf-8-sig"))
    previous = settings.get("hotkey")
    settings["hotkey"] = key
    target.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return previous


def pick_hotkey() -> int:
    """Ask for a key, save it, and return the process exit code."""
    from pynput import keyboard
    from pynput.keyboard import Key

    print("\nMirabel Voice - choose your dictation key\n")
    print(SUGGESTIONS)
    print("\nPress the key you want to use. Press Esc to keep what you have.\n")

    chosen: list[str] = []

    def on_press(key) -> bool | None:  # noqa: ANN001
        if key is Key.esc:
            return False
        label = name_of(key)
        if label is None:
            print("  That key cannot be used. Try another.")
            return None
        chosen.append(label)
        return False

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

    if not chosen:
        print("Nothing changed.")
        return 0

    key = chosen[0]
    print(f"\nYou pressed: {key}")
    previous = save_choice(key)
    print(f"\nSaved. Your dictation key is now: {key}   (was {previous})")
    print("Restart Mirabel Voice, then press that key and speak.")
    return 0
