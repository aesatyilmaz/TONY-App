"""FrameView — the vision mode camera picture, painted inside TONY's glass.

Two jobs, both small: hold the newest frame alive, and draw it with the same
rounded corners and gold hairline as everything else TONY paints. A square video
pasted into a rounded panel reads as a screenshot of another program.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ui import tokens
from vision import frames

RADIUS = 10


class FrameView(QWidget):
    """Holding the numpy array alive matters: QImage does not copy the buffer it is
    handed, so a temporary would be freed out from under the painter."""

    def __init__(self, width: int, height: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._frame = None
        self._alpha = 1.0

    def set_frame(self, frame) -> None:
        self._frame = frame
        self.update()

    def detach(self) -> None:
        """Take a private copy of the current frame, because the buffer behind it is
        about to go.

        What arrives here is a numpy VIEW into vision mode's shared memory — that is the
        whole point, no copy per frame. But the closing animation keeps painting for
        another quarter of a second after vision mode stops, and painting through an
        unmapped pointer is an access violation: the process dies where it stands,
        with no traceback and nothing in tony.log. One copy, once, at shutdown.
        """
        if self._frame is not None:
            self._frame = self._frame.copy()

    def set_alpha(self, a: float) -> None:
        """Fade, painted by the widget itself. NOT a QGraphicsOpacityEffect: an effect
        renders the widget through an offscreen surface and composites it back, and on
        this app's layered windows that composite is where the black rectangle came
        from. One setOpacity call has no such surface."""
        a = min(1.0, max(0.0, a))
        if a != self._alpha:
            self._alpha = a
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setOpacity(self._alpha)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())

        clip = QPainterPath()
        clip.addRoundedRect(rect, RADIUS, RADIUS)
        p.setClipPath(clip)

        if self._frame is None:
            p.fillRect(rect, QColor(tokens.BEIGE))
        else:
            # Format_BGR888 reads OpenCV's byte order directly. Swapping channels
            # would be a full-frame copy, thirty times a second, for nothing.
            p.drawImage(rect, QImage(self._frame.data, frames.W, frames.H,
                                     frames.W * 3, QImage.Format_BGR888))

        p.setClipping(False)
        pen = QPen(QColor(tokens.GOLD))      # setters, never QPen(colour, cap=...):
        pen.setWidth(1)                      # that keyword form is a hard crash
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
