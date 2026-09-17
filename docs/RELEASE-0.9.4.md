# 0.9.4: the dictation key can be Right Ctrl, and the app starts on a default Windows computer

Right Ctrl, and every other left or right modifier, now works as the dictation key. The listener folded a sided key into its generic form, so a saved `ctrl_r` never matched a press. Sided keys keep their side; generic names such as the paste-last binding still accept either side. Settings shows keys by the names people use and explains how Change key ended.

Settings gains a Dictation mode switch between toggle and hold. A switch is refused during a recording and leaves a key capture alone.

When the app falls back to typing (the clipboard holds a rich format, or the insertion method is "type"), a newline now goes out as Shift+Enter. It was typed as Enter, which sends the message in AI chat tools, so a long dictation with "new paragraph" arrived as several sent messages.

On a computer with the Windows default PowerShell execution policy, the Start menu shortcut, Desktop shortcut and Start with Windows entry refused the unsigned launch script under a hidden window, so the app worked once from the installer and never again. The installer now passes a per-process bypass, and a running app repairs entries an older installer wrote, so this fix arrives with the source update. Confirmed on an affected computer.

The Settings card no longer keeps a Tk variable past teardown, which could abort the process on exit.

Preferences, credentials and runtime dependencies are unchanged, so this is a source update; no new ZIP is required for existing installations. A `scripts/diagnose_launch.ps1` launch report is on the `launch-diagnostic` branch for support.
