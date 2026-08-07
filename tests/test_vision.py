"""Vision mode's logic and HUD — no camera, no key events, no cursor moved.

The camera is on the founder's live desktop, so none of this may touch it. The hand
model is built in run(), not __init__, so VisionController is free to construct here.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision import gesture as g  # noqa: E402


def test_the_faders_only_claim_their_own_tracks():
    mid = (g.FADER_TOP + g.FADER_BOT) / 2
    assert g.zone_at(g.FADER_X_VOL, mid) == "vol"
    assert g.zone_at(g.FADER_X_SCR, mid) == "scroll"
    assert g.zone_at(0.5, mid) is None                    # the middle is gesture space
    assert g.zone_at(g.FADER_X_VOL, g.FADER_TOP - 0.05) is None   # above the track
    assert g.zone_at(g.FADER_X_VOL, g.FADER_BOT + 0.05) is None   # below it
    assert g.zone_at(g.FADER_X_VOL + g.FADER_HALF_W + 0.01, mid) is None


def _buf(points):
    return [(x, y, 0.0) for x, y in points]


def test_swipe_needs_the_threshold_and_enough_frames():
    far = _buf([(0.1 + i * 0.05, 0.5) for i in range(10)])
    assert g.calc_swipe(far, g.SWIPE_THRESHOLD)[0] == "right"
    assert g.calc_swipe(far[:4], g.SWIPE_THRESHOLD)[0] == "none"   # too few frames
    near = _buf([(0.5 + i * 0.001, 0.5) for i in range(10)])
    assert g.calc_swipe(near, g.SWIPE_THRESHOLD)[0] == "none"      # below threshold


def test_a_hand_dropping_out_of_frame_is_not_a_side_swipe():
    """Vertical must win over horizontal, or every hand leaving the frame fires
    browser back/forward."""
    diagonal = _buf([(0.3 + i * 0.02, 0.2 + i * 0.06) for i in range(10)])
    assert g.calc_swipe(diagonal, g.SWIPE_THRESHOLD)[0] == "down"


def test_cursor_mapping_clamps_to_the_screen():
    assert g.cam_to_screen(0.0, 0.0) == (g.SCREEN_X, g.SCREEN_Y)
    assert g.cam_to_screen(1.0, 1.0) == (g.SCREEN_X + g.SCREEN_W, g.SCREEN_Y + g.SCREEN_H)
    mid_x, mid_y = g.cam_to_screen(0.5, 0.5)
    assert mid_x == g.SCREEN_X + g.SCREEN_W // 2


def test_drag_speed_stays_inside_its_bounds():
    for v in (0.0001, 0.02, 5.0):
        assert g.VOL_PCT_MIN <= g.volume_step(v) <= g.VOL_PCT_MAX
        assert g.SCROLL_MIN <= g.scroll_step(v) <= g.SCROLL_MAX
    assert g.volume_step(-0.02) == g.volume_step(0.02)      # direction is the caller's job
    assert g.scroll_step(-1.0) == g.scroll_step(1.0)


def test_scrolling_faster_actually_scrolls_further():
    """The founder's ask: a slow drag nudges, a fast flick throws. The old version
    took per-frame displacement, so the answer also depended on the frame rate."""
    slow, medium, fast = (g.scroll_step(v) for v in (0.1, 0.5, 1.5))
    assert slow < medium < fast
    assert medium * 2 < fast, "the curve is too flat to feel different"
    assert fast == g.SCROLL_MAX                            # past SCROLL_FAST it saturates


def test_a_zone_drag_ignores_the_first_frame_and_small_jitter():
    drag = g.VisionController._drag_delta
    y, delta = drag(None, 0.5, g.VOL_MOVE_THRESH)
    assert (y, delta) == (0.5, None)                      # first frame only anchors
    y, delta = drag(y, 0.5001, g.VOL_MOVE_THRESH)
    assert delta is None                                  # jitter is a dead zone
    y, delta = drag(y, 0.6, g.VOL_MOVE_THRESH)
    assert delta is not None and delta > 0


def test_the_cursor_filter_smooths_jitter_but_still_follows_a_real_move():
    """One Euro's whole point: heavy on a still hand, light on a moving one. A fixed
    average can't do both, which is what made pointing feel rough."""
    f = g.OneEuro(g.MOUSE_MIN_CUTOFF, g.MOUSE_BETA)
    f(0.5, 0.0)
    jittery = [f(0.5 + (0.004 if i % 2 else -0.004), i / 30) for i in range(1, 31)]
    assert max(abs(v - 0.5) for v in jittery) < 0.004      # shiver is damped

    f.reset()
    f(0.2, 0.0)
    for i in range(1, 16):                                 # half a second of real travel
        out = f(0.2 + i * 0.04, i / 30)
    assert out > 0.6                                       # and it keeps up (target 0.8)


