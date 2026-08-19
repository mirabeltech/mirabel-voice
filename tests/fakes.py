"""Stand-in objects for the network and the keyboard."""

from __future__ import annotations

from types import SimpleNamespace


class FakeTranscriptionsAPI:
    def __init__(self, text="um so this is a test", error=None):
        self.text = text
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.text


class FakeOpenAI:
    def __init__(self, text="um so this is a test", error=None):
        self.transcriptions = FakeTranscriptionsAPI(text, error)
        self.audio = SimpleNamespace(transcriptions=self.transcriptions)


def text_response(text, stop_reason="end_turn"):
    """Build an object shaped like an Anthropic response."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
    )


class FakeMessagesAPI:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeAnthropic:
    def __init__(self, response=None, error=None):
        self.messages = FakeMessagesAPI(response, error)
        self.options = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


class FakeClipboard:
    def __init__(self, content=""):
        self.content = content
        self.history = []

    def copy(self, text):
        self.content = text
        self.history.append(text)

    def paste(self):
        return self.content


class FakeKeyboard:
    """Records keystrokes and keeps a model of the resulting text field.

    The model understands backspace and Ctrl+V, so tests can assert on
    what the user would actually end up seeing.
    """

    def __init__(self, existing="", clipboard=None):
        self.events = []
        self.field = existing
        self.clipboard = clipboard
        self._ctrl_down = False

    def press(self, key):
        self.events.append(("press", key))
        name = getattr(key, "name", key)
        if name == "backspace":
            self.field = self.field[:-1]
        elif name == "ctrl":
            self._ctrl_down = True
        elif key == "v" and self._ctrl_down and self.clipboard is not None:
            self.field += self.clipboard.paste()

    def release(self, key):
        self.events.append(("release", key))
        if getattr(key, "name", key) == "ctrl":
            self._ctrl_down = False

    def type(self, text):
        self.events.append(("type", text))
        self.field += text

    def tap(self, key):
        self.press(key)
        self.release(key)
