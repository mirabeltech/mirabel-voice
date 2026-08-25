"""Tests for the Google sign-in verifier.

Everything runs offline. The tests hold their own RSA key pair and
sign real RS256 tokens with it; the JWKS fetch is a fake serving that
key as Google would. The private half below signs test tokens and
nothing else - it protects nothing and appears in no other place.
"""

import base64
import hashlib
import json

from mirabel_relay.signin import GoogleSignin, looks_like_jwt

CLIENT_ID = "12345-mirabel.apps.googleusercontent.com"
DOMAIN = "mirabeltech.com"
NOW = 1_756_000_000.0

TEST_N = int(
    "a648fa2db26f505def07d1f8c318a29a05dd87e1eeb607ef2a277a43ff948a2f"
    "e57713effc69b7aeb9f7e575083b1a53e83b0883428f3fe3df7d3c9b5c9fc209"
    "d2bba4a06f3ed3ff859933b9fda5211cb486fdfd59a1262150ab839f2b454d35"
    "08ae7d23844197b5b6e080b5d4dc3b80461f489a3bfb5e1ee89a0a67a1c0506f"
    "ab1fc27cdc639da1957504bc352d804aa9e88e78f06fda5208e4043677db4b68"
    "2706abc54b0aea71947403dd062621ce081d11cf346ff32531755b891dac0d47"
    "5271861a7e33ddd63dd8f9e8f6961ea36cba98a4af681366c61533b8bac31cd1"
    "72503228bc6a6029910c648478e5d15a324616befe76c5e85a60d690d25e6979",
    16,
)
TEST_E = 0x10001
TEST_D = int(
    "16816e0add499f90f71711de1f59a8383c6efd4320f1d6251289814ccebca5ef"
    "51994a4382e034121bed674aedb04221f51e784a7ba9b3b5fdbb8f865f84e7d8"
    "38835906b5c7c51da25157e4e6658113c78335c1226e6320c3305382297319be"
    "01cccbf710a1680d1a114c9a4f92f722a75af8929767b01772d7d66cac41c121"
    "0426442fb8645f5b64eeb94b1fc2218695c58665511d13176e4f79ace2a51a76"
    "c9077bd833d2fc38a5e7979de54dd30b01c1074d617574d7dc3f1402567bef7d"
    "fefca5f32aaf5810c8009915eb27d459b7a96289f9588924a354def618f38f7d"
    "1e257d07a5a8477aea8856b374a7cca38f195ff289d48de8117eadd4acf33ad9",
    16,
)

DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_b64url(value: int) -> str:
    return _b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def sign_token(claims: dict, kid: str = "key-1", alg: str = "RS256") -> str:
    """Sign one token with the test key, exactly as Google would."""
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    signing_input = _b64url(json.dumps(header).encode()) + "." + _b64url(
        json.dumps(claims).encode()
    )
    digest_info = DIGEST_INFO + hashlib.sha256(signing_input.encode()).digest()
    length = (TEST_N.bit_length() + 7) // 8
    padding = b"\xff" * (length - len(digest_info) - 3)
    message = b"\x00\x01" + padding + b"\x00" + digest_info
    signature = pow(int.from_bytes(message, "big"), TEST_D, TEST_N)
    return signing_input + "." + _b64url(signature.to_bytes(length, "big"))


def claims(**overrides) -> dict:
    """A valid set of claims; tests break one thing at a time."""
    good = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": NOW + 3600,
        "hd": DOMAIN,
        "email": "priya@mirabeltech.com",
        "email_verified": True,
    }
    good.update(overrides)
    return {k: v for k, v in good.items() if v is not None}


class FakeJwks:
    """Serve the test key as Google's endpoint would, counting fetches."""

    def __init__(self, kids=("key-1",), fail=False):
        self.kids = list(kids)
        self.fail = fail
        self.fetches = 0

    def __call__(self):
        self.fetches += 1
        if self.fail:
            raise OSError("no route to Google")
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "alg": "RS256",
                    "kid": kid,
                    "n": _int_b64url(TEST_N),
                    "e": _int_b64url(TEST_E),
                }
                for kid in self.kids
            ]
        }


def make_signin(jwks=None, now=NOW):
    jwks = jwks if jwks is not None else FakeJwks()
    return GoogleSignin(CLIENT_ID, DOMAIN, fetch_keys=jwks, now=lambda: now), jwks


