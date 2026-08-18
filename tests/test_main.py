import uuid

from mirabel_voice import __main__ as entry


def test_the_second_instance_check_detects_the_first():
    # A unique name keeps this test independent of a really running app.
    name = f"Local\\MirabelVoiceTest-{uuid.uuid4()}"
    assert entry.already_running(name) is False
    # The mutex from the first call is still held by this process, so a
    # second acquisition must report that the app is already running.
    assert entry.already_running(name) is True
