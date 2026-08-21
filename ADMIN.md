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

**That was the old arrangement. The relay replaced it** (2026-08-21). A machine set up against the relay holds one personal token and no provider keys at all, the keys live in AWS, and every request is logged against the holder's name. See **Running the relay** below. The two paragraphs above still describe any machine that has not moved over yet, and a `keys.json` on such a machine is still a key somebody can read.

## Running the relay

The relay is an AWS Lambda that holds the provider keys and forwards dictation to OpenAI and Anthropic. Each person presents a personal token instead of a key. Everything here runs from the repository, and every one of these commands is safe to run again.

### Give somebody a token

```powershell
python scripts\setup_relay.py
```

Press `a`, type their name, press `d`. The wizard generates the token, saves the list, redeploys, and prints the new token once. Hand it over on a channel you trust. The name is what appears in the usage report, so use the name you want to read there.

On their machine:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -RelayUrl https://<the relay address>
```

It asks for the token, checks it through the relay, and refuses to finish if the relay does not know it. A machine set up this way needs no provider keys.

### Take a token away

```powershell
python scripts\setup_relay.py
```

Press `r`, type their name exactly as the list shows it, press `d`. Their token stops working the moment the deploy finishes, and nobody else is touched. There is nothing to collect from their laptop, because the token is all they ever had.

### Rotate a provider key

1. Make the new key on the provider dashboard.
2. In AWS Secrets Manager (region `us-east-2`), open `mirabel-voice/openai` or `mirabel-voice/anthropic` and store the new value as the whole plaintext secret.
3. Redeploy so the Lambda reads it: `python scripts\deploy_relay.py`. The deploy ends with a live test call through both providers, so a bad paste is caught here rather than during somebody's dictation.
4. Delete the old key on the dashboard.

Nobody's laptop is involved and nobody has to be told. That is the difference the relay bought.

A machine still on the old arrangement holds its own keys, and rotating those means the `keys.json` steps below.

### Pull the usage report

```powershell
python scripts\usage_report.py --days 30
```

It reads the relay's own usage lines out of CloudWatch and adds them up per person: dictations, minutes of speech, and cost split between transcription and cleanup. The lines carry no audio and no text, so the report can be shared without sharing anything anybody said.

The rates live in `docs/pricing.json`. They are rates, not measurements, so check them against the provider pricing pages before you quote a number to anybody. A model with no price listed is reported at the bottom rather than counted as free.

Refused requests appear as a count with no name attached, which is what a wrong or withdrawn token looks like from the relay's side. A few are normal, because the app's warm-up pings reach the relay before any dictation does. A run of them from nowhere is worth a look.

## Rotating a key on a machine that still holds keys

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
