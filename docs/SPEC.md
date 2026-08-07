# TONY App — Design Spec

> Date: 2026-08-04. The locked design for the reshape into command-and-control; what
> came before it is in `archive/HISTORY.md`. Everything English.
> **Status 2026-08-05: BUILT.** The sections below are the original design; where the
> build knowingly diverged after live testing, see **§11 As-built delta** at the end —
> that section wins over anything above it.

## 1. Philosophy (north star)
100% local, minimal, lightweight **voice command-and-control** tool. Runs always-on in the background **without slowing the computer**. It is command-and-control, **NOT** a chat assistant.

**Deliberately not here:** a thinking LLM brain, TTS (Tony does not speak), chat, RAG memory, in-loop vision, proactive check-ins. The earlier build had all six; each one is why it was heavy.

**Flow:** your voice → recognize the command → execute the action. One direction, no reasoning loop.

## 2. Architecture (pipeline)
1. **Trigger** — wake-word ("Tony" via Vosk) OR global hotkey OR double-clap. Opens the **active window**.
2. **Active window** — after wake, stay actively listening for **20s**, accepting multiple commands back-to-back. **Rolling: each executed command resets the 20s timer;** it closes after 20s of silence, then the wake word is required again.
3. **Capture** — record a short audio clip.
4. **STT** — Whisper transcribes the clip → transcript text. *(the only model; on-demand)*
5. **Router** — `rapidfuzz` fuzzy-matches the transcript against the command registry → best command (+ optional argument). **No model, deterministic.** If the best match is below a confidence threshold → do nothing (ignore).
6. **Execute** — send hotkey / launch app / open URL(s).

**Two model-free safety nets:** (a) fuzzy matching forgives STT errors ("scrol down" → `scroll down`); (b) the command vocabulary is small and fixed, so mismatch is unlikely.

### 2.1 Focus handling (critical)
Hotkey commands go to the **foreground window**, so Tony's own window must never steal focus:
- Tray window is a **no-activate window** (Win32 `WS_EX_NOACTIVATE`) — it shows and can be clicked without stealing foreground, so voice commands always land on the app the user was using.
- Tony also **remembers the last non-Tony foreground window**; before sending a hotkey from a **button click** (a click does focus Tony), it restores focus to that window first.

### 2.2 Command tuning
Magnitude/behavior values live in `config` (sensible defaults, editable from the Settings panel):
- `volume_step` — number of `VK_VOLUME_UP/DOWN` presses per command (1 press ≈ 2% on Windows; default 5 ≈ 10%).
- `scroll_amount` — wheel notches / lines per scroll command.
- `fuzzy_threshold` — minimum match score to accept a command.
- Custom trigger words per command are user-editable in Settings. *(ponytail: calibration knobs — real volume/scroll steps vary by OS/hardware.)*

## 3. Model & VRAM budget
- **Only model = Whisper STT** (~1–2GB, runs only while you speak). Candidate to shrink to Whisper small/base (~0.2–0.5GB) since the vocab is tiny and fuzzy matching covers STT errors — **decided in plan.**
- **Wake word (Vosk)** ~50MB, CPU.
- **Router** — no model, negligible CPU.
- **Dropped along the way:** LLM brain (~2GB), Kokoro TTS, embeddings, in-loop vision. The earlier build juggled three models in 8GB; this one runs one, on-demand.

## 4. Components (isolated units)
- **`triggers`** — wake-word (Vosk) + global hotkey + double-clap; signals when to listen. *(carried over from the earlier `core/`)*
- **`stt`** — Whisper transcribe. *(carried over from the earlier `core/stt`)*
- **`router`** — command registry + rapidfuzz match → resolved command. Pure & testable.
- **`actions`** — executor: hotkey sender, app launcher, URL opener (single/multi).
- **`commands.py`** — the single command registry (one source of truth): each entry = `{triggers[], type, payload, response}` (`response` = fixed feedback text shown in the UI, e.g. "increased volume by 10%").
- **`ui`** — PySide6/Qt tray overlay (see §6). Each button fires the same action as its voice command.
- **`config`** — single dict: app paths (Chrome, Claude), `volume_step`, `scroll_amount`, `fuzzy_threshold`, hotkeys. Editable from Settings.

## 5. Command registry (full set)

