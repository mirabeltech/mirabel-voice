"""Scheduled relay checks and approximate spend metrics; never log payloads."""
from __future__ import annotations
import base64
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

NAMESPACE = "MirabelVoice/Operations"


def metric(client, name, value, unit="Count"):
    client.put_metric_data(Namespace=NAMESPACE, MetricData=[
        {"MetricName": name, "Value": value, "Unit": unit}
    ])


def estimate(line, prices):
    """USD estimate, or None when a paid request cannot be priced."""
    if line.get("route") not in {"transcribe", "cleanup"}:
        return 0.0
    if line.get("outcome") != "ok":
        return None  # a timeout does not establish that no charge occurred
    for key in ("input_tokens", "output_tokens", "audio_tokens", "text_tokens", "audio_seconds"):
        value = line.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            return None
    model = line.get("model", "")
    if line["route"] == "cleanup":
        rates = prices["cleanup_per_million_tokens"].get(model)
        if not rates or any(type(line.get(k)) not in (int, float) for k in ("input_tokens", "output_tokens")):
            return None
        return (line["input_tokens"] * rates["input"] + line["output_tokens"] * rates["output"]) / 1e6
    rates = prices["transcribe_per_million_tokens"].get(model)
    if rates and all(type(line.get(k)) in (int, float) for k in ("audio_tokens", "text_tokens", "output_tokens")):
        return (line["audio_tokens"] * rates["audio"] + line["text_tokens"] * rates["text"] + line["output_tokens"] * rates["output"]) / 1e6
    per_minute = prices["transcribe_per_minute"].get(model)
    seconds = line.get("audio_seconds")
    if per_minute is None or type(seconds) not in (int, float) or seconds <= 0:
        return None
    return seconds / 60 * per_minute


RELAY_LOGS = "/aws/lambda/mirabel-voice-relay"
# Six hours of logs: a few reads each, and only four windows per daily run.
WINDOW_MS = 6 * 3_600_000
# Only count logs at least this old, so each window is final when committed.
SETTLE_MS = 15 * 60_000
# Kept free after the last log read starts: one bounded read plus saving progress.
RESERVE_MS = 35_000
WINDOW_PAGES = 500


def month_start(moment):
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month(start):
    return (start + dt.timedelta(days=32)).replace(day=1)


def ms(moment):
    return int(moment.timestamp() * 1000)


def scan_window(logs, prices, start, end, deadline, clock=time.monotonic):
    """Price the usage logged in [start, end) ms; a window is all or nothing."""
    args = dict(logGroupName=RELAY_LOGS, startTime=start, endTime=end - 1,
                filterPattern='"usage"')
    seen, tokens = set(), set()
    total, unpriced, pages = 0.0, 0, 0
    for _ in range(WINDOW_PAGES):
        if clock() > deadline:
            raise TimeoutError("Out of time before the window finished")
        page = logs.filter_log_events(**args)
        pages += 1
        for event in page.get("events", []):
            event_id = event["eventId"]
            if event_id in seen:
                continue
            seen.add(event_id)
            _, marker, text = event["message"].partition("usage {")
            if not marker:
                continue
            try:
                cost = estimate(json.loads("{" + text.strip()), prices)
            except (ValueError, TypeError, KeyError):
                cost = None
            if cost is None:
                unpriced += 1
            else:
                total += cost
        token = page.get("nextToken")
        if not token:
            return total, unpriced, pages
        if token in tokens:
            raise RuntimeError("Window scan did not complete")
        tokens.add(token)
        args["nextToken"] = token
    raise RuntimeError("Window scan exceeded its page budget")


class Ledger:
    """Month totals and the time up to which they are complete, in DynamoDB.

    Each window's cost is added in the same conditional write that advances
    `covered`, so a crash or an overlapping run can never count a window twice.
    """
    def __init__(self, client, table):
        self.client, self.table = client, table

    @staticmethod
    def key(month):
        return {"pk": {"S": "spend-ledger#" + month.strftime("%Y-%m")}}

    def get(self, month):
        item = self.client.get_item(TableName=self.table, Key=self.key(month),
                                    ConsistentRead=True).get("Item")
        if item is None:
            return None
        return {"covered": int(item["covered"]["N"]), "total": float(item["total"]["N"]),
                "unpriced": int(item["unpriced"]["N"])}

    def open(self, month):
        try:
            self.client.put_item(TableName=self.table, Item=dict(self.key(month),
                covered={"N": str(ms(month))}, total={"N": "0"}, unpriced={"N": "0"}),
                ConditionExpression="attribute_not_exists(pk)")
        except Exception as error:
            if not conditional_failure(error):
                raise

    def commit(self, month, start, end, cost, unpriced):
        """False when another run already moved this month past `start`."""
        try:
            self.client.update_item(TableName=self.table, Key=self.key(month),
                UpdateExpression="SET covered = :end ADD #total :cost, unpriced :unpriced",
                ConditionExpression="covered = :start",
                ExpressionAttributeNames={"#total": "total"},
                ExpressionAttributeValues={":start": {"N": str(start)}, ":end": {"N": str(end)},
                    ":cost": {"N": format(cost, ".12f")}, ":unpriced": {"N": str(unpriced)}})
            return True
        except Exception as error:
            if conditional_failure(error):
                return False
            raise


