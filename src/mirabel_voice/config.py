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


def keys_path(base: Path | None = None) -> Path:
    """Return the full path of the API keys file."""
    return (base or config_dir()) / "keys.json"


KEY_FIELDS = {
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}


def load_api_keys(base: Path | None = None) -> None:
    """Read keys.json and fill the missing environment variables.

    An environment variable that is already set always wins. A missing or
    unreadable keys file is not an error.
    """
    target = keys_path(base)
    if not target.exists():
        return
    try:
        # utf-8-sig also accepts the BOM that Windows PowerShell writes.
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    for field_name, env_name in KEY_FIELDS.items():
        value = raw.get(field_name)
        if value and not os.environ.get(env_name):
            os.environ[env_name] = str(value)


def relay_base(url: str) -> str:
    """Return the relay address with no trailing slash.

    The Function URL that AWS prints ends with one, and both provider SDKs
    add their own separator when they build a path.
    """
    return url.rstrip("/")


@dataclass
class Config:
    """All user settings.

    Attributes:
        hotkey: The key you hold to record. See hotkey.py for the names.
        mode: "toggle" starts on one press and stops on the next, so you
            can speak with your hands free. "hold" records only while you
            hold the key down.
        sample_rate: Microphone sample rate in Hz. Whisper uses 16000.
        input_device: Microphone name or index. None selects the default
            Windows microphone.
        min_seconds: The app discards audio shorter than this value.
        max_seconds: The app stops the recording at this length.
        transcribe_model: The OpenAI speech-to-text model.
        language: A two-letter language code, or None to detect it.
        cleanup_enabled: True sends the transcript to Claude for a cleanup.
        cleanup_model: The Claude model that does the cleanup.
        cleanup_timeout: Seconds to wait for Claude. The app uses the raw
            transcript if Claude is slower than this value.
        custom_words: Names and terms that the models must spell correctly.
        paste_last_hotkey: The key combination that pastes the last
            transcript again. Uses the same format as hotkey.
        streaming_enabled: True shows the words while you speak and makes
            the wait after the hotkey shorter. It costs about six times more
            per minute, so it ships off. show_overlay and live_insert do
            nothing while it is off.
        streaming_model: The live transcription model.
        show_overlay: True shows the live words in a small window near
            the cursor while you speak. Needs streaming_enabled.
        live_insert: True types the words straight into the program you
            are using while you speak, then replaces them with the clean
            version. Needs streaming_enabled. It also needs a hotkey with no
            Ctrl, Alt, Shift, or Windows key in it, because Windows refuses
            typed characters while such a key is held. With a modifier
            hotkey the words go to the preview window instead.
        inject_method: "paste" uses the clipboard and Ctrl+V. "type" sends
            each character as a keystroke.
        restore_clipboard: True puts your old clipboard content back after
            a paste.
        play_sounds: True plays a short beep on start and on stop.
        show_status: True shows a small panel near the bottom of the
            screen while the app listens and while it writes your text,
            so that the wait does not look like a failure. It also shows
            the reason when a dictation produces nothing. It never takes
            the keyboard focus and clicks pass through it.
        auto_update: True lets the installed app keep itself current:
            once a day it fetches the newest release, applies it, and
            restarts between dictations. Only the installed bundle does
            this; a source checkout and the packaged program never
            self-update.
        relay_url: The address of the relay that holds the provider keys.
            When it is set, transcription and cleanup travel through the
            relay and this machine needs no provider keys of its own.
            None sends the calls straight to the providers, which is the
            development mode.
        relay_token: The personal token this machine shows the relay. The
            owner issues one per person, and the usage log names the
            holder. It is needed whenever relay_url is set, unless the
            Google sign-in below replaces it.
        google_client_id: Our Google OAuth client. When this and the
            secret are set beside relay_url, the app signs the person in
            with their Mirabel Google account and shows that sign-in to
            the relay, and relay_token is no longer used. Both values
            ship in the zip; neither is a secret.
        google_client_secret: The OAuth client's companion value. Google
            issues one to desktop apps while documenting that they
            cannot keep it secret; it grants nothing without a person
            signing in.
    """

    hotkey: str = "insert"
    mode: str = "toggle"
    sample_rate: int = 16000
    input_device: str | int | None = None
    min_seconds: float = 0.4
    max_seconds: float = 300.0
    transcribe_model: str = "gpt-4o-mini-transcribe"
    language: str | None = "en"
    cleanup_enabled: bool = True
    cleanup_model: str = "claude-haiku-4-5"
    cleanup_timeout: float = 20.0
    custom_words: list[str] = field(default_factory=list)
    paste_last_hotkey: str = "shift+alt+z"
    streaming_enabled: bool = False
    streaming_model: str = "gpt-live-transcribe"
    show_overlay: bool = True
    live_insert: bool = True
    inject_method: str = "paste"
    restore_clipboard: bool = True
    play_sounds: bool = True
    show_status: bool = True
    auto_update: bool = True
    relay_url: str | None = None
    relay_token: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Read the settings file. Write a default file if none exists."""
        target = path or config_path()
        if not target.exists():
            cfg = cls()
            cfg.save(target)
            return cfg
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
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