### Media & System
| Command | Mechanism | Triggers |
|---|---|---|
| Volume up | `VK_VOLUME_UP` | volume up, louder, turn it up, increase volume |
| Volume down | `VK_VOLUME_DOWN` | volume down, quieter, turn it down, lower volume |
| Mute / Unmute | `VK_VOLUME_MUTE` | mute, unmute, silence, sound off/on |
| Play / Pause | `VK_MEDIA_PLAY_PAUSE` | pause, play, resume, pause track |
| Next track | `VK_MEDIA_NEXT_TRACK` | next track, next song, skip song |
| Previous track | `VK_MEDIA_PREV_TRACK` | previous track, previous song, last song |

### Scroll
| Command | Mechanism | Triggers |
|---|---|---|
| Scroll down | wheel / PageDown | scroll down, go down, down |
| Scroll up | wheel / PageUp | scroll up, go up, up |

### Zoom
| Command | Mechanism | Triggers |
|---|---|---|
| Zoom in | `Ctrl +` | zoom in, bigger, enlarge |
| Zoom out | `Ctrl -` | zoom out, smaller |
| Reset zoom | `Ctrl 0` | reset zoom, actual size, default zoom |

### Tabs & Browser Navigation
| Command | Mechanism | Triggers |
|---|---|---|
| New tab | `Ctrl+T` | new tab, open a tab |
| Close tab | `Ctrl+W` | close tab, close this tab |
| Next tab | `Ctrl+Tab` | next tab, switch tab |
| Previous tab | `Ctrl+Shift+Tab` | previous tab, last tab |
| Reopen closed tab | `Ctrl+Shift+T` | reopen tab, restore tab, reopen closed tab |
| Refresh | `F5` | refresh, reload, reload page |
| Back | `Alt+Left` | go back, back, previous page |
| Forward | `Alt+Right` | go forward, forward, next page |

### Windows
| Command | Mechanism | Triggers |
|---|---|---|
| Close window/app | `Alt+F4` | close window, close app, close this |
| Minimize | `Win+Down` | minimize, minimize window |
| Maximize | `Win+Up` | maximize, maximize window |
| Show desktop | `Win+D` | show desktop, minimize everything |
| Snap left | `Win+Left` | snap left, dock left |
| Snap right | `Win+Right` | snap right, dock right |

### Editing (clipboard)
| Command | Mechanism | Triggers |
|---|---|---|
| Copy | `Ctrl+C` | copy |
| Paste | `Ctrl+V` | paste |
| Cut | `Ctrl+X` | cut |
| Select all | `Ctrl+A` | select all |
| Undo | `Ctrl+Z` | undo |
| Redo | `Ctrl+Y` | redo |

### Capture
| Command | Mechanism | Triggers |
|---|---|---|
| Screenshot | `Win+PrtSc` (saves to file) | screenshot, take a screenshot, capture screen |
| Start recording | `Win+Alt+R` (Game Bar) | start recording, record screen, screen record |
| Stop recording | `Win+Alt+R` | stop recording, stop record |

### Open (URL / app)
| Command | Mechanism | Triggers |
|---|---|---|
| Google | launch **Chrome app** | open google, open chrome, google |
| Gmail | open **2 URLs**: `mail.google.com/mail/u/0/#inbox` + `mail.google.com/mail/u/1/#inbox` | open mail, open gmail, check mail, emails |
| Claude | launch **desktop Claude app** | open claude, claude |
| YouTube | `youtube.com` | open youtube, youtube |
| LinkedIn | `linkedin.com` | open linkedin, linkedin |
| Indeed | `indeed.com` | open indeed, indeed, jobs |
| Spotify | `open.spotify.com` (web) | open spotify, spotify |
| Dashboard | whatever URL is set in `dashboard_url` (personal; ships empty) | open dashboard, dashboard |
| Open vision mode | launch `vision/` via `open_vision()` | open vision, launch vision, start vision |
| Close vision mode | `close_vision()` | close vision, stop vision, turn off vision |

**Disambiguation:** "back"/"next" are qualified in triggers ("next **track**" vs "next **tab**"; "go back" vs "previous **song**") so media and browser commands don't collide.

