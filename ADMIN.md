# Running Mirabel Voice for the team

The selected distribution is the free **Python ZIP on company-restricted Google Drive**. Store/MSIX, developer registration, paid signing and a software portal are out of scope. Tommy is the only manual acceptance tester. The tested 0.9.0 ZIP is authorized for the final download/installation check. Organization-wide rollout and relay deployment remain separate.

## Build and review the download

Use the full python.org **CPython 3.13.15 x64** with Tcl/Tk and a matching `.venv`. Runtime dependencies are pinned with hashes in `packaging/requirements-windows.lock`; the reviewed embeddable Python download is pinned in `packaging/python-runtime.sha256`. Updating either requires a full bundle and new checks. Changes to bundled launch/recovery support or `sitecustomize.py` also require incrementing `bundle_format` in `src/mirabel_voice/data/runtime.json`; the installed runtime keeps a separate format marker so a source-only update will refuse that mismatch. The full Python installation supplies Tk; the builder checks Python/Tk signatures and inventories all native components. Third-party native libraries can be unsigned. A valid interpreter signature does not establish universal Smart App Control compatibility.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pip_audit -r packaging/requirements-windows.lock --require-hashes --disable-pip
powershell -ExecutionPolicy Bypass -File packaging\build_bundle.ps1
```

The local builder obtains the private relay and Google desktop-client configuration from the existing ignored `relay.json`, or explicit arguments. Never commit that file, configured ZIPs, settings, credentials or private support files. CI uses `https://relay.invalid` and dummy Google values. CI artifacts are test-only downloads, not working company releases. The workflow builds the actual Python ZIP, performs offline import/Tcl/encoder checks and audits the locked packages. Test/build/audit tooling is pinned with hashes in `packaging/requirements-build.lock`; runtime packages cannot float during the build.

