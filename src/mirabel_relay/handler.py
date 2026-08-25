"""The Lambda entry point: AWS on the outside, the relay on the inside.

AWS hands a Lambda Function URL request over as a dictionary and wants
a dictionary back. The relay itself knows nothing about that shape - it
speaks the plain Request and Response of relay.py - so this module is
the translation, and nothing else. Keeping the translation here is what
lets every relay test run without AWS.

The provider keys and the token list are read from AWS Secrets Manager
once, at cold start, and kept for the life of the container. A key that
cannot be read is reported by the name of the secret it came from, so a
mistyped paste points at the secret to fix instead of arriving as an
unexplained 401 from a provider.

Nothing here needs a package that is not already in the Lambda runtime:
boto3 ships with it, and the forwarding uses urllib from the standard
library. The deployment is therefore three source files and no build.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.request

from mirabel_relay.relay import Relay, Request, Response
from mirabel_relay.signin import GoogleSignin

log = logging.getLogger(__name__)

# The Lambda runtime leaves the root logger at WARNING, which drops every
# usage line the cost report is built from. The relay's own loggers say
# what they need at INFO; nothing else in the account is affected.
logging.getLogger("mirabel_relay").setLevel(logging.INFO)

DEFAULT_OPENAI_SECRET = "mirabel-voice/openai"
DEFAULT_ANTHROPIC_SECRET = "mirabel-voice/anthropic"
DEFAULT_TOKENS_SECRET = "mirabel-voice/tokens"

# Long enough for a five-minute recording to be transcribed, and short
# enough to answer before the Lambda's own timeout cuts the call off.
FORWARD_TIMEOUT = 100.0


class SecretProblem(Exception):
    """A secret is missing, unreadable, or not shaped as expected.

    The message always names the secret, because the fix is always in
    that one secret.
    """


def aws_secret(name: str) -> str:
    """Read one secret's value from AWS Secrets Manager."""
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("secretsmanager")
    try:
        answer = client.get_secret_value(SecretId=name)
    except ClientError as failure:
        code = failure.response.get("Error", {}).get("Code", "unknown")
        raise SecretProblem(
            f"The secret {name} could not be read ({code})."
        ) from failure
    value = answer.get("SecretString")
    if value is None:
        raise SecretProblem(f"The secret {name} holds bytes, not text.")
    return value


def build_relay(read_secret=aws_secret) -> Relay:
    """Assemble the relay from what the secrets hold.

    Args:
        read_secret: Returns one secret's value by name. Injected so
            the tests never reach AWS.
    """
    openai_name = os.environ.get("MIRABEL_OPENAI_SECRET", DEFAULT_OPENAI_SECRET)
    anthropic_name = os.environ.get(
        "MIRABEL_ANTHROPIC_SECRET", DEFAULT_ANTHROPIC_SECRET
    )
    tokens_name = os.environ.get("MIRABEL_TOKENS_SECRET", DEFAULT_TOKENS_SECRET)
    return Relay(
        tokens=_read_tokens(read_secret, tokens_name),
        anthropic_key=_read_key(read_secret, anthropic_name),
        openai_key=_read_key(read_secret, openai_name),
        forward=urllib_forward,
        signin=_google_signin(),
        update_info=_update_info(),
    )


def _update_info() -> dict | None:
    """Read the endorsed update, when the environment carries one.

    Both values or neither, like the sign-in: half an endorsement is a
    deploy mistake, and refusing to start names it.
    """
    version = os.environ.get("MIRABEL_UPDATE_VERSION", "").strip()
    digest = os.environ.get("MIRABEL_UPDATE_HASH", "").strip()
    if version and digest:
        return {"version": version, "sha256": digest}
    if version or digest:
        raise SecretProblem(
            "The update endorsement needs both MIRABEL_UPDATE_VERSION "
            "and MIRABEL_UPDATE_HASH. Only one is set."
        )
    return None


