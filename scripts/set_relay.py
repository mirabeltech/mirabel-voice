"""Point this machine at the relay.

    python scripts/set_relay.py --url https://<id>.lambda-url.<region>.on.aws
    python scripts/set_relay.py --token <the token you were given>

The setup script calls this once the person has their token. It writes the
address and the token into config.json and touches nothing else, so a
machine that was already set up keeps its hotkey, its words, and its
preferences.

The address is not a secret; the token is. Passing only one of them
changes only that one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirabel_voice.config import Config  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="The relay address.")
    parser.add_argument("--token", help="This machine's relay token.")
    parser.add_argument("--google-client-id", help="Our Google OAuth client id.")
    parser.add_argument(
        "--google-client-secret",
        help="Its companion value. With both set, the app signs in with "
             "the work account and the token is no longer used.",
    )
    parsed = parser.parse_args(argv)

    google = (parsed.google_client_id, parsed.google_client_secret)
    if any(google) and not all(google):
        print("Google sign-in needs both --google-client-id and "
              "--google-client-secret.")
        return 1
    if not parsed.url and not parsed.token and not all(google):
        print("Nothing to set. Pass --url, --token, the Google pair, or any mix.")
        return 1

    config = Config.load()
    if parsed.url:
        config.relay_url = parsed.url.strip()
    if parsed.token:
        config.relay_token = parsed.token.strip()
    if all(google):
        config.google_client_id = parsed.google_client_id.strip()
        config.google_client_secret = parsed.google_client_secret.strip()
    config.save()
    print(f"This machine now dictates through {config.relay_url}")
    if config.google_client_id:
        print("It signs in with the Mirabel Google account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
