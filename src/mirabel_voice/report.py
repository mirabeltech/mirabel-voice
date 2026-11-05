"""Error reports: what failed on this copy, sent to the relay quietly.

Five known failures record a report: a crash, an update download, a
Google sign-in, the microphone, and the launch entry repair. A report
holds the error's type, its scrubbed message and the file, line and
function of each frame - never source lines, locals, audio, transcript
text, keys or tokens. Reports wait in reports.json in the settings
folder and go to the relay's POST /v1/report from one background
thread, so a failure to send never touches dictation.

Nothing here may raise into its caller: an error report that breaks
the app would be worse than none.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import re
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .config import relay_base
from .storage import save_bytes
from .version import VERSION_HEADER, client_version

log = logging.getLogger(__name__)

QUEUE_FILE = "reports.json"
MAX_REPORT_BYTES = 16_384
MAX_MESSAGE_CHARS = 500
LAST_RESORT_MESSAGE_CHARS = 200
MAX_QUEUED = 20
MAX_SENDS_PER_WINDOW = 20
SEND_WINDOW_SECONDS = 3_600
SEND_TIMEOUT_SECONDS = 10
RETRY_SECONDS = 3_600
WORKER_NAME = "mirabel-voice-reports"

REDACTED = "[redacted]"
PROFILE = "%USERPROFILE%"
_PROFILE_PATH = re.compile(r'(?i)[a-z]:[\\/]+users[\\/]+[^\\/:*?"<>|\r\n]+')
_SECRET_SHAPES = (
    re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*){0,2}"),  # a JWT
    re.compile(r"sk-[A-Za-z0-9_-]+"),  # an OpenAI or Anthropic key
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

# The relay's answers that mean "this report will never be taken":
# resending it would only spend the hourly budget again.
_DROP_STATUSES = (400, 413)


def _profile_pattern() -> re.Pattern | None:
    """The USERPROFILE folder, matched in any case and with either slash."""
    parts = [part for part in re.split(r"[\\/]+", os.environ.get("USERPROFILE", "")) if part]
    if not parts:
        return None
    folder = r"[\\/]+".join(map(re.escape, parts))
    return re.compile(folder + r'(?![^\\/:*?"<>|\r\n])', re.IGNORECASE)


def scrub(text, secrets=()) -> str:  # noqa: ANN001 - any object prints
    """Return text with the profile folder and every secret replaced."""
    try:
        text = str(text)
        for secret in secrets:
            if secret:
                text = text.replace(secret, REDACTED)
        profile = _profile_pattern()
        if profile is not None:
            text = profile.sub(PROFILE, text)
        text = _PROFILE_PATH.sub(PROFILE, text)
        for shape in _SECRET_SHAPES:
            text = shape.sub(REDACTED, text)
        return text
    except Exception:  # noqa: BLE001
        return ""


def _size(report: dict) -> int:
    return len(_serialize(report))


def _serialize(report: dict) -> bytes:
    return json.dumps(report).encode("utf-8")


def _fit(report: dict) -> dict:
    """Shrink a report to MAX_REPORT_BYTES, keeping frames[0] and the innermost."""
    frames = report["frames"]
    if _size(report) <= MAX_REPORT_BYTES or len(frames) < 3:
        fitted = report
    else:
        def kept(innermost: int) -> dict:
            return {**report, "frames": [frames[0]] + frames[len(frames) - innermost:]}

        low, high = 1, len(frames) - 1
        while low < high:  # the most innermost frames that still fit
            middle = (low + high + 1) // 2
            if _size(kept(middle)) <= MAX_REPORT_BYTES:
                low = middle
            else:
                high = middle - 1
        fitted = kept(low)
    if _size(fitted) > MAX_REPORT_BYTES:
        fitted = {**fitted, "message": fitted["message"][:LAST_RESORT_MESSAGE_CHARS]}
    return fitted


def build(trigger: str, error: BaseException, secrets=()) -> dict:  # noqa: ANN001
    """Return the scrubbed report for one failure."""
    report = {
        "trigger": trigger,
        "error_type": type(error).__name__,
        "message": "",
        "frames": [],
        "app_version": "",
        "windows_version": "",
        "cpu": "",
        "time": "",
    }
    try:
        report["app_version"] = client_version()
        report["windows_version"] = platform.version()
        report["cpu"] = platform.machine()
        report["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report["message"] = scrub(error, secrets)[:MAX_MESSAGE_CHARS]
        report["frames"] = [
            [scrub(frame.filename, secrets), frame.lineno, frame.name]
            for frame in traceback.extract_tb(error.__traceback__)
        ]
        return _fit(report)
    except Exception:  # noqa: BLE001 - a partial report beats none
        return {**report, "frames": report["frames"][-1:]}


def _post(url: str, data: bytes, headers: dict, timeout: float) -> int:
    """POST one report and return the HTTP status."""
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
            return answer.status
    except urllib.error.HTTPError as refusal:
        return refusal.code


def _identity(report: dict) -> tuple:
    frames = report.get("frames") or [None]
    innermost = frames[-1]
    return (
        report.get("trigger"),
        report.get("error_type"),
        tuple(innermost) if isinstance(innermost, list) else innermost,
    )


class Reporter:
    """The queue file folder/reports.json and its sender."""

    def __init__(
        self,
        folder: Path,
        relay_url: str,
        credential,  # noqa: ANN001 - a token, or a callable returning one
        post=_post,  # noqa: ANN001
        clock=time.monotonic,  # noqa: ANN001
    ) -> None:
        self.path = Path(folder) / QUEUE_FILE
        self.url = relay_base(relay_url) + "/v1/report"
        self.credential = credential
        self.post = post
        self.clock = clock
        self._lock = threading.Lock()
        self._sends: deque[float] = deque()

    def queued(self) -> list[dict]:
        """The waiting reports, oldest first. A missing or damaged file is none."""
        try:
            reports = json.loads(self.path.read_bytes())
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(reports, list):
            return []
        return [report for report in reports if isinstance(report, dict)]

    def _write(self, reports: list[dict]) -> None:
        save_bytes(self.path, json.dumps(reports).encode("utf-8"), backup=False)

    def add(self, report: dict) -> None:
        """Queue a report unless the same failure already waits."""
        try:
            with self._lock:
                reports = self.queued()
                if any(_identity(waiting) == _identity(report) for waiting in reports):
                    return
                self._write((reports + [report])[-MAX_QUEUED:])
        except Exception:  # noqa: BLE001
            log.debug("The error report was not queued.", exc_info=True)

    def _may_send(self) -> bool:
        now = self.clock()
        while self._sends and now - self._sends[0] >= SEND_WINDOW_SECONDS:
            self._sends.popleft()
        return len(self._sends) < MAX_SENDS_PER_WINDOW

    def _remove(self, report: dict) -> None:
        with self._lock:
            reports = self.queued()
            if report in reports:
                reports.remove(report)
                self._write(reports)

    def flush(self) -> None:
        """Send the waiting reports in order, until one is not taken."""
        try:
            reports = self.queued()
            if not reports:
                return
            key = self.credential() if callable(self.credential) else self.credential
            if not key:
                return
            headers = {
                "x-api-key": key,
                VERSION_HEADER: client_version(),
                "content-type": "application/json",
                "User-Agent": "mirabel-voice",
            }
            for report in reports:
                if not self._may_send():
                    return
                self._sends.append(self.clock())
                status = self.post(self.url, _serialize(report), headers, SEND_TIMEOUT_SECONDS)
                if not (200 <= status < 300 or status in _DROP_STATUSES):
                    return
                self._remove(report)
        except Exception:  # noqa: BLE001 - offline or signed out: try later
            log.debug("The error reports were not sent.", exc_info=True)


_state_lock = threading.Lock()
_reporter: Reporter | None = None
_secrets: tuple[str, ...] = ()
_inbox: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None


def configure(relay_url, credential, folder, secrets=()) -> None:  # noqa: ANN001
    """Point reports at the relay. A falsy relay_url turns them off."""
    global _reporter, _secrets  # noqa: PLW0603
    try:
        _secrets = tuple(secret for secret in secrets if secret)
        _reporter = Reporter(folder, relay_url, credential) if relay_url else None
    except Exception:  # noqa: BLE001
        _reporter = None


def _ensure_worker() -> None:
    global _worker  # noqa: PLW0603
    with _state_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name=WORKER_NAME, daemon=True)
            _worker.start()


def _work() -> None:
    next_flush: float | None = None
    while True:
        timeout = None if next_flush is None else max(0.0, next_flush - time.monotonic())
        try:
            item = _inbox.get(timeout=timeout)
        except queue.Empty:
            item = ("flush", 0.0)
        try:
            reporter = _reporter
            if reporter is None:
                continue
            kind, value = item
            if kind == "later":
                next_flush = time.monotonic() + value
                continue
            if kind == "record":
                trigger, error = value
                reporter.add(build(trigger, error, _secrets))
            reporter.flush()
            next_flush = time.monotonic() + RETRY_SECONDS if reporter.queued() else None
        except Exception:  # noqa: BLE001 - the worker outlives every report
            log.debug("The error report worker skipped an item.", exc_info=True)


def record(trigger: str, error: BaseException, wait: bool = False) -> None:
    """Report one failure. wait=True queues it before returning, without sending."""
    try:
        reporter = _reporter
        if reporter is None:
            return
        if wait:
            reporter.add(build(trigger, error, _secrets))
            return
        _inbox.put(("record", (trigger, error)))
        _ensure_worker()
    except Exception:  # noqa: BLE001
        pass


def flush_later(delay_seconds: float) -> None:
    """Send what earlier runs queued, delay_seconds from now."""
    try:
        if _reporter is None:
            return
        _inbox.put(("later", float(delay_seconds)))
        _ensure_worker()
    except Exception:  # noqa: BLE001
        pass
