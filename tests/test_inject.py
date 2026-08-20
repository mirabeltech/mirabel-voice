"""Tests for the paste path of TextInjector.

The live-typing behavior has its own file, test_live_typing.py.
"""

import mirabel_voice.inject as inject
from fakes import FakeClipboard, FakeKeyboard
from mirabel_voice.inject import TextInjector


def make_injector(monkeypatch, sequences=None, previous="old content"):
    """Build an injector over fakes, with the waits removed.

    sequences feeds the clipboard-change counter one value per call.
    None (the default) stands for a machine without the counter.
    """
    monkeypatch.setattr(inject, "PASTE_SETTLE_SECONDS", 0)
    monkeypatch.setattr(inject, "CLIPBOARD_RESTORE_SECONDS", 0)
    clipboard = FakeClipboard(content=previous)
    keyboard = FakeKeyboard(clipboard=clipboard)
    values = list(sequences) if sequences is not None else [None]

    def next_sequence():
        return values.pop(0) if len(values) > 1 else values[0]

    injector = TextInjector(
        keyboard=keyboard, clipboard=clipboard, sequence=next_sequence
    )
    return injector, keyboard, clipboard


def test_a_paste_delivers_the_text_and_restores_the_clipboard(monkeypatch):
    injector, keyboard, clipboard = make_injector(monkeypatch, sequences=[5, 5])
    injector.send("Hello world.")
    assert keyboard.field == "Hello world."
    assert clipboard.content == "old content"


def test_a_clipboard_taken_by_another_program_is_not_overwritten(monkeypatch):
    """A copy made during the wait must survive. Putting the old content
    back would silently destroy what the user just copied."""
    injector, keyboard, clipboard = make_injector(monkeypatch, sequences=[5, 9])
    injector.send("Hello world.")
    assert keyboard.field == "Hello world."
    assert clipboard.content != "old content"


def test_a_missing_change_counter_still_restores(monkeypatch):
    """Off Windows there is no counter. The restore must then behave as
    it always did."""
    injector, keyboard, clipboard = make_injector(monkeypatch, sequences=None)
    injector.send("Hello world.")
    assert keyboard.field == "Hello world."
    assert clipboard.content == "old content"


def test_restore_off_leaves_the_text_on_the_clipboard(monkeypatch):
    monkeypatch.setattr(inject, "PASTE_SETTLE_SECONDS", 0)
    monkeypatch.setattr(inject, "CLIPBOARD_RESTORE_SECONDS", 0)
    clipboard = FakeClipboard(content="old content")
    keyboard = FakeKeyboard(clipboard=clipboard)
    injector = TextInjector(
        keyboard=keyboard, clipboard=clipboard, restore_clipboard=False
    )
    injector.send("Hello world.")
    assert keyboard.field == "Hello world."
    assert clipboard.content == "Hello world."
