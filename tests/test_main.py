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
