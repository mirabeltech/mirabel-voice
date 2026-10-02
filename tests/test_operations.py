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
CONFIG = dict(requests_per_person_per_minute=20, reserved_concurrency=20, aws_reserve_usd=20,
              emails=["test@example.invalid"], region="us-east-2")


def test_estimate_uses_counts_and_marks_unknown_charges():
    line = dict(route="cleanup", outcome="ok", model="claude-haiku-4-5",
                input_tokens=1000, output_tokens=200)
    assert monitor.estimate(line, PRICES) == pytest.approx(.002)
    assert monitor.estimate(dict(line, outcome="unreachable"), PRICES) is None
    assert monitor.estimate(dict(line, model="unknown"), PRICES) is None
    del line["input_tokens"]
    assert monitor.estimate(line, PRICES) is None


def usage(route="transcribe", seconds=60, **extra):
    return "INFO usage " + json.dumps({"route": route, "outcome": "ok", "model": "whisper-1",
                                       "audio_seconds": seconds, **extra})


def test_window_scan_paginates_deduplicates_and_includes_smoke_checks():
    event = dict(eventId="a", message=usage(token="Smoke test"))
    calls = []
    pages = iter([{"events":[event],"nextToken":"second"},{"events":[event]}])
    def read(**kwargs):
        calls.append(kwargs)
        return next(pages)
    total, unknown, count = monitor.scan_window(SimpleNamespace(filter_log_events=read), PRICES,
                                                1000, 2000, deadline=float("inf"))
    assert total == pytest.approx(.006)
    assert (unknown, count) == (0, 2)
    assert (calls[0]["startTime"], calls[0]["endTime"]) == (1000, 1999)
    assert calls[1]["nextToken"] == "second"


def test_incomplete_window_cannot_report_a_false_zero():
    logs=SimpleNamespace(filter_log_events=lambda **kwargs:{"events":[],"nextToken":"stuck"})
    with pytest.raises(RuntimeError, match="did not complete"):
        monitor.scan_window(logs, PRICES, 0, 1, deadline=float("inf"))


class FakeLogs:
    """FilterLogEvents over timestamped events, two per page, inclusive bounds."""
    def __init__(self, events):
        self.events = sorted(events, key=lambda e: e["timestamp"])
        self.calls = 0

    def filter_log_events(self, startTime, endTime, nextToken=None, **kwargs):
        self.calls += 1
        hits = [e for e in self.events if startTime <= e["timestamp"] <= endTime]
        offset = int(nextToken or 0)
        page = {"events": hits[offset:offset + 2]}
        if offset + 2 < len(hits):
            page["nextToken"] = str(offset + 2)
        return page


class FakeTable:
    """Just enough DynamoDB for the ledger's conditional writes."""
    class Conflict(Exception):
        response = {"Error": {"Code": "ConditionalCheckFailedException"}}

    def __init__(self):
        self.items = {}

    def get_item(self, TableName, Key, ConsistentRead):
        item = self.items.get(Key["pk"]["S"])
        return {"Item": json.loads(json.dumps(item))} if item else {}

    def put_item(self, TableName, Item, ConditionExpression):
        if Item["pk"]["S"] in self.items:
            raise self.Conflict()
        self.items[Item["pk"]["S"]] = Item

    def update_item(self, TableName, Key, ExpressionAttributeValues, **kwargs):
        item, values = self.items[Key["pk"]["S"]], ExpressionAttributeValues
        if item["covered"]["N"] != values[":start"]["N"]:
            raise self.Conflict()
        item["covered"] = values[":end"]
        item["total"] = {"N": str(float(item["total"]["N"]) + float(values[":cost"]["N"]))}
        item["unpriced"] = {"N": str(int(item["unpriced"]["N"]) + int(values[":unpriced"]["N"]))}


def at(*args):
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


def logged(moment, n, message=None):
    return dict(eventId=str(n), timestamp=monitor.ms(moment), message=message or usage())


def run(logs, table, now, budget=float("inf")):
    """One scheduled run; `budget` is how many log reads it has time for."""
    progress = {"windows": 0, "pages": 0}
    reads = iter(range(10**6))
    clock = lambda: next(reads) if budget != float("inf") else 0
    try:
        monitor.spend(logs, monitor.Ledger(table, "t"), PRICES, now, budget, progress, clock)
        return True
    except TimeoutError:
        return False


