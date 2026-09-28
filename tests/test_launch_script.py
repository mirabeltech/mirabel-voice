"""The installed Launch.ps1, run for real by Windows PowerShell in check mode."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="runs Windows PowerShell")

LAUNCH = Path(__file__).resolve().parents[1] / "packaging" / "Launch.ps1"
STUB_LAUNCHER = "import pathlib, sys\npathlib.Path(__file__).with_name('checked').write_text(' '.join(sys.argv[1:]))\n"


def stub_runtime(folder: Path) -> None:
    """A Python that runs from any folder: this venv's launcher and its pyvenv.cfg."""
    scripts = Path(sys.executable).parent
    if not (scripts.parent / "pyvenv.cfg").exists():
        pytest.skip("needs pytest to run from a virtual environment")
    folder.mkdir(parents=True)
    for name in ("python.exe", "pythonw.exe"):
        shutil.copy2(scripts / name, folder / name)
    shutil.copy2(scripts.parent / "pyvenv.cfg", folder / "pyvenv.cfg")


def install(tmp_path: Path) -> Path:
    root = tmp_path / "Mirabel Voice"
    root.mkdir()
    shutil.copy2(LAUNCH, root / "Launch.ps1")
    (root / "launcher.py").write_text(STUB_LAUNCHER)
    return root


def check(root: Path, prefixed: bool, env=None) -> subprocess.CompletedProcess:
    script = str(root / "Launch.ps1")
    if prefixed:
        # How the Start with Windows entry reached a real machine.
        script = "\\\\?\\" + script
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-CheckOnly"],
        capture_output=True, text=True, timeout=120, env=env,
    )


def assert_checked(root: Path, result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "checked").read_text() == "--self-test"


@pytest.fixture(params=[False, True], ids=["plain", "long-path"])
def prefixed(request):
    return request.param


def test_a_healthy_install_starts(tmp_path, prefixed):
    root = install(tmp_path)
    stub_runtime(root / "python")
    assert_checked(root, check(root, prefixed))


def test_an_interrupted_update_restores_the_previous_runtime(tmp_path, prefixed):
    root = install(tmp_path)
    stub_runtime(root / "python.previous")
    (root / "python").mkdir()
    (root / "python" / "half-copied").write_text("")
    (root / ".install-pending").write_text("")
    assert_checked(root, check(root, prefixed))
    assert (root / "python" / "python.exe").exists()
    assert not (root / "python" / "half-copied").exists()
    assert not (root / "python.previous").exists()
    assert not (root / ".install-pending").exists()


def test_an_interrupted_first_install_is_kept_once_it_passes(tmp_path, prefixed):
    root = install(tmp_path)
    stub_runtime(root / "python")
    (root / ".install-pending").write_text("")
    package = tmp_path / "packages" / "mirabel_voice"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text("")
    env = dict(os.environ, PYTHONPATH=str(package.parent))
    assert_checked(root, check(root, prefixed, env))
    assert not (root / ".install-pending").exists()


def test_a_missing_runtime_comes_back_from_the_backup(tmp_path, prefixed):
    root = install(tmp_path)
    stub_runtime(root / "python.previous")
    assert_checked(root, check(root, prefixed))
    assert (root / "python" / "python.exe").exists()
    assert not (root / "python.previous").exists()