def conditional_failure(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def spend(logs, ledger, prices, now, deadline, progress, clock=time.monotonic):
    """Advance the month ledgers window by window until caught up or out of time.

    Last month is finished first, so usage near midnight on the 1st is counted.
    `progress` records where the run got to; an interrupted window is redone later.
    """
    settled = ms(now) - SETTLE_MS
    current = month_start(now)
    previous = month_start(current - dt.timedelta(days=1))
    ledger.open(current)
    months = [(m, min(settled, ms(next_month(m)))) for m in (previous, current)]
    for month, end in months:
        state = ledger.get(month)
        if state is None:
            continue  # months before the ledger existed are not rebuilt
        covered = state["covered"]
        while covered < end:
            stop = min(covered + WINDOW_MS, end)
            progress["stage"] = "scan"
            cost, unpriced, pages = scan_window(logs, prices, covered, stop, deadline, clock)
            progress["pages"] += pages
            progress["stage"] = "commit"
            if ledger.commit(month, covered, stop, cost, unpriced):
                covered = stop
                progress["windows"] += 1
            else:
                covered = ledger.get(month)["covered"]
    progress["stage"] = "done"


def call(url, path, token, body, content_type):
    request = urllib.request.Request(url.rstrip("/") + path, data=body,
        headers={"x-api-key": token, "content-type": content_type})
    if path == "/v1/messages":
        request.add_header("anthropic-version", "2023-06-01")
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Service check refused")
        return json.loads(response.read(1_000_000))


def health(url, token, audio, send=call):
    boundary = "MirabelSyntheticCheck"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngpt-4o-transcribe\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"check.wav\"\r\nContent-Type: audio/wav\r\n\r\n"
    ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    started = time.monotonic()
    transcription = send(url, "/v1/audio/transcriptions", token, body,
                         f"multipart/form-data; boundary={boundary}")
    words = re.sub(r"[^a-z ]", "", transcription.get("text", "").lower())
    if "service check" not in words:
        raise RuntimeError("Transcription check failed")
    cleaned = send(url, "/v1/messages", token, json.dumps({
        "model": "claude-haiku-4-5", "max_tokens": 16,
        "messages": [{"role": "user", "content": "Reply with only the word ready."}]
    }).encode(), "application/json")
    text = " ".join(p.get("text", "") for p in cleaned.get("content", []) if p.get("type") == "text")
    if text.strip().lower().rstrip(".!") != "ready":
        raise RuntimeError("Cleanup check failed")
    return (time.monotonic() - started) * 1000


def bounded(name):
    """Clients whose calls cannot outlast the time reserved after a scan."""
    import boto3
    from botocore.config import Config
    return boto3.client(name, config=Config(connect_timeout=3, read_timeout=10,
                                            retries={"total_max_attempts": 2, "mode": "standard"}))


def spend_check(context, prices, clock=time.monotonic):
    """Bring the ledger up to date, then publish every spending metric at once."""
    started = clock()
    deadline = started + context.get_remaining_time_in_millis() / 1000 - RESERVE_MS / 1000
    now = dt.datetime.now(dt.timezone.utc)
    ledger = Ledger(bounded("dynamodb"), os.environ["SPEND_LEDGER_TABLE"])
    report = {"check": "spend", "windows": 0, "pages": 0, "stage": "ledger"}
    try:
        spend(bounded("logs"), ledger, prices, now, deadline, report, clock)
        caught_up = True
    except Exception as error:
        report["category"] = type(error).__name__
        caught_up = False
    # A partial month is still a correct lower bound, so it is published too.
    state = ledger.get(month_start(now))
    report["covered_until"] = dt.datetime.fromtimestamp(state["covered"] / 1000, dt.timezone.utc).isoformat()
    report["elapsed_ms"] = int((clock() - started) * 1000)
    report["result"] = "ok" if caught_up else "incomplete"
    print(json.dumps(report))
    checked = dt.date.fromisoformat(prices["checked"])
    return caught_up, [
        ("AIEstimatedUSD", state["total"], "None"),
        # Reservation is explicitly an allowance, not measured AWS billing.
        ("EstimatedUSDWithAWSReserve", state["total"] + float(os.environ["AWS_RESERVE_USD"]), "None"),
        ("UnpricedRequests", state["unpriced"], "Count"),
        ("PricingAgeDays", (now.date() - checked).days, "Count"),
    ]


def lambda_handler(event, context):
    kind = event.get("kind")
    if kind not in {"health", "spend"}:
        raise ValueError("Unknown check")
    if kind == "spend":
        cw = bounded("cloudwatch")
        values = []
        try:
            prices = json.loads(Path(__file__).with_name("pricing.json").read_text())
            ok, values = spend_check(context, prices)
        except Exception as error:
            print(json.dumps({"check": kind, "result": "failed", "stage": "ledger",
                              "category": type(error).__name__}))
            ok = False
        # One request, so the estimate and the failure flag cannot disagree.
        cw.put_metric_data(Namespace=NAMESPACE, MetricData=[
            {"MetricName": name, "Value": value, "Unit": unit}
            for name, value, unit in values + [("SpendFailed", 0 if ok else 1, "Count")]])
        return {"check": kind, "ok": ok}
    import boto3
    cw = boto3.client("cloudwatch")
    failed = 1
    try:
        secret = boto3.client("secretsmanager").get_secret_value(
            SecretId=os.environ["TOKENS_SECRET"])["SecretString"]
        tokens = json.loads(secret)
        token = next(k for k, v in tokens.items() if v == "Smoke test")
        latency = health(os.environ["RELAY_URL"], token,
                         Path(__file__).with_name("synthetic.wav").read_bytes())
        metric(cw, "SyntheticLatency", latency, "Milliseconds")
        failed = 0
    except Exception as error:
        # Never include exception messages, URLs, tokens or provider payloads.
        print(json.dumps({"check": kind, "result": "failed", "category": type(error).__name__}))
    finally:
        metric(cw, "HealthFailed", failed)
    return {"check": kind, "ok": not failed}
