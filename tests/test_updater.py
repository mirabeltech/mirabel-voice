"""Tests for the in-app updater.

The updater swaps site-packages\\mirabel_voice for the newest release
the same careful way the bootstrap does: prove the result answers, or
put the old code back. Everything network-shaped is injected.
"""

import io
import json
import zipfile

from mirabel_voice.updater import ARCHIVE_BASE, RELEASE_API, Updater, parse_version


def a_bundle(tmp_path, version="0.4.0"):
    """Lay out an installed bundle the way build_bundle.ps1 leaves one."""
    site = tmp_path / "python" / "Lib" / "site-packages"
    (site / "mirabel_voice").mkdir(parents=True)
    (site / "mirabel_voice" / "__init__.py").write_text("old code")
    (site / f"mirabel_voice-{version}.dist-info").mkdir()
    python_dir = tmp_path / "python"
    (python_dir / "pythonw.exe").write_text("not really")
    return site, python_dir


def a_release(tag="v0.5.0", with_package=True):
    """Return a fetch callable serving one GitHub release."""
    buffer = io.BytesIO()
    root = f"mirabel-voice-{tag.lstrip('v')}"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{root}/pyproject.toml", 'version = "irrelevant"')
        if with_package:
            archive.writestr(f"{root}/src/mirabel_voice/__init__.py", "new code")
            archive.writestr(f"{root}/src/mirabel_voice/app.py", "new app")
    served = {
        RELEASE_API: json.dumps({"tag_name": tag}).encode(),
        f"{ARCHIVE_BASE}/{tag}.zip": buffer.getvalue(),
    }
    return lambda url: served[url]  # a KeyError is a wrong address


