"""Render TONY's UI states to PNGs (offscreen) for visual review.
Run: python tools/render_ui.py   → writes tools/render/*.png

No window is ever shown and no audio/mic is touched — this is the safe way to
look at the UI.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtGui import QPixmap, QColor, QPainter, QFontDatabase

OUT = Path(__file__).resolve().parent / "render"
# Qt's offscreen platform ships an EMPTY font database on Windows (families() == []),
# so every glyph renders as tofu and the review is worthless. Seed it from the real
# Windows fonts — dev-tool only, the app itself uses the normal windows platform.
_SEED = ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf",
         "constan.ttf", "constanb.ttf", "constani.ttf",
         "pala.ttf", "palab.ttf", "palai.ttf", "times.ttf", "timesbd.ttf", "timesi.ttf")


def seed_fonts():
    for f in _SEED:
        p = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / f
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))


def shot(w, name, bg="#2c2622", overlay=None):
    """Render `w` (and optionally an `overlay` top-level, composited at its real
    offset) onto the mockup's dark stage. The canvas is the union of both windows —
    the popup is wider than the pill and used to get cropped."""
    OUT.mkdir(parents=True, exist_ok=True)
    box = w.geometry() if overlay is None else w.geometry().united(overlay.geometry())
    pm = QPixmap(box.size())
    pm.fill(QColor(bg))
    p = QPainter(pm)
    for win in (w, overlay):
        if win is None:
            continue
        wpm = QPixmap(win.size()); wpm.fill(QColor(0, 0, 0, 0))
        win.render(wpm)
        p.drawPixmap(win.x() - box.x(), win.y() - box.y(), wpm)
    p.end()
    pm.save(str(OUT / f"{name}.png"))


def motion_strip(t, name, values, pad=14):
    """The popup's motion, frame by frame, left→right on one canvas.

    Motion cannot be judged from a still and cannot be watched offscreen, so the
    tweens get laid out as a strip instead. windowOpacity is not part of what
    QWidget.render() draws, so the frame's opacity is applied by the painter here —
    otherwise every frame would come out fully lit and the strip would show only the
    travel."""
    OUT.mkdir(parents=True, exist_ok=True)
    pop = t._popup
    box = None
    for v in values:                       # pass 1: the union box, so tiles all match
        pop._render(v)
        b = t.geometry().united(pop.geometry())
        box = b if box is None else box.united(b)
    pm = QPixmap(box.width() * len(values) + pad * (len(values) + 1), box.height() + 2 * pad)
    pm.fill(QColor("#2c2622"))
    p = QPainter(pm)
    for i, v in enumerate(values):
        pop._render(v)
        ox = pad + i * (box.width() + pad) - box.x()
        for win, opacity in ((t, 1.0), (pop, v)):
            wpm = QPixmap(win.size()); wpm.fill(QColor(0, 0, 0, 0))
            win.render(wpm)
            p.setOpacity(opacity)
            p.drawPixmap(ox + win.x(), pad + win.y() - box.y(), wpm)
    p.end()
    pm.save(str(OUT / f"{name}.png"))


def main():
    app = QApplication.instance() or QApplication([])
    seed_fonts()
    from ui.tray import TonyTray

    t = TonyTray()
    t.show()   # offscreen platform — no real window; show_response is a no-op while hidden
    # the popup fades in over 280ms and the pill cross-fades over ~320ms; a static
    # PNG wants the settled frame, so snap instead of catching a tween.
    t._popup._reduce_motion = True
    t._reduce_motion = True

    for state in ("idle", "listening"):     # the only two the pill can look like
        t.set_state(state)
        # park the breath on its peak — a still of a mid-tween glow tells you nothing
        # about how loud the animation actually gets.
        t._breath = 1.0
        t._apply_liveness(t._live)
        app.processEvents()
        shot(t, f"tray_{state}")

    # ...and the frame that is actually being judged: halfway through the fade.
    t._breath = 0.5
    t._apply_liveness(0.5)
    app.processEvents()
    shot(t, "tray_fade_50")
    t._breath = 1.0; t._apply_liveness(1.0)   # back to lit for the popup shots

    t.set_state("executed")
    t.show_response("increased volume by 10%")
    app.processEvents()
    shot(t, "tray_response", overlay=t._popup)
    t._popup.hide()

    t.set_state("no_match")
    t.show_response("didn't catch that", ok=False)
    app.processEvents()
    shot(t, "tray_no_match", overlay=t._popup)

    # ...and the part a still cannot show: the popup coming out of the pill and going
    # back into it, sampled ON ITS OWN EASING (quarter-points of the timeline, not of
    # the opacity) so the strip shows where the motion actually spends its time.
    from PySide6.QtCore import QEasingCurve
    from ui.tray import _POP_IN_MS, _POP_OUT_MS
    t.set_state("executed")
    t.show_response("increased volume by 10%")
    quarters = (0.0, 0.25, 0.5, 0.75, 1.0)
    ease_in = QEasingCurve(QEasingCurve.OutCubic)
    ease_out = QEasingCurve(QEasingCurve.InOutSine)
    motion_strip(t, f"popup_enter_{_POP_IN_MS}ms",
                 [ease_in.valueForProgress(q) for q in quarters])
    motion_strip(t, f"popup_exit_{_POP_OUT_MS}ms",
                 [1.0 - ease_out.valueForProgress(q) for q in quarters])
    t._popup.hide()

    # the panel, drawn WITH the pill: it hangs off it, so reviewing it alone tells
    # you nothing about whether the two read as one object.
    t.set_state("idle")
    t._popup.hide()
    from ui.info_window import InfoWindow
    w = InfoWindow(on_turn_off=lambda: None)
    w.present()
    app.processEvents()
    shot(t, "panel", overlay=w)
    bar = w.findChild(QScrollArea).verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    app.processEvents()
    shot(t, "panel_scrolled", overlay=w)

    print("wrote:", *(p.name for p in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
