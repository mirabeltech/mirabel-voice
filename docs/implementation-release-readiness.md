# Current implementation status — September 10, 2026

The September 8 preparation notes below are historical. They are superseded where they say local-only, unapproved updates, blocked monitoring, pending Drive upload or open provider-key ownership:

- PRs #75/#76 and #78–#80 merged; v0.9.3 is published with successful Windows bundle CI. Tommy confirmed Drive upload, normal dictation and the final clipboard/destination/busy-update usage checks.
- Issues #64–#72 track completed implementation. Remaining manual acceptance belongs to #74 and [windows-acceptance.md](windows-acceptance.md); no untested case is implicitly passed.
- Operations are deployed with per-person/concurrency limits, health/spending schedules and confirmed SNS test delivery. PR #77 publishes the current setup, revision/rollback fixes and budget-independent activation option. #73 remains open until merge and operating follow-ups are recorded.
- Company-owned provider keys were confirmed by Tommy and #46 is closed.
- Parent #63 remains open for #73 and #74. Fresh-profile install/Google sign-in/first dictation and explicit remaining acceptance results or deferrals are still needed for the broader rollout record.

## Historical implementation evidence

# Windows release-readiness implementation

Prepared locally on 8 September 2026 as **Mirabel Voice 0.9.0**. This is an implementation/verification record. Tommy has authorized publishing the tested download and its installer/approval metadata for the final Drive installation check. Source endorsement and relay deployment are separate; organization-wide rollout checks remain open.

## Changes

| Requirement / issue | Local implementation | Remaining release evidence |
|---|---|---|
| R1 / #64 | One Drive ZIP workflow, version-aware discovery, independent approval/hash verification, current-user installation/repair/removal and clear architecture errors. Long-path copy/extraction/import/cleanup works without changing Windows policy. | Tommy's fresh browser download with protections on; publish the approved ZIP/hash after acceptance. |
| R2 / #65 | Bootstrap update requests go to the same app coordinator; relay approval remains required and malformed/missing approval fails closed. Older approved source rollback remains possible. | Publish/endorse only a tested release; live update result pending. |
| R3 / #66 | Staged startup checks, installation lock, transaction journal, retained previous package/runtime and stable recovery launchers. Settings preserved. | Tommy confirms dictation after recovery in his test environment. |
| R4 / #67 | One coordinator handles timer/tray/request-file checks. Recording, processing and pending paste delay switching/restart. | Tommy's busy-update and ordinary update test. |
| R5 / #68 | Actual Python ZIP CI, Python 3.13.15 x64 runtime checksum, hashed runtime/build dependency locks, native inventory, vulnerability scans and installed-bundle smoke workflow. Runtime/format contracts reject incompatible source-only updates, including legacy --config probes. | Hosted CI after review/push; candidate browser-download acceptance. |
| R6 / #69 | Wall-clock budgets, no automatic SDK retries, processing cancellation suppresses late insertion, bounded in-memory retry/discard, audio plus UTF-8/multipart size budget, explicit raw-transcript fallback. | Tommy's real connection failure, long speech and latency checks. |
| R7 / #70 | Atomic settings and encrypted sign-in replacement, validated backup recovery, preserved damaged files, type/range validation and unreadable-sign-in guidance. | Actual work-account sign-in/refresh in the configured candidate. |
| R8 / #71 | First-run practice box, level display, keyboard-focusable buttons, startup preference, microphone pause/resume and Windows default-endpoint change detection. | Tommy's first run, device change, sleep/wake and visual/accessibility checks. |
| R9 / #72 | Rich/image clipboard uses typing without replacing original formats; restore honors intervening copies and paste errors do not repeat automatically. Window/focused-control/title checks suppress known destination changes. | Real clipboard formats and normal/elevated/remote target coverage where available. |
| R10 / #73 | Relay model/body/output validation, optional shared DynamoDB rate counter, controlled 429/503 outcomes and a synthetic service-check command. Maintenance/runbook prepared. | User/concurrency estimates, table/IAM provisioning, rate/concurrency/spend limits, owner/backup, alert destination and actual deployment. Existing organization-key issue #46 remains open. |
| R11 / #74 | Plain installation/privacy/recovery documentation, allowlisted support export and Tommy-only acceptance checklist. | Tommy's recorded results and release decision. |

## Verification

The initial source passed **468 automated tests** under Python 3.13.15 on Windows x64. The candidate build passed 467 tests; the additional native Windows-encryption regression was added afterward without changing application code. Tests include refused approval/tampered/traversal ZIPs using the real PowerShell bootstrap; atomic-write failures, backup recovery and a real Windows-encrypted sign-in backup round trip; source-update interruption/rollback; cancellation and late responses; full five-minute forced-WAV rejection; multibyte custom-word upload overhead; and simulated relay overload (5 successful requests and 45 controlled rejections).

