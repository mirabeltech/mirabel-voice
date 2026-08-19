r"""Choose the key you want to dictate with.

The person presses the key they want and the choice is saved. This lives
in the package, not in scripts, because the installed app has no scripts
folder next to it.

Use a key that does nothing else on the computer. Keys with Ctrl, Alt,
Shift, or Windows in them work for dictation, but they cannot type the
words into the text box as the person speaks, because Windows refuses
typed characters while such a key is held.
"""

from __future__ import annotations

import json

from .config import Config, config_path

MODIFIERS = {
    "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr",
    "shift", "shift_l", "shift_r", "cmd", "cmd_l", "cmd_r",
}

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


def save_choice(key: str) -> tuple[str | None, bool]:
    """Store the key in the settings file.

    Returns the key that was in use before, and whether the words can now
    type straight into the text box.
    """
    target = config_path()
    if not target.exists():
        # A fresh install may not have written the file yet.
        Config().save(target)
    settings = json.loads(target.read_text(encoding="utf-8-sig"))
    previous = settings.get("hotkey")
    live = key not in MODIFIERS
    settings["hotkey"] = key
    settings["live_insert"] = live
    target.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return previous, live


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
    if key in MODIFIERS:
        print(
            "\nThat is a modifier key. Dictation will work, but the words "
            "cannot appear in your text box as you speak. They will show in "
            "the small preview window instead."
        )

    previous, live = save_choice(key)
    print(f"\nSaved. Your dictation key is now: {key}   (was {previous})")
    print("Restart Mirabel Voice, then press that key and speak.")
    if live:
        print("The words will type straight into your text box.")
    return 0
