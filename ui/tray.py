"""TonyTray — the frameless, no-activate glass pill, and vision mode's home.

Logo only, normally: a small stadium of cream glass holding the gold TONY wordmark.
Its border glows gold while TONY is active and sits perfectly still while idle; a
transient popup drops below it to report what a command did.

## Vision mode

Saying "open vision" does not open a window. The pill itself grows into a rounded
panel with the camera picture under the wordmark, and shrinks back to a pill when
vision mode ends. One object in two shapes, never two objects — which is what
"integrate vision mode into TONY" actually means.

Three things follow from that and are easy to get wrong:

* **The pill can be dragged in this mode, and only this mode.** At pill size it is
  a docked ornament; at panel size it covers whatever the founder is gesturing at,
  so it has to be movable. The drag is handed to Windows (win_native.start_native_drag)
  rather than done with move(): re-positioning a layered topmost window per mouse
  event is the same class of call that wedged the GUI thread once already.
* **"Where is the pill" stops being a calculation.** See pill_rect().
* **Clicking the logo shows the gestures, not the voice commands.** In Vision mode
  the voice list is the wrong reference card.

Nothing tells the pill that vision mode started. It watches the shared frame buffer on
its own timer — because the command that starts vision mode runs on the worker thread,
and a worker thread that touches a widget is exactly what froze TONY for four
rounds (see app._GuiBridge).
"""
from __future__ import annotations

import time

