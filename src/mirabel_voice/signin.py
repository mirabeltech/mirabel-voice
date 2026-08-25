"""Sign in with the Mirabel Google account, instead of holding a token.

The first run opens the browser on the Google sign-in page. Google
hands back a short code through a loopback address on this machine,
the code is exchanged for tokens, and from then on the app holds one
refresh token and asks Google for a fresh ID token whenever the
current one nears its hour. The ID token is what the relay verifies;
see mirabel_relay/signin.py for the other half.

The refresh token is the one durable secret this app has ever stored,
so it is protected with DPAPI - Windows encrypts it to this user on
this machine, and a copied file is unreadable anywhere else. The
client id and client secret are not secrets: Google documents that an
installed app cannot keep a secret, and the pair grants nothing
without a person signing in.

Leaving the company signs a person out on its own: a disabled Google
account cannot refresh, and the app falls back to asking for a
sign-in that can no longer succeed.

The flow is the standard library end to end, proved against the live
relay before this module existed. The one seam is `receive`: the
browser-and-loopback step, injected so every test runs offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from .config import config_dir

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "openid email profile"

# Ask for a new ID token this long before the current one dies, so a
# dictation started at minute 59 is never signed by a corpse.
REFRESH_MARGIN_SECONDS = 120

# How long the browser page may sit open before a sign-in gives up.
SIGN_IN_WAIT_SECONDS = 300

STORE_NAME = "google_signin.bin"


class SigninError(RuntimeError):
    """The sign-in did not complete. The message says what happened."""


class SigninRefused(SigninError):
    """Google answered the token request with a refusal, by name."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def post_form(url: str, form: dict) -> dict:
    """POST one form to Google and return the JSON reply.

    A 4xx carries a named OAuth error - invalid_grant means the refresh
    token is dead, which is a fact, not a failure. Network trouble
    raises as itself, so the caller can tell "signed out" from
    "offline".
    """
    body = urllib.parse.urlencode(form).encode("ascii")
    call = urllib.request.Request(url, data=body, method="POST")
    call.add_header("content-type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(call, timeout=30) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as refusal:
        detail = refusal.read()
        try:
            parsed = json.loads(detail)
            code = parsed.get("error", "http-" + str(refusal.code))
            message = parsed.get("error_description", "") or code
        except Exception:  # noqa: BLE001 - an unreadable refusal still refuses
            code = "http-" + str(refusal.code)
            message = detail.decode("utf-8", "replace")[:200]
        raise SigninRefused(code, message) from refusal


def dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes to this Windows user, with DPAPI."""
    return _dpapi(data, protect=True)


def dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt what dpapi_protect stored. Raises for anyone else's file."""
    return _dpapi(data, protect=False)


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    import ctypes.wintypes

    class Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    incoming = Blob(len(data), ctypes.cast(data, ctypes.POINTER(ctypes.c_char)))
    outgoing = Blob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN: never show a prompt
    call = (
        ctypes.windll.crypt32.CryptProtectData
        if protect
        else ctypes.windll.crypt32.CryptUnprotectData
    )
    if not call(
        ctypes.byref(incoming), None, None, None, None, flags, ctypes.byref(outgoing)
    ):
        raise OSError("DPAPI refused the data.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _claims_of(id_token: str) -> dict:
    """Read an ID token's claims without verifying them.

    The app never trusts these for security - the relay does the real
    verification. Here they answer two harmless questions: when does
    this token expire, and what address do we greet the person by.
    """
    try:
        payload = id_token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
        return claims if isinstance(claims, dict) else {}
    except Exception:  # noqa: BLE001 - unreadable claims read as empty
        return {}


def receive_code(auth_url: str, wait_seconds: float) -> tuple[str, str]:
    """Run the browser half of the flow: open the page, catch the redirect.

    Returns the authorization code and the exact redirect address it
    arrived on, which the token exchange must repeat. The state value in
    the URL is checked, so a stray request to the loopback port cannot
    hand us somebody else's code.
    """
    import http.server

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    redirect = f"http://localhost:{port}"
    state = _b64url(secrets.token_bytes(16))
    landed: dict = {}
    done = threading.Event()

    class Catch(http.server.BaseHTTPRequestHandler):
        # A browser opens speculative connections that send nothing.
        # Give each one this long to speak, then drop it.
        timeout = 10

        def do_GET(self):  # noqa: N802 - the base class names it
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            arrived = {k: v[0] for k, v in query.items()}
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            if arrived.get("state") != state:
                self.wfile.write(b"<h2>That sign-in did not match. Try again.</h2>")
                return
            landed.update(arrived)
            done.set()
            if "code" in arrived:
                self.wfile.write(
                    b"<h2>Signed in. You can close this tab - "
                    b"Mirabel Voice is ready.</h2>"
                )
            else:
                self.wfile.write(b"<h2>The sign-in was not completed.</h2>")

        def log_message(self, *args):  # noqa: ANN002 - the base class's shape
            pass

    # One thread per connection. A single-threaded server can accept a
    # browser's silent speculative connection first and sit on it while
    # the real sign-in waits in the backlog until everything times out.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Catch)
    server.daemon_threads = True
    server.timeout = 1.0

    def serve() -> None:
        deadline = time.monotonic() + wait_seconds
        while not done.is_set() and time.monotonic() < deadline:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    webbrowser.open(auth_url + "&" + urllib.parse.urlencode({"state": state,
                                                             "redirect_uri": redirect}))
    done.wait(timeout=wait_seconds)
    thread.join(timeout=2.0)
    server.server_close()

    if landed.get("error"):
        raise SigninError(f"Google refused the sign-in: {landed['error']}")
    if "code" not in landed:
        raise SigninError(
            "The sign-in page was not completed. Start it again from the "
            "Mirabel Voice icon near the clock."
        )
    return landed["code"], redirect


class GoogleSignin:
    """Hold one person's sign-in and answer with a current ID token.

    Args:
        client_id: Our OAuth client's id. Ships in the zip; not a secret.
        client_secret: Its companion. Google issues one to desktop apps
            while documenting that they cannot keep it secret; it grants
            nothing without a person signing in.
        store: Where the protected refresh token lives. Defaults to the
            settings folder.
        receive: Runs the browser-and-loopback step and returns the code
            and the redirect address. Injected so tests run offline.
        post: Sends one form to Google. Injected for the same reason.
        protect / unprotect: DPAPI, injected because tests must not
            depend on Windows.
        now: Seconds since the epoch, for the expiry margin.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        store: Path | None = None,
        receive: Callable[[str, float], tuple[str, str]] = receive_code,
        post: Callable[[str, dict], dict] = post_form,
        protect: Callable[[bytes], bytes] = dpapi_protect,
        unprotect: Callable[[bytes], bytes] = dpapi_unprotect,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.store = store or config_dir() / STORE_NAME
        self.receive = receive
        self.post = post
        self.protect = protect
        self.unprotect = unprotect
        self.now = now
        self.email: str | None = None
        self._refresh_token: str | None = None
        self._id_token: str | None = None
        self._expires: float = 0.0
        self._loaded = False
        self._lock = threading.Lock()

    def signed_in(self) -> bool:
        """True when a sign-in is stored, however old."""
        self._load()
        return self._refresh_token is not None

    def sign_in(self, wait_seconds: float = SIGN_IN_WAIT_SECONDS) -> str:
        """Run the interactive sign-in and return the account's address.

        Raises:
            SigninError: The person did not finish, or Google refused.
        """
        verifier = _b64url(secrets.token_bytes(32))
        auth = AUTH_URL + "?" + urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": _b64url(
                    hashlib.sha256(verifier.encode("ascii")).digest()
                ),
                "code_challenge_method": "S256",
            }
        )
        code, redirect = self.receive(auth, wait_seconds)
        tokens = self.post(
            TOKEN_URL,
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
        if "refresh_token" not in tokens or "id_token" not in tokens:
            raise SigninError("Google's answer held no sign-in to keep.")
        with self._lock:
            self._refresh_token = tokens["refresh_token"]
            self._remember(tokens["id_token"])
            self._save()
        return self.email or ""

    def credential(self) -> str | None:
        """Return a current ID token, or None when a sign-in is needed.

        None has exactly one meaning: a person has to open the browser
        again - never signed in, or the account can no longer refresh.
        Network trouble raises instead, because "offline" must not be
        told "sign in again".
        """
        with self._lock:
            if self._id_token and self._expires - self.now() > REFRESH_MARGIN_SECONDS:
                return self._id_token
            self._load()
            if self._refresh_token is None:
                return None
            try:
                tokens = self.post(
                    TOKEN_URL,
                    {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            except SigninRefused as refusal:
                if refusal.code == "invalid_grant":
                    # The account was disabled or the sign-in revoked.
                    self._forget()
                    return None
                raise
            if "id_token" not in tokens:
                return None
            self._remember(tokens["id_token"])
            self._save()
            return self._id_token

    def _remember(self, id_token: str) -> None:
        claims = _claims_of(id_token)
        self._id_token = id_token
        expiry = claims.get("exp")
        self._expires = float(expiry) if isinstance(expiry, (int, float)) else (
            self.now() + 3000
        )
        self.email = claims.get("email") or self.email

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self.store.read_bytes()
        except OSError:
            return
        try:
            held = json.loads(self.unprotect(raw))
            self._refresh_token = held.get("refresh_token") or None
            self.email = held.get("email") or None
        except Exception:  # noqa: BLE001 - an unreadable store means signed out
            self._refresh_token = None

    def _save(self) -> None:
        held = {"refresh_token": self._refresh_token, "email": self.email}
        payload = self.protect(json.dumps(held).encode("utf-8"))
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_bytes(payload)

    def _forget(self) -> None:
        self._refresh_token = None
        self._id_token = None
        self._expires = 0.0
        try:
            self.store.unlink()
        except OSError:
            pass
