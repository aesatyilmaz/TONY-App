# TONY App — UI Visual Design

> By Iris (Frontend Engineer, AEYS Innovations). Date: 2026-08-04.
> Companion to `SPEC.md` §6. Visual reference: `ui-mockup.html`.
> Design tokens live **here** (§7) — this doc is their source of truth. (They came
> originally from the earlier web UI's `styles.css`, which no longer exists; the values
> are embedded below so this doc stands alone.)
> Target implementation: PySide6/Qt (this doc specs the design; Sam writes the Qt).

---

## 0. North star
One small glass tray, docked top-center, always visible, never steals focus. Vintage
gold-on-cream. It has exactly two footprints — a **collapsed pill** (idle) and an
**expanded tray** (active) — plus one full-panel **Settings** mode. No chrome, no
title bar, no chat. Minimal by mandate. Tokens are self-contained in this doc (§7).

---

## 1. Geometry & footprints

All dims in logical px (Qt device-independent). Dock: horizontally centered, `top = 16px`
from screen top by default; draggable; last position persisted to `config`.

| Footprint | Width | Height | Radius | When |
|---|---|---|---|---|
| **Collapsed pill** | 196 | 46 | 999 (full) | Idle / Paused |
| **Expanded tray** | 480 | 68 | 22 (`--r-lg`) | Listening / Heard / Executed / No-match |
| **Settings panel** | 480 | auto, max 472 | 22 | Settings open |

Collapse/expand is a width+height tween (see §5). The window itself is `WA_TranslucentBackground`,
frameless, always-on-top, **no-activate** (§7). All three footprints share one glass surface:

```
background: rgba(251,247,239,0.72)     /* translucent --white */
border:     1px solid rgba(201,162,39,0.55)   /* --stroke-gold */
box-shadow: --shadow-lg + inset top highlight
```

Internal padding: pill `0 16px`; tray `0 16px`; settings `14px 16px 16px`.

---

## 2. The three zones (expanded tray)

Grid: `auto | 1px divider | 1fr center | auto controls`, gap 14px, vertically centered.

- **Left — logo.** `TONY`, `--display` (Cinzel Decorative) 700, 17px, letter-spacing .14em,
  gold gradient fill (`--gold-lite → --gold-deep`) with a 1px white text-shadow for the
  engraved look. Never truncates.
- **Divider.** 1px, 34px tall, vertical gold gradient fading at both ends.
- **Center — live state area.** The only zone that changes per state (§4). Holds the orb+ring
  and/or transcript. `min-width:0` so long transcripts ellipsize instead of pushing the controls.
- **Right — controls.** Two 30px icon buttons: **Pause** then **Settings (gear)**. Border
  `--stroke-gold`, translucent cream fill; hover → `--stroke-gold-strong` + `--glow-gold`.

In the collapsed pill the zones reduce to: **logo · dim hint · status dot** (no divider, no controls).
Controls reappear on expand.

---

## 3. Status dot (collapsed pill)

9px circle at the pill's right edge — the at-a-glance state when collapsed.

| State | Fill | Treatment |
|---|---|---|
| Idle | `--brown-soft` | soft 3px halo, static |
| Live (wake fired but pill still shown briefly) | `--gold` | gold halo + `pulse` 1.4s |
| Paused | warm clay `#a86a52` | static, no halo |

---

## 4. States (center area)

Five visual states. Each names its animation and its exact center content.

### 4.1 Idle  *(collapsed pill)*
Dim. Content: logo · right-aligned italic hint `Say "Tony"` in `--brown-soft` 12.5px · idle dot.
Whole pill breathes with **`borderGlow`** (3.6s) — the same gentle gold halo the old chatbox wore.
This is the resting, always-on presence.

