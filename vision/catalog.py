"""What the gestures are, as plain data.

Lives apart from gesture.py on purpose: TONY's UI shows this list, and importing
gesture.py to read it would drag OpenCV and MediaPipe into the UI process for the
sake of a few strings. Nothing here imports anything.

Grouped the same way commands.grouped() groups voice commands, so the panel that
shows them can be the same panel.
"""
from __future__ import annotations

# (group, [(gesture, what it does)])
#
# Terse on purpose. This is a card you glance at with one hand in the air, not
# documentation — the gesture and the word for what it does, nothing else. The
# group name carries the context that would otherwise need a clause (the same
# open-palm swipe means "previous window" under Windows and "back" under Browser).
GESTURES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Pointer", (
        ("Index finger", "Move cursor"),
        ("Peace sign", "Click"),
    )),
    ("Faders", (
        ("Left track", "Volume"),
        ("Right track", "Scroll"),
    )),
    ("Windows", (
        ("OK sign, 1s", "Window switcher"),
        ("Open palm ← →", "Previous / next"),
        ("Both hands still, 2s", "Confirm"),
    )),
    ("Browser", (
        ("Open palm ← →", "Back / forward"),
    )),
    ("Vision mode", (
        ("Fist, 1s", "Sleep / wake"),
        ('Say "close vision"', "Quit"),
    )),
)


def count() -> int:
    return sum(len(rows) for _, rows in GESTURES)
