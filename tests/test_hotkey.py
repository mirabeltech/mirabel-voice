import pytest
from pynput.keyboard import Key, KeyCode

from mirabel_voice.hotkey import HotkeyListener, UnknownHotkeyError, parse_hotkey


def test_parse_win_aliases_to_the_windows_key():
    assert parse_hotkey("ctrl+win") == frozenset({Key.ctrl, Key.cmd})


def test_parse_windows_and_super_alias_too():
    assert parse_hotkey("windows") == frozenset({Key.cmd})
    assert parse_hotkey("super") == frozenset({Key.cmd})


def test_parse_single_named_key():
    assert parse_hotkey("f9") == frozenset({Key.f9})


def test_parse_single_character():
    assert parse_hotkey("ctrl+j") == frozenset({Key.ctrl, KeyCode.from_char("j")})


def test_parse_rejects_unknown_names():
    with pytest.raises(UnknownHotkeyError):
        parse_hotkey("ctrl+banana")


def test_parse_rejects_an_empty_spec():
    with pytest.raises(UnknownHotkeyError):
        parse_hotkey("  ")


class Events:
    """Collect the callbacks the listener fires."""

    def __init__(self):
        self.log = []

    def start(self):
        self.log.append("start")

    def stop(self):
        self.log.append("stop")

    def cancel(self):
        self.log.append("cancel")


def make_listener(mode="hold", hotkey="ctrl+win"):
    events = Events()
    listener = HotkeyListener(
        hotkey=hotkey,
        mode=mode,
        on_start=events.start,
        on_stop=events.stop,
        on_cancel=events.cancel,
    )
    return listener, events


def test_hold_mode_starts_when_all_keys_are_down_and_stops_on_release():
    listener, events = make_listener()
    listener.handle_press(Key.ctrl)
    assert events.log == []
    listener.handle_press(Key.cmd)
    assert events.log == ["start"]
    listener.handle_release(Key.cmd)
    assert events.log == ["start", "stop"]


def test_os_key_repeats_do_not_restart_the_recording():
    listener, events = make_listener()
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    listener.handle_press(Key.cmd)
    listener.handle_press(Key.ctrl)
    assert events.log == ["start"]


def test_unrelated_keys_change_nothing():
    listener, events = make_listener()
    listener.handle_press(Key.ctrl)
    listener.handle_press(KeyCode.from_char("c"))
    assert events.log == []


def test_escape_cancels_an_active_recording():
    listener, events = make_listener()
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    listener.handle_press(Key.esc)
    assert events.log == ["start", "cancel"]
    assert listener.is_active is False


def test_toggle_mode_switches_on_each_full_press():
    listener, events = make_listener(mode="toggle")
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    listener.handle_release(Key.cmd)
    listener.handle_release(Key.ctrl)
    assert events.log == ["start"]
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    assert events.log == ["start", "stop"]
