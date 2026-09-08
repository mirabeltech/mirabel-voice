Mirabel Voice — Windows release readiness PRD

Date: 8 September 2026. Product owner and sole acceptance tester: Tommy. Status: implementation prepared locally as 0.9.0; automated verification recorded separately. Tommy's acceptance, production configuration/deployment and release approval remain pending.

**Purpose**

Make Mirabel Voice easier to download, install, and use, and make updates dependable enough for organization-wide distribution. Someone should be able to install from one shared link, sign in, test their microphone, and dictate. An update or temporary internet problem should not destroy a working installation or leave the app stuck.

This PRD supersedes the audit's proposed multi-employee pilot and software-portal dependency. Tommy is the only manual tester. There is no Intune/Company Portal rollout, employee test group, or mandatory multi-day pilot. Automated tests and clean Windows environments operated by Tommy or the developer supplement his testing where available. Untested Windows versions, hardware and security configurations must be listed as unverified rather than claimed to work universally.

**Distribution decision**

Keep the existing company-restricted Google Drive distribution and one stable download link. A software portal is not required. Do not publish a configured bundle, credentials, private service addresses or diagnostic data to this public repository or its issues.

**Final owner decision: improve the existing free Python ZIP installation from Google Drive.** This is the selected distribution method, not a temporary fallback. Microsoft Store/MSIX investigation, developer-account registration, certification, paid signing and software-portal deployment are out of scope. No new Microsoft account, subscription or certificate is required for this plan. The earlier Store recommendation in issue #64 and the installation investigation is superseded.

Keep the existing Google work-account sign-in and in-app updater. Shorten the download/install instructions, reliably identify the right ZIP, and make the bootstrap, tray and background updates follow one approval policy. Provide current-user Start-menu launch, startup preferences, repair and removal through the bundle workflow; a separate signed installer is not a requirement.

The existing Python bundle has worked with Smart App Control enabled, but fresh browser downloads have required an Unblock step. Document that step clearly when needed for the trusted company download, before extraction. Test the actual browser-download path and all native components used by the app; a successful local-file launch alone is insufficient. Do not promise a restriction-free install or describe unblocking as a general security-policy bypass. Do not ask employees to disable Windows protections. If the selected ZIP still fails, capture the specific block and address it within this scope; do not silently reopen Store or paid-signing work.

Preserve download integrity at no signing-service cost: verify the ZIP against release metadata obtained from a trusted source before executing its installer. A checksum supplied only inside the same ZIP is insufficient. This integrity check is separate from Windows trusting the executable components and does not claim to replace Authenticode signing. Coordinate the exact mechanism in R2 without adding developer-account setup for Tommy or employees.

**User outcomes and release requirements**

