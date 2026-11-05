# 0.9.7: The app reports its version and its errors

Until now Tommy could only find out which version someone ran, or what went wrong on their computer, when they told him. This release has every copy tell the relay which version it is, and send a short report when something fails.

## What's new

- **Version on every relay request.** The app sends its version with each dictation, each cleanup and the update check. On a signed-in copy with automatic updates on, the update check runs about a minute after the app starts and then once a day, so that copy shows up even if nobody dictates with it. `usage_report.py` now lists each person, the version they last ran and when.
- **Error reports.** When one of five known failures happens, the app sends a report to the relay: a crash, a failed update download, a failed sign-in, the microphone not opening, or a failed repair of the Start with Windows entry. A report holds the error type and message, where in the code it happened, the app and Windows versions, and the CPU type. User folder names are taken out of file paths, keys, tokens and email addresses are removed, and a report never holds audio or anything you said. If the relay can't be reached, up to 20 reports wait in the settings folder and go out later. The app sends at most 20 an hour, and sending never holds up dictation. `usage_report.py --reports` groups them.
- **A crash leaves a trace.** A crash that ends the app now writes its traceback to the log and shows an error box that says where the log is. Before, the app could vanish without leaving anything behind.
- **The uninstaller works on Windows on ARM.** Windows on ARM keeps some of the runtime's files locked for a few seconds after the app quits, which made removal fail. The uninstaller now waits for them.

## Privacy

The privacy promise changes. Mirabel Voice used to say it kept no telemetry. Now no audio and no transcripts are stored anywhere, and the relay keeps the version on each request and the error reports in its log for 90 days. The README, SPEC and ADMIN guide say this in full.

## Updating

The runtime dependencies are the same as in 0.9.6, so a computer already running 0.9.6 can take this as a normal update once the relay endorses it. A computer on 0.9.5 or older still needs the new Python ZIP, because 0.9.6 changed the runtime: quit Mirabel Voice, download the ZIP from the company drive to Downloads, and run the usual install command. The uninstaller fix only arrives with the ZIP. Preferences and credentials are kept.

Error reports only reach Tommy through a relay that has the report route, which went live with the relay deploy on November 5.
