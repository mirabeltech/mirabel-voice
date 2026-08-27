# Mirabel Voice

Speak instead of type — in any program on your PC.

Press **Insert**, say what you want to write, then press **Insert** again. Your words appear where you were typing, tidied up: no "um"s, correct punctuation, ready to send. It works in Claude, ChatGPT, VS Code, Outlook, Teams, and anywhere else with a text box.

## Install

**[Get the download from the shared drive](https://drive.google.com/drive/folders/0AL2zqxan1Ec6Uk9PVA)** — sign in with your Mirabel Google account if Drive asks. The download is only open to Mirabel people, because the file carries the address of our server.

Then:

1. **Open PowerShell**: press the Windows key, type `powershell`, and press Enter.
2. **Paste this line and press Enter** (a right-click pastes in PowerShell, if Ctrl+V does nothing):

   ```powershell
   irm https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/install.ps1 | iex
   ```

   It finds the zip you downloaded, unpacks it, and runs the installer inside. There is nothing to unblock, nothing to extract, and nothing to right-click. Pasted the line before downloading? It opens the shared drive for you and waits.

3. **Sign in when your browser opens.** Use your Mirabel work account, the same one as your email. That is the whole setup: no token to paste, no API keys to enter, nothing new to keep. (An older download asks for a token instead; if yours does, ask Tommy for one.)
4. **Pick your language**: click the microphone icon near the clock (click the **^** arrow if it is hidden) to open the controls, and pick English, Hindi, Hungarian, Kannada, Marathi, Tamil, or Telugu in the **Language** box — or **Detect automatically** if you mix languages when you speak. English is the default, so skip this step if that is you. Prefer to speak your language but write in English? Tick **Translate to English** on the same card.

![The microphone icon behind the ^ arrow near the clock](https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/docs/images/tray-icon.png)

Updates take care of themselves: once a day the app checks for the newest release, swaps it in, and restarts between dictations. In a hurry, right-click the icon near your clock and choose **Check for updates** — or paste the same line again; all three do the same careful thing, and your settings stay as they are. (The rare release that changes the app's foundations is the exception: the app keeps the old version, and the icon's tooltip sends you back to the shared drive for a fresh zip.) To keep a version, set `"auto_update": false` in `config.json`.

<details>
<summary>If the pasted line will not run</summary>

The zip installs by hand too — this is what the pasted line does for you:

1. **Double-click the downloaded zip**, click the **⋯** button in the toolbar, choose **Properties**, tick **`Unblock`** at the bottom, and click OK. Windows marks everything that arrives from the internet and refuses to run marked scripts; that one tick says you trust where this came from. Skip it and the install ends in a "blocked a file that may be unsafe" message.

   ![The ⋯ menu in the zip's toolbar](https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/docs/images/install-1-open-zip.png)

   ![The Unblock checkbox at the bottom of Properties](https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/docs/images/install-3-unblock.png)

2. **Click `Extract all`** in the same toolbar, and extract to somewhere you can find, such as your Downloads folder.

3. **Open the extracted folder, click `Install` once to select it, then right-click it** and choose **Run with PowerShell**. The option only appears when the file is selected first. If your menu does not show it, look under **Show more options**.

   ![Run with PowerShell in the right-click menu](https://raw.githubusercontent.com/mirabeltech/mirabel-voice/main/docs/images/install-5-run.png)

If Windows still refuses the script, open PowerShell in the extracted folder and run:

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

The icon near your clock shows the same thing with a small colour badge: no badge means ready, **red** listening, **blue** writing, **orange** something went wrong. **Click it** to open the controls — microphone, language, translation, copy the last text, and your dictation key all live there. Right-click it for the rest: check for updates, open the settings folder, or quit.

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

Insert is the default because it is free on most computers. If it clashes with something you use, pick another: click the icon near your clock, press **Change key…**, and press the key you want. It works from your very next dictation — no restart.

Two things to know when you choose:

- **Avoid the F keys.** Laptops use them for volume, brightness, and screenshots.
- **Plain keys are best.** A key with Ctrl, Alt, Shift, or Windows in it also works for dictation. `scroll_lock` and `pause` are good plain alternatives.

## Your words, spelled right

Mirabel names — ChargeBrite, MagHub, Magazine Manager and the rest — are built in and spell correctly from the start.

To add your own words, right-click the icon near your clock, choose **Open the settings folder**, and edit `config.json`:

```json
"custom_words": ["Acme Publishing", "Priya Ramesh"]
```

## Dictating in another language

Click the icon near your clock and pick Hindi, Hungarian, Kannada, Marathi, Tamil, Telugu, or English in the **Language** box. The switch applies to your very next dictation — no restart. Your words come back in the language you spoke.

If you often mix languages in one sentence, pick **Detect automatically** and the app works out each dictation's language itself.

**To speak one language and write another**, tick **Translate to English** on the same card. Speak Telugu — or anything else the app understands — and the text that lands in your text box is written English, tidied the same way as always: a question stays a question, and your own words stay yours. Untick it to turn it off. Like the language switch, it applies to your very next dictation, and it is your setting alone — nobody else's copy changes.

Both settings live in `config.json`: `"language"` as `"en"`, `"hi"`, `"hu"`, `"kn"`, `"mr"`, `"ta"`, `"te"`, or `null` to detect, and `"translate_to_english"` as `true` or `false`.

## Good to know

- **Privacy.** Your speech is processed in the cloud, under terms that exclude training on your data. Nothing is saved on your computer — no recordings, no history.
- **Prose, not code.** Prompts, emails, and messages work very well. Dictating brackets and symbols does not.
- **Do not click into another window while speaking.** If you do, the app leaves the untidied words where they landed instead of editing a document it no longer owns. Press **Shift+Alt+Z** to put the clean version where you want it.
- **If the internet drops** mid-sentence, the app quietly falls back to sending the recording when you let go. You still get your text.
- **Only one copy runs at a time.** Starting it again does not open a second one — it just tells you it is already running and points you to the icon near the clock.

## Something is wrong?

- **Nothing appears.** The panel near the bottom of the screen says what happened, and stays for a few seconds. If you missed it, look at the icon near your clock: orange means an error, and hovering over it shows the same reason. Usually the network.
- **No icon near your clock.** It is hiding behind the **^** arrow. Click the arrow and it is there; the Taskbar settings step under Install keeps it in view for good.
- **Your text landed in the wrong window.** Press **Shift+Alt+Z** in the right one.
- **Your key does nothing.** It may be one your laptop keeps for itself. Run the key picker above and choose another.
- Still stuck? Message Tommy.

## Removing it

1. Right-click the icon near your clock and choose **Quit**.
2. Delete the folder `%LOCALAPPDATA%\Programs\Mirabel Voice` (paste that into the File Explorer address bar).
3. Delete the **Mirabel Voice** shortcut from your Desktop, and the one in your Startup folder (paste `shell:startup` into the address bar) so Windows stops starting it.

Your settings stay in `%APPDATA%\MirabelVoice`, so a later install picks up where you left off. Delete that folder too if you want nothing left behind.

---

Handing this out to a team? See [ADMIN.md](ADMIN.md).
