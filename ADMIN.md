# Running Mirabel Voice for the team

This is for whoever hands the app out. Everyone else only needs the README.

## Handing it out

Point each person at the README: they download the zip from the shared drive and paste the install line into PowerShell. The bootstrap in this repository's `install.ps1` finds the zip in their Downloads folder, unblocks it, unpacks it, and runs the `Install.ps1` inside — the unblock/extract/right-click routine, done for them. For a token build, also send their own token on a channel you trust. They do not need Git, Python, an API key, or an administrator password.

**Do not attach the zip to a GitHub release.** The repository is public, and the zip carries the relay's address in `Install.ps1`. A token still gates every request, but a public address is one anybody can hammer, and every refused call is a billed Lambda invocation.

The install puts the app in `%LOCALAPPDATA%\Programs\Mirabel Voice` and starts it with Windows. Running a newer one over an older one replaces the program and leaves the settings and the token alone.

## Cutting a release

The normal release is three steps, and the third one is the rollout:

1. **Bump the version.** Change `version` in `pyproject.toml` — the only place the version lives — and commit it on `main`.

2. **Tag it and push the tag.** GitHub Actions runs the tests, checks the tag against `pyproject.toml`, and publishes the release notes. It attaches no file, on purpose: the download carries the relay's address and this repository is public.

   ```powershell
   git tag v0.6.0
   git push origin main v0.6.0
   ```

3. **Endorse it.** Nothing rolls out until this runs:

   ```powershell
   python scripts\deploy_relay.py --endorse v0.6.0
   ```

That is the whole job. Every installed machine checks the relay once a day, sees the endorsed version, downloads that tag from GitHub, verifies it against the endorsed hash, swaps it in, proves the new code still imports, and restarts between dictations. The team is current within a day and nobody installs anything. The impatient right-click the icon and choose **Check for updates**, and the pasted install line lands on the endorsed release too.

Tag and endorse are a pair. Machines follow the endorsement, not the release list, so a tag without an endorsement reaches nobody. A bad release is recalled with `--endorse` of the previous good version; deleting things achieves nothing, because machines only ever move to what is endorsed.

Why the endorsement exists: it moves the authority to update the fleet from "can publish a GitHub release" to "can deploy the relay". The hash covers the package contents, computed the same way the app computes it (the contents, not the zip — GitHub does not promise byte-identical archives forever), so GitHub is just the delivery. Later deploys carry the endorsement forward until the next `--endorse`. A machine that gets no answer from the relay — development mode, or a relay never endorsed — falls back to following the newest published release.

### The rare release that changes the bundle

A release that touches the runtime itself — a Python version bump, a new binary library, Tkinter — cannot travel as source. Machines refuse it safely: the proof step fails, they keep the old version, and the icon's tooltip sends their person to the shared drive. For those releases, add two steps:

