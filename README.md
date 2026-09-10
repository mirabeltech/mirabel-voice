# Mirabel Voice

Press **Insert**, speak, then press **Insert** again. Mirabel Voice turns your speech into text and inserts it where you were typing.

**Release status:** Tommy has confirmed the Google Drive download, installation/repair, Settings, dictation, restart, sleep/wake, microphone reconnection and connection recovery on his Windows computer. Version 0.9.3 adds a shutdown deadline so a stalled Quit or update restart can release the old process. Version 0.9.2 refreshed Settings with grouped preferences, consistent icon buttons and an optional microphone test. Settings opens once on first launch; no setup completion is required. Fresh installations use English and Insert, while upgrades retain saved preferences. Service usage limits, outage monitoring and the remaining [release checklist](docs/windows-acceptance.md) still need to be completed before organization-wide rollout. These results do not verify every Windows computer or a fresh user profile.

## Install on Windows

1. [Open the company shared drive](https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA), sign in with your Mirabel work account, and download the approved **MirabelVoice-[version]-python.zip**. Keep it in Downloads.
2. Open **PowerShell** from the Start menu. Paste this line and press Enter:

   ```powershell
   irm https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1 | iex
   ```

   The command checks that the ZIP is approved and complete, then unpacks and installs it in your own Windows profile. It needs no administrator password. If you have not downloaded the ZIP, it opens the drive; download the file and run the command again.
3. Sign in with your Mirabel Google account when asked. Settings opens on first launch. Choose your microphone, language and dictation key, or keep the defaults. **Test microphone** optionally shows the live input level. Reopen Settings anytime from the microphone icon near the clock (look under **^** if hidden).

This distribution method needs no Microsoft 365 subscription, developer account, Store registration or signing purchase. AI processing and the existing relay still have running costs.

The candidate bundle is for **Windows x64**. Other architectures and managed security policies require separate verification. If **Smart App Control**, your company's security software or PowerShell policy blocks it, stop and send Tommy the exact message. Do not turn off Windows protection. ZIP approval and unblocking cannot override all Windows policies. There is no promise that it will run on every Windows computer.

## Everyday use

Click into the intended text box and keep it selected until your text arrives.

| Action | Control |
|---|---|
| Start / finish dictation | Press Insert / press Insert again |
| Cancel recording or waiting for a result | Esc |
| Insert the last completed text again | Shift+Alt+Z |
| Choose microphone, language, key or translation | Click the microphone icon |
| Close the app and microphone | **Quit** in controls |
| Start automatically after signing into Windows | **Start with Windows** checkbox |
| Check for an approved update | **Check for Updates** in controls |
| Copy the completed transcript yourself | **Copy last text** |

A hold-mode configuration uses hold/release instead of two presses. The controls show the current mode. Choosing the system default microphone lets the app reopen it after Windows changes the default, once the current recording finishes. Explicitly selected microphones stay selected.

The status panel shows listening, processing, completion or an error. One sound means start, a lower sound means captured, and a high sound means the text was sent to the selected application; check the result before sending your message. Two low sounds mean the action could not complete; check the displayed message. Processing time varies with recording length, connection and service availability.

If transcription fails, dictate again. The failed recording stays in memory until a new recording, Esc or Quit clears it. Esc cancels local waiting and prevents the late result from being inserted; a request already sent may still finish at the provider. If cleanup or translation fails, the app preserves the original transcript and reports that the original words were used.

If the destination window, focused control or detectable document title changes, automatic insertion is held back. Use Copy last text or deliberately paste into the intended field. Some applications do not expose every change of document or field: keep your intended destination selected and check the result before sending it. Rich text or an image already on your clipboard makes the app use typing instead of replacing it. A failed paste is not automatically repeated, to avoid duplicate text.

## Updates and repairs

The app checks for an **approved** update daily. Right-click the icon and choose **Check for updates** to check sooner. The install command sends the same request to an existing compatible installation. Checks share one updater and wait for dictation to finish before changing files or restarting.

If approval is unavailable, the existing version stays installed. An update is tested before it is accepted; the previous copy is kept for recovery. A change to runtime dependencies requires a new full Python ZIP. Quit the app and run the install command with that ZIP in Downloads. Your language, key, sign-in and other settings stay in your profile.

For a damaged installation, use the full ZIP repair route. A damaged settings file is recovered from its last valid backup when available. If both copies are damaged, ask Tommy to repair the settings; the app will not silently erase them. Set `"auto_update": false` in `config.json` if you need manual checks only.

## Privacy and support

Speech goes through Mirabel's relay to OpenAI for transcription. When cleanup or translation is enabled, transcript text also goes through the relay to Anthropic. Provider retention and account terms must be confirmed by the service owner; this app does not promise zero provider retention.

Recordings, recent microphone audio and the last completed transcript are held in memory, not intentionally written to a recording/history file. The microphone normally stays open for fast response and keeps a rolling buffer of up to two seconds locally. Quit closes it. `"hot_mic": false` in the settings makes it open only for a dictation.

Settings, custom words and application logs are stored in `%APPDATA%\MirabelVoice`. Google refresh credentials and their recovery copies use Windows account encryption. Legacy relay tokens, if used, remain in the settings file. Settings backups and damaged copies may contain the same personal configuration as the original. The clipboard belongs to Windows; Windows clipboard history or sync may retain pasted text if you enabled those features.

For help, right-click the icon and choose **Export support information**. It creates `support.json` in the settings folder containing version/platform information and an offline health result. It does **not** include raw logs, recordings, transcripts, credentials, your email or your custom words. Send that file and the visible error message to Tommy. Do not send the whole settings folder.

If the microphone meter stays at zero, check the selected input and Windows **Settings → Privacy & security → Microphone**, including desktop-app permission. Try a different input if a headset was disconnected. After sleep, allow the microphone a few seconds to reconnect.

## Personal spellings

Mirabel names such as ChargeBrite, MagHub and Magazine Manager are built in. Add your own spellings in `config.json` through **Open the settings folder**:

```json
"custom_words": ["Acme Publishing", "Priya Ramesh"]
```

## Remove the app

Choose **Quit**, then uninstall **Mirabel Voice** from Windows **Installed apps**. This removes the app, shortcuts and startup entry. Settings are kept for a later reinstall. To remove those too, delete `%APPDATA%\MirabelVoice` after uninstalling.

For development and release maintenance, see [ADMIN.md](ADMIN.md).
