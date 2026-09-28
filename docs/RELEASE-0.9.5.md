# 0.9.5: Mirabel Voice starts at sign-in again

On some computers, Windows showed "Mirabel Voice could not start" at every sign-in. Nothing was updating and nothing needed repair. The Start with Windows entry pointed at the launch script through a `\\?\` long-path prefix, and Windows PowerShell 5.1 cannot build paths from a folder written that way. The launcher's catch-all turned the error into the generic message. The Start menu shortcut kept working.

The running app now writes the entry without the prefix and rewrites an entry that already has it, so this fix arrives with the source update. On an affected computer, open Mirabel Voice once from the Start menu. After it updates, the next sign-in starts normally. The launch script also accepts the prefix now, but the updater does not replace the launch script, so that part reaches a computer only through the bundle installer. On an affected computer, the fixed launch script started the app from the broken entry. Tests cover the entry repair; it has not yet run on a real installation.

Preferences, credentials and runtime dependencies are unchanged, so this is a source update; no new ZIP is required for existing installations.

The relay's operations changed separately and need no client update: the daily spending check keeps a running monthly total instead of rescanning the month, alarm text matches how each alarm triggers, and the runbook records the backup owner and key-rotation decisions.
