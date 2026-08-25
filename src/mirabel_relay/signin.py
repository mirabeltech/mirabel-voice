"""Google sign-in for the relay: prove who is calling without a token list.

The app signs the person in with their Mirabel Google account and sends
the resulting ID token where a relay token would otherwise go. This
module decides whether such a token is real: signed by Google, meant
for our OAuth client, current, and belonging to an account in the
Mirabel Workspace. What comes back is the verified email address, which
is what the usage log then names.

Google's signing keys are public and fetched from one well-known URL.
They are cached for the life of the container, the same way the
provider keys are, and refetched once when a token names a key we do
not hold - Google rolls these keys routinely, and a rollover must not
lock everyone out until the next cold start.

The signature check itself is RSASSA-PKCS1-v1_5 with SHA-256, done with
the standard library alone. Verification needs only modular
exponentiation with the public key and a byte comparison against the
expected padding - no private-key work, no library. This keeps the
deploy what it has always been: source files in a zip, nothing vendored,
nothing compiled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.request
from typing import Callable

GOOGLE_KEYS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Google has signed ID tokens as both of these over the years. Both are
# Google; accepting both is what their own verification guide says to do.
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

# A token that expired moments ago is a clock disagreement, not an
# intruder. Anything older is refused.
CLOCK_SKEW_SECONDS = 60

# How long after a fetch that still did not hold the asked-for key id
# before another unknown id may trigger a fetch. This is what keeps a
# stream of garbage tokens from turning the relay into a load test of
# Google's key endpoint, while a real key rollover - where the fetch
# finds the new key - is never made to wait.
REFETCH_COOLDOWN_SECONDS = 60

# The DER prefix that EMSA-PKCS1-v1_5 places before a SHA-256 digest.
# Fixed bytes from RFC 8017, spelled out rather than computed.
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def looks_like_jwt(credential: str) -> bool:
    """True when a credential has a JWT's three-part shape.

    Relay tokens come from token_urlsafe and never contain a dot, so
    this test cleanly separates the two kinds of credential.
    """
    return credential.count(".") == 2


def fetch_google_keys() -> dict:
    """Fetch Google's current signing keys. The tests replace this."""
    with urllib.request.urlopen(GOOGLE_KEYS_URL, timeout=10) as reply:
        return json.loads(reply.read())


class GoogleSignin:
    """Decide whether a presented ID token is a current Mirabel sign-in.

    Args:
        client_id: Our OAuth client's id. A token minted for any other
            audience is refused, however valid it is elsewhere.
        domain: The Mirabel Workspace primary domain. The Internal
            consent screen already keeps outside accounts from signing
            in at all; checking the domain again here means the relay
            stays closed even if that screen's setting ever drifts.
        fetch_keys: Returns Google's JWKS document. Injected so every
            test runs offline - this module's one testing seam.
        now: Returns seconds since the epoch, for the expiry check.
            Injected for the tests.
    """

    def __init__(
        self,
        client_id: str,
        domain: str,
        fetch_keys: Callable[[], dict] = fetch_google_keys,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.domain = domain
        self.fetch_keys = fetch_keys
        self.now = now
        self._keys: dict[str, tuple[int, int]] | None = None
        self._missed_at: float | None = None

    def verify(self, credential: str) -> str | None:
        """Return the verified account's email address, or None to refuse.

        Every way a token can be wrong ends in the same None, on
        purpose: the caller gets one 401, and the reasons stay here.
        """
        parsed = _parse(credential)
        if parsed is None:
            return None
        header, claims, signature, signing_input = parsed
        if header.get("alg") != "RS256":
            return None
        key = self._key_for(header.get("kid"))
        if key is None:
            return None
        if not _rs256_verify(key[0], key[1], signature, signing_input):
            return None
        return self._checked_email(claims)

    def _checked_email(self, claims: dict) -> str | None:
        """The claim checks: right issuer, right audience, current, ours."""
        if claims.get("iss") not in GOOGLE_ISSUERS:
            return None
        if claims.get("aud") != self.client_id:
            return None
        expiry = claims.get("exp")
        if not isinstance(expiry, (int, float)):
            return None
        if expiry + CLOCK_SKEW_SECONDS <= self.now():
            return None
        if claims.get("hd") != self.domain:
            return None
        if claims.get("email_verified") is not True:
            return None
        email = claims.get("email")
        return email if isinstance(email, str) and email else None

    def _key_for(self, kid) -> tuple[int, int] | None:
        """Return the (modulus, exponent) for one key id.

        An unknown id triggers one refetch, because Google rolls keys.
        A fetch that fails refuses the request rather than raising: the
        next request tries again, and the static-token path is never
        affected.
        """
        if not isinstance(kid, str) or not kid:
            return None
        if self._keys is not None and kid in self._keys:
            return self._keys[kid]
        if self._missed_at is not None:
            if self.now() - self._missed_at < REFETCH_COOLDOWN_SECONDS:
                return None
        try:
            document = self.fetch_keys()
        except Exception:  # noqa: BLE001 - Google being unreachable is a refusal, not a crash
            return None
        self._keys = _parse_jwks(document)
        key = self._keys.get(kid)
        if key is None:
            self._missed_at = self.now()
        return key


def _parse(credential: str):
    """Split a JWT into its parts, or None for anything malformed."""
    pieces = credential.split(".")
    if len(pieces) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(pieces[0]))
        claims = json.loads(_b64url_decode(pieces[1]))
        signature = _b64url_decode(pieces[2])
    except Exception:  # noqa: BLE001 - malformed input is a refusal, not an error
        return None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        return None
    signing_input = (pieces[0] + "." + pieces[1]).encode("ascii")
    return header, claims, signature, signing_input


def _b64url_decode(text: str) -> bytes:
    """Decode base64url with the padding JWTs leave off."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _parse_jwks(document: dict) -> dict[str, tuple[int, int]]:
    """Turn a JWKS document into key id -> (modulus, exponent)."""
    keys: dict[str, tuple[int, int]] = {}
    for entry in document.get("keys", []):
        if not isinstance(entry, dict) or entry.get("kty") != "RSA":
            continue
        kid, n, e = entry.get("kid"), entry.get("n"), entry.get("e")
        if not all(isinstance(value, str) and value for value in (kid, n, e)):
            continue
        try:
            keys[kid] = (
                int.from_bytes(_b64url_decode(n), "big"),
                int.from_bytes(_b64url_decode(e), "big"),
            )
        except Exception:  # noqa: BLE001 - one bad entry must not drop the others
            continue
    return keys


def _rs256_verify(n: int, e: int, signature: bytes, message: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 verification with SHA-256, per RFC 8017.

    The signature is raised to the public exponent and the result must
    equal, byte for byte, the one padding the standard allows for this
    digest. Building the expected bytes and comparing whole is the
    verification method the RFC itself recommends, and it leaves no
    room for the padding-parsing mistakes that made forgeries against
    lenient verifiers possible.
    """
    length = (n.bit_length() + 7) // 8
    if len(signature) != length:
        return False
    decrypted = pow(int.from_bytes(signature, "big"), e, n)
    recovered = decrypted.to_bytes(length, "big")
    digest_info = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    padding = length - len(digest_info) - 3
    if padding < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding + b"\x00" + digest_info
    return hmac.compare_digest(recovered, expected)
