# Mirabel Voice — v1 Specification

Status: agreed 2026-08-18 · Owner: Tommy McCormick · Target: Windows pilot

## What it is

An internal dictation tool for the organization. Hold `Ctrl+Win`, speak, release. The cleaned text appears in the active program within 1–2 seconds. It works in every app with a text field: Claude, ChatGPT, VS Code, Outlook, Teams, browsers. The primary use case is speaking prompts to AI tools instead of typing them.

## Goals

1. Key-release to pasted text in 1–2 seconds for a typical utterance.
2. Output that needs no manual editing: no filler words, correct punctuation, self-corrections applied.
3. Zero data at rest: no audio, no transcripts, no telemetry stored anywhere.
4. A non-technical coworker can install it with one script and one hotkey lesson.

## Non-goals (v1)

- Sub-second latency (requires streaming audio during speech — v2).
- Mac support (planned v1.x; keep modules portable).
- Code signing, auto-update. (The packaged installer was moved into scope on 2026-08-19 — see #11.)
- Snippets, styles/tones, screen-context awareness, voice editing of existing text.
- A relay server for API keys (revisit if pilot succeeds).

## Users and pilot

Phase 1: Tommy, a few days. Phase 2: 3–5 coworkers. Success: pilots still use it in week two without prompting. Feedback goes to Tommy directly.

## Controls

| Action | Default | Notes |
|---|---|---|
| Push-to-talk | Hold `Ctrl+Win` | Configurable; both hold and toggle modes exist |
| Lock hands-free | Double-tap `Ctrl+Win` | Press once more to stop |
| Cancel recording | `Esc` | Discards audio, nothing is sent |
| Paste last transcript | `Shift+Alt+Z` | Safety net if a paste lands wrong |

Tray icon states: grey ready, red recording, blue processing, orange error. Menu: cleanup on/off, copy last text, open settings folder, quit.

## Pipeline

1. **Capture** — 16 kHz mono from the default mic while the hotkey is down. No audio discarded at the start (Wispr's top complaint). Recordings under 0.4 s or silent are dropped.
2. **Transcribe** — one WAV to the OpenAI Whisper API (`whisper-1`), with the user's language and dictionary terms as a spelling prompt. Fallback model if multilingual accuracy disappoints: `gpt-4o-transcribe` (config change only).
3. **Clean up** — transcript to `claude-haiku-4-5`. Contract: remove fillers; apply self-corrections ("scratch that"); punctuate; apply spoken layout commands ("new paragraph"); never add, remove, translate, summarize, or answer the text. On any failure or timeout, the raw transcript is used — dictation is never lost.
4. **Insert** — clipboard paste (Ctrl+V) into the focused window, previous clipboard restored; keystroke-typing fallback for paste-blocking apps.

Latency budget (typical 10 s utterance): capture stop ~0 ms, Whisper ~800–1200 ms, Haiku ~300–600 ms, paste ~150 ms.

## Languages

English is the default. Hindi and Telugu are supported as a per-user setting (one Whisper language code). The cleanup must preserve the spoken language and mixed-language (Hinglish) text — never translate. Telugu accuracy on `whisper-1` is expected to be weaker; validate in pilot and switch transcribe model if needed.

## Dictionary

A seed file of hand-curated Mirabel terms ships with the app (Mirabel, Magazine Manager, Marketing Manager, ChargeBrite, Digital Studio, Mirabel Mobile, MagHub, ...). Users add personal words in config. Both lists feed the Whisper spelling prompt and the cleanup system prompt. The machine-mined KB glossary was reviewed and rejected as a seed source (ticket noise).

## Keys, privacy, security

- One shared org key pair (OpenAI + Anthropic), entered once by the setup script, stored in the user's config folder (`%APPDATA%\MirabelVoice`). Never in the repo.
- Owner task before pilot: set spend limits on both provider dashboards.
- Audio goes to OpenAI; transcripts go to Anthropic; both under API no-training terms. Nothing is written to disk. No telemetry.
- The keyboard listener observes keys only; it never blocks or modifies keystrokes (Wispr's worst bug class).

## Distribution

Pilot: a packaged installer, `MirabelVoiceSetup-x.y.z.exe`, from a public GitHub Release (#11). PyInstaller packs the app, Inno Setup wraps it, GitHub Actions publishes it on a `v*` tag. It installs per user, so it needs no administrator password, and it collects and validates the two keys itself.

It ships unsigned, so Windows shows "Windows protected your PC" and people click through. A certificate is the next step, not this one.

Developers still use `git clone` + `setup.ps1` (creates venv, installs, prompts for keys, offers a Startup shortcut). Both paths produce the same app.

## Cost

Streaming ships **off**, so a minute of speech costs about $0.0058: $0.003 transcription (`gpt-4o-mini-transcribe`) plus $0.0028 Haiku cleanup. Heavy use (~60 min speech/day, 22 days) is about **$7.66/user/month**.

With `streaming_enabled: true` the transcription model becomes `gpt-live-transcribe` at $0.017/min, and the same use costs about $26/user/month. Wispr Flow Pro is $15/user/month for comparison. Full table in ADMIN.md.

## Architecture (existing draft, kept)

`src/mirabel_voice/`: `config.py` (settings JSON), `audio.py` (recorder), `transcribe.py` (Whisper), `cleanup.py` (Claude), `inject.py` (paste/type), `hotkey.py` (global listener), `app.py` (pipeline + state machine), `tray.py` (icon), `__main__.py` (CLI). Tests use fakes for network and keyboard; no live API calls.

Revisions required to the draft: `Ctrl+Win` default + `win` key alias; double-tap lock; paste-last binding; cleaner switched to `claude-haiku-4-5` (drop Opus-specific effort/fallback plumbing); language setting surfaced; seed dictionary; `setup.ps1`; README for non-technical users.

## Risks

| Risk | Mitigation |
|---|---|
| Telugu accuracy poor | Switch to `gpt-4o-transcribe`; validate in phase 1 |
| Shared key leaks | Spend limits + rotation; relay server if rollout widens |
| App blocks paste | Keystroke fallback + `Shift+Alt+Z` re-paste |
| Cleanup rewrites meaning | Strict contract prompt; cleanup can be toggled off in tray |
| Latency misses target on long dictation | Cap recording at 5 min; document that length scales latency |
