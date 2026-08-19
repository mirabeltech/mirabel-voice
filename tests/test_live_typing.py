from fakes import FakeClipboard, FakeKeyboard
from mirabel_voice.inject import LiveTyper, TextInjector


def make_typer(existing=""):
    clipboard = FakeClipboard()
    keyboard = FakeKeyboard(existing, clipboard=clipboard)
    typer = LiveTyper(
        TextInjector(keyboard=keyboard, clipboard=clipboard),
        use_unicode=False,
    )
    return typer, keyboard


def test_words_appear_as_they_arrive():
    typer, keyboard = make_typer()
    typer.show("Hello")
    typer.show("Hello there")
    assert keyboard.field == "Hello there"
    assert typer.typed == "Hello there"


def test_only_the_new_words_are_typed():
    typer, keyboard = make_typer()
    typer.show("Hello")
    keyboard.events.clear()
    typer.show("Hello there")
    assert keyboard.events == [("type", " there")]


def test_a_revision_is_left_for_the_final_correction():
    """No deleting while the hotkey is held: a delete key plus the held
    modifier would eat a whole word."""
    typer, keyboard = make_typer()
    typer.show("I met Anne")
    typer.show("I met Ann Marie")
    assert keyboard.field == "I met Anne"  # untouched, no backspaces
    assert not any(e[0] == "press" for e in keyboard.events)
    typer.replace_with("I met Ann Marie.")
    assert keyboard.field == "I met Ann Marie."


def test_a_revision_applies_when_deleting_is_allowed():
    typer, keyboard = make_typer()
    typer.show("I met Anne")
    typer.show("I met Ann Marie", allow_delete=True)
    assert keyboard.field == "I met Ann Marie"


def test_typing_never_touches_text_that_was_already_there():
    typer, keyboard = make_typer(existing="Dear Priya, ")
    typer.show("thanks")
    typer.show("thanks a lot")
    assert keyboard.field == "Dear Priya, thanks a lot"


def test_replace_swaps_the_typed_words_for_the_clean_ones():
    typer, keyboard = make_typer(existing="Note: ")
    typer.show("um hello world")
    typer.replace_with("Hello world.")
    assert keyboard.field == "Note: Hello world."
    assert typer.typed == ""


def test_replace_without_any_typed_words_pastes_normally():
    typer, keyboard = make_typer()
    typer.replace_with("Hello world.")
    assert keyboard.field == "Hello world."


def test_clear_removes_only_what_was_typed():
    typer, keyboard = make_typer(existing="keep this")
    typer.show("spoken words")
    typer.clear()
    assert keyboard.field == "keep this"
    assert typer.typed == ""


def test_identical_clean_text_changes_nothing_on_screen():
    """The cleanup often returns exactly what was typed. Deleting and
    retyping it would make the text flicker for no reason."""
    typer, keyboard = make_typer(existing="Note: ")
    typer.show("Hello world.")
    keyboard.events.clear()
    typer.replace_with("Hello world.")
    assert keyboard.events == []
    assert keyboard.field == "Note: Hello world."


def test_only_the_changed_tail_is_rewritten():
    typer, keyboard = make_typer()
    typer.show("send it on tuesday")
    keyboard.events.clear()
    typer.replace_with("send it on Wednesday.")
    assert keyboard.field == "send it on Wednesday."
    # "send it on " is shared, so only the tail is deleted and retyped.
    backspaces = sum(1 for e in keyboard.events if e[0] == "press")
    assert backspaces == len("tuesday")


def test_late_live_words_cannot_land_after_the_finished_text():
    """The socket thread can still deliver a word while the worker thread
    is putting the finished text in place. A late word would appear after
    it and read as a stutter."""
    typer, keyboard = make_typer()
    typer.show("shall we open a ne")
    typer.replace_with("Shall we open a new tab.")
    typer.show("shall we open a new tab")   # arrives too late
    assert keyboard.field == "Shall we open a new tab."


def test_the_next_dictation_starts_clean():
    typer, keyboard = make_typer()
    typer.show("first")
    typer.replace_with("First.")
    typer.reopen()
    typer.show("second")
    assert keyboard.field == "First.second"
