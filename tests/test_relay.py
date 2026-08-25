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
REAL_OPENAI_KEY = "sk-the-real-openai-key"

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
        tokens=TOKENS,
        anthropic_key=REAL_KEY,
        openai_key=REAL_OPENAI_KEY,
        forward=forward,
        clock=lambda: 0.0,
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


# --- The transcribe route: audio through the relay ---


BOUNDARY = "test-boundary-1234"


def ogg_audio(seconds=2.0):
    """A minimal Ogg stream whose last page says it is this long."""
    granule = int(seconds * 48000)
    page = b"OggS" + bytes(2) + granule.to_bytes(8, "little") + bytes(14)
    return b"OggS" + bytes(2) + bytes(8) + bytes(14) + page


def wav_audio(seconds=2.0):
    """A minimal WAV whose header says it is this long (16 kHz mono)."""
    byte_rate = 32000
    data_size = int(seconds * byte_rate)
    fmt = (
        (1).to_bytes(2, "little")          # PCM
        + (1).to_bytes(2, "little")        # mono
        + (16000).to_bytes(4, "little")    # sample rate
        + byte_rate.to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
    )
    body = b"WAVE" + b"fmt " + len(fmt).to_bytes(4, "little") + fmt
    body += b"data" + data_size.to_bytes(4, "little")
    return b"RIFF" + (len(body) + data_size).to_bytes(4, "little") + body


def multipart(audio, filename="speech.ogg", model="gpt-4o-mini-transcribe"):
    """Build the multipart body the OpenAI SDK would send."""
    b = BOUNDARY.encode()
    parts = []
    for name, value in [
        ("model", model),
        ("language", "en"),
        ("prompt", "Spell these terms correctly: ChargeBrite"),
    ]:
        parts.append(
            b"--" + b + b"\r\n"
            b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n'
            b"\r\n" + value.encode() + b"\r\n"
        )
    parts.append(
        b"--" + b + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="'
        + filename.encode() + b'"\r\n'
        b"Content-Type: audio/ogg\r\n\r\n" + audio + b"\r\n"
    )
    parts.append(b"--" + b + b"--\r\n")
    return b"".join(parts)


def transcribe_request(token="tommy-token-1", audio=None, filename="speech.ogg"):
    audio = audio if audio is not None else ogg_audio()
    headers = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return Request(
        method="POST",
        path="/v1/audio/transcriptions",
        headers=headers,
        body=multipart(audio, filename=filename),
    )


def test_a_recording_comes_back_as_text():
    relay, forward = make_relay(FakeForward(body=b"um hello there"))
    reply = relay.handle(transcribe_request())
    assert reply.status == 200
    assert reply.body == b"um hello there"
    assert forward.calls[0]["url"].endswith("/v1/audio/transcriptions")


def test_the_multipart_body_travels_unchanged():
    """The audio, the language, and the spelling prompt must arrive at
    OpenAI exactly as the SDK built them."""
    relay, forward = make_relay(FakeForward(body=b"words"))
    request = transcribe_request()
    relay.handle(request)
    assert forward.calls[0]["body"] == request.body


def test_the_real_openai_key_goes_out_as_a_bearer():
    relay, forward = make_relay(FakeForward(body=b"words"))
    relay.handle(transcribe_request())
    sent = forward.calls[0]["headers"]
    assert sent["authorization"] == "Bearer " + REAL_OPENAI_KEY
    assert "tommy-token-1" not in json.dumps(sent)


def test_transcribe_auth_matches_the_cleanup_route():
    relay, forward = make_relay(FakeForward(body=b"words"))
    reply = relay.handle(transcribe_request(token="stolen-guess"))
    assert reply.status == 401
    assert forward.calls == []
    reply = relay.handle(transcribe_request(token=None))
    assert reply.status == 401
    assert forward.calls == []


def test_the_usage_line_carries_audio_seconds_from_an_opus_upload(caplog):
    relay, _ = make_relay(FakeForward(body=b"words"))
    with caplog.at_level(logging.INFO):
        relay.handle(transcribe_request(audio=ogg_audio(seconds=2.0)))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage ")]
    line = json.loads(lines[0].removeprefix("usage "))
    assert line["route"] == "transcribe"
    assert line["model"] == "gpt-4o-mini-transcribe"
    assert line["audio_seconds"] == 2.0
    assert line["token"] == "tommy"


def test_the_usage_line_carries_audio_seconds_from_a_wav_fallback(caplog):
    """The app falls back to WAV when Opus encoding fails. The fallback
    must not be orphaned by the relay."""
    relay, _ = make_relay(FakeForward(body=b"words"))
    with caplog.at_level(logging.INFO):
        relay.handle(
            transcribe_request(audio=wav_audio(seconds=3.0), filename="speech.wav")
        )
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage ")]
    line = json.loads(lines[0].removeprefix("usage "))
    assert line["audio_seconds"] == 3.0


