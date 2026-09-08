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
        timeout: float = 120.0,
        client=None,  # noqa: ANN001 - an OpenAI client, or None to build one
        relay_url: str | None = None,
        relay_token=None,  # noqa: ANN001 - a str, or a callable returning one
    ) -> None:
        self.timeout = timeout
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
                    timeout=self.timeout, max_retries=0,
                )
            else:
                self._client = OpenAI(timeout=self.timeout, max_retries=0)
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
        # The json shape, not text: it carries the usage block, which
        # the relay reads into its log so the cost report can price by
        # tokens. The text comes out of the same reply either way.
        upload = recording.for_upload()
        if self.relay_url and len(upload[1]) > 4_000_000:
            raise TranscriptionError("This recording is too large to send. Discard it and dictate a shorter section; the audio encoder may need repair.")
        request = {
            "model": self.model,
            "file": upload,
            "response_format": "json",
        }
        if self.language:
            request["language"] = self.language
        prompt = self._prompt()
        if prompt:
            request["prompt"] = prompt

        # Include UTF-8 prompts/custom words and a generous multipart-header
        # allowance, rather than comparing audio bytes to the relay cap alone.
        estimated_body = len(upload[1]) + sum(len(str(v).encode('utf-8')) for k, v in request.items() if k != 'file') + 8192
        if self.relay_url and estimated_body > 4_100_000:
            raise TranscriptionError('This recording and its custom words are too large to send. Use a shorter section or a smaller custom word list.')
        try:
            result = self._for_this_call().with_options(timeout=self.timeout, max_retries=0).audio.transcriptions.create(**request)
        except TranscriptionError:
            raise
        except Exception as error:  # noqa: BLE001 - report every API failure the same way
            status = getattr(error, "status_code", None)
            message = {401: "Please sign in again.", 403: "Your account does not have access.", 429: "The service is busy. Try again shortly."}.get(status, "Could not transcribe. Check your connection and try again.")
            raise TranscriptionError(message) from error

        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()
