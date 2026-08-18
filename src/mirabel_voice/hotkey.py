"""Global hotkey detection.

The listener works in every program, not only in a Mirabel Voice window.

Hotkey names use the pynput names. Examples:

* "ctrl+win" - the Ctrl and Windows keys together (the default)
* "ctrl_r" - the right Ctrl key
* "f9" - a function key
* "ctrl+alt+space" - a combination. Every key must be down at the same time.

The names "win", "windows", and "super" all mean the Windows key.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger(__name__)

MODE_HOLD = "hold"
MODE_TOGGLE = "toggle"

# pynput names the Windows key "cmd". Accept the names people expect.
KEY_ALIASES = {"win": "cmd", "windows": "cmd", "super": "cmd"}

# A second press within this window after a release locks hands-free mode.
DOUBLE_TAP_SECONDS = 0.5


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
        self.keys = parse_hotkey(hotkey)
        self.mode = mode if mode in (MODE_HOLD, MODE_TOGGLE) else MODE_HOLD
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.on_lock = on_lock
        self._clock = clock or time.monotonic
        self._down: set = set()
        self._active = False
        self._locked = False
        self._last_release = float("-inf")
        self._listener = None

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
        if self._listener is not None:
            try:
                return self._listener.canonical(key)
            except Exception:  # noqa: BLE001 - some keys have no canonical form
                return key
        return key

    def handle_press(self, key) -> None:  # noqa: ANN001
        """Process one key-down event."""
        resolved = self._canonical(key)
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
        resolved = self._canonical(key)
        if resolved not in self.keys:
            return
        was_complete = self._down >= set(self.keys)
        self._down.discard(resolved)
        if self.mode != MODE_HOLD or not was_complete or not self._active:
            return
        if self._locked:
            return  # The double-tap holds the recording open.
        self._active = False
        self._last_release = self._clock()
        self._safe(self.on_stop)

    def _engage(self) -> None:
        """Start, stop a locked recording, or in toggle mode switch."""
        if self.mode == MODE_TOGGLE:
            if self._active:
                self._active = False
                self._safe(self.on_stop)
            else:
                self._active = True
                self._safe(self.on_start)
            return
        if self._locked and self._active:
            self._locked = False
            self._active = False
            self._safe(self.on_stop)
            return
        if not self._active:
            if self._clock() - self._last_release <= DOUBLE_TAP_SECONDS:
                self._locked = True
            self._active = True
            self._safe(self.on_start)
            if self._locked and self.on_lock is not None:
                self._safe(self.on_lock)

    def _handle_other_key(self, key) -> None:  # noqa: ANN001
        """Cancel an active recording when the user presses Esc."""
        from pynput.keyboard import Key

        if key is Key.esc and self._active and self.on_cancel is not None:
            self._active = False
            self._locked = False
            self._down.clear()
            self._safe(self.on_cancel)

    @staticmethod
    def _safe(callback: Callable[[], None]) -> None:
        """Run a callback and log any error, so the listener stays alive."""
        try:
            callback()
        except Exception:  # noqa: BLE001
            log.exception("A hotkey action failed.")

    def start(self) -> None:
        """Begin to watch the keyboard."""
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=self.handle_press,
            on_release=self.handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop watching the keyboard."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        """Block until the listener stops."""
        if self._listener is not None:
            self._listener.join()
