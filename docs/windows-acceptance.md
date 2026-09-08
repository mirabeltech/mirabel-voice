# Tommy's release check

Tommy is the only manual acceptance tester. Automated checks supplement his testing. No employee pilot is required.

**Current status: not approved for organization-wide release.** The code and test build do not establish fresh-download compatibility or a successful production update. Complete the rows below against one configured ZIP. Do not test destructive failures against your only working copy.

For a first local check on Tommy's current Windows computer, quit Mirabel Voice and run this in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Dev\mirabel-voice\build_probe\Test-MirabelVoice.ps1"
```

This uses the prepared private 0.9.0 candidate and its separate local test manifest, preserves settings, and starts the new app. It has **not** been run against Tommy's working installation by the developer. This local install does not replace the fresh browser-download check below. Do not send this machine-specific test command to employees.

Record the ZIP filename and SHA-256, app version, Windows version/build, x64/other architecture, Smart App Control state, account type, and date. The developer can supply the artifact details. Keep private account information out of public issues.

| Check | Your action | Result |
|---|---|---|
| Fresh installation | Download the configured ZIP from company Drive in a browser and follow README in a fresh Windows profile if available. Leave protections on. | Pending Tommy |
| Settings controls | Open dropdowns, select a language/microphone, click buttons and type in the practice box. Settings stays open for controls and dropdowns; clicking anywhere outside, Escape or Finish setup closes it. | Passed: Tommy confirmed the final Settings behavior |
| First use | Sign in, choose microphone/key, dictate a harmless sentence into the practice box. Check it appears once. | Pending Tommy |
| Your usual apps | Try your email, browser and editor. Keep the destination selected until text arrives. | Passed: Tommy reported Notepad/usual-app dictation works |
| Clipboard | Copy plain text, then an image/rich text; dictate; check the earlier clipboard content is preserved. Disable clipboard sync for sensitive test data. | Pending Tommy |
| Different destination | Switch windows/documents while text is processing. Confirm detected changes hold insertion and Copy last text recovers it. | Pending Tommy |
| Microphones | Pause/resume; unplug/reconnect available headset; switch Windows default; sleep/wake. Mark unavailable devices untested. | Tommy reported sleep/wake and microphone reconnection work; other device cases unconfirmed |
| Startup | Turn Start with Windows off/on and verify after signing out/in in the test profile. | Tommy reported restart and retained settings work; explicit off/on test unconfirmed |
| Approved update | Record starting version, choose Check for updates after approval is available, confirm new version/settings and a new dictation. | Pending Tommy; approval not published |
| Busy update | Request an update while a harmless recording is processing. It must finish before restart. | Pending Tommy |
| Internet failure | Disconnect during a harmless test; wait for the error, cancel or retry, reconnect. Check no canceled text arrives later. | Tommy reported offline/reconnect recovery works; cancellation/late-result cases unconfirmed |
| Long recording | Try five minutes of synthetic/non-sensitive speech. A developer separately tests forced WAV fallback and size rejection. | Pending Tommy |
| Recovery | Review developer's interruption/rollback results, then dictate using the recovered app in the test environment. | Automated evidence available; dictation pending |
| Repair/removal | Repair from the full ZIP in a test profile; uninstall; check startup/shortcuts are removed and retained settings are explained. | Pending Tommy |
| Support file | Export support information; confirm version and health facts are useful and there is no transcript/account/credential data. | Pending Tommy |

If a Windows protection blocks something, record its exact name/message and the affected file. Stop there; do not disable the protection. Passing on one computer does not verify other Windows versions, ARM64, managed policies, elevated applications, Remote Desktop, or every headset. Elevated/remote text targets may refuse simulated typing; use Copy last text and paste deliberately where permitted.

Record failures and untested configurations in [acceptance issue #74](https://github.com/mirabeltech/mirabel-voice/issues/74). Release remains Tommy's decision after the [service setup prerequisites](service-maintenance.md) have owners and agreed limits.
