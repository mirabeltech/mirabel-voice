# Mirabel Voice

Speak instead of type — in any program on your PC.

Hold **Ctrl+Win**, say what you want to write, and release. One to two seconds later, your words appear at your cursor as clean, finished text: no "um"s, correct punctuation, ready to send. It works in Claude, ChatGPT, VS Code, Outlook, Teams, and every other program with a text box.

## Install (about 3 minutes)

1. Ask Tommy for the two API keys.
2. Open PowerShell and run these three lines:

   ```powershell
   git clone https://github.com/mirabeltech/mirabel-voice.git
   cd mirabel-voice
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```

3. The script asks for the two keys and puts a **Mirabel Voice** shortcut on your Desktop. Double-click it. A small microphone icon appears near your clock.

That is the whole install.

## How to use it

| You want to | Do this |
|---|---|
| Dictate | Click into a text box. Hold **Ctrl+Win** and speak. Release. |
| Dictate hands-free | Tap **Ctrl+Win** twice quickly. Speak as long as you like. Press **Ctrl+Win** once to finish. |
| Throw away a recording | Press **Esc** while recording. Nothing is sent. |
| Paste the last dictation again | Press **Shift+Alt+Z**. Useful if it landed in the wrong window. |

Speak naturally. Say "new paragraph" or "new line" to shape the text. If you misspeak, just correct yourself ("send it Tuesday — scratch that — Wednesday"); the correction is applied for you.

**You see your words as you speak.** A small dark box appears near the bottom of the screen showing what has been heard so far. It is a preview only — nothing is typed into your program until you release the key, because the cleanup needs your whole sentence to remove the "um"s and apply your corrections.

### Typing straight into your document

If you would rather watch the words land in the actual text box, set `"live_insert": true` in `config.json`. The words then type themselves as you speak, and when you release the key they are replaced by the tidied version.

Two things to know before you turn it on:

- **Do not click into another window while speaking.** If you do, the app stops and leaves the raw words where they landed rather than deleting text in a document it no longer owns. Press **Shift+Alt+Z** to paste the clean version where you want it.
- It works by deleting and retyping its own words. It is well behaved in ordinary text boxes, but a program that reformats as you type — or autocorrects — can confuse it. Try it in the programs you use before you rely on it.

The tray icon shows what the app is doing: **grey** ready, **red** recording, **blue** writing your text, **orange** something failed. Right-click it to switch the AI cleanup on or off, copy the last text, or quit.

## Your words, spelled right

Mirabel product names (ChargeBrite, MagHub, Magazine Manager, ...) are built in and spell correctly from day one. To add your own terms — client names, coworkers — right-click the tray icon, choose **Open the settings folder**, and add them to `custom_words` in `config.json`:

```json
"custom_words": ["Acme Publishing", "Priya Ramesh"]
```

## Dictating in Hindi or Telugu

In the same `config.json`, change `language`:

```json
"language": "hi"
```

Use `"hi"` for Hindi, `"te"` for Telugu, `"en"` for English. The cleanup step never translates what you said.

If you often mix languages in one sentence (English-Hindi, for example), use `"language": null` instead. The transcriber then detects the language itself instead of forcing one.

## Good to know

- **Privacy:** your audio is processed in the cloud (OpenAI for speech, Anthropic for cleanup) under terms that exclude training on your data. The app saves nothing to disk — no audio, no history.
- **Best for prose, not code:** speaking prompts, emails, and messages works great. Dictating brackets and symbols does not.
- **Live words cost more.** Streaming runs about $0.017 per minute of speech instead of $0.003. To go back to the cheaper, slightly slower way, set `"streaming_enabled": false` in `config.json`. To keep the speed but hide the preview box, set `"show_overlay": false`.
- If the network drops mid-sentence, the app quietly falls back to sending the recording after you release. You still get your text.
- The hotkeys can be changed in `config.json` — for example `"hotkey": "f9"` or `"paste_last_hotkey": "ctrl+alt+v"`. Both use the same format: key names joined with `+`.

## Something is wrong?

- **No text appears:** check the tray icon. Orange means an error — hover over it to read what happened. Most often the network or a key problem.
- **Text landed in the wrong window:** press **Shift+Alt+Z** in the right window.
- **First run shows a key error:** run `setup.ps1` again and re-enter the keys.
- Still stuck? Message Tommy.
