"""InfoWindow — the reference card that drops out of the pill.

Not a window in the taskbar sense any more: clicking the pill opens this directly
underneath it, like a menu off a button. Same cream glass, same gold hairline, a
caret pointing back up at the pill — one object, not two.

IT IS NOT A Qt.Popup ANY MORE, and that is the point. A popup takes an
application-wide mouse AND keyboard grab the moment it shows, and calls
activateWindow() — while the pill it hangs off is WS_EX_NOACTIVATE and cannot hold
focus. A grab whose activation does not land where Qt expects is a grab that can
outlive the window that took it, and an input grab nobody releases is a GUI thread
that answers nothing: the founder's report was a command that did not run, THEN a
click on the pill that painted a black rectangle. The rectangle was the stale
surface of a window that had already stopped pumping.

So the two behaviours the popup gave us for free are re-implemented by hand, both
out of things that cannot wedge:
  click-away  →  changeEvent(ActivationChange): the panel closes when it loses
                 activation. No grab, and if activation never arrives the worst
                 case is a panel that waits for the next click on the pill.
  Esc         →  keyPressEvent. Six lines, no window class semantics involved.
Qt.Tool keeps it out of the taskbar and out of alt-tab, which is the only other
thing Qt.Popup was buying.

Read-only by design (founder: "eklemeli çıkarmalı değil, sadece info şeklinde") —
no inputs, no add/remove, no click-to-run. One control only, at the very top:
Turn off TONY.

The list is one row per GROUP (commands.grouped), not one per command: 16 rows
instead of 52, related phrases sharing a row (founder: "undo-redo falan tek bi
tane"). Every trigger phrase is still printed — a reference card that hides half
the vocabulary is a shorter list that is worth less.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QHBoxLayout,
    QApplication,
)

from ui import tokens
from ui.glyphs import GlassSurface, CARET, MARGIN
from ui.stats import StatsStrip
from ui.tray import pill_rect, vision_mode, DROP
from commands import build_commands, grouped
from vision import catalog

# BROWN_SOFT is only 3.8:1 on cream — too light for 12px trigger text. This is the
# same hue two steps darker: 5.5:1, still clearly secondary to the group name.
_MUTED = "#6F5A44"
_NAME_COL = 88    # the alignment column: every group name starts on the same x.
                  # 88 = the widest label ("Screenshot", 63px) + a 25px gutter, so the
                  # phrases stay close enough to the label to read as belonging to it.
_PANEL_W = 560
_PANEL_H = 700    # capped to what fits under the pill on the actual screen
_SHADOW_DY = 8

# Nothing here may paint an opaque background: the panel is a translucent
# top-level and the GlassSurface *is* the background. A child with a solid fill
# would square off the rounded corners and cover the caret.
_QSS = f"""
QWidget {{ color: {tokens.BROWN}; background: transparent; }}
#header {{ border-bottom: 1px solid {tokens.STROKE_GOLD}; }}
#row {{ border-bottom: 1px solid rgba(201,162,39,0.20); }}
QScrollArea, #list, QScrollArea > QWidget > QWidget {{ border: none; background: transparent; }}
QPushButton#off {{
    color: {tokens.CLAY};
    background: rgba(160,90,60,0.07);
    border: 1px solid rgba(160,90,60,0.55);
    border-radius: 7px;
    padding: 7px 16px;
}}
QPushButton#off:hover  {{ background: {tokens.CLAY}; color: {tokens.WHITE};
                          border-color: {tokens.CLAY}; }}
QPushButton#off:pressed {{ background: #8A4A30; color: {tokens.WHITE}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(201,162,39,0.45); border-radius: 5px;
                               min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(201,162,39,0.70); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


class _Line:
    """A gesture row, shaped like a Command so _row() can draw either without
    knowing which it has. The gesture reads in full contrast and what it does sits
    muted behind it — exactly the relationship a command's main phrase has to its
    alternates."""

    def __init__(self, gesture: str, does: str):
        self.triggers = (gesture, does)


