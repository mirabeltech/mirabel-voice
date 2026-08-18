"""User settings for Mirabel Voice.

Settings live in one JSON file. The app writes a default file on first start.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "MirabelVoice"


def config_dir() -> Path:
    """Return the folder that holds the settings file."""
    base = os.environ.get("MIRABEL_VOICE_HOME")
    if base:
        return Path(base)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def config_path() -> Path:
    """Return the full path of the settings file."""
    return config_dir() / "config.json"


@dataclass
class Config:
    """All user settings.

    Attributes:
        hotkey: The key you hold to record. See hotkey.py for the names.
        mode: "hold" records while you hold the key. "toggle" starts and
            stops on each press.
        sample_rate: Microphone sample rate in Hz. Whisper uses 16000.
        input_device: Microphone name or index. None selects the default
            Windows microphone.
        min_seconds: The app discards audio shorter than this value.
        max_seconds: The app stops the recording at this length.
        transcribe_model: The OpenAI speech-to-text model.
        language: A two-letter language code, or None to detect it.
        cleanup_enabled: True sends the transcript to Claude for a cleanup.
        cleanup_model: The Claude model that does the cleanup.
        cleanup_effort: Claude thinking effort. "low" keeps the delay small.
        cleanup_timeout: Seconds to wait for Claude. The app uses the raw
            transcript if Claude is slower than this value.
        custom_words: Names and terms that the models must spell correctly.
        inject_method: "paste" uses the clipboard and Ctrl+V. "type" sends
            each character as a keystroke.
        restore_clipboard: True puts your old clipboard content back after
            a paste.
        play_sounds: True plays a short beep on start and on stop.
    """

    hotkey: str = "ctrl_r"
    mode: str = "hold"
    sample_rate: int = 16000
    input_device: str | int | None = None
    min_seconds: float = 0.4
    max_seconds: float = 300.0
    transcribe_model: str = "whisper-1"
    language: str | None = "en"
    cleanup_enabled: bool = True
    cleanup_model: str = "claude-opus-5"
    cleanup_effort: str = "low"
    cleanup_timeout: float = 20.0
    custom_words: list[str] = field(default_factory=list)
    inject_method: str = "paste"
    restore_clipboard: bool = True
    play_sounds: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Read the settings file. Write a default file if none exists."""
        target = path or config_path()
        if not target.exists():
            cfg = cls()
            cfg.save(target)
            return cfg
        raw = json.loads(target.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> Path:
        """Write the settings to disk and return the path."""
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target
