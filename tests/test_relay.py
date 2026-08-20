"""Tests for the relay's cleanup route and token auth.

Everything runs offline: the forward function is a fake, standing in
for the network, and the tests speak the Anthropic wire format the
real SDK would send.
"""

import json
import logging

from mirabel_relay.relay import ANTHROPIC_BASE, Relay, Request

TOKENS = {"tommy-token-1": "tommy", "priya-token-2": "priya"}
REAL_KEY = "sk-ant-the-real-key"

CLEANUP_BODY = json.dumps(
    {
        "model": "claude-haiku-4-5",
        "system": "Clean up dictated text.",
        "messages": [{"role": "user", "content": "um hello there"}],
    }
).encode()

PROVIDER_REPLY = json.dumps(
    {
        "content": [{"type": "text", "text": "Hello there."}],
        "usage": {"input_tokens": 21, "output_tokens": 7},
    }
).encode()


class FakeForward:
    """Stand in for the network. Records every call it receives."""

    def __init__(self, status=200, body=PROVIDER_REPLY, error=None):
        self.status = status
        self.body = body
        self.error = error
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "body": body}
        )
        if self.error is not None:
            raise self.error
        return self.status, {"content-type": "application/json"}, self.body


def make_relay(forward=None):
    forward = forward if forward is not None else FakeForward()
    relay = Relay(
        tokens=TOKENS, anthropic_key=REAL_KEY, forward=forward, clock=lambda: 0.0
    )
    return relay, forward


def cleanup_request(token="tommy-token-1", header="x-api-key"):
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if token is not None:
        if header == "x-api-key":
            headers["x-api-key"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
    return Request(method="POST", path="/v1/messages", headers=headers, body=CLEANUP_BODY)


def test_a_valid_token_gets_the_cleaned_text_back():
    relay, forward = make_relay()
    reply = relay.handle(cleanup_request())
    assert reply.status == 200
    assert reply.body == PROVIDER_REPLY
    assert len(forward.calls) == 1
    assert forward.calls[0]["url"] == ANTHROPIC_BASE + "/v1/messages"


def test_the_request_body_travels_unchanged():
    """Byte-for-byte passthrough is what makes relay mode behave
    exactly like direct mode."""
    relay, forward = make_relay()
    relay.handle(cleanup_request())
    assert forward.calls[0]["body"] == CLEANUP_BODY


def test_the_real_key_goes_out_and_the_token_does_not():
    relay, forward = make_relay()
    relay.handle(cleanup_request())
    sent = forward.calls[0]["headers"]
    assert sent["x-api-key"] == REAL_KEY
    assert "tommy-token-1" not in json.dumps(sent)
    assert "authorization" not in {k.lower() for k in sent}


def test_the_providers_own_headers_still_travel():
    """anthropic-version and content-type must reach the provider, or
    the SDK's request is no longer the request that arrives."""
    relay, forward = make_relay()
    relay.handle(cleanup_request())
    sent = forward.calls[0]["headers"]
    assert sent["anthropic-version"] == "2023-06-01"
    assert sent["content-type"] == "application/json"


def test_a_missing_token_is_refused_before_any_provider_call():
    relay, forward = make_relay()
    reply = relay.handle(cleanup_request(token=None))
    assert reply.status == 401
    assert forward.calls == []


def test_an_unknown_token_is_refused_before_any_provider_call():
    relay, forward = make_relay()
    reply = relay.handle(cleanup_request(token="stolen-guess"))
    assert reply.status == 401
    assert forward.calls == []


def test_the_token_is_read_from_a_bearer_header_too():
    """The OpenAI SDK carries its key as Authorization: Bearer. The
    relay accepts the token wherever the SDKs put it."""
    relay, forward = make_relay()
    reply = relay.handle(cleanup_request(header="bearer"))
    assert reply.status == 200
    assert len(forward.calls) == 1


def test_an_unknown_path_is_refused_without_a_provider_call():
    relay, forward = make_relay()
    request = cleanup_request()
    request.path = "/v1/other"
    reply = relay.handle(request)
    assert reply.status == 404
    assert forward.calls == []


def test_a_provider_error_status_passes_through():
    """A 529 from Anthropic must reach the app as a 529, so the app's
    own fallback (use the raw transcript) still fires."""
    relay, _ = make_relay(FakeForward(status=529, body=b'{"error":{}}'))
    reply = relay.handle(cleanup_request())
    assert reply.status == 529


def test_an_unreachable_provider_answers_502():
    relay, _ = make_relay(FakeForward(error=ConnectionError("down")))
    reply = relay.handle(cleanup_request())
    assert reply.status == 502


def test_the_usage_line_names_who_and_how_much(caplog):
    relay, _ = make_relay()
    with caplog.at_level(logging.INFO):
        relay.handle(cleanup_request())
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage ")]
    assert len(lines) == 1
    line = json.loads(lines[0].removeprefix("usage "))
    assert line["token"] == "tommy"
    assert line["route"] == "cleanup"
    assert line["model"] == "claude-haiku-4-5"
    assert line["input_tokens"] == 21
    assert line["output_tokens"] == 7
    assert line["outcome"] == "ok"


def test_no_log_line_ever_contains_the_spoken_words(caplog):
    """The zero-data-at-rest promise extends to the relay: what was
    said appears in no log, on success or refusal."""
    relay, _ = make_relay()
    with caplog.at_level(logging.DEBUG):
        relay.handle(cleanup_request())
        relay.handle(cleanup_request(token="stolen-guess"))
    everything = " ".join(r.getMessage() for r in caplog.records)
    assert "um hello there" not in everything
    assert "Hello there." not in everything
    assert "tommy-token-1" not in everything


def test_a_refusal_is_logged_without_naming_anyone(caplog):
    relay, _ = make_relay()
    with caplog.at_level(logging.INFO):
        relay.handle(cleanup_request(token="stolen-guess"))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage ")]
    line = json.loads(lines[0].removeprefix("usage "))
    assert line["token"] == "-"
    assert line["outcome"] == "refused"
