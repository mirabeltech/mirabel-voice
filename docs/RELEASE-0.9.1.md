# 0.9.1: setup and microphone switching

Release authorized by Tommy on September 9, 2026 after confirming the 0.9.1 candidate works. The approved private ZIP SHA-256 is `2de9c657d87bd6951106c3f75f0a1b8a07d9c96116d5fcc54c572327102f3a51`. Upload that exact ZIP to the restricted company Drive; the usual installer validates it through `packaging/bundles.json`.

- Fresh installations use English (`en`) and Insert. These defaults already existed; regression coverage now exercises the installer's configuration command and the produced ZIP. Repairs/upgrades preserve explicitly saved language and key choices, including automatic language detection.
- Finish setup previously saved `onboarding_complete` but was rendered unconditionally whenever Settings was built. Completing setup now removes the help text, practice box and Finish setup button, including after restarting. Other settings remain available.
- A stream whose `start()` fails is now stopped and closed before retrying. Errors from an abandoned open cannot overwrite the current recorder generation's error.
- On Windows, a saved WDM-KS selection uses a uniquely and exactly named WASAPI input when available. No other microphone is substituted for an explicit selection. A WDM-KS system default uses the WASAPI default if available; an MME default mapper is preserved. WASAPI opens in shared mode with system format conversion enabled.
- Microphone start failures display recovery instructions; the full driver exception remains in the application log.

The employee screenshot shows a WDM-KS host error while starting capture. That identifies the failing backend, but does not establish why that particular device refused to start. The changes address resource leakage and legacy-backend selection; the employee's actual microphone still needs a dictation retest.

## Verification

- Windows Python 3.13 build environment: **495 tests passed**, including new installation defaults, retained upgrade preferences, setup completion, failed stream cleanup, backend selection, and retry after microphone switching.
- Packaged runtime startup, Tcl and audio encoder checks passed without opening a microphone or making network requests.
- Produced ZIP installation, English/Insert defaults, repair with retained preferences, interrupted runtime/source recovery, and uninstall with retained settings all passed in a disposable Windows profile.
- An initial combined run under the older Python 3.12 development environment aborted during garbage collection in native code after Tk tests. The targeted groups passed separately under the release environment, and the build's full Python 3.13 test run passed.

## Employee verification

After installing this candidate, confirm v0.9.1, finish setup and reopen Settings to confirm the setup section is gone. Dictate using the first microphone, stop dictating, choose the second microphone and dictate again. Switch back and repeat. If a microphone was connected after Mirabel launched, restart Mirabel before selecting it; the audio library's device inventory can be stale.

The original defaults apply to fresh settings only. An existing user's preferences should remain unchanged during the upgrade.

Technical reference: [sounddevice WASAPI settings](https://python-sounddevice.readthedocs.io/en/0.5.3/api/platform-specific-settings.html#sounddevice.WasapiSettings).
