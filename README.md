# Mirabel Voice

Speak instead of type — in any program on your PC.

Press **Insert**, say what you want to write, then press **Insert** again. Your words appear where you were typing, tidied up: no "um"s, correct punctuation, ready to send. It works in Claude, ChatGPT, VS Code, Outlook, Teams, and anywhere else with a text box.

## Install

**[Download Mirabel Voice](https://github.com/mirabeltech/mirabel-voice/releases/latest)** — take the `MirabelVoiceSetup` file and run it.

Three things to expect:

1. **Windows says "Windows protected your PC".** Click **More info**, then **Run anyway**. Windows says this about every program that has not paid for a certificate. Ours has not yet.
2. **The installer asks for two keys.** Ask Tommy for them, and paste one into each box. It tests them before it finishes, so a wrong key is caught now rather than mid-sentence next week.
3. **It does not ask for an administrator password.** Everything goes in your own profile.

A microphone icon appears near your clock, and Mirabel Voice starts with Windows from then on. The whole thing takes about two minutes.

To update later, download and run the newer file. Your settings and keys stay as they are.

<details>
<summary>Installing from the source code instead (for developers)</summary>

```powershell
git clone https://github.com/mirabeltech/mirabel-voice.git
cd mirabel-voice
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Setup sorts out the keys, checks that they work, and starts the app.

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

The icon near your clock shows what is happening: **grey** ready, **red** listening, **blue** writing, **orange** something went wrong. Right-click it to turn the tidying off, copy the last text, change your dictation key, or quit.

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

## Something is wrong?

- **Nothing appears.** Look at the icon near your clock. Orange means an error; hover over it to read what happened. Usually the network or a key.
- **Your text landed in the wrong window.** Press **Shift+Alt+Z** in the right one.
- **Your key does nothing.** It may be one your laptop keeps for itself. Run the key picker above and choose another.
- **Words appear in a small box instead of your text box.** Your key has Ctrl, Alt, Shift, or Windows in it. Pick a plain key.
- Still stuck? Message Tommy.

## Removing it

Open **Settings**, then **Apps**, find **Mirabel Voice**, and choose **Uninstall**. Your settings and keys stay in `%APPDATA%\MirabelVoice`, so a later install picks up where you left off. Delete that folder too if you want nothing left behind.

---

Handing this out to a team? See [ADMIN.md](ADMIN.md).