Both hashed dependency scans report **no known vulnerabilities**: [runtime packages](evidence/windows-0.9.0/runtime-dependency-audit.json) and [build/test/audit tools](evidence/windows-0.9.0/build-tools-audit.json). `pip check` passes. This does not establish absence of unknown vulnerabilities or scan the Windows/Python runtime itself. Python 3.13.15 was selected from [Python.org's Windows releases](https://www.python.org/downloads/windows/), checked on the preparation date, and its official downloaded archive was hashed. The package runtime contract and separate bundle-format marker make older runtime/source-only combinations fail their startup proof before approval.

The Windows host reports build **10.0.26200**, **AMD64**, with `VerifiedAndReputablePolicyState = 1` (Smart App Control enabled). The test ZIP passes app imports, Tcl initialization and synthetic audio encoding under that host. The native inventory has **81 components: 35 valid signatures and 46 unsigned**. It is deliberately not described as an entirely signed bundle.

Both the produced dummy-config ZIP and the configured private candidate pass installation, same-version repair, retained settings, interrupted runtime recovery, interrupted source-package recovery and removal in a disposable path, using `scripts/verify_bundle.ps1`. That test initially exposed Windows path-length failures; copying, extraction and deletion now use long-path-capable operations and the bundle normalizes its own import paths. No persistent Windows policy or registry change was made for long-path support. Shortcuts and startup/uninstall registry integration are deliberately skipped in this automated test so it cannot alter Tommy's existing installation; those integrations remain in his isolated-profile checklist.

Follow-up extraction regression: Tommy's local test exposed a failure in the final ZIP after documentation entries were added with forward-slash names. Windows PowerShell's .NET extraction rejected those names under an extended-length destination. The bootstrap and bundle verifier now normalize member separators before extracting, retaining path validation and long-path support. All five bootstrap integration tests pass from `C:\Windows\System32`, including mixed separators, directory entries, verified file contents beyond 260 characters, and rejection of unapproved, changed or traversal ZIPs. The exact frozen private candidate was then rechecked successfully for installation, repair, retained settings, interrupted runtime/source recovery and removal in a disposable folder. This fixes the local bootstrap; the candidate ZIP and its approval hash are unchanged.

Follow-up Settings fix: Tommy confirmed controls now work. At his request, Settings closes on an outside mouse press, while keyboard-focus changes alone do not dismiss it. A mouse listener observes presses without suppressing them and checks native window ownership, including explicitly registered ttk dropdown windows. The listener stops on hide/destruction and stale queued clicks cannot close a reopened card. Losing focus still disarms shortcut capture. All 29 flyout tests pass on Windows, including a native Tk dropdown/control ownership test and checks for outside presses, inside presses, releases and stale callbacks. The private candidate and matching local QA manifest/hash were refreshed; organization distribution remains unapproved. Tommy subsequently confirmed the final Settings behavior, dictation, restart, sleep/wake, microphone reconnection and connection recovery.

Native Tk controls can be constructed and expose keyboard-focusable buttons/practice input. A screenshot from the available desktop session returned black, so visual appearance is not marked verified. Tommy has since reported successful real dictation and the everyday checks above. Fresh browser-download/Mark-of-the-Web acceptance, explicit sign-in refresh and a real approved update installation remain unverified.

Publication verification: the current Windows suite passes **475 tests**. The 27 current application Python files match the tested ZIP. The frozen ZIP also contains an unused legacy `streaming.py` module from its earlier build directory; current source does not import it. Its bytes are retained to preserve the exact artifact Tommy tested. The public installer and manifest enable download verification; Drive upload and browser-origin installation remain pending.

## Handoff

The [candidate filename and SHA-256](evidence/windows-0.9.0/candidate.json) identify the exact private build. The configured ZIP is a **private local candidate** in `dist/MirabelVoice-0.9.0-python.zip`. Do not confuse it with `dist/test-only/MirabelVoice-0.9.0-python.zip`, which uses a deliberately invalid relay. Keep configured files and private logs out of public GitHub artifacts/issues. Tommy authorized the exact artifact in `packaging/bundles.json` for download verification; a passing local build alone is not approval.

Version 0.9.0 replaces the Python runtime, so existing users need one full ZIP install/repair rather than a source-only update. The stable install command must be published together with the reviewed manifest before organization distribution. Do not use an older public bootstrap as evidence for the new workflow.

Use [Tommy's checklist](windows-acceptance.md) and [the service setup/maintenance decisions](service-maintenance.md) before release. Only Tommy tests manually; no employee pilot or developer-account registration is required. Cloud monitoring and rate limits remain unconfigured until the owner supplies the missing operating decisions.
