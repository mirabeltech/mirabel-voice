"""Tests for the app side of the Google sign-in.

Everything runs offline: the browser step, Google's token endpoint,
and DPAPI are all injected fakes. The relay's half of this contract
is tested in test_signin.py against real RS256 signatures; here the
subject is the flow - what gets stored, when a refresh happens, and
what "signed out" means.
"""

import base64
import json
import urllib.parse

import pytest

from mirabel_voice.signin import GoogleSignin, SigninError, SigninRefused

CLIENT_ID = "12345-mirabel.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-not-actually-a-secret"
NOW = 1_756_000_000.0


def id_token(email="priya@mirabeltech.com", exp=NOW + 3600):
    """A token shaped like Google's. The app never verifies it - the
    relay does - so an unsigned one is enough here."""
    claims = {"email": email, "exp": exp}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return "header." + payload.decode() + ".signature"


class FakeGoogle:
    """Google's token endpoint, answering from a script."""

    def __init__(self, refuse=None, fail=False):
        self.forms = []
        self.refuse = refuse
        self.fail = fail
        self.next_id_token = id_token()

    def __call__(self, url, form):
        self.forms.append(form)
        if self.fail:
            raise OSError("no route to Google")
        if self.refuse is not None:
            raise SigninRefused(self.refuse, "refused: " + self.refuse)
        answer = {"id_token": self.next_id_token}
        if form.get("grant_type") == "authorization_code":
            answer["refresh_token"] = "the-refresh-token"
        return answer


def fake_protect(data: bytes) -> bytes:
    return b"DPAPI!" + bytes(reversed(data))


def fake_unprotect(data: bytes) -> bytes:
    assert data.startswith(b"DPAPI!"), "the store was written unprotected"
    return bytes(reversed(data[len(b"DPAPI!"):]))


def fake_receive(auth_url, wait_seconds):
    fake_receive.seen = auth_url
    return "the-code", "http://localhost:12345"


def make_signin(tmp_path, google=None, now=NOW):
    google = google if google is not None else FakeGoogle()
    signin = GoogleSignin(
        CLIENT_ID,
        CLIENT_SECRET,
        store=tmp_path / "google_signin.bin",
        receive=fake_receive,
        post=google,
        protect=fake_protect,
        unprotect=fake_unprotect,
        now=lambda: now,
    )
    return signin, google


def test_signing_in_names_the_account(tmp_path):
    signin, _ = make_signin(tmp_path)
    assert signin.sign_in() == "priya@mirabeltech.com"
    assert signin.signed_in()


def test_the_exchange_carries_the_code_and_the_proof_of_possession(tmp_path):
    signin, google = make_signin(tmp_path)
    signin.sign_in()
    form = google.forms[0]
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "the-code"
    assert form["redirect_uri"] == "http://localhost:12345"
    assert form["code_verifier"]  # PKCE: the code alone must not be enough
    query = urllib.parse.parse_qs(urllib.parse.urlparse(fake_receive.seen).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]


def test_the_stored_file_is_protected_and_holds_no_plain_secret(tmp_path):
    signin, _ = make_signin(tmp_path)
    signin.sign_in()
    raw = (tmp_path / "google_signin.bin").read_bytes()
    assert raw.startswith(b"DPAPI!")
    assert b"the-refresh-token" not in raw


def test_a_fresh_token_is_answered_without_asking_google(tmp_path):
    signin, google = make_signin(tmp_path)
    signin.sign_in()
    exchanges = len(google.forms)
    assert signin.credential() == google.next_id_token
    assert len(google.forms) == exchanges  # no refresh happened


def test_a_dying_token_is_refreshed_before_it_expires(tmp_path):
    signin, google = make_signin(tmp_path)
    google.next_id_token = id_token(exp=NOW + 60)  # inside the margin
    signin.sign_in()
    google.next_id_token = id_token(exp=NOW + 3600)
    fresh = signin.credential()
    assert fresh == google.next_id_token
    assert google.forms[-1]["grant_type"] == "refresh_token"
    assert google.forms[-1]["refresh_token"] == "the-refresh-token"