## 6. UI concept — tray overlay
**Stack:** PySide6/Qt (frameless, always-on-top, **no-activate**, translucency, smooth animation). No React/Chromium — a real native app (the earlier pywebview+React+Chromium stack is dropped). **Tokens are self-contained here** (copied below + in `UI-DESIGN.md`); the old app folder is gone, so do NOT reference it. Sam creates a `tokens.py` from these values:
- **Palette:** cream base `#F4ECDD / #EDE3D0 / #DCCDB0 / #FBF7EF`; brown text `#5A4632 / #8A745A / #1E1A15`; gold accent `#C9A227 / #E4C868 / #9C7A16`.
- **Fonts:** Lora (body), Cinzel (titles), Cinzel Decorative (display).
- **Look:** glassmorphism (blur ~22px, translucent cream), gold strokes/glows, soft shadows.
- **Animations:** `borderGlow` (3.6s breathing halo), `breathe` (listening), `pulse`, gold `sweep` on hover, `spin`, `reveal`; honor `prefers-reduced-motion`.

**Form:** a small "chat box"-style tray, docked **top-center**, always visible (draggable, remembers position). Collapses to logo + dot when idle; expands when active.

**Layout:**
- **Left** — TONY text logo.
- **Right** — Settings button → transforms the tray into the Settings view: the command/trigger table, plus editable tuning (`volume_step`, `scroll_amount`, `fuzzy_threshold`) and custom trigger words.
- **Center (active area)** — state: idle ("Say 'Tony'") → listening (pulsing orb + a thin **20s countdown ring** for the active window) → heard (show transcript) → executed (fixed `response` popup below, e.g. "increased volume by 10%") → no-match ("didn't catch that").

**Feedback:** every command's fixed `response` string shows in the popup (text only — no TTS).

**Global pause toggle** — one click to stop/resume listening (privacy + control for an always-on mic).

*Formal visual design (mockup + exact tokens) to be produced by the Innovations frontend agent (Iris), then folded in here.*

## 7. Vision mode integration
Use `vision/` (current). `__init__.py` already exposes `open_vision()` / `close_vision()` that launch/kill `gesture.py` as a **separate process** (camera + MediaPipe isolated from the voice loop). Router just calls these. *(It is a **mode of TONY App**, not a product of its own — the standalone gesture app it grew out of lives in a separate repo and has diverged.)*

## 8. Non-goals (YAGNI)
Chat, TTS, dictation, mouse-by-voice, memory/RAG, proactive check-ins, command history. **Dictation** (voice → type into focused field) is parked as a possible phase-2 — it is a continuous STT→keystroke stream, not a single command.

## 9. Testing
`router` self-check: assert a set of sample transcripts (including fuzzy/misheard variants and one below-threshold input) map to the expected command or to "no match". No framework.

## 10. Open items (resolved during the build)
- ~~Formal UI visual design~~ → `docs/UI-DESIGN.md` + `docs/ui-mockup.html` (Iris).
- ~~Chrome / Claude launch paths~~ → Chrome via `open_app("chrome")`; Claude via `claude_path` → `%LOCALAPPDATA%\AnthropicClaude\claude.exe` → PATH → Start-menu fallback chain.
- ~~Whisper size~~ → **`small`** (founder live-confirmed the accuracy is enough); selectable from Settings.

---

## 11. As-built delta (2026-08-07)
What the shipped code does differently from the design above. **This section is authoritative.**

**Commands: 63** (design listed ~43), in 18 groups. Added after live testing: `enter`, `open_folder`, `open_notepad`, `open_settings`, `stop_listening`, `capture_window`, the `start_recording`/`stop_recording` split, then `repeat`, `save`, `open_gallery`, `clear_field`, `search_this`, `translate_this`, `type_mode` and `research`.

**Capture behaviour changed** (§5 "Capture" is superseded):
- `screenshot` → presses the native **PrtSc** key (nothing saved by TONY).
- `capture_window` → captures the **entire monitor** the foreground window is on → `gallery/screenshots/`.
- Recording no longer uses Windows Game Bar. `start_recording`/`stop_recording` drive a **bundled ffmpeg** (`imageio-ffmpeg`, gdigrab) that records that whole monitor straight into `gallery/recordings/`.

**`close_window`** sends **WM_CLOSE** to the foreground window instead of `alt+f4` (Windows 11 Notepad swallowed the synthesized keys).

**Bare `back` / `forward`** are real triggers; the router uses `fuzz.ratio` for single-token transcripts and `WRatio` for multi-word ones, so a bare "stop"/"close"/"next" can't greedily match a longer trigger. `fuzzy_threshold` calibrated to **86**.

**One-shot wake phrase:** "Tony, volume up" executes immediately using the wake listener's trailing text — no need to wait for the window.

