"""The relay: it holds the provider keys so the laptops do not have to.

The app points its provider SDKs at this relay instead of at the
providers. A request arrives carrying a per-person token where the
provider key would normally be. The relay checks the token, swaps in
the real key, and forwards the call unchanged. The response travels
back the same way.

The wire format is the provider's own, because the app redirects by
base URL alone: the cleanup route is POST /v1/messages, exactly as the
Anthropic SDK sends it. The relay never rewrites a request body, so
the app's behavior through the relay is the same as without it.

Nothing spoken or written is ever logged. Each request emits one usage
line - who, which route, which model, how many tokens, how long, and
the outcome - and that line never contains payload text.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

ANTHROPIC_BASE = "https://api.anthropic.com"

# Headers that carry the caller's credential or the transport's own
# bookkeeping. They must not travel on to the provider.
STRIPPED_HEADERS = {"x-api-key", "authorization", "host", "content-length"}


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
    """Check the caller's token, swap in the real key, forward the call.

    Args:
        tokens: Every allowed token, mapped to the holder's name. The
            names appear in the usage log; the tokens never do.
        anthropic_key: The real Anthropic key, from the secret store.
        forward: Sends one HTTP call. Injected so every test runs
            offline - this is the relay's one testing seam.
        clock: Returns seconds, for the latency figure. Injected for
            the tests.
    """

    def __init__(
        self,
        tokens: dict[str, str],
        anthropic_key: str,
        forward: Forward = http_forward,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.tokens = tokens
        self.anthropic_key = anthropic_key
        self.forward = forward
        self._clock = clock or time.monotonic

    def handle(self, request: Request) -> Response:
        """Answer one call from the app."""
        name = self._authenticate(request.headers)
        if name is None:
            self._log_usage("-", request.path, None, None, 0.0, "refused")
            return _error(401, "The token is missing or not recognized.")
        if request.method == "POST" and request.path == "/v1/messages":
            return self._proxy(
                name,
                route="cleanup",
                url=ANTHROPIC_BASE + "/v1/messages",
                key_header="x-api-key",
                key=self.anthropic_key,
                request=request,
            )
        return _error(404, "The relay does not serve this path.")

    def _authenticate(self, headers: dict[str, str]) -> str | None:
        """Return the token holder's name, or None to refuse.

        The comparison takes the same time whether the token is nearly
        right or nowhere close, so response timing teaches an attacker
        nothing about the token list.
        """
        presented = self._presented_token(headers)
        if not presented:
            return None
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
        key_header: str,
        key: str,
        request: Request,
    ) -> Response:
        """Forward one call with the real key, and log the usage line."""
        headers = {
            k.lower(): v
            for k, v in request.headers.items()
            if k.lower() not in STRIPPED_HEADERS
        }
        headers[key_header] = key
        model = self._model_of(request.body)

        started = self._clock()
        try:
            status, reply_headers, body = self.forward(
                request.method, url, headers, request.body
            )
        except Exception:  # noqa: BLE001 - the provider being down is an answer too
            latency = self._clock() - started
            log.exception("The provider could not be reached.")
            self._log_usage(name, route, model, None, latency, "unreachable")
            return _error(502, "The provider could not be reached.")
        latency = self._clock() - started

        outcome = "ok" if status < 400 else f"provider-{status}"
        usage = self._usage_of(body) if status < 400 else None
        self._log_usage(name, route, model, usage, latency, outcome)

        content_type = {
            k.lower(): v for k, v in reply_headers.items()
        }.get("content-type", "application/json")
        return Response(status, body, {"content-type": content_type})

    @staticmethod
    def _model_of(body: bytes) -> str | None:
        """Read the model name from the request, for the usage line."""
        try:
            model = json.loads(body).get("model")
            return model if isinstance(model, str) else None
        except Exception:  # noqa: BLE001 - a body we cannot read is not an error
            return None

    @staticmethod
    def _usage_of(body: bytes) -> dict | None:
        """Read the token counts from a provider reply, for the usage line."""
        try:
            usage = json.loads(body).get("usage") or {}
            return {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        except Exception:  # noqa: BLE001
            return None

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
        here may ever include request or response text.
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
