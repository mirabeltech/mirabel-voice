"""Tests for the Lambda entry point.

Everything runs offline. The secret reader is a fake, standing in for
Secrets Manager, and the relay is injected, so no test needs AWS, a
network, or credentials.
"""

import base64
import json
import urllib.error

import pytest

from mirabel_relay import handler
from mirabel_relay.handler import (
    SecretProblem,
    build_relay,
    lambda_handler,
    request_from_event,
    response_to_lambda,
    urllib_forward,
)
from mirabel_relay.relay import Relay, Request, Response

SECRETS = {
    "mirabel-voice/openai": "sk-the-real-openai-key",
    "mirabel-voice/anthropic": "sk-ant-the-real-key",
    "mirabel-voice/tokens": json.dumps({"tommy-token-1": "tommy"}),
}

PROVIDER_REPLY = json.dumps(
    {
        "content": [{"type": "text", "text": "Hello there."}],
        "usage": {"input_tokens": 21, "output_tokens": 7},
    }
).encode()


def fake_reader(secrets=None):
    """Return a reader over a dictionary, like Secrets Manager over AWS."""
    store = SECRETS if secrets is None else secrets

    def read(name):
        if name not in store:
            raise SecretProblem(f"The secret {name} could not be read (NotFound).")
        return store[name]

    return read


def event(
    method="POST",
    path="/v1/messages",
    headers=None,
    body=b'{"model": "claude-haiku-4-5"}',
    encoded=False,
):
    """Build one Lambda Function URL event."""
    payload = base64.b64encode(body).decode() if encoded else body.decode()
    return {
        "version": "2.0",
        "rawPath": path,
        "headers": headers if headers is not None else {"x-api-key": "tommy-token-1"},
        "requestContext": {"http": {"method": method, "path": path}},
        "body": payload,
        "isBase64Encoded": encoded,
    }


class EchoRelay:
    """Stand in for the relay, recording the request it was handed."""

    def __init__(self, response=None):
        self.response = response or Response(
            200, PROVIDER_REPLY, {"content-type": "application/json"}
        )
        self.seen = None

    def handle(self, request):
        self.seen = request
        return self.response


def test_the_method_and_path_survive_the_event():
    relay = EchoRelay()
    lambda_handler(event(path="/v1/audio/transcriptions"), None, relay=relay)
    assert relay.seen.method == "POST"
    assert relay.seen.path == "/v1/audio/transcriptions"


def test_audio_arrives_as_the_bytes_that_were_sent():
    audio = bytes(range(256))
    relay = EchoRelay()
    lambda_handler(event(body=audio, encoded=True), None, relay=relay)
    assert relay.seen.body == audio


def test_json_arrives_as_the_bytes_that_were_sent():
    body = b'{"model": "claude-haiku-4-5"}'
    relay = EchoRelay()
    lambda_handler(event(body=body), None, relay=relay)
    assert relay.seen.body == body


def test_an_empty_body_is_not_an_error():
    request = request_from_event(event(method="GET", body=b""))
    assert request.body == b""


def test_the_answer_carries_the_status_and_the_headers():
    answer = response_to_lambda(Response(401, b'{"error": {}}', {"content-type": "x"}))
    assert answer["statusCode"] == 401
    assert answer["headers"] == {"content-type": "x"}


def test_the_answer_body_survives_the_round_trip():
    reply = Response(200, PROVIDER_REPLY, {})
    answer = response_to_lambda(reply)
    assert answer["isBase64Encoded"] is True
    assert base64.b64decode(answer["body"]) == PROVIDER_REPLY


def test_a_real_relay_refuses_an_unknown_token():
    relay = Relay(
        tokens={"tommy-token-1": "tommy"},
        anthropic_key="sk-ant-the-real-key",
        openai_key="sk-the-real-openai-key",
        forward=lambda *args: (200, {}, PROVIDER_REPLY),
    )
    answer = lambda_handler(
        event(headers={"x-api-key": "not-a-token"}), None, relay=relay
    )
    assert answer["statusCode"] == 401


def test_a_real_relay_answers_a_known_token():
    relay = Relay(
        tokens={"tommy-token-1": "tommy"},
        anthropic_key="sk-ant-the-real-key",
        openai_key="sk-the-real-openai-key",
        forward=lambda *args: (200, {"content-type": "application/json"}, PROVIDER_REPLY),
    )
    answer = lambda_handler(event(), None, relay=relay)
    assert answer["statusCode"] == 200
    assert base64.b64decode(answer["body"]) == PROVIDER_REPLY


