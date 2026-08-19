r"""Choose the key you want to dictate with.

Run it, press the key you want, and it saves your choice:

    .venv\Scripts\python.exe scripts\pick_hotkey.py

Use a key that does nothing else on your computer. Keys with Ctrl, Alt,
Shift, or Windows in them work for dictation, but they cannot type the
words into your text box as you speak, because Windows refuses typed
characters while such a key is held.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.config import config_path  # noqa: E402

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


def main() -> int:
    from pynput import keyboard

    print("\nMirabel Voice - choose your dictation key\n")
    print(SUGGESTIONS)
    print("\nPress the key you want to use. Press Esc to keep what you have.\n")

    chosen: list[str] = []

    def on_press(key) -> bool | None:  # noqa: ANN001
        from pynput.keyboard import Key

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

    target = config_path()
    settings = json.loads(target.read_text(encoding="utf-8-sig"))
    previous = settings.get("hotkey")
    settings["hotkey"] = key
    settings["live_insert"] = key not in MODIFIERS
    target.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    print(f"\nSaved. Your dictation key is now: {key}   (was {previous})")
    print("Restart Mirabel Voice, then hold that key and speak.")
    if settings["live_insert"]:
        print("The words will type straight into your text box.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
