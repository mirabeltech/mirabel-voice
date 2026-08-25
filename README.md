# Mirabel Voice

Speak instead of type — in any program on your PC.

Press **Insert**, say what you want to write, then press **Insert** again. Your words appear where you were typing, tidied up: no "um"s, correct punctuation, ready to send. It works in Claude, ChatGPT, VS Code, Outlook, Teams, and anywhere else with a text box.

## Install

**[Get the download from the shared drive](https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA)** — sign in with your Mirabel Google account if Drive asks. The download is only open to Mirabel people, because the file carries the address of our server.

Then:

1. **Unblock the download**: in your Downloads folder, right-click the zip, choose **Properties**, tick **Unblock** at the bottom, and click **OK**. Windows marks everything that arrives from the internet and refuses to run marked scripts; that one tick says you trust where this came from. Skip it and the next steps end in a "blocked a file that may be unsafe" message.
2. **Then unzip it**: right-click the zip again and choose **Extract All**. Double-clicking the zip only peeks inside it — nothing can install from in there.
3. **In the extracted folder, right-click `Install`**, choose **Show more options**, then **Run with PowerShell**. (Windows 11 tucks that option behind Show more options.)
4. **Sign in when your browser opens.** The first time the app starts, it opens the Google sign-in page — use your Mirabel work account, the same one as your email. That is the whole setup: no token to paste, no API keys to enter, nothing new to keep. (An older download asks for a token instead; if yours does, ask Tommy for one.)

It does not ask for an administrator password. Everything goes in your own profile.

A microphone icon appears near your clock, and Mirabel Voice starts with Windows from then on. The whole thing takes about two minutes.

One thing Windows does that we cannot stop: it tucks new icons behind the **^** arrow near the clock. Click the arrow to find the microphone, then drag the icon onto the taskbar itself so it is always in view. Worth the five seconds — the icon's colour is how you know the app is listening.

To update later, unzip the newer file and run `Install.ps1` again. Your settings and your token stay as they are, and it does not ask for the token again.

<details>
<summary>If Windows says it cannot run the script</summary>

Windows blocks downloaded scripts until you say otherwise. Open PowerShell in the unzipped folder and run this instead, which does the same thing:

```powershell
powershell -ExecutionPolicy Bypass -File Install.ps1
```

</details>

<details>
<summary>Installing from the source code instead (for developers)</summary>

```powershell
git clone https://github.com/mirabeltech/mirabel-voice.git
cd mirabel-voice
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Add `-RelayUrl https://<the relay address>` to set the machine up against the relay, the same as the installer does. Setup asks for your token, checks it, and starts the app. Without that switch it asks for provider keys instead and calls OpenAI and Anthropic directly, which is the development mode.

</details>

## How to use it

Click into any text box. Press **Insert** once, speak, then press **Insert** again to finish.

Your hands are free while you talk. Press Insert again and the tidied text appears in your text box about two seconds later.

| You want to | Do this |
|---|---|
| Start | Press **Insert** |
| Finish | Press **Insert** again |
| Throw away what you are saying | Press **Esc** |
| Paste the last dictation again | Press **Shift+Alt+Z** |

Speak naturally. Say "new paragraph" or "new line" to shape the text. If you misspeak, just correct yourself — "send it Tuesday, scratch that, Wednesday" — and the correction is applied for you.

A small panel appears near the bottom of your screen while this happens. It says **Listening** while you speak and **Writing your text** while your words are being tidied, then goes away when the text lands. It is there so that the wait never leaves you wondering whether anything is happening. It cannot be clicked and never takes your cursor away from what you are typing in.

When a dictation produces nothing, the panel says why instead of vanishing: too short, no sound, nothing heard.

The icon near your clock shows the same thing in colour: **grey** ready, **red** listening, **blue** writing, **orange** something went wrong. Right-click it to turn the tidying off, copy the last text, change your dictation key, or quit.

To turn the panel off, set `"show_status": false` in `config.json` (right-click the icon, **Open the settings folder**).

## What the beeps mean