### 4.2 Listening  *(expanded)* — the 20s active window
Center = **orb + countdown ring** + `Listening` state-label (`--title` 10.5px, tracked, `--brown-soft`).
- **Orb:** 20px radial-gold sphere (`--gold-lite → --gold-deep`), soft gold glow, **`breathe`** 1.4s
  (scale 1 → 1.14). This is the "I'm hearing you" heartbeat.
- **Countdown ring:** 40px, 2.5px stroke, `--gold` over a faint `rgba(201,162,39,.16)` track,
  round cap, `-90°` start (12 o'clock), drains clockwise over **20s** (`stroke-dashoffset 0 → 106.8`,
  circumference of r=17). **Rolling:** every executed command resets it to full. When it empties,
  the tray collapses back to idle and the wake word is required again. This is the one bespoke
  visual nothing before it had — it makes the invisible active-window timer legible.

### 4.3 Heard  *(expanded)*
The ring keeps draining. Center swaps the state-label for the **transcript**: `--serif` italic 15px,
`--black`, in curly quotes, e.g. *"turn it up"*. Ellipsizes if long. Orb keeps breathing.

### 4.4 Executed  *(expanded + popup)*
Transcript stays; a **feedback popup** drops in ~12px below the tray, centered, with a small
caret pointing up at the command. Glass chip, `--stroke-gold`, `--shadow-md`, 12.5px `--brown`,
gold `✓`, and the command's fixed `response` string (e.g. `increased volume by 10%`,
`copied`, `opened Chrome`). **Text only, no TTS.** Enters with **`reveal`** (0.28s), auto-dismisses
after ~2.2s (fades). The ring resets to full on execution (rolling window).

### 4.5 No match  *(expanded + popup)*
Below-threshold input: nothing fires. Transcript shows muted (`--brown-soft`), and a **muted popup**
`didn't catch that` in clay `#a05a3c` with a clay border. Same `reveal` + auto-dismiss. No `✓`.

### 4.6 Paused  *(collapsed pill)*
Global mic off. `borderGlow` stops (halo frozen), dot goes clay, hint reads `Paused`. One click on
the Pause control resumes → back to Idle.

---

## 5. Motion & transitions

| Moment | Motion |
|---|---|
| Idle resting | `borderGlow` 3.6s breathing halo (one element, cheap) |
| Wake → expand | width 196→480 + height 46→68, 220ms ease-out; contents cross-fade in |
| Listening | orb `breathe` 1.4s + ring 20s linear drain |
| Command executed | ring snaps back to full (150ms), popup `reveal` in |
| Popup out | fade 200ms after ~2.2s hold |
| Collapse (window closes) | reverse of expand, 200ms |
| Hover on any control/row | border strengthens + `--glow-gold`; gold `sweep` optional on settings Save |
| Settings open/close | height tween to panel; command table cross-fades in |

**`prefers-reduced-motion`:** kill all keyframes (halo, breathe, ring drain animation, reveal).
Ring still shows remaining time as a *static* arc updated in discrete steps; orb stays a solid
sphere. Honor the OS setting — expose a "reduce motion" toggle in Settings as a manual override.

---

## 6. Settings view

Tray transforms in place (same width, grows down). Contents top-to-bottom:

1. **Header** — back arrow (`←`, returns to compact tray) · `SETTINGS` (`--title` 700, tracked,
   uppercase) · small `TONY` logo right.
2. **Tuning row** — 3 fields in a grid: `volume_step`, `scroll_amount`, `fuzzy_threshold`. Label
   `--brown-soft` 11px, input on `--white` with `--stroke-gold`, focus → strong stroke + glow.
   *(These are the calibration knobs from spec §2.2 — real volume/scroll steps vary by hardware.)*
3. **Section label** — `Commands & trigger words` with a hairline rule.
4. **Command table** — scrollable (max 220px), `--stroke-gold` rounded container. Each **row**:
   `command name` (`--title` 13px) | wrapped **trigger chips** (cream pills, `--stroke-gold`) +
   a dashed **`+ add`** chip to append a custom trigger word. Rows come straight from
   `commands.py` (spec §5).
   - **Rows double as the button UI** (spec §6 "a button UI that fires the same actions"):
     clicking a row *runs* that command now. Footnote reads *"click a command to run it now."*
     This satisfies the button-UI requirement without adding a separate command grid (see §8).
