# Mirabel Voice

Speak instead of type — in any program on your PC.

Press **Insert**, say what you want to write, then press **Insert** again. Your words appear where you were typing, tidied up: no "um"s, correct punctuation, ready to send. It works in Claude, ChatGPT, VS Code, Outlook, Teams, and anywhere else with a text box.

## Install

Open PowerShell and paste these three lines:

```powershell
git clone https://github.com/mirabeltech/mirabel-voice.git
cd mirabel-voice
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Setup sorts out the keys, checks that they work, and starts the app. If it asks you to paste two keys, ask Tommy for them. A microphone icon appears near your clock, and Mirabel Voice starts with Windows from then on.

That is the whole install. Takes about three minutes.

## How to use it

Click into any text box. Press **Insert** once, speak, then press **Insert** again to finish.

Your hands are free while you talk. You will see the words appear as you speak, and when you press Insert again they are replaced by the tidied version.

| You want to | Do this |
|---|---|
| Start | Press **Insert** |
| Finish | Press **Insert** again |
| Throw away what you are saying | Press **Esc** |
| Paste the last dictation again | Press **Shift+Alt+Z** |

Speak naturally. Say "new paragraph" or "new line" to shape the text. If you misspeak, just correct yourself — "send it Tuesday, scratch that, Wednesday" — and the correction is applied for you.

The icon near your clock shows what is happening: **grey** ready, **red** listening, **blue** writing, **orange** something went wrong. Right-click it to turn the tidying off, copy the last text, or quit.

## Changing your key

Insert is the default because it is free on most computers. If it clashes with something you use, pick another:

```powershell
.venv\Scripts\python.exe scripts\pick_hotkey.py
```

Press the key you want and it saves your choice. Restart Mirabel Voice afterwards.

Two things to know when you choose:

- **Avoid the F keys.** Laptops use them for volume, brightness, and screenshots.
- **A key with Ctrl, Alt, Shift, or Windows in it still works for dictation, but your words cannot appear as you speak.** Windows will not accept typed characters while such a key is held, so the words show in a small preview window instead and arrive in your text box when you let go. `scroll_lock` and `pause` are good plain alternatives.

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

---

Handing this out to a team? See [ADMIN.md](ADMIN.md).