def test_a_valid_sign_in_names_the_account():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims())) == "priya@mirabeltech.com"


def test_a_relay_token_does_not_look_like_a_jwt():
    assert not looks_like_jwt("wc39mNvyBIhwSewgtDlSBGVMhSaXfe-t")
    assert looks_like_jwt("aa.bb.cc")


def test_a_token_for_another_client_is_refused():
    signin, _ = make_signin()
    stray = claims(aud="other-app.apps.googleusercontent.com")
    assert signin.verify(sign_token(stray)) is None


def test_a_token_from_another_issuer_is_refused():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(iss="https://evil.example"))) is None


def test_the_bare_google_issuer_is_accepted():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(iss="accounts.google.com"))) is not None


def test_an_expired_token_is_refused():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(exp=NOW - 120))) is None


def test_a_token_just_past_expiry_is_a_clock_disagreement_not_a_refusal():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(exp=NOW - 30))) is not None


def test_an_account_outside_the_workspace_is_refused():
    """A personal Gmail account has no hd claim at all."""
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(hd=None))) is None
    assert signin.verify(sign_token(claims(hd="gmail.com"))) is None


def test_an_unverified_email_is_refused():
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(email_verified=False))) is None


def test_a_tampered_payload_fails_the_signature():
    signin, _ = make_signin()
    token = sign_token(claims())
    head, payload, signature = token.split(".")
    forged = claims(email="attacker@mirabeltech.com")
    swapped = head + "." + _b64url(json.dumps(forged).encode()) + "." + signature
    assert signin.verify(swapped) is None


def test_a_token_signed_by_the_wrong_key_is_refused():
    """Right shape, right claims, but not Google's signature."""
    signin, _ = make_signin()
    token = sign_token(claims())
    head, payload, signature = token.split(".")
    hollow = head + "." + payload + "." + _b64url(b"\x01" * 256)
    assert signin.verify(hollow) is None


def test_only_rs256_is_accepted():
    """"alg": "none" and friends must never reach the claim checks."""
    signin, _ = make_signin()
    assert signin.verify(sign_token(claims(), alg="none")) is None
    assert signin.verify(sign_token(claims(), alg="HS256")) is None


def test_garbage_is_refused_not_crashed():
    signin, _ = make_signin()
    for junk in ("aa.bb.cc", "..", "a.b.c.d".rsplit(".", 1)[0], "\x00.\x00.\x00"):
        assert signin.verify(junk) is None


def test_a_rolled_key_triggers_one_refetch():
    """Google rotates keys; the second fetch finds the new one."""
    jwks = FakeJwks(kids=("key-1",))
    signin, _ = make_signin(jwks=jwks)
    assert signin.verify(sign_token(claims())) is not None
    jwks.kids = ["key-1", "key-2"]
    assert signin.verify(sign_token(claims(), kid="key-2")) is not None
    assert jwks.fetches == 2


def test_unknown_keys_cannot_stampede_the_key_endpoint():
    """A stream of garbage kids gets one refetch per cooldown, not one each."""
    jwks = FakeJwks()
    signin, _ = make_signin(jwks=jwks)
    for attempt in range(5):
        assert signin.verify(sign_token(claims(), kid=f"unknown-{attempt}")) is None
    assert jwks.fetches == 1


def test_google_being_unreachable_is_a_refusal_not_a_crash():
    signin, _ = make_signin(jwks=FakeJwks(fail=True))
    assert signin.verify(sign_token(claims())) is None


def test_the_next_request_retries_after_a_failed_fetch():
    jwks = FakeJwks(fail=True)
    signin, _ = make_signin(jwks=jwks)
    assert signin.verify(sign_token(claims())) is None
    jwks.fail = False
    assert signin.verify(sign_token(claims())) is not None


def test_every_org_domain_is_welcome_and_others_are_not():
    """One Workspace can answer to several domains, and the hd claim
    carries the account's own - both must pass, outsiders must not."""
    signin = GoogleSignin(
        CLIENT_ID,
        "mirabeltech.com, maghub.com",
        fetch_keys=FakeJwks(),
        now=lambda: NOW,
    )
    assert signin.verify(sign_token(claims())) is not None
    assert signin.verify(sign_token(claims(hd="maghub.com"))) is not None
    assert signin.verify(sign_token(claims(hd="gmail.com"))) is None
