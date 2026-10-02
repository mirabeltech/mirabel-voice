# Activate usage limits and monitoring

## Spending alerts removed, October 2, 2026

Tommy decided that Mirabel Voice's spending is too small to monitor. The service does spend money, mostly OpenAI and Anthropic usage (about $0.90 of AI usage in September), but nothing alerts on it any more. These were deleted with an administrator sign-in:

- The `mirabel-voice-infrastructure` AWS budget. It had been created account-wide by mistake, so its $20 limit was compared with the whole shared account (about $6,760 in September, almost all of it other projects' servers). It emailed Tommy, Surya Prakash and Mark at every threshold. Mirabel Voice's own AWS charges in September were under $5.
- The four `estimated-budget-100/150/180/200` CloudWatch alarms. None of them had ever fired.
- The `spend-monitor`, `unpriced-usage` and `stale-prices` alarms, which only kept the estimate accurate for those warnings. `stale-prices` was in ALARM when it was deleted.

Every deletion was read back from AWS. The previous settings, including the budget's notifications and recipients, are saved privately under `build_probe/budget-alerts-backup-20261002T161943Z/`.

`health` is now the only alarm that emails. Setup creates only that one, and all the deleted alarm names are in `RETIRED_ALARMS`, so a rerun deletes them if they reappear. The `--skip-aws-budget` option, the `aws_budget_tag` setting and the billing permission are gone.

The daily spending run still keeps the ledger and publishes `AIEstimatedUSD` and `EstimatedUSDWithAWSReserve` to CloudWatch. Anyone who wants the number can look there or run `scripts/usage_report.py`. Runaway provider usage would show up only on the OpenAI and Anthropic bills. Sections below dated before October 2 describe alarms that no longer exist.

## Fewer alerts and simpler emails, September 29, 2026

Eight alarms remain enabled. The `slow`, `relay-errors`, and `relay-throttles` alarms no longer send emails. AWS denied deletion with the deployment account, so their actions are disabled and all notification destinations are empty. An AWS administrator can delete those three inactive entries later.

Each remaining email description uses short lines for the problem, what to do, and what recovery means. AWS still adds its standard technical fields. The updated descriptions and disabled notifications were read back from AWS and verified. The monitoring schedule and remaining thresholds are unchanged. Existing account-wide AWS billing-budget emails are separate and unchanged.

Setup now creates only the eight wanted alarms. It deletes the three retired alarms when permitted, or disables their notifications if AWS denies deletion. Its generated permission request limits deletion to those three names. The operations tests cover removal, notification disabling, and unexpected AWS failures.

Private backups of the previous alarm settings are under `build_probe/alerts-backup-20260929T*.json`. The earliest backup contains the original descriptions and notification settings. An operator can restore an alarm by passing its saved configuration to CloudWatch `PutMetricAlarm`.

## Resumable spending ledger and plain-language alerts — September 18, 2026

The daily spending check timed out on September 16 and 18 (84 s and 80 s against a 75 s scan limit), because every run rescanned the month from the 1st. It now keeps a running total and counts only new logs; see [How the spending check works](#how-the-spending-check-works). All 11 alarm descriptions now say in plain words what ALARM and OK mean; see [Responding to alerts](#responding-to-alerts).

Deployed at 22:30 UTC by Tommy with a narrow script that changed only the monitor Lambda (code plus `SPEND_LEDGER_TABLE`), the monitor role's inline policy (ledger keys only), and the alarm descriptions. The previous state was saved privately under `build_probe/spend-ledger-backup-20260918T223029Z/`. The relay was not changed. That script is private (`build_probe/deploy_spend_ledger.py`). `setup_operations.py --apply` would have produced the same monitor and alarms, but it also redeploys the relay and resets its concurrency. After deployment, the health check passed. Two spending runs overlapped, because a second invocation started 61 seconds after the first. The first run counted 64 windows, then stopped at its time limit with its progress saved. The second run finished the remaining 8 windows. Month-to-date coverage reached 22:16 UTC. Each window's total is saved with a conditional write, so overlapping runs cannot count it twice. The alarm descriptions were read back and verified. `mirabel-voice-spend-monitor` stays in ALARM until that day's 20:46 UTC failure leaves its 24-hour window, which should be after the next daily run on September 19.


At Tommy's request, the live spending rule was changed from `rate(1 hour)` to
`rate(1 day)`. All seven spending-related alarms now use a 86,400-second period
with one evaluation period and one datapoint to alarm. Failed/missing checks
remain alertable; spending estimates and warnings now have daily cadence.
Health checks remain every 15 minutes.

The live rule and all seven alarm configurations were read back and verified.
The operations suite passes 28 tests. Previous rule/alarm settings were saved
privately under `build_probe/daily-spend-backup-20260915T204439Z.json`.
Only the schedule and alarm timing were updated; no Lambda deployment occurred.
This reduces scan frequency but does not repair the full-month scan timeout or
month-end accounting gaps documented in [the reliability review](spend-monitor-review-2026-09-15.md).
Recovery was verified on September 17, 2026: the daily scan completed and
`mirabel-voice-spend-monitor` moved from ALARM to OK at 20:47 UTC, sending the
recovery email. `mirabel-voice-unpriced-usage` remains in ALARM for the seven
historical unknown-cost requests, as intended.

Status: **operations activated on September 10, 2026** with `--skip-aws-budget`. Live checks confirm the rate-limit table is active with TTL enabled, the relay is configured for 20 requests per person per minute and concurrency 20, and both monitoring schedules are enabled. One email subscription is confirmed, which the owner has accepted as sufficient; the other two may remain pending. The owner confirmed receipt of the SNS test alert; email delivery is verified. The existing account-wide billing budget remains unchanged and is a separate administrator follow-up that the owner does not consider a blocker.

## Agreed operating target

- About 10 active users, with up to 50 expected.
- $200 monthly target, not an exact bill or an automatic spending cutoff.
- Initial per-person limit: 20 provider requests per UTC minute. A normal dictation uses transcription and cleanup, so this permits about 10 complete dictations per minute per person.
- Initial relay concurrency reservation: 20 in-flight requests. This is a starting capacity control, not a limit of 20 registered users. AWS must have enough unreserved concurrency quota.
- Reserve $20 of the target for infrastructure and monitoring. The daily estimate adds that allowance to estimated AI charges. No alert compares it with the target since October 2, 2026.
- Alert recipients are stored in the private deployment configuration, not this public repository.

The price file contains estimates, including an inferred audio-token rate. Unpriced requests are counted in the ledger rather than silently counting as free, but nothing alerts on them. Direct provider usage outside the relay is not included. Failed requests can still incur charges. These controls do not guarantee a $200 ceiling.

Official references: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [AWS budget notification delays](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

## Prepared checks

The scheduled monitor runs in AWS independently of Tommy's computer:

- Every 15 minutes, transcribe a short synthetic phrase through the public relay URL and ask the cleanup service for a known response. No employee recording is used. Two consecutive failed/missing checks trigger an alert; successful checks restore the alarm to OK and send recovery notification.
- The monitor records synthetic check latency without sending a slow-service alert.
- Once per day, bring the month's approximate AI spending up to date from the redacted usage logs (see [How the spending check works](#how-the-spending-check-works)). Synthetic checks are included. The result is published to CloudWatch; no alert watches it.
- No employee transcript, account identifier or credential appears in monitor output or alerts.

Price checks require periodic maintenance. CloudWatch alarms, Lambda, log reads, DynamoDB, SNS and synthetic provider requests can have running costs; check those against the infrastructure allowance after activation.

## Responding to alerts

`health` is the only alarm that sends email. The email names the alarm and includes a short explanation and a next step. "ALARM" means the condition triggered and "OK" means it cleared. The number in AWS's "Reason for State Change" is the measured value. The date in brackets is the start of the measured period, written day/month/year.

| Alarm | What it means | What to do |
|---|---|---|
| `health` | Two consecutive dictation checks failed or were missed. Checks run every 15 minutes. | Try a dictation. If it fails, ask the support owner to check the service. An OK email follows recovery. |

## How the spending check works

The monitor keeps a running total per UTC month in the rate-limit DynamoDB table, under keys starting with `spend-ledger#` (for example `spend-ledger#2026-09`). The monitor's role can reach only those keys. Each item holds the month's total, the unpriced-request count, and `covered`: the time up to which the logs have been counted.

Each daily run counts the logs after `covered` in six-hour windows. Each window's cost is added in the same conditional write that advances `covered`, so a crash, a timeout, or two overlapping runs cannot count a window twice. When a run runs out of time, the finished windows are kept and the next run continues from there. The run stops starting log reads 45 seconds before the Lambda timeout, so it has time to save progress and publish its metrics. If AWS is slow enough that the Lambda times out anyway, the saved windows are kept and the missing `SpendFailed` datapoint counts as a failure. Every spending metric, including `SpendFailed`, goes out in one request.

- **Month end:** each run finishes last month before starting this month, so usage near midnight on the 1st is counted in the right month.
- **Late logs:** only logs at least 15 minutes old are counted. A log that arrives in CloudWatch more than 15 minutes after its timestamp would be missed. Lambda logs normally arrive within seconds.
- **Price changes** apply only to windows counted after the monitor is redeployed. To recount a month with new prices, delete its `spend-ledger#YYYY-MM` item. The next run rebuilds it from the 1st, as long as the relay's logs for that month still exist. Only the current month is recreated automatically.
- **Partial totals:** a run that stops early still publishes the total so far. That figure is correct up to `covered_until`. It can be low but never high, so any spending warning it sets off is one the full total would also set off.

A trial against the live logs on September 18, 2026 (read-only) built September from the 1st in 72 windows and 55 seconds. Its total matched a single full-month scan exactly ($0.8998, 7 unpriced). A normal daily run is about four windows.

## Administrator handoff

Run preparation using the existing deployment account:

    build_probe\venv313\Scripts\python.exe scripts\setup_operations.py --config build_probe\operations-config.json

It makes read-only permission checks and writes:

- build_probe/operations-plan/administrator-permissions.json: a ready-to-use customer-managed IAM policy scoped to Mirabel resources.
- build_probe/operations-plan/preflight.json: the denied API checks.
- The private configuration contains the alert recipients supplied by Tommy.

An AWS administrator should review the generated policy, create it as a **customer-managed policy**, and attach it to the existing mirabel-voice-admin deployment identity. Keep its existing permissions. The policy does not grant permission to edit that user's permissions, read other applications' secrets, or pass arbitrary roles. The administrator may instead run setup with an appropriately authorized profile. Do not send AWS passwords or provider keys to the assistant.

After permission is granted, rerun preparation. It must pass before applying:

    build_probe\venv313\Scripts\python.exe scripts\setup_operations.py --config build_probe\operations-config.json --audio build_probe\synthetic.wav --apply

The WAV is an offline, synthetic recording saying “This is a routine service check,” no longer than ten seconds. It was generated with Windows text-to-speech; the microphone was not used.

Apply saves existing relay code/environment/concurrency privately, creates rate-limit and notification/monitor resources, preserves existing Google sign-in and update endorsement, then deploys the tested relay source with rate limits. Both one-off checks must pass before recurring schedules are enabled. On a relay change/check failure it attempts to restore saved code/environment/concurrency and disables the new schedules. Review the private backup if AWS also denies a rollback action. Resources created before a failure remain for inspection/retry.

Recipients must click **Confirm subscription** in the AWS email. A pending subscription cannot receive alerts; [AWS requires this confirmation](https://docs.aws.amazon.com/sns/latest/dg/sns-email-notifications.html). After confirmation, verify delivery to the required recipients using a clearly labeled test and check scheduled monitoring. Tommy accepted one confirmed recipient as sufficient and received the test; additional recipients are optional. Do not call setup complete based only on successful resource creation.

## Validation and remaining activation work

Focused automated tests cover costing, unpriced requests, calendar-month boundaries, pagination/deduplication, incomplete scans, semantic health checks, missing-data alarms, permission scope and preflight refusal without writes.

The first activation attempt created resources but failed during the relay configuration update because it reused a stale Lambda revision ID. Revision refresh and rollback handling have since been fixed and tested. Existing resources remain for inspection and retry.

A live synthetic baseline successfully transcribed the test phrase and checked cleanup in about 2.9 seconds. It used the existing dedicated smoke-test credential and did not change the relay. At initial preparation, 130 focused tests passed, including 12 operations checks; these are historical counts.

The current operations suite passes 27 tests, including activation without billing access, budget-scope refusal when budget management is requested, and settled-revision deployment/rollback. Activation, deployed rate-limit/concurrency settings and SNS email delivery have been verified. Actual provider account quotas and formal backup ownership remain operating follow-ups, not prerequisites to current use. Cost Explorer service-breakdown access remains denied; budget scoping is a separate administrator follow-up.


## Unpriced-usage alarm investigation (September 10, 2026)

The deployed monitor source matches `operations/monitor.py`. A direct invocation of its spending check completed successfully with `ok: true`. An independent read-only scan using the same pricing logic found seven unpriced cleanup requests, all `provider-400` responses for `claude-haiku-4-5`: five on September 4 and two on September 8. They contain no usage counts. No employee identities or request/response contents were needed for this investigation.

The alarm's displayed reason still describes its earlier missing-data transition. That text alone did not establish that metrics were still missing: the current spending invocation completed all metric publications, including `UnpricedRequests`. The seven historical unknown-cost requests exceed its threshold. Keep the alarm and conservative unknown-cost treatment; do not count failures as free or suppress the alarm to make the dashboard green. The monthly scan includes these records for the rest of September. Its priced-only estimate was $0.038994 at investigation time, excluding unknown costs, actual AWS infrastructure charges, and any provider usage outside the relay. This is not a verified total bill.

Direct CloudWatch metric-history reads are denied to the deployment identity. Verification used the deployed source, successful live invocation, independent usage-log scan, and alarm configuration/state. No alarm threshold, permissions, or production code was changed by this investigation.


## User acceptance and alert delivery test

The owner confirmed normal dictation works and accepted the earlier account-wide AWS charge as unrelated to this tool's activation; further billing investigation is not an activation requirement. This records the owner's decision, not an independently verified allocation of that bill.

At the owner's explicit request, a test was published to `mirabel-voice-alerts` with subject **Mirabel Voice - TEST alert (no action required)**. SNS accepted message `0ed39294-aed6-545a-b8c5-f188686f8235`; one email subscription was confirmed. The message explicitly says no outage or spending threshold triggered it. The owner confirmed receipt of this test email. Normal dictation and SNS email delivery acceptance checks are complete. This checks SNS delivery, not a simulated CloudWatch alarm transition.


Activation acceptance is complete: normal dictation works, usage limits and scheduled monitoring are enabled, and the owner received the test alert through the one required confirmed subscription. The seven historical requests with unknown costs remain flagged; the spending target is not a hard cutoff.

Owner maintenance decision: Surya Prakash is backup owner. Provider-key rotation is annual, with replacement keys stored in AWS; automatic rotation was not configured. Provider-quota review is explicitly deferred for current use, and actual provider limits have not been verified or changed. A separate live rotation/revocation acceptance exercise is not a release requirement. These decisions close #73; remaining release acceptance is tracked in #74 under parent #63.
