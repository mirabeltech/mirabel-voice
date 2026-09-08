"""Atomic per-user persistence. Recovery copies have the same protection as live data."""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

_WRITE_LOCK = threading.RLock()


def replace_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_bytes(path: Path, data: bytes, *, backup: bool = True) -> None:
    with _WRITE_LOCK:
        if backup and path.exists():
            replace_bytes(path.with_suffix(path.suffix + '.bak'), path.read_bytes())
        replace_bytes(path, data)


def load_validated(path: Path, decode):
    """Keep a damaged file intact and return a validated backup when available."""
    with _WRITE_LOCK:
        try:
            return decode(path.read_bytes())
        except (OSError, ValueError, TypeError, KeyError) as error:
            backup = path.with_suffix(path.suffix + '.bak')
            try:
                result = decode(backup.read_bytes())
            except (OSError, ValueError, TypeError, KeyError):
                raise ValueError(f'{path.name} cannot be read. Restore a valid backup or repair the settings file.') from error
            # Preserve the damaged bytes for repair; do not promote them over the backup.
            if path.exists():
                replace_bytes(path.with_suffix(path.suffix + '.damaged'), path.read_bytes())
            replace_bytes(path, backup.read_bytes())
            return result
