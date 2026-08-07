"""Render vision mode's HUD to PNGs — no camera, no cursor, no key events.

The camera is on the founder's live desktop, so nobody gets to "just run it and
look". This paints every HUD state onto a synthetic frame with a synthetic hand,
exactly the way tools/render_ui.py does for TONY's overlay.

    python tools/render_vision.py [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision import gesture as g  # noqa: E402

W, H = 640, 480

# A hand-ish set of 21 normalized points in MediaPipe's landmark order: wrist, thumb,
# then index through pinky. hand_at() reduces it to what the HUD actually consumes.
_HAND = [
    (0.50, 0.72),
    (0.44, 0.68), (0.40, 0.62), (0.38, 0.56), (0.36, 0.51),
    (0.47, 0.56), (0.46, 0.47), (0.455, 0.41), (0.45, 0.36),
    (0.51, 0.55), (0.51, 0.45), (0.51, 0.385), (0.51, 0.33),
    (0.55, 0.56), (0.56, 0.47), (0.565, 0.41), (0.57, 0.36),
    (0.59, 0.58), (0.61, 0.51), (0.62, 0.46), (0.63, 0.42),
]


def backdrop() -> np.ndarray:
    """Something camera-like to draw over: a soft vignette plus sensor grain, so the
    HUD's translucency is judged against texture rather than flat black."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.hypot(xx - W / 2, yy - H / 2) / np.hypot(W / 2, H / 2)
    base = (62 * (1.0 - 0.75 * r))[..., None] * np.array([1.15, 1.0, 0.9], np.float32)
    grain = np.random.default_rng(7).normal(0, 4, (H, W, 1))
    return np.clip(base + grain, 0, 255).astype(np.uint8)


def hand_at(dx: float = 0.0, dy: float = 0.0):
    """What the loop hands the HUD per hand: (palm centre, wrist→knuckle span).
    Derived from the landmark set rather than hard-coded, so the two stay honest."""
    pts = [(x + dx, y + dy) for x, y in _HAND]
    palm = [pts[i] for i in (0, 5, 9, 13, 17)]
    centre = (sum(p[0] for p in palm) / 5, sum(p[1] for p in palm) / 5)
    span = np.hypot(pts[9][0] - pts[0][0], pts[9][1] - pts[0][1])
    return centre, float(span)


def scene(name: str, **state):
    """Build a controller in a given state and paint one frame of it."""
    v = g.VisionController()
    v.__dict__.update({k: val for k, val in state.items() if not k.startswith("_")})
    # The "V standby · Q quit" hint only exists in standalone console mode — run()
    # clears it when the HUD is drawn into TONY's pill, where there is no window to
    # press keys at. Painting it here would put a key hint in every review shot for a
    # mode that has no keys.
    v._hint = state.get("hint", "")
    frame = backdrop()
    v._draw_hud(frame, state.get("_label", ""), 1000.0)
    return name, frame


def scroll_lock(last_y: float, countdown: float) -> g._Lock:
    lock = g._Lock()
    lock.locked, lock.last_y, lock.countdown = True, last_y, countdown
    return lock


def swipe_trail(now: float):
    """A quarter-circle of pointer samples, oldest first — enough for the comet."""
    import math
    return [(0.55 + 0.13 * math.cos(a), 0.50 - 0.13 * math.sin(a),
             now - (1 - i / 14) * 0.35, 1.4)
            for i, a in enumerate(np.linspace(3.4, 1.4, 15))]


def build_scenes():
    """Every HUD state, painted. tests/test_vision.py runs this as a paint gate."""
    now = 1000.0
    return [
        scene("1-standby", active=False, fps=28.4),
        scene("2-active-idle", hands_seen=[hand_at()], last_palm=(0.50, 0.55),
              vol_level=45, fps=28.4),
        scene("3-volume-engaged", hands_seen=[hand_at(-0.40, -0.05)],
              last_palm=(g.FADER_X_VOL, 0.45), vol_last_y=0.45, vol_level=72,
              fps=27.9, _label="VOL UP"),
        scene("4-scroll-locked", hands_seen=[hand_at(0.38, 0.02)],
              last_palm=(g.FADER_X_SCR, 0.58), vol_level=45, fps=27.1,
              scr=scroll_lock(0.58, now + 1.8), _label="SCROLL DOWN"),
        scene("5-ok-hold", hands_seen=[hand_at(0.0, -0.02)], last_palm=(0.50, 0.53),
              ok_hold_start=now - 0.6, vol_level=45, fps=28.0,
              _label="OK 0.6s / 1.0s"),
        scene("7-standby-waking", active=False, hands_seen=[hand_at()],
              fist_start=now - 1.2, fps=28.1),
        scene("6-pointer-trail", hands_seen=[hand_at(0.05, -0.06)], mouse_mode=True,
              last_palm=(0.55, 0.47), vol_level=45, fps=29.2,
              trail=swipe_trail(now), _label="MOUSE MODE"),
    ]


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    scenes = build_scenes()
    for name, frame in scenes:
        cv2.imwrite(str(out / f"{name}.png"), frame)
        print(f"  {name}.png")
    print(f"\n{len(scenes)} frames -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "renders")
