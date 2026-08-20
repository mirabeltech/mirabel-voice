"""Global hotkey detection.

The listener works in every program, not only in a Mirabel Voice window.

Hotkey names use the pynput names. Examples:

* "insert" - the Insert key (the default)
* "scroll_lock", "pause" - other keys that are usually free
* "ctrl_r" - the right Ctrl key
* "ctrl+alt+space" - a combination. Every key must be down at the same time.

The names "win", "windows", and "super" all mean the Windows key.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

MODE_HOLD = "hold"
MODE_TOGGLE = "toggle"

# pynput names the Windows key "cmd". Accept the names people expect.
KEY_ALIASES = {"win": "cmd", "windows": "cmd", "super": "cmd"}

# A press counts as a tap when it is shorter than this.
TAP_SECONDS = 0.35

# A press within this window after a TAP locks hands-free mode. A press
# after a long hold never locks: that is the next dictation starting.
DOUBLE_TAP_SECONDS = 0.5

# How often the watchdog compares the remembered keys with the keyboard.
WATCHDOG_SECONDS = 0.25


class UnknownHotkeyError(ValueError):
    """The settings file names a key that pynput does not know."""


def parse_hotkey(spec: str):  # noqa: ANN201 - returns a frozenset of pynput keys
    """Turn a hotkey string into the set of keys that must be down.

    Raises:
        UnknownHotkeyError: A part of the string is not a known key.
    """
    from pynput.keyboard import Key, KeyCode

    keys = set()
    for part in spec.lower().split("+"):
        name = part.strip()
        if not name:
            continue
        name = KEY_ALIASES.get(name, name)
        if hasattr(Key, name):
            keys.add(getattr(Key, name))
        elif len(name) == 1:
            keys.add(KeyCode.from_char(name))
        else:
            raise UnknownHotkeyError(
                f"'{name}' is not a key name. Use a name such as ctrl_r, "
                f"alt_r, f9, or a single character."
            )
    if not keys:
        raise UnknownHotkeyError("The hotkey is empty.")
    return frozenset(keys)


def key_id(key):  # noqa: ANN001, ANN201
    """Return one comparable value for a key.

    Two shapes of the same key reach us. The settings give a named key
    such as Key.insert, while the keyboard listener gives a key code that
    also carries the scan code of the physical key. pynput compares scan
    codes, so those two never match, and a hotkey built from the settings
    would never fire. Comparing the plain character or key number instead
    makes both shapes agree.
    """
    from pynput.keyboard import Key, KeyCode

    if isinstance(key, Key):
        key = key.value
    if isinstance(key, KeyCode):
        if key.char:
            return ("char", key.char.lower())
        return ("vk", key.vk)
    return key


def esc_id():  # noqa: ANN201
    """Return the comparable form of the Esc key."""
    from pynput.keyboard import Key

    return key_id(Key.esc)


def key_is_down(resolved):  # noqa: ANN001, ANN201
    """Ask the keyboard whether the key is physically held right now.

    Returns True or False from Windows itself, or None when there is no
    answer (not Windows, or a form of key it cannot look up).

    The listener remembers which keys are down, but a busy machine can
    lose a key-up event. The remembered key then makes the next press
    look like key repeat, and that press dies without a sound. This is
    the ground truth that lets the watchdog repair the memory.
    """
    try:
        import ctypes

        kind, value = resolved
        if kind == "vk":
            code = value
        elif kind == "char":
            scan = ctypes.windll.user32.VkKeyScanW(ord(value))
            if scan == -1:
                return None
            code = scan & 0xFF
        else:
            return None
        return bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)
    except Exception:  # noqa: BLE001 - not Windows, or an unknown key shape
        return None


class HotkeyListener:
    """Call on_start and on_stop when the user works the hotkey.

    In "hold" mode the listener calls on_start when every hotkey key goes
    down, and on_stop when one of them comes up. A quick double-tap locks
    the recording open; the next press stops it. In "toggle" mode each full
    press switches between the two.
    """

    def __init__(
        self,
        hotkey: str,
        mode: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None] | None = None,
        on_lock: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.spec = hotkey
        self.keys = frozenset(key_id(k) for k in parse_hotkey(hotkey))
        self.mode = mode if mode in (MODE_HOLD, MODE_TOGGLE) else MODE_HOLD
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.on_lock = on_lock
        self._clock = clock or time.monotonic
        self._down: set = set()
        self._active = False
        self._locked = False
        self._engaged_at = float("-inf")
        self._last_tap_release = float("-inf")
        self._bindings: list[dict] = []
        self._pressed: set = set()
        self._listener = None
        # The hook thread and the watchdog both touch the key memory.
        self._memory_lock = threading.Lock()
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None

    def add_binding(self, spec: str, callback: Callable[[], None]) -> None:
        """Watch an extra key combination and call the callback on it.

        The spec uses the same grammar as the main hotkey ("shift+alt+z").

        Raises:
            UnknownHotkeyError: A part of the spec is not a known key.
        """
        self._bindings.append(
            {
                "keys": frozenset(key_id(k) for k in parse_hotkey(spec)),
                "callback": callback,
                "latched": False,
            }
        )

    @property
    def is_active(self) -> bool:
        """Return True while the listener treats the hotkey as engaged."""
        return self._active

    @property
    def is_locked(self) -> bool:
        """Return True while a double-tap holds the recording open."""
        return self._locked

    def _canonical(self, key):  # noqa: ANN001, ANN202
        """Return the key in the form that matches the parsed hotkey."""
        resolved = key
        if self._listener is not None:
            try:
                resolved = self._listener.canonical(key)
            except Exception:  # noqa: BLE001 - some keys have no canonical form
                resolved = key
        return key_id(resolved)

    def handle_press(self, key) -> None:  # noqa: ANN001
        """Process one key-down event."""
        with self._memory_lock:
            self._press_resolved(self._canonical(key))

    def _press_resolved(self, resolved) -> None:  # noqa: ANN001
        """Apply one key-down, given in comparable form. Hold the lock."""
        if resolved not in self._pressed:
            self._pressed.add(resolved)
            self._fire_bindings()
        if resolved not in self.keys:
            self._handle_other_key(resolved)
            return
        if resolved in self._down:
            return  # Windows repeats a held key. Ignore the repeats.
        self._down.add(resolved)
        if self._down >= set(self.keys):
            self._engage()

    def handle_release(self, key) -> None:  # noqa: ANN001
        """Process one key-up event."""
        with self._memory_lock:
            self._release_resolved(self._canonical(key))

    def _release_resolved(self, resolved) -> None:  # noqa: ANN001
        """Apply one key-up, given in comparable form. Hold the lock."""
        self._pressed.discard(resolved)
        for binding in self._bindings:
            if resolved in binding["keys"]:
                binding["latched"] = False
        if resolved not in self.keys:
            return
        was_complete = self._down >= set(self.keys)
        self._down.discard(resolved)
        if self.mode != MODE_HOLD or not was_complete or not self._active:
            return
        if self._locked:
            return  # The double-tap holds the recording open.
        self._active = False
        if self._clock() - self._engaged_at <= TAP_SECONDS:
            self._last_tap_release = self._clock()
        self._safe(self.on_stop)

    def _fire_bindings(self) -> None:
        """Run the callback of every extra combination that is now down."""
        for binding in self._bindings:
            if binding["latched"] or not binding["keys"] <= self._pressed:
                continue
            binding["latched"] = True
            self._safe(binding["callback"])

    def _engage(self) -> None:
        """Start, stop a locked recording, or in toggle mode switch."""
        if self.mode == MODE_TOGGLE:
            if self._active:
                self._active = False
                self._safe(self.on_stop)
            else:
                started = self._safe(self.on_start)
                if started is False:
                    return  # The app refused (busy or microphone error).
                self._active = True
            return
        if self._locked:
            self._locked = False
            self._active = False
            self._safe(self.on_stop)
            return
        if not self._active:
            wants_lock = (
                self._clock() - self._last_tap_release <= DOUBLE_TAP_SECONDS
            )
            started = self._safe(self.on_start)
            if started is False:
                return  # The app refused (busy or microphone error).
            self._active = True
            self._engaged_at = self._clock()
            if wants_lock:
                self._locked = True
                if self.on_lock is not None:
                    self._safe(self.on_lock)

    def _handle_other_key(self, key) -> None:  # noqa: ANN001
        """Cancel an active recording when the user presses Esc."""
        if key == esc_id() and self._active and self.on_cancel is not None:
            self._active = False
            self._locked = False
            self._down.clear()
            self._safe(self.on_cancel)

    @staticmethod
    def _safe(callback: Callable[[], None]):  # noqa: ANN205
        """Run a callback and log any error, so the listener stays alive.

        Returns the callback result, or None when the callback raised.
        """
        try:
            return callback()
        except Exception:  # noqa: BLE001
            log.exception("A hotkey action failed.")
            return None

    def _sweep(self) -> None:
        """Release every remembered key that the keyboard says is up.

        Windows can lose a key-up event on a busy machine. The key then
        stays in the memory, the next press of it looks like key repeat,
        and that press is dropped before it can start or stop anything.
        One lost release costs the user one dead press. Asking the
        keyboard for the truth repairs the memory within a moment, and a
        key that is genuinely held is left exactly as it is.
        """
        for resolved in list(self._down | self._pressed):
            if key_is_down(resolved) is False:
                with self._memory_lock:
                    if resolved not in self._down and resolved not in self._pressed:
                        continue  # its release arrived while we asked
                    log.info("A lost key release was repaired: %s.", resolved)
                    self._release_resolved(resolved)

    def _watch(self) -> None:
        """Run _sweep a few times a second until stop() is called."""
        while not self._watch_stop.wait(WATCHDOG_SECONDS):
            self._sweep()

    def start(self) -> None:
        """Begin to watch the keyboard."""
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=self.handle_press,
            on_release=self.handle_release,
        )
        self._listener.start()
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(
            target=self._watch, name="mirabel-voice-key-watchdog", daemon=True
        )
        self._watch_thread.start()

    def stop(self) -> None:
        """Stop watching the keyboard."""
        self._watch_stop.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=1.0)
            self._watch_thread = None
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        """Block until the listener stops."""
        if self._listener is not None:
            self._listener.join()