def month(table, *args):
    return monitor.Ledger(table, "t").get(at(*args))


def test_interrupted_runs_resume_without_recounting():
    events = [logged(at(2026, 9, 1) + dt.timedelta(hours=h, minutes=30), h) for h in range(40)]
    table, logs = FakeTable(), FakeLogs(events)
    now = at(2026, 9, 2, 20)
    assert run(logs, table, now, budget=10) is False
    partial = month(table, 2026, 9, 1)
    assert 0 < partial["total"] < 40 * .006
    reads = logs.calls
    assert run(logs, table, now) is True
    assert month(table, 2026, 9, 1)["total"] == pytest.approx(40 * .006)
    # The second run starts where the first stopped rather than at the 1st.
    fresh = FakeLogs(events)
    assert run(fresh, FakeTable(), now) is True
    assert logs.calls - reads < fresh.calls
    assert run(logs, table, now) is True
    assert month(table, 2026, 9, 1)["total"] == pytest.approx(40 * .006)


def test_overlapping_runs_cannot_double_count():
    table = FakeTable()
    logs = FakeLogs([logged(at(2026, 9, 1, 0, 30), 1)])
    ledger = monitor.Ledger(table, "t")
    ledger.open(at(2026, 9, 1))
    start = monitor.ms(at(2026, 9, 1))
    assert ledger.commit(at(2026, 9, 1), start, start + monitor.WINDOW_MS, .006, 0)
    assert not ledger.commit(at(2026, 9, 1), start, start + monitor.WINDOW_MS, .006, 0)
    assert run(logs, table, at(2026, 9, 1, 3)) is True
    assert month(table, 2026, 9, 1)["total"] == pytest.approx(.006)


def test_month_rollover_finishes_last_month_first():
    late = logged(at(2026, 9, 30, 23, 50), 1)
    early = logged(at(2026, 10, 1, 0, 10), 2, usage(seconds=120))
    table, logs = FakeTable(), FakeLogs([late, early])
    assert run(logs, table, at(2026, 9, 30, 23, 25)) is True
    assert month(table, 2026, 9, 1)["total"] == 0
    assert run(logs, table, at(2026, 10, 1, 0, 25)) is True
    # 00:10 is still settling, so October waits; September is complete.
    assert month(table, 2026, 9, 1)["total"] == pytest.approx(.006)
    assert month(table, 2026, 10, 1)["total"] == 0
    assert run(logs, table, at(2026, 10, 2)) is True
    assert month(table, 2026, 10, 1)["total"] == pytest.approx(.012)
    assert month(table, 2026, 9, 1)["covered"] == monitor.ms(at(2026, 10, 1))


def test_unpriced_usage_is_counted_separately():
    table = FakeTable()
    logs = FakeLogs([logged(at(2026, 9, 1, 1), 1, usage(outcome="timeout")),
                     logged(at(2026, 9, 1, 2), 2, "INFO usage {not json")])
    assert run(logs, table, at(2026, 9, 1, 5)) is True
    assert month(table, 2026, 9, 1)["unpriced"] == 2
    assert month(table, 2026, 9, 1)["total"] == 0


def handler_run(monkeypatch, logs, table, remaining_ms=120_000):
    published = []
    cloudwatch = SimpleNamespace(put_metric_data=lambda **kwargs: published.append(kwargs["MetricData"]))
    clients = {"logs": logs, "dynamodb": table, "cloudwatch": cloudwatch}
    monkeypatch.setattr(monitor, "bounded", clients.__getitem__)
    monkeypatch.setattr(monitor, "__file__", str(ROOT / "docs/pricing.json"))  # packaged beside it
    monkeypatch.setenv("SPEND_LEDGER_TABLE", "t")
    monkeypatch.setenv("AWS_RESERVE_USD", "20")
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: remaining_ms)
    result = monitor.lambda_handler({"kind": "spend"}, context)
    assert len(published) == 1, "every spending metric goes in one request"
    return result, {m["MetricName"]: m["Value"] for m in published[0]}


