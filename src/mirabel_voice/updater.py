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
        return response.read()


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
        if answer.get("version") and answer.get("sha256"):
            return answer
        return None

    return ask


def endorsement_for(config, signin=None):  # noqa: ANN001
    """Build this machine's endorsement asker, or None without a relay."""
    if not getattr(config, "relay_url", None):
        return None
    credential = signin.credential if signin is not None else config.relay_token
    if not credential:
        return None
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
        self._endorsement = endorsement

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
        except Exception as error:  # noqa: BLE001 - fall back to the newest release
            log.debug("The relay offered no endorsement: %s", error)
            return None

    def apply_latest(self) -> str | None:
        """Update to what the relay endorses, or to the newest release.

        The endorsement outranks the release list: when the relay names
        a version and a hash, only that version at that hash installs.
        Without an endorsement - no relay, no answer, no network - the
        newest published release is followed, which is how machines
        behaved before endorsement existed.

        None means there was nothing to do, or nothing safe to do: no
        newer release, no network, a hash that did not match, or a
        release the proof step refused, in which case the old code is
        already back in place.
        """
        required_hash = None
        endorsed = self._endorsed()
        if endorsed:
            version = parse_version(endorsed["version"])
            if version is None:
                log.warning(
                    "The relay endorsed an unreadable version: %r.",
                    endorsed["version"],
                )
                return None
            url = f"{ARCHIVE_BASE}/v{endorsed['version']}.zip"
            required_hash = endorsed["sha256"]
        else:
            release = self.latest()
            if release is None:
                return None
            version, url = release
        installed = self.installed_version()
        if installed and version <= installed:
            return None

        try:
            archive = zipfile.ZipFile(io.BytesIO(self._fetch(url)))
        except Exception as error:  # noqa: BLE001
            log.warning("The release download failed: %s", error)
            return None

        with tempfile.TemporaryDirectory(prefix="mirabel-voice-update-") as work:
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
                log.warning("The release download holds no package; not applied.")
                return None
            if required_hash and content_hash(staged) != required_hash:
                log.warning(
                    "The download does not match what the relay endorses; "
                    "nothing was changed."
                )
                return None
            return self._swap(staged, version)

    def _swap(self, staged: Path, version: tuple[int, ...]) -> str | None:
        """Move the new code in with the old code one rename away.

        The running app keeps its imported modules, so the disk can
        change under it; only the next start reads the new files. The
        window with no package on disk is two renames wide.
        """
        target = self.site_packages / "mirabel_voice"
        incoming = self.site_packages / "mirabel_voice.new"
        backup = self.site_packages / "mirabel_voice.previous"
        for leftover in (incoming, backup):
            if leftover.exists():
                shutil.rmtree(leftover)

        shutil.copytree(staged, incoming)
        target.rename(backup)
        incoming.rename(target)

        if not self._prove():
            shutil.rmtree(target)
            backup.rename(target)
            log.warning(
                "The newest release needs more than new code; the old "
                "version was kept. The full download applies it."
            )
            return None

        shutil.rmtree(backup)
        name = ".".join(str(part) for part in version)
        wanted = self.site_packages / f"mirabel_voice-{name}.dist-info"
        marker = self._dist_info()
        # Stale markers from an install-over-install go first, so the
        # rename below never lands on a folder that already exists,
        # which Windows refuses.
        for stale in self.site_packages.glob("mirabel_voice-*.dist-info"):
            if stale != marker and stale != wanted:
                shutil.rmtree(stale)
        if marker is not None and marker != wanted and not wanted.exists():
            marker.rename(wanted)
        log.info("Updated to %s. The next start runs it.", name)
        return name

    def _app_answers(self) -> bool:
        """Prove the code on disk still imports and answers."""
        try:
            done = subprocess.run(  # noqa: S603
                [str(self.python_dir / "python.exe"), "-m", "mirabel_voice", "--config"],
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
                [str(self.python_dir / "pythonw.exe"), "-m", "mirabel_voice"],
                cwd=str(self.python_dir.parent),
                env=env,
            )
        except Exception:  # noqa: BLE001
            log.exception("The updated app did not start.")
            return False
        return True
