import numpy as np
import pytest

from fakes import FakeOpenAI
from mirabel_voice.audio import Recording
from mirabel_voice.transcribe import TranscriptionError, Transcriber


def a_recording():
    return Recording(samples=np.ones(16000, dtype=np.int16) * 1000, sample_rate=16000)


def test_transcribe_returns_the_trimmed_text():
    client = FakeOpenAI(text="  hello world  \n")
    assert Transcriber(client=client).transcribe(a_recording()) == "hello world"


def test_request_carries_the_model_and_the_language():
    client = FakeOpenAI()
    Transcriber(model="whisper-1", language="en", client=client).transcribe(a_recording())
    call = client.transcriptions.calls[0]
    assert call["model"] == "whisper-1"
    assert call["language"] == "en"
    # The audio goes up as Opus, which is about a ninth of the WAV size.
    assert call["file"][0] == "speech.ogg"
    assert call["file"][1][:4] == b"OggS"
    assert call["file"][2] == "audio/ogg"


def test_no_language_key_when_the_language_is_unset():
    client = FakeOpenAI()
    Transcriber(language=None, client=client).transcribe(a_recording())
    assert "language" not in client.transcriptions.calls[0]


def test_custom_words_become_a_spelling_prompt():
    client = FakeOpenAI()
    Transcriber(custom_words=["Mirabel", "Kubernetes"], client=client).transcribe(
        a_recording()
    )
    prompt = client.transcriptions.calls[0]["prompt"]
    assert "Mirabel" in prompt and "Kubernetes" in prompt


def test_a_pinned_language_goes_into_the_prompt():
    # The gpt-4o transcription models take the language parameter as a
    # hint only, so the pin must also arrive as words in the prompt.
    client = FakeOpenAI()
    Transcriber(language="te", client=client).transcribe(a_recording())
    prompt = client.transcriptions.calls[0]["prompt"]
    assert "Telugu" in prompt


def test_the_prompt_carries_the_language_and_the_spellings_together():
    client = FakeOpenAI()
    Transcriber(
        language="hi", custom_words=["Mirabel"], client=client
    ).transcribe(a_recording())
    prompt = client.transcriptions.calls[0]["prompt"]
    assert "Hindi" in prompt and "Mirabel" in prompt


def test_no_prompt_key_without_a_language_or_custom_words():
    client = FakeOpenAI()
    Transcriber(language=None, client=client).transcribe(a_recording())
    assert "prompt" not in client.transcriptions.calls[0]


def test_an_api_failure_raises_a_transcription_error():
    client = FakeOpenAI(error=RuntimeError("network is down"))
    with pytest.raises(TranscriptionError, match="network is down"):
        Transcriber(client=client).transcribe(a_recording())


def test_the_reply_shape_is_json_so_the_relay_can_read_usage():
    """The json reply carries the usage block. The relay prices
    dictations from it, so the text shape must never come back."""
    client = FakeOpenAI()
    Transcriber(client=client).transcribe(a_recording())
    assert client.transcriptions.calls[0]["response_format"] == "json"


def test_a_plain_string_reply_still_works():
    """The relay or a provider may answer with the bare text shape.
    The transcriber must accept both, so no reply is ever dropped."""

    class BareTextAPI(FakeOpenAI):
        def __init__(self):
            super().__init__()
            self.transcriptions.create = lambda **kwargs: "  plain text  "

    assert Transcriber(client=BareTextAPI()).transcribe(a_recording()) == "plain text"
