"""Offscreen GUI smoke test — constructs the real widgets and forces a paint pass.
Catches paint-time crashes (bad QPen/enum/kwarg) without showing a window.
Run: QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_smoke.py -v
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPixmap

_app = QApplication.instance() or QApplication([])


def _paint_box(s):
    """Everything a GlassSurface can put on screen, in its parent's coordinates: the
    glass, grown by the shadow's reach (+1 for the outermost stroke's own width) and
    pushed down by its offset. The whole gutter design is that this stays inside the
    window — see test_nothing_paints_outside_its_window."""
    g = s.glass_rect().toAlignedRect().translated(s.pos())
    r, dy = s._shadow_r, s._shadow_dy
    return g.adjusted(-r - 1, round(-r - 1 + dy), r + 1, round(r + 1 + dy))


def _force_paint(w):
    """Render the widget into a pixmap → runs paintEvent for real.
    render(QPaintDevice) — this PySide6 build's render(QPainter) overload requires
    a targetOffset positional arg too; passing the QPixmap directly is the plain
    supported overload and does the same job."""
    w.resize(w.sizeHint() if w.sizeHint().isValid() else w.size())
    pm = QPixmap(max(w.width(), 10), max(w.height(), 10))
    pm.fill()
    w.render(pm)


def _sample_leg(popup, n=12):
    """Step the popup's CURRENT animation leg frame by frame — the real animation, not
    _render() called by hand — and return (window geometries, glass offsets) per frame."""
    from PySide6.QtCore import QAbstractAnimation
    assert popup._anim.state() == QAbstractAnimation.Running, "nothing is animating"
    # pause first: Qt's unified timer re-drives a RUNNING animation from wall-clock,
    # which would overwrite the frame we are trying to inspect.
    popup._anim.pause()
    geos, offsets = [], []
    for i in range(n + 1):
        popup._anim.setCurrentTime(round(popup._anim.duration() * i / n))
        geos.append(popup.geometry())
        offsets.append(popup._surface.y())
    return geos, offsets


def _settle(popup, legs=6):
    """Run whatever the popup is animating to its end — and whatever THAT starts —
    without waiting on the wall clock. Driving currentTime to the duration stops the
    animation at its end, which is what emits finished(), so a retract that has a
    message queued behind it chains into its own entrance exactly as it does live."""
    from PySide6.QtCore import QAbstractAnimation
    for _ in range(legs):
        if popup._anim.state() == QAbstractAnimation.Stopped:
            return
        popup._anim.setCurrentTime(popup._anim.duration())
    raise AssertionError("the popup's motion never came to rest")


def _settle_reveal(t):
    """Drive the pill's open/close reveal straight to its end, without the wall clock.
    setCurrentTime(duration) stops the animation at its end, which is what emits
    finished() — and finished() is where the window is allowed to resize."""
    from PySide6.QtCore import QAbstractAnimation
    a = t._reveal_anim
    if a.state() != QAbstractAnimation.Stopped:
        a.setCurrentTime(a.duration())
    assert a.state() == QAbstractAnimation.Stopped, "the reveal never came to rest"


def test_pill_is_the_wordmark_plus_its_padding():
    """The pill is logo-only, so its footprint IS the wordmark + the design padding.
    Pinning both the constant and the relation catches an art-asset swap that would
    silently leave the letterforms hanging out of the glass."""
    from ui.glyphs import Wordmark
    from ui.tray import _PILL, _LOGO, _PAD

    assert _PILL == (95, 40)
    assert _PAD[0] == _PILL[1] // 2, "x-padding must clear the stadium's end radius"
    assert Wordmark(_LOGO).width() + 2 * _PAD[0] == _PILL[0]
    assert _LOGO + 2 * _PAD[1] == _PILL[1]


def test_tray_paints_every_state_and_never_changes_size():
    from ui.tray import TonyTray, _PILL, _WIN

    window = _WIN

    t = TonyTray()                       # no constructor args any more
    t.show()                             # offscreen platform: no real window appears
    _force_paint(t)
    assert t.size().toTuple() == window
    # the surface IS the window: it carries the shadow gutter itself, so the glass
    # inside it is the pill
    assert t._surface.size().toTuple() == window
    assert t._surface.glass_rect().size().toTuple() == _PILL

    for s in ("idle", "listening", "heard", "executed", "no_match"):
        t.set_state(s)
        _force_paint(t)
        # the pill no longer resizes, expands, or shows the state — only the glow moves
        assert t.size().toTuple() == window, f"{s} resized the pill"
        assert t._glow_on is (s != "idle"), f"{s}: glow should be {s != 'idle'}"

    t.show_response("increased volume by 10%")
    _settle(t._popup)
    wide = t._popup.width()
    assert t._popup._tick.isVisibleTo(t._popup)
    assert abs(t._popup.geometry().center().x() - t._visible_rect().center().x()) <= 1
    _force_paint(t._popup)

    t.show_response("didn't catch that", ok=False)
    _settle(t._popup)
    assert not t._popup._tick.isVisibleTo(t._popup)   # failures read muted, no gold check
    assert t._popup.width() < wide  # sizes to THIS message, not the previous one
    _force_paint(t._popup)

    t.on_window_opened(); _force_paint(t)
    assert t._glow_on
    t.on_window_closed(); _force_paint(t)
    assert not t._glow_on
    assert t.size().toTuple() == window

    # the removed surface: no settings, no ring, no transcript, no state label
    for gone in ("_stack", "_ring", "_settings_view", "set_transcript",
                 "on_window_reset", "_open_settings", "_dot", "_hint"):
        assert not hasattr(t, gone), f"{gone} should be gone"


def test_the_popup_stays_silent_while_the_pill_is_hidden():
    """The notification-area icon toggles the pill, but the popup is its own
    top-level — so a command used to pop "increased volume by 10%" up at the top of
    an empty screen with nothing to hang off. It follows the pill, both ways."""
    from ui.tray import TonyTray

    t = TonyTray(); t.show()
    t.show_response("increased volume by 10%")
    assert t._popup.isVisible(), "with the pill up, the popup still reports"

    t.hide()   # what the tray icon does: overlay.setVisible(False)
    assert not t._popup.isVisible(), "a popup mid-display must go with the pill"

    t.show_response("increased volume by 10%")
    assert not t._popup.isVisible(), "hidden pill → no orphan popup"
    t.show_response("didn't catch that", ok=False)
    assert not t._popup.isVisible(), "…failures too, not just the ok path"

    t.show()
    t.show_response("increased volume by 10%")
    assert t._popup.isVisible(), "and it comes back when the pill does"


def test_the_popup_comes_out_of_the_pill_and_goes_back_into_it():
    """The founder's complaint: "bir anda ekrana çıkıyor ve bir anda gidiyor". The
    entrance already faded; the exit was a bare hide() — the popup was deleted from
    the screen mid-sentence. Both ends must be a MOVE as well as a fade: a pure
    opacity change with no travel reads as a flicker, not as an object arriving."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.glyphs import MARGIN
    from ui.tray import TonyTray, _POPUP_MS, _POP_TRAVEL, _POP_IN_MS, _POP_OUT_MS, DROP

    t = TonyTray(); t.show()
    p = t._popup

    # The caret tip IS the top of the glass, and the glass is what travels — the
    # window around it holds still. So the motion is read off the glass, in global
    # coordinates, which is where the founder's eye reads it too. (The surface is
    # the glass plus its shadow gutter, hence the MARGIN.)
    def caret_tip():
        return p.y() + p._surface.y() + MARGIN

    t.show_response("increased volume by 10%")
    rest = t._visible_rect().bottom() + DROP
    assert p._anim.state() == QAbstractAnimation.Running, "the entrance must animate"
    assert p._anim.duration() == _POP_IN_MS, "a full-distance entrance is the full duration"
    assert p._opacity == 0.0 and caret_tip() == rest - _POP_TRAVEL, \
        "it must start tucked under the pill, not at its resting place"
    assert _POP_TRAVEL > DROP, "at zero opacity the caret tip must be INSIDE the pill"

    p._anim.pause(); p._anim.setCurrentTime(p._anim.duration() // 2)
    assert 0.0 < p._opacity < 1.0, "half-way through, half faded"
    assert rest - _POP_TRAVEL < caret_tip() < rest, "...and half-way out"
    assert p._surface.x() == 0, "the travel is vertical only — it must not drift sideways"

    _settle(p)
    assert p._opacity == 1.0 and caret_tip() == rest, "it must settle exactly on its anchor"
    assert p._hide_timer.isActive() and p._hide_timer.interval() == _POPUP_MS

    # the hold expires — fire the timer by hand rather than sleeping 2.2s
    p._hide_timer.stop(); p._dismiss()
    assert p.isVisible(), "the popup must still be on screen while it leaves"
    assert p._anim.state() == QAbstractAnimation.Running, "the exit must animate too"
    # Reading self._opacity AFTER re-configuring the animation would read the value it
    # is about to animate TO — distance ~0, and every leg collapses to the 60ms floor.
    assert p._anim.duration() == _POP_OUT_MS, "the exit collapsed to the minimum duration"
    assert _POP_OUT_MS > _POP_IN_MS, "leaving is slower than arriving — it drifts away"
    p._anim.pause(); p._anim.setCurrentTime(p._anim.duration() // 2)
    assert 0.0 < p._opacity < 1.0, "mid-exit it must be part-faded, not gone"
    assert caret_tip() < rest, "...and drifting back up into the pill"

    _settle(p)
    assert not p.isVisible(), "and it must actually be gone at the end"
    assert p.windowOpacity() == 0.0, "a layered window left part-opaque can burn in"


def test_the_popup_window_holds_still_and_only_the_glass_inside_it_travels():
    """THE FREEZE. The first cut of this motion animated the popup's own position:
    a SetWindowPos per animation frame on a WS_EX_LAYERED always-on-top tool window,
    i.e. ~60 full layered recomposites a second driven from the GUI thread. On the
    founder's machine the GUI thread wedged — process alive, Responding=False, no
    Python traceback, worker thread still logging. The pill's breathing glow has
    animated for days without trouble because it only ever REPAINTS.

    So the rule the founder's machine wrote: the popup's window geometry is set once
    per message and is byte-identical at every point of both legs, and what moves is
    the glass inside it — a non-native child, whose move is a dirty region, not a
    Win32 geometry call."""
    from PySide6.QtCore import Qt
    from ui.tray import TonyTray, _POP_TRAVEL

    t = TonyTray(); t.show()
    p = t._popup

    t.show_response("increased volume by 10%")
    geos, offsets = _sample_leg(p)                        # the entrance, frame by frame
    assert all(g == geos[0] for g in geos), \
        f"the window moved or resized mid-entrance: {geos[0]} → {geos[-1]}"
    assert len(set(offsets)) > 3, "the glass must actually travel, not merely fade"
    assert offsets == sorted(offsets), "the entrance comes OUT of the pill, monotonically"

    _settle(p)
    p._hide_timer.stop(); p._dismiss()
    out_geos, out_offsets = _sample_leg(p)                # ...and the exit
    assert all(g == geos[0] for g in out_geos), \
        f"the window moved or resized mid-exit: {out_geos[0]} → {out_geos[-1]}"
    assert out_offsets == sorted(out_offsets, reverse=True), "the exit goes back IN"
    assert min(offsets + out_offsets) == 0, "fully tucked is flush with the window top"
    assert max(offsets + out_offsets) == _POP_TRAVEL, "...and so is full rest, one travel down"

    # The mechanism, not just the symptom. A native child would put the per-frame
    # SetWindowPos straight back, and calling winId() on the glass is how that happens.
    assert not p._surface.testAttribute(Qt.WA_NativeWindow), \
        "the glass must stay a non-native child: its move is a repaint, not a Win32 call"
    assert p.layout() is None, \
        "an outer layout would re-place the glass on activation and fight the travel"


def test_nothing_in_the_ui_re_geometries_a_translucent_top_level_per_frame():
    """The same sweep, across the whole UI rather than the one widget that broke: every
    animated render path must be paint-only. The pill breathes for as long as TONY is
    awake — it is the one that would hurt most."""
    from ui.tray import TonyTray
    from ui.info_window import InfoWindow

    t = TonyTray(); t.show()
    before = (t.geometry(), t._surface.geometry())
    for i in range(21):                       # the fade, with the breath riding on it
        t._breath = (i % 11) / 10
        t._apply_liveness(i / 20)
        assert (t.geometry(), t._surface.geometry()) == before, \
            f"the pill re-geometried at liveness {i / 20} — it must only repaint"

    # ...and the panel, which is the third layered top-level. It has no animation at
    # all: present() places it once and nothing else in it touches geometry.
    w = InfoWindow(on_turn_off=lambda: None)
    w.present()
    panel = w.geometry()
    pm = QPixmap(w.size()); pm.fill(); w.render(pm)   # NOT _force_paint: that resizes
    assert w.geometry() == panel, "painting the panel must not re-place it"
    import ui.info_window as panel_mod
    src = open(panel_mod.__file__, encoding="utf-8").read()
    assert "QVariantAnimation" not in src and "QPropertyAnimation" not in src, \
        "an animation in the panel needs the same paint-only audit the popup got"


def test_back_to_back_commands_retract_and_come_back_out():
    """He fires several commands inside one listening window, so this path runs more
    often than the entrance does. The popup must never blink out and never resize
    under a fully-lit message — it ducks back into the pill, changes its line there,
    and comes out again. That also means a repeat of the SAME sentence still reads as
    a new answer, which an in-place text swap could not do."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.tray import TonyTray, _POP_SWAP_MS, _POP_IN_MS, _POP_TRAVEL

    t = TonyTray(); t.show()
    p = t._popup

    t.show_response("increased volume by 10%")
    _settle(p)
    wide = p.width()

    t.show_response("didn't catch that", ok=False)
    assert p._pending is not None, "the new line waits until the old one is out of sight"
    assert p.width() == wide, "the size must not snap while the old line is still lit"
    assert p._anim.endValue() == 0.0, "it retracts into the pill first"
    assert p._anim.duration() == _POP_SWAP_MS, "the retract collapsed to the 60ms floor"
    assert not p._hide_timer.isActive(), "...and the old hold is cancelled, not left to fire"
    assert p.isVisible()

    p._anim.setCurrentTime(p._anim.duration())   # the retract lands; the swap chains on
    assert p._anim.duration() == _POP_IN_MS, \
        "the entrance behind a swap must run at full speed, not at the floor"
    _settle(p)
    assert p.isVisible(), "it must never blink out between two commands"
    assert p._pending is None
    assert p.width() < wide and not p._tick.isVisibleTo(p), "the new message is on screen"
    assert p._opacity == 1.0 and p._surface.y() == _POP_TRAVEL
    assert p._hide_timer.isActive(), "the hold restarts with the new message"

    # the common real case: the same command twice in a row. Nothing about the popup
    # CHANGES, so the beat is the only thing that reports the second one.
    t.show_response("didn't catch that", ok=False)
    assert p._anim.endValue() == 0.0, "an identical repeat must still get its beat"
    _settle(p)
    assert p.isVisible() and p._opacity == 1.0

    # a message landing mid-entrance is the same story, not a special case
    t.show_response("volume down")
    _settle(p)
    t.show_response("muted")
    assert p._anim.state() == QAbstractAnimation.Running and p._pending is not None
    _settle(p)
    assert p.isVisible() and p._opacity == 1.0


def test_reduce_motion_snaps_the_popup_both_ways():
    """Same rule as everywhere else in the UI — and the EXIT has to obey it too, or
    reduce_motion buys a 300ms animation it just removed from the entrance."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.tray import TonyTray, _POP_TRAVEL

    t = TonyTray(); t._reduce_motion = True
    t._popup._reduce_motion = True
    t.show()
    p = t._popup

    t.show_response("increased volume by 10%")
    assert p._anim.state() == QAbstractAnimation.Stopped, "reduce_motion must not animate"
    assert p._opacity == 1.0 and p._surface.y() == _POP_TRAVEL, \
        "it must be fully out immediately"

    t.show_response("didn't catch that", ok=False)   # back-to-back: instant swap
    assert p._anim.state() == QAbstractAnimation.Stopped and p._pending is None
    assert not p._tick.isVisibleTo(p) and p._opacity == 1.0

    p._dismiss()
    assert not p.isVisible(), "the exit must snap too"
    assert p._anim.state() == QAbstractAnimation.Stopped


def _snap(t, active):
    """Put the pill on an endpoint with no animation running — the state the eye
    settles on, which is what the readability assertions are about."""
    rm, t._reduce_motion = t._reduce_motion, True
    t.set_state("listening" if active else "idle")
    t._reduce_motion = rm


def test_idle_and_listening_are_two_different_objects():
    """The founder could not tell whether TONY was awake: a breathing glow is a
    peripheral-vision failure (slow bloom, same warm colour). The step has to be in
    contrast — ring weight, ring alpha and wordmark brightness all move at once, so
    a future tweak cannot quietly flatten the two states back together."""
    from ui.tray import TonyTray, _PILL, _WIN

    t = TonyTray(); t.show()

    _snap(t, False)
    idle_w, idle_a = t._surface._stroke_w, t._surface._stroke.alpha()
    idle_fill, idle_ext = t._surface._fill.alpha(), t._surface._shadow_r
    assert t._mark._live == 0.0, "idle: the wordmark must read washed out"
    # ...but idle is ASLEEP, not ABSENT: the founder asked for a thin gold border he
    # can actually see. The old 22% light-gold hairline vanished into the cream edge.
    assert idle_a >= 150, f"idle ring alpha {idle_a} is too faint to read as gold"
    assert t._surface._stroke.getRgb()[:3] in ((201, 162, 39), (156, 122, 22)), \
        "the idle border must be a palette GOLD, not a neutral edge"
    assert idle_w <= 1.0, "...and still a hairline: 'ince'"

    _snap(t, True)
    live_w, live_a = t._surface._stroke_w, t._surface._stroke.alpha()
    assert t._mark._live == 1.0, "listening: full-contrast gold wordmark"

    assert live_w >= idle_w * 2, f"ring {idle_w}→{live_w}px is not a visible step"
    assert live_a > idle_a, f"ring alpha {idle_a}→{live_a} must still brighten"
    # Idle now carries a real gold border, so the ring's step is mostly WEIGHT, not
    # alpha. What the eye catches is the combination — its INK, weight x alpha.
    assert live_w * live_a >= 3 * idle_w * idle_a, "the two states read the same"
    assert t._surface._fill.alpha() > idle_fill, "idle glass must sit back"
    assert t._surface._shadow_r > idle_ext, "listening must carry the bigger glow"
    assert t._mark.MUTED_OPACITY < 0.5

    # the thicker ring grows INWARD: the glass (and so the paint) must not grow
    assert t._surface.size().toTuple() == _WIN
    assert t._surface.glass_rect().size().toTuple() == _PILL
    assert t.rect().contains(_paint_box(t._surface)),         "the lit glow paints outside the window — that is the black box"


def test_the_two_states_cross_fade_instead_of_snapping():
    """The founder's complaint: the step was right but the SWITCH was jarring. One
    0→1 scalar is animated and every property is a pure function of it, so the fade
    can never desync — and it must actually pass through the middle, both ways."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.tray import TonyTray

    t = TonyTray(); t.show()
    assert t._live == 0.0, "TONY must boot asleep, snapped — no fade on startup"

    def sample():
        return (t._surface._stroke_w, t._surface._stroke.alpha(),
                t._surface._fill.alpha(), t._mark._live, t._surface._shadow_r)

    idle = sample()
    t.set_state("listening")
    assert t._live_anim.state() == QAbstractAnimation.Running, "it must animate"
    assert t._live == 0.0, "the fade starts where the pill actually is"

    # pause first: Qt's unified timer re-drives a RUNNING animation from wall-clock,
    # which would overwrite the frame we are trying to inspect.
    t._live_anim.pause()
    t._live_anim.setCurrentTime(t._live_anim.duration() // 2)
    mid = sample()
    t._live_anim.setCurrentTime(t._live_anim.duration())
    live = sample()
    for i, (m, lo, hi) in enumerate(zip(mid, idle, live)):
        assert min(lo, hi) < m < max(lo, hi), f"property {i} snapped instead of fading"

    # ...and back out again: fading out must be a fade too, not a drop
    t.set_state("listening")      # repeated signal: must not restart anything
    t.set_state("idle")
    assert t._live_anim.state() == QAbstractAnimation.Running, "the way out fades too"
    # pause first: Qt's unified timer re-drives a RUNNING animation from wall-clock,
    # which would overwrite the frame we are trying to inspect.
    t._live_anim.pause()
    t._live_anim.setCurrentTime(t._live_anim.duration() // 2)
    out = sample()
    for i, (m, lo, hi) in enumerate(zip(out, idle, live)):
        assert min(lo, hi) < m < max(lo, hi), f"property {i} snapped on the way out"


def test_a_fade_interrupted_mid_way_retargets_instead_of_jumping():
    """TONY drops in and out of the active window constantly, so a state change
    lands mid-fade all the time. It must pick up from the CURRENT value."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.tray import TonyTray

    t = TonyTray(); t.show()
    t.set_state("listening")
    # pause first: Qt's unified timer re-drives a RUNNING animation from wall-clock,
    # which would overwrite the frame we are trying to inspect.
    t._live_anim.pause()
    t._live_anim.setCurrentTime(t._live_anim.duration() // 2)
    caught = t._live
    assert 0.0 < caught < 1.0

    t.set_state("idle")           # interrupt half-way up
    assert t._live == caught, "the reverse fade jumped instead of retargeting"
    assert t._live_anim.startValue() == caught
    assert t._live_anim.endValue() == 0.0
    # a shorter distance takes proportionally less time — same speed, not a crawl
    assert t._live_anim.duration() < 420

    t.set_state("listening")      # ...and interrupt the interruption
    assert t._live_anim.startValue() == t._live
    assert t._live_anim.endValue() == 1.0
    assert t._breath_timer.isActive(), \
        "the breath must not be restarted from zero on every wake"


def test_the_breath_rides_on_top_of_the_fade_and_reduce_motion_snaps():
    """The two animations must not fight: the fade sets the settled level, the breath
    modulates on top scaled by liveness — so at idle the breath is worth exactly
    nothing and a fade starting mid-breath cannot produce a jerk."""
    from PySide6.QtCore import QAbstractAnimation
    from ui.tray import TonyTray, _BREATH_PEAK, _LIVE_REACH

    t = TonyTray(); t.show()

    t._breath = 1.0                       # breath at its peak...
    t._apply_liveness(0.0)                # ...but the pill is asleep
    asleep = t._surface._shadow_r
    t._breath = 0.0
    t._apply_liveness(0.0)
    assert t._surface._shadow_r == asleep, "the breath must be silent while idle"

    t._apply_liveness(1.0)
    settled = t._surface._shadow_r
    t._breath = 1.0
    t._apply_liveness(1.0)
    assert t._surface._shadow_r > settled, "the breath must still show while lit"
    assert settled == _LIVE_REACH and t._surface._shadow_r == _BREATH_PEAK

    # reduce_motion: snap, don't animate — same rule as everywhere else in the UI
    t2 = TonyTray(); t2._reduce_motion = True
    t2.set_state("listening")
    assert t2._live == 1.0 and t2._live_anim.state() == QAbstractAnimation.Stopped
    assert not t2._breath_timer.isActive()
    t2.set_state("idle")
    assert t2._live == 0.0 and t2._live_anim.state() == QAbstractAnimation.Stopped


def test_the_breath_runs_on_its_own_slower_clock():
    """The breath is the only thing in the UI that repaints continuously, and each of
    its frames is a layered-window recomposite plus one strokePath per pixel of glow
    reach. Qt's animation driver is ~60Hz and cannot be told otherwise, so the breath
    owns a QTimer — the rate is a knob, and it is pinned here so nobody quietly puts
    it back on the 60Hz driver. The founder likes the glow: what changes is how often
    it is recomputed, never that it exists."""
    from ui.tray import TonyTray, _BREATH_MS, _BREATH_FPS

    assert _BREATH_FPS <= 30, "the whole point is fewer composites than the 60Hz driver"
    t = TonyTray(); t.show()
    assert t._breath_timer.interval() == round(1000 / _BREATH_FPS) == 40

    t.set_state("listening")
    assert t._breath_timer.isActive() and t._breath_phase == 0 and t._breath == 0.0, \
        "a wake must start flush: phase 0 contributes nothing on top of the fade"

    # a full cycle of ticks, by hand — a triangle wave: 0 → 1 at the half, → 0 again
    seen = []
    for _ in range(round(_BREATH_MS / t._breath_timer.interval())):
        t._on_breath()
        seen.append(t._breath)
    assert max(seen) == 1.0 and seen[-1] == 0.0 and t._breath_phase == 0
    assert seen[:len(seen) // 2] == sorted(seen[:len(seen) // 2]), "it must rise, then fall"
    assert all(abs(b - a) < 0.1 for a, b in zip(seen, seen[1:])), \
        "no step big enough to read as a stutter"

    # ...and it stops dead when the pill goes back to sleep, phase and all
    t.set_state("idle")
    t._live = 0.0; t._settle()
    assert not t._breath_timer.isActive() and t._breath_phase == 0 and t._breath == 0.0


def test_the_docked_pill_sits_top_centre_and_stays_there():
    """At pill size it is an ornament bolted to the top edge, and dock_rect() is a
    pure function of the screen. Only Vision mode may move it (see the drag test)."""
    from PySide6.QtGui import QGuiApplication
    from ui.tray import TonyTray, dock_rect, pill_rect, _PILL, _MARGIN, _TOP_GAP

    t = TonyTray()
    screen = QGuiApplication.primaryScreen().availableGeometry()

    assert dock_rect().size().toTuple() == _PILL
    assert abs(dock_rect().center().x() - screen.center().x()) <= 1
    # tied to the constant, not a copy of it — the gap is tunable, the dock isn't
    assert dock_rect().top() == screen.top() + _TOP_GAP
    assert _TOP_GAP >= _MARGIN // 2, "gap must clear the shadow gutter"
    assert t._visible_rect() == dock_rect(), "the pill must sit exactly on its dock"
    assert pill_rect() == t._visible_rect(), "pill_rect() must ask the real pill"

    # a resolution change re-centres it instead of leaving it stranded
    t.move(0, 0)
    t._dock()
    assert t._visible_rect() == dock_rect()

    import ui.tray as tray_mod
    assert "tray_pos" not in open(tray_mod.__file__, encoding="utf-8").read(), \
        "the position is never persisted — the dock is computed, not remembered"


def test_only_vision_mode_can_be_dragged_and_it_hands_the_move_to_windows():
    """Dragging means re-positioning a layered topmost window per mouse event, which
    is the class of call that wedged the GUI thread once. So Qt must never do it:
    past the slop we call the OS and stop tracking. And the docked pill never drags
    at all."""
    from PySide6.QtCore import QPointF, QEvent, Qt, QPoint
    from PySide6.QtGui import QMouseEvent
    from ui import tray as tray_mod
    from ui.tray import TonyTray, _DRAG_SLOP

    dragged = []
    real = tray_mod.win_native.start_native_drag
    tray_mod.win_native.start_native_drag = lambda hwnd: dragged.append(hwnd)
    try:
        t = TonyTray()

        def press(g):
            t.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(0, 0), QPointF(g),
                                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

        def move(g):
            t.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(0, 0), QPointF(g),
                                         Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

        far = t._visible_rect().center() + QPoint(_DRAG_SLOP * 8, _DRAG_SLOP * 8)
        press(t._visible_rect().center()); move(far)
        assert dragged == [], "the docked pill must not be draggable"

        t._set_vision(True); _settle_reveal(t)
        press(t._visible_rect().center())
        move(t._visible_rect().center() + QPoint(1, 1))
        assert dragged == [], "a one-pixel wobble is still a click, not a drag"
        move(t._visible_rect().center() + QPoint(_DRAG_SLOP * 8, 0))
        assert len(dragged) == 1, "past the slop, Windows takes the move"
        assert t._press_at is None, "tracking must stop the moment the OS takes over"
    finally:
        tray_mod.win_native.start_native_drag = real


def test_a_click_on_the_glass_opens_the_panel_but_the_gutter_is_dead():
    """The window is _MARGIN bigger than the pill on every side (shadow gutter) and
    that gutter is invisible — clicking empty air next to the pill must do nothing."""
    from PySide6.QtCore import QPointF, QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from ui.tray import TonyTray

    opened = []
    t = TonyTray(on_open_info=lambda: opened.append(1))

    def click(g):
        for kind, btn in ((QEvent.MouseButtonPress, Qt.LeftButton),
                          (QEvent.MouseButtonRelease, Qt.LeftButton)):
            ev = QMouseEvent(kind, QPointF(0, 0), QPointF(g), btn, btn, Qt.NoModifier)
            (t.mousePressEvent if kind == QEvent.MouseButtonPress
             else t.mouseReleaseEvent)(ev)

    click(t._visible_rect().center())
    assert opened == [1], "a click on the pill opens the panel"

    click(t.geometry().topLeft())        # in the transparent gutter
    assert opened == [1], "the shadow gutter must not be clickable"

    # In Vision mode only the wordmark opens the card; the rest of the glass drags.
    t.show()
    t._set_vision(True); _settle_reveal(t)
    t._surface.layout().activate()       # _click_target() reads the wordmark's position
    click(t._view.mapToGlobal(t._view.rect().center()))
    assert opened == [1], "clicking the picture must not open the card"
    click(t._click_target().center())
    assert opened == [1, 1], "clicking the wordmark opens the gesture card"
    t._set_vision(False); _settle_reveal(t)   # _live_tray is module-global


def test_panel_is_one_row_per_group_with_one_button():
    from PySide6.QtWidgets import QFrame
    from ui.info_window import InfoWindow
    from commands import build_commands, GROUPS, grouped

    off = []
    w = InfoWindow(on_turn_off=lambda: off.append(1))
    w.present()
    _force_paint(w)

    assert w.turn_off_button.text() == "Turn off TONY"
    w.turn_off_button.click()
    assert off == [1], "the turn-off button must fire its callback"

    rows = w._page(False).findChildren(QFrame, "row")
    # The number is here to catch a group silently vanishing, not to be precious —
    # bump it when you add one on purpose.
    assert len(rows) == len(GROUPS) == 18, f"{len(rows)} rows, expected 18"
    assert "COMMANDS" in w._count.text(), "not in Vision mode: the voice list"

    # every trigger phrase still reaches the panel — shorter list, nothing dropped
    printed = " ".join(l.text() for r in rows for l in r.findChildren(type(w._count)))
    for c in build_commands():
        for trigger in c.triggers:
            assert trigger in printed, f"{c.name}: '{trigger}' is not on the card"
    assert [label for label, _ in grouped(build_commands())][0] in printed

    # read-only: no editors, no add/remove anywhere in the panel
    from PySide6.QtWidgets import QLineEdit, QTextEdit, QPushButton
    assert not w.findChildren(QLineEdit) and not w.findChildren(QTextEdit)
    assert [b.text() for b in w.findChildren(QPushButton)] == ["Turn off TONY"]


def test_panel_hangs_off_the_pill_and_dismisses_itself():
    """It must read as an extension of the pill: centred under it, caret up, on the
    screen — and it must go away on click-away and on Esc, both WITHOUT an input grab.

    THE GRAB IS THE POINT. This was a Qt.Popup, which takes an application-wide mouse
    and keyboard grab on show and calls activateWindow() — while the pill it hangs off
    is WS_EX_NOACTIVATE and cannot hold focus. The founder's freeze arrived on exactly
    that click. A grab nothing releases is a GUI thread that answers nothing, and the
    black rectangle is then just the stale surface of a window that stopped pumping.
    So: no popup, no grab, and dismissal re-implemented out of ordinary events."""
    from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
    from PySide6.QtGui import QGuiApplication, QKeyEvent, QWheelEvent
    from ui.info_window import InfoWindow
    from ui.tray import pill_rect, DROP
    from ui.glyphs import MARGIN

    w = InfoWindow(on_turn_off=lambda: None)
    assert w.windowType() == Qt.Tool, "a Qt.Popup grabs the mouse and the keyboard"

    w.present()
    assert QWidget.mouseGrabber() is None and QWidget.keyboardGrabber() is None, \
        "the open panel must hold no input grab — that is the thing that can wedge"
    glass = w.geometry().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
    pill = pill_rect()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert abs(glass.center().x() - pill.center().x()) <= 1, "not centred under the pill"
    assert glass.top() == pill.bottom() + DROP, "must hang off the pill, not float"
    assert avail.contains(glass), "the panel must fit on the screen"
    assert w._surface._caret, "the caret is what ties the panel back to the pill"

    # it is the founder's reading surface: the wheel has to move it
    area = w._area
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0, "16 rows should still be scrollable content"
    QApplication.sendEvent(area.viewport(), QWheelEvent(
        QPointF(10, 10), QPointF(w.x() + 10, w.y() + 10), QPoint(0, -120), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    assert bar.value() > 0, "the panel must not eat the scroll"

    # Esc, by our own keyPressEvent: QWidget only closes on Cancel for popups
    assert w.isVisible()
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not w.isVisible(), "Esc must close the panel"

    # ...and a re-open inside the guard window is swallowed, so a dismissal that is
    # followed microseconds later by the pill's own click cannot re-open the panel
    w.present()
    assert not w.isVisible(), "a re-open within the guard window must be swallowed"

    # CLICK-AWAY, without a grab: activation arrives, then something else takes the
    # foreground and the panel closes on its own.
    w._hidden_at = 0.0
    w.present()
    QApplication.processEvents()          # activation is delivered on the event loop
    assert w.isActiveWindow() and w._was_active, "the panel must take focus to be closable"
    elsewhere = QWidget(); elsewhere.show(); elsewhere.activateWindow()
    QApplication.processEvents()
    assert not w.isVisible(), "losing activation must dismiss the panel"

    # ...but a panel whose activation never landed (Windows can refuse the foreground)
    # must NOT read its own missing focus as a dismissal and vanish on open.
    w._hidden_at = 0.0
    w.present()
    QApplication.sendEvent(w, QEvent(QEvent.ActivationChange))
    assert w.isVisible(), "the panel hid itself before it was ever focused"

    # the pill's second click closes it — the toggle no longer rides on the popup's
    # dismiss-and-replay, because clicking a NOACTIVATE pill takes no focus away
    w.present()
    assert not w.isVisible(), "clicking the pill again must close the panel"


def test_no_widget_in_the_ui_wears_a_graphics_effect():
    """THE BUG CLASS. The black rectangle came back three times on three unrelated
    triggers — a shadow past the gutter, a per-frame move(), and finally just opening
    the panel. The one thing all three shared: a QGraphicsDropShadowEffect on a widget
    inside a WA_TranslucentBackground top-level. An effect makes Qt render that widget
    through an OFFSCREEN surface and composite the result back into a Win32 layered
    window; every fix held only until the next thing disturbed that composite.

    So the guard is not "the shadow is small enough" any more. It is: there is no
    effect anywhere in the UI. Shadows are painted by GlassSurface, into its own
    surface, like any other pixel."""
    import pathlib
    from PySide6.QtWidgets import QGraphicsEffect
    from ui.tray import TonyTray
    from ui.info_window import InfoWindow

    t = TonyTray(); t.show()
    t.show_response("increased volume by 10%")
    panel = InfoWindow(on_turn_off=lambda: None)
    panel.present()

    for top in (t, t._popup, panel):
        for w in [top] + top.findChildren(QWidget):
            assert w.graphicsEffect() is None, \
                f"{type(w).__name__} in {type(top).__name__} wears a QGraphicsEffect"
        assert not top.findChildren(QGraphicsEffect), \
            f"{type(top).__name__} still owns an effect object"

    # ...and not just at runtime: an effect installed on a widget built later (a
    # future popup, a future row) would slip past the walk above.
    import ui.tray
    for src in pathlib.Path(ui.tray.__file__).parent.glob("*.py"):
        text = src.read_text(encoding="utf-8")
        assert "setGraphicsEffect" not in text, f"{src.name} installs a graphics effect"
        assert "QGraphicsDropShadowEffect(" not in text, \
            f"{src.name} builds the effect that caused the black box"


def test_nothing_paints_outside_its_window():
    """The gutter invariant, which survives the effect's removal: each GlassSurface
    carries MARGIN px of transparent room for its own shadow, and set_shadow() clamps
    the reach to it — so the surface's whole painted box stays inside its top-level,
    in every state, at every point of the fade and of the popup's travel."""
    from ui.glyphs import MARGIN
    from ui.tray import TonyTray
    from ui.info_window import InfoWindow

    t = TonyTray()

    def check(where, top):
        box = _paint_box(top._surface)
        assert top.rect().contains(box), (
            f"{where}: the surface paints {box} outside the window {top.rect()} — "
            f"this is the black-box bug")
        assert top._surface._shadow_r + abs(top._surface._shadow_dy) < MARGIN, \
            f"{where}: the shadow ate its own gutter"

    for state in ("idle", "listening", "executed"):
        t.set_state(state)
        check(state, t)

    # The pill CROSS-FADES between asleep and lit while breathing on top, so the
    # dangerous values are the intermediate ones: sweep the whole (liveness x breath)
    # product, not just the two endpoints.
    for i in range(21):
        for j in range(11):
            t._breath = j / 10
            t._apply_liveness(i / 20)
            check(f"fade @{i / 20} breath @{j / 10}", t)
    assert t._surface._shadow_r == MARGIN - 2 - 1, "the lit peak must fill the gutter"

    # The popup TRAVELS as it fades, inside a window _POP_TRAVEL taller than the
    # surface — so the invariant has to hold at every offset of the travel too.
    t.show()
    t.show_response("increased volume by 10%")
    pop = t._popup
    size, reach = pop._surface.size(), pop._surface._shadow_r
    geo = pop.geometry()
    for i in range(21):
        pop._render(i / 20)
        check(f"popup @{i / 20}", pop)
        assert pop._surface.size() == size, "the popup's surface resized mid-motion"
        assert pop._surface._shadow_r == reach, "the shadow grew mid-motion"
        assert pop.geometry() == geo, \
            "the window must hold still — moving it per frame is what froze the GUI thread"

    panel = InfoWindow(on_turn_off=lambda: None)
    panel.present()
    check("panel", panel)

    # ...and the PIXELS have to agree with the arithmetic, which is the half the old
    # boundingRectFor() sweep could never check: paint the loudest frame there is and
    # look at the window's outermost ring. Any ink there is ink Windows has to
    # composite at the very edge of a layered window.
    from PySide6.QtGui import QImage
    t._breath = 1.0
    t._apply_liveness(1.0)
    for top in (t, pop, panel):
        img = QImage(top.size(), QImage.Format_ARGB32)
        img.fill(0)
        top.render(img)
        edge = [img.pixelColor(x, y).alpha()
                for y in (0, img.height() - 1) for x in range(img.width())]
        edge += [img.pixelColor(x, y).alpha()
                 for x in (0, img.width() - 1) for y in range(img.height())]
        assert max(edge) == 0, \
            f"{type(top).__name__} painted onto its own window edge (alpha {max(edge)})"


def test_deleted_modules_stay_deleted():
    import importlib
    for mod in ("ui.ring", "ui.settings_view"):
        try:
            importlib.import_module(mod)
        except ImportError:
            continue
        raise AssertionError(f"{mod} is back")


def test_font_chain_resolves_to_a_real_serif():
    """Guards the bug that flattened the whole design: QSS `font-family: 'Lora',
    serif` does not walk the fallback list — Qt landed on the system UI sans
    (Tahoma) and every vintage serif silently became a sans. tokens.family() must
    resolve against the real font database instead, and tracking must survive."""
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    from ui import tokens

    georgia = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "georgia.ttf"
    if georgia.exists():  # offscreen Qt starts with an EMPTY font DB — seed it
        QFontDatabase.addApplicationFont(str(georgia))
        tokens.family.cache_clear()
        assert tokens.family("body") == "Georgia"
    assert tokens.family("body") in tokens._CHAINS["body"]
    assert tokens.font("title", 10.5, tracking=1.5).letterSpacing() == 1.5


def test_the_pill_becomes_the_vision_panel_and_goes_back():
    """"Integrate vision mode into TONY" means one object in two shapes, not two objects.
    Both shapes must paint, and the way back must restore every part of the pill —
    size, corner, dock, and the fact that it stops being draggable."""
    import numpy as np
    from ui.tray import TonyTray, dock_rect, _PILL, _VISION_GLASS, _VIEW, _V_RADIUS
    from vision import frames

    t = TonyTray(); t.show()
    assert not t.vision and not t._view.isVisibleTo(t)
    assert t._surface.glass_rect().size().toTuple() == _PILL
    _force_paint(t)

    frame = np.zeros((frames.H, frames.W, 3), np.uint8)
    frame[:, :, 0] = 200                  # BGR: a blue field, so a channel swap shows
    t._view.set_frame(frame)
    t._set_vision(True); _settle_reveal(t)
    assert t.vision and t._view.isVisibleTo(t) and t._view._alpha == 1.0
    assert t._surface.glass_rect().size().toTuple() == _VISION_GLASS
    assert t._surface._radius == _V_RADIUS, "a stadium around a rectangular picture"
    assert t._view.size().toTuple() == _VIEW
    _force_paint(t)

    from PySide6.QtGui import QPixmap
    pm = QPixmap(*_VIEW); pm.fill()
    t._view.render(pm)
    img = pm.toImage()
    px = img.pixelColor(img.width() // 2, img.height() // 2)
    assert px.blue() > px.red(), "the BGR frame came out with its channels swapped"

    t._set_vision(False); _settle_reveal(t)
    assert not t.vision and not t._view.isVisibleTo(t)
    assert t._surface.glass_rect().size().toTuple() == _PILL
    assert t._surface._radius == 999
    assert t._visible_rect() == dock_rect(), "it must go back to its dock"
    _force_paint(t)


def test_the_reference_card_follows_the_mode():
    """While vision mode is running, the voice command list is the wrong card to be
    holding — the founder is using his hands, not his voice."""
    from ui.info_window import InfoWindow
    from ui.tray import TonyTray
    from vision import catalog

    t = TonyTray()
    w = InfoWindow(on_turn_off=lambda: None)

    w.present()
    assert "VOICE COMMANDS" in w._count.text()
    commands_page = w._area.widget()
    w.hide(); w._hidden_at = 0.0

    t._set_vision(True); _settle_reveal(t)
    w.present()
    assert w._count.text() == f"{catalog.count()} GESTURES"
    assert w._area.widget() is not commands_page
    _force_paint(w)
    w.hide(); w._hidden_at = 0.0

    t._set_vision(False); _settle_reveal(t)
    w.present()
    assert "VOICE COMMANDS" in w._count.text()
    assert w._area.widget() is commands_page, "the pages are built once and kept"


def test_an_empty_response_shows_no_popup():
    """Opening vision mode grows the pill in front of you; a popup saying so would narrate
    what the founder is already watching — and it would anchor to a tray mid-resize,
    which is how it ended up orphaned in the middle of the screen."""
    from ui.tray import TonyTray

    t = TonyTray(); t.show()
    t.show_response("")
    assert not t._popup.isVisible(), "an empty response must stay silent"
    t.show_response("increased volume by 10%")
    assert t._popup.isVisible(), "…but a real one still speaks"


def test_the_reveal_never_resizes_the_window():
    """The whole reason the pill opens by painting instead of growing: resizing a
    layered topmost window sixty times a second is the call pattern that wedged the
    GUI thread. The window takes its final size BEFORE the reveal and does not change
    again until AFTER it — in between, only the painted glass moves."""
    from ui.tray import TonyTray, _VISION_WIN, _WIN

    t = TonyTray(); t.show()

    t._set_vision(True)
    assert t.size().toTuple() == _VISION_WIN, "final size before the first frame"
    geo, heights = t.geometry(), []
    for i in range(11):
        t._apply_reveal(i / 10)
        assert t.geometry() == geo, f"the window moved at t={i / 10}"
        heights.append(t._surface.glass_rect().height())
    assert heights == sorted(heights) and heights[0] < heights[-1], "the glass must grow"
    _settle_reveal(t)
    assert t.size().toTuple() == _VISION_WIN

    t._set_vision(False)
    geo = t.geometry()
    for i in range(10, -1, -1):
        t._apply_reveal(i / 10)
        assert t.geometry() == geo, "closing must not move it either"
    _settle_reveal(t)
    assert t.size().toTuple() == _WIN, "…only once it is over"


def test_the_picture_only_fades_in_after_the_glass_has_finished_growing():
    """Otherwise the bottom of a 300px picture hangs outside a glass that is still
    150px tall — for most of the reveal."""
    from ui.tray import TonyTray, _VISION_GLASS

    t = TonyTray(); t.show()
    t._set_vision(True)
    for i in range(21):
        t._apply_reveal(i / 20)
        if t._view._alpha > 0:
            assert t._surface.glass_rect().height() == _VISION_GLASS[1], \
                "the picture started fading while the glass was still growing"
    _settle_reveal(t)
    t._set_vision(False); _settle_reveal(t)


def test_closing_vision_takes_a_private_copy_of_the_last_frame():
    """The picture is a numpy VIEW into vision mode's shared memory — no copy per frame,
    which is the whole point. But the closing animation keeps painting for a quarter
    of a second after that memory is unmapped, and painting through an unmapped
    pointer kills the process where it stands: no traceback, nothing in tony.log,
    the log just ends. So the view must own its pixels before the buffer goes."""
    import numpy as np
    from ui.tray import TonyTray, _LOOK_EVERY
    from vision import frames

    w = frames.Writer()
    try:
        w.put(np.full((frames.H, frames.W, 3), 77, np.uint8))
        t = TonyTray(); t.show()
        for _ in range(_LOOK_EVERY + 2):
            t._poll_vision()
        assert t.vision, "never picked the frames up"
        assert not t._view._frame.flags["OWNDATA"], "should still be the shared view"

        t._set_vision(False)
        assert t._view._frame is not None, "the fade-out still needs something to paint"
        assert t._view._frame.flags["OWNDATA"], "it must be TONY's own memory now"
        assert int(t._view._frame[0, 0, 0]) == 77, "…and still the right pixels"
        _force_paint(t)
        _settle_reveal(t)
    finally:
        w.close()


def test_the_stats_strip_reads_the_machine_and_survives_no_gpu():
    """nvidia-smi is a process launch, so it goes through QProcess and comes back on
    the GUI thread — a machine without it must degrade to CPU and RAM, not to an
    empty line or a crash."""
    from ui.stats import StatsStrip, format_stats, parse_smi

    assert parse_smi("9, 843, 8188\n") == (9, 843, 8188)
    assert parse_smi("") is None
    assert parse_smi("Failed to initialize NVML") is None

    assert "VRAM 0.8 / 8.0 GB" in format_stats(12.4, 47.2, (9, 843, 8188))
    assert "GPU" not in format_stats(12.4, 47.2, None), "say nothing rather than '—'"

    s = StatsStrip()
    s._render()
    assert s.text().startswith("CPU ") and "RAM" in s.text()
    s._gpu_gone()                      # no NVIDIA driver
    s._render()
    assert "GPU" not in s.text()


def test_the_card_only_polls_hardware_while_it_is_open():
    """Reading the GPU once a second for a panel nobody is looking at is battery
    spent on nothing."""
    from ui.info_window import InfoWindow

    w = InfoWindow(on_turn_off=lambda: None)
    assert not w.stats._timer.isActive(), "must not tick before it is ever shown"
    w.present()
    assert w.stats._timer.isActive()
    w.hide()
    assert not w.stats._timer.isActive()


def test_the_stats_strip_does_not_resize_as_the_numbers_change():
    """It updates once a second in a proportional serif. Sized to the current
    reading, it would slide sideways for as long as the card was open."""
    from ui.stats import StatsStrip

    from ui.info_window import InfoWindow, _PANEL_W

    w = InfoWindow(on_turn_off=lambda: None)
    w.present()
    widths = []
    for gpu in (None, (0, 0, 8188), (100, 8188, 8188)):
        w.stats._gpu = gpu
        w.stats._render()
        w._head.layout().activate()
        widths.append(w.stats.width())
    assert len(set(widths)) == 1, f"the strip resized as the numbers changed: {widths}"
    assert w.width() <= _PANEL_W + 2 * 24 + 1, "the strip pushed the card wider"
