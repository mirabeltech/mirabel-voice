"""Speech to text with the OpenAI Whisper API."""

from __future__ import annotations

from .audio import Recording


class TranscriptionError(RuntimeError):
    """The speech-to-text step failed."""


class Transcriber:
    """Send audio to the Whisper API and return the words."""

    def __init__(
        self,
        model: str = "whisper-1",
        language: str | None = "en",
        custom_words: list[str] | None = None,
        client=None,  # noqa: ANN001 - an OpenAI client, or None to build one
    ) -> None:
        self.model = model
        self.language = language
        self.custom_words = custom_words or []
        self._client = client

    @property
    def client(self):  # noqa: ANN201
        """Return the OpenAI client. Build it on first use."""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def _prompt(self) -> str | None:
        """Return a spelling hint for names and terms, or None."""
        if not self.custom_words:
            return None
        return "Spell these terms correctly: " + ", ".join(self.custom_words)

    def transcribe(self, recording: Recording) -> str:
        """Return the text of the recording.

        Raises:
            TranscriptionError: The API call failed.
        """
        payload = recording.to_wav_bytes()
        request = {
            "model": self.model,
            "file": ("speech.wav", payload, "audio/wav"),
            "response_format": "text",
        }
        if self.language:
            request["language"] = self.language
        prompt = self._prompt()
        if prompt:
            request["prompt"] = prompt

        try:
            result = self.client.audio.transcriptions.create(**request)
        except Exception as error:  # noqa: BLE001 - report every API failure the same way
            raise TranscriptionError(str(error)) from error

        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()
