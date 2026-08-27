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
