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

Both the installer and `setup.ps1` look in these places, in order, and stop at the first one:

1. `keys.json` sitting next to the installer (or next to `setup.ps1`)
2. the path in the `MIRABEL_VOICE_KEYS` environment variable
3. otherwise they ask the person to paste the keys

The file looks like this:

```json
{
  "openai_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

Pick whichever way suits you:

**A shared folder.** Put `keys.json` somewhere everyone can read, then have people run one line before setup:

```powershell
$env:MIRABEL_VOICE_KEYS = "\yourserver\share\mirabel-voice\keys.json"
```

Windows file permissions decide who can read it, and you replace one file when you rotate the keys.

**A folder with the installer in it.** Put `keys.json` and `MirabelVoiceSetup-x.y.z.exe` in the same folder and share that folder. The installer finds the keys and never asks. Simplest for people who do not have Git.

Never attach `keys.json` to a GitHub release. The repository is public, and so is everything on a release page.

**Neither.** Leave it out and setup asks for the keys. Fine for two or three people.

`keys.json` is in `.gitignore`, so it cannot be committed by accident. Never put it in the repository.

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

## Watching the cost

Set spending limits on both dashboards before you hand the app out. Live dictation runs about **$0.017 a minute**, so an hour of speech a day is roughly **$22 a month per person**.

To halve it, set `"streaming_enabled": false` in a person's `config.json`. They lose the words-as-you-speak effect and wait about a second longer, and the cost drops to about $0.003 a minute.
