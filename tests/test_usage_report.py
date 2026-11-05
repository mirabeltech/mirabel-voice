"""The cost report's arithmetic, without touching AWS.

The report prices what the usage lines carry: token counts when a
line has them (v0.6.4 and later), audio minutes for older lines.
Getting this wrong misprices every number anyone quotes about the
pilot, so each path gets its own test.
"""

import pytest

from usage_report import summarize

PRICES = {
    "checked": "2026-08-27",
    "transcribe_per_minute": {"gpt-4o-transcribe": 0.006, "whisper-1": 0.006},
    "transcribe_per_million_tokens": {
        "gpt-4o-transcribe": {"audio": 6.0, "text": 2.5, "output": 10.0},
    },
    "cleanup_per_million_tokens": {"claude-haiku-4-5": {"input": 1.0, "output": 5.0}},
}


def transcribe_line(**extra):
    line = {
        "token": "tommy",
        "route": "transcribe",
        "model": "gpt-4o-transcribe",
        "outcome": "ok",
        "audio_seconds": 60.0,
    }
    line.update(extra)
    return line


def test_a_line_with_token_counts_is_priced_by_tokens():
    lines = [transcribe_line(audio_tokens=1000, text_tokens=100, output_tokens=200)]
    person = summarize(lines, PRICES)["tommy"]
    assert person["token_priced"] == 1
    assert person["transcribe_cost"] == pytest.approx(
        1000 / 1e6 * 6.0 + 100 / 1e6 * 2.5 + 200 / 1e6 * 10.0
    )
    # The minutes still count: they are the report's Minutes column.
    assert person["minutes"] == pytest.approx(1.0)


def test_a_line_without_token_counts_is_priced_by_minutes():
    person = summarize([transcribe_line()], PRICES)["tommy"]
    assert person["token_priced"] == 0
    assert person["transcribe_cost"] == pytest.approx(0.006)


def test_a_token_line_is_never_also_priced_by_minutes():
    """One line, one price. Charging tokens and minutes together
    would double-count every dictation from v0.6.4 on."""
    with_tokens = summarize(
        [transcribe_line(audio_tokens=1000, text_tokens=0, output_tokens=0)],
        PRICES,
    )["tommy"]
    assert with_tokens["transcribe_cost"] == pytest.approx(0.006)  # tokens only


def test_token_counts_for_a_model_without_token_rates_fall_back_to_minutes():
    """whisper-1 has a per-minute rate but no token table entry. A
    line from it must not vanish from the bill."""
    line = transcribe_line(model="whisper-1", audio_tokens=500)
    person = summarize([line], PRICES)["tommy"]
    assert person["token_priced"] == 0
    assert person["transcribe_cost"] == pytest.approx(0.006)


def test_an_unknown_model_lands_in_unpriced_not_at_zero():
    person = summarize([transcribe_line(model="mystery-model")], PRICES)["tommy"]
    assert person["transcribe_cost"] == 0.0
    assert person["unpriced"] == {"mystery-model"}


def test_cleanup_pricing_is_unchanged():
    line = {
        "token": "tommy",
        "route": "cleanup",
        "model": "claude-haiku-4-5",
        "outcome": "ok",
        "input_tokens": 1000,
        "output_tokens": 100,
    }
    person = summarize([line], PRICES)["tommy"]
    assert person["cleanup_cost"] == pytest.approx(
        1000 / 1e6 * 1.0 + 100 / 1e6 * 5.0
    )


# --- The versions section ----------------------------------------------------

import usage_report  # noqa: E402
from usage_report import (  # noqa: E402
    SMOKE_HOLDER, never_seen, read_expected, read_usage, report_versions, versions,
)


def seen(who, version, at, **extra):
    line = {"token": who, "route": "update", "outcome": "ok", "seen_ms": at}
    if version is not None:
        line["version"] = version
    line.update(extra)
    return line


def test_the_latest_version_is_the_newest_call_not_the_highest_number():
    people = versions([
        seen("cole", "0.9.6", 1_000),
        seen("cole", "0.9.7", 2_000),
        seen("cole", "0.9.5", 3_000),  # rolled back
    ])
    assert people["cole"]["latest"] == "0.9.5"
    assert people["cole"]["last_seen_ms"] == 3_000
    assert people["cole"]["others"] == ["0.9.6", "0.9.7"]