def _google_signin() -> GoogleSignin | None:
    """Build the sign-in verifier, when the environment configures one.

    Both values or neither: a half-configured sign-in is a deploy
    mistake, and refusing to start names it, where starting without
    sign-in would hide it until someone could not dictate.
    """
    client_id = os.environ.get("MIRABEL_GOOGLE_CLIENT_ID", "").strip()
    domain = os.environ.get("MIRABEL_GOOGLE_DOMAIN", "").strip()
    if client_id and domain:
        return GoogleSignin(client_id, domain)
    if client_id or domain:
        raise SecretProblem(
            "Google sign-in needs both MIRABEL_GOOGLE_CLIENT_ID and "
            "MIRABEL_GOOGLE_DOMAIN. Only one is set."
        )
    return None


def _read_key(read_secret, name: str) -> str:
    """Read a provider key, forgiving the whitespace a paste adds."""
    key = read_secret(name).strip()
    if not key:
        raise SecretProblem(f"The secret {name} is empty.")
    if key.startswith("{"):
        raise SecretProblem(
            f"The secret {name} holds JSON. Its whole value must be the "
            f"provider key on its own, with no braces and no quotes."
        )
    return key


def _read_tokens(read_secret, name: str) -> dict[str, str]:
    """Read the token list: every allowed token, mapped to its holder."""
    raw = read_secret(name)
    try:
        tokens = json.loads(raw)
    except ValueError as failure:
        raise SecretProblem(f"The secret {name} is not valid JSON.") from failure
    if not isinstance(tokens, dict) or not tokens:
        raise SecretProblem(
            f"The secret {name} must be a JSON object of token to holder "
            f"name, and must name at least one holder."
        )
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in tokens.items()):
        raise SecretProblem(
            f"Every entry in the secret {name} must be text to text."
        )
    return tokens


def urllib_forward(method: str, url: str, headers: dict, body: bytes):
    """Send one call to a provider, using only the standard library.

    A provider answering 4xx or 5xx is an answer, not a failure: it is
    returned like any other, so the relay passes the provider's own
    error back to the app instead of hiding it behind a 502.
    """
    call = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        call.add_header(name, value)
    try:
        with urllib.request.urlopen(call, timeout=FORWARD_TIMEOUT) as reply:
            return reply.status, dict(reply.headers), reply.read()
    except urllib.error.HTTPError as refusal:
        return refusal.code, dict(refusal.headers), refusal.read()


def request_from_event(event: dict) -> Request:
    """Turn one Function URL event into the relay's plain Request.

    Audio arrives base64 encoded, because it is not text; JSON usually
    does not. The event says which, and this is the only place that
    difference is handled.
    """
    http = event.get("requestContext", {}).get("http", {})
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        payload = base64.b64decode(body)
    else:
        payload = body.encode("utf-8")
    return Request(
        method=http.get("method", "GET"),
        path=event.get("rawPath") or http.get("path", "/"),
        headers=event.get("headers") or {},
        body=payload,
    )


def response_to_lambda(response: Response) -> dict:
    """Turn the relay's plain Response into what a Function URL wants.

    The body always travels base64 encoded. A transcript is text and an
    error is JSON, but encoding everything the same way means no reply
    can ever be corrupted by being guessed at.
    """
    return {
        "statusCode": response.status,
        "headers": response.headers,
        "body": base64.b64encode(response.body).decode("ascii"),
        "isBase64Encoded": True,
    }


_relay: Relay | None = None


def lambda_handler(event, context=None, relay: Relay | None = None) -> dict:
    """Answer one call from the app. AWS calls this.

    Args:
        event: The Function URL event.
        context: The Lambda context. Unused.
        relay: Injected by the tests. In AWS this is None, and the
            relay built at cold start is used instead.
    """
    if relay is None:
        try:
            relay = _cached_relay()
        except SecretProblem as problem:
            log.error("The relay could not start: %s", problem)
            return response_to_lambda(_server_error(str(problem)))
    return response_to_lambda(relay.handle(request_from_event(event)))


def _cached_relay() -> Relay:
    """Build the relay once per container, then keep it."""
    global _relay
    if _relay is None:
        _relay = build_relay()
    return _relay


def _server_error(message: str) -> Response:
    payload = json.dumps({"error": {"message": message}}).encode()
    return Response(500, payload, {"content-type": "application/json"})
