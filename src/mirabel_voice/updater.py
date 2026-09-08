"""Keep the installed bundle current, from inside the app.

The bootstrap in the repository updates a machine when its person
pastes the install line. This removes even that: the app checks the
newest release once a day and applies it the same careful way - swap
the package folder, prove the result imports, or put the old code
back - then restarts itself when the person is not mid-dictation.

Only the installed bundle updates itself. A development checkout is
git's job, and the packaged .exe is frozen; both leave this off.
The Python runtime is never touched, so a release that changes the
bundle itself is refused by the proof step and waits for the person
to fetch the new zip, exactly as the bootstrap does.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

RELEASE_API = "https://api.github.com/repos/mirabeltech/mirabel-voice/releases/latest"
ARCHIVE_BASE = "https://github.com/mirabeltech/mirabel-voice/archive/refs/tags"

# The child spawned for a restart carries this variable, so that it
# waits for our mutex instead of announcing "already running".
RELAUNCH_ENV = "MIRABEL_VOICE_RELAUNCH"

CREATE_NO_WINDOW = 0x08000000  # no console flash under pythonw


def parse_version(text: str) -> tuple[int, ...] | None:
    """Return a comparable version, or None when the text holds none."""
    match = re.search(r"(\d+(?:\.\d+)+)", text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _fetch(url: str, headers: dict | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "mirabel-voice"})
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise ValueError('Update download is too large')
        return data


def content_hash(root: Path) -> str:
    """One hash for a folder's contents, stable across zip containers.

    GitHub does not promise byte-identical archives forever - the
    compression has changed under people before - so the endorsement
    hashes what gets installed, not the zip it travelled in. The same
    function runs here and in the endorse step of the relay deploy,
    which is what makes the two answers comparable.
    """
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        digest.update(file.relative_to(root).as_posix().encode())
        digest.update(b"\x00")
        digest.update(file.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def relay_endorsement(relay_url: str, credential, fetch=None):  # noqa: ANN001
    """Return a callable that asks the relay which release it endorses.

    credential is what the SDK clients hold: the person's sign-in as a
    callable, or the static token. It is resolved on every ask, so a
    sign-in refreshed between checks is used, not remembered.
    """
    base = relay_url.rstrip("/")

    def ask() -> dict | None:
        key = credential() if callable(credential) else credential
        if not key:
            return None
        answer = json.loads((fetch or _fetch)(f"{base}/update", {"x-api-key": key}))
        if isinstance(answer, dict) and answer.get("version") and answer.get("sha256"):
            return answer
        return None

    return ask


def endorsement_for(config, signin=None):  # noqa: ANN001
    """Build this machine's endorsement asker, or None without a relay."""
    if not getattr(config, "relay_url", None):
        return None
    credential = signin.credential if signin is not None else config.relay_token
    return relay_endorsement(config.relay_url, credential)


