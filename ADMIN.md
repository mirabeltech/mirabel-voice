# Running Mirabel Voice for the team

This is for whoever hands the app out. Everyone else only needs the README.

## Giving people the keys without them typing anything

Make one `keys.json` and let setup find it. It looks in these places, in order, and stops at the first one:

1. `keys.json` sitting next to `setup.ps1`
2. the path in the `MIRABEL_VOICE_KEYS` environment variable
3. otherwise it asks the person to paste the keys

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

**A zip.** Put `keys.json` in the folder alongside `setup.ps1`, zip the whole thing, and share the zip. Simplest for people who do not have Git.

**Neither.** Leave it out and setup asks for the keys. Fine for two or three people.

`keys.json` is in `.gitignore`, so it cannot be committed by accident. Never put it in the repository.

## What this does and does not protect

Every method above puts a copy of the key on each person's computer, in `%APPDATA%\MirabelVoice\keys.json`. Anyone who can use that computer can read it. That is acceptable for an internal pilot with spending limits set, and it is what the design agreed.

It does not give you per-person usage figures, and it means one leak needs a rotation for everybody.

**The proper answer, when the pilot grows:** put a small server in the middle. The app calls the server, the server holds the keys and calls OpenAI and Anthropic. The key never reaches anyone's computer, you can see who used what, and you can cut off one person without touching anyone else. The cost is that you then own a server, its sign-in, and its uptime — and it adds a hop to a pipeline that has been tuned hard for speed.

## Rotating a key

1. Make the new key on the provider dashboard.
2. Replace the shared `keys.json`.
3. Tell people to run `setup.ps1` again. It copies the new file.
4. Delete the old key on the dashboard.

To force a re-copy on one machine, delete `%APPDATA%\MirabelVoice\keys.json` first.

## Watching the cost

Set spending limits on both dashboards before you hand the app out. Live dictation runs about **$0.017 a minute**, so an hour of speech a day is roughly **$22 a month per person**.

To halve it, set `"streaming_enabled": false` in a person's `config.json`. They lose the words-as-you-speak effect and wait about a second longer, and the cost drops to about $0.003 a minute.
