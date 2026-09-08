# Service operation and release prerequisites

Implementation does not enable cloud schedules, create tables, change production limits or authorize spending. The live relay has not been deployed as part of these local checks.

## Limits implemented

Production relay construction enables request validation: 4,100,000 bytes maximum incoming body, cleanup JSON up to 256,000 bytes, at most 8,000 output tokens, plain-text messages, no streaming/tools/remote image inputs, and a small approved model list in `src/mirabel_relay/limits.py`. The client rejects uploads over 4,000,000 bytes before sending, leaving room for multipart fields and Lambda's base64 envelope. An oversize WAV fallback gives a shorter-recording/encoder-repair instruction and retains one recording in memory for retry/discard. No paid request is made for a rejected body.

The model list includes the configured GPT-4o transcription models, whisper-1, and Claude Haiku 4.5 alias/snapshot. Changing models requires reviewing the list, compatibility tests, pricing and lifecycle together. A returned provider error is not evidence the user should repeatedly retry; the app disables automatic SDK retries and offers explicit recovery.

Optional per-person limits use a **shared DynamoDB atomic counter**, not a separate count in each Lambda container. Configure both `MIRABEL_RATE_LIMIT_TABLE` and `MIRABEL_REQUESTS_PER_MINUTE`; deployments preserve existing values. Missing both leaves request validation enabled but **does not enforce a per-person rate limit**. Half a configuration prevents startup. Exceeding a configured budget returns 429; a counter outage returns 503 before contacting a provider.

The table needs string partition key `pk` and TTL attribute `expires`. Grant only `dynamodb:UpdateItem` on that table to the relay role. Keys contain a hash of authenticated identity plus minute, never the credential. Each transcription and cleanup is a separate request. This fixed-minute budget limits bursts within a minute; it is not a monthly spending cap. Table/alert resources may have costs, so provision them only after the owner agrees thresholds and spending.

## Before production release

| Decision or check | Current status |
|---|---|
| Expected users, concurrent dictations and requests/minute | Awaiting Tommy |
| Per-person request budget; organization concurrency cap | Awaiting usage decision; no live change |
| Actual provider account/model quotas | Owner must record from the accounts; not inferred from public defaults |
| Lambda memory, timeout, reserved/account concurrency, Function URL payload limit | Owner must record current deployed settings; client/relay budget uses conservative body margins |
| Owner and backup for incidents, alerts and model changes | Awaiting names/contact destination |
| Monthly spend ceiling and warning thresholds | Awaiting owner; no cloud schedule or budget alert enabled |
| Organization-owned provider keys | Existing issue #46; verify before rollout |

Use a mocked provider for simulated load first: concurrent requests must be denied cleanly when the shared counter's atomic condition fails. Then run a small agreed real-service check using synthetic speech. Never use employee recordings for a load test. Account-level throttling and overall concurrency still require owner configuration; a per-person limit alone does not cap total organizational spend.

## Routine checks and response

The prepared command `.venv\Scripts\python.exe scripts\service_check.py` checks local imports/encoding without microphone or network. With `--live --audio <synthetic-speech.wav>`, it makes one transcription and one cleanup request using the configured relay. Supply a synthetic phrase of at most ten seconds. Output contains pass/fail category and latency, never transcripts, credentials or provider response bodies. Live checks incur normal provider charges. Run manually first; daily scheduling is pending approval of cost and alert destination.

At production setup, create alerts for failed service checks, sustained provider/relay 429 or 5xx, latency exceeding the agreed budget, Lambda errors/throttles, and actual versus forecast monthly spend. Test delivery to the named owner and backup. Record exact thresholds, destination and test time in private operations notes. A plan or script is not an active alert.

For an outage: keep the working desktop release; inspect redacted status/usage metrics, provider status and credentials; stop rollout if errors began with a release. Re-endorse the previously tested source release when dependencies match, or restore the previous full ZIP for runtime changes. Make one synthetic check and verify a fresh dictation before resuming rollout. Do not repeatedly restart every client or ask people to disable security controls.

Monthly, review dependency advisories, Python/Tk/Windows support, provider model deprecations, quota/cost trends, and token/key ownership. The candidate moves to Python 3.13.15, listed as an August 2026 Windows release by [Python.org](https://www.python.org/downloads/windows/) (checked 8 September 2026). The pinned runtime makes builds reproducible; pinning does not establish that an old runtime remains supported or free of vulnerabilities. Review runtime security releases separately from the Python-package audit and rebuild/retest the full bundle when needed. At each release, preserve the ZIP/hash, inventories, dependency audit and Tommy's results, and keep the last working private download.
