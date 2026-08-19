# Running Mirabel Voice for the team

This is for whoever hands the app out. Everyone else only needs the README.

## Handing it out

Send people to the [latest release](https://github.com/mirabeltech/mirabel-voice/releases/latest). They download one file, run it, and paste the two keys. They do not need Git, Python, or an administrator password.

The installer puts the app in `%LOCALAPPDATA%\Programs\Mirabel Voice` and starts it with Windows. Running a newer installer over an older one replaces the program and leaves settings and keys alone.

`setup.ps1` still works and is the right choice for developers. Both paths produce the same app.

## Cutting a release

1. Change `__version__` in `src/mirabel_voice/__init__.py`.
2. Commit that on `main`.
3. Tag it and push the tag:

```powershell
git tag v0.2.0
git push origin v0.2.0
```

GitHub Actions then runs the tests, builds the installer, and publishes it. The tag must match `__version__`, or the build stops and says so.

Every push to `main` builds the installer too, without publishing it. That way a broken build is found on the day it breaks, not on release day. Look under **Actions** for the file.

To build one on your own machine instead:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

That needs [Inno Setup](https://jrsoftware.org/isdl.php) 6.3 or newer.

## The "Windows protected your PC" warning

The installer is not signed, so Windows warns about it and some antivirus tools may hold it back. People click **More info**, then **Run anyway**. The README says so, and so does every release.

To remove the warning you need a code-signing certificate: about $200-400 a year for a standard one, which stops the warning only after enough people have downloaded the file, or more for one that stops it at once. Ask Mirabel IT first — the company may already hold one, or may be able to allowlist the app. When you have a certificate, sign `dist\MirabelVoice\*.exe` before Inno Setup runs, and sign the finished installer after.

## Giving people the keys without them typing anything

**You prepare the keys once. The people you send the app to do nothing with them.** They never see a key and never see a key page.

### What you do, one time

1. Make one folder on a share that only the pilot users can open.
2. Put `keys.json` in it:

```json
{
  "openai_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

3. Put `MirabelVoiceSetup-x.y.z.exe` in the same folder.
4. Send people that folder.

### What each person does

1. Open the folder.
2. Double-click the installer.
3. Click **More info**, then **Run anyway**, on the Windows warning.
4. Click Next until it finishes.

The installer finds `keys.json` beside itself and copies it to `%APPDATA%\MirabelVoice\keys.json`. It hides the key page because it no longer needs one.

### The other two ways

Both the installer and `setup.ps1` look in these places, in order, and stop at the first one:

1. `keys.json` next to the installer (or next to `setup.ps1`) - the way above
2. the path in the `MIRABEL_VOICE_KEYS` environment variable
3. otherwise they ask the person to paste the keys

Method 2 is the only one that asks a person to run something. Use it when the keys cannot sit next to the installer. Each person runs one line before setup:

```powershell
$env:MIRABEL_VOICE_KEYS = "\\yourserver\share\mirabel-voice\keys.json"
```

Method 3 needs no preparation. Fine for two or three people you can hand the keys to yourself.

### Keeping the file safe

`keys.json` is plain text. Anyone who can open the folder can read both keys.

- Share the folder with named people. Never with "anyone with the link".
- Never email it, never post it in Teams or Slack, never attach it to a GitHub release. The repository is public, and so is every release page.
- `keys.json` is in `.gitignore`, so it cannot be committed by accident. Never put it in the repository.

**Give each person their own key pair if you can.** Both dashboards let you make more than one key. Put each pair in that person's own folder. One leak then needs one revoked key instead of a rotation for everybody, and the dashboards show you who spends what. For a pilot of three to five people this is a short job and it is the best improvement available before the relay server.

## What this does and does not protect

Every method above puts a copy of the key on each person's computer, in `%APPDATA%\MirabelVoice\keys.json`. Anyone who can use that computer can read it. That is acceptable for an internal pilot with spending limits set, and it is what the design agreed.

It does not give you per-person usage figures, and it means one leak needs a rotation for everybody.

**The proper answer, when the pilot grows:** put a small server in the middle. The app calls the server, the server holds the keys and calls OpenAI and Anthropic. The key never reaches anyone's computer, you can see who used what, and you can cut off one person without touching anyone else. The cost is that you then own a server, its sign-in, and its uptime — and it adds a hop to a pipeline that has been tuned hard for speed.

## Rotating a key

1. Make the new key on the provider dashboard.
2. Replace the shared `keys.json`.
3. Tell people to delete `%APPDATA%\MirabelVoice\keys.json`, then run the installer (or `setup.ps1`) again. It copies the new file.
4. Delete the old key on the dashboard.

Step 3 needs the delete first. Both the installer and setup leave an existing keys file alone, so that nobody's working setup is overwritten by accident.

## When somebody says it is slow

Run this from the install folder. It proves the audio encoder loaded, which
is the difference between sending 155 kB and sending 1.4 MB per dictation:

```powershell
& "$env:LOCALAPPDATA\Programs\Mirabel Voice\MirabelVoiceConsole.exe" --check-audio
```

A copy with a broken encoder still dictates. It just sends about nine times
more audio and never says so, which shows up as a slow first second.

## Watching the cost

Set spending limits on both dashboards before you hand the app out. Nothing else caps what the app can spend.

The app ships with the live view **off**. A minute of speech then costs about **$0.0058**: $0.003 for the transcription (`gpt-4o-mini-transcribe`) and $0.0028 for the Claude cleanup. Over 22 working days that gives:

| Speech per day | Cost per person per month |
|---|---|
| 10 minutes | $1.28 |
| 30 minutes | $3.83 |
| 60 minutes | $7.66 |

**Turning the live view on costs 3.4 times more.** Set `"streaming_enabled": true` in a person's `config.json` to show the words while they speak. The transcription model becomes `gpt-live-transcribe` at $0.017 a minute, and the same three rows become $4.36, $13.07, and $26.14. Give it to a new user for the first week if it helps them trust the tool, then turn it off again.

To cut the cost further, right-click the icon near the clock and turn off **Clean up with Claude**. That saves $0.0028 a minute, which is about half of what the app costs with the live view off.

For comparison, Wispr Flow Pro costs $15 a person a month, or $12 billed annually.