5. **Footer** — the click-to-run note (left) + gold **Save** button (right).

---

## 7. Token & animation → Qt map (for Sam)

Design side is CSS/tokens; here's the high-level Qt translation. **You write the Qt, not me.**

### 7.0 Design tokens (canonical — the source of truth; the old web UI is gone)

```
/* Cream base */   --cream #F4ECDD  --cream-2 #EDE3D0  --beige #DCCDB0  --white #FBF7EF
/* Brown text */   --brown #5A4632  --brown-soft #8A745A  --black #1E1A15
/* Gold accent */  --gold #C9A227  --gold-lite #E4C868  --gold-deep #9C7A16

/* Glass surface */ background rgba(251,247,239,0.72); + inset top highlight rgba(255,255,255,0.5)
/* Strokes */      --stroke-gold 1px rgba(201,162,39,0.55)  --stroke-gold-strong 1.5px rgba(201,162,39,0.9)
/* Glow */         --glow-gold  0 0 0 3px rgba(201,162,39,0.15), 0 0 14px rgba(201,162,39,0.35)
/* Shadows */      --shadow-md 0 6px 20px rgba(90,70,50,0.14)   --shadow-lg 0 16px 44px rgba(60,45,30,0.18)
/* Radii */        --r-sm 8  --r-md 14  --r-lg 22  --r-full 999
/* Spacing */      4 · 8 · 12 · 16 · 24 · 32 px
/* Fonts */        body Lora · titles Cinzel · display Cinzel Decorative
```


| Design token / effect | Qt equivalent |
|---|---|
| color tokens (below) | one `tokens.py` dict / `QColor` constants; feed into `.setStyleSheet()` QSS |
| `--stroke-gold`, radii, spacing | QSS `border`, `border-radius`, layout margins/spacing |
| Glass surface (translucent cream) | `WA_TranslucentBackground` window + a rounded `QWidget.paintEvent` filling `rgba(251,247,239,0.72)` |
| **`backdrop-filter: blur(22px)`** | **No native Qt equivalent — see §8.1.** Ship translucent-cream fill (looks ~90% there); real backdrop blur is optional/expensive |
| `--shadow-lg` / soft shadows | `QGraphicsDropShadowEffect` (blur + offset + `QColor` alpha), since frameless has no native shadow |
| `borderGlow` (3.6s) | `QPropertyAnimation` on the drop-shadow's `blurRadius`/`color`, `InOutSine`, loop |
| `breathe` (orb scale) | `QPropertyAnimation` on a custom `scale` prop → `QTransform` in `paintEvent`, or geometry tween |
| `pulse` (dot) | same, on shadow blur radius |
| **Countdown ring** | custom `QWidget.paintEvent`: `QPainter.drawArc`, span angle bound to a `progress` float (1→0) driven by a `QVariantAnimation`/`QTimer` (~30fps) over 20s; `resetTimer()` on each execute |
| `reveal` (popup) | popup = separate no-activate `QWidget`; fade+translate via `QPropertyAnimation` on `windowOpacity`+pos; `QTimer.singleShot(2200, hide)` |
| `sweep` hover | optional; `QPropertyAnimation` on a gradient offset, or skip — hover border+glow is enough |
| `prefers-reduced-motion` | check OS (or Settings toggle) → don't start the loop animations; paint static states |
| Fonts (Lora/Cinzel/Cinzel Decorative) | bundle TTFs, `QFontDatabase.addApplicationFont` at startup (don't rely on network) |
| expand/collapse | `QPropertyAnimation` on window `geometry` (or a fixed inner `QStackedWidget` swap) |

---

## 8. Honest flags — where the concept fights a no-activate frameless Qt overlay

These are real, called out per the brief. None are blockers; each has a chosen resolution.

### 8.1 Live glassmorphism blur is not native to Qt
`backdrop-filter` doesn't exist in Qt/QSS. True backdrop blur means grabbing the screen region
behind the window and blurring it every frame — expensive, and it flickers while dragging.
**Resolution:** ship the **translucent cream fill** (0.72 alpha `--white`) + inset highlight +
gold stroke. Over most apps this reads as frosted glass at ~90% of the effect for ~0% of the cost.
If Esat Bey wants literal blur later, do a one-shot grab-and-blur on show (not per-frame). Ponytail:
translucent fill now, real blur only if it visibly falls short.

### 8.2 **Typing in Settings vs. `WS_EX_NOACTIVATE`** — the load-bearing one
A no-activate window **never takes keyboard focus** — by design, so voice hotkeys land on the
user's real app (spec §2.1). But the Settings view has **text inputs** (tuning fields, custom
trigger words). You cannot type into a field in a window that can't be focused.
**Resolution:** treat Settings as a **modal exception** — when Settings opens, temporarily
**drop `WS_EX_NOACTIVATE`** (allow the window to activate) so inputs are editable; on Back/Save,
**restore `WS_EX_NOACTIVATE`** and return to the compact tray. This is safe because while editing
Settings the user isn't issuing voice commands at another app anyway. Flag for Sam: the flag
swap must be re-applied on the native `HWND` (via `SetWindowLongPtr`), not just at construction.

