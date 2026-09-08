"""Allowlisted support facts. Never export raw logs, configuration or environment."""
import json
import platform
from pathlib import Path
from .config import config_dir


def export(destination: Path | None = None) -> Path:
    from .health import check
    from .updater import Updater
    from .flyout import app_version
    try:
        check()
        health = 'passed'
    except Exception as error:
        health = type(error).__name__  # provider/exception text can contain secrets
    updater = Updater.discover()
    facts = {'app_version': app_version(), 'windows': platform.version(),
             'architecture': platform.machine(), 'python': platform.python_version(),
             'bundle': updater is not None, 'offline_health': health,
             'privacy': 'No logs, account names, paths, credentials, audio or dictation text included.'}
    path = destination or config_dir() / 'support.json'
    from .storage import save_bytes
    save_bytes(path, (json.dumps(facts, indent=2) + '\n').encode(), backup=False)
    return path
