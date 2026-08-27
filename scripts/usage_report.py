"""Who used the relay, how much, and what it cost.

    python scripts/usage_report.py
    python scripts/usage_report.py --days 30

The relay writes one usage line per request to CloudWatch. This reads
those lines back and adds them up per person. Nothing here reaches a
provider's billing API: the numbers are the relay's own record of what
it forwarded, priced with the rates in docs/pricing.json.

The lines carry no audio and no text, so a report can be shared without
sharing anything anybody said.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy_relay
from deploy_relay import DEFAULT_REGION, FUNCTION, SMOKE_HOLDER, Stop, say

LOG_GROUP = f"/aws/lambda/{FUNCTION}"
PRICES = Path(__file__).resolve().parent.parent / "docs" / "pricing.json"


def main(argv=None) -> int:
    parsed = _arguments(argv)
    try:
        session = deploy_relay.open_session(parsed.profile, parsed.region)
        prices = json.loads(PRICES.read_text(encoding="utf-8"))
        lines = read_usage(session, parsed.days)
        if not lines:
            say(f"No relay requests in the last {parsed.days} days.")
            return 0
        report(summarize(lines, prices), prices, parsed.days)
        return 0
    except Stop as reason:
        say()
        say(f"Stopped: {reason}")
        return 1


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="Default: 30.")
    parser.add_argument("--profile", help="AWS profile name.")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"Default: {DEFAULT_REGION}.")
    return parser.parse_args(argv)


def read_usage(session, days: int) -> list[dict]:
    """Return every usage line in the window, oldest first."""
    import time

    client = session.client("logs")
    start = int((time.time() - days * 86400) * 1000)
    found = []
    pages = client.get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, startTime=start, filterPattern="usage"
    )
    for page in pages:
        for event in page.get("events", []):
            _, marker, body = event["message"].partition("usage {")
            if not marker:
                continue
            try:
                found.append(json.loads("{" + body.strip()))
            except json.JSONDecodeError:
                continue
    return found


def summarize(lines: list[dict], prices: dict) -> dict:
    """Add the lines up per person."""
    per_minute = prices["transcribe_per_minute"]
    per_million = prices["cleanup_per_million_tokens"]
    people: dict[str, dict] = {}
    for line in lines:
        who = line.get("token", "-")
        person = people.setdefault(
            who,
            {
                "dictations": 0, "minutes": 0.0, "input_tokens": 0,
                "output_tokens": 0, "refused": 0, "failed": 0,
                "transcribe_cost": 0.0, "cleanup_cost": 0.0, "unpriced": set(),
            },
        )
        outcome = line.get("outcome")
        if outcome == "refused":
            person["refused"] += 1
            continue
        if outcome != "ok":
            person["failed"] += 1
        model = line.get("model")
        if line.get("route") == "transcribe":
            person["dictations"] += 1
            minutes = (line.get("audio_seconds") or 0) / 60
            person["minutes"] += minutes
            rate = per_minute.get(model)
            if rate is None:
                person["unpriced"].add(model)
            else:
                person["transcribe_cost"] += minutes * rate
        elif line.get("route") == "cleanup":
            person["input_tokens"] += line.get("input_tokens") or 0
            person["output_tokens"] += line.get("output_tokens") or 0
            rate = per_million.get(model)
            if rate is None:
                person["unpriced"].add(model)
            else:
                person["cleanup_cost"] += (
                    (line.get("input_tokens") or 0) / 1e6 * rate["input"]
                    + (line.get("output_tokens") or 0) / 1e6 * rate["output"]
                )
    return people


def report(people: dict, prices: dict, days: int) -> None:
    """Print the report."""
    say(f"Relay usage, last {days} days. Rates checked {prices['checked']}.")
    say("=" * 78)
    say(f"{'Person':<24}{'Dictations':>11}{'Minutes':>9}{'Transcribe':>12}{'Cleanup':>10}{'Total':>10}")
    say("-" * 78)
    totals = {"dictations": 0, "minutes": 0.0, "transcribe_cost": 0.0, "cleanup_cost": 0.0}
    unpriced: set = set()
    refused = 0
    smoke_cost = None
    for who in sorted(people):
        person = people[who]
        refused += person["refused"]
        unpriced |= {m for m in person["unpriced"] if m}
        if who == "-":
            # Refused calls have no holder and cost nothing.
            continue
        if who == SMOKE_HOLDER:
            # The deploy's own test calls: real spend, but not a person.
            smoke_cost = person["transcribe_cost"] + person["cleanup_cost"]
            continue
        cost = person["transcribe_cost"] + person["cleanup_cost"]
        say(
            f"{who:<24}{person['dictations']:>11}{person['minutes']:>9.1f}"
            f"{'$' + format(person['transcribe_cost'], '.4f'):>12}"
            f"{'$' + format(person['cleanup_cost'], '.4f'):>10}"
            f"{'$' + format(cost, '.4f'):>10}"
        )
        for key in totals:
            totals[key] += person[key]
    say("-" * 78)
    grand = totals["transcribe_cost"] + totals["cleanup_cost"]
    say(
        f"{'Everyone':<24}{totals['dictations']:>11}{totals['minutes']:>9.1f}"
        f"{'$' + format(totals['transcribe_cost'], '.4f'):>12}"
        f"{'$' + format(totals['cleanup_cost'], '.4f'):>10}"
        f"{'$' + format(grand, '.4f'):>10}"
    )
    say()
    if totals["dictations"]:
        say(f"That is ${grand / totals['dictations']:.4f} a dictation.")
    if smoke_cost is not None:
        say(f"Deploy smoke tests spent ${smoke_cost:.4f} on top; the table leaves them out.")
    failed = sum(p["failed"] for p in people.values())
    if failed:
        say(f"{failed} request(s) came back as an error.")
    if refused:
        say(f"{refused} request(s) were refused: no token, or a token nobody holds.")
    if unpriced:
        say(f"No price for: {', '.join(sorted(unpriced))}. Add it to docs/pricing.json.")


if __name__ == "__main__":
    raise SystemExit(main())