class _P:
    def __init__(self, x, y): self.x, self.y, self.z = x, y, 0.0


def hand(*extended: str):
    """21 landmarks in MediaPipe order with the named fingers extended and the rest
    curled toward the wrist. Enough for the shape predicates, which is all they read."""
    pts = {i: _P(0.5, 0.90) for i in range(21)}      # unused joints sit on the wrist
    pts[4] = _P(0.30, 0.75)                          # thumb tip, clear of the index
    for name, mcp, pip, tip, x in (("index", 5, 6, 8, 0.44), ("middle", 9, 10, 12, 0.50),
                                   ("ring", 13, 14, 16, 0.56), ("pinky", 17, 18, 20, 0.62)):
        pts[mcp] = _P(x, 0.60)
        pts[pip] = _P(x, 0.50)
        pts[tip] = _P(x, 0.35 if name in extended else 0.72)
    return [pts[i] for i in range(21)]


def test_the_shape_predicates_do_not_overlap():
    """Each hand shape selects exactly one mode, so no shape may satisfy two — the
    moment one does, that gesture starts stealing another's frames."""
    shapes = {
        "palm":  (hand("index", "middle", "ring", "pinky"), g.is_open_palm),
        "point": (hand("index"),                            g.is_index_only),
        "peace": (hand("index", "middle"),                  g.is_peace),
        "fist":  (hand(),                                   g.is_fist),
    }
    for name, (lm, own) in shapes.items():
        assert own(lm), f"{name} does not match its own predicate"
        for other, (_, pred) in shapes.items():
            if other != name:
                assert not pred(lm), f"{name} also reads as {other}"


def test_the_waking_fist_is_read_in_either_state():
    """The founder's question: can it still see my hand in standby? It must —
    _check_fist never consults self.active, which is the whole point."""
    v = g.VisionController()
    fist = hand()
    for active in (True, False):
        v.active, v.fist_start = active, None
        assert v._check_fist(fist, 0.0) is False                      # starts the hold
        assert v._check_fist(fist, g.FIST_HOLD_SECS - 0.1) is False
        assert v._check_fist(fist, g.FIST_HOLD_SECS + 0.01) is True


def test_opening_the_hand_restarts_the_fist_hold():
    v = g.VisionController()
    v._check_fist(hand(), 0.0)
    v._check_fist(hand("index", "middle", "ring", "pinky"), 0.5)      # hand opened
    assert v.fist_start is None
    assert v._check_fist(hand(), 9.0) is False                        # no free pass


def test_a_swipe_needs_an_open_palm():
    """Moving any old hand across the frame used to send the browser back."""
    v = g.VisionController()
    for shape, expected in ((hand("index", "middle", "ring", "pinky"), "left"),
                            (hand("index"), None)):
        v.palm_buf.clear()
        got = None
        for i in range(12):                       # a clear right-to-left sweep
            got = v._swipe(0.8 - i * 0.05, 0.5, i / 30, shape) or got
        assert got == expected


def _child(tmp_path, body: str):
    import os, subprocess, sys as _s
    script = tmp_path / "child.py"
    script.write_text(f"import sys\nsys.path.insert(0, r'{ROOT}')\n{body}\n")
    return subprocess.Popen([_s.executable, str(script)], env={**os.environ})


def test_the_launcher_learns_whether_the_camera_actually_came_up(tmp_path):
    """TONY announced "opened vision mode" the instant Popen returned, so when the
    camera was busy the child died silently after the founder had been told it worked.
    Both answers must arrive, and neither may cost the full timeout."""
    from tools.launch import wait_for_vision

    up = _child(tmp_path, "from tools.launch import vision_ready\n"
                          "vision_ready()\n"
                          "import time; time.sleep(30)")
    try:
        assert wait_for_vision(lambda: up.poll() is None, timeout=10) is True
    finally:
        up.kill()

    dead = _child(tmp_path, "sys.exit(2)")
    assert wait_for_vision(lambda: dead.poll() is None, timeout=10) is False


def test_every_hud_state_paints_without_blowing_up():
    """The camera is the founder's live desktop, so the HUD can never be checked by
    running it. This paints every state offscreen instead — the same gate TONY's
    overlay has in test_ui_smoke.py, and the same reason: a bad cv2 argument is a
    hard crash, not an exception, and it would only show up in his face."""
    import numpy as np
    from tools import render_vision

    for name, frame in render_vision.build_scenes():
        assert frame.shape == (render_vision.H, render_vision.W, 3), name
        assert frame.dtype == np.uint8, name
        assert frame.any(), f"{name} painted nothing"