### 8.3 Button-clicks steal focus (already anticipated in spec §2.1)
Clicking a **command row** (button UI) does focus TONY, so the hotkey would land on TONY, not the
user's app. Spec §2.1 already solves this: remember the last non-TONY foreground window and
`SetForegroundWindow` back to it *before* sending the hotkey. Pause/Settings/Save buttons don't
send hotkeys, so they're exempt. Design-side nothing changes — just don't add command buttons
that fire without that focus-restore path.

### 8.4 Frameless rounded window shadow & drag
Frameless + translucent = no OS shadow and no OS title-bar drag.

**Both of this section's original answers were wrong, and the build proved it — do not
put them back:**

- ~~`QGraphicsDropShadowEffect`~~. A graphics effect renders the widget through an
  offscreen surface and composites it back, and on a translucent always-on-top window
  that composite is where a black rectangle appears — it happened three times, on three
  unrelated triggers, always on a widget wearing an effect. **Shadows are painted by
  hand** in the widget's own `paintEvent`; fades are `QPainter.setOpacity`.
- ~~`mousePressEvent`/`mouseMoveEvent` moving the window~~. These are layered windows;
  moving one is synchronous Win32 work on the GUI thread. Drag is handed to Windows
  (`WM_NCLBUTTONDOWN` with `HTCAPTION`) so the OS runs its own move loop and Qt never
  touches geometry. See `SPEC.md` §12 — the rule is *repaint per frame, never
  re-geometry*, and it governs every animation in the app.

### 8.5 Countdown ring smoothness
20s at 30fps is 600 repaints of a tiny widget — negligible. But if the machine is under load and
TONY must stay light (spec §1), a `QTimer` at ~20fps or a `QVariantAnimation` is plenty; don't
over-sample. Ponytail: 20fps arc, bump only if it looks choppy.

---

## 9. What I deliberately did not add (YAGNI)
- No separate command-button **grid** — Settings rows are the button UI (§6). Add a dedicated grid
  only if voice-first usage proves users want one-tap tiles.
- No theming/dark mode — the vintage cream *is* the brand.
- No settings for dock side/anchor — top-center is the concept; drag covers the rest.
- No animated waveform in the orb — the breathe+ring already read as "listening" and cost less.

---

*Visual reference lives in `ui-mockup.html` (open in a browser). It is a static reference,
not production code — Sam implements against this doc in PySide6.*