def test_a_newer_release_is_swapped_in(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    updater = Updater(site, python_dir, fetch=a_release("v0.5.0"), prove=lambda: True)

    assert updater.apply_latest() == "0.5.0"

    assert (site / "mirabel_voice" / "__init__.py").read_text() == "new code"
    assert (site / "mirabel_voice-0.5.0.dist-info").exists()
    assert not (site / "mirabel_voice-0.4.0.dist-info").exists()
    # No half-finished folders left behind.
    assert not (site / "mirabel_voice.previous").exists()
    assert not (site / "mirabel_voice.new").exists()


def test_nothing_happens_when_already_current(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.5.0")
    proofs = []
    updater = Updater(
        site,
        python_dir,
        fetch=a_release("v0.5.0"),
        prove=lambda: proofs.append(1) or True,
    )

    assert updater.apply_latest() is None
    assert (site / "mirabel_voice" / "__init__.py").read_text() == "old code"
    assert not proofs  # nothing was even tried


def test_a_refused_proof_puts_the_old_code_back(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    updater = Updater(site, python_dir, fetch=a_release("v0.5.0"), prove=lambda: False)

    assert updater.apply_latest() is None

    assert (site / "mirabel_voice" / "__init__.py").read_text() == "old code"
    assert (site / "mirabel_voice-0.4.0.dist-info").exists()
    assert not (site / "mirabel_voice.previous").exists()
    assert not (site / "mirabel_voice.new").exists()


def test_no_network_is_an_ordinary_day(tmp_path):
    def fetch(url):
        raise OSError("offline")

    site, python_dir = a_bundle(tmp_path)
    updater = Updater(site, python_dir, fetch=fetch, prove=lambda: True)

    assert updater.latest() is None
    assert updater.apply_latest() is None
    assert (site / "mirabel_voice" / "__init__.py").read_text() == "old code"


def test_a_download_with_no_package_changes_nothing(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    updater = Updater(
        site,
        python_dir,
        fetch=a_release("v0.5.0", with_package=False),
        prove=lambda: True,
    )

    assert updater.apply_latest() is None
    assert (site / "mirabel_voice" / "__init__.py").read_text() == "old code"


def test_a_stale_marker_does_not_hide_the_installed_version(tmp_path):
    # Install.ps1 used to copy the new bundle over the old one, leaving
    # both version markers behind. The newest one is the truth.
    site, python_dir = a_bundle(tmp_path, version="0.5.1")
    (site / "mirabel_voice-0.5.0.dist-info").mkdir()
    updater = Updater(site, python_dir, fetch=a_release("v0.5.1"), prove=lambda: True)

    assert updater.installed_version() == (0, 5, 1)
    assert updater.apply_latest() is None  # already current, no re-install


def test_an_update_sweeps_stale_markers_away(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.4.1")
    (site / "mirabel_voice-0.4.0.dist-info").mkdir()
    updater = Updater(site, python_dir, fetch=a_release("v0.5.0"), prove=lambda: True)

    assert updater.apply_latest() == "0.5.0"

    assert (site / "mirabel_voice-0.5.0.dist-info").exists()
    assert not (site / "mirabel_voice-0.4.0.dist-info").exists()
    assert not (site / "mirabel_voice-0.4.1.dist-info").exists()


def test_discover_declines_this_source_checkout():
    # The tests run from the repository, which git manages. Only the
    # installed bundle - site-packages beside a pythonw.exe - updates.
    assert Updater.discover() is None


def test_versions_parse_from_tags_and_marker_names():
    assert parse_version("v0.5.0") == (0, 5, 0)
    assert parse_version("mirabel_voice-0.4.0.dist-info") == (0, 4, 0)
    assert parse_version("0.10.1") == (0, 10, 1)
    assert parse_version("nonsense") is None
    assert parse_version("") is None


def test_the_replacement_waits_for_the_old_copy_to_leave():
    from mirabel_voice.__main__ import _wait_for_exit

    states = [True, True, False]
    assert _wait_for_exit(lambda: states.pop(0) if states else False, sleep=lambda s: None)


def test_the_wait_gives_up_at_the_deadline():
    from mirabel_voice.__main__ import _wait_for_exit

    assert not _wait_for_exit(lambda: True, seconds=0, sleep=lambda s: None)


# --- The relay endorsement ---------------------------------------------------

from mirabel_voice.updater import content_hash, relay_endorsement  # noqa: E402


def hash_of_release(tmp_path):
    """The content hash of the package a_release() serves."""
    staged = tmp_path / "hash-probe"
    (staged / "mirabel_voice").mkdir(parents=True)
    (staged / "mirabel_voice" / "__init__.py").write_text("new code")
    (staged / "mirabel_voice" / "app.py").write_text("new app")
    return content_hash(staged / "mirabel_voice")


def test_the_content_hash_sees_names_and_bytes_not_containers(tmp_path):
    first = tmp_path / "a" / "pkg"
    second = tmp_path / "b" / "pkg"
    for root in (first, second):
        root.mkdir(parents=True)
        (root / "one.py").write_text("same")
    assert content_hash(first) == content_hash(second)

    (second / "one.py").write_text("different")
    assert content_hash(first) != content_hash(second)

    (second / "one.py").write_text("same")
    (second / "two.py").write_text("")
    assert content_hash(first) != content_hash(second)


def test_the_endorsement_outranks_the_newest_release(tmp_path):
    # GitHub's newest is v0.6.0, but the relay endorses v0.5.0: the
    # endorsed version installs, and the newest is never even fetched.
    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    serve = a_release("v0.5.0")
    updater = Updater(
        site,
        python_dir,
        fetch=lambda url: serve(url),
        prove=lambda: True,
        endorsement=lambda: {"version": "0.5.0", "sha256": hash_of_release(tmp_path)},
    )
    assert updater.apply_latest() == "0.5.0"
    assert (site / "mirabel_voice" / "__init__.py").read_text() == "new code"


def test_a_download_that_fails_the_hash_is_refused(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    updater = Updater(
        site,
        python_dir,
        fetch=a_release("v0.5.0"),
        prove=lambda: True,
        endorsement=lambda: {"version": "0.5.0", "sha256": "0" * 64},
    )
    assert updater.apply_latest() is None
    assert (site / "mirabel_voice" / "__init__.py").read_text() == "old code"
    assert (site / "mirabel_voice-0.4.0.dist-info").exists()


def test_no_endorsement_answer_falls_back_to_the_newest_release(tmp_path):
    def unreachable():
        raise OSError("the relay is out")

    site, python_dir = a_bundle(tmp_path, version="0.4.0")
    updater = Updater(
        site,
        python_dir,
        fetch=a_release("v0.5.0"),
        prove=lambda: True,
        endorsement=unreachable,
    )
    assert updater.apply_latest() == "0.5.0"


def test_an_endorsed_version_already_installed_means_nothing_to_do(tmp_path):
    site, python_dir = a_bundle(tmp_path, version="0.5.0")
    updater = Updater(
        site,
        python_dir,
        fetch=lambda url: (_ for _ in ()).throw(AssertionError("no fetch needed")),
        prove=lambda: True,
        endorsement=lambda: {"version": "0.5.0", "sha256": "abc"},
    )
    assert updater.apply_latest() is None


def test_the_endorsement_asker_presents_the_rotating_credential():
    asked = []

    def fetch(url, headers):
        asked.append((url, headers))
        return b'{"version": "0.5.0", "sha256": "abc"}'

    tokens = iter(["first-token", "second-token"])
    ask = relay_endorsement(
        "https://relay.example.on.aws/", lambda: next(tokens), fetch=fetch
    )

    assert ask() == {"version": "0.5.0", "sha256": "abc"}
    assert ask() == {"version": "0.5.0", "sha256": "abc"}
    assert asked[0] == (
        "https://relay.example.on.aws/update", {"x-api-key": "first-token"}
    )
    assert asked[1][1] == {"x-api-key": "second-token"}


def test_a_signed_out_machine_asks_nothing():
    ask = relay_endorsement(
        "https://relay.example.on.aws",
        lambda: None,
        fetch=lambda url, headers: (_ for _ in ()).throw(AssertionError("no call")),
    )
    assert ask() is None
