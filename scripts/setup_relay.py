"""The setup wizard: who may dictate, and putting the relay in the air.

    python scripts/setup_relay.py

It checks that the account is ready, keeps the list of who holds a
token, and then deploys. Tokens are generated here rather than typed,
because a token nobody chose is a token nobody reuses from somewhere
else. Each new token is printed once, at the end, to be handed to its
person over a channel you trust.

The two provider-key secrets are not this script's business. The
account owner creates those by hand (docs/AWS.md step 5), so the keys
never pass through a script. This wizard reads neither.

Revoking one person is removing their name here and running it again.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy_relay
from deploy_relay import (
    ANTHROPIC_SECRET,
    DEFAULT_REGION,
    FUNCTION,
    OPENAI_SECRET,
    TOKENS_SECRET,
    Stop,
    say,
)

TOKEN_LENGTH = 24


def main(argv=None) -> int:
    parsed = _arguments(argv)
    try:
        session = deploy_relay.open_session(parsed.profile, parsed.region)
        say("Mirabel Voice relay setup")
        say("=" * 60)
        account = _check_account(session, parsed.region)
        holders = read_tokens(session)
        issued = choose_holders(session, holders)
        say()
        say("Deploying.")
        say("-" * 60)
        code = deploy_relay.main(
            _deploy_arguments(parsed) + (["--no-smoke"] if parsed.no_smoke else [])
        )
        if code != 0:
            say()
            say("The deploy did not finish. Nothing was handed out.")
            say("The token list is saved, so fixing the cause and running "
                "this again reissues nothing.")
            return code
        _hand_over(session, issued, account)
        return code
    except Stop as reason:
        say()
        say(f"Stopped: {reason}")
        return 1
    except KeyboardInterrupt:
        say()
        say("Nothing was deployed.")
        return 1


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="AWS profile name.")
    parser.add_argument("--region", default=DEFAULT_REGION,
                        help=f"Default: {DEFAULT_REGION}.")
    parser.add_argument("--no-smoke", action="store_true",
                        help="Deploy without the live test calls.")
    return parser.parse_args(argv)


def _deploy_arguments(parsed):
    argv = ["--region", parsed.region]
    if parsed.profile:
        argv += ["--profile", parsed.profile]
    return argv


def _check_account(session, region: str) -> str:
    """Confirm the account is ready before anything is changed."""
    account = deploy_relay._identity(session)
    say(f"Account {account}, region {region}.")
    deploy_relay._require_provider_secrets(session)
    say(f"Both provider keys are stored: {OPENAI_SECRET}, {ANTHROPIC_SECRET}.")
    return account


def read_tokens(session) -> dict[str, str]:
    """Read the token list, or start an empty one."""
    from botocore.exceptions import ClientError

    client = session.client("secretsmanager")
    try:
        held = deploy_relay._attempt(
            "reading the token list", client.get_secret_value, SecretId=TOKENS_SECRET
        )
    except ClientError as failure:
        if failure.response["Error"]["Code"] == "ResourceNotFoundException":
            return {}
        raise
    return json.loads(held["SecretString"])


def write_tokens(session, tokens: dict[str, str]) -> None:
    """Store the token list, creating the secret the first time."""
    from botocore.exceptions import ClientError

    client = session.client("secretsmanager")
    body = json.dumps(tokens, indent=2, sort_keys=True)
    try:
        deploy_relay._attempt(
            "storing the token list",
            client.put_secret_value,
            SecretId=TOKENS_SECRET,
            SecretString=body,
        )
    except ClientError as failure:
        if failure.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        deploy_relay._attempt(
            "creating the token list",
            client.create_secret,
            Name=TOKENS_SECRET,
            SecretString=body,
            Description="Who may use the Mirabel Voice relay.",
        )


def holders_of(tokens: dict[str, str]) -> list[str]:
    """The names, in order, without ever showing a token."""
    return sorted(tokens.values())


def choose_holders(session, tokens: dict[str, str]) -> dict[str, str]:
    """Add and remove people until the owner is done. Returns new tokens."""
    issued: dict[str, str] = {}
    changed = False
    while True:
        say()
        current = holders_of(tokens)
        if current:
            say(f"Token holders ({len(current)}): " + ", ".join(current))
        else:
            say("Nobody holds a token yet. Add at least one person.")
        say()
        say("  [a] add a person   [r] remove a person   [d] done, deploy now")
        choice = input("> ").strip().lower()[:1]

        if choice == "a":
            name = input("Their name: ").strip()
            if not name:
                say("A token needs a name, so the usage log can say whose it is.")
                continue
            if name in tokens.values():
                say(f"{name} already holds a token. Remove it first to reissue.")
                continue
            token = secrets.token_urlsafe(TOKEN_LENGTH)
            tokens[token] = name
            issued[name] = token
            changed = True
            say(f"Issued a token for {name}.")
        elif choice == "r":
            name = input("Whose token should stop working: ").strip()
            gone = [t for t, who in tokens.items() if who == name]
            if not gone:
                say(f"Nobody named {name} holds a token.")
                continue
            for token in gone:
                del tokens[token]
            issued.pop(name, None)
            changed = True
            say(f"Removed {name}. Their token stops working at the next deploy.")
        elif choice == "d":
            if not tokens:
                say("Add at least one person first; the relay needs a way in.")
                continue
            break
        else:
            say("Answer a, r, or d.")

    if changed:
        write_tokens(session, tokens)
        say()
        say(f"The token list now names {len(tokens)} "
            f"{'person' if len(tokens) == 1 else 'people'}.")
    return issued


def _hand_over(session, issued: dict[str, str], account: str) -> None:
    """Print the relay's address, and any token made in this run."""
    url = _function_url(session)
    say()
    say("=" * 60)
    say("The relay is live.")
    say()
    say(f"  Relay URL   {url}")
    say(f"  Function    {FUNCTION} in account {account}")
    if not issued:
        say()
        say("No new tokens were issued in this run.")
        return
    say()
    say("Give each person their own line. Send it over a channel you trust,")
    say("not email and not a ticket. This is the only time it is printed.")
    say()
    for name, token in sorted(issued.items()):
        say(f"  {name}")
        say(f"    relay_url   {url}")
        say(f"    relay_token {token}")
        say()


def _function_url(session) -> str:
    config = session.client("lambda").get_function_url_config(FunctionName=FUNCTION)
    return config["FunctionUrl"].rstrip("/")


if __name__ == "__main__":
    sys.exit(main())
