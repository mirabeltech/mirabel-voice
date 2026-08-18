from fakes import FakeAnthropic, text_response
from mirabel_voice.cleanup import Cleaner


class BadRequest(Exception):
    status_code = 400


def test_clean_returns_the_model_text():
    client = FakeAnthropic(response=text_response("So this is a test."))
    assert Cleaner(client=client).clean("um so this is a test") == "So this is a test."


def test_empty_input_never_calls_the_api():
    client = FakeAnthropic(response=text_response("x"))
    assert Cleaner(client=client).clean("   ") == "   "
    assert client.beta_messages.calls == []


def test_an_api_failure_returns_the_raw_transcript():
    client = FakeAnthropic(error=RuntimeError("timed out"))
    raw = "um so this is a test"
    assert Cleaner(client=client).clean(raw) == raw


def test_a_refusal_returns_the_raw_transcript():
    client = FakeAnthropic(response=text_response("", stop_reason="refusal"))
    raw = "um so this is a test"
    assert Cleaner(client=client).clean(raw) == raw


def test_an_empty_reply_returns_the_raw_transcript():
    client = FakeAnthropic(response=text_response("   "))
    raw = "um so this is a test"
    assert Cleaner(client=client).clean(raw) == raw


def test_the_request_uses_the_model_and_the_effort_from_the_settings():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(model="claude-opus-5", effort="low", client=client).clean("dirty")
    call = client.beta_messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["messages"] == [{"role": "user", "content": "dirty"}]


def test_custom_words_reach_the_system_prompt():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(custom_words=["Mirabel"], client=client).clean("dirty")
    assert "Mirabel" in client.beta_messages.calls[0]["system"]


def test_a_rejected_beta_falls_back_to_the_plain_endpoint():
    client = FakeAnthropic(response=text_response("Clean."), beta_error=BadRequest())
    client.messages.error = None
    cleaner = Cleaner(client=client)
    assert cleaner.clean("dirty") == "Clean."
    assert len(client.messages.calls) == 1
    assert cleaner._use_fallbacks is False


def test_the_timeout_is_applied_to_the_client():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(timeout=7.5, client=client).clean("dirty")
    assert client.options[0]["timeout"] == 7.5