| ID | Priority | Requirement | Acceptance |
|---|---|---|---|
| R1 | Release gate | Download and install without a software portal | One stable shared link identifies the current approved artifact and version. The Google Drive Python ZIP installation completes in Tommy's clean user profile with Windows protections enabled. Missing permissions, partial download, blocked components and unsupported architecture give a clear next step. Document exactly what was tested. |
| R2 | Release gate | Only approved releases install through updates | Tray, background updater and bootstrap use the same relay approval and hash rules. No approval, expired sign-in, malformed response or hash mismatch keeps the working version. An approved older version can be installed to undo a bad release. The initial ZIP is checked against trusted release metadata before its installer executes, without paid signing or a developer account. |
| R3 | Release gate | Failed installation/update preserves a working copy | Stage and prove the replacement before switching. Disk full, locked files, access denied, failed copy, failed startup and interruption leave the old app usable or automatically recoverable. Retain settings and credentials. A stable recovery entry point works even when the app package is incomplete. |
| R4 | Release gate | Updates never interrupt dictation or compete | One installation-wide update coordinator handles all entry points. Repeated clicks and simultaneous background checks cannot race. Restart waits until microphone capture, transcription and paste complete. Show distinct outcomes: current, updated, deferred, approval unavailable, failed, or full bundle download required. |
| R5 | Release gate | Test the exact employee download | CI builds and runs the Python bundle using non-production configuration. Pin compatible runtime and dependencies with hashes, inventory native components, and scan dependencies. Test the configured release through the same process without exposing its private configuration. Installed version, source version and artifact version agree. Preserve artifact hash and last known-good download. |
| R6 | Release gate | Slow internet and long speech fail clearly and recover | Provisional transcription deadline: 120 seconds total including retries; cleanup deadline: 20 seconds total. Confirm these budgets with real use. Cancel remains available and suppresses late paste. Enforce relay payload limits before upload, including request overhead; test five-minute speech and forced WAV fallback. Retain a failed recording only in bounded memory for an explicit retry/discard action; never create a silent disk recording history. |
| R7 | Release gate | Settings and sign-in survive interrupted writes | Save settings and encrypted sign-in data by atomic replacement. Validate types/ranges and recover a last known-good copy. Explain an unreadable file without overwriting it or silently dropping the user's credentials. Logs omit secrets. |
| R8 | Release scope | Everyday controls work without editing JSON | First-run flow offers sign-in, microphone level test, key selection and scratch dictation. Controls expose pause/resume microphone and start-with-Windows. Follow the current system-default microphone after device changes, preserving explicit selection. Display the actual key/mode. Preserve existing language and translation controls. |
| R9 | Release gate | Dictation never silently destroys the clipboard or lands after cancellation | Test text, image and rich-text clipboard behavior; preserve supported original formats or explicitly define a safe alternative. Suppress automatic paste if a known focus change occurs, including same-app document changes where detectable; keep copy/paste-last recovery. Explain unsupported elevated/remote targets and clipboard-history implications. Do not equate simulated keystrokes with confirmed delivery. |
| R10 | Release gate | Service remains supportable as usage grows | Validate models, request sizes, output limits and per-user request budgets on the relay. Agree expected peak usage with Tommy and test simulated load; no employee load-test group. Record provider/Lambda limits and a controlled overload response. Set ownership, alerts and a model/runtime review process. Reference existing organization-key issue #46 rather than duplicate it. |
| R11 | Release gate | Tommy can verify the release and get useful help | Provide the checklist below and record pass/fail/not-tested, artifact hash, versions, and Windows protection state. Add a redacted support export and truthful install/privacy/offline/update instructions. Tommy's update result is pending until he reports it. |

“Release gate” means a correctness or reliability condition required for approval. R8 usability improvements belong in this release, but an individual enhancement may be deferred explicitly if the existing control is usable. No date, budget, or external service purchase is committed here.

**Tommy's acceptance checklist**

Use non-sensitive sample speech. Record results in the acceptance GitHub issue. The developer supplies the exact approved artifact and prepares automated failure tests; Tommy need not intentionally corrupt his working installation.

| Check | What Tommy does | Pass result |
|---|---|---|
| Install | Download the Python ZIP through the browser from the shared Drive link and follow only the published steps, including Unblock if required, in a fresh profile/environment where available. | No extra developer tools, security-disable instructions, or missing steps; app starts and shows its version. |
| Sign-in and first dictation | Sign in, test the microphone, choose a usable key, and dictate into a scratch text box. | Words appear once, the key is clear, and microphone state is visible. |
| Regular use | Use his usual browser/editor/email apps, available microphones, pause/resume, and a sleep/wake cycle. | App stays responsive and captures from the selected microphone. Unavailable hardware is marked untested. |
| Working update | Note current version; choose Check for updates after an approved release is available; note the result and resulting version. | Approved version is shown after restart, settings remain, and a new dictation works. Tommy has volunteered to perform this check; no result is assumed. |
| Busy update | Trigger an update while a harmless test dictation is being processed. | Recording/text completes before restart; no duplicated or lost result. |
| Recovery | Developer demonstrates automated interrupted-update recovery and approved rollback; Tommy confirms the recovered app dictates. | Prior working version returns with settings retained. No destructive test against Tommy's only working copy. |
| Network problem | Temporarily disconnect during a non-sensitive test, cancel or retry as offered, then reconnect. | Clear bounded failure, responsive controls, and no unexpected late paste. |
| Repair and remove | Exercise repair and uninstall in the test profile/environment. | App can be repaired; uninstall removes app/startup entries; settings retention is explicit. |

Automated tests cover cases Tommy cannot reproduce readily: disk full, locked files, concurrent updates, invalid approval/hash, expired credentials, large requests, provider 429/5xx, settings corruption, late callbacks and dependency mismatch. A Windows environment with Smart App Control disabled does not count as evidence of compatibility with it enabled. If no protected test environment is available, record that gap; do not invent employee testing as a requirement.

