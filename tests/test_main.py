import uuid

from mirabel_voice import __main__ as entry


def test_the_second_instance_check_detects_the_first():
    # A unique name keeps this test independent of a really running app.
    name = f"Local\\MirabelVoiceTest-{uuid.uuid4()}"
    assert entry.already_running(name) is False
    # The mutex from the first call is still held by this process, so a
    # second acquisition must report that the app is already running.
    assert entry.already_running(name) is True


def _hold_mutex(name):
    """Create the mutex the way another running copy would."""
    import ctypes

    return ctypes.windll.kernel32.CreateMutexW(None, False, name)


def _release_mutex(handle):
    import ctypes

    ctypes.windll.kernel32.CloseHandle(handle)


def test_the_check_clears_once_the_holder_exits():
    # The v0.5.1 -> v0.6.0 update lost the tray icon to this: the check
    # kept its own handle to the mutex it found, so the mutex it was
    # waiting on could never disappear, and the relaunched copy gave up.
    name = f"Local\\MirabelVoiceTest-{uuid.uuid4()}"
    holder = _hold_mutex(name)
    assert entry.already_running(name) is True
    _release_mutex(holder)
    assert entry.already_running(name) is False


def test_a_relaunch_survives_a_slowly_leaving_predecessor():
    # The field sequence: the old copy is still shutting down when the
    # updated copy first checks, and releases the mutex a moment later.
    name = f"Local\\MirabelVoiceTest-{uuid.uuid4()}"
    holder = _hold_mutex(name)
    assert entry.already_running(name) is True

    released = []

    def sleep(_seconds):
        if holder not in released:
            released.append(holder)
            _release_mutex(holder)

    assert entry._wait_for_exit(
        lambda: entry.already_running(name), seconds=5.0, sleep=sleep
    ) is True


def _install_crash_report(monkeypatch):
    """Install the hooks for one test; monkeypatch puts the old ones back."""
    import sys
    import threading

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    boxes = []
    monkeypatch.setattr(entry, "_show_box", lambda message, icon: boxes.append(message))
    entry._report_crashes()
    return boxes


def test_a_startup_crash_reaches_the_log_and_a_box(monkeypatch, caplog):
    # Under pythonw a crash in main() left no icon, no box and no log
    # line, so a work computer that never showed the icon gave no clue.
    import sys

    boxes = _install_crash_report(monkeypatch)
    try:
        raise RuntimeError("the tray would not start")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())

    assert "the tray would not start" in caplog.text
    assert "Traceback" in caplog.text
    assert len(boxes) == 1 and "RuntimeError: the tray would not start" in boxes[0]


def test_a_background_crash_is_logged_without_a_box(monkeypatch, caplog):
    import threading

    boxes = _install_crash_report(monkeypatch)

    def fail():
        raise ValueError("the update check broke")

    worker = threading.Thread(target=fail, name="mirabel-test-worker")
    worker.start()
    worker.join()

    assert "mirabel-test-worker" in caplog.text
    assert "the update check broke" in caplog.text
    assert boxes == []
