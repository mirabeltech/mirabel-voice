"""Quit deadlines and the real Windows single-instance handoff."""
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from mirabel_voice.shutdown import ShutdownDeadline, SHUTDOWN_TIMEOUT


def test_completed_cleanup_does_not_force_exit(tmp_path):
    exits = []
    guard = ShutdownDeadline(tmp_path, timeout=0.01, exit_process=exits.append)
    guard.finish()
    guard.arm()
    guard.arm()
    guard._watch()
    assert not exits
    assert not (tmp_path / 'shutdown-timeout.log').exists()


def test_stuck_cleanup_records_stacks_and_exits_once(tmp_path):
    exited = threading.Event()
    codes = []
    def stop(code):
        codes.append(code)
        exited.set()
    guard = ShutdownDeadline(tmp_path, timeout=0.01, exit_process=stop)
    guard.arm()
    guard.arm()
    assert exited.wait(2)
    assert codes == [0]
    assert 'exceeded its deadline' in (tmp_path / 'shutdown-timeout.log').read_text()
    assert SHUTDOWN_TIMEOUT < 20


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows process mutex')
def test_stuck_quit_releases_mutex_for_waiting_update(tmp_path):
    script = tmp_path / 'handoff.py'
    source = Path(__file__).resolve().parents[1] / 'src'
    script.write_text('''
import sys, threading, subprocess, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from mirabel_voice.__main__ import already_running, _wait_for_exit
from mirabel_voice.shutdown import ShutdownDeadline
from mirabel_voice.tray import Tray
folder = Path(__file__).parent
name = "Local\\\\MirabelShutdownTest-" + folder.name
if len(sys.argv) > 2:
    (folder / 'child-ready').touch()
    assert _wait_for_exit(lambda: already_running(name), seconds=4)
    (folder / 'restarted').touch()
else:
    assert not already_running(name)
    child = subprocess.Popen([sys.executable, __file__, sys.argv[1], 'child'])
    deadline = time.monotonic() + 3
    while not (folder / 'child-ready').exists():
        assert time.monotonic() < deadline
        time.sleep(.01)
    # Both update and Quit use Tray.stop. Simulate a cleanup lock that
    # never returns, after the update's replacement has started waiting.
    guard = ShutdownDeadline(folder, timeout=.2)
    tray = object.__new__(Tray)
    tray.before_stop = guard.arm
    tray.app = SimpleNamespace(stop=lambda: threading.Event().wait())
    tray.icon = None
    tray.stop()
''')
    subprocess.run([sys.executable, str(script), str(source)], timeout=6, check=True)
    import time
    end = time.monotonic() + 5
    while not (tmp_path / 'restarted').exists() and time.monotonic() < end:
        time.sleep(.02)
    assert (tmp_path / 'restarted').exists()
    assert 'tray.py' in (tmp_path / 'shutdown-timeout.log').read_text()