def test_the_keys_and_tokens_come_from_the_secrets():
    relay = build_relay(read_secret=fake_reader())
    assert relay.openai_key == "sk-the-real-openai-key"
    assert relay.anthropic_key == "sk-ant-the-real-key"
    assert relay.tokens == {"tommy-token-1": "tommy"}


def test_a_pasted_key_may_carry_whitespace():
    secrets = dict(SECRETS, **{"mirabel-voice/openai": "  sk-the-real-openai-key\n"})
    relay = build_relay(read_secret=fake_reader(secrets))
    assert relay.openai_key == "sk-the-real-openai-key"


def test_an_empty_key_names_its_secret():
    secrets = dict(SECRETS, **{"mirabel-voice/anthropic": "   "})
    with pytest.raises(SecretProblem, match="mirabel-voice/anthropic"):
        build_relay(read_secret=fake_reader(secrets))


def test_a_key_pasted_as_json_names_its_secret():
    secrets = dict(SECRETS, **{"mirabel-voice/openai": '{"key": "sk-the-real-key"}'})
    with pytest.raises(SecretProblem, match="mirabel-voice/openai"):
        build_relay(read_secret=fake_reader(secrets))


def test_a_broken_token_list_names_its_secret():
    secrets = dict(SECRETS, **{"mirabel-voice/tokens": "not json at all"})
    with pytest.raises(SecretProblem, match="mirabel-voice/tokens"):
        build_relay(read_secret=fake_reader(secrets))


def test_an_empty_token_list_names_its_secret():
    secrets = dict(SECRETS, **{"mirabel-voice/tokens": "{}"})
    with pytest.raises(SecretProblem, match="mirabel-voice/tokens"):
        build_relay(read_secret=fake_reader(secrets))


def test_a_missing_secret_is_answered_with_500_naming_it(monkeypatch):
    monkeypatch.setattr(handler, "_relay", None)
    monkeypatch.setattr(
        handler, "build_relay", lambda: (_ for _ in ()).throw(
            SecretProblem("The secret mirabel-voice/openai could not be read.")
        )
    )
    answer = lambda_handler(event(), None)
    assert answer["statusCode"] == 500
    assert "mirabel-voice/openai" in base64.b64decode(answer["body"]).decode()


def test_the_secret_names_can_be_moved_by_environment(monkeypatch):
    monkeypatch.setenv("MIRABEL_TOKENS_SECRET", "other/tokens")
    secrets = dict(SECRETS)
    secrets["other/tokens"] = json.dumps({"priya-token-2": "priya"})
    relay = build_relay(read_secret=fake_reader(secrets))
    assert relay.tokens == {"priya-token-2": "priya"}


def test_a_provider_refusal_comes_back_as_an_answer(monkeypatch):
    """A provider 400 is the provider's answer, not the relay failing."""

    def refuse(call, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.anthropic.com/v1/messages",
            400,
            "Bad Request",
            {"content-type": "application/json"},
            None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    status, headers, body = urllib_forward(
        "POST", "https://api.anthropic.com/v1/messages", {}, b"{}"
    )
    assert status == 400


def test_sign_in_arrives_from_the_environment(monkeypatch):
    monkeypatch.setenv("MIRABEL_GOOGLE_CLIENT_ID", "12345-mirabel.apps")
    monkeypatch.setenv("MIRABEL_GOOGLE_DOMAIN", "mirabeltech.com")
    relay = build_relay(read_secret=fake_reader())
    assert relay.signin is not None
    assert relay.signin.client_id == "12345-mirabel.apps"
    assert relay.signin.domain == "mirabeltech.com"


def test_without_the_environment_the_relay_is_tokens_only():
    relay = build_relay(read_secret=fake_reader())
    assert relay.signin is None


def test_half_a_sign_in_configuration_refuses_to_start(monkeypatch):
    """One variable without the other is a deploy mistake, and it must
    be named at start rather than discovered as unexplained 401s."""
    monkeypatch.setenv("MIRABEL_GOOGLE_CLIENT_ID", "12345-mirabel.apps")
    with pytest.raises(SecretProblem, match="MIRABEL_GOOGLE_DOMAIN"):
        build_relay(read_secret=fake_reader())