def _row(label: str, cmds) -> QFrame:
    """One group = one row. Inside it, one line per command: the phrase to say in
    full contrast, its alternates muted behind it. Flattening a whole group into a
    single paragraph would be shorter still — and would lose which phrase turns the
    volume UP."""
    w = QFrame(); w.setObjectName("row")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(22, 9, 22, 9); lay.setSpacing(14)

    name = QLabel(label)
    # No tracking: Constantia's kerning fights QFont.AbsoluteSpacing on lowercase
    # pairs and blows a visible hole into "Scroll" / "Screenshot". Tracking stays
    # where it earns its keep — the all-caps label in the header.
    name.setFont(tokens.font("title", 13))
    name.setFixedWidth(_NAME_COL)
    name.setAlignment(Qt.AlignLeft | Qt.AlignTop)

    lines = []
    for c in cmds:
        line = c.triggers[0]
        if len(c.triggers) > 1:
            line += f"<span style='color:{_MUTED}'> · " + " · ".join(c.triggers[1:]) + "</span>"
        lines.append(line)
    trig = QLabel("<br>".join(lines))
    trig.setFont(tokens.font("body", 12))
    trig.setWordWrap(True)
    trig.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    trig.setTextInteractionFlags(Qt.TextSelectableByMouse)  # read-only, still copyable

    lay.addWidget(name); lay.addWidget(trig, 1)
    return w


