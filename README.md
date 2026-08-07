# TONY App

**A local voice command-and-control assistant for Windows.** Say "Tony", then a
command — it matches what you said against 63 built-in actions and runs it. It also
reads your hands: vision mode turns hand gestures into cursor, clicks, volume and
scrolling.

Everything runs on your machine. **No LLM, no text-to-speech, no chat, no cloud, no
API key, no account.** One direction — your voice, the action — with no reasoning loop
in between.

<p align="center">
  <img src="docs/images/vision-mode.png" alt="Vision mode: the pill has grown into a panel holding the camera, with the gesture reference card below it" width="520">
</p>

---

## Table of contents

- [What it looks like](#what-it-looks-like)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Running it](#running-it)
- [Commands](#commands)
- [Vision mode](#vision-mode)
- [Configuration](#configuration)
- [Project layout — every file and why it exists](#project-layout--every-file-and-why-it-exists)
- [Tech stack — what is used and why](#tech-stack--what-is-used-and-why)
- [Design rules the code obeys](#design-rules-the-code-obeys)
- [Testing](#testing)
- [Privacy](#privacy)
- [License](#license)

---

## What it looks like

The whole interface is one 95×40 glass pill docked at the top of the screen, holding
the gold wordmark. It never takes focus, so your commands land on whatever app you are
actually using.

| Idle | Listening |
|---|---|
| <img src="docs/images/pill-idle.png" alt="The pill at rest" width="230"> | <img src="docs/images/pill-listening.png" alt="The pill with its border glowing" width="230"> |

It **glows at the border while listening and sits perfectly still when it is not** —
the inverse of the usual "pulse to get attention" design. An always-on tool that
animates while idle is a thing you learn to tune out.

After a command, a short popup drops out from under the pill and goes back in:

<p align="center">
  <img src="docs/images/pill-response.png" alt="A popup reading: increased volume by 10%" width="260">
</p>

<p align="center">
  <img src="docs/images/popup-motion.png" alt="The popup's entrance sampled at five points along its easing curve" width="640">
</p>

*The popup's motion, sampled along its own easing curve. Motion cannot be judged from
a still, so the render harness lays the tween out as a strip instead.*

Click the pill and the reference card drops open underneath it — every command, its
trigger phrases, a live CPU/RAM/VRAM strip, and the off switch:

<p align="center">
  <img src="docs/images/command-card.png" alt="The reference card listing all 63 commands by group" width="520">
</p>

> All the images above are produced by `tools/render_ui.py` and `tools/render_vision.py`,
> which paint the real widgets offscreen. Nothing here is a mockup, and no camera or
> microphone is touched to make them.

---

## How it works

```
"Tony"  (wake word, Vosk — always listening, CPU-only, tiny)
   or   ctrl+alt+t  (global hotkey)
        │
        ▼
  20-second active window
  rolling: every command that runs resets the timer
        │
        ▼
  faster-whisper transcribes what you said   (local; loaded, then idle until needed)
        │
        ▼
  rapidfuzz matches the transcript against the trigger list
  no model, deterministic — below the threshold, nothing happens
        │
        ▼
  the action runs   (hotkey · media key · app launch · URL · window control)
```

**Why there is no language model in the loop.** The job is "turn a short phrase into
one of 63 fixed actions". A model would add a second of latency, gigabytes of VRAM and
a class of failure — a confidently wrong action — that fuzzy matching simply does not
have. The command vocabulary is small and fixed, so a threshold on string similarity
is the *better* answer, not the cheap one.

**Why fuzzy and not exact.** Fuzzy matching is what lets a small Whisper be enough: a
misheard "scrol down" still snaps to `scroll down`. The transcriber is allowed to be
imperfect because the router forgives it.

**Two guards keep that forgiveness from becoming dangerous.** A single word like
"stop" is scored whole-string so it cannot greedily win a longer trigger, and a
transcript may exceed its trigger by at most two words — otherwise "can you close this
window for me later" would close your unsaved work, because the microphone is open for
the whole 20 seconds.

---

## Installation

### Prerequisites

| | |
|---|---|
| **OS** | Windows 10 or 11. Not portable — TONY leans on Win32 for the overlay, window control and audio. |
| **Python** | 3.12 (3.10+ should work). Install from [python.org](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**. **Not needed if you use the packaged app below.** |
| **Microphone** | Any. |
| **Webcam** | Only for vision mode. Everything else works without one. |
| **GPU** | Optional. NVIDIA + CUDA makes transcription faster; without it Whisper runs on the CPU. |
| **Disk** | ~1 GB for the app, plus ~540 MB of speech models downloaded on first run. |

### The packaged app — no Python needed

TONY builds into an ordinary Windows application you double-click. From a clone with
[PyInstaller](https://pyinstaller.org) installed:

```powershell
pip install pyinstaller
python tools/build.py
```

That writes **`dist/TONY App/`** — about 800 MB, containing `TONY App.exe` and
everything it needs. Zip that folder, unzip it anywhere on any Windows machine, and run
the .exe. No Python, no pip, no dependencies.

Check a build without launching it:

```powershell
"dist/TONY App/TONY App.exe" --selftest
```

That paints the real interface offscreen, reads every bundled asset and loads the hand
model, then exits — no window, no microphone, no camera. Everything that breaks in a
packaged build and nowhere else is a file that *is not Python*, and this finds a missing
one in seconds instead of at the moment you first wave at the camera.

`settings.json`, `gallery/` and `tony.log` are written **next to the .exe**, not inside
the bundle, so the app stays a folder you can move and your settings stay somewhere you
can find.

> To run TONY from source instead — which is what you want if you intend to change it —
> carry on below.

### 1. Get the code

```powershell
git clone https://github.com/aesatyilmaz/TONY-App.git
cd TONY-App
```

### 2. Install the dependencies

```powershell
pip install -r requirements.txt
```

That is about 400 MB, most of it PySide6 and MediaPipe. A virtual environment is
optional but tidy:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. First run downloads two models

Nothing is bundled. The first time TONY starts it fetches:

- the **Vosk** English model (~40 MB) for the wake word,
- the **faster-whisper `small`** model (~500 MB) for transcription, from HuggingFace.

Both are cached, and after that TONY works fully offline. To stay air-gapped,
pre-download them and point `vosk_model_path` and the faster-whisper cache at them.

### 4. Optional — GPU transcription

`faster-whisper` uses `torch` only to *detect* CUDA, and falls back to the CPU when it
is absent. **torch is deliberately not in `requirements.txt`** — installing it there
could overwrite a working pinned CUDA build. If you want GPU transcription, install
the build that matches your CUDA yourself:

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 5. Optional — desktop icon and start on boot

```powershell
python tools/shortcuts.py --desktop   # put TONY on your Desktop, with its icon
python tools/shortcuts.py --startup   # launch it automatically on boot
python tools/shortcuts.py --status    # what is installed (read-only)
python tools/shortcuts.py --remove    # remove both
```

Each is a `TONY.lnk` pointing at `pythonw.exe app.py` — silent, no console window —
carrying `ui/assets/tony.ico`. No admin rights, no registry changes, user-level only.

> **If you ever move or rename the project folder, re-run this.** The shortcuts hold
> absolute paths, so after a move TONY stops opening with no error at all.

### Known install snags

| Symptom | Cause and fix |
|---|---|
| The hotkey does nothing | The `keyboard` library installs a low-level hook; Windows sometimes requires an elevated terminal. The wake word still works. |
| `OMP: Error #15` on startup | Two libraries loading the same OpenMP runtime. Already handled — `KMP_DUPLICATE_LIB_OK=TRUE` is set before the heavy imports in `main.py` and `app.py`. If you write your own entry point, set it there too. |
| "the camera would not open" | Another app is holding the webcam. TONY retries across two capture backends before giving up, so close whatever has it and try again. |
| No GPU/VRAM on the card | `nvidia-smi` is missing or there is no NVIDIA GPU. The strip drops those two readings and keeps CPU and RAM. |

---

## Running it

```powershell
python app.py         # the pill (this is the one you want)
python main.py        # headless — same voice loop, console output
python main.py text   # keyboard mode: type transcripts, no microphone at all
```

`python main.py text` is the fastest way to feel the router out — you type what you
would have said and see which command it resolves to.

**Turning it off:** click the pill → **Turn off TONY**. Also on the notification-area
icon's right-click menu, and Ctrl+C in the console. That stops the listener, finalizes
any recording in flight, and ends vision mode.

**Hiding the pill:** left-click the notification-area icon. TONY keeps listening
either way.

---

## Commands

63 commands in 18 groups. Every one has several trigger phrases — click the pill for
the full list, or read `commands.py`, which is the single source of truth.

| Group | What it does |
|---|---|
| **Session** | stop listening · turn off · do that again |
| **Volume** | up / down / mute — with an amount: *"volume down 40"* sets it exactly |
| **Playback** | play, pause, next track, previous track |
| **Scroll · Zoom** | scroll up/down, zoom in/out/reset |
| **Tabs · Page** | new, close, next, previous, reopen tab · refresh · back / forward |
| **Windows** | close, minimize, maximize, show desktop, snap left/right, switch window |
| **Clipboard** | copy, paste, cut, select all, clear the field |
| **Selection** | search this · translate this · research this |
| **Undo · Keys** | undo, redo, enter, space, save |
| **Dictation** | type mode |
| **Capture** | screenshot, capture window, start/stop recording, open gallery |
| **Apps** | Google, File Explorer, Notepad, Settings, Task Manager, Claude |
| **Websites** | Gmail, YouTube, LinkedIn, Indeed, Spotify, Maps, dashboard |
| **Vision mode** | on / off |

A few worth explaining:

- **"volume down 40"** does not press the volume key twenty times. It reads the master
  volume through Core Audio and sets it, because key presses move it by a step that
  depends on the device — the same command would land somewhere different on different
  hardware.
- **"search this" / "translate this" / "research this"** copy your current selection,
  read the clipboard, and put back whatever was there before. If the copy fails,
  nothing is overwritten.
- **Type mode** dictates into the focused field and ends **three** ways: say "stop
  typing", press the hotkey, or stay quiet for five seconds. A dictation mode that
  outlives you leaving the desk would type the room's next conversation into whatever
  has focus, so it always ends itself.
- **"research this"** captures a spoken argument rather than a command — what you say
  after it is never routed, only used.

---

## Vision mode

Say **"open vision"** and the pill grows into a panel with the camera under the
wordmark. Click the logo while it is open and the card lists gestures instead of
commands. Say **"close vision"** and it shrinks back.

| Gesture | Does |
|---|---|
| Index finger | move the cursor |
| Peace sign | click |
| OK sign, held 1s | Alt+Tab window switcher |
| Open palm, swipe ← → | previous / next window, or back / forward in a browser |
| Both hands still, 2s | confirm (closes the switcher) |
| Fist, held 1s | sleep / wake vision mode |
| Left edge, drag up/down | volume |
| Right edge, drag up/down | scroll — the faster your hand moves, the further it goes |

<p align="center">
  <img src="docs/images/vision-pointer.jpg" alt="Pointer mode with the comet trail behind the fingertip" width="400">
  <img src="docs/images/vision-volume.jpg" alt="The left fader engaged, the palm glowing gold" width="400">
</p>

*Left: pointer mode, with the trail behind your fingertip. Right: the volume fader
engaged — your palm glows gold when a fader has hold of it.*

**There are no buttons.** An earlier version had tap targets around the edge of the
frame; they were removed because a button you have to aim at with your whole hand is
worse than a gesture. What is left are two edge faders (borrowed from a DJ mixer, the
founder's idea) and gestures that do not collide with each other.

**How it is wired.** Vision mode runs as its **own process** — a camera and MediaPipe
must never share a thread with the voice loop. Instead of opening its own window it
writes finished frames into **shared memory** (`vision/frames.py`: two slots and a
sequence counter), and a timer on TONY's GUI thread picks them up and paints them
inside the pill. Nothing signals the pill; it watches the buffer. The command that
starts vision mode runs on the worker thread, and a worker thread that touches a widget
is what froze this app for four rounds.

**Cursor smoothing** is a [One Euro filter](https://gery.casiez.net/1euro/) (Casiez,
Roussel & Vogel, CHI 2012) on a dedicated 120 Hz thread, not an exponential average. A
fixed-alpha average has to choose between lag and jitter; the One Euro filter adapts
its cutoff to how fast you are moving, so slow movement is steady and fast movement
still keeps up. The trail behind the fingertip is a Catmull-Rom spline through the
recent samples.

---

## Configuration

There is no settings UI — TONY is deliberately one pill. Defaults live in
`config/settings.py`; override any of them in `config/settings.json`, which is
gitignored so personal values never end up in the repo.

```json
{
  "active_window_seconds": 20.0,
  "fuzzy_threshold": 86,
  "volume_step": 5,
  "scroll_amount": 10,
  "type_mode_idle_seconds": 5.0,
  "stt_model": "small",
  "activate_hotkey": "ctrl+alt+t",
  "dashboard_url": "",
  "custom_triggers": { "open_notepad": ["notes", "scratchpad"] }
}
```

| Key | Meaning |
|---|---|
| `active_window_seconds` | how long TONY keeps listening after the wake word |
| `fuzzy_threshold` | match strictness, 0–100 (rapidfuzz WRatio). 86 is calibrated — lower it and near-misses start firing |
| `volume_step` | percentage points per "volume up/down" without an amount |
| `scroll_amount` | scroll strength |
| `type_mode_idle_seconds` | silence that ends dictation |
| `stt_model` | faster-whisper size: `tiny` · `base` · `small` · `medium` · `large-v3` |
| `stt_language` | `"en"`, or `"auto"` to let Whisper decide |
| `activate_hotkey` | the alternative to saying "Tony" |
| `vosk_model_path` | a local Vosk model instead of the downloaded one |
| `dashboard_url` | personal; ships empty, drives "open dashboard" |
| `claude_path` | only needed if the Claude desktop app is not found automatically |
| `gallery_dir` | where captures are written (default `gallery/`) |
| `custom_triggers` | `{command_name: [extra phrases]}` — add your own wording |

---

## Project layout — every file and why it exists

```
app.py                  UI entry point
main.py                 headless entry point
session.py              the one voice loop, shared by both
commands.py             the command registry
router.py               fuzzy matching
triggers_hotkey.py      the global hotkey
config/  core/  actions/  ui/  vision/  tools/  tests/  docs/
```

### Entry points and the loop

| File | What it is |
|---|---|
| `app.py` | Starts Qt, builds the pill, puts the voice loop on a `QThread`, installs the notification-area icon. Six worker signals connect to six tray slots — and a test parses this file to prove none of them is wired to a bare lambda. |
| `main.py` | The same loop with no UI. `python main.py text` swaps the microphone for the keyboard. |
| `session.py` | **`run_session()` — the single implementation** of wake → active window → transcribe → route → run. `main.py` and `ui/voice_worker.py` differ *only* in the `report()` callback they pass. They used to each hold a copy, and the copies drifted, which is why there is now exactly one. |
| `triggers_hotkey.py` | A `threading.Event` the loop can wait on alongside the wake word, so the hotkey and the voice are the same kind of thing to the loop. |

### Routing

| File | What it is |
|---|---|
| `commands.py` | Every command: trigger phrases, the function to run, and the fixed response text shown in the popup. Also `GROUPS`, which is how the reference card is laid out. One source of truth — a test proves every command appears in exactly one group. |
| `router.py` | `match()` (rapidfuzz WRatio + the two length guards), `strip_fillers()` (drops "okay", "tony", "please" from the ends and number words from anywhere), `parse_amount()` ("forty" and "40" both), `is_exit_phrase()` (stricter, for leaving type mode). |

### Voice

| File | What it is |
|---|---|
| `core/wake.py` | The always-on Vosk listener. Matches on a **word boundary**, so "antony" is not "tony", and returns whatever followed the wake word — which is what makes "Tony, volume up" work in one breath. |
| `core/stt.py` | `WhisperSTT` (greedy decoding, VAD filter) and `record_utterance()`, which records until you stop talking, using an RMS threshold — with a give-up timer so silence does not hold the microphone for the full cap. |
| `core/audio_state.py` | Two shared `threading.Event`s so a speaking TONY could never answer itself. Nothing speaks today; the seam is kept. |

### Actions — the things TONY can actually do

| File | What it is |
|---|---|
| `actions/control.py` | Keys, hotkeys, media keys, scrolling, via pyautogui. Maps key names as people say them ("windows", "escape", "return") onto pyautogui's names. |
| `actions/volume.py` | Master volume read and set **exactly**, through Core Audio (pycaw), on an MTA thread with a thread-local proxy. Counting key presses assumes a fixed step per press, and that is not true. |
| `actions/apps.py` | Launches Windows apps by name, with aliases. Claude is an MSIX package with no `.exe`, so it is started by AppUserModelID through `shell:AppsFolder`, read from the package registry. |
| `actions/web.py` | Hands a URL to the default browser. Nothing else — **TONY makes no outbound network requests of its own**, and the privacy claim below is checkable by grepping this one file. |
| `actions/screen_record.py` | Records the monitor the focused window is on, with the ffmpeg binary bundled by `imageio-ffmpeg` (gdigrab), straight into `gallery/recordings/`. |

### UI

| File | What it is |
|---|---|
| `ui/tray.py` | The pill: frameless, translucent, always-on-top, **no-activate** (Win32 `WS_EX_NOACTIVATE`) so clicking it never steals focus. Also vision mode's home — the grow/shrink, the frame timer, the drag. |
| `ui/info_window.py` | The reference card that drops out of the pill like a menu off a button. Read-only by design. Swaps between the command list and the gesture list depending on the mode. |
| `ui/glyphs.py` | The parts QSS cannot express, painted by hand: gradient-filled text, the inset top highlight, the popup's caret, and `GlassSurface` — whose `set_glass_box()` is the seam that lets the pill "grow" without the window ever resizing. |
| `ui/frame_view.py` | Draws the camera picture with the same rounded corners and gold hairline as everything else. `detach()` copies the frame before the shared memory goes away. |
| `ui/stats.py` | The CPU/RAM/VRAM strip. `nvidia-smi` runs through `QProcess`, so its output is delivered back **on the GUI thread** — no worker, and none of the hazards one brings. Only ticks while the card is visible. |
| `ui/tokens.py` | Colours, fonts and the QSS builder. Values come from `docs/UI-DESIGN.md` §7. |
| `ui/win_native.py` | ctypes Win32: the no-activate flag, DPI awareness, and `start_native_drag()` — which hands dragging to Windows via `WM_NCLBUTTONDOWN`/`HTCAPTION` so Qt never moves the window itself. |
| `ui/voice_worker.py` | Runs `session.run_session()` on a `QThread` and translates its events into Qt signals. |
| `ui/assets/` | The gold wordmark and the app icon. |

### Vision mode

| File | What it is |
|---|---|
| `vision/gesture.py` | The whole controller: MediaPipe landmarks, gesture classification, the faders, the One Euro cursor, the palm glow, the comet trail, and the HUD. Runs as its own process. |
| `vision/frames.py` | The shared-memory frame channel — two slots and an `int64` sequence number, so the reader never sees a half-written frame. |
| `vision/__init__.py` | Start and stop. `open_vision()` waits on a **named Windows event** the child sets once frames are actually flowing, so TONY can no longer report success for a child that died on a busy camera. |
| `vision/catalog.py` | The gesture list as plain data. Deliberately imports nothing — the UI process reads it, and importing `gesture.py` would drag OpenCV and MediaPipe in for the sake of a few strings. |

### Tools

| File | What it is |
|---|---|
| `tools/launch.py` | Logging under `pythonw` (where stdout and stderr are both `None`, so every print and traceback vanishes and a crash looks like a freeze), a single-instance guard, and the camera-ready handshake. |
| `tools/shortcuts.py` | Desktop and startup shortcuts. |
| `tools/watchdog.py` | Watches the GUI thread and dumps every thread's stack when it stalls — turns "it froze again" into something you can read. |
| `tools/render_ui.py` | Paints every UI state offscreen to PNGs. The safe way to look at the interface. |
| `tools/render_vision.py` | Paints every HUD state onto a synthetic frame with a synthetic hand. **The camera is somebody's live desktop — nobody gets to "just run it and look."** Also runs as a paint gate in the tests. |
| `tools/build.py` | Packages everything into `dist/TONY App/` with PyInstaller. Carries the list of what must be bundled by hand (assets, fonts, MediaPipe's models) and what must be kept out (the ML stacks MediaPipe's optional imports would otherwise drag in — 800 MB of them). |

---

## Tech stack — what is used and why

**Language:** Python 3.12, throughout. No compiled extensions of our own, no
JavaScript, no web view. The UI is native Qt.

| Library | Used for | Why this one |
|---|---|---|
| **Vosk** | wake word | Runs every second the machine is on, so it has to be tiny and CPU-only. Accuracy barely matters — it has one word to find. |
| **faster-whisper** | transcription | The accurate/expensive half of the trade, and it only runs after the wake word. CTranslate2 makes it several times faster than reference Whisper at the same quality. |
| **sounddevice** | microphone | Thin PortAudio binding; gives raw float32 blocks, which is what both the RMS endpointing and Whisper want. |
| **numpy** | audio buffers | The frame format everything speaks. |
| **rapidfuzz** | routing | Fast C++ fuzzy matching. `WRatio` handles substrings, transposition and typos in one score — the whole reason a small Whisper is enough. |
| **pyautogui** | keys, media, scroll | The action layer. Commands become the same key events you would have pressed. |
| **pycaw** + **comtypes** | exact volume | Core Audio, so "volume down 40" means 40 — not "press the key some number of times and hope". |
| **pyperclip** | selection commands | Reads what you selected, then restores the clipboard. |
| **Pillow** | screen capture, and HUD text | `ImageGrab` for window captures. It also renders every string on the vision HUD: OpenCV can only draw its own stroke font, and this build has no `cv2.freetype`, so the serif text is drawn by Pillow into cached sprites and blitted onto the frame. |
| **keyboard** | global hotkey | A system-wide hook so the hotkey works from any app. |
| **imageio-ffmpeg** | screen recording | Ships an ffmpeg binary, so recording needs no separate install. |
| **PySide6 (Qt 6)** | the interface | A real native overlay: translucency, always-on-top and no-activate, with no browser runtime. The previous build used React inside a bundled Chromium for an always-on background app — this replaced it. |
| **psutil** | CPU/RAM readings | Microseconds per read, unlike the GPU. |
| **OpenCV** | camera and drawing | Capture plus every pixel of the HUD. |
| **MediaPipe** | hand landmarks | 21 landmarks per hand, on the CPU, in real time. |
| **ctypes** → Win32 | the awkward parts | No-activate windows, native drag, `SetCursorPos`, named events and mutexes, MSIX app launching. Not a dependency — it is in the standard library. |

**Deliberately absent:** `torch` (optional, see [Installation](#installation)), any LLM
runtime, any TTS engine, any embedding or vector store, any telemetry.

---

## Design rules the code obeys

These were each learned expensively. They are documented here because they are not
obvious from reading the code — only from breaking it.

**1 · Repaint per frame, never re-geometry.** Every visible surface is a translucent,
always-on-top `Qt.Tool` window, which on Windows is a *layered* window: moving or
resizing one is synchronous Win32 work on the GUI thread. Doing it per animation frame
wedges the whole app — process alive, no traceback, nothing in the log. So the popup
slides its glass inside a taller stationary window, and the pill "grows" into the
vision panel by taking its final size *before* the first frame and animating only the
painted glass box. A test steps both animations frame by frame and asserts the window
geometry never changes.

**2 · No graphics effects on these windows.** `QGraphicsOpacityEffect` and
`QGraphicsDropShadowEffect` render a widget through an offscreen surface and composite
it back, and on a layered window that composite is where a black rectangle came from —
three times, on three unrelated triggers, always on a widget wearing an effect. Shadows
are painted by hand; fades are `QPainter.setOpacity` inside `paintEvent`.

**3 · No worker-thread signal may land on a bare lambda.** A lambda has no receiver
`QObject`, so Qt runs it in the *emitting* thread — which put widget construction on
the voice thread. Receivers are bound methods of GUI-thread objects, and
`tests/test_app_wiring.py` parses `app.py` and fails if anyone reconnects a lambda.

**4 · A trigger must survive the router's own normalisation.** `strip_fillers()` runs
on every transcript, so a trigger containing a filler or a number word reaches the
matcher shorter than itself and **can never be said out loud**. The test that pins this
found that "snap right" and "dock right" had never worked, because "right" was on the
filler list — that command was dead for its entire existence.

**5 · Uniqueness is not the same as reachability.** Trigger strings being distinct
proves nothing when the matcher is fuzzy: a trigger sitting whole inside a longer
transcript scores around 90, over the threshold. That is why "close vision mode" is not
a trigger — "vision mode" opens it — and why a second test says every trigger, spoken
exactly, must reach the command that owns it.

**6 · Never hand out a pointer into memory you are about to unmap.** The camera picture
is a numpy *view* into vision mode's shared memory. Closing it unmapped the buffer while
the 260 ms close animation was still painting: access violation, no traceback, the log
ending mid-line. `FrameView.detach()` copies first — and the order of two lines at the
call site is the difference between working and crashing silently.

---

## Testing

```powershell
python -m pytest -q
```

**97 tests, no hardware required.** The voice loop runs against fake ears and a fake
STT; the UI is painted offscreen (`QT_QPA_PLATFORM=offscreen`); the vision HUD is
painted onto a synthetic frame with a synthetic hand. Nothing opens a microphone, a
camera or a window, and no test presses a real key.

| File | Covers |
|---|---|
| `tests/test_router.py` | matching, the length guards, filler stripping, amounts, registry integrity, and the two structural guards above |
| `tests/test_session.py` | the voice loop: wake handling, the one-shot wake phrase, the rolling window, type mode's three exits |
| `tests/test_ui_smoke.py` | every UI state painted for real, the geometry rule, the pill↔panel transition, dragging, the card following the mode |
| `tests/test_vision.py` | gesture and fader logic, the readiness handshake, and a paint pass over every HUD state |
| `tests/test_control.py` | key-name parsing and media mapping — pure logic, no keys pressed |
| `tests/test_app_wiring.py` | an AST pass over `app.py`: every signal reaches a real slot, and none of them is a lambda |

---

## Privacy

TONY listens continuously and installs a global keyboard hook, so it is worth being
precise about what that means.

- **Your voice never leaves the machine.** Wake-word detection and transcription both
  run locally. There is no server, no API key, no telemetry, and no audio is written to
  disk.
- **One exception — the first run downloads models**, as described in
  [Installation](#installation). After that it is fully offline.
- **The camera is only on while vision mode is.** It opens when you ask for it, the
  process is killed when you close it, and no frame is ever written to disk.
- **The global hotkey** installs a low-level keyboard hook, which by nature sees
  system-wide key events. TONY only checks for its own combination — it does not log or
  store keystrokes — but the hook exists, and Windows may require an elevated terminal
  for it to work.
- **Captures stay local**, in `gallery/` (gitignored).
- **Commands act on the focused window.** The pill never takes focus, so voice commands
  land on whatever you are actually using — including destructive ones like "close
  window". Nothing is confirmed twice. Treat it like a keyboard.

---

## License

[MIT](LICENSE) © Esat Yilmaz

---

## Design documents

- [`docs/SPEC.md`](docs/SPEC.md) — the full design. §11 is what the build does
  differently, and it is authoritative over everything above it.
- [`docs/UI-DESIGN.md`](docs/UI-DESIGN.md) — the visual design and the design tokens.
- [`docs/ui-mockup.html`](docs/ui-mockup.html) — static visual reference; open it in a
  browser.
