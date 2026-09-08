"""No AWS writes or paid provider calls: operations decisions and failure handling."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


monitor = load("operations_monitor", "operations/monitor.py")
setup = load("operations_setup", "scripts/setup_operations.py")
PRICES = json.loads((ROOT / "docs/pricing.json").read_text())
CONFIG = dict(requests_per_person_per_minute=20, reserved_concurrency=20,
              monthly_target_usd=200, aws_reserve_usd=20, warning_usd=[100,150,180,200],
              emails=["test@example.invalid"], region="us-east-2")


def test_estimate_uses_counts_and_marks_unknown_charges():
    line = dict(route="cleanup", outcome="ok", model="claude-haiku-4-5",
                input_tokens=1000, output_tokens=200)
    assert monitor.estimate(line, PRICES) == pytest.approx(.002)
    assert monitor.estimate(dict(line, outcome="unreachable"), PRICES) is None
    assert monitor.estimate(dict(line, model="unknown"), PRICES) is None
    del line["input_tokens"]
    assert monitor.estimate(line, PRICES) is None


def test_calendar_month_scan_paginates_deduplicates_and_includes_smoke_checks():
    event = dict(eventId="a", message='INFO usage '+json.dumps(dict(
        route="transcribe", outcome="ok", model="whisper-1",
        audio_seconds=60, token="Smoke test")))
    calls = []
    pages = iter([{"events":[event],"nextToken":"second"},{"events":[event]}])
    def read(**kwargs):
        calls.append(kwargs)
        return next(pages)
    now=dt.datetime(2026,9,8,tzinfo=dt.timezone.utc)
    total, unknown=monitor.spend(SimpleNamespace(filter_log_events=read), PRICES, now)
    assert total == pytest.approx(.006)
    assert unknown == 0
    assert calls[0]["startTime"] == int(dt.datetime(2026,9,1,tzinfo=dt.timezone.utc).timestamp()*1000)
    assert calls[1]["nextToken"] == "second"


def test_incomplete_spend_scan_cannot_report_a_false_zero():
    logs=SimpleNamespace(filter_log_events=lambda **kwargs:{"events":[],"nextToken":"stuck"})
    with pytest.raises(RuntimeError, match="did not complete"):
        monitor.spend(logs, PRICES)


def test_synthetic_check_requires_both_transcription_and_cleanup():
    calls=[]
    def send(url,path,token,body,content_type):
        calls.append(path)
        if "transcriptions" in path:
            return {"text":"This is a routine service check."}
        return {"content":[{"type":"text","text":"ready"}]}
    assert monitor.health("https://relay.invalid","synthetic",b"fixture",send) >= 0
    assert len(calls)==2
    with pytest.raises(RuntimeError,match="Transcription"):
        monitor.health("https://relay.invalid","synthetic",b"fixture",lambda *a:{"text":""})


def test_missing_checks_alarm_and_budget_alarms_do_not_claim_hard_cap():
    alarms=setup.alarms(CONFIG,"test-topic")
    health=next(a for a in alarms if a["AlarmName"].endswith("-health"))
    assert health["TreatMissingData"] == "breaching"
    assert health["OKActions"] == ["test-topic"]
    budgets=[a for a in alarms if "estimated-budget" in a["AlarmName"]]
    assert [a["Threshold"] for a in budgets] == [100,150,180,200]
    assert all(a["OKActions"] == [] for a in budgets)


def test_preflight_reports_access_denial_without_mutations():
    class Denied(Exception):
        response={"Error":{"Code":"AccessDenied"}}
    calls=[]
    class Client:
        def __getattr__(self,name):
            def call(**kwargs):
                calls.append(name)
                raise Denied()
            return call
    failures=setup.preflight(SimpleNamespace(client=lambda name:Client()),"123",CONFIG)
    assert failures
    assert all(name.startswith(("get_","describe_")) for name in calls)


def test_permission_request_cannot_edit_operator_permissions_or_other_functions():
    policy=setup.required_permissions("123","us-east-2")
    serialized=json.dumps(policy)
    assert "iam:PutUserPolicy" not in serialized
    assert "iam:AttachUserPolicy" not in serialized
    assert "function:*" not in serialized
    assert "iam:PassRole" in serialized


@pytest.mark.parametrize("changes", [
    {"reserved_concurrency":0}, {"requests_per_person_per_minute":0},
    {"aws_reserve_usd":200}, {"warning_usd":[100,50,200]},
])
def test_invalid_controls_are_rejected(changes):
    with pytest.raises(ValueError):
        setup.validate(dict(CONFIG,**changes))


def test_cleanup_check_sends_required_provider_version(monkeypatch):
    requests=[]
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): return b'{}'
    def open_request(request,timeout):
        requests.append(request)
        return Response()
    monkeypatch.setattr(monitor.urllib.request,"urlopen",open_request)
    monitor.call("https://relay.invalid","/v1/messages","dummy",b"{}","application/json")
    assert requests[0].get_header("Anthropic-version") == "2023-06-01"
