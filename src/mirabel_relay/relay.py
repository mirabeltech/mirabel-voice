"""The relay: it holds the provider keys so the laptops do not have to.

The app points its provider SDKs at this relay instead of at the
providers. A request arrives carrying a per-person token where the
provider key would normally be. The relay checks the token, swaps in
the real key, and forwards the call unchanged. The response travels
back the same way.

The wire formats are the providers' own, because the app redirects by
base URL alone: cleanup is POST /v1/messages exactly as the Anthropic
SDK sends it, and transcription is POST /v1/audio/transcriptions
exactly as the OpenAI SDK sends it. The relay never rewrites a request
body, so the app's behavior through the relay is the same as without
it.

Nothing spoken or written is ever logged. Each request emits one usage
line - who, which route, which model, how much, how long, and the
outcome - and that line never contains payload text or audio bytes.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from mirabel_relay.signin import looks_like_jwt

log = logging.getLogger(__name__)

ANTHROPIC_BASE = "https://api.anthropic.com"
OPENAI_BASE = "https://api.openai.com"

# The rate Ogg granule positions count at for Opus, whatever the
# recording's own sample rate.
OGG_OPUS_GRANULE_RATE = 48_000

# Headers that carry the caller's credential or the transport's own
# bookkeeping. They must not travel on to the provider.
#
# accept-encoding is in the list for a different reason. The SDKs ask for
# gzip, and a compressed reply arriving here would have to be decompressed
# to be understood or passed on with its content-encoding intact. Asking
# the provider for plain bytes instead keeps the relay a byte forwarder.
# The bodies are a few kilobytes, so the compression buys nothing here.
STRIPPED_HEADERS = {
    "x-api-key",
    "authorization",
    "host",
    "content-length",
    "accept-encoding",
}

# Reply headers the client needs to read the body. Anything else the
# provider sends is the provider's own bookkeeping and stops here.
PASSED_REPLY_HEADERS = ("content-type", "content-encoding")


@dataclass
class Request:
    """One call from the app, in plain form."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Response:
    """One answer to the app, in plain form."""

    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


Forward = Callable[[str, str, dict, bytes], tuple[int, dict, bytes]]


def http_forward(method: str, url: str, headers: dict, body: bytes):
    """Send one call over the network. The tests replace this."""
    import httpx

    reply = httpx.request(method, url, headers=headers, content=body, timeout=60.0)
    return reply.status_code, dict(reply.headers), reply.content


def _error(status: int, message: str) -> Response:
    payload = json.dumps({"error": {"message": message}}).encode()
    return Response(status, payload, {"content-type": "application/json"})


