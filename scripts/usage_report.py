"""Who used the relay, how much, and what it cost.

    python scripts/usage_report.py
    python scripts/usage_report.py --days 30
    python scripts/usage_report.py --expected people.txt
    python scripts/usage_report.py --reports

The relay writes one usage line per request to CloudWatch. This reads
those lines back and adds them up per person. Nothing here reaches a
provider's billing API: the numbers are the relay's own record of what
it forwarded, priced with the rates in docs/pricing.json.

After the cost table comes a versions section: each person's latest app
version and when their copy last called the relay. With --expected, the
names in that file that never called in the window are listed too.
With --reports, the app's error reports follow, grouped by error type
and the innermost stack frame.

The lines carry no audio and no text, so a report can be shared without
sharing anything anybody said.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "operations"))

import deploy_relay
from deploy_relay import DEFAULT_REGION, FUNCTION, SMOKE_HOLDER, Stop, say
from monitor import group_reports

LOG_GROUP = f"/aws/lambda/{FUNCTION}"
PRICES = Path(__file__).resolve().parent.parent / "docs" / "pricing.json"


def main(argv=None) -> int:
    parsed = _arguments(argv)
    expected = None
    if parsed.expected:
        try:
            expected = read_expected(parsed.expected)
        except (OSError, UnicodeDecodeError):
            say(f"Cannot read the expected-people file: {parsed.expected}")
            return 2
    try:
        session = deploy_relay.open_session(parsed.profile, parsed.region)
        prices = json.loads(PRICES.read_text(encoding="utf-8"))
        lines = read_usage(session, parsed.days)
        if lines:
            report(summarize(lines, prices), prices, parsed.days)
        else:
            say(f"No relay requests in the last {parsed.days} days.")
        say()
        report_versions(versions(lines), expected, parsed.days)
        if parsed.reports:
            say()
            report_errors(*group_reports(read_reports(session, parsed.days)), parsed.days)
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
    parser.add_argument(
        "--expected", type=Path,
        help="A file of names, one per line as the report shows them. "
        "Lists the ones never seen in the window.",
    )
    parser.add_argument(
        "--reports", action="store_true",
        help="Also list the app's error reports, grouped.",
    )
    return parser.parse_args(argv)


def read_usage(session, days: int) -> list[dict]:
    """Return every usage line in the window, oldest first."""
    return read_lines(session, days, "usage")


def read_reports(session, days: int) -> list[dict]:
    """Return every error report line in the window, oldest first.

    A line that does not parse stays in without a report, so
    group_reports counts it as unreadable.
    """
    return read_lines(session, days, "report", keep_unparsed=True)


def read_lines(session, days: int, marker: str, keep_unparsed: bool = False) -> list[dict]:
    """Return every `marker {...}` line in the window, oldest first.

    Each line gains seen_ms, the log event's own timestamp, so the
    versions section can tell which call came last. A line whose JSON
    does not parse is dropped, or kept as an empty line with
    keep_unparsed.
    """
    import time

    client = session.client("logs")
    start = int((time.time() - days * 86400) * 1000)
    found = []
    pages = client.get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, startTime=start, filterPattern=marker
    )
    for page in pages:
        for event in page.get("events", []):
            _, opening, body = event["message"].partition(marker + " {")
            if not opening:
                continue
            try:
                line = json.loads("{" + body.strip())
            except json.JSONDecodeError:
                if not keep_unparsed:
                    continue
                line = {}
            line["seen_ms"] = event.get("timestamp", 0)
            found.append(line)
    return found


def versions(lines: list[dict]) -> dict[str, dict]:
    """Each person's latest version, when they were last seen, and the rest.

    Latest means the version on the newest line, not the highest number:
    a person who rolled back runs the older release. Refused calls and
    the deploy's smoke test are not people. A line from before the relay
    recorded versions counts as unknown.
    """
    people: dict[str, dict] = {}
    for line in lines:
        who = line.get("token", "-")
        if who in ("-", SMOKE_HOLDER):
            continue
        version = line.get("version") or "unknown"
        seen = line.get("seen_ms", 0)
        person = people.setdefault(
            who, {"latest": version, "last_seen_ms": seen, "seen": set()}
        )
        person["seen"].add(version)
        if seen >= person["last_seen_ms"]:
            person["latest"] = version
            person["last_seen_ms"] = seen
    for person in people.values():
        person["others"] = sorted(person.pop("seen") - {person["latest"]})
    return people


def read_expected(path: Path) -> list[str]:
    """The names in an expected-people file, in file order.

    One name per line, written as the usage line's token. Blank lines
    and # comments are skipped. A leading byte order mark is dropped:
    Windows PowerShell 5.1 writes one with -Encoding utf8.
    """
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        name = raw.split("#", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def never_seen(expected: list[str], people: dict) -> list[str]:
    """The expected names with no line in the window."""
    return [name for name in expected if name not in people]


def summarize(lines: list[dict], prices: dict) -> dict:
    """Add the lines up per person.

    A transcribe line that carries token counts (v0.6.4 and later) is
    priced from the token rates, which is what OpenAI actually bills:
    audio in, prompt text in, transcript out. An older line without
    counts is priced by audio minutes, which misses the text tokens
    and understates the cost.
    """
    per_minute = prices["transcribe_per_minute"]
    per_token = prices.get("transcribe_per_million_tokens", {})
    per_million = prices["cleanup_per_million_tokens"]
    people: dict[str, dict] = {}
    for line in lines:
        who = line.get("token", "-")
        person = people.setdefault(
            who,
            {
                "dictations": 0, "token_priced": 0, "minutes": 0.0,
                "input_tokens": 0, "output_tokens": 0, "refused": 0,
                "failed": 0, "transcribe_cost": 0.0, "cleanup_cost": 0.0,
                "unpriced": set(),
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
            token_rate = per_token.get(model)
            if line.get("audio_tokens") is not None and token_rate is not None:
                person["token_priced"] += 1
                person["transcribe_cost"] += (
                    (line.get("audio_tokens") or 0) / 1e6 * token_rate["audio"]
                    + (line.get("text_tokens") or 0) / 1e6 * token_rate["text"]
                    + (line.get("output_tokens") or 0) / 1e6 * token_rate["output"]
                )
            elif model in per_minute:
                person["transcribe_cost"] += minutes * per_minute[model]
            else:
                person["unpriced"].add(model)
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
    totals = {
        "dictations": 0, "token_priced": 0, "minutes": 0.0,
        "transcribe_cost": 0.0, "cleanup_cost": 0.0,
    }
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
        say(
            f"{totals['token_priced']} of {totals['dictations']} dictations "
            "carried token counts and are priced exactly; the rest are "
            "priced by audio minutes, which understates them."
        )
    if smoke_cost is not None:
        say(f"Deploy smoke tests spent ${smoke_cost:.4f} on top; the table leaves them out.")
    failed = sum(p["failed"] for p in people.values())
    if failed:
        say(f"{failed} request(s) came back as an error.")
    if refused:
        say(f"{refused} request(s) were refused: no token, or a token nobody holds.")
    if unpriced:
        say(f"No price for: {', '.join(sorted(unpriced))}. Add it to docs/pricing.json.")


def report_versions(people: dict, expected: list[str] | None, days: int) -> None:
    """Print the versions section."""
    from datetime import datetime, timezone

    say(f"App versions, last {days} days. Times are UTC.")
    say("=" * 78)
    say(f"{'Person':<32}{'Latest':<12}{'Last seen':<18}Other versions")
    say("-" * 78)
    for who in sorted(people):
        person = people[who]
        seen = datetime.fromtimestamp(person["last_seen_ms"] / 1000, tz=timezone.utc)
        others = ", ".join(person["others"])
        say(f"{who:<32}{person['latest']:<12}{seen:%Y-%m-%d %H:%M}  {others}".rstrip())
    if not people:
        say("Nobody called the relay.")
    if expected is None:
        return
    missing = never_seen(expected, people)
    say()
    if missing:
        say(f"Installed but never seen ({len(missing)}):")
        for name in missing:
            say(f"  {name}")
    else:
        say("Everyone in the expected-people file was seen.")


def report_errors(groups: list[dict], unreadable: int, days: int) -> None:
    """Print the error reports section."""
    from datetime import datetime, timezone

    def when(ms):
        return f"{datetime.fromtimestamp(ms / 1000, tz=timezone.utc):%Y-%m-%d %H:%M}"

    say(f"Error reports, last {days} days. Times are UTC.")
    say("=" * 78)
    for group in groups:
        people = ", ".join(sorted(group["people"]))
        say(f"{group['error_type']} at {group['frame']}")
        say(
            f"  {group['count']} report(s) from {people}; "
            f"first {when(group['first_seen_ms'])}, last {when(group['last_seen_ms'])}"
        )
        for file, number, function in group["frames"]:
            say(f"    {file}:{number} in {function}")
        if group["message"]:
            say(f"  {group['message']}")
        say()
    if not groups:
        say("No error reports.")
    if unreadable:
        say(f"skipped {unreadable} unreadable report lines")


if __name__ == "__main__":
    raise SystemExit(main())
