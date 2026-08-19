r"""Choose the key you want to dictate with.

Run it, press the key you want, and it saves your choice:

    .venv\Scripts\python.exe scripts\pick_hotkey.py

The installed app does the same job from the icon near the clock:
right-click it and choose "Change my dictation key".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.picker import pick_hotkey  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(pick_hotkey())
