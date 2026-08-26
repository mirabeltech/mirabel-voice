"""The app side of the relay.

Relay mode must be configuration and nothing else: the same Transcriber,
the same Cleaner, the same warm-up, pointed somewhere else. These tests
watch for a fork appearing.
"""

import time
from types import SimpleNamespace

from fakes import FakeAnthropic, FakeOpenAI, text_response
from mirabel_voice.app import VoiceApp
from mirabel_voice.cleanup import Cleaner
from mirabel_voice.config import Config, relay_base
from mirabel_voice.keycheck import check_relay
from mirabel_voice.transcribe import Transcriber
from test_app import CapturingInjector, FakeRecorder, loud_recording

RELAY = "https://relay.example.on.aws"
TOKEN = "a-token-nobody-typed"


def wait_for(condition, seconds=5.0):
    """Wait for a background thread to do its work."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- settings --------------------------------------------------------------

def test_relay_settings_are_off_by_default():
    config = Config()
    assert config.relay_url is None
    assert config.relay_token is None


def test_relay_settings_survive_a_round_trip(tmp_path):
    target = tmp_path / "config.json"
    Config(relay_url=RELAY, relay_token=TOKEN).save(target)
    config = Config.load(target)
    assert config.relay_url == RELAY
    assert config.relay_token == TOKEN


def test_the_address_loses_a_trailing_slash():
    # The Function URL that AWS prints ends with one.
    assert relay_base(RELAY + "/") == RELAY


# --- the two clients -------------------------------------------------------

def test_the_transcriber_points_at_the_relay():
    transcriber = Transcriber(relay_url=RELAY + "/", relay_token=TOKEN)
    # The SDK adds its own paths after /v1, which is where the relay listens.
    assert str(transcriber.client.base_url).rstrip("/") == RELAY + "/v1"
    assert transcriber.client.api_key == TOKEN


def test_the_cleaner_points_at_the_relay():
    cleaner = Cleaner(relay_url=RELAY + "/", relay_token=TOKEN)
    # The Anthropic SDK writes /v1/messages itself.
    assert str(cleaner.client.base_url).rstrip("/") == RELAY
    assert cleaner.client.api_key == TOKEN


def test_an_injected_client_still_wins():
    # The seam the offline tests fake at must not move in relay mode.
    fake = FakeOpenAI()
    transcriber = Transcriber(client=fake, relay_url=RELAY, relay_token=TOKEN)
    assert transcriber.client is fake


# --- the app ---------------------------------------------------------------

class PingingOpenAI(FakeOpenAI):
    """A fake that records the warm-up call as well as the real one."""

    def __init__(self):
        super().__init__()
        self.warmed = []
        self.models = SimpleNamespace(list=lambda: self.warmed.append("models.list"))


class PingingAnthropic(FakeAnthropic):
    def __init__(self):
        super().__init__(response=text_response("Hello."))
        self.warmed = []
        self.messages.count_tokens = lambda **kwargs: self.warmed.append(kwargs)


def relay_app(**clients):
    config = Config(
        relay_url=RELAY,
        relay_token=TOKEN,
        play_sounds=False,
    )
    app = VoiceApp(
        config=config,
        recorder=FakeRecorder(loud_recording()),
        injector=CapturingInjector(),
        **clients,
    )
    app._focus = lambda: 111
    return app


def test_the_app_hands_the_relay_settings_to_both_clients():
    app = relay_app()
    assert (app.transcriber.relay_url, app.transcriber.relay_token) == (RELAY, TOKEN)
    assert (app.cleaner.relay_url, app.cleaner.relay_token) == (RELAY, TOKEN)


def test_direct_mode_is_unchanged_when_no_relay_is_set():
    config = Config(play_sounds=False)
    app = VoiceApp(
        config=config,
        recorder=FakeRecorder(loud_recording()),
        injector=CapturingInjector(),
    )
    assert app.transcriber.relay_url is None
    assert app.cleaner.relay_url is None


def test_the_warm_up_pings_go_through_the_relay_clients():
    # Recording starts, and both connections are opened while the person
    # is still speaking. In relay mode that is what warms the Lambda.
    openai_client = PingingOpenAI()
    anthropic_client = PingingAnthropic()
    app = relay_app(
        transcriber=Transcriber(client=openai_client),
        cleaner=Cleaner(client=anthropic_client),
    )
    app.start_recording()
    assert wait_for(lambda: openai_client.warmed and anthropic_client.warmed)
    app.stop_recording()
    if app._worker is not None:
        app._worker.join(timeout=5)


# --- the setup check -------------------------------------------------------

class StubCleaner:
    """Stands in for the Cleaner that check_relay builds."""

    last = None

    def __init__(self, error=None, **kwargs):
        self.kwargs = kwargs
        StubCleaner.last = self
        self.client = SimpleNamespace(
            messages=SimpleNamespace(create=self._create)
        )
        self._error = error

    def _create(self, **kwargs):
        if self._error is not None:
            raise self._error
        return text_response("hi")


def test_the_check_accepts_a_working_relay(monkeypatch):
    import mirabel_voice.cleanup as cleanup_module

    monkeypatch.setattr(cleanup_module, "Cleaner", StubCleaner)
    ok, message = check_relay(Config(relay_url=RELAY, relay_token=TOKEN))
    assert ok
    assert message == "The relay works."
    assert StubCleaner.last.kwargs["relay_url"] == RELAY
    assert StubCleaner.last.kwargs["relay_token"] == TOKEN


def test_the_check_refuses_a_token_the_relay_does_not_know(monkeypatch):
    import mirabel_voice.cleanup as cleanup_module

    def refused(**kwargs):
        return StubCleaner(error=RuntimeError("401 The token is not recognized."), **kwargs)

    monkeypatch.setattr(cleanup_module, "Cleaner", refused)
    ok, message = check_relay(Config(relay_url=RELAY, relay_token="wrong"))
    assert not ok
    assert "401" in message


def test_the_check_says_so_when_the_token_is_missing():
    ok, message = check_relay(Config(relay_url=RELAY))
    assert not ok
    assert "token" in message


# --- starting up -----------------------------------------------------------

def test_a_relay_machine_starts_with_no_provider_keys(monkeypatch):
    from mirabel_voice.__main__ import _check_keys

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _check_keys(Config(relay_url=RELAY, relay_token=TOKEN)) == []


def test_a_relay_machine_with_no_token_is_told_what_to_do(monkeypatch):
    from mirabel_voice.__main__ import _check_keys

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    problems = _check_keys(Config(relay_url=RELAY))
    assert len(problems) == 1
    assert "token" in problems[0]


def test_a_direct_machine_still_needs_its_keys(monkeypatch):
    from mirabel_voice.__main__ import _check_keys

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    problems = _check_keys(Config())
    assert any("OPENAI_API_KEY" in p for p in problems)


# --- the Google sign-in as the credential ----------------------------------

class RotatingCredential:
    """Stands in for GoogleSignin.credential: a token that changes."""

    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.asked = 0

    def __call__(self):
        self.asked += 1
        return self.tokens.pop(0) if len(self.tokens) > 1 else self.tokens[0]


def test_the_transcriber_asks_for_a_fresh_credential_each_call():
    credential = RotatingCredential(["token-one", "token-two"])
    fake = FakeOpenAI()
    transcriber = Transcriber(
        client=fake, relay_url=RELAY, relay_token=credential
    )
    transcriber._for_this_call()
    assert fake.options[-1]["api_key"] == "token-one"
    transcriber._for_this_call()
    assert fake.options[-1]["api_key"] == "token-two"


def test_a_working_sign_in_reaches_the_cleaner_call():
    fake = FakeAnthropic(response=text_response("Tidied."))
    cleaner = Cleaner(
        client=fake, relay_url=RELAY, relay_token=lambda: "an-id-token"
    )
    assert cleaner.clean("um the words") == "Tidied."
    assert fake.options[-1]["api_key"] == "an-id-token"


def test_a_signed_out_transcriber_says_how_to_repair_it():
    from mirabel_voice.transcribe import TranscriptionError

    transcriber = Transcriber(
        client=FakeOpenAI(), relay_url=RELAY, relay_token=lambda: None
    )
    try:
        transcriber._for_this_call()
        raise AssertionError("a signed-out call must be refused")
    except TranscriptionError as told:
        assert "Sign in with Google" in str(told)


def test_a_signed_out_cleaner_returns_the_words_untouched():
    cleaner = Cleaner(
        client=FakeAnthropic(response=text_response("Tidied.")),
        relay_url=RELAY,
        relay_token=lambda: None,
    )
    assert cleaner.clean("um the words") == "um the words"


def test_a_refresh_failure_never_loses_the_transcript():
    def unreachable():
        raise OSError("no route to Google")

    cleaner = Cleaner(
        client=FakeAnthropic(response=text_response("Tidied.")),
        relay_url=RELAY,
        relay_token=unreachable,
    )
    assert cleaner.clean("um the words") == "um the words"


def test_the_app_prefers_the_sign_in_over_a_stored_token():
    class FakeSignin:
        def credential(self):
            return "an-id-token"

    config = Config(
        relay_url=RELAY,
        relay_token=TOKEN,
        google_client_id="12345-mirabel.apps",
        google_client_secret="GOCSPX-x",
        play_sounds=False,
    )
    app = VoiceApp(
        config=config,
        recorder=FakeRecorder(loud_recording()),
        injector=CapturingInjector(),
        signin=FakeSignin(),
    )
    assert callable(app.transcriber.relay_token)
    assert app.transcriber.relay_token() == "an-id-token"
    assert app.cleaner.relay_token() == "an-id-token"


def test_without_the_google_fields_the_token_still_rules():
    app = relay_app()
    assert app.signin is None
    assert app.transcriber.relay_token == TOKEN


def test_a_google_machine_starts_with_no_token_at_all(monkeypatch):
    from mirabel_voice.__main__ import _check_keys

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = Config(
        relay_url=RELAY,
        google_client_id="12345-mirabel.apps",
        google_client_secret="GOCSPX-x",
    )
    assert _check_keys(config) == []
