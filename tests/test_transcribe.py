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
    assert call["file"][0] == "speech.wav"
    assert call["file"][1][:4] == b"RIFF"


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


def test_no_prompt_key_without_custom_words():
    client = FakeOpenAI()
    Transcriber(client=client).transcribe(a_recording())
    assert "prompt" not in client.transcriptions.calls[0]


def test_an_api_failure_raises_a_transcription_error():
    client = FakeOpenAI(error=RuntimeError("network is down"))
    with pytest.raises(TranscriptionError, match="network is down"):
        Transcriber(client=client).transcribe(a_recording())