class Relay:
    """Check the caller's credential, swap in the real key, forward the call.

    Args:
        tokens: Every allowed token, mapped to the holder's name. The
            names appear in the usage log; the tokens never do.
        anthropic_key: The real Anthropic key, from the secret store.
        openai_key: The real OpenAI key, from the secret store.
        forward: Sends one HTTP call. Injected so every test runs
            offline - this is the relay's one testing seam.
        clock: Returns seconds, for the latency figure. Injected for
            the tests.
        signin: Verifies a Google sign-in and returns the account's
            email, or None to refuse. When set, a credential shaped
            like an ID token is judged by it instead of the token
            list. None means tokens only, which is also what an
            undeployed or half-configured sign-in safely degrades to.
        update_info: The release every machine should self-update to:
            {"version": ..., "sha256": ...}, set at deploy time. None
            means no endorsement, and the app falls back to following
            the newest published release.
    """

    def __init__(
        self,
        tokens: dict[str, str],
        anthropic_key: str,
        openai_key: str,
        forward: Forward = http_forward,
        clock: Callable[[], float] | None = None,
        signin=None,
        update_info: dict | None = None,
    ) -> None:
        self.tokens = tokens
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.forward = forward
        self._clock = clock or time.monotonic
        self.signin = signin
        self.update_info = update_info

    def handle(self, request: Request) -> Response:
        """Answer one call from the app."""
        name = self._authenticate(request.headers)
        if name is None:
            self._log_usage("-", request.path, None, None, 0.0, "refused")
            return _error(401, "The token is missing or not recognized.")
        if request.method == "POST" and request.path == "/v1/messages":
            return self._cleanup(name, request)
        if request.method == "POST" and request.path == "/v1/audio/transcriptions":
            return self._transcribe(name, request)
        if request.method == "GET" and request.path == "/update":
            return self._update(name)
        return _error(404, "The relay does not serve this path.")

    def _update(self, name: str) -> Response:
        """Say which release this relay endorses for self-update.

        The two values are set at deploy time and are not secrets. No
        endorsement is an answer too: the app then falls back to the
        newest published release, which is how machines behaved before
        endorsement existed.
        """
        if not self.update_info:
            self._log_usage(name, "update", None, None, 0.0, "none")
            return _error(404, "The relay endorses no update.")
        self._log_usage(name, "update", None, None, 0.0, "ok")
        return Response(
            200,
            json.dumps(self.update_info).encode(),
            {"content-type": "application/json"},
        )

    def _cleanup(self, name: str, request: Request) -> Response:
        """Forward a transcript to Anthropic for tidying."""
        return self._proxy(
            name,
            route="cleanup",
            url=ANTHROPIC_BASE + "/v1/messages",
            auth=("x-api-key", self.anthropic_key),
            request=request,
            model=_json_model(request.body),
            usage_from_reply=_token_usage,
        )

    def _transcribe(self, name: str, request: Request) -> Response:
        """Forward a recording to OpenAI for speech-to-text.

        The body is multipart form data holding the audio file and the
        request fields. It travels byte for byte; the parsing here is
        for the usage line only. The audio's length in seconds comes
        from the container header - Ogg Opus pages or the WAV header -
        so no audio is ever decoded, and no audio bytes are logged.
        """
        content_type = _header(request.headers, "content-type")
        model = None
        seconds = None
        boundary = _boundary_of(content_type)
        if boundary:
            model = _multipart_text(request.body, boundary, "model")
            audio = _multipart_file(request.body, boundary)
            if audio is not None:
                seconds = _audio_seconds(audio)
        return self._proxy(
            name,
            route="transcribe",
            url=OPENAI_BASE + "/v1/audio/transcriptions",
            auth=("authorization", "Bearer " + self.openai_key),
            request=request,
            model=model,
            usage_from_reply=_transcribe_usage,
            extra_usage={
                "audio_seconds": round(seconds, 1) if seconds else None
            },
        )

    def _authenticate(self, headers: dict[str, str]) -> str | None:
        """Return the caller's name, or None to refuse.

        Two kinds of credential arrive here. A Google ID token has a
        JWT's three-part shape - relay tokens never contain a dot - and
        is judged by the sign-in verifier when one is configured. A
        failed sign-in is refused outright rather than retried against
        the token list, so the two doors stay separate. Everything else
        is compared against the token list, and that comparison takes
        the same time whether the token is nearly right or nowhere
        close, so response timing teaches an attacker nothing.
        """
        presented = self._presented_token(headers)
        if not presented:
            return None
        if self.signin is not None and looks_like_jwt(presented):
            return self.signin.verify(presented)
        for token, name in self.tokens.items():
            if hmac.compare_digest(token.encode(), presented.encode()):
                return name
        return None

    @staticmethod
    def _presented_token(headers: dict[str, str]) -> str | None:
        """Read the token from either header the provider SDKs use.

        The Anthropic SDK sends x-api-key; the OpenAI SDK sends
        Authorization: Bearer. The app uses both SDKs, so the relay
        accepts the token in either place.
        """
        lowered = {k.lower(): v for k, v in headers.items()}
        if lowered.get("x-api-key"):
            return lowered["x-api-key"]
        auth = lowered.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[len("bearer "):].strip() or None
        return None

    def _proxy(
        self,
        name: str,
        route: str,
        url: str,
        auth: tuple[str, str],
        request: Request,
        model: str | None,
        usage_from_reply: Callable[[bytes], dict | None] | None = None,
        extra_usage: dict | None = None,
    ) -> Response:
        """Forward one call with the real key, and log the usage line."""
        headers = {
            k.lower(): v
            for k, v in request.headers.items()
            if k.lower() not in STRIPPED_HEADERS
        }
        header_name, header_value = auth
        headers[header_name] = header_value

        started = self._clock()
        try:
            status, reply_headers, body = self.forward(
                request.method, url, headers, request.body
            )
        except Exception:  # noqa: BLE001 - the provider being down is an answer too
            latency = self._clock() - started
            log.exception("The provider could not be reached.")
            self._log_usage(name, route, model, extra_usage, latency, "unreachable")
            return _error(502, "The provider could not be reached.")
        latency = self._clock() - started

        outcome = "ok" if status < 400 else f"provider-{status}"
        usage = dict(extra_usage or {})
        if usage_from_reply is not None and status < 400:
            usage.update(usage_from_reply(body) or {})
        self._log_usage(name, route, model, usage or None, latency, outcome)

        lowered = {k.lower(): v for k, v in reply_headers.items()}
        headers = {"content-type": lowered.get("content-type", "application/json")}
        # A provider that compresses anyway must say so, or the client
        # reads gzip bytes as text and the call fails at the last step.
        for name in PASSED_REPLY_HEADERS[1:]:
            if lowered.get(name):
                headers[name] = lowered[name]
        return Response(status, body, headers)

    @staticmethod
    def _log_usage(
        name: str,
        route: str,
        model: str | None,
        usage: dict | None,
        latency: float,
        outcome: str,
    ) -> None:
        """Emit the one line per request that the cost report is built from.

        The line names who and how much, never what was said. Nothing
        here may ever include request text, response text, or audio.
        """
        line = {
            "token": name,
            "route": route,
            "model": model,
            "latency_ms": round(latency * 1000),
            "outcome": outcome,
        }
        if usage:
            line.update(usage)
        log.info("usage %s", json.dumps(line, sort_keys=True))


