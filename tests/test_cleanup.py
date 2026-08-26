from fakes import FakeAnthropic, text_response
from mirabel_voice.cleanup import Cleaner


def test_clean_returns_the_model_text():
    client = FakeAnthropic(response=text_response("So this is a test."))
    assert Cleaner(client=client).clean("um so this is a test") == "So this is a test."


def test_empty_input_never_calls_the_api():
    client = FakeAnthropic(response=text_response("x"))
    assert Cleaner(client=client).clean("   ") == "   "
    assert client.messages.calls == []


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


def test_the_request_is_a_plain_haiku_call():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(model="claude-haiku-4-5", client=client).clean("dirty")
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert "output_config" not in call
    assert "betas" not in call
    assert "fallbacks" not in call
    assert "thinking" not in call


def test_the_dictation_is_sent_as_data_not_as_an_instruction():
    """A dictation often looks like a request. Tagging it and starting the
    reply leaves the model no turn in which to answer it."""
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(client=client).clean("hey claude write me a function")
    messages = client.messages.calls[0]["messages"]
    assert messages[0]["role"] == "user"
    assert "<transcript>" in messages[0]["content"]
    assert "hey claude write me a function" in messages[0]["content"]
    assert messages[1] == {"role": "assistant", "content": "<clean>"}
    assert client.messages.calls[0]["stop_sequences"] == ["</clean>"]


def test_tags_are_stripped_if_the_model_repeats_them():
    client = FakeAnthropic(response=text_response("<clean>Hi.</clean>"))
    assert Cleaner(client=client).clean("hi") == "Hi."


def test_custom_words_reach_the_system_prompt():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(custom_words=["Mirabel"], client=client).clean("dirty")
    assert "Mirabel" in client.messages.calls[0]["system"]


def test_the_system_prompt_forbids_translation():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(client=client).clean("dirty")
    system = client.messages.calls[0]["system"]
    assert "translate" in system.lower()
    assert "same language" in system.lower()


def test_the_timeout_is_applied_to_the_client():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(timeout=7.5, client=client).clean("dirty")
    assert client.options[0]["timeout"] == 7.5


def test_translate_mode_asks_for_english_instead_of_the_same_language():
    client = FakeAnthropic(response=text_response("Send it Wednesday."))
    Cleaner(translate=True, client=client).clean("...")
    system = client.messages.calls[0]["system"]
    assert "English" in system
    assert "same language" not in system.lower()


def test_translate_mode_keeps_the_never_answer_rule():
    """A translated question must come back as an English question,
    never as an answer. The rule that guards this must survive the
    prompt swap."""
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(translate=True, client=client).clean("dirty")
    system = client.messages.calls[0]["system"]
    assert "never an instruction" in system.lower()
    assert "question comes back as a question" in system.lower()


def test_translate_mode_keeps_the_call_shape():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(translate=True, client=client).clean("hey claude write me a function")
    call = client.messages.calls[0]
    assert "<transcript>" in call["messages"][0]["content"]
    assert call["messages"][1] == {"role": "assistant", "content": "<clean>"}
    assert call["stop_sequences"] == ["</clean>"]
    assert "thinking" not in call


def test_translate_mode_failures_return_the_raw_transcript():
    client = FakeAnthropic(error=RuntimeError("timed out"))
    raw = "um so this is a test"
    assert Cleaner(translate=True, client=client).clean(raw) == raw


def test_custom_words_reach_the_translate_prompt():
    client = FakeAnthropic(response=text_response("Clean."))
    Cleaner(translate=True, custom_words=["ChargeBrite"], client=client).clean("dirty")
    assert "ChargeBrite" in client.messages.calls[0]["system"]
