# Activate usage limits and monitoring

Status: prepared and tested; **not activated**. The current AWS deployment identity is denied the required operations APIs. Existing desktop installation and live relay settings are unchanged.

## Agreed operating target

- About 10 active users, with up to 50 expected.
- $200 monthly target, not an exact bill or an automatic spending cutoff.
- Initial per-person limit: 20 provider requests per UTC minute. A normal dictation uses transcription and cleanup, so this permits about 10 complete dictations per minute per person.
- Initial relay concurrency reservation: 20 in-flight requests. This is a starting capacity control, not a limit of 20 registered users. AWS must have enough unreserved concurrency quota.
- Reserve $20 of the target for infrastructure and monitoring. AI usage warnings compare estimated AI charges plus that allowance with $100, $150, $180 and $200.
- A separate $20 AWS infrastructure budget warns at 50%, 80% and 100%. It is account-wide: unrelated AWS charges, if any, also count. Its billed-cost alerts can lag.
- Alert recipients are stored in the private deployment configuration, not this public repository.

The price file contains estimates, including an inferred audio-token rate. Compare actual provider bills and revise rates routinely; unpriced requests raise an alert rather than silently counting as free. Direct provider usage outside the relay is not included. Failed requests can still incur charges. These controls do not guarantee a $200 ceiling.

Official references: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), [AWS budget notification delays](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).

## Prepared checks

The scheduled monitor runs in AWS independently of Tommy's computer:

- Every 15 minutes, transcribe a short synthetic phrase through the public relay URL and ask the cleanup service for a known response. No employee recording is used. Two consecutive failed/missing checks trigger an alert; successful checks restore the alarm to OK and send recovery notification.
- Combined synthetic check latency of 15 seconds or more in two consecutive periods raises a slow-service alert.
- Every hour, calculate approximate AI spending for the current UTC calendar month from existing redacted usage logs. Include synthetic checks, deduplicate paginated events, and refuse to report a completed total when the scan exceeds its deadline or page budget.
- Raise alerts for failed/missing spending checks, unpriced requests, price data older than 30 days, sustained Lambda errors and throttling.
- Budget alerts do not shut down dictation. No employee transcript, account identifier or credential appears in monitor output or alerts.

Price checks and spending scans require periodic maintenance. The month-to-date scan is bounded to 500 pages and 75 seconds; if usage grows beyond that, migrate to an incremental cost ledger. CloudWatch alarms, Lambda, log reads, DynamoDB, SNS and synthetic provider requests can have running costs; check those against the infrastructure allowance after activation.

## Administrator handoff

Run preparation using the existing deployment account:

    build_probe\venv313\Scripts\python.exe scripts\setup_operations.py --config build_probe\operations-config.json

It makes read-only permission checks and writes:

- build_probe/operations-plan/administrator-permissions.json: a ready-to-use customer-managed IAM policy scoped to Mirabel resources.
- build_probe/operations-plan/preflight.json: the denied API checks.
- The private configuration contains the three email recipients supplied by Tommy.

An AWS administrator should review the generated policy, create it as a **customer-managed policy**, and attach it to the existing mirabel-voice-admin deployment identity. Keep its existing permissions. The policy does not grant permission to edit that user's permissions, read other applications' secrets, or pass arbitrary roles. The administrator may instead run setup with an appropriately authorized profile. Do not send AWS passwords or provider keys to the assistant.

After permission is granted, rerun preparation. It must pass before applying:

    build_probe\venv313\Scripts\python.exe scripts\setup_operations.py --config build_probe\operations-config.json --audio build_probe\synthetic.wav --apply

The WAV is an offline, synthetic recording saying “This is a routine service check,” no longer than ten seconds. It was generated with Windows text-to-speech; the microphone was not used.

Apply saves existing relay code/environment/concurrency privately, creates rate-limit and notification/monitor resources, preserves existing Google sign-in and update endorsement, then deploys the tested relay source with rate limits. Both one-off checks must pass before recurring schedules are enabled. On a relay change/check failure it attempts to restore saved code/environment/concurrency and disables the new schedules. Review the private backup if AWS also denies a rollback action. Resources created before a failure remain for inspection/retry.

Recipients must click **Confirm subscription** in the AWS email. A pending subscription cannot receive alerts; [AWS requires this confirmation](https://docs.aws.amazon.com/sns/latest/dg/sns-email-notifications.html). After confirmation, verify delivery to all three addresses using a clearly labeled test and check that both schedules report fresh metrics. Do not call setup complete based only on successful resource creation.

## Validation and remaining activation work

Focused automated tests cover costing, unpriced requests, calendar-month boundaries, pagination/deduplication, incomplete scans, semantic health checks, missing-data alarms, permission scope and preflight refusal without writes.

The live relay was inspected read-only. Rate-limit environment settings are absent. AWS denied concurrency, DynamoDB, CloudWatch alarms, SNS, EventBridge and Budgets checks. No permission change, monitoring resource creation, subscription email or production relay update has been performed by this setup.

A live synthetic baseline successfully transcribed the test phrase and checked cleanup in about 2.9 seconds. It used the existing dedicated smoke-test credential and did not change the relay. The final focused suite passes 130 tests, including 12 operations checks.

Activation, actual email delivery, deployed rate-limit/concurrency checks and review of real provider/account quotas remain pending administrator access.