class InfoWindow(QWidget):
    """`InfoWindow(on_turn_off)` — on_turn_off() is called when the button is
    pressed. The panel does not shut anything down itself; app.py owns that."""

    def __init__(self, on_turn_off, parent=None):
        super().__init__(parent)
        self._on_turn_off = on_turn_off
        self._hidden_at = 0.0
        self._was_active = False
        # Qt.Tool, NOT Qt.Popup: out of the taskbar and out of alt-tab, with no input
        # grab. Not WindowStaysOnTopHint either — a panel that both floats above
        # everything and (in the worst case) missed its activation would be a panel
        # sitting in the founder's way; while it IS active it is on top anyway.
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(_QSS)

        # the same glass the pill is made of — it carries its own MARGIN gutter, so
        # its shadow paints inside this window instead of past it (see glyphs.MARGIN)
        # — with the caret aimed back up at the pill.
        self._surface = GlassSurface(radius=16, caret=True, parent=self)
        self._surface.set_shadow((60, 45, 30, 95), dy=_SHADOW_DY, reach=15)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._surface)

        root = QVBoxLayout(self._surface)
        root.setContentsMargins(MARGIN, CARET + MARGIN, MARGIN, MARGIN)
        root.setSpacing(0)
        self._head = self._header()
        self._area = self._commands()
        root.addWidget(self._head)
        root.addWidget(self._area, 1)

    # ------------------------------------------------------------- parts --
    def _header(self) -> QFrame:
        head = QFrame(); head.setObjectName("header")
        outer = QVBoxLayout(head)
        outer.setContentsMargins(22, 12, 22, 10); outer.setSpacing(7)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(16)

        # No wordmark here: the pill is 8px above this line, already wearing it.
        # Repeating it would say twice what the panel hanging off the pill says once.
        self._count = QLabel("")
        self._count.setFont(tokens.font("title", 10, tracking=1.6))
        self._count.setStyleSheet(f"color: {_MUTED};")

        self.turn_off_button = QPushButton("Turn off TONY")
        self.turn_off_button.setObjectName("off")
        self.turn_off_button.setFont(tokens.font("title", 12, tracking=1.0))
        self.turn_off_button.setCursor(Qt.PointingHandCursor)
        self.turn_off_button.clicked.connect(lambda: self._on_turn_off())

        lay.addWidget(self._count, 0, Qt.AlignVCenter); lay.addStretch(1)
        lay.addWidget(self.turn_off_button, 0, Qt.AlignVCenter)
        outer.addLayout(lay)

        # Under the button, as the founder asked. It only ticks while this panel is
        # up — see StatsStrip.
        self.stats = StatsStrip()
        outer.addWidget(self.stats)      # fills the row; its TEXT is right-aligned
        return head

    def _commands(self) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.viewport().setAutoFillBackground(False)   # let the glass show through
        self._pages = {}
        return area

    def _page(self, gestures: bool) -> QWidget:
        """The list, built once per mode and kept. Both modes are the same object in
        the same place — while vision mode is running, the voice list is the wrong
        reference card to be holding."""
        if gestures in self._pages:
            return self._pages[gestures]
        if gestures:
            groups = [(label, [_Line(g, what) for g, what in rows])
                      for label, rows in catalog.GESTURES]
        else:
            groups = grouped(build_commands())

        inner = QWidget(); inner.setObjectName("list")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        for label, group in groups:
            lay.addWidget(_row(label, group))
        lay.addStretch(1)
        self._pages[gestures] = inner
        return inner

    # -------------------------------------------------------------- api --
    def present(self) -> None:
        """Drop the panel open under the pill — and the pill's toggle.

        The toggle is now explicit. As a Qt.Popup it was implicit and clever: the
        click on the pill was the click that dismissed the popup, Qt replayed that
        press onto the pill underneath, and the 250ms guard swallowed the re-open.
        The pill is WS_EX_NOACTIVATE, so clicking it does NOT take activation away
        from this panel any more — nothing dismisses it on the way in, and without a
        branch here the founder's second click would do visibly nothing. Which is
        exactly what "TONY froze" looks like from the outside.

        The guard stays: it costs one comparison and it still covers the case where
        something else did dismiss us microseconds before the click arrives."""
        if self.isVisible():
            self.hide()
            return
        if time.monotonic() - self._hidden_at < 0.25:
            return

        gestures = vision_mode()
        # takeWidget() first: setWidget() takes ownership and DELETES whatever was
        # there, so swapping back to a kept page would hand Qt a destroyed object.
        self._area.takeWidget()
        self._area.setWidget(self._page(gestures))
        self._count.setText(f"{catalog.count()} GESTURES" if gestures
                            else f"{len(build_commands())} VOICE COMMANDS")

        anchor = pill_rect()
        avail = QGuiApplication.primaryScreen().availableGeometry()
        top = anchor.bottom() + DROP - MARGIN     # caret tip sits DROP under the pill
        # Fit the content, then cap. The two cards are very different lengths — 16
        # command groups against 5 gesture groups — and a fixed height left the short
        # one as a third of a card followed by empty cream.
        #
        # heightForWidth, not sizeHint: every row wraps its text, and a wrapping
        # label's sizeHint is measured at its own natural width, not the width it
        # will actually get. It came out ~100px too tall, which is exactly the blank
        # this is here to remove.
        page = self._area.widget()
        body = page.heightForWidth(_PANEL_W)
        if body <= 0:
            body = page.sizeHint().height()
        wanted = self._head.sizeHint().height() + body + CARET + MARGIN
        h = min(_PANEL_H, wanted, avail.bottom() - top - MARGIN)
        self.resize(_PANEL_W + 2 * MARGIN, h + 2 * MARGIN)
        self.move(anchor.center().x() - self.width() // 2, top)
        self._was_active = False       # arm the click-away only once it HAS focus
        self.stats.start()      # hardware polling, only while it is looked at
        self.show()
        self.raise_()
        # Esc and the click-away both need focus, and the pill never takes it. The
        # click that opened this panel was delivered to our process, which is what
        # earns us SetForegroundWindow — so this normally lands. If Windows refuses
        # it, nothing breaks: the panel just waits for the next click on the pill.
        self.activateWindow()
        self._nudge()

    def changeEvent(self, e):
        """Click-away, without a grab: the founder clicked something else, so that
        something else took the foreground and we lost activation. Only armed after
        activation has actually arrived — a show() that never got focus must not
        read its own missing activation as a dismissal and hide instantly."""
        if e.type() == QEvent.ActivationChange and self.isVisible():
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active:
                self.hide()
        super().changeEvent(e)

    def keyPressEvent(self, e):
        """Esc closes it. QWidget::keyPressEvent only does this for popups, and this
        is not one any more."""
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    def _nudge(self) -> None:
        """Repaint whatever else is on screen. Opening and closing this panel moves
        the foreground on and off the pill underneath — a window-state change nothing
        else tells the pill about, on exactly the click the founder saw go black. One
        repaint each way is cheaper than reasoning about whose composite is stale."""
        for w in QApplication.topLevelWidgets():
            if w is not self and w.isVisible():
                w.update()

    def hideEvent(self, e):
        """Leave nothing behind: this is a layered window, and a composite that
        fails on the way out leaves its last frame burned onto the screen."""
        self.stats.stop()
        self._hidden_at = time.monotonic()
        self.update()
        self._nudge()
        super().hideEvent(e)
