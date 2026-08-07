# TONY App

TONY is a 100% local, voice-driven command-and-control assistant for Windows.
Say "Tony", then a command — it fuzzy-matches to one of 63 built-in actions and
runs it. No LLM, no TTS, no chat — everything runs on your machine
(see [Privacy](#privacy) for the one first-run exception).

It also sees your hands: **vision mode** turns hand gestures into cursor, clicks,
volume and scrolling, and it lives inside TONY's own pill rather than in a
window of its own.

## Architecture

```
"Tony" (wake word, Vosk)
  → 20s rolling active window (each matched command resets the timer)
    → faster-whisper STT (local, GPU) transcribes what you say
      → fuzzy router (rapidfuzz) matches the transcript to a command trigger
        → action runs (hotkey, media key, app launch, window control, ...)
```

No model decides anything. The router is `rapidfuzz` over a fixed list of trigger
phrases, which is what lets a small Whisper be enough: a misheard word still snaps
to the nearest known command, and anything below the threshold is ignored rather
than guessed at.

- `core/wake.py` — always-on wake word listener (Vosk)
- `core/stt.py` — command transcription (faster-whisper)
- `router.py` — fuzzy trigger matching (rapidfuzz)
- `commands.py` — the command registry (single source of truth for triggers → actions)
- `actions/` — action handlers: apps, web, control (keys/media/scroll), screen recording
- `vision/` — hand-gesture control, in its own process, drawing into the pill
- `session.py` — the one voice loop, shared by the console and the UI
- `ui/` — the overlay (PySide6): a small glass pill docked top-centre showing the TONY
  logo. It glows while TONY is listening, sits still when it isn't, and drops a short
  popup under itself after a command. Click it for the reference card, which carries
  a CPU/RAM/VRAM strip and the **Turn off TONY** button.
- `main.py` — headless orchestration loop
- `app.py` — UI entry point (tray)
- `docs/` — the design spec and the UI visual design

## Install

```powershell
pip install -r requirements.txt
```

No Ollama, no API key, no account. Python 3.12 on Windows; a GPU makes Whisper
faster but is not required.

## Run

```powershell
python app.py         # tray UI (recommended)
python main.py        # headless voice mode
python main.py text   # keyboard mode — mic-free router testing
```

**Turning it off:** click the TONY pill → **Turn off TONY** at the top of the
reference card. (Also on the notification-area icon's right-click menu, and Ctrl+C
in the console.) That stops the listener, finalizes any recording, and ends vision mode.

**Hiding the pill:** left-click the notification-area icon to hide or show it —
TONY keeps listening either way.

## Commands

63 voice commands in 18 groups:

- **Session** — stop listening, turn off, do that again
- **Volume · Playback** — volume up/down (with an amount: "volume down 40"), mute,
  play/pause, next/previous track
- **Scroll · Zoom** — scroll up/down, zoom in/out/reset
- **Tabs · Page** — new/close/next/previous/reopen tab, refresh, back/forward
- **Windows** — close, minimize, maximize, show desktop, snap left/right, switch window
- **Clipboard · Undo · Keys** — copy, paste, cut, select all, clear the field,
  undo, redo, enter, space, save
- **Selection** — search this, translate this, research this (select something first)
- **Dictation** — type mode: everything you say is typed into the focused field
- **Capture** — screenshot, capture window, start/stop recording, open gallery
- **Apps** — Google, File Explorer, Notepad, Settings, Task Manager, Claude
- **Websites** — Gmail, YouTube, LinkedIn, Indeed, Spotify, Maps, dashboard
- **Vision mode** — turn hand-gesture control on and off

Full list with exact trigger phrases: `commands.py`, or click the pill.

**Type mode** ends three ways — say "stop typing", press the hotkey, or stay quiet
for five seconds. A dictation mode that outlives you leaving the desk would type the
room's next conversation into whatever has focus, so it always ends itself.

## Vision mode — hand gestures

Say "open vision" and the pill grows into a panel with the camera under the wordmark.
Click the logo while it's open and the card lists gestures instead of commands.

| Gesture | Does |
|---|---|
| Index finger | move the cursor |
| Peace sign | click |
| OK sign, held 1s | Alt+Tab |
| Open palm, swipe | back / forward |
| Fist, held 1s | sleep / wake vision mode |
| Left edge, drag up/down | volume |
| Right edge, drag up/down | scroll — the faster you move, the further it goes |

It runs as a **separate process**, because a camera and MediaPipe must never share a
thread with the voice loop. Frames arrive in TONY through shared memory and are
painted by the pill. Ending vision mode shrinks the pill back and returns the reference
card to commands.

## Configuration

There is no settings UI — TONY is deliberately a single glowing pill. Defaults live in
`config/settings.py`; override any of them in `config/settings.json` (not committed —
see `.gitignore`). Common knobs:

- `active_window_seconds` — how long TONY keeps listening after the wake word (20)
- `fuzzy_threshold` — match strictness (0-100, rapidfuzz WRatio; 86)
- `volume_step` — volume key presses per "volume up/down" command
- `scroll_amount` — scroll strength
- `type_mode_idle_seconds` — silence that ends dictation (5)
- `stt_model` — faster-whisper model size (`small`)
- `custom_triggers` — `{command_name: [extra trigger words]}` to add your own phrases
- `dashboard_url` — personal; ships empty, set your own for the "open dashboard" command
- `claude_path` — path to the Claude desktop app if it isn't found automatically
- `gallery_dir` — where captures are written (default: `gallery/`)

## Privacy

TONY listens continuously and installs a global hotkey hook, so it's worth being
precise about what that means:

- **Your voice never leaves the machine.** Wake-word detection (Vosk) and
  transcription (faster-whisper) both run locally. There is no server, no API key,
  no telemetry, and no audio is written to disk.
- **One exception — first run downloads models.** Vosk fetches its English model and
  faster-whisper fetches the chosen Whisper model (from HuggingFace) the first time
  they run. After that TONY works fully offline. To stay air-gapped, pre-download the
  models and point `vosk_model_path` / the faster-whisper cache at them.
- **The camera is only on while vision mode is.** It opens when you say "open vision" and
  the process is killed when you close it. No frame is ever written to disk.
- **The global hotkey** (`keyboard` library) installs a low-level keyboard hook, which
  by nature sees system-wide key events. TONY only checks for its own combo — it does
  not log or store keystrokes — but the hook exists, and Windows may require an
  elevated terminal for it to work.
- **Captures stay local.** Screenshots and recordings are written to `gallery/`
  (gitignored) and are never uploaded.
- **Commands act on the focused window.** The pill never takes focus, so voice
  commands land on whatever app you're actually using — including destructive ones
  like "close window". Nothing is confirmed twice; treat it like a keyboard.

## Desktop icon & start on boot

```powershell
python tools/shortcuts.py --desktop   # put TONY on your Desktop, with its icon
python tools/shortcuts.py --startup   # launch it automatically on boot
python tools/shortcuts.py --status    # what's installed
python tools/shortcuts.py --remove    # remove both
```

Each is a `TONY.lnk` pointing at `pythonw.exe app.py` (silent — no console window),
carrying `ui/assets/tony.ico`. No admin rights, no registry changes — user-level only.

## Tests

```powershell
python -m pytest -q
```

96 tests, no hardware needed: the voice loop runs against fake ears and a fake STT,
and the UI is painted offscreen (`QT_QPA_PLATFORM=offscreen`) so a paint-time crash
fails a test instead of only showing up on screen.

## Docs

- `docs/SPEC.md` — the design, and §11 for everything the build does differently
- `docs/UI-DESIGN.md` — the visual design and the design tokens
- `docs/ui-mockup.html` — static visual reference, open it in a browser
