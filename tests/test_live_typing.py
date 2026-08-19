from fakes import FakeClipboard, FakeKeyboard
from mirabel_voice.inject import LiveTyper, TextInjector


def make_typer(existing=""):
    clipboard = FakeClipboard()
    keyboard = FakeKeyboard(existing, clipboard=clipboard)
    typer = LiveTyper(
        TextInjector(keyboard=keyboard, clipboard=clipboard)
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


def test_a_revised_word_replaces_only_the_changed_tail():
    typer, keyboard = make_typer()
    typer.show("I met Anne")
    typer.show("I met Ann Marie")
    assert keyboard.field == "I met Ann Marie"


def test_typing_never_touches_text_that_was_already_there():
    typer, keyboard = make_typer(existing="Dear Priya, ")
    typer.show("thanks")
    typer.show("thank you")
    assert keyboard.field == "Dear Priya, thank you"


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
