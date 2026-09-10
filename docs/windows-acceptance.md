# Windows release acceptance

Tommy is the sole manual tester. Version 0.9.3 is published and approved for in-app updates; Tommy confirmed upload to company Drive. The installed app updated/restarted successfully and normal dictation works. This does not establish a fresh-profile installation or universal Windows compatibility.

## Verified evidence

| Check | Evidence |
|---|---|
| Browser download and repair in existing profile | Tommy confirmed; recorded in merged PR #76. Fresh-profile installation remains untested. |
| Approved update and restart | 0.9.3 update/restart verified in the release thread; normal dictation confirmed again after operations activation. |
| Settings and ordinary apps | Tommy confirmed controls, retained settings and ordinary dictation. |
| Clipboard, changed destination and busy update | Tommy confirmed the final usage checks for 0.9.3. |
| Sleep/wake, microphone reconnection, offline/reconnect | Tommy reported these working; this does not cover every device, cancellation race or network condition. |
| Installation/update failure recovery | Automated isolated installation, repair, interrupted runtime/source recovery and removal; Windows CI passed for v0.9.3. No destructive test on Tommy's working installation. |
| Service operation | Rate limits and schedules deployed; normal dictation works; owner confirmed receipt of an explicitly labeled SNS test email. See service-operations-setup.md. |

## Remaining acceptance record — issue #74

- [ ] Fresh Windows profile: company Drive browser download, documented installation, Google work sign-in and first dictation with protections enabled. Record artifact/hash, app version, Windows build/architecture and Smart App Control state. Use a separate test profile where available.
- [ ] Explicit Google sign-in refresh/recovery observation; current normal dictation does not prove every refresh path.
- [ ] Long non-sensitive dictation; network interruption with cancellation and no late paste. Automated size/fallback/cancellation checks exist; record manual result or explicit deferral.
- [ ] Owner-controlled recovery/repair/removal, startup off/on, and support export spot-check where feasible. Isolated automated checks exist; do not damage the only working installation.
- [ ] Record unavailable microphone, accessibility/scaling, elevated-app and remote-desktop configurations as untested. No additional employee testing cohort is required.
- [ ] Tommy records broader rollout decision with the above results or explicit deferrals. Do not silently convert untested cases to passes.

Use only non-sensitive sample speech. Never disable Windows security as an installation step. Keep private account details, credentials, speech/text and service URLs out of public evidence. The selected route remains the free company Drive Python ZIP, Google work sign-in and in-app updates; Store packaging and paid signing are out of scope.

Completed implementation issues #64–#72 are reconciled into this acceptance record. Their closure records implementation/release evidence, not a claim that all optional hardware or manual edge cases were tested.
