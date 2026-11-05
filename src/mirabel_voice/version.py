"""Which release is running, for the flyout, diagnostics and the relay.

This lives apart from the flyout because the flyout imports the app,
tray and overlay modules; transcribe and cleanup need the version
without pulling those in.
"""

from __future__ import annotations

import functools

# The relay logs this header's value as the usage line's version.
VERSION_HEADER = "X-Mirabel-Version"


def version_from_markers(site) -> str:  # noqa: ANN001 - a Path
    """The version by the newest dist-info folder name, or nothing.

    The updater records each source update by RENAMING the dist-info
    folder; the METADATA file inside still says whatever pip wrote at
    the original install. importlib reads that file, so it answers
    with the version pip installed, not the one running. The folder
    name is the truth.
    """
    try:
        from .updater import parse_version

        markers = list(site.glob("mirabel_voice-*.dist-info"))
        versions = [parse_version(marker.name) for marker in markers]
        versions = [v for v in versions if v]
        if versions:
            return "v" + ".".join(str(part) for part in max(versions))
    except Exception:  # noqa: BLE001 - a strange layout answers nothing
        pass
    return ""


def app_version() -> str:
    """The running version, or nothing when it cannot be known."""
    from pathlib import Path
    marker = Path(__file__).with_name("_version.txt")
    if marker.exists():
        return "v" + marker.read_text(encoding="utf-8").strip()
    try:
        from pathlib import Path

        marked = version_from_markers(Path(__file__).resolve().parent.parent)
        if marked:
            return marked
    except Exception:  # noqa: BLE001
        pass
    source_project = Path(__file__).resolve().parents[2] / 'pyproject.toml'
    if source_project.exists():
        import tomllib
        return 'v' + tomllib.loads(source_project.read_text(encoding='utf-8'))['project']['version']
    # Fall back for other installed layouts.
    try:
        from importlib.metadata import version

        return f"v{version('mirabel-voice')}"
    except Exception:  # noqa: BLE001 - a missing dist-info is fine
        return ""


@functools.lru_cache(maxsize=None)
def client_version() -> str:
    """The version the app reports to the relay: no leading v, never empty.

    Cached because the running code cannot change version without a
    restart, and every relay call asks.
    """
    return app_version().removeprefix("v") or "unknown"
