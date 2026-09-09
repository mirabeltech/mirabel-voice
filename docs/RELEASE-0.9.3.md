# 0.9.3: bounded shutdown for Quit and update restart

Quit and update restart now start a 12-second cleanup deadline. Normal cleanup cancels the deadline. If cleanup remains stuck, the app records thread stacks in `logs/shutdown-timeout.log` and exits its own process, releasing the Windows single-instance mutex for a waiting replacement. Repeated Quit requests do not create additional deadlines.

The update coordinator still waits for dictation to finish before starting shutdown. Preferences, credentials and runtime dependencies are unchanged.

The exact cause of Tommy's previous hang could not be established after the stuck process was terminated. This change addresses the unbounded shutdown path and captures diagnostics if it recurs.

Regression coverage includes normal cleanup, a stuck cleanup, repeated Quit, and a real Windows subprocess/mutex handoff to a waiting replacement. The native tray, overlay, keyboard listener and microphone also completed normal shutdown in a local check.

An already-running 0.9.2 process does not gain this safeguard until it restarts into 0.9.3. If that one-time update gets stuck, the old process still needs to be closed manually.
