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


def spend(logs, prices, now=None, clock=time.monotonic):
    """Recompute the UTC calendar month; paginated retries cannot double-count."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    args = dict(logGroupName="/aws/lambda/mirabel-voice-relay",
                startTime=int(start.timestamp() * 1000),
                endTime=int(now.timestamp() * 1000), filterPattern='"usage"')
    seen, tokens = set(), set()
    total, unpriced, deadline = 0.0, 0, clock() + 75
    for _ in range(500):
        if clock() > deadline:
            raise TimeoutError("Monthly scan incomplete")
        page = logs.filter_log_events(**args)
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
            return total, unpriced
        if token in tokens:
            raise RuntimeError("Monthly scan did not complete")
        tokens.add(token)
        args["nextToken"] = token
    raise RuntimeError("Monthly scan exceeded its page budget")


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


def lambda_handler(event, context):
    import boto3
    cw = boto3.client("cloudwatch")
    kind = event.get("kind")
    if kind not in {"health", "spend"}:
        raise ValueError("Unknown check")
    failed = 1
    try:
        if kind == "health":
            secret = boto3.client("secretsmanager").get_secret_value(
                SecretId=os.environ["TOKENS_SECRET"])["SecretString"]
            tokens = json.loads(secret)
            token = next(k for k, v in tokens.items() if v == "Smoke test")
            latency = health(os.environ["RELAY_URL"], token,
                             Path(__file__).with_name("synthetic.wav").read_bytes())
            metric(cw, "SyntheticLatency", latency, "Milliseconds")
        else:
            prices = json.loads(Path(__file__).with_name("pricing.json").read_text())
            total, unpriced = spend(boto3.client("logs"), prices)
            metric(cw, "AIEstimatedUSD", total, "None")
            # Reservation is explicitly an allowance, not measured AWS billing.
            metric(cw, "EstimatedUSDWithAWSReserve",
                   total + float(os.environ["AWS_RESERVE_USD"]), "None")
            metric(cw, "UnpricedRequests", unpriced)
            checked = dt.date.fromisoformat(prices["checked"])
            metric(cw, "PricingAgeDays", (dt.datetime.now(dt.timezone.utc).date() - checked).days)
        failed = 0
    except Exception as error:
        # Never include exception messages, URLs, tokens or provider payloads.
        print(json.dumps({"check": kind, "result": "failed", "category": type(error).__name__}))
    finally:
        metric(cw, kind.title() + "Failed", failed)
    return {"check": kind, "ok": not failed}
