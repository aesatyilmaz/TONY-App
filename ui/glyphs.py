"""The parts of the design QSS cannot express, painted by hand.

Gradient-filled text (`-webkit-background-clip:text`), an inset top highlight
(`inset 0 1px 0 rgba(255,255,255,.5)`) and the popup's caret have no QSS
equivalent — each gets a small paintEvent instead.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QLinearGradient, QPen, QBrush, QPainterPath, QImage, QPixmap,
    QGuiApplication,
)
from PySide6.QtWidgets import QWidget

from ui import tokens

CARET = 6  # popup caret height (design §4.4)

# The transparent gutter every glass surface carries AROUND its glass, and the only
# place its shadow may reach. Every glass top-level is WA_TranslucentBackground, i.e.
# a Windows layered window, and anything painted past the window rect is a composite
# that disagrees with itself. The gutter belongs to the SURFACE, so "outside the
# window" and "outside the widget" are the same edge — and set_shadow() clamps to it.
MARGIN = 24


class GlassSurface(QWidget):
    """The one glass object the pill, the popup and the panel share (design §1):
    near-opaque cream fill, gold hairline, the inset top highlight that sells it as
    glass — and its own shadow. THE WIDGET IS BIGGER THAN THE GLASS: `pad` px of
    transparent gutter all round, which is what the shadow is painted into.

    The shadow is PAINTED, and deliberately not a QGraphicsDropShadowEffect. An
    effect makes Qt render the widget through an offscreen surface and composite the
    result back; on a layered top-level that composite is where the founder's black
    rectangle came from — three times, on three unrelated triggers, always on a
    widget wearing an effect. Strokes go into the widget's own surface: no offscreen
    buffer, no cached effect pixmap, nothing for the composite to disagree with."""

    def __init__(self, radius: int = 22, caret: bool = False,
                 pad: int = MARGIN, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._caret = caret
        self._pad = pad
        self._box = None          # set_glass_box(): the reveal animation's rect
        self._fill = QColor(*tokens.GLASS_RGBA)
        self._stroke = QColor(*tokens.STROKE_RGBA)
        self._stroke_w = 1.0
        self._shadow = QColor(0, 0, 0, 0)
        self._shadow_dy = 0.0
        self._shadow_r = 0.0

    def set_radius(self, radius: int) -> None:
        """The pill is a stadium (radius 999); carrying a camera view it is a rounded
        rectangle. Same surface either way — one glass object, two shapes."""
        if radius != self._radius:
            self._radius = radius
            self.update()

    def set_glass_box(self, box: QRectF | None) -> None:
        """Paint the glass at `box` (widget coordinates) instead of filling the whole
        widget minus its gutter. None restores the default.

        This is how the pill opens into the vision mode panel. The WINDOW is at its final
        size from the first frame and never moves; only the painted glass grows. The
        other way — resizing the window per frame — is a SetWindowPos on a layered
        topmost window sixty times a second, which is the exact call pattern that
        wedged the GUI thread once already (see ui/tray.py's popup note). Repaint per
        frame, never re-geometry.
        """
        self._box = QRectF(box) if box is not None else None
        self.update()

    def glass_rect(self) -> QRectF:
        """The VISIBLE glass — the widget minus its shadow gutter, or wherever
        set_glass_box() has put it. Everything else here derives from this one rect,
        so animating it moves the fill, the ring, the highlight and the shadow
        together and none of them can drift apart mid-reveal."""
        if self._box is not None:
            return QRectF(self._box)
        return QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)

    def set_tone(self, fill, stroke, width: float = 1.0) -> None:
        """`width` is the ring weight. The path insets by width/2 so a thick ring
        grows INWARD — it never paints past the glass and never eats the gutter."""
        self._fill, self._stroke = QColor(*fill), QColor(*stroke)
        self._stroke_w = width
        self.update()

    def set_shadow(self, color, dy: float = 0.0, reach: float = 0.0) -> None:
        """`reach` = how far past the glass the shadow fades out, `dy` = how far it is
        pushed down. Clamped to what the gutter holds (-1 for the outermost stroke's
        own width), so no caller can paint outside the widget however it tunes."""
        self._shadow = QColor(*color)
        self._shadow_dy = dy
        self._shadow_r = max(0.0, min(reach, self._pad - abs(dy) - 1))
        self.update()

    def _shape(self, inset: float, caret: bool = True) -> QPainterPath:
        """The glass silhouette, inset by `inset` px — negative grows it outwards,
        which is how the shadow rings are built. `caret=False` drops the caret
        triangle: the shadow rings skip it (a united() per ring is the one expensive
        thing here, and a 6px spur under an offset shadow shows nothing)."""
        r = self.glass_rect().adjusted(inset, inset, -inset, -inset)
        if self._caret:
            r.setTop(r.top() + CARET)
        rad = max(0.0, min(self._radius - inset, r.height() / 2))
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        if self._caret and caret:  # small up-pointing caret, centred on the top edge
            cx = r.center().x()
            tip = QPainterPath()
            tip.moveTo(cx - CARET, r.top() + 0.5)
            tip.lineTo(cx, r.top() - CARET + 0.5)
            tip.lineTo(cx + CARET, r.top() + 0.5)
            tip.closeSubpath()
            path = path.united(tip)
        return path

    def _paint_shadow(self, p: QPainter) -> None:
        """One 2px stroke per pixel of reach, growing outwards, alpha falling as
        (1-t)**3. Cubic, not linear: a linear ramp reads as a flat halo with a visible
        outer edge, while cubed the ink sits in the first few pixels off the glass and
        the tail dies away — which is what a blur looks like. 2px strokes at 1px
        spacing cover every pixel about twice; that doubling is priced into the alphas
        callers pass."""
        r = self._shadow_r
        if r < 1 or self._shadow.alpha() == 0:
            return
        p.save()
        p.translate(0.0, self._shadow_dy)
        c = QColor(self._shadow)
        a = self._shadow.alphaF()
        for i in range(int(r), 0, -1):
            c.setAlphaF(a * (1.0 - i / r) ** 3)
            p.strokePath(self._shape(-i, caret=False), QPen(c, 2.0))
        p.restore()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_shadow(p)
        path = self._shape(self._stroke_w / 2)
        p.fillPath(path, self._fill)
        # inset top highlight: stroke the path 1px in, clipped to its upper half
        p.save()
        top = self.glass_rect()
        top.setHeight(top.height() / 2)
        p.setClipRect(top)
        p.strokePath(self._shape(1.5 * self._stroke_w), QPen(QColor(255, 255, 255, 165), 1))
        p.restore()
        p.strokePath(path, QPen(self._stroke, self._stroke_w))


_WORDMARK = Path(__file__).resolve().parent / "assets" / "tony-wordmark.png"


def _mask_fill(mask: QImage, brush) -> QImage:
    """Recolour an alpha-mask image with `brush`, keeping its alpha."""
    out = QImage(mask.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.fillRect(out.rect(), brush)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(0, 0, mask)
    p.end()
    return out


class Wordmark(QWidget):
    """The real TONY wordmark artwork (ui/assets/), gold-tinted through its own
    alpha and sat on a 1px white shadow for the engraved look (design §2).

    Beats type-setting the word: the artwork *is* the brand's letterforms, and it
    sidesteps the missing-Cinzel-Decorative problem for the one element that
    mattered most. Tinting keeps it on-palette — the source art is black."""

    MUTED_OPACITY = 0.34   # liveness 0: the letterforms wash out into the glass

    def __init__(self, height: int = 22, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._live = 1.0
        dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        mask = QImage(str(_WORDMARK)).convertToFormat(QImage.Format_ARGB32) \
            .scaledToHeight(max(1, round(height * dpr)), Qt.SmoothTransformation)

        g = QLinearGradient(QPointF(0, 0), QPointF(0, mask.height()))
        g.setColorAt(0.0, QColor(tokens.GOLD_LITE))
        g.setColorAt(0.55, QColor(tokens.GOLD))
        g.setColorAt(1.0, QColor(tokens.GOLD_DEEP))
        self._ink = QPixmap.fromImage(_mask_fill(mask, QBrush(g)))
        self._lift = QPixmap.fromImage(_mask_fill(mask, QColor(255, 255, 255, 190)))
        for pm in (self._ink, self._lift):
            pm.setDevicePixelRatio(dpr)
        self.setFixedSize(round(mask.width() / dpr), height)

    def set_liveness(self, v: float) -> None:
        """0 = asleep (washed out, flat), 1 = lit. Continuous, so the mark can be
        cross-faded with the rest of the pill instead of switching."""
        v = min(1.0, max(0.0, float(v)))
        if v == self._live:
            return
        self._live = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # The engraved white lift is what makes the mark sit UP off the glass, so it
        # fades in with liveness: the mark RISES out of the glass instead of flipping
        # from flat to raised. At liveness 0 it contributes nothing (old muted look).
        if self._live:
            p.setOpacity(self._live)
            p.drawPixmap(0, 1, self._lift)
        p.setOpacity(self.MUTED_OPACITY + (1.0 - self.MUTED_OPACITY) * self._live)
        p.drawPixmap(0, 0, self._ink)


class Tick(QWidget):
    """The popup's gold ✓ — drawn, because the character is missing from the
    vintage serif faces and Qt's per-glyph fallback drops it into a mismatched sans."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(tokens.GOLD_DEEP), 2)
        pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(1.5, 6.5), QPointF(4.5, 9.5), QPointF(10.5, 2.5)])
