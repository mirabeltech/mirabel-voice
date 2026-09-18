# Spending monitor reliability review — September 15, 2026

## Conclusion

Use resumable processing of bounded time windows with durable, deduplicated usage records and explicit freshness/completeness tracking. Increasing the timeout alone does not address the verified recovery and month-boundary problems. First add safe scan diagnostics and explicit network/retry budgets so live measurements can size the worker and distinguish slow API responses from excess pagination.

This is a repository review, not an implementation or deployment. No production configuration was changed. Earlier live investigation confirmed `TimeoutError` in spending runs, deployed source matching `operations/monitor.py`, a 120-second Lambda timeout, and the spending alarm in ALARM while the health alarm was OK. The repository cannot establish actual page counts, throttling, or log-read latency for those runs: the monitor does not record them.

## Findings

1. **Repeated full scans have no saved progress** (`operations/monitor.py:49–85`). Each invocation starts at the first day of the UTC month. Totals, deduplication IDs, and pagination state exist only in memory. A timeout discards all work; the next hourly invocation repeats it. More history increases the work subject to the same 75-second/500-page bounds. This establishes a structural scaling risk, not proof that volume caused the live slowdown.
2. **The deadline is not a strict wall-clock bound** (`monitor.py:57–80,139`). Time is checked before each log API call, but not after the call or before returning a terminal page. An offline probe returned a successful estimate after a simulated 100-second terminal call. The client has no explicit connection/read/retry configuration and the handler ignores Lambda remaining time. API calls, retries, parsing, and later metric publication can overrun the scan allowance and potentially exhaust the function timeout.
3. **Month rollover leaves an accounting gap** (`monitor.py:51–55`). The first scan of a new month stops querying the previous month. Usage after the last previous-month scan, or previous-month events arriving late, has no final reconciliation. A simulated September 30 23:25 run followed by October 1 00:25 left September's final 35 minutes outside both query windows. Within the current month, full rescans can recover late events if those logs are still retained.
4. **Caught failures do not request Lambda error retries** (`monitor.py:148–153`). The handler emits `SpendFailed=1` but returns normally with `ok:false`. This is deliberate custom-metric failure signaling, not an unhandled function error. The next scheduled attempt starts over. The EventBridge target also sets delivery retries to zero and a 60-second event age (`scripts/setup_operations.py:358–360`); delivery policy is separate from Lambda processing retries. Merely enabling retries would not add saved progress.
5. **Failure diagnostics cannot explain scan performance** (`monitor.py:150`). Logs contain only check, failed result, and exception class. There are no page/event counts, elapsed API time, retry counts, completion watermark, or failure stage. `SpendFailed` also covers metric-publication failures, so its name alone does not locate the error.
6. **Publishing the result is not atomic** (`monitor.py:140–146`). Separate metric writes can publish an estimate and then fail on a later metric. Conversely, a scan failure emits no new total, correctly avoiding a misleading partial estimate. Future durable progress and metric publication must recover independently so a publication failure cannot lose accounted usage.

## Existing safeguards worth preserving

- CloudWatch event IDs are deduplicated within a scan.
- Empty intermediate pages with continuation tokens are handled correctly.
- Repeated tokens and the 500-page limit reject incomplete scans.
- A scan failure does not publish a partial total as complete.
- Unknown costs remain explicitly unpriced rather than silently free.
- Missing spending checks trigger an alarm.

## Recommended implementation and acceptance criteria

1. Record only operational diagnostics: bounded window, page/event counts, elapsed time, SDK retry count, failure stage, and last completed coverage. Do not log usage bodies, employee names, credentials, or transcripts. Measure representative live scans before selecting window size and throughput.
2. Bound each worker's API calls and retries, reserve time for saving progress and signaling status, and use Lambda remaining time. Check the deadline after API calls and before publishing a completed result.
3. Persist small time windows and event IDs in a dedicated store. Commit records and progress safely under crashes and overlapping invocations. Reprocessing must not double-charge an event; a continuation token alone is not a durable recovery design. Retain normalized usage inputs plus pricing version so price corrections remain possible.
4. Revisit recent windows for late arrivals and perform previous-month reconciliation. Define the supported lateness and log-retention horizon explicitly; no fixed overlap can promise recovery of arbitrarily late data. Older reconciliation/backfill must also be bounded and resumable.
5. Publish monthly estimates alongside coverage/freshness status, retaining the last completed result when work is incomplete. Alarm on stale progress even if the worker is running successfully. Retry publication without recounting usage.
6. Test slow terminal pages, throttling/retries, 500+ pages, crashes around every persistence boundary, concurrent workers, duplicate delivery, late events, month/year rollover, malformed/unknown usage, and partial metric failures. Verify catch-up throughput exceeds incoming usage under a representative backlog, then observe consecutive scheduled runs and alarm recovery before declaring the repair complete.

## Verification performed

- `build_probe/venv313/Scripts/python.exe -m pytest tests/test_operations.py -q`: **27 passed**.
- `build_probe/venv313/Scripts/python.exe build_probe/review_spend_monitor.py`: **six offline behavior probes passed**. They confirm current behavior, including the defects; they do not certify a repaired implementation.
- Reviewed the relay usage emitter, spend estimator/scanner, handler, alarm definitions, scheduling/deployment configuration, and operations runbook.
- No live throughput benchmark or new AWS invocation was performed during this repository review. Increased log volume versus slow requests/throttling remains unmeasured.

## AWS references

- [FilterLogEvents pagination](https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_FilterLogEvents.html): empty pages can still have continuation tokens.
- [Lambda asynchronous error handling](https://docs.aws.amazon.com/lambda/latest/dg/invocation-async-error-handling.html): function errors drive processing retries; duplicate delivery remains possible.
- [Boto3 configuration](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html): client retry behavior is configurable and can depend on configuration outside the call site.
