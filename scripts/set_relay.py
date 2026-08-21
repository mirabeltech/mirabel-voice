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
    parsed = parser.parse_args(argv)

    if not parsed.url and not parsed.token:
        print("Nothing to set. Pass --url, --token, or both.")
        return 1

    config = Config.load()
    if parsed.url:
        config.relay_url = parsed.url.strip()
    if parsed.token:
        config.relay_token = parsed.token.strip()
    config.save()
    print(f"This machine now dictates through {config.relay_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
