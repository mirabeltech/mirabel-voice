from mirabel_voice import __main__ as entry


def test_the_second_instance_check_detects_the_first():
    assert entry.already_running() is False
    # The mutex from the first call is still held by this process, so a
    # second acquisition must report that the app is already running.
    assert entry.already_running() is True