def _header(headers: dict[str, str], name: str) -> str:
    """Return one header's value, whatever its capitalization."""
    return {k.lower(): v for k, v in headers.items()}.get(name, "")


def _json_model(body: bytes) -> str | None:
    """Read the model name from a JSON request, for the usage line."""
    try:
        model = json.loads(body).get("model")
        return model if isinstance(model, str) else None
    except Exception:  # noqa: BLE001 - a body we cannot read is not an error
        return None


def _token_usage(body: bytes) -> dict | None:
    """Read the token counts from an Anthropic reply, for the usage line."""
    try:
        usage = json.loads(body).get("usage") or {}
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
    except Exception:  # noqa: BLE001
        return None


def _transcribe_usage(body: bytes) -> dict | None:
    """Read the token counts from an OpenAI transcription reply.

    The counts arrive when the app asks for the json reply shape.
    A plain text reply, or a model that reports duration instead of
    tokens, gives None, and the usage line then holds audio_seconds
    alone. The reply's transcript text is never touched: only the
    numbers leave here.
    """
    try:
        usage = json.loads(body).get("usage") or {}
        if usage.get("type") != "tokens":
            return None
        details = usage.get("input_token_details") or {}
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "audio_tokens": details.get("audio_tokens"),
            "text_tokens": details.get("text_tokens"),
        }
    except Exception:  # noqa: BLE001
        return None


def _boundary_of(content_type: str) -> bytes | None:
    """Read the multipart boundary out of a Content-Type header."""
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            value = part[len("boundary="):].strip().strip('"')
            return value.encode() if value else None
    return None


def _multipart_parts(body: bytes, boundary: bytes):
    """Yield (headers, payload) for each part of a multipart body."""
    pieces = body.split(b"--" + boundary)
    for piece in pieces[1:-1]:  # drop the preamble and the closing "--"
        piece = piece.strip(b"\r\n")
        head, separator, payload = piece.partition(b"\r\n\r\n")
        if separator:
            yield head, payload


def _multipart_text(body: bytes, boundary: bytes, name: str) -> str | None:
    """Return one text field of a multipart body, for the usage line."""
    marker = b'name="' + name.encode() + b'"'
    for head, payload in _multipart_parts(body, boundary):
        if marker in head and b"filename=" not in head:
            try:
                return payload.decode().strip()
            except Exception:  # noqa: BLE001
                return None
    return None


def _multipart_file(body: bytes, boundary: bytes) -> bytes | None:
    """Return the uploaded file's bytes from a multipart body."""
    for head, payload in _multipart_parts(body, boundary):
        if b"filename=" in head:
            return payload
    return None


def _audio_seconds(payload: bytes) -> float | None:
    """Return the recording's length, read from its container header.

    Understands the two shapes the app sends: Ogg Opus, and the WAV
    fallback. Returns None for anything else - an unknown length must
    never block a transcription.
    """
    if payload[:4] == b"OggS":
        return _ogg_seconds(payload)
    if payload[:4] == b"RIFF":
        return _wav_seconds(payload)
    return None


def _ogg_seconds(payload: bytes) -> float | None:
    """Length of an Ogg Opus stream, from its last page.

    Every Ogg page carries a granule position - the count of 48 kHz
    samples up to that page, whatever the recording's own rate. The
    last page's position is the length. No decoding needed.
    """
    index = payload.rfind(b"OggS")
    if index < 0 or len(payload) < index + 14:
        return None
    granule = int.from_bytes(payload[index + 6 : index + 14], "little", signed=True)
    if granule <= 0:
        return None
    return granule / OGG_OPUS_GRANULE_RATE


def _wav_seconds(payload: bytes) -> float | None:
    """Length of a WAV file: data size over byte rate, from the header."""
    if payload[8:12] != b"WAVE":
        return None
    byte_rate = None
    data_size = None
    position = 12
    while position + 8 <= len(payload):
        chunk_id = payload[position : position + 4]
        size = int.from_bytes(payload[position + 4 : position + 8], "little")
        if chunk_id == b"fmt " and size >= 16:
            byte_rate = int.from_bytes(
                payload[position + 16 : position + 20], "little"
            )
        elif chunk_id == b"data":
            data_size = size
        position += 8 + size + (size % 2)  # chunks are padded to even sizes
    if not byte_rate or not data_size:
        return None
    return data_size / byte_rate