**Order of work**

1. Simplify the selected Google Drive Python ZIP installation and verify the actual fresh-download path with Smart App Control enabled. In parallel, finish approval enforcement and build the exact runtime in CI. No Store or signing feasibility task precedes this work.
2. Implement installation recovery and a shared update coordinator, followed by network/payload and settings recovery.
3. Complete daily-use/clipboard improvements, service safeguards and accurate support documentation.
4. Run automated checks and Tommy's acceptance checklist against one identified artifact. Record the deployment state of each fix; source-code tests alone do not mean users have it.
5. Tommy decides whether to release based on recorded results and explicit untested configurations. Keep the previous download ready for recovery. There is no multi-employee pilot requirement.

The audit's in-app approval validation and approved downgrade changes already exist locally and passed the suite (426 tests). They still require review/integration and testing through all update entry points. Do not rebuild them blindly or treat them as already deployed. Existing closed issues #35 (Smart App Control) and #47 (relay endorsement) provide history; new follow-up issues cover the gaps found in the audit. Existing open issue #46 covers organization-owned provider keys.

**Maintenance and success measures**

Success means Tommy completes the chosen installation and a real approved update, his normal dictation works after restart, simulated failures preserve the app/settings, and all release gates have recorded outcomes. Report verified Windows build/architecture and security state instead of promising every Windows PC is supported.

At each release: build/test the real artifact, scan its dependencies, verify versions and signatures, and demonstrate update/rollback. Plan a daily non-sensitive service check with bounded cost, actionable outage/latency alerts, a monthly dependency/model lifecycle review, and a named owner plus backup. Agree actual thresholds, alert destination, and spending limits before enabling cloud schedules or buying services. Building this plan does not itself deploy monitoring.

**Out of scope**

Employee testing groups; software-portal deployment; universal Windows compatibility claims; switching off Windows security as an install step; public distribution of a privately configured bundle; credential rotation already tracked in #46; new dictation history, streaming architecture, or Microsoft Store/MSIX investigation, packaging, developer registration, certification or publication; purchasing signing services or deploying the planned changes during PRD creation.

GitHub issue links are recorded below. The parent issue contains this PRD in full so it is readable before this local document is committed.

**Implementation tracking**

See [implementation and verification record](../implementation-release-readiness.md) for the completed local changes and remaining release gates. Checkboxes below remain open until acceptance/deployment is verified; they do not mean implementation has not started.

Parent PRD: https://github.com/mirabeltech/mirabel-voice/issues/63

- [ ] [R1 — [Release] Simplify the free Google Drive Python ZIP installation](https://github.com/mirabeltech/mirabel-voice/issues/64)
- [ ] [R2 — [Release] Enforce one approved-release policy across installation and all update paths](https://github.com/mirabeltech/mirabel-voice/issues/65)
- [ ] [R3 — [Release] Preserve a working installation through failed or interrupted updates](https://github.com/mirabeltech/mirabel-voice/issues/66)
- [ ] [R4 — [Release] Serialize update checks and restart only after dictation finishes](https://github.com/mirabeltech/mirabel-voice/issues/67)
- [ ] [R5 — [Release] Build, scan and smoke-test the employee Python bundle in CI](https://github.com/mirabeltech/mirabel-voice/issues/68)
- [ ] [R6 — [Release] Bound network waits and recover safely from long or failed dictations](https://github.com/mirabeltech/mirabel-voice/issues/69)
- [ ] [R7 — [Release] Save settings and sign-in atomically and recover damaged configuration](https://github.com/mirabeltech/mirabel-voice/issues/70)
- [ ] [R8 — [Usability] Guide first-run setup and expose microphone and startup controls](https://github.com/mirabeltech/mirabel-voice/issues/71)
- [ ] [R9 — [Release] Protect clipboard content and make text delivery failures recoverable](https://github.com/mirabeltech/mirabel-voice/issues/72)
- [ ] [R10 — [Release] Add relay usage limits and a sustainable service maintenance plan](https://github.com/mirabeltech/mirabel-voice/issues/73)
- [ ] [R11 — [Release] Record Tommy-only acceptance and publish accurate installation/support guidance](https://github.com/mirabeltech/mirabel-voice/issues/74)
- [ ] Existing prerequisite: [Organization-owned provider keys #46](https://github.com/mirabeltech/mirabel-voice/issues/46)