from PySide6.QtCore import (
    Qt, QTimer, QVariantAnimation, QEasingCurve, QRect, QRectF, QPoint,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

from ui import tokens, win_native
from ui.frame_view import FrameView
from ui.glyphs import GlassSurface, Wordmark, Tick, CARET, MARGIN
from config import settings
from vision import frames

_LOGO = 22            # wordmark cap height
_PAD = (20, 9)        # x/y padding around it. x == the stadium's end radius (h/2), so
                      # the letterforms start exactly where the cap curve stops eating space.
_PILL = (95, 40)      # = Wordmark(_LOGO).width() + 2*_PAD[0]  ×  _LOGO + 2*_PAD[1]
_POPUP_MS = 2200
_TOP_GAP = 40         # screen top → pill (founder wants it sitting a little lower)
DROP = 8              # pill bottom → whatever hangs off it (popup caret, panel caret)

# Popup motion (founder: "bir anda ekrana çıkıyor ve bir anda gidiyor").
# _POP_TRAVEL is DROP + 2: at zero opacity the caret tip sits 2px INSIDE the pill, so
# the popup is never a thing that materialises in place — it comes out from under the
# pill and goes back into it. Out is slower than in, same reasoning as the pill's fade.
# The swap leg is the retract half of a back-to-back message: it has to be quick,
# because the founder is already waiting on the next line.
#
# THE TRAVEL HAPPENS INSIDE A WINDOW THAT NEVER MOVES. The first cut animated the
# popup's own position, i.e. a SetWindowPos per frame on a WS_EX_LAYERED topmost
# tool window — ~60 full layered recomposites a second, each one a synchronous
# Win32 geometry change on the GUI thread. That wedged the GUI thread on the
# founder's machine (process alive, Responding=False, no Python traceback, worker
# thread still logging). The pill's breathing glow has animated for days without
# trouble because it only ever repaints. So: repaint per frame, never re-geometry.
_POP_TRAVEL = DROP + 2
_POP_IN_MS, _POP_OUT_MS, _POP_SWAP_MS = 260, 300, 130

# Idle vs listening is the ONE state the founder has to read from across the room,
# and a breathing glow alone failed at it: a slow bloom in an already-warm colour is
# invisible to peripheral vision, which catches luminance/contrast STEPS, not motion.
# So the two states are two different objects — asleep and lit — on three axes at once:
#   ring   quiet 1px gold hairline → bright 2.6px gold ring
#   mark   washed out (34%)        → full gold gradient + engraved lift
#   glass  thinner, flatter        → solid, with the breathing gold glow
# (Ring weight grows inward — see GlassSurface.set_tone — so the gutter is untouched.)
#
# Idle is ASLEEP, not ABSENT (founder: "pasifken de altın border olsun, ince").
# The old (201,162,39,55) hairline was a smudge — at 1px, 22% of a LIGHT gold over a
# near-white fill is indistinguishable from the edge of the cream. So idle uses the
# DEEP gold at 69%: same 1px weight, but dark enough against the fill to read as a
# deliberate outline. The fade then lifts deep gold → bright gold, which reads as the
# pill warming up rather than merely brightening.
_IDLE_FILL = (251, 247, 239, 216); _IDLE_RING = (156, 122, 22, 175); _IDLE_W = 1.0
_LIVE_FILL = (251, 247, 239, 250); _LIVE_RING = (201, 162, 39, 255); _LIVE_W = 2.6
_IDLE_SHADOW = (60, 45, 30, 45)                  # a flat, low lift: recessive
_LIVE_SHADOW = (201, 162, 39, 120)               # gold bloom
_IDLE_DY, _LIVE_DY = 3.0, 2.0                    # shadow offset
_IDLE_REACH, _LIVE_REACH = 9.0, 13.0             # SETTLED reach; the breath adds on top
_BREATH_PEAK = MARGIN - _LIVE_DY - 1             # the whole gutter, at the top of the breath

# The breath is the ONE thing that runs continuously the whole time TONY is
# listening, and every frame of it is a full repaint of a WA_TranslucentBackground
# topmost window — i.e. a Win32 layered recomposite, plus up to 21 strokePath() calls
# because GlassSurface paints its glow one 2px ring per pixel of reach. Qt's
# animation driver ticks at ~60Hz and QVariantAnimation cannot be told otherwise, so
# the breath is a plain QTimer instead: a triangle wave over _BREATH_MS, stepped at
# _BREATH_FPS. 25 is not a guess about smoothness — the glow's reach travels
# _LIVE_REACH→_BREATH_PEAK, about 8px, over 1.2s. That is ~7px/s, i.e. a quarter of a
# pixel per frame at 25Hz; there is no visible step to lose and 60% of the composites
# go away. The glow itself is untouched (founder likes it) — only how often it is
# recomputed. Drop it further if the freeze survives this; raise it if he sees steps.
_BREATH_MS = 2400
_BREATH_FPS = 25

# Fade feel. Asymmetric on purpose: waking has to answer the wake word, so it starts
# at full speed (OutCubic) and is over in ~1/3 s; dropping out happens constantly as
# TONY leaves the active window, so it drifts away slower and starts soft (InOutSine)
# — an exit that snaps reads like a glitch, an exit that eases reads like it chose to.
_FADE_IN_MS, _FADE_OUT_MS = 320, 420
# The transparent gutter every glass surface carries around its glass, so its
# hand-painted shadow lands inside the window instead of past it. See glyphs.
_MARGIN = MARGIN
_WIN = (_PILL[0] + 2 * _MARGIN, _PILL[1] + 2 * _MARGIN)   # the pill's window/surface

# ── Vision mode ───────────────────────────────────────────────────────────────
# 400x300, not the camera's native 640x480: at panel size this thing sits on top of
# whatever is being gestured at, and a quarter of the screen is too much rent for a
# preview of your own hand.
_VIEW = (400, 300)
_V_PAD = 12           # glass edge → contents
_V_GAP = 9            # wordmark → picture
_V_RADIUS = 18        # a stadium at pill size, a rounded rect once it holds a picture
_VISION_GLASS = (_VIEW[0] + 2 * _V_PAD, _V_PAD + _LOGO + _V_GAP + _VIEW[1] + _V_PAD)
_VISION_WIN = (_VISION_GLASS[0] + 2 * _MARGIN, _VISION_GLASS[1] + 2 * _MARGIN)
# The pill does not snap between the two shapes: it opens, and it closes. Both are
# PURE REPAINT inside a window that is already at its final size — see
# GlassSurface.set_glass_box. One number drives it, mapped to two phases so the
# picture only ever fades inside a glass that has finished growing:
#   0 .. _REVEAL_SPLIT   the glass grows out of the pill, downward and outward
#   _REVEAL_SPLIT .. 1   the camera picture fades up inside it
# Out is quicker than in, the same reasoning the popup's legs use.
_REVEAL_SPLIT = 0.62
_OPEN_MS, _CLOSE_MS = 320, 260
_FRAME_MS = 33        # ~30fps, the rate frames actually arrive at
_LOOK_EVERY = 30      # while vision mode is not running, only look for it once a second
_STALE_S = 1.5        # frames stopped this long ago = vision mode died rather than quit
_DRAG_SLOP = 4        # px before a press on the glass counts as a drag, not a click


def _mix(a, b, t: float):
    """Componentwise lerp of two RGBA tuples."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


_live_tray = None      # the one TonyTray; set in its __init__ (there is only ever one)


def dock_rect() -> QRect:
    """Where the pill parks: top-centre of the primary screen, at its pill size."""
    s = QGuiApplication.primaryScreen().availableGeometry()
    return QRect(s.center().x() - _PILL[0] // 2, s.top() + _TOP_GAP, *_PILL)


def pill_rect() -> QRect:
    """Where the pill ACTUALLY is, right now.

    It used to be computed from the screen, which was true while the pill was a
    fixed-size thing bolted to the top edge. It is neither any more: carrying the
    vision-mode picture it grows, and in that mode the founder can drag it wherever he
    wants. Anything anchoring to a computed dock would then open where the pill
    used to be. So this asks the pill, and only falls back to the dock before one
    exists (which is what the offscreen tests construct)."""
    return _live_tray._visible_rect() if _live_tray is not None else dock_rect()


def vision_mode() -> bool:
    """True while the pill is carrying vision mode's picture — which is what decides
    whether clicking the logo shows gestures or voice commands."""
    return _live_tray is not None and _live_tray.vision


class _Popup(QWidget):
    """Feedback popup — a separate no-activate top-level widget so it can float
    below the pill without growing the pill's own footprint.

    Its motion is one scalar, exactly like the pill's fade: _render(opacity) is THE
    render function and the vertical offset is a pure function of that opacity, so a
    fully faded popup is always fully tucked into the pill and the fade and the travel
    can never disagree. Everything else is which target _render is driven towards:
      in    0→1  OutCubic, 260ms — it drops out of the pill
      hold       2200ms
      out   1→0  InOutSine, 300ms — it retracts back into the pill and is hidden
      swap  1→0→1        130ms out, then straight back in with the new line

    The WINDOW is placed exactly once per message and never touched again: it is
    _POP_TRAVEL taller than the surface, and the surface carries its own shadow
    gutter, so both extremes of the travel fit inside it. What moves is the surface
    within it, which is a non-native child: a dirty-region repaint, not a Win32
    geometry call. That is the whole difference between this and the version that
    froze the GUI thread. (The outer widget deliberately has NO layout: a layout
    would re-place the surface on the next activation and fight the travel.)
    """

    def __init__(self, reduce_motion: bool):
        super().__init__()
        self._reduce_motion = reduce_motion
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(tokens.qss())

        # The glass surface: its own _MARGIN gutter round the glass for the shadow,
        # and free to slide _POP_TRAVEL down inside the (taller) window. Placed by
        # hand (see the class docstring): no outer layout.
        self._surface = GlassSurface(radius=14, caret=True, parent=self)
        self._surface.set_shadow((90, 70, 50, 70), dy=6, reach=17)

        lay = QHBoxLayout(self._surface)
        lay.setContentsMargins(15 + _MARGIN, 8 + CARET + _MARGIN, 15 + _MARGIN, 8 + _MARGIN)
        lay.setSpacing(8)
        self._tick = Tick()
        self._text = QLabel("")
        self._text.setFont(tokens.font("body", 12.5))
        lay.addWidget(self._tick); lay.addWidget(self._text)

        self._opacity = 0.0
        self._pending = None        # a message that arrived while one was on screen
        self._sticky = False        # a MODE banner: no hold timer, dismissed explicitly
        self._hide_timer = QTimer(self); self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._dismiss)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(lambda v: self._render(float(v)))
        self._anim.finished.connect(self._arrived)

    def showEvent(self, e):
        super().showEvent(e)
        try:
            win_native.set_no_activate(win_native.own_hwnd(self))
        except Exception:
            pass  # offscreen/no real HWND in the smoke test — real runtime behavior unaffected

    def hideEvent(self, e):
        """Leave nothing behind. A layered window whose last composite failed keeps
        that frame on screen; stop anything still animating and force one clean,
        fully-transparent update so a stale popup cannot burn in. Hiding is always
        immediate — the animated exit is _dismiss(); this is the pill taking the
        popup with it, and a popup easing out under a pill that is already gone
        would be an orphan."""
        self._pending = None
        self._anim.stop(); self._hide_timer.stop()
        self._opacity = 0.0
        self.setWindowOpacity(0.0)
        self.update()
        super().hideEvent(e)

    # ------------------------------------------------------------ motion --
    def _render(self, o: float) -> None:
        """THE render function: opacity in, and the glass's offset derived from it.
        Every frame is a REPAINT — the window's geometry is set once per message and
        is identical at every point of both animations. Moving the top-level per frame
        is what froze the GUI thread; a child widget is not a native window, so its
        offset costs a dirty region, not a SetWindowPos + layered recomposite.

        The surface keeps its size and its shadow keeps its reach, and it carries its
        gutter with it, so the invariant (nothing painted outside the window) holds
        at every offset in the range rather than only at rest — the window is exactly
        _POP_TRAVEL taller than the surface.

        The offset trails the opacity (o³) instead of tracking it. Straight
        proportional travel put the whole slide inside the first quarter of the
        entrance, where the popup is still too faint to see it move — it went back to
        reading as a flicker. Cubed, ~80% of the travel is still to come at half
        opacity, so the motion happens where the eye actually is. The endpoints are
        untouched: fully faded is still fully tucked into the pill."""
        self._opacity = o = min(1.0, max(0.0, o))
        self.setWindowOpacity(o)
        self._surface.move(0, round(_POP_TRAVEL * o ** 3))

    def _animate(self, target: float, ms: int, curve) -> None:
        """Duration scales with the distance left, so a motion interrupted half-way
        runs at the same SPEED as a full one — same rule as the pill's fade."""
        # Read where we ARE before touching the animation, exactly as _set_glow does:
        # re-configuring a stopped QVariantAnimation re-evaluates it at its stale
        # currentTime, and setEndValue() emits that straight into _render. Reading
        # self._opacity afterwards gives the value we are about to animate TO, so
        # every leg after the first computed distance ~0 and ran at the 60ms floor —
        # a 260ms entrance that actually took 60. start() re-emits the real t=0 value.
        cur = self._opacity
        self._anim.stop()
        self._anim.setStartValue(cur)
        self._anim.setEndValue(target)
        self._anim.setDuration(max(60, round(ms * abs(target - cur))))
        self._anim.setEasingCurve(curve)
        self._anim.start()

    def _arrived(self) -> None:
        """End of a motion. Only the way OUT has anything left to do: either the next
        message is already waiting and comes straight back out of the pill, or the
        popup is done and the window goes away."""
        if self._anim.endValue() != 0.0:
            return
        pending, self._pending = self._pending, None
        if pending:
            self._apply(*pending)
            self._enter()
        else:
            self.hide()

    def _dismiss(self) -> None:
        """The hold expired: retract into the pill instead of blinking out."""
        if self._reduce_motion:
            self.hide()
            return
        self._animate(0.0, _POP_OUT_MS, QEasingCurve.InOutSine)

    def _enter(self) -> None:
        self._render(0.0)
        self.show()
        self._animate(1.0, _POP_IN_MS, QEasingCurve.OutCubic)
        if not self._sticky:
            self._hide_timer.start(_POPUP_MS)

    def _apply(self, text: str, ok: bool, anchor: QRect) -> None:
        """Content and geometry for ONE message — the ONLY place the window is sized
        or moved. It happens once, while the popup is fully faded out, and holds for
        the whole life of the message; _render then owns nothing but paint."""
        self._tick.setVisible(ok)
        self._text.setText(text)
        self._text.setStyleSheet(f"color: {tokens.BROWN if ok else tokens.CLAY};")
        self._surface.set_tone(tokens.POPUP_RGBA,
                              (201, 162, 39, 140) if ok else (160, 90, 60, 130))
        # activate() first: sizeHint() would otherwise be the layout's PREVIOUS hint,
        # so every popup came out the width of the message before it (one-call lag).
        self._surface.layout().activate()
        self._surface.resize(self._surface.sizeHint())
        # The window contains the surface (glass + its gutter) AND the travel: the
        # surface sits at y=0 fully tucked and at y=_POP_TRAVEL at rest, so nothing
        # it paints leaves the window at either end — or anywhere in between.
        self.resize(self._surface.width(), self._surface.height() + _POP_TRAVEL)
        # ...so the window sits _POP_TRAVEL higher than the glass's resting place,
        # which is DROP under the pill with the caret tip on the pill's edge.
        self.move(anchor.center().x() - self.width() // 2,
                  anchor.bottom() + DROP - _MARGIN - _POP_TRAVEL)
        self._render(self._opacity)   # re-place the glass inside the new window

    def show_message(self, text: str, ok: bool, anchor: QRect,
                     sticky: bool = False) -> None:
        """ok=True → gold tick + brown text. ok=False → no tick, clay text and a
        clay hairline, so a failure reads muted instead of celebratory.

        `sticky` keeps it up until something dismisses it. That is for a MODE, not a
        message: while dictation is on, every word goes into whatever has focus, and
        a two-second notice that TONY is now typing is a notice you will miss."""
        self._sticky = sticky
        if self._reduce_motion:
            self._apply(text, ok, anchor)
            self._render(1.0); self.show()
            if not sticky:
                self._hide_timer.start(_POPUP_MS)
            return
        if self.isVisible():
            # Back-to-back commands — he fires several inside one listening window.
            # The popup ducks back into the pill and comes out again with the new
            # line. Swapping the text in place would report a second "increased
            # volume by 10%" by changing nothing on screen, and resizing under a
            # fully-lit popup is the snap he is complaining about.
            self._pending = (text, ok, anchor)
            self._hide_timer.stop()
            self._animate(0.0, _POP_SWAP_MS, QEasingCurve.InOutSine)
            return
        self._apply(text, ok, anchor)
        self._enter()


class TonyTray(QWidget):
    def __init__(self, on_open_info=None):
        """on_open_info: called on a left click on the glass. At pill size that is
        every click, because a docked pill cannot be dragged; in Vision mode a click
        is only a click if the mouse did not move (see mouseMoveEvent)."""
        super().__init__()
        global _live_tray
        _live_tray = self               # pill_rect() asks the real pill where it is
        self._on_open_info = on_open_info
        self.vision = False             # read by InfoWindow to pick its content
        self._reader = None
        self._looks = 0
        self._last_frame_at = 0.0
        self._press_at = None
        self._reveal_t = 0.0
        self._cfg = settings.load()
        self._reduce_motion = bool(self._cfg.get("reduce_motion", False))

        tokens.load_fonts()  # bundled TTFs if ui/fonts/ exists; never a network fetch
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(tokens.qss())

        # The glass surface fills the window: it carries its own _MARGIN gutter for
        # the glow, so the window is the glass plus that gutter and nothing else.
        # No outer layout — the surface is fixed-size at (0,0), which a layout would
        # only re-assert.
        self._surface = GlassSurface(radius=999, parent=self)

        # One layout for both shapes: wordmark on top, picture under it. At pill size
        # the picture is hidden and the column collapses to the wordmark, which is
        # exactly the pill. Swapping layouts at runtime would be the other way to do
        # this, and a strictly worse one.
        self._mark = Wordmark(_LOGO)
        self._view = FrameView(*_VIEW)
        self._view.hide()
        self._lay = QVBoxLayout(self._surface)
        self._lay.setContentsMargins(_PAD[0] + _MARGIN, _PAD[1] + _MARGIN,
                                     _PAD[0] + _MARGIN, _PAD[1] + _MARGIN)
        self._lay.setSpacing(_V_GAP)
        self._lay.addWidget(self._mark, 0, Qt.AlignCenter)
        self._lay.addWidget(self._view, 0, Qt.AlignCenter)

        # ── the two motions, and how they compose ─────────────────────────────
        # _live_anim    0→1    the FADE. Drives the settled level of every property.
        #                      Short and rare, so it stays on Qt's 60Hz driver.
        # _breath_timer 0→1→0  the BREATH. Rides on top, scaled by _live, and runs
        #                      for as long as TONY listens — hence its own, slower
        #                      clock (see _BREATH_FPS).
        # Everything visible is a pure function of (_live, _breath) in
        # _apply_liveness(), so the two can never desync and a fade that starts
        # mid-breath cannot jerk: at _live 0 the breath is worth exactly nothing.
        self._live = 0.0
        self._breath = 0.0
        self._live_anim = QVariantAnimation(self)
        self._live_anim.valueChanged.connect(self._apply_liveness)
        self._live_anim.finished.connect(self._settle)
        self._breath_phase = 0        # ms into the cycle
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(round(1000 / _BREATH_FPS))
        self._breath_timer.timeout.connect(self._on_breath)
        self._glow_on = False
        self._apply_liveness(0.0)     # boot asleep, snapped — never a fade on startup

        self._popup = _Popup(self._reduce_motion)

        self._surface.setFixedSize(*_WIN)
        self.setFixedSize(*_WIN)
        self._dock()

        self._reveal_anim = QVariantAnimation(self)
        self._reveal_anim.valueChanged.connect(self._apply_reveal)
        self._reveal_anim.finished.connect(self._reveal_settled)

        # Vision mode's picture arrives here, or does not. See the module docstring for
        # why nothing signals this and it watches instead.
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._poll_vision)
        self._frame_timer.start(_FRAME_MS)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:   # re-centre when the resolution / taskbar changes
            # DEFERRED, never inline. This fires from inside Windows' own display-change
            # handling (monitor sleep/wake, DPI, RDP, GPU driver reset), and _dock() is a
            # move() on a layered topmost window — synchronous Win32 geometry work, the
            # same class of call that provably wedged the GUI thread once before. Bounce
            # it onto the event loop so the OS handler returns first, and let the display
            # settle before we measure it.
            screen.availableGeometryChanged.connect(
                lambda *_: QTimer.singleShot(250, self._dock))

    # -------------------------------------------------------- geometry --
    def _dock(self) -> None:
        """Top-centre. Skipped in Vision mode: the founder put the panel somewhere
        deliberately, and a monitor waking up is no reason to overrule him."""
        if self.vision:
            return
        self.move(dock_rect().topLeft() - QPoint(_MARGIN, _MARGIN))

    def _visible_rect(self) -> QRect:
        """Global rect of the visible GLASS (excludes the shadow gutter) — used to
        anchor the popup and the panel underneath it.

        Read off the surface rather than computed from a mode, so it is true while
        the pill is mid-reveal too: anything anchoring to it follows the glass instead
        of jumping to where the glass is about to be."""
        return self._surface.glass_rect().toAlignedRect().translated(self.pos())

    # ---------------------------------------------------------- vision --
    def _poll_vision(self) -> None:
        """One tick: is vision mode sending frames? Show them, or fall back to a pill.

        Every way vision mode can end — closed by voice, crashed, killed — arrives here as
        the same two facts: the buffer is gone, or it went quiet. One rule covers all."""
        if self._reader is None:
            self._looks += 1
            if self._looks < _LOOK_EVERY:
                return
            self._looks = 0
            try:
                self._reader = frames.Reader()
            except (FileNotFoundError, OSError):
                return                       # vision mode simply is not running
            self._last_frame_at = time.monotonic()

        frame = self._reader.get()
        if frame is False:                   # vision mode shut down cleanly
            self._set_vision(False)
            return
        if frame is not None:
            self._last_frame_at = time.monotonic()
            self._view.set_frame(frame)
            if not self.vision:
                self._set_vision(True)
        elif time.monotonic() - self._last_frame_at > _STALE_S:
            self._set_vision(False)          # no goodbye and no frames: it died

    def _set_vision(self, on: bool) -> None:
        """Open into the panel, or close back to the pill.

        The WINDOW is resized exactly twice per cycle and both times at rest: to the
        panel size before the opening starts, and back to the pill size after the
        closing has finished. In between only paint changes. See _reveal().
        """
        if on == self.vision:
            return
        self.vision = on
        if not on:
            # ORDER MATTERS: the picture must own its pixels before the buffer they
            # live in is unmapped, or the closing animation paints through a dangling
            # pointer and takes the whole process with it.
            self._view.detach()
            if self._reader is not None:
                self._reader.close()
                self._reader = None

        if on:
            # Everything the panel needs is in place before the first frame of the
            # reveal, so the animation has nothing to do but paint.
            self._surface.set_radius(_V_RADIUS)
            self._view.set_alpha(0.0)
            self._view.setVisible(True)      # in the layout from frame one, invisible
            self._lay.setContentsMargins(_V_PAD + _MARGIN, _V_PAD + _MARGIN,
                                         _V_PAD + _MARGIN, _V_PAD + _MARGIN)
            self._surface.setFixedSize(*_VISION_WIN)
            self.setFixedSize(*_VISION_WIN)
            # Keep the wordmark roughly where it already was, so the pill reads as
            # opening downward out of itself rather than jumping somewhere new.
            here, avail = self.pos(), QGuiApplication.primaryScreen().availableGeometry()
            self.move(min(max(avail.left(), here.x() - (_VISION_WIN[0] - _WIN[0]) // 2),
                          max(avail.left(), avail.right() - _VISION_WIN[0])),
                      min(here.y(), max(avail.top(), avail.bottom() - _VISION_WIN[1])))

        self._reveal_anim.stop()
        self._reveal_anim.setDuration(_OPEN_MS if on else _CLOSE_MS)
        self._reveal_anim.setEasingCurve(
            QEasingCurve.OutCubic if on else QEasingCurve.InOutSine)
        self._reveal_anim.setStartValue(self._reveal_t)
        self._reveal_anim.setEndValue(1.0 if on else 0.0)
        self._reveal_anim.start()

    def _apply_reveal(self, t: float) -> None:
        """THE render function for the transition: 0 is a pill, 1 is the open panel.

        Nothing here moves a window. The glass box grows out of the pill rect and the
        picture fades in behind it, both inside a window that already has its final
        geometry — which is the one kind of motion this app is allowed to animate.
        """
        self._reveal_t = t = min(1.0, max(0.0, float(t)))
        full = QRectF(self._surface.rect()).adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        if t >= 1.0:
            self._surface.set_glass_box(None)
        else:
            grow = min(1.0, t / _REVEAL_SPLIT)
            pill = QRectF(full.center().x() - _PILL[0] / 2, full.top(), *_PILL)
            self._surface.set_glass_box(QRectF(
                _lerp(pill.x(), full.x(), grow), full.top(),
                _lerp(pill.width(), full.width(), grow),
                _lerp(pill.height(), full.height(), grow)))
        # The picture only fades once the glass around it has finished growing —
        # otherwise its lower edge hangs outside the glass for the whole reveal.
        # It stays in the LAYOUT throughout, at zero opacity: hiding it takes it out
        # of the column, and the wordmark then centres itself in the whole panel and
        # slides out from under a glass that has not grown yet.
        self._view.set_alpha(max(0.0, (t - _REVEAL_SPLIT) / (1.0 - _REVEAL_SPLIT)))

    def _reveal_settled(self) -> None:
        """End of a close: only now may the window shrink, and only now is it a pill
        again. Doing either mid-animation would put a geometry change on every frame."""
        if self._reveal_t > 0.0:
            return
        self._view.set_frame(None)
        self._view.setVisible(False)
        self._surface.set_glass_box(None)
        self._surface.set_radius(999)
        self._lay.setContentsMargins(_PAD[0] + _MARGIN, _PAD[1] + _MARGIN,
                                     _PAD[0] + _MARGIN, _PAD[1] + _MARGIN)
        self._surface.setFixedSize(*_WIN)
        self.setFixedSize(*_WIN)
        self._dock()

    def _apply_liveness(self, v: float) -> None:
        """THE render function: asleep(0) → lit(1). Ring, wordmark, glass and glow are
        all derived from this one scalar, so no two of them can drift apart mid-fade."""
        self._live = v = min(1.0, max(0.0, float(v)))
        self._surface.set_tone(_mix(_IDLE_FILL, _LIVE_FILL, v),
                               _mix(_IDLE_RING, _LIVE_RING, v),
                               _lerp(_IDLE_W, _LIVE_W, v))
        self._mark.set_liveness(v)
        # The breath is now a paint parameter, not an animated effect: the reach of
        # the painted glow. set_shadow clamps it to the gutter at every intermediate
        # value, not just the two endpoints.
        self._surface.set_shadow(
            _mix(_IDLE_SHADOW, _LIVE_SHADOW, v),
            dy=_lerp(_IDLE_DY, _LIVE_DY, v),
            reach=_lerp(_IDLE_REACH, _LIVE_REACH, v)
                  + (_BREATH_PEAK - _LIVE_REACH) * v * self._breath)

    def _on_breath(self) -> None:
        """One tick: advance the phase and re-derive the breath from it. A triangle
        wave (0→1→0), same shape the keyframed animation had. The phase is counted in
        ticks rather than read off a clock — a coarse timer that runs a few ms late
        makes the breath a few ms slower, which is not a thing anyone can see, and it
        keeps the wave continuous across a tick that arrives late."""
        self._breath_phase = (self._breath_phase + self._breath_timer.interval()) % _BREATH_MS
        p = self._breath_phase / _BREATH_MS
        self._breath = 1.0 - abs(2.0 * p - 1.0)
        self._apply_liveness(self._live)

    def _settle(self) -> None:
        """End of a fade-out: stop breathing entirely rather than animate a glow
        nobody can see. Phase resets with it, so the next wake starts flush at zero
        contribution instead of jumping into the middle of a breath."""
        if self._live <= 0.0:
            self._breath_timer.stop()
            self._breath_phase = 0
            self._breath = 0.0
            self._apply_liveness(0.0)

    def _set_glow(self, active: bool) -> None:
        """Lit vs asleep — cross-faded, both directions, and interruptible: a state
        change mid-fade retargets from wherever the fade currently sits instead of
        jumping back to the far endpoint."""
        if active == self._glow_on:
            return  # don't restart anything on a repeated state signal
        self._glow_on = active
        target = 1.0 if active else 0.0
        # Grab where we ARE before touching the animation: re-configuring a stopped
        # QVariantAnimation re-evaluates it at its stale currentTime and would emit a
        # bogus value straight into _live. start() re-emits the real one at t=0.
        cur = self._live
        self._live_anim.stop()

        if self._reduce_motion:
            self._breath_timer.stop(); self._breath_phase = 0; self._breath = 0.0
            self._apply_liveness(target)
            return

        if active and not self._breath_timer.isActive():
            self._breath_timer.start()  # phase 0 == zero contribution: starts flush
        # Duration scales with the distance left to travel, so an interrupted fade
        # runs at the same SPEED as a full one instead of crawling the last 10%.
        dist = abs(target - cur)
        base = _FADE_IN_MS if active else _FADE_OUT_MS
        self._live_anim.setDuration(max(90, round(base * dist)))
        self._live_anim.setEasingCurve(
            QEasingCurve.OutCubic if active else QEasingCurve.InOutSine)
        self._live_anim.setStartValue(cur)
        self._live_anim.setEndValue(target)
        self._live_anim.start()

    # ------------------------------------------------------------ win32 --
    def showEvent(self, e):
        super().showEvent(e)
        try:
            win_native.set_no_activate(win_native.own_hwnd(self))  # never steal focus
        except Exception:
            pass  # offscreen/no real HWND in the smoke test — real runtime behavior unaffected

    # ------------------------------------------- click, and in vision mode drag --
    def _click_target(self) -> QRect:
        """Where a click opens the reference card. At pill size that is the whole
        pill. Carrying a picture it is the wordmark alone — the rest of the glass is
        for dragging, and a click on the founder's own hand would be a strange way to
        ask for the gesture list."""
        if not self.vision:
            return self._visible_rect()
        return QRect(self._mark.mapToGlobal(QPoint(0, 0)), self._mark.size())

    def mousePressEvent(self, e):
        if (e.button() == Qt.LeftButton
                and self._visible_rect().contains(e.globalPosition().toPoint())):
            self._press_at = e.globalPosition().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """Vision mode can be dragged; the docked pill cannot. The slop is what keeps
        a click on the wordmark from becoming a one-pixel drag — past it, Windows
        takes over the move entirely (see win_native.start_native_drag)."""
        if (self.vision and self._press_at is not None and
                (e.globalPosition().toPoint() - self._press_at).manhattanLength() > _DRAG_SLOP):
            self._press_at = None
            try:
                win_native.start_native_drag(win_native.own_hwnd(self))
            except Exception:
                pass   # offscreen/no real HWND in the smoke test
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """A click that never became a drag opens the reference card. The window is
        _MARGIN bigger than the glass on every side (shadow gutter), and that gutter
        is invisible — so only a release on the glass itself counts."""
        if (e.button() == Qt.LeftButton and self._press_at is not None
                and self._on_open_info is not None
                and self._click_target().contains(e.globalPosition().toPoint())):
            self._on_open_info()
        self._press_at = None
        super().mouseReleaseEvent(e)

    # --------------------------------------------------- worker signals --
    def set_state(self, state: str) -> None:
        """The only thing state drives now is the glow: anything but "idle" is active."""
        self._set_glow(state != "idle")

    def show_response(self, text: str, ok: bool = True) -> None:
        """The one piece of text TONY still shows. ok=False for failures/no-match.

        Silent while the pill is hidden: the popup is its own top-level, so with the
        pill toggled off from the notification area it used to pop up at the top of
        an otherwise empty screen with nothing to hang off. The guard lives here, not
        in app.py, so every caller of show_response gets it.

        Empty text is also silence, which is how a command says "I did something you
        can already see" — opening vision mode is the case that needed it."""
        if not text or not self.isVisible():
            return
        self._popup.show_message(text, ok=ok, anchor=self._visible_rect())

    def on_type_mode(self, on: bool) -> None:
        """Dictation is a MODE, and the cost of not knowing you are in it is a
        paragraph of speech typed into whatever happened to have focus. So it gets a
        banner that stays up, not a notice that fades after two seconds."""
        if not self.isVisible():
            return
        if on:
            self._popup.show_message('TYPE MODE  ·  say "stop typing"', ok=True,
                                     anchor=self._visible_rect(), sticky=True)
        else:
            self._popup._sticky = False
            self._popup._dismiss()

    def hideEvent(self, e):
        """...and a popup already on screen goes with the pill, mid-display."""
        self._popup.hide()
        super().hideEvent(e)

    def on_window_opened(self) -> None:
        self._set_glow(True)

    def on_window_closed(self) -> None:
        self._set_glow(False)