class Updater:
    """Swap the installed package for the newest release, safely."""

    def __init__(
        self,
        site_packages: Path,
        python_dir: Path,
        fetch=None,  # noqa: ANN001 - a callable url -> bytes, for tests
        prove=None,  # noqa: ANN001 - a callable () -> bool, for tests
        endorsement=None,  # noqa: ANN001 - asks the relay what it endorses
    ) -> None:
        self.site_packages = site_packages
        self.python_dir = python_dir
        self._fetch = fetch or _fetch
        self._prove = prove if prove is not None else self._app_answers
        self._prove_staging = prove is None
        self._endorsement = endorsement
        self.outcome = "current"
        self.message = "Already up to date."

    @classmethod
    def discover(cls, endorsement=None) -> "Updater | None":  # noqa: ANN001
        """Return an updater for this process, or None outside the bundle.

        The bundle's layout is python\\Lib\\site-packages\\mirabel_voice
        with the signed interpreter two levels up. Anything else - the
        source checkout, the frozen .exe - is not ours to update.
        """
        if getattr(sys, "frozen", False):
            return None
        package = Path(__file__).resolve().parent
        site = package.parent
        python_dir = site.parent.parent
        if site.name.lower() != "site-packages":
            return None
        if not (python_dir / "pythonw.exe").exists():
            return None
        return cls(site_packages=site, python_dir=python_dir, endorsement=endorsement)

    # --- What is installed, what is out ------------------------------------

    def installed_version(self) -> tuple[int, ...] | None:
        """Read the version from the dist-info marker the installer wrote.

        The marker's version descends from pyproject.toml, the one
        place the version lives.
        """
        version_file = self.site_packages / "mirabel_voice" / "_version.txt"
        if version_file.exists():
            return parse_version(version_file.read_text().strip())
        marker = self._dist_info()
        return parse_version(marker.name) if marker else None

    def _dist_info(self) -> Path | None:
        """Return the newest version marker.

        An install over an old bundle can leave the old marker beside
        the new one, and the newest of them is the truth.
        """
        markers = list(self.site_packages.glob("mirabel_voice-*.dist-info"))
        if not markers:
            return None
        return max(markers, key=lambda marker: parse_version(marker.name) or (0,))

    def latest(self) -> tuple[tuple[int, ...], str] | None:
        """Return the newest release's version and its source address."""
        try:
            tag = json.loads(self._fetch(RELEASE_API)).get("tag_name", "")
        except Exception as error:  # noqa: BLE001 - offline is an ordinary day
            log.debug("The release check did not reach GitHub: %s", error)
            return None
        version = parse_version(tag)
        if version is None:
            return None
        return version, f"{ARCHIVE_BASE}/{tag}.zip"

    # --- The swap -----------------------------------------------------------

    def _endorsed(self) -> dict | None:
        """Ask the relay what it endorses. No answer is an answer."""
        if self._endorsement is None:
            return None
        try:
            return self._endorsement()
        except Exception as error:  # noqa: BLE001 - retain the installed release
            log.debug("The relay offered no endorsement: %s", error)
            return None

    def apply_latest(self) -> str | None:
        from .transaction import InstallLock, UpdateBusy
        try:
            with InstallLock(self.python_dir.parent):
                self.outcome, self.message = "current", "Already up to date."
                return self._apply_locked()
        except UpdateBusy:
            self.outcome, self.message = "deferred", "Another installation or update is running."
        except Exception:
            self.outcome, self.message = "failed", "Update failed. The previous copy was retained; try again or repair from the full bundle."
            log.exception("Update failed; use the stable launcher for recovery.")
        return None

    def _apply_locked(self) -> str | None:
        """Update to what the relay endorses, or to the newest release.

        The endorsement outranks the release list: when the relay names
        a version and a hash, only that version at that hash installs.
        Relay-managed machines keep their installed version when approval
        is unavailable. Only machines without a relay follow GitHub alone.
        An explicit endorsement can recall a release to an older version.

        None means there was nothing to do, or nothing safe to do: no
        newer release, no network, a hash that did not match, or a
        release the proof step refused, in which case the old code is
        already back in place.
        """
        required_hash = None
        endorsed = self._endorsed()
        if self._endorsement is not None and not endorsed:
            self.outcome, self.message = "unavailable", "Update approval is unavailable. Sign in and try again later."
            log.warning(self.message)
            return None
        if endorsed:
            if not isinstance(endorsed, dict):
                self.outcome, self.message = "unavailable", "Update approval was invalid. Nothing changed."
                return None
            tag = endorsed.get("version", "")
            required_hash = endorsed.get("sha256", "")
            if (
                not isinstance(tag, str)
                or re.fullmatch(r"\d+\.\d+\.\d+", tag) is None
                or not isinstance(required_hash, str)
                or re.fullmatch(r"[0-9a-fA-F]{64}", required_hash) is None
            ):
                self.outcome, self.message = "unavailable", "Update approval was invalid. Nothing changed."
                log.warning(self.message)
                return None
            version = parse_version(tag)
            url = f"{ARCHIVE_BASE}/v{tag}.zip"
            required_hash = required_hash.lower()
        else:
            release = self.latest()
            if release is None:
                self.outcome, self.message = "unavailable", "The update service could not be reached."
                return None
            version, url = release
        installed = self.installed_version()
        if installed and (version == installed or (not endorsed and version < installed)):
            return None

        try:
            archive = zipfile.ZipFile(io.BytesIO(self._fetch(url)))
        except Exception as error:  # noqa: BLE001
            self.outcome, self.message = "failed", "The download failed. Nothing changed."
            log.warning("The release download failed: %s", type(error).__name__)
            return None

        with tempfile.TemporaryDirectory(prefix="mirabel-voice-update-") as work:
            # Bound expansion and reject ambiguous/traversal members before writing.
            if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("Release archive is too large")
            for member in archive.infolist():
                relative = Path(member.filename.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts or ":" in member.filename:
                    raise ValueError("Unsafe archive path")
            archive.extractall(work)
            staged = next(
                (
                    parent / "mirabel_voice"
                    for parent in Path(work).glob("*/src")
                    if (parent / "mirabel_voice" / "__init__.py").exists()
                ),
                None,
            )
            if staged is None:
                self.outcome, self.message = "failed", "The release has no app package. Nothing changed."
                log.warning(self.message)
                return None
            if required_hash and content_hash(staged) != required_hash:
                self.outcome, self.message = "failed", "Download verification failed. Nothing changed."
                log.warning(self.message)
                return None
            candidate_lock = staged.parent.parent / 'packaging' / 'requirements-windows.lock'
            installed_lock = self.site_packages / 'mirabel_voice' / '_runtime.lock'
            if installed_lock.exists() and (not candidate_lock.exists() or candidate_lock.read_bytes() != installed_lock.read_bytes()):
                self.outcome, self.message = 'bundle_required', 'The approved update needs a new Python bundle. Download it from the company drive.'
                return None
            if candidate_lock.exists():
                shutil.copyfile(candidate_lock, staged / '_runtime.lock')
            return self._swap(staged, version)

    def _swap(self, staged: Path, version: tuple[int, ...]) -> str | None:
        """Move the new code in with the old code one rename away.

        The running app keeps its imported modules, so the disk can
        change under it; only the next start reads the new files. The
        window with no package on disk is two renames wide.
        """
        from .transaction import replace_directory
        target = self.site_packages / "mirabel_voice"
        name = ".".join(str(part) for part in version)
        (staged / "_version.txt").write_text(name, encoding="utf-8")
        old_version = self.installed_version()
        if old_version and not (target / "_version.txt").exists():
            (target / "_version.txt").write_text(".".join(map(str, old_version)), encoding="utf-8")
        try:
            if self._prove_staging:
                code = "import sys; sys.path.insert(0, sys.argv[1]); from mirabel_voice.health import check; check()"
                check = subprocess.run([str(self.python_dir / 'python.exe'), '-c', code, str(staged.parent)], capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW)
                if check.returncode:
                    raise RuntimeError('Staged app failed its startup checks')
            replace_directory(target, staged, self._prove)
        except RuntimeError:
            self.outcome, self.message = "bundle_required", "This update needs the full bundle download. The previous version was retained."
            return None
        # Package-local version is the transactional authority. Keep dist-info
        # useful to inventory tools too; recovery still works if this is interrupted.
        try:
            marker = self._dist_info()
            wanted = self.site_packages / f"mirabel_voice-{name}.dist-info"
            if marker is not None:
                metadata = marker / "METADATA"
                if metadata.exists():
                    text = re.sub(r"(?m)^Version: .*", "Version: " + name, metadata.read_text(encoding="utf-8"))
                    metadata.write_text(text, encoding="utf-8")
                for stale in self.site_packages.glob("mirabel_voice-*.dist-info"):
                    if stale != marker:
                        shutil.rmtree(stale)
                if marker != wanted:
                    marker.rename(wanted)
        except OSError:
            log.warning("App update committed; dependency inventory metadata needs repair.")
        self.outcome, self.message = "updated", f"Updated to {name}. Restarting when dictation finishes."
        return name

    def _app_answers(self) -> bool:
        """Prove the code on disk still imports and answers."""
        try:
            done = subprocess.run(  # noqa: S603
                [str(self.python_dir / "python.exe"), "-m", "mirabel_voice", "--self-test"],
                capture_output=True,
                timeout=120,
                creationflags=CREATE_NO_WINDOW,
                cwd=str(self.python_dir.parent),
            )
        except Exception:  # noqa: BLE001 - a proof that cannot run proves nothing
            return False
        return done.returncode == 0

    # --- The restart ---------------------------------------------------------

    def start_new_copy(self) -> bool:
        """Start the updated app; it waits for this process to leave.

        The caller quits right after. The child sees the instance mutex
        still held, waits for it because of the environment flag, and
        takes over the moment this process exits.
        """
        env = dict(os.environ)
        env[RELAUNCH_ENV] = "1"
        try:
            subprocess.Popen(  # noqa: S603
                [str(self.python_dir / "pythonw.exe")] + ([str(self.python_dir.parent / "launcher.py")] if (self.python_dir.parent / "launcher.py").exists() else ["-m", "mirabel_voice"]),
                cwd=str(self.python_dir.parent),
                env=env,
            )
        except Exception:  # noqa: BLE001
            log.exception("The updated app did not start.")
            return False
        return True


class UpdateCoordinator:
    """One coordinator shared by tray, background timer and update requests."""
    def __init__(self, app, updater, stop):
        self.app, self.updater, self.stop = app, updater, stop
        self._lock = threading.Lock()

    def request(self, notify=lambda message: None):
        if self.updater is None:
            notify("Updates are available only in the installed Python bundle.")
            return
        if not self._lock.acquire(blocking=False):
            notify("An update check is already running.")
            return
        def run():
            import time
            try:
                notify("Checking for an approved update...")
                # Protect both disk switching and restart from new dictations.
                while not self.app.reserve_update():
                    if self.app._stopped:
                        return
                    notify("Update deferred until dictation finishes.")
                    time.sleep(1)
                try:
                    version = self.updater.apply_latest()
                    notify(self.updater.message)
                    if version:
                        self.app.injector.flush_restore() if hasattr(self.app.injector, "flush_restore") else None
                        if self.updater.start_new_copy():
                            self.stop()
                        else:
                            notify("Update installed. Quit and start Mirabel Voice to use it.")
                finally:
                    self.app.release_update()
            finally:
                self._lock.release()
        threading.Thread(target=run, name="mirabel-voice-update", daemon=True).start()
