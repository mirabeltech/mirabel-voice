"""Speech to text with the OpenAI Whisper API."""

from __future__ import annotations

from .audio import Recording
from .config import LANGUAGES, relay_base


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
        relay_url: str | None = None,
        relay_token=None,  # noqa: ANN001 - a str, or a callable returning one
    ) -> None:
        self.model = model
        self.language = language
        self.custom_words = custom_words or []
        self._client = client
        self.relay_url = relay_url
        self.relay_token = relay_token

    @property
    def client(self):  # noqa: ANN201
        """Return the OpenAI client. Build it on first use.

        A relay address redirects the same client rather than replacing it,
        so every request below this point is the one the SDK always sent.
        """
        if self._client is None:
            from openai import OpenAI

            if self.relay_url:
                # The SDK hangs its paths off the base URL, so the /v1 the
                # relay serves belongs here. A placeholder key is fine: a
                # rotating credential replaces it per call, below.
                self._client = OpenAI(
                    base_url=relay_base(self.relay_url) + "/v1",
                    api_key=self._current_key() or "signed-out",
                )
            else:
                self._client = OpenAI()
        return self._client

    def _current_key(self) -> str | None:
        """Return the relay credential as it stands right now.

        A Google sign-in rotates hourly, so it arrives as a callable and
        is asked fresh; a token is a string and is itself.
        """
        if callable(self.relay_token):
            return self.relay_token()
        return self.relay_token

    def _for_this_call(self):  # noqa: ANN201
        """Return the client to use for one request.

        With a rotating credential the client is re-armed per call;
        with a static token the built client is already right.
        """
        if not self.relay_url or not callable(self.relay_token):
            return self.client
        key = self._current_key()
        if key is None:
            raise TranscriptionError(
                "You are signed out of Google. Right-click the Mirabel "
                "Voice icon near the clock and choose Sign in with Google."
            )
        return self.client.with_options(api_key=key)

    def _prompt(self) -> str | None:
        """Return the transcription hint: the language, then spellings.

        The gpt-4o transcription models take the language parameter as a
        hint only and still follow the spoken language. The prompt is the
        stronger lever, so a pinned language goes there as well.
        """
        parts = []
        name = dict(LANGUAGES).get(self.language)
        if name:
            parts.append(
                f"The dictation is spoken in {name}. "
                f"Write the transcript in {name}."
            )
        if self.custom_words:
            parts.append(
                "Spell these terms correctly: " + ", ".join(self.custom_words)
            )
        return " ".join(parts) or None

    def transcribe(self, recording: Recording) -> str:
        """Return the text of the recording.

        Raises:
            TranscriptionError: The API call failed.
        """
        request = {
            "model": self.model,
            "file": recording.for_upload(),
            "response_format": "text",
        }
        if self.language:
            request["language"] = self.language
        prompt = self._prompt()
        if prompt:
            request["prompt"] = prompt

        try:
            result = self._for_this_call().audio.transcriptions.create(**request)
        except TranscriptionError:
            raise
        except Exception as error:  # noqa: BLE001 - report every API failure the same way
            raise TranscriptionError(str(error)) from error

        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()