def test_line_order_does_not_decide_the_latest():
    people = versions([seen("cole", "0.9.7", 2_000), seen("cole", "0.9.6", 1_000)])
    assert (people["cole"]["latest"], people["cole"]["last_seen_ms"]) == ("0.9.7", 2_000)


def test_a_line_without_a_version_counts_as_unknown():
    people = versions([seen("priya", None, 1_000)])
    assert people["priya"]["latest"] == "unknown"


def test_refusals_and_the_smoke_test_are_not_people():
    people = versions([seen("-", "0.9.7", 1_000), seen(SMOKE_HOLDER, "0.9.7", 1_000)])
    assert people == {}


def test_the_expected_file_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / "people.txt"
    path.write_text(
        "# who should be running it\n\ncole@example.com\n  priya@example.com  # laptop\n",
        encoding="utf-8",
    )
    assert read_expected(path) == ["cole@example.com", "priya@example.com"]


def test_a_byte_order_mark_does_not_hide_the_first_name(tmp_path):
    path = tmp_path / "people.txt"
    path.write_bytes(b"\xef\xbb\xbfcole@example.com\nmark@example.com\n")
    expected = read_expected(path)
    assert expected == ["cole@example.com", "mark@example.com"]
    people = versions([seen("cole@example.com", "0.9.7", 1_000)])
    assert never_seen(expected, people) == ["mark@example.com"]


def test_never_seen_lists_the_expected_people_without_a_line():
    people = versions([seen("cole@example.com", "0.9.7", 1_000)])
    assert never_seen(["cole@example.com", "mark@example.com"], people) == ["mark@example.com"]


def test_the_section_prints_person_version_last_seen_and_the_rest(capsys):
    people = versions([
        seen("cole", "0.9.6", 1_000),
        seen("cole", "0.9.7", 1_762_257_600_000),  # 2025-11-04 12:00 UTC
    ])
    report_versions(people, ["cole", "mark"], 30)
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("cole"))
    assert row.split() == ["cole", "0.9.7", "2025-11-04", "12:00", "0.9.6"]
    assert "Installed but never seen (1):" in out
    assert "  mark" in out


def test_read_usage_keeps_each_events_timestamp():
    class Logs:
        def get_paginator(self, name):
            assert name == "filter_log_events"
            return self

        def paginate(self, **kwargs):
            assert kwargs["filterPattern"] == "usage"
            return [{"events": [
                {"timestamp": 1_234, "message": 'INFO usage {"token": "cole", "version": "0.9.7"}'},
                {"timestamp": 5_678, "message": "INFO something else"},
            ]}]

    class Session:
        def client(self, name):
            return Logs()

    assert read_usage(Session(), 30) == [
        {"token": "cole", "version": "0.9.7", "seen_ms": 1_234}
    ]


def test_an_unreadable_expected_file_stops_before_aws(tmp_path, monkeypatch, capsys):
    def no_session(*args):
        raise AssertionError("the report must not sign in to AWS")

    monkeypatch.setattr(usage_report.deploy_relay, "open_session", no_session)
    missing = tmp_path / "nobody.txt"
    assert usage_report.main(["--expected", str(missing)]) == 2
    assert f"Cannot read the expected-people file: {missing}" in capsys.readouterr().out


def test_the_versions_section_follows_the_cost_section(monkeypatch, capsys):
    monkeypatch.setattr(usage_report.deploy_relay, "open_session", lambda *args: object())
    monkeypatch.setattr(
        usage_report, "read_usage",
        lambda session, days: [dict(seen("cole", "0.9.7", 1_000), route="cleanup",
                                    model="claude-haiku-4-5", input_tokens=1, output_tokens=1)],
    )
    assert usage_report.main([]) == 0
    out = capsys.readouterr().out
    assert out.index("Relay usage") < out.index("App versions")


def test_an_empty_window_still_lists_the_expected_people(tmp_path, monkeypatch, capsys):
    path = tmp_path / "people.txt"
    path.write_text("cole@example.com\n", encoding="utf-8")
    monkeypatch.setattr(usage_report.deploy_relay, "open_session", lambda *args: object())
    monkeypatch.setattr(usage_report, "read_usage", lambda session, days: [])
    assert usage_report.main(["--expected", str(path)]) == 0
    out = capsys.readouterr().out
    assert "No relay requests in the last 30 days." in out
    assert "Nobody called the relay." in out
    assert "Installed but never seen (1):" in out
    assert "  cole@example.com" in out