4. **Rebuild the zip.** `relay.json` in the repository root supplies the address and the Google client:

   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\build_bundle.ps1
   ```

5. **Upload it over the existing shared-drive file** with **Manage versions**, and rename the file to the new version — a rename keeps the link the README carries.

People then paste the install line once; the newer zip outranks their install and does the full reinstall, keeping their settings.

Every push to `main` also builds the installer with a deliberately useless relay address, so a broken build is found on the day it breaks. That artifact is a compile check and is not something to hand anybody. `packaging\build.ps1` makes the packaged .exe pair instead and needs [Inno Setup](https://jrsoftware.org/isdl.php) 6.3 or newer; prefer the bundle. See **Build the download** below.

## When Windows blocks it

Two different refusals, and they are not the same problem.

**"Windows protected your PC"** is SmartScreen. It appears because the file is not signed. People click **More info**, then **Run anyway**, and it installs. Annoying, not blocking.

**"An Application Control policy has blocked this file"** is Smart App Control, and there is no way past it. It refuses unsigned programs outright, it is on by default on clean Windows 11 installs, and turning it off is permanent. This is why the Python bundle exists: everything executable in it is signed by the Python Software Foundation, so Smart App Control allows it. See issue #35.

To check a machine before sending anything:

```powershell
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState
```

`1` means Smart App Control is on and only the Python bundle will work there. `0`, blank, or an error means either download is fine.

A code-signing certificate removes both problems: about $200-400 a year for a standard one, which quiets SmartScreen only after enough people have downloaded the file, or more for one that works at once. Ask Mirabel IT first, since the company may already hold one. It is worth buying when this goes past a handful of people. It is not needed for the pilot, because the bundle sidesteps both.

## Handing out tokens

**Nobody you send the app to ever sees an API key.** They get one token, and that token only works through the relay.

### Build the download

```powershell
python scripts\setup_relay.py
powershell -ExecutionPolicy Bypass -File packaging\build_bundle.ps1 -RelayUrl https://<the relay address>
```

The wizard prints the address; the build bakes it into `Install.ps1` so that nobody has to type it. A build with no address fails rather than producing a download that points nowhere. The result is `dist\MirabelVoice-x.y.z-python.zip`, about 53 MB.

That zip holds Python's own embeddable build with the app installed into it. It exists because Windows Smart App Control refuses unsigned programs outright, with no way past it, and refuses ours (see issue #35). It does not refuse Python, which the Python Software Foundation signed, and it does not refuse our source, which is text. The build checks that signature and stops if it is not valid.

`packaging\build.ps1` still makes the older pair, `MirabelVoiceSetup-x.y.z.exe` and `MirabelVoice-x.y.z.zip`, which hold a packaged program instead. They are smaller and they install the same way, but a machine with Smart App Control on cannot run either. Prefer the Python bundle until the program is signed.

The bundle carries Tkinter, which the status panel needs and which neither the embeddable build nor the NuGet package ships. `build_bundle.ps1` takes it from the full Python that made the `.venv`, checks that each file is signed, and stops if it is not. That is why the build needs a python.org install of the same version on the machine, not only the `.venv`.

You only rebuild when the app changes. The same zip serves everybody, because the token is the only per-person part and it is typed at install time.

### Give each person their token

Issue it with `python scripts\setup_relay.py` (press `a`, their name, `d`) and send them two things: the zip, and their own token. Send the token on a channel you trust. It is printed once and cannot be read back.

They then download the zip, paste the README's install line into PowerShell, and type their token when asked.

The install checks the token through the relay before it finishes. A token the relay does not know is refused there, with a plain sentence, and cleared so that a second run asks again rather than skipping the page.

A newer zip installed over an older one keeps the token, the dictation key, and every other setting, and does not ask for the token again.

### If somebody's token has to change

Issue them a new one and have them run the installer again. It sees the stored token, so tell them to clear it first: right-click the icon near the clock, quit, then delete the `relay_token` line from `%APPDATA%\MirabelVoice\config.json`. Or run this from the install folder, which is quicker:

```powershell
& "$env:LOCALAPPDATA\Programs\Mirabel Voice\MirabelVoiceConsole.exe" --set-relay "https://<the relay address>" "<their new token>"
```

`setup.ps1` still works and is the right choice for developers. Both paths produce the same app.

## What this does and does not protect

A machine set up against the relay holds one token in `%APPDATA%\MirabelVoice\config.json` and no provider keys at all. Anyone who can use that computer can read the token, so treat it as that person's own credential: it names them in the usage report, and taking it away is one line in the wizard.

What the relay does not do is separate people from each other's dictation history, because there is no history. Nothing spoken or written is stored anywhere, by the app or the relay.

A developer running `setup.ps1` without `-RelayUrl` still holds two provider keys in `%APPDATA%\MirabelVoice\keys.json`, in plain text, exactly as the whole pilot used to. That mode exists so the app can be worked on without AWS. Use a key that belongs to you, not the org's, and delete the file when you are done with it.

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

### Turn on Google sign-in

Done once, when the OAuth client from IT exists (issue #40):

```powershell
python scripts\deploy_relay.py --google-client-id <the client id> --google-domain <our Workspace domains, comma separated>
```

From then on the relay accepts a Mirabel Google sign-in wherever it accepts a token, and the usage report names the verified account. Tokens keep working beside it — the smoke test and any machine not yet moved over rely on that. A later plain `deploy_relay.py` keeps sign-in on; the two values live on the Lambda, not in this repository, which is public.

Sign-in access needs no issuing and no revoking: an account that leaves the Workspace stops being able to sign in, and its access to the relay ends within the hour on its own.

For the app side, add the OAuth client to `relay.json` in the repository root (it is not committed, same as the relay address):

```json
{
  "relay_url": "https://<the relay address>",
  "google_client_id": "<the client id>",
  "google_client_secret": "<its companion value>"
}
```

Both build scripts bake the pair into `Install.ps1` beside the relay address. A zip built this way has no token page at all: the person unzips, runs `Install.ps1`, and signs in when the browser opens. Neither value is a secret — Google documents that an installed app cannot keep one, and the pair grants nothing without a Mirabel sign-in.

A machine already on a token keeps working untouched. To move it over without a reinstall:

```powershell
python scripts\set_relay.py --google-client-id <the client id> --google-client-secret <its value>
```

The app then signs the person in on its next start, and the stored token stays in the settings as the escape hatch: remove the two `google_` lines from `config.json` and the token rules again.

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

Two things watch the spend now. The AWS budget alarm mails the shared mailbox at $5 and $10 a month, and `scripts/usage_report.py` says who the spend belongs to. Neither is a cap: nothing stops the app spending, so the alarm is a thing to read rather than ignore.

The table below is the estimate the pilot started with. Once a month of real use is in the log, the report is the better number.

A minute of speech costs about **$0.0088**: $0.006 for the transcription (`gpt-4o-transcribe`) and $0.0028 for the Claude cleanup. Over 22 working days that gives:

| Speech per day | Cost per person per month |
|---|---|
| 10 minutes | $1.94 |
| 30 minutes | $5.81 |
| 60 minutes | $11.62 |

To cut the cost further, right-click the icon near the clock and turn off **Clean up with Claude**. That saves $0.0028 a minute, about a third of the total. (It has no effect for someone using **Translate to English** — translation happens in that same cleanup pass, so the pass keeps running.)

For comparison, Wispr Flow Pro costs $15 a person a month, or $12 billed annually.