def test_caught_up_run_publishes_estimate_and_clears_failure(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    result, values = handler_run(monkeypatch, FakeLogs([logged(now, 1)]), FakeTable())
    assert result == {"check": "spend", "ok": True}
    assert values["SpendFailed"] == 0
    assert values["AIEstimatedUSD"] == pytest.approx(.006)
    assert values["EstimatedUSDWithAWSReserve"] == pytest.approx(20.006)


def test_run_out_of_time_keeps_progress_and_flags_failure(monkeypatch, capsys):
    result, values = handler_run(monkeypatch, FakeLogs([]), FakeTable(), remaining_ms=1_000)
    assert result == {"check": "spend", "ok": False}
    assert values["SpendFailed"] == 1
    assert values["AIEstimatedUSD"] == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["result"], report["category"], report["stage"]) == ("incomplete", "TimeoutError", "scan")


def test_ledger_outage_still_flags_failure(monkeypatch):
    class Down:
        def __getattr__(self, name):
            raise RuntimeError("unavailable")
    result, values = handler_run(monkeypatch, FakeLogs([]), Down())
    assert result["ok"] is False
    assert values == {"SpendFailed": 1}


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


def test_only_the_health_check_alarms():
    alarms=setup.alarms(CONFIG,"test-topic")
    assert [a["AlarmName"] for a in alarms] == ["mirabel-voice-health"]
    health=alarms[0]
    assert health["TreatMissingData"] == "breaching"
    assert health["OKActions"] == ["test-topic"]
    assert health["Period"] == 900
    assert "\nWhat to do: " in health["AlarmDescription"]
    assert not set(setup.RETIRED_ALARMS) & {a["AlarmName"] for a in alarms}


def test_monitor_reaches_only_spending_ledger_keys():
    access = setup.monitor_ledger_access("arn:aws:dynamodb:us-east-2:123:table/t")
    assert set(access["Action"]) == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"}
    assert access["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] == ["spend-ledger#*"]


def test_retired_alarms_stop_sending_when_aws_denies_deletion():
    from unittest.mock import MagicMock
    from botocore.exceptions import ClientError
    cw = MagicMock()
    cw.delete_alarms.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteAlarms")
    original = dict(AlarmName="mirabel-voice-slow", MetricName="SyntheticLatency",
                    Threshold=15000, ActionsEnabled=True, AlarmActions=["topic"],
                    OKActions=["topic"], InsufficientDataActions=["topic"])
    cw.describe_alarms.return_value = {"MetricAlarms": [dict(original, StateValue="OK")]}
    cw.meta.service_model.operation_model.return_value.input_shape.members = dict.fromkeys(original)
    assert setup.retire_alarms(cw) == "notifications_disabled"
    cw.describe_alarms.assert_called_once_with(AlarmNames=setup.RETIRED_ALARMS)
    cw.put_metric_alarm.assert_called_once_with(**dict(
        original, ActionsEnabled=False, AlarmActions=[], OKActions=[], InsufficientDataActions=[]))


def test_retirement_deletes_only_alarms_that_still_exist():
    from unittest.mock import MagicMock
    cw = MagicMock()
    cw.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "mirabel-voice-estimated-budget-100"}]}
    assert setup.retire_alarms(cw) == "deleted"
    cw.delete_alarms.assert_called_once_with(AlarmNames=["mirabel-voice-estimated-budget-100"])
    cw.describe_alarms.return_value = {"MetricAlarms": []}
    cw.delete_alarms.reset_mock()
    assert setup.retire_alarms(cw) == "absent"
    cw.delete_alarms.assert_not_called()


def test_retirement_refuses_alarms_it_did_not_ask_for():
    from unittest.mock import MagicMock
    cw = MagicMock()
    cw.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "mirabel-voice-health"}]}
    with pytest.raises(ValueError, match="unexpected alarm"):
        setup.retire_alarms(cw)
    cw.delete_alarms.assert_not_called()


def test_retirement_reports_unexpected_aws_errors():
    from unittest.mock import MagicMock
    from botocore.exceptions import ClientError
    cw = MagicMock()
    cw.describe_alarms.return_value = {"MetricAlarms": [{"AlarmName": "mirabel-voice-slow"}]}
    cw.delete_alarms.side_effect = ClientError({"Error": {"Code": "InternalServiceError"}}, "DeleteAlarms")
    with pytest.raises(ClientError):
        setup.retire_alarms(cw)
    cw.put_metric_alarm.assert_not_called()


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


