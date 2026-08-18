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


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def make_locking_listener():
    events = Events()
    clock = FakeClock()
    listener = HotkeyListener(
        hotkey="ctrl+win",
        mode="hold",
        on_start=events.start,
        on_stop=events.stop,
        on_cancel=events.cancel,
        clock=clock,
    )
    return listener, events, clock


def tap(listener, clock, duration=0.1):
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    clock.tick(duration)
    listener.handle_release(Key.cmd)
    listener.handle_release(Key.ctrl)


def test_double_tap_locks_recording_open_until_the_next_press():
    listener, events, clock = make_locking_listener()
    tap(listener, clock)          # tap 1: normal short start/stop
    clock.tick(0.2)
    tap(listener, clock)          # tap 2: locks - release must not stop
    assert events.log == ["start", "stop", "start"]
    assert listener.is_locked is True
    clock.tick(5.0)               # speak for a while, hands free
    listener.handle_press(Key.ctrl)
    listener.handle_press(Key.cmd)
    assert events.log == ["start", "stop", "start", "stop"]
    assert listener.is_locked is False


def test_a_slow_second_tap_does_not_lock():
    listener, events, clock = make_locking_listener()
    tap(listener, clock)
    clock.tick(2.0)               # too slow to count as a double-tap
    tap(listener, clock)
    assert events.log == ["start", "stop", "start", "stop"]
    assert listener.is_locked is False


def test_escape_cancels_and_unlocks_a_locked_recording():
    listener, events, clock = make_locking_listener()
    tap(listener, clock)
    clock.tick(0.2)
    tap(listener, clock)
    assert listener.is_locked is True
    listener.handle_press(Key.esc)
    assert events.log == ["start", "stop", "start", "cancel"]
    assert listener.is_locked is False
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
