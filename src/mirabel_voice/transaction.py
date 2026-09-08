"""Standard-library-only installation lock and recoverable directory replacement.

Also copied beside the installed launcher: recovery must not import the app.
"""
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path


class UpdateBusy(RuntimeError):
    pass


class InstallLock:
    def __init__(self, root: Path):
        self.path = root / '.update.lock'
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.stream = open(self.path, 'a+b')
            if self.path.stat().st_size == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except OSError as error:
            if self.stream:
                self.stream.close()
            raise UpdateBusy('Another installation or update is in progress.') from error

    def __exit__(self, *args):
        self.stream.close()  # OS releases the lock, including after a crash.


def _write(path: Path, value: dict):
    pending = path.with_suffix('.tmp')
    with pending.open('w', encoding='utf-8') as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(pending, path)


def recover(target: Path):
    journal = target.with_name(target.name + '.transaction.json')
    backup = target.with_name(target.name + '.previous')
    incoming = target.with_name(target.name + '.new')
    if journal.exists():
        state = json.loads(journal.read_text(encoding='utf-8'))['state']
        if state == 'pending':
            if backup.exists():
                if target.exists():
                    shutil.rmtree(target)
                backup.rename(target)
            # Before first rename the target is still the previous good copy.
        elif state != 'committed':
            raise RuntimeError('Unrecognized recovery journal; repair the installation.')
        journal.unlink()
    elif not target.exists() and backup.exists():
        backup.rename(target)
    if incoming.exists():
        shutil.rmtree(incoming)


def replace_directory(target: Path, staged: Path, prove) -> bool:
    """Caller holds InstallLock. Keep the previous copy until the next update."""
    recover(target)
    incoming = target.with_name(target.name + '.new')
    backup = target.with_name(target.name + '.previous')
    journal = target.with_name(target.name + '.transaction.json')
    shutil.copytree(staged, incoming)
    # Removing an older recovery copy is safe only while target is intact.
    if backup.exists():
        shutil.rmtree(backup)
    had_target = target.exists()
    _write(journal, {'state': 'pending'})
    try:
        if target.exists():
            target.rename(backup)
        incoming.rename(target)
        if not prove():
            raise RuntimeError('The candidate failed its startup checks.')
        _write(journal, {'state': 'committed'})
    except Exception:
        if backup.exists():
            if target.exists():
                shutil.rmtree(target)
            backup.rename(target)
        elif not had_target and target.exists():
            # A failed first installation must not be mistaken for working.
            shutil.rmtree(target)
        journal.unlink(missing_ok=True)
        if incoming.exists():
            shutil.rmtree(incoming)
        raise
    journal.unlink()
    return True