The app talks to you in four sounds, so you never have to look at the icon:

| Sound | When | Meaning |
|---|---|---|
| One mid tone | You press to start | The microphone is open — speak |
| One lower tone | You press to finish | Your words were captured; the tidying has begun |
| One soft high tone | A second or two later | The text is on screen — safe to press Enter or dictate again |
| Two low tones | A press the app could not honor | "I heard you, but I am busy or something is wrong" |

A normal dictation sounds like: **mid** → you speak → **lower** → short silence → **high**. The silence is the tidying at work. The high tone is your green light.

The double-low always means the press arrived but was refused — never that the app missed you, and never that words were lost:

- **You pressed to start while the last dictation was still finishing.** Wait for its high tone, then press again.
- **You pressed to stop when nothing was recording.** Press once more to start fresh.
- **The microphone did not open.** The icon goes orange; hover over it for the reason.
- **You clicked into another window before the text arrived.** It was held back rather than pasted into the wrong place. Click into the right box and press **Shift+Alt+Z**.

One rule covers everything: do not act before the high tone, and do not worry after the double-low.

To turn all sounds off, set `"play_sounds": false` in `config.json` (right-click the icon, **Open the settings folder**).

## Changing your key

Insert is the default because it is free on most computers. If it clashes with something you use, pick another: right-click the icon near your clock and choose **Change my dictation key**.

Press the key you want and it saves your choice. Restart Mirabel Voice afterwards.

Two things to know when you choose:

- **Avoid the F keys.** Laptops use them for volume, brightness, and screenshots.
- **Plain keys are best.** A key with Ctrl, Alt, Shift, or Windows in it also works for dictation. `scroll_lock` and `pause` are good plain alternatives.

## Your words, spelled right

Mirabel names — ChargeBrite, MagHub, Magazine Manager and the rest — are built in and spell correctly from the start.

To add your own words, right-click the icon near your clock, choose **Open the settings folder**, and edit `config.json`:

```json
"custom_words": ["Acme Publishing", "Priya Ramesh"]
```

## Dictating in Hindi or Telugu

In the same `config.json`:

```json
"language": "hi"
```

Use `"hi"` for Hindi, `"te"` for Telugu, `"en"` for English. Your words come back in the language you spoke; nothing is ever translated.

If you often mix languages in one sentence, use `"language": null` instead and the app works out the language itself.

## Good to know

- **Privacy.** Your speech is processed in the cloud, under terms that exclude training on your data. Nothing is saved on your computer — no recordings, no history.
- **Prose, not code.** Prompts, emails, and messages work very well. Dictating brackets and symbols does not.
- **Do not click into another window while speaking.** If you do, the app leaves the untidied words where they landed instead of editing a document it no longer owns. Press **Shift+Alt+Z** to put the clean version where you want it.
- **If the internet drops** mid-sentence, the app quietly falls back to sending the recording when you let go. You still get your text.
- **Only one copy runs at a time.** Starting it again does not open a second one — it just tells you it is already running and points you to the icon near the clock.

## Something is wrong?

- **Nothing appears.** The panel near the bottom of the screen says what happened, and stays for a few seconds. If you missed it, look at the icon near your clock: orange means an error, and hovering over it shows the same reason. Usually the network.
- **No icon near your clock.** It is hiding behind the **^** arrow. Click the arrow, then drag the microphone onto the taskbar so it stays put.
- **Your text landed in the wrong window.** Press **Shift+Alt+Z** in the right one.
- **Your key does nothing.** It may be one your laptop keeps for itself. Run the key picker above and choose another.
- **Words appear in a small box instead of your text box.** Your key has Ctrl, Alt, Shift, or Windows in it. Pick a plain key.
- Still stuck? Message Tommy.

## Removing it

Open **Settings**, then **Apps**, find **Mirabel Voice**, and choose **Uninstall**. Your settings and your token stay in `%APPDATA%\MirabelVoice`, so a later install picks up where you left off. Delete that folder too if you want nothing left behind.

---

Handing this out to a team? See [ADMIN.md](ADMIN.md).