def test_preflight_reads_only_named_metric_alarms():
    requests = []
    class Client:
        def __getattr__(self, name):
            def call(**kwargs):
                if name == "describe_alarms":
                    requests.append(kwargs)
                    assert "AlarmNamePrefix" not in kwargs
                    assert kwargs["AlarmTypes"] == ["MetricAlarm"]
                    assert all(n.startswith("mirabel-voice-") for n in kwargs["AlarmNames"])
                if name == "get_account_settings":
                    return {"AccountLimit": {"UnreservedConcurrentExecutions": 1000}}
                return {}
            return call
    assert setup.preflight(SimpleNamespace(client=lambda name: Client()), "123", CONFIG) == []
    assert len(requests) == 1
    assert len(requests[0]["AlarmNames"]) == len(setup.alarms(CONFIG, "test-topic"))


def test_apply_activates_limits_alarms_and_schedules_without_billing_access(tmp_path, monkeypatch):
    import io
    import sys
    from unittest.mock import MagicMock
    clients = {name: MagicMock() for name in ("lambda", "iam", "sns", "dynamodb", "events", "cloudwatch", "logs")}
    lam = clients["lambda"]
    previous = {"CodeSha256": "old", "Environment": {"Variables": {"keep": "value"}}}
    lam.get_function.return_value = {"Configuration": previous, "Code": {"Location": "https://example.invalid/relay.zip"}}
    lam.get_function_concurrency.return_value = {}
    lam.get_function_url_config.return_value = {"FunctionUrl": "https://relay.invalid/"}
    lam.invoke.side_effect = lambda **kwargs: {"Payload": io.BytesIO(b'{"ok":true}')}
    clients["dynamodb"].describe_time_to_live.return_value = {"TimeToLiveDescription": {"TimeToLiveStatus": "ENABLED"}}
    clients["sns"].create_topic.return_value = {"TopicArn": "test-topic"}
    clients["sns"].get_paginator.return_value.paginate.return_value = [{"Subscriptions": [{"Protocol": "email", "Endpoint": CONFIG["emails"][0]}]}]
    clients["iam"].get_role.return_value = {"Role": {"Arn": "test-role"}}
    clients["events"].put_rule.return_value = {"RuleArn": "test-rule"}
    clients["events"].put_targets.return_value = {"FailedEntryCount": 0}
    clients["cloudwatch"].describe_alarms.return_value = {"MetricAlarms": [
        {"AlarmName": name} for name in setup.RETIRED_ALARMS]}
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b"old-zip"
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *a, **kw: response)
    monkeypatch.setattr(setup, "package_monitor", lambda _: b"monitor")
    monkeypatch.setitem(sys.modules, "deploy_relay", SimpleNamespace(TOKENS_SECRET="test-secret", build_package=lambda: b"relay"))
    deployment = MagicMock()
    monkeypatch.setattr(setup, "RelayDeployment", lambda *a: deployment)
    # No budgets client exists: any billing read/write fails this test.
    result = setup.apply(SimpleNamespace(client=clients.__getitem__), "123", CONFIG, None,
                         tmp_path / "backup")
    assert result["configured"] is True
    assert result["retired_alarms"] == "deleted"
    assert deployment.environment.call_args.args[0]["MIRABEL_REQUESTS_PER_MINUTE"] == "20"
    lam.put_function_concurrency.assert_called_once_with(FunctionName=setup.FUNCTION, ReservedConcurrentExecutions=20)
    assert clients["cloudwatch"].put_metric_alarm.call_count == 1
    clients["cloudwatch"].delete_alarms.assert_called_once_with(AlarmNames=[
        "mirabel-voice-slow", "mirabel-voice-relay-errors", "mirabel-voice-relay-throttles",
        "mirabel-voice-spend-monitor", "mirabel-voice-unpriced-usage", "mirabel-voice-stale-prices",
        "mirabel-voice-estimated-budget-100", "mirabel-voice-estimated-budget-150",
        "mirabel-voice-estimated-budget-180", "mirabel-voice-estimated-budget-200"])
    assert [json.loads(c.kwargs["Payload"])["kind"] for c in lam.invoke.call_args_list] == ["health", "spend"]
    assert len([c for c in clients["events"].put_rule.call_args_list if c.kwargs["State"] == "ENABLED"]) == 2
    enabled = {c.kwargs["Name"]: c.kwargs["ScheduleExpression"]
               for c in clients["events"].put_rule.call_args_list if c.kwargs["State"] == "ENABLED"}
    assert enabled[setup.MONITOR + "-spend"] == "rate(1 day)"
    assert enabled[setup.MONITOR + "-health"] == "rate(15 minutes)"
    role = next(c.kwargs for c in clients["iam"].put_role_policy.call_args_list
                if c.kwargs["RoleName"] == setup.MONITOR + "-role")
    assert "spend-ledger#*" in role["PolicyDocument"]
    monitor_env = lam.create_function.call_args or lam.update_function_configuration.call_args
    assert monitor_env.kwargs["Environment"]["Variables"]["SPEND_LEDGER_TABLE"] == setup.TABLE