def test_an_unreadable_recording_still_transcribes(caplog):
    """The length is bookkeeping. A file the relay cannot measure must
    still reach the provider - losing a dictation over a log field
    would be absurd."""
    relay, forward = make_relay(FakeForward(body=b"words"))
    with caplog.at_level(logging.INFO):
        reply = relay.handle(transcribe_request(audio=b"not an audio container"))
    assert reply.status == 200
    assert len(forward.calls) == 1
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("usage ")]
    line = json.loads(lines[0].removeprefix("usage "))
    assert line["audio_seconds"] is None


def test_no_transcribe_log_ever_contains_audio_bytes(caplog):
    audio = ogg_audio()
    relay, _ = make_relay(FakeForward(body=b"the spoken words"))
    with caplog.at_level(logging.DEBUG):
        relay.handle(transcribe_request(audio=audio))
    for record in caplog.records:
        message = record.getMessage()
        assert "the spoken words" not in message
        assert audio.hex()[:16] not in message


# --- compression -----------------------------------------------------------

def test_the_provider_is_asked_for_plain_bytes():
    # The SDKs ask for gzip. The relay forwards bodies untouched, so a
    # compressed reply would reach the app as unreadable bytes.
    relay, forward = make_relay()
    request = cleanup_request()
    request.headers["accept-encoding"] = "gzip, deflate"
    relay.handle(request)
    sent = {k.lower() for k in forward.calls[0]["headers"]}
    assert "accept-encoding" not in sent


class CompressingForward(FakeForward):
    """A provider that compresses the reply regardless."""

    def __call__(self, method, url, headers, body):
        super().__call__(method, url, headers, body)
        return (
            200,
            {"content-type": "application/json", "content-encoding": "gzip"},
            b"\x1f\x8b compressed",
        )


def test_a_compressed_reply_still_says_it_is_compressed():
    # Without the header the client reads gzip bytes as text and the
    # cleanup falls back to the raw transcript.
    relay, _ = make_relay(forward=CompressingForward())
    reply = relay.handle(cleanup_request())
    assert reply.headers["content-encoding"] == "gzip"


def test_the_usage_line_is_emitted_at_a_level_lambda_keeps(caplog):
    relay, _ = make_relay()
    with caplog.at_level(logging.INFO, logger="mirabel_relay.relay"):
        relay.handle(cleanup_request())
    assert any(record.levelno >= logging.INFO for record in caplog.records)


class FakeSignin:
    """Stand in for the Google verifier, answering a fixed email or None."""

    def __init__(self, email=None):
        self.email = email
        self.seen = []

    def verify(self, credential):
        self.seen.append(credential)
        return self.email


A_JWT = "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6InByaXlhIn0.c2lnbmF0dXJl"


def make_signin_relay(email=None):
    forward = FakeForward()
    relay = Relay(
        tokens=TOKENS,
        anthropic_key=REAL_KEY,
        openai_key=REAL_OPENAI_KEY,
        forward=forward,
        clock=lambda: 0.0,
        signin=FakeSignin(email),
    )
    return relay, forward


def test_a_verified_sign_in_opens_the_door():
    relay, forward = make_signin_relay(email="priya@mirabeltech.com")
    reply = relay.handle(cleanup_request(token=A_JWT))
    assert reply.status == 200
    assert len(forward.calls) == 1


def test_the_usage_line_names_the_verified_account(caplog):
    relay, _ = make_signin_relay(email="priya@mirabeltech.com")
    with caplog.at_level(logging.INFO):
        relay.handle(cleanup_request(token=A_JWT))
    lines = [r.message for r in caplog.records if r.message.startswith("usage")]
    assert any("priya@mirabeltech.com" in line for line in lines)


def test_a_refused_sign_in_is_401_and_never_tries_the_token_list():
    """The two doors stay separate: a bad JWT must not be retried as a
    token, and no provider call may happen."""
    relay, forward = make_signin_relay(email=None)
    reply = relay.handle(cleanup_request(token=A_JWT))
    assert reply.status == 401
    assert forward.calls == []


def test_static_tokens_still_work_beside_sign_in():
    relay, forward = make_signin_relay(email="priya@mirabeltech.com")
    reply = relay.handle(cleanup_request(token="tommy-token-1"))
    assert reply.status == 200
    assert relay.signin.seen == []


def test_a_jwt_shaped_credential_without_sign_in_configured_is_refused():
    relay, forward = make_relay()
    reply = relay.handle(cleanup_request(token=A_JWT))
    assert reply.status == 401
    assert forward.calls == []