**No pause control.** The design's §6 pause toggle and the `paused` state were removed at the founder's request (`stop_listening` covers stopping; pausing killed the mic so the wake word couldn't revive it).

**The UI is far smaller than §6 describes** — after live-testing, the founder stripped it to essentials (2026-08-05). §6's expanded tray, countdown ring, transcript, state label, status dot and **the whole Settings panel are gone**, and with the panel went the click-to-run "button UI" the original spec asked for (config is still editable in `config/settings.json`). What remains: a **95×40 glass pill holding only the gold TONY wordmark**, which **glows at the border while listening and sits perfectly still when idle** (the inverse of the original design), plus a transient popup below it carrying the command's response — gold tick for a result, muted clay for "didn't catch that" / a failed action. Deleted with it: `ui/ring.py`, `ui/settings_view.py`, `win_native.ForegroundTracker` and `drop_no_activate` (both existed only to serve the panel's focus needs).

**The active window is 20s** — briefly raised to 60s, then put back after live use.

**One shared loop.** `session.py::run_session()` is the single implementation of the wake → active-window → STT → route → run loop; `main.py` (console) and `ui/voice_worker.py` (tray) only supply a `report()` callback. They previously each had a copy and the copies drifted.

**Dead code from the earlier build deleted:** the LLM brain, TTS, barge-in, `hwfit`, chat memory, the Ollama tool-schema registry, and `actions/system.py` (which carried an arbitrary `run_shell`) are gone — none were reachable any more, and the repo is public.

**Personal config is not committed:** `dashboard_url` ships empty; real values live in the gitignored `config/settings.json`.

**Testing** (§9 badly understated it): **96 tests** across router matching, the control
layer, the voice loop with fake ears and fake STT, VISION's geometry and gesture logic,
an AST guard over `main()`'s signal wiring, and an **offscreen Qt paint pass** over every
UI state — the last one exists because a paint-time crash otherwise only shows up on the
founder's screen. Two of them are structural and have each already caught a real bug:
`test_no_trigger_can_be_erased_by_its_own_router` (a trigger the router's own
normalisation eats can never be said out loud) and the geometry assertion in
`test_ui_smoke.py` (no animation may move or resize a window — see §12).

**VISION is not a separate window; it is the pill.** §7 is superseded. "Open vision"
grows the pill into a rounded panel with the camera under the wordmark, and it shrinks
back when vision mode stops. The controller still runs as its **own process** — the camera
and MediaPipe must never share a thread with the voice loop — but instead of calling
`cv2.imshow` it writes finished frames into **shared memory** (`vision/frames.py`), and
a GUI-thread timer in the pill paints them. Nothing signals the pill from the worker
thread. While vision mode is up the pill is draggable (handed to Windows via
`WM_NCLBUTTONDOWN`, so Qt never moves it) and clicking the logo lists **gestures**
instead of commands. Ten gestures: index = pointer, peace = click, OK held 1s =
Alt+Tab, open-palm swipe = back/forward, fist held 1s = sleep/wake (read even while
asleep), plus two faders — left is volume, right is scroll and its speed follows how
fast your hand moves.

**A hardware strip** (CPU / RAM / VRAM) sits under the command list, refreshed by an
async `nvidia-smi` through `QProcess` so the GUI thread never blocks on it.

**Type mode** turns speech into keystrokes in the focused field. It has **three** exits
— a spoken phrase, the hotkey, and 5 seconds of silence — because a dictation mode that
outlives you leaving the desk types the next conversation into whatever has focus.

## 12. The one rule the UI cannot break

Every visible surface is a translucent, always-on-top `Qt.Tool` window, which on Windows
is a layered window: **moving or resizing one is synchronous Win32 work on the GUI
thread**, and doing it per animation frame wedges the whole app — alive, unresponsive,
no traceback. So: **repaint per frame, never re-geometry.** The popup slides its glass
inside a taller stationary window; the pill "grows" into the vision mode panel by taking its
final size before the first frame and animating only the painted glass box. Two related
bans follow from the same reasoning: no `QGraphicsOpacityEffect` / `QGraphicsDropShadowEffect`
(their offscreen composite is where the black rectangle came from — three times), and no
worker-thread signal may land on a bare lambda (a lambda has no receiver object, so Qt
runs it in the emitting thread, which put widget construction on the voice thread).