The output is `dist/MirabelVoice-[version]-python.zip`, its SHA-256 file, and native/dependency inventories. Preserve those together with the dependency audit and [Tommy's acceptance results](docs/windows-acceptance.md). The generated `_version.txt` comes from `pyproject.toml`; it moves transactionally with the app. Keep the previous configured download privately for recovery. Legacy EXE/Inno scripts remain historical development tools and are not the organization release path or CI release artifact.

## Approve and distribute

Approval is explicit. Do not publish the dummy CI ZIP as an employee download. Build a configured candidate, verify its integrity, and have Tommy authorize that exact hash for download testing. Tommy then tests it downloaded through a browser with protections enabled before organization-wide rollout. A local smoke test is not a fresh-download test.

The bootstrap downloads **public approval metadata separately from the private ZIP**. It checks the full ZIP SHA-256 before unblocking, extracting or executing its installer. `packaging/bundles.json` lists only ZIPs explicitly authorized by the release owner. The 0.9.0 entry enables the final download test; it does not mark all release checks complete. A public checksum exposes only filename/version/hash, not private configuration. Protect changes to the bootstrap and this manifest with repository review controls. The metadata is a trust decision based on the repository over HTTPS; it is not Authenticode signing and cannot defeat a managed Windows policy.

Prepare the manifest entry locally after the release owner authorizes the exact ZIP:

```powershell
.venv\Scripts\python.exe scripts\approve_bundle.py dist\MirabelVoice-0.9.0-python.zip
```

Review the exact entry, publish the manifest through the normal reviewed repository change, and place that exact configured ZIP in the restricted Drive folder. Confirm the public manifest and Drive hash match. Do not replace bytes underneath an already reviewed hash. An unpublished candidate can be tested in an isolated profile using a separate local manifest and `install.ps1 -ManifestPath <test-manifest> -DownloadsDir <test-downloads> -Target <test-install>`; this is a developer test input, not an employee trust bypass or production approval.

Share the [README](README.md) and one stable Drive link. Users need no Git, separate Python installation or provider keys. The bootstrap finds the versioned Python ZIP, including browser duplicate-number filenames, verifies it, and installs current-user shortcuts/startup/removal support. If Windows blocks it, collect the exact block and affected component. Do not advise disabling Smart App Control or weakening organization policy.

## Source updates and rollback

Commit/review the source, ensure `pyproject.toml` matches the release tag, then publish the source release through the normal repository process. A published GitHub release alone does not approve an update for relay-managed users. After testing, the release owner endorses the package content hash through the existing relay deployment tooling:

```powershell
.venv\Scripts\python.exe scripts\deploy_relay.py --endorse 0.9.0
```

This is a **production rollout action**, not part of building or testing locally. See the command's help and [AWS operations guide](docs/AWS.md) for account details. Keep the previous approved source/version and private full ZIP available. An explicit older relay endorsement supports source rollback when its dependency lock matches the installed runtime; runtime changes require the previous full ZIP. Version 0.9.0 changes Python itself, so existing users need the full ZIP. The package runtime contract also makes older --config proof commands reject this source-only upgrade and keep their working copy.

Tray, daily checks and the bootstrap's update request now share the app coordinator. Missing/invalid approval, expired credentials, an unavailable relay or a hash mismatch keeps the working app. The bootstrap no longer carries a second GitHub-only update implementation. A source/developer checkout without a relay is a separate development mode.

The updater takes an installation lock, waits for active work, checks the candidate with installed dependencies, journals the replacement, verifies startup again and retains the previous package. Package-local version metadata is authoritative after recovery. A stable launcher outside the package restores an interrupted package update. A separate PowerShell launcher restores an interrupted full-runtime replacement before starting Python. If the lock is busy, wait and retry; do not delete it while another process is using it.

## Repair and remove

Quit the app before replacing the full runtime; the installer refuses to kill active dictation. For an explicit repair with an approved ZIP in Downloads:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1))) -Repair
```

Repair stages and tests a full runtime, keeps the previous runtime, and preserves per-user settings/credentials. Startup preference is retained. Normal updates cannot silently migrate changed dependency locks: they ask for a new ZIP. The stable launchers recover pending replacements; if both settings copies are unreadable, repair the configuration rather than resetting it blindly.

Uninstall through Windows Installed apps after Quit. Shortcuts/startup entries and application files are removed; settings are retained unless explicitly removed. `%APPDATA%\MirabelVoice` can include settings backups, encrypted sign-in backups and logs, so do not distribute that directory as a support bundle. Use **Export support information**, which allowlists version/platform and offline health facts.

## Service and privacy maintenance

See [service maintenance](docs/service-maintenance.md) for request/model/output validation, optional distributed request limits, pending usage/alert decisions and the synthetic service-check command. Cloud limits, monitoring and provider-key ownership must be reviewed before rollout; a local implementation is not a deployed safeguard. Existing organization-key work remains issue #46.

The microphone normally maintains a rolling memory buffer for fast starts; Pause closes it. Failed audio is retained only in memory for one explicit retry and discarded on new recording, Discard or Quit. The last transcript remains in memory for copy/paste-last. Configuration, credentials and application logs do persist; clipboard history/sync and provider retention are separate systems. Do not promise zero retention or describe network loss as seamless offline operation. Keep logs limited to operational status, not speech, keys or provider payloads.

The following commands describe existing relay operations. They require the appropriate operator credentials and are not automatically run by the installer.

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

A dictation from a v0.6.4 machine carries its real token counts and is priced from them — audio in, prompt text in, transcript out, which is what OpenAI actually bills. An older line is priced by audio minutes alone, which misses the text tokens and understates it. The report's footer says how many of each went into the numbers; treat a mostly-minutes report as a floor, not a total. Before quoting a month to anybody, compare the report against the OpenAI dashboard's own billing page once — the audio token rate in pricing.json is derived from OpenAI's published per-minute estimate, and one invoice settles it.

The deploy's smoke test makes real calls, and those used to be charged to whichever person's token the script borrowed first — numbers before August 2026 carry that noise. The smoke test now holds its own token, named **Smoke test** in the token list (the first deploy after this change mints it). The report keeps its spend out of the per-person table and prints it as a footnote instead. If the wizard is ever used to remove that holder, the next deploy simply mints a new one.

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

The Claude cleanup can be turned off by setting `cleanup_enabled` to `false` in `%APPDATA%\MirabelVoice\config.json`, which saves $0.0028 a minute, about a third of the total. It stopped being a tray item in v0.6.4: nobody in the pilot ever turned it off, and without the cleanup the app is a plain transcriber. (The setting has no effect for someone using **Translate to English** — translation happens in that same cleanup pass, so the pass keeps running.)

For comparison, Wispr Flow Pro costs $15 a person a month, or $12 billed annually.
