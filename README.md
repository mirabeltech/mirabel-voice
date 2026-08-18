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

Use `"hi"` for Hindi, `"te"` for Telugu, `"en"` for English. Your text comes back in the language you spoke — mixed English-Hindi stays mixed.

## Good to know

- **Privacy:** your audio is processed in the cloud (OpenAI for speech, Anthropic for cleanup) under terms that exclude training on your data. The app saves nothing to disk — no audio, no history.
- **Best for prose, not code:** speaking prompts, emails, and messages works great. Dictating brackets and symbols does not.
- The hotkey can be changed in `config.json` (`"hotkey": "ctrl+win"`) — for example `"f9"` or `"ctrl+alt+space"`.

## Something is wrong?

- **No text appears:** check the tray icon. Orange means an error — hover over it to read what happened. Most often the network or a key problem.
- **Text landed in the wrong window:** press **Shift+Alt+Z** in the right window.
- **First run shows a key error:** run `setup.ps1` again and re-enter the keys.
- Still stuck? Message Tommy.
