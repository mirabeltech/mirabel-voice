"""Tests for the app's error reports.

Everything runs offline: the sender, the clock and the folder are
injected, so no test touches the network or the real settings folder.
"""

import json
import sys

import pytest

from mirabel_voice import report
from mirabel_voice.report import MAX_REPORT_BYTES, Reporter, build, scrub
from mirabel_voice.version import VERSION_HEADER

RELAY = "https://relay.example.on.aws/"


def raised(error):
    """Return error with a real traceback."""
    try:
        raise error
    except BaseException as caught:  # noqa: BLE001
        return caught


class FakeRelay:
    """The relay's report route, answering from a script."""

    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.sent = []

    def __call__(self, url, data, headers, timeout):
        self.sent.append((url, json.loads(data), headers, timeout))
        status = self.statuses.pop(0) if self.statuses else 204
        if isinstance(status, Exception):
            raise status
        return status


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def a_report(n=0, trigger="crash"):
    return {"trigger": trigger, "error_type": f"Error{n}", "message": "", "frames": [["app.py", n, "run"]]}


def make(tmp_path, relay=None, credential="the-token", clock=None):
    relay = relay if relay is not None else FakeRelay()
    reporter = Reporter(tmp_path, RELAY, credential, post=relay, clock=clock or Clock())
    return reporter, relay


@pytest.fixture
def unconfigured(monkeypatch):
    """Leave the module as each test found it."""
    monkeypatch.setattr(report, "_reporter", None)
    monkeypatch.setattr(report, "_secrets", ())


# --- scrubbing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\Priya Rao\AppData\Roaming\MirabelVoice\config.json",
        "c:/users/Priya Rao/AppData/Roaming/MirabelVoice/config.json",
        r"C:\\USERS\\Priya Rao\\AppData\\Roaming\\MirabelVoice\\config.json",
    ],
)
def test_the_profile_folder_never_leaves_the_machine(path):
    scrubbed = scrub(f"cannot open '{path}'")
    assert "Priya" not in scrubbed
    assert "%USERPROFILE%" in scrubbed
    assert "MirabelVoice" in scrubbed  # the rest of the path still helps


def test_a_profile_outside_users_is_scrubbed_in_any_case(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"D:\Profiles\priya")
    assert scrub("d:/PROFILES/Priya/app.py and D:\\Profiles\\priyanka") == (
        "%USERPROFILE%/app.py and D:\\Profiles\\priyanka"
    )


@pytest.mark.parametrize(
    "secret",
    [
        "eyJhbGciOiJSUzI1NiJ9.eyJlbWFpbCI6InByaXlhIn0.c2lnbmF0dXJl",
        "sk-ant-api03-abcdefGHIJ_123",
        "sk-proj-abcdef123456",
        "Bearer abc.def-ghi",
        "priya.rao@mirabeltech.com",
    ],
)
def test_each_secret_shape_is_redacted(secret):
    scrubbed = scrub(f"refused: {secret} (try again)")
    assert scrubbed == "refused: [redacted] (try again)"


def test_the_literal_secrets_are_redacted():
    assert scrub("token mv-1234-abcd refused", secrets=["mv-1234-abcd"]) == "token [redacted] refused"


# --- building ------------------------------------------------------------------


def test_a_report_holds_only_the_named_facts():
    error = raised(ValueError("cannot open C:\\Users\\priya\\x.wav for mv-token"))
    built = build("microphone", error, secrets=["mv-token"])

    assert set(built) == {
        "trigger", "error_type", "message", "frames",
        "app_version", "windows_version", "cpu", "time",
    }
    assert built["trigger"] == "microphone"
    assert built["error_type"] == "ValueError"
    assert built["message"] == "cannot open %USERPROFILE%\\x.wav for [redacted]"
    file, line, function = built["frames"][-1]
    assert function == "raised" and isinstance(line, int)
    assert built["time"].endswith("+00:00")


def test_the_message_is_capped():
    built = build("crash", raised(RuntimeError("x" * 5000)))
    assert len(built["message"]) == 500