def test_the_sign_in_survives_a_restart(tmp_path):
    first, _ = make_signin(tmp_path)
    first.sign_in()
    again, google = make_signin(tmp_path)
    assert again.signed_in()
    assert again.credential() == google.next_id_token
    assert google.forms[-1]["refresh_token"] == "the-refresh-token"
    assert again.email == "priya@mirabeltech.com"


def test_a_revoked_account_reads_as_signed_out(tmp_path):
    """invalid_grant is Google saying the person is gone. The stored
    sign-in is dropped, and credential() says sign in again."""
    signin, _ = make_signin(tmp_path)
    signin.sign_in()
    revoked, _ = make_signin(tmp_path, google=FakeGoogle(refuse="invalid_grant"))
    assert revoked.credential() is None
    assert not (tmp_path / "google_signin.bin").exists()


def test_being_offline_is_not_being_signed_out(tmp_path):
    signin, _ = make_signin(tmp_path)
    signin.sign_in()
    offline, _ = make_signin(tmp_path, google=FakeGoogle(fail=True))
    with pytest.raises(OSError):
        offline.credential()
    assert (tmp_path / "google_signin.bin").exists()


def test_no_stored_sign_in_means_none_not_an_error(tmp_path):
    signin, google = make_signin(tmp_path)
    assert not signin.signed_in()
    assert signin.credential() is None
    assert google.forms == []


def test_an_answer_without_a_refresh_token_is_refused(tmp_path):
    class Withholding(FakeGoogle):
        def __call__(self, url, form):
            return {"id_token": id_token()}

    signin, _ = make_signin(tmp_path, google=Withholding())
    with pytest.raises(SigninError):
        signin.sign_in()


def test_a_store_written_by_another_user_reads_as_signed_out(tmp_path):
    (tmp_path / "google_signin.bin").write_bytes(b"not dpapi at all")
    signin, _ = make_signin(tmp_path)
    assert not signin.signed_in()
    assert signin.credential() is None


def test_the_loopback_survives_a_browser_that_preconnects(monkeypatch):
    """Chrome opens a speculative connection that sends nothing. The
    loopback must serve the real redirect anyway, not sit blocked on
    the silent one until everything times out."""
    import socket
    import threading
    import urllib.parse
    import urllib.request

    from mirabel_voice import signin as signin_module

    held = []

    def browse(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        target = query["redirect_uri"][0]
        state = query["state"][0]

        def visit():
            # The speculative connection first: open, say nothing.
            address = urllib.parse.urlparse(target)
            silent = socket.create_connection((address.hostname, address.port))
            held.append(silent)  # keep it open across the real request
            # Then the real redirect.
            with urllib.request.urlopen(
                target + "?" + urllib.parse.urlencode(
                    {"code": "the-code", "state": state}
                ),
                timeout=30,
            ) as reply:
                assert b"Signed in" in reply.read()

        threading.Thread(target=visit, daemon=True).start()
        return True

    monkeypatch.setattr(signin_module.webbrowser, "open", browse)
    code, redirect = signin_module.receive_code("https://auth.example?x=1", 30)
    assert code == "the-code"
    assert redirect.startswith("http://localhost:")
    for connection in held:
        connection.close()


def test_the_loopback_ignores_a_code_with_the_wrong_state(monkeypatch):
    """A stray request to the port must not hand us somebody's code."""
    import urllib.parse
    import urllib.request

    from mirabel_voice import signin as signin_module

    def browse(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        target = query["redirect_uri"][0]
        state = query["state"][0]

        def visit():
            with urllib.request.urlopen(
                target + "?code=stray&state=wrong", timeout=30
            ):
                pass
            with urllib.request.urlopen(
                target + "?" + urllib.parse.urlencode(
                    {"code": "the-real-code", "state": state}
                ),
                timeout=30,
            ):
                pass

        import threading

        threading.Thread(target=visit, daemon=True).start()
        return True

    monkeypatch.setattr(signin_module.webbrowser, "open", browse)
    code, _ = signin_module.receive_code("https://auth.example?x=1", 30)
    assert code == "the-real-code"