def test_permission_request_cannot_edit_operator_permissions_or_other_functions():
    policy=setup.required_permissions("123","us-east-2")
    serialized=json.dumps(policy)
    assert "iam:PutUserPolicy" not in serialized
    assert "iam:AttachUserPolicy" not in serialized
    assert "function:*" not in serialized
    assert "iam:PassRole" in serialized
    assert "budgets:" not in serialized


@pytest.mark.parametrize("changes", [
    {"reserved_concurrency":0}, {"requests_per_person_per_minute":0},
    {"aws_reserve_usd":0},
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


class RevisionLambda:
    """Lambda advances revision again when each async update settles."""
    def __init__(self):
        import base64, hashlib
        self.hash = lambda blob: base64.b64encode(hashlib.sha256(blob).digest()).decode()
        self.revision = 1
        self.current = {"CodeSha256": self.hash(b"old"), "Environment": {"Variables": {"keep": "value"}}}
        self.pending = False
        self.fail_environment = False
        self.writes = []

    def get_waiter(self, name):
        def wait(**kwargs):
            if self.pending:
                self.revision += 1
                self.pending = False
        return SimpleNamespace(wait=wait)

    def get_function_configuration(self, **kwargs):
        from copy import deepcopy
        return dict(deepcopy(self.current), RevisionId=str(self.revision))

    def update_function_code(self, **kwargs):
        assert kwargs['RevisionId'] == str(self.revision)
        self.writes.append('code')
        self.current['CodeSha256'] = self.hash(kwargs['ZipFile'])
        self.revision += 1
        self.pending = True
        return self.get_function_configuration()

    def update_function_configuration(self, **kwargs):
        assert kwargs['RevisionId'] == str(self.revision)
        if self.fail_environment:
            self.fail_environment = False
            raise RuntimeError('configuration refused')
        self.writes.append('environment')
        self.current['Environment'] = kwargs['Environment']
        self.revision += 1
        self.pending = True
        return self.get_function_configuration()


def test_deployment_refreshes_revision_after_each_completed_update():
    client = RevisionLambda()
    deployment = setup.RelayDeployment(client, client.get_function_configuration())
    deployment.code(b'new')
    deployment.environment({'keep': 'value', 'limit': '20'})
    assert client.writes == ['code', 'environment']
    assert deployment.settled()['RevisionId'] == '5'


def test_rollback_refreshes_revisions_after_failed_configuration():
    client = RevisionLambda()
    original = client.get_function_configuration()
    deployment = setup.RelayDeployment(client, original)
    deployment.code(b'new')
    client.fail_environment = True
    with pytest.raises(RuntimeError, match='configuration refused'):
        deployment.environment({'limit': '20'})
    deployment.restore(b'old', original['Environment']['Variables'])
    assert client.current == {key: original[key] for key in ('CodeSha256', 'Environment')}


@pytest.mark.parametrize('field', ['CodeSha256', 'Environment'])
def test_rollback_does_not_overwrite_another_operators_changes(field):
    client = RevisionLambda()
    original = client.get_function_configuration()
    deployment = setup.RelayDeployment(client, original)
    deployment.code(b'new')
    client.current[field] = 'different-code' if field == 'CodeSha256' else {'Variables': {'other': 'change'}}
    with pytest.raises(RuntimeError, match='outside this activation'):
        deployment.restore(b'old', original['Environment']['Variables'])
    assert client.writes == ['code']