def test_a_deep_traceback_fits_and_keeps_the_innermost_frame():
    def dive(depth):
        if depth == 0:
            raise RuntimeError("the bottom " + "y" * 600)
        dive(depth - 1)

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(5000)
    try:
        error = raised_from(lambda: dive(2000))
    finally:
        sys.setrecursionlimit(limit)
    built = build("crash", error)

    assert len(json.dumps(built).encode("utf-8")) <= MAX_REPORT_BYTES
    assert built["frames"][-1][2] == "dive"
    assert built["frames"][0][2] == "raised_from"
    assert len(built["frames"]) > 2


def raised_from(call):
    try:
        call()
    except BaseException as caught:  # noqa: BLE001
        return caught
    raise AssertionError("did not raise")


def test_frame_paths_are_scrubbed(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("USERPROFILE", str(Path(__file__).parent))
    built = build("crash", raised(RuntimeError("boom")))

    assert built["frames"]
    assert all(file.startswith("%USERPROFILE%") for file, _, _ in built["frames"])


def test_build_never_raises_on_an_error_without_a_traceback():
    built = build("crash", None)
    assert built["error_type"] == "NoneType"


# --- the queue file ------------------------------------------------------------


def test_the_queue_keeps_the_newest_twenty(tmp_path):
    reporter, _ = make(tmp_path)
    for n in range(25):
        reporter.add(a_report(n))

    queued = reporter.queued()
    assert len(queued) == 20
    assert [r["error_type"] for r in queued] == [f"Error{n}" for n in range(5, 25)]


def test_the_same_failure_is_queued_once(tmp_path):
    reporter, _ = make(tmp_path)
    reporter.add(a_report(1))
    reporter.add({**a_report(1), "message": "a second time", "time": "later"})
    reporter.add(a_report(1, trigger="microphone"))

    assert len(reporter.queued()) == 2


def test_a_corrupt_queue_reads_as_empty(tmp_path):
    (tmp_path / "reports.json").write_bytes(b"{not json")
    reporter, _ = make(tmp_path)
    assert reporter.queued() == []
    reporter.add(a_report(1))
    assert len(reporter.queued()) == 1


def test_an_unwritable_folder_never_raises(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder")
    reporter = Reporter(blocked, RELAY, "the-token", post=FakeRelay(), clock=Clock())

    reporter.add(a_report(1))
    reporter.flush()
    assert reporter.queued() == []


# --- sending ---------------------------------------------------------------------


def test_a_report_goes_to_the_relay_with_the_credential(tmp_path):
    reporter, relay = make(tmp_path)
    reporter.add(a_report(1))
    reporter.flush()

    url, body, headers, timeout = relay.sent[0]
    assert url == "https://relay.example.on.aws/v1/report"
    assert body == a_report(1)
    assert headers["x-api-key"] == "the-token"
    assert headers[VERSION_HEADER]
    assert headers["content-type"] == "application/json"
    assert headers["User-Agent"] == "mirabel-voice"
    assert timeout == 10


def test_a_callable_credential_is_asked_at_send_time(tmp_path):
    reporter, relay = make(tmp_path, credential=lambda: "fresh-id-token")
    reporter.add(a_report(1))
    reporter.flush()
    assert relay.sent[0][2]["x-api-key"] == "fresh-id-token"


@pytest.mark.parametrize("status", [204, 400, 413])
def test_a_taken_or_refused_report_leaves_the_queue(tmp_path, status):
    reporter, _ = make(tmp_path, relay=FakeRelay(status))
    reporter.add(a_report(1))
    reporter.flush()
    assert reporter.queued() == []


@pytest.mark.parametrize("answer", [500, 404, OSError("offline")])
def test_a_failed_send_keeps_the_rest(tmp_path, answer):
    reporter, relay = make(tmp_path, relay=FakeRelay(204, answer))
    for n in range(3):
        reporter.add(a_report(n))
    reporter.flush()

    assert len(relay.sent) == 2
    assert [r["error_type"] for r in reporter.queued()] == ["Error1", "Error2"]
    assert "the-token" not in (tmp_path / "reports.json").read_text()


@pytest.mark.parametrize("credential", [None, lambda: None])
def test_no_credential_keeps_the_queue(tmp_path, credential):
    reporter, relay = make(tmp_path, credential=credential)
    reporter.add(a_report(1))
    reporter.flush()
    assert relay.sent == []
    assert len(reporter.queued()) == 1


def test_a_credential_that_raises_keeps_the_queue(tmp_path):
    def offline():
        raise OSError("no route to Google")

    reporter, relay = make(tmp_path, credential=offline)
    reporter.add(a_report(1))
    reporter.flush()
    assert relay.sent == []
    assert len(reporter.queued()) == 1


def test_the_twenty_first_send_in_an_hour_waits(tmp_path):
    clock = Clock()
    reporter, relay = make(tmp_path, clock=clock)
    for n in range(20):
        reporter.add(a_report(n))
    reporter.flush()
    assert len(relay.sent) == 20

    reporter.add(a_report(20))
    clock.now += 3599
    reporter.flush()
    assert len(relay.sent) == 20
    assert len(reporter.queued()) == 1

    clock.now += 1
    reporter.flush()
    assert len(relay.sent) == 21
    assert reporter.queued() == []


# --- the module API --------------------------------------------------------------


def test_record_does_nothing_before_configure(unconfigured, tmp_path, monkeypatch):
    monkeypatch.setattr(report, "_ensure_worker", lambda: pytest.fail("a worker started"))
    report.record("crash", raised(RuntimeError("boom")))
    report.record("crash", raised(RuntimeError("boom")), wait=True)
    report.flush_later(60)


def test_record_does_nothing_without_a_relay(unconfigured, tmp_path, monkeypatch):
    report.configure("", "the-token", tmp_path)
    monkeypatch.setattr(report, "_ensure_worker", lambda: pytest.fail("a worker started"))
    report.record("crash", raised(RuntimeError("boom")), wait=True)
    report.record("crash", raised(RuntimeError("boom")))
    assert not (tmp_path / "reports.json").exists()


def test_record_never_raises_on_an_error_without_a_traceback(unconfigured, tmp_path):
    report.configure(RELAY, "the-token", tmp_path)
    report.record("crash", None, wait=True)

    assert json.loads((tmp_path / "reports.json").read_text())[0]["error_type"] == "NoneType"


def test_waiting_writes_before_returning_and_sends_nothing(unconfigured, tmp_path, monkeypatch):
    report.configure(RELAY, "mv-secret-token", tmp_path, secrets=["mv-secret-token"])
    monkeypatch.setattr(report, "_ensure_worker", lambda: pytest.fail("a worker started"))
    report.record("crash", raised(RuntimeError("refused mv-secret-token")), wait=True)

    queued = json.loads((tmp_path / "reports.json").read_text())
    assert len(queued) == 1
    assert queued[0]["message"] == "refused [redacted]"


def test_the_worker_queues_and_sends(unconfigured, tmp_path, monkeypatch):
    import threading

    relay = FakeRelay()
    sent = threading.Event()

    def post(*args):
        status = relay(*args)
        sent.set()
        return status

    report.configure(RELAY, "the-token", tmp_path)
    report._reporter.post = post
    report.record("microphone", raised(OSError("device gone")))

    assert sent.wait(5)
    assert relay.sent[0][1]["trigger"] == "microphone"
    assert any(t.name == "mirabel-voice-reports" for t in threading.enumerate())


def test_flush_later_sends_what_an_earlier_run_queued(unconfigured, tmp_path):
    import threading

    make(tmp_path)[0].add(a_report())
    relay = FakeRelay()
    sent = threading.Event()

    def post(*args):
        status = relay(*args)
        sent.set()
        return status

    report.configure(RELAY, "the-token", tmp_path)
    report._reporter.post = post
    report.flush_later(0)

    assert sent.wait(5)
    assert relay.sent[0][1]["error_type"] == "Error0"


def test_a_failed_send_is_retried_later(unconfigured, tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(report, "RETRY_SECONDS", 0.05)
    make(tmp_path)[0].add(a_report())
    relay = FakeRelay(500)
    retried = threading.Event()

    def post(*args):
        status = relay(*args)
        if len(relay.sent) == 2:
            retried.set()
        return status

    report.configure(RELAY, "the-token", tmp_path)
    report._reporter.post = post
    report.flush_later(0)

    assert retried.wait(5)
    assert [sent[1]["error_type"] for sent in relay.sent] == ["Error0", "Error0"]
