"""Vision mode — hand-gesture computer control.

Runs as its own process (see `vision/__init__.py`) so the camera and MediaPipe never
share a thread with TONY's voice loop. There are no on-screen buttons: everything is
a gesture, plus two faders at the edges of the frame.

Gestures
    index only            pointer — the index tip drives the cursor
    peace sign            left click (only while pointing)
    OK sign held 1s       open Alt+Tab, then:
        open-palm swipe       next / previous window
        two hands still 2s    commit and close it
    open-palm swipe       browser forward / back
    fist held 2s          standby / wake — the only gesture read while asleep,
                          because reaching for the keyboard defeats the point

Every swipe needs a deliberately open palm. Without that it fired from any hand
shape nothing else had claimed, so moving a hand across the frame sent the browser
back — something that happened to you rather than something you did.

Nothing here closes a window. Two hands swept down used to, and dropping both hands
to the desk is not a decision — Alt+F4 belongs on a spoken command, not a reflex.

Faders — move the hand up/down inside one
    left edge             volume  — no lock: being on it is holding it
    right edge            scroll  — locks after 5 frames, releases 2.5s after the
                                    hand leaves (scrolling is a long motion), and
                                    scrolls by hand SPEED, not distance

V also toggles active/standby, Q quits.
"""
from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import time
from collections import deque
from enum import Enum, auto
from functools import lru_cache
from pathlib import Path

import cv2
import keyboard
import mediapipe as mp
import numpy as np
import pyautogui
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # launched as a script
from actions import volume                                        # noqa: E402
from vision import frames                                         # noqa: E402

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.0

CAMERA_INDEX         = 0
CAMERA_OPEN_TRIES    = 3     # a busy webcam is a wait, not a failure
CAMERA_RETRY_WAIT    = 0.7

# ─── Gestures ──────────────────────────────────────────────────────────────────
COOLDOWN             = 1.2
SWIPE_FRAMES         = 20
SWIPE_THRESHOLD      = 0.12

OK_HOLD_SECS         = 1.0   # OK sign held this long opens Alt+Tab
FIST_HOLD_SECS       = 1.0   # fist held this long flips active/standby
TWO_HAND_STILL_SECS  = 2.0   # both hands held still this long closes it
TWO_HAND_STILL_THRESH= 0.03  # movement below this counts as still (normalized)

# ─── Palette (TONY's, in BGR because that is what cv2 speaks) ──────────────────
GOLD       = (39, 162, 201)     # #C9A227
GOLD_LITE  = (104, 200, 228)    # #E4C868
GOLD_DEEP  = (22, 122, 156)     # #9C7A16
CREAM      = (221, 236, 244)    # #F4ECDD
CLAY       = (60, 90, 160)      # #A05A3C

# ─── Faders ────────────────────────────────────────────────────────────────────
# Two vertical tracks at the edges of the frame, worked like the faders on a mixing
# desk: reach into one and slide the hand up or down.
FADER_X_VOL          = 0.07
FADER_X_SCR          = 0.93
FADER_HALF_W         = 0.06  # how far from the track the hand still counts as on it
FADER_TOP            = 0.20
FADER_BOT            = 0.80
ZONE_HOLD_FRAMES     = 5     # palm frames on the scroll fader before it locks
LOCK_COUNTDOWN       = 2.5   # hand gone this long = unlock
LOCK_GESTURE_BLOCK   = 2.0   # gestures stay inactive this long after a lock
GLOW_RADIUS          = 0.18  # palm this close to a fader lights it up

# ─── Palm glow ─────────────────────────────────────────────────────────────────
# Light in the middle of the palm, not an outline around the hand.
PALM_GLOW_SCALE      = 1.05  # × hand span (wrist→middle knuckle) = glow radius, so
                             # the light stays inside the palm instead of flooding
PALM_GLOW_FALLOFF    = 3.0   # higher = tighter core, quieter edge
PALM_GLOW_ENGAGED    = 0.70  # peak brightness while a fader is held
PALM_GLOW_IDLE       = 0.22  # while the hand is merely being watched

# ─── Cursor ────────────────────────────────────────────────────────────────────
CURSOR_HZ            = 120   # the camera gives ~20-30 positions/s; a mouse gives 125+
CURSOR_EASE          = 0.35  # per tick, toward the latest target

# Scroll — driven by how fast the hand moves, in frame-heights per SECOND.
# Per-frame displacement was the wrong measure: at 15fps the same hand speed reads
# as twice the movement it does at 30fps. Gamma > 1 keeps a slow, deliberate drag
# genuinely slow while a fast flick pulls away.
SCROLL_MIN           = 12
SCROLL_MAX           = 900
SCROLL_FAST          = 1.2   # frame-heights/sec that counts as full speed
SCROLL_GAMMA         = 2.0
SCROLL_MOVE_THRESH   = 0.006

# Volume — speed-driven, in percentage points (set exactly via Core Audio).
# No lock: the hand being in the zone IS the grip, like a fader. That makes every
# pass through the zone count, so the steps are deliberately small.
VOL_PCT_MIN          = 1
VOL_PCT_MAX          = 6
VOL_MULT             = 90
VOL_MOVE_THRESH      = 0.012

# ─── Mouse ─────────────────────────────────────────────────────────────────────
MOUSE_CAM_ZONE       = 0.60
MOUSE_CAM_MARGIN     = (1.0 - MOUSE_CAM_ZONE) / 2
# One Euro filter (see OneEuro below). Lower min_cutoff = steadier when still;
# higher beta = less lag when moving fast.
MOUSE_MIN_CUTOFF     = 1.0
MOUSE_BETA           = 0.6
CLICK_COOLDOWN       = 0.7
CLICK_FRAMES_NEEDED  = 3
MOUSE_EXIT_TOLERANCE = 8
TRAIL_MAXLEN         = 25
TRAIL_FADE_S         = 0.5

_u32     = ctypes.windll.user32
SCREEN_X = _u32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
SCREEN_Y = _u32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
SCREEN_W = _u32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
SCREEN_H = _u32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN

WRIST      = 0
THUMB_TIP  = 4
INDEX_TIP  = 8;  INDEX_PIP  = 6;  INDEX_MCP  = 5
MIDDLE_TIP = 12; MIDDLE_PIP = 10; MIDDLE_MCP = 9
RING_TIP   = 16; RING_PIP   = 14; RING_MCP   = 13
PINKY_TIP  = 20; PINKY_PIP  = 18; PINKY_MCP  = 17


class Gesture(Enum):
    SWIPE_LEFT  = auto()
    SWIPE_RIGHT = auto()


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)

def dist_2d(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)

def finger_curl(lm, tip, mcp):
    td = dist(lm[tip], lm[WRIST])
    md = dist(lm[mcp], lm[WRIST])
    if md == 0: return 0.0
    return max(0.0, min(1.0, 1.5 - td / md))

def palm_center(lm):
    pts = [WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]
    return sum(lm[i].x for i in pts) / 5, sum(lm[i].y for i in pts) / 5

def is_ok(lm):
    """Thumb and index tips touching, the other three fingers open."""
    hand_size = dist(lm[WRIST], lm[MIDDLE_MCP])
    if hand_size == 0: return False
    touching = dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hand_size < 0.25
    return (touching and
            lm[MIDDLE_TIP].y < lm[MIDDLE_PIP].y and
            lm[RING_TIP].y   < lm[RING_PIP].y and
            lm[PINKY_TIP].y  < lm[PINKY_PIP].y)

def is_peace(lm):
    return (lm[INDEX_TIP].y < lm[INDEX_PIP].y and
            lm[MIDDLE_TIP].y < lm[MIDDLE_PIP].y and
            finger_curl(lm, RING_TIP,  RING_MCP)  > 0.50 and
            finger_curl(lm, PINKY_TIP, PINKY_MCP) > 0.50)

def is_index_only(lm):
    return (lm[INDEX_TIP].y < lm[INDEX_PIP].y and
            finger_curl(lm, MIDDLE_TIP, MIDDLE_MCP) > 0.45 and
            finger_curl(lm, RING_TIP,   RING_MCP)   > 0.50 and
            finger_curl(lm, PINKY_TIP,  PINKY_MCP)  > 0.50)

def is_fist(lm):
    """Every finger curled, thumb NOT touching the index. That last clause costs one
    comparison and keeps the pinch shape — same closed hand, thumb on the index —
    free for a future gesture instead of colliding with this one."""
    hand_size = dist(lm[WRIST], lm[MIDDLE_MCP])
    if hand_size and dist(lm[THUMB_TIP], lm[INDEX_TIP]) / hand_size < 0.25:
        return False
    return (finger_curl(lm, INDEX_TIP,  INDEX_MCP)  > 0.45 and
            finger_curl(lm, MIDDLE_TIP, MIDDLE_MCP) > 0.45 and
            finger_curl(lm, RING_TIP,   RING_MCP)   > 0.50 and
            finger_curl(lm, PINKY_TIP,  PINKY_MCP)  > 0.50)

def is_open_palm(lm):
    """All four fingers extended. The thumb is ignored on purpose — it reads
    unreliably once the hand turns, and demanding it would reject half of a real
    open palm."""
    return (lm[INDEX_TIP].y  < lm[INDEX_PIP].y and
            lm[MIDDLE_TIP].y < lm[MIDDLE_PIP].y and
            lm[RING_TIP].y   < lm[RING_PIP].y and
            lm[PINKY_TIP].y  < lm[PINKY_PIP].y)

def zone_at(cx, cy) -> str | None:
    """"vol", "scroll", or None — which fader the palm has hold of."""
    if not FADER_TOP <= cy <= FADER_BOT:
        return None
    if abs(cx - FADER_X_VOL) < FADER_HALF_W: return "vol"
    if abs(cx - FADER_X_SCR) < FADER_HALF_W: return "scroll"
    return None


def fader_distance(cx, cy, track_x) -> float:
    """Distance from the palm to the nearest point on a fader track — drives the
    glow, so a fader lights up as the hand approaches rather than on contact."""
    return dist_2d(cx, cy, track_x, min(FADER_BOT, max(FADER_TOP, cy)))

def calc_swipe(buf, threshold):
    """Dominant-axis swipe over the buffer. Vertical wins over horizontal, which is
    what keeps a hand dropping out of frame from reading as a left/right swipe."""
    if len(buf) < 8: return "none", 0.0
    pts = list(buf)
    dx = pts[-1][0] - pts[0][0]
    dy = pts[-1][1] - pts[0][1]
    if abs(dy) > abs(dx) and abs(dy) > threshold:
        return ("up" if dy < 0 else "down"), abs(dy)
    if abs(dx) > abs(dy) and abs(dx) > threshold:
        return ("left" if dx < 0 else "right"), abs(dx)
    return "none", 0.0

def cam_to_screen(nx, ny):
    sx = (nx - MOUSE_CAM_MARGIN) / MOUSE_CAM_ZONE
    sy = (ny - MOUSE_CAM_MARGIN) / MOUSE_CAM_ZONE
    return (int(SCREEN_X + max(0.0, min(1.0, sx)) * SCREEN_W),
            int(SCREEN_Y + max(0.0, min(1.0, sy)) * SCREEN_H))

def _euro_alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    """One Euro filter (Casiez, Roussel & Vogel, CHI 2012) — ~20 lines, no deps.

    A fixed-alpha average can only be steady OR responsive: crank it up and the
    cursor lags behind the hand, wind it down and it shivers. This adapts instead —
    it filters hard while the hand is nearly still (where jitter shows) and lets
    fast movement straight through (where lag shows). That is the whole reason
    pointing felt rough.
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = 0.0

    def __call__(self, x: float, t: float) -> float:
        if self.x_prev is None:
            self.x_prev, self.t_prev = x, t
            return x
        dt = max(1e-3, t - self.t_prev)
        self.t_prev = t
        a_d = _euro_alpha(self.d_cutoff, dt)
        self.dx_prev += a_d * ((x - self.x_prev) / dt - self.dx_prev)
        a = _euro_alpha(self.min_cutoff + self.beta * abs(self.dx_prev), dt)
        self.x_prev += a * (x - self.x_prev)
        return self.x_prev


def volume_step(delta: float) -> int:
    return int(min(VOL_PCT_MAX, max(VOL_PCT_MIN, abs(delta) * VOL_MULT)))

def scroll_step(velocity: float) -> int:
    """`velocity` is frame-heights per second. Slow hand → small scroll, fast flick
    → a lot, with the curve bent so the two ends actually feel different."""
    t = min(1.0, abs(velocity) / SCROLL_FAST) ** SCROLL_GAMMA
    return int(SCROLL_MIN + t * (SCROLL_MAX - SCROLL_MIN))


# ─── text ──────────────────────────────────────────────────────────────────────
# cv2 can only draw the Hershey stroke font, and this build has no cv2.freetype,
# so TONY's serif comes in through Pillow. Paths, not family names — Pillow takes
# files. Same chain as ui/tokens.py, resolved to what Windows actually ships.
_FONT_DIR  = Path(__file__).resolve().parent.parent / "ui" / "fonts"
_WIN_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
_FONT_CHAIN = (
    *(sorted(_FONT_DIR.glob("Cinzel*.ttf")) if _FONT_DIR.is_dir() else ()),
    _WIN_FONTS / "constan.ttf",     # Constantia
    _WIN_FONTS / "pala.ttf",        # Palatino Linotype
    _WIN_FONTS / "georgia.ttf",
    _WIN_FONTS / "times.ttf",
)


@lru_cache(maxsize=8)
def _font(size: int):
    for path in _FONT_CHAIN:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=256)
def text_sprite(text: str, size: int, colour: tuple, tracking: int = 0) -> np.ndarray:
    """A pre-rendered RGBA patch of `text`, cached.

    Converting the whole frame to PIL and back every frame costs milliseconds we
    do not have at 30fps. Rendering each string once and blitting the small patch
    costs almost nothing — and the HUD's strings repeat constantly.

    `tracking` is per-character spacing: PIL has no letter-spacing, and the tracked
    caps are the whole point of TONY's look, so the glyphs are placed one by one.
    """
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    widths = [probe.textlength(ch, font=font) for ch in text]
    w = int(sum(widths) + tracking * max(0, len(text) - 1)) + size
    img = Image.new("RGBA", (max(1, w), size * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rgba = (colour[2], colour[1], colour[0], 255)          # frame is BGR, PIL is RGB
    x = 0.0
    for ch, cw in zip(text, widths):
        draw.text((x, size // 3), ch, font=font, fill=rgba)
        x += cw + tracking
    return np.array(img.crop(img.getbbox() or (0, 0, 1, 1)))


def blit(frame, sprite, x: int, y: int, alpha: float = 1.0) -> None:
    """Alpha-composite an RGBA patch onto a BGR frame, clipped to the frame."""
    fh, fw = frame.shape[:2]
    sh, sw = sprite.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + sw), min(fh, y + sh)
    if x1 <= x0 or y1 <= y0:
        return
    patch = sprite[y0 - y:y1 - y, x0 - x:x1 - x]
    a = patch[:, :, 3:4].astype(np.float32) * (alpha / 255.0)
    roi = frame[y0:y1, x0:x1]
    roi[:] = (roi * (1 - a) + patch[:, :, 2::-1] * a).astype(np.uint8)


@lru_cache(maxsize=32)
def _falloff(radius: int) -> np.ndarray:
    """A soft radial falloff, cached per radius — one array per hand size, not one
    per frame. The exponent keeps the core bright and the edge quiet; linear reads
    as a floodlight rather than a shimmer."""
    d = radius * 2 + 1
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32)
    r = np.hypot(xx - radius, yy - radius) / radius
    return np.clip(1.0 - r, 0, 1) ** PALM_GLOW_FALLOFF


def palm_glow(frame, centre, radius: int, colour, strength: float) -> None:
    """Light sitting in the palm.

    Added rather than blended: light falls ON the hand, it does not paint over it,
    so the skin still reads through as a warm shimmer instead of a gold sticker.
    Only the glow's own bounding box is touched.
    """
    radius = int(radius)
    if strength <= 0 or radius < 4:
        return
    h, w = frame.shape[:2]
    cx, cy = int(centre[0]), int(centre[1])
    x0, x1 = max(0, cx - radius), min(w, cx + radius + 1)
    y0, y1 = max(0, cy - radius), min(h, cy + radius + 1)
    if x1 <= x0 or y1 <= y0:
        return
    g = _falloff(radius)[y0 - cy + radius:y1 - cy + radius,
                         x0 - cx + radius:x1 - cx + radius][..., None]
    roi = frame[y0:y1, x0:x1]
    roi[:] = np.clip(roi + g * (np.array(colour, np.float32) * strength), 0, 255).astype(np.uint8)


def catmull_rom(points, steps: int = 8):
    """Smooth curve through `points`. The camera gives ~25 trail samples a second,
    and joining them with straight lines is what made the comet look like a zigzag."""
    if len(points) < 2:
        return list(points)
    pts = [points[0], *points, points[-1]]
    out = []
    for p0, p1, p2, p3 in zip(pts, pts[1:], pts[2:], pts[3:]):
        for i in range(steps):
            t = i / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2
                       + (-a + 3 * b - 3 * c + d) * t3)
                for a, b, c, d in zip(p0, p1, p2, p3)))
    out.append(tuple(points[-1]))
    return out


def _open_camera():
    """Open the webcam, trying DirectShow first, and retry before giving up.

    DirectShow grabs frames faster than the default MSMF backend, and every
    millisecond there is a millisecond the hand is not tracked — but not every
    driver exposes a DirectShow filter, so it falls back.

    The retries are not belt-and-braces. A webcam is one shared device: another app
    holding it, or a previous vision mode process whose handle Windows has not finished
    releasing, both mean "busy right now" rather than "broken". Failing on the first
    attempt is what made the app blink the camera light and vanish, and made trying
    again a minute later work. The wait between attempts also gives OUR own just-
    released handle time to go, which the fallback would otherwise trip over.

    Each backend has to actually deliver a frame: isOpened() returns True on a
    device that never reads.
    """
    for attempt in range(1, CAMERA_OPEN_TRIES + 1):
        for backend, name in ((cv2.CAP_DSHOW, "DirectShow"), (cv2.CAP_ANY, "default")):
            cap = cv2.VideoCapture(CAMERA_INDEX, backend)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            if cap.isOpened() and cap.read()[0]:
                print(f"VISION: camera opened via {name} (attempt {attempt})")
                return cap
            print(f"VISION: {name} gave no frame (attempt {attempt}) — camera busy?")
            cap.release()
        time.sleep(CAMERA_RETRY_WAIT)
    return None


class _Lock:
    """One fader's state: hold count, locked flag, unlock countdown, last sample."""

    def __init__(self):
        self.hold = 0
        self.locked = False
        self.countdown: float | None = None
        self.last_y: float | None = None
        self.last_t: float = 0.0

    def reset(self):
        self.__init__()


class VisionController:
    def __init__(self):
        # The hand model is built in run(), not here: it is only needed while frames
        # are flowing, and constructing one per object makes anything that just wants
        # to paint the HUD (tools/render_vision.py) load — and tear down — a model.
        self.hands = None

        self.active       = True
        self.last_trigger = {}
        self.palm_buf     = deque(maxlen=SWIPE_FRAMES)

        self.scr = _Lock()             # scroll locks; volume is grab-and-go
        self.vol_last_y: float | None = None

        # Mouse. The cursor is driven by its own thread (see _cursor_loop) — this is
        # only where the latest target is dropped off.
        self.mouse_mode        = False
        self.smooth_x          = OneEuro(MOUSE_MIN_CUTOFF, MOUSE_BETA)
        self.smooth_y          = OneEuro(MOUSE_MIN_CUTOFF, MOUSE_BETA)
        self._cursor_target: tuple[int, int] | None = None
        self.last_click_t      = 0.0
        self.click_frame_cnt   = 0
        self.mouse_exit_frames = 0

        # Alt+Tab window switcher
        self.alttab_mode       = False
        self.two_hand_still_t  = None
        self.two_hand_last_pos = None
        self.ok_hold_start     = None
        self.fist_start        = None

        self.lock_engaged_t = 0.0     # gestures stay blocked briefly after a lock
        self.last_palm      = None    # (x, y) — drives the fader glow
        self.hands_seen     = []      # this frame's [(palm centre, hand span)]
        # Read in run(), not here. Reading it here put a COM proxy in every instance
        # anyone constructed — including the seven the HUD render harness builds —
        # and releasing those during garbage collection crashed the interpreter.
        self.vol_level      = 50

        self.trail        = deque(maxlen=TRAIL_MAXLEN)
        self.trail_last_x = 0.5
        self.trail_last_y = 0.5
        self.trail_last_t = 0.0

        self.fps      = 0.0
        self.cap      = None
        self._running = False
        # Inside TONY's panel there is no window to press keys at, so advertising
        # them would be a lie printed on every frame. run() corrects this.
        self._hint    = "V standby · Q quit"

    def toggle(self):
        self.active = not self.active
        self._reset_all()
        print("VISION MODE:", "ACTIVE" if self.active else "STANDBY")

    def _exit_mouse_mode(self):
        self.mouse_mode = False
        self._cursor_target = None
        self.smooth_x.reset()
        self.smooth_y.reset()
        self.trail.clear()

    def _cursor_loop(self):
        """Drives the cursor on its own clock.

        The camera hands us a position ~20-30 times a second. Calling SetCursorPos
        once per frame means the pointer teleports 20-30 times a second, which is
        exactly the stepping the founder saw — a real mouse reports at 125Hz and up.
        So the frame loop only drops off a target and this eases toward it at
        CURSOR_HZ, turning discrete hops into continuous motion.
        """
        pos = None
        while self._running:
            target = self._cursor_target          # tuple swap — atomic in CPython
            if target is None:
                pos = None
            else:
                if pos is None:
                    pos = list(target)
                pos[0] += (target[0] - pos[0]) * CURSOR_EASE
                pos[1] += (target[1] - pos[1]) * CURSOR_EASE
                _u32.SetCursorPos(int(pos[0]), int(pos[1]))
            time.sleep(1.0 / CURSOR_HZ)

    def _release_alt(self):
        if self.alttab_mode:
            keyboard.release("alt")
            self.alttab_mode = False

    def _reset_all(self):
        self.palm_buf.clear()
        self.scr.reset()
        self.vol_last_y        = None
        self._exit_mouse_mode()
        self.click_frame_cnt   = 0
        self.mouse_exit_frames = 0
        self._release_alt()
        self.two_hand_still_t  = None
        self.two_hand_last_pos = None
        self.ok_hold_start     = None
        self.fist_start        = None
        self.last_palm         = None
        self.trail.clear()

    # ─── main loop ─────────────────────────────────────────────────────────────
    def run(self, embed: bool = False):
        """Blocks on the calling thread. cv2's HighGUI wants the main thread, and
        this is its own process anyway — there is nothing else here to run.

        `embed` sends the finished frame to TONY's panel instead of opening a window
        of its own. The drawing is identical either way; only the last step differs.
        There is no V or Q key in that mode because there is no window to press them
        at — a held fist covers standby, and "close vision" covers quitting.
        """
        self.cap = _open_camera()
        if self.cap is None:
            print("VISION ERROR: no camera could be opened")
            return

        from tools.launch import vision_ready
        vision_ready()               # only now may TONY tell the founder it opened
        self.vol_level = volume.current() or self.vol_level   # the fader's real level

        self.hands = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=2,
            min_detection_confidence=0.75, min_tracking_confidence=0.65)

        writer = frames.Writer() if embed else None
        if embed:
            # No key hints inside TONY: there is no window to press them at, and the
            # gesture list is one click on the wordmark away. Printing instructions on
            # every frame of a live camera feed is clutter you cannot look away from.
            self._hint = ""
        self._running = True
        threading.Thread(target=self._cursor_loop, daemon=True).start()
        last_label = ""
        last_frame_t = time.time()
        try:
            while self._running:
                ret, frame = self.cap.read()
                if not ret: continue

                frame  = cv2.flip(frame, 1)
                result = self.hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                now = time.time()
                self.fps += 0.1 * (1.0 / max(1e-3, now - last_frame_t) - self.fps)
                last_frame_t = now
                action_label = ""

                if self.scr.countdown is not None and now > self.scr.countdown:
                    self.scr.reset()
                    print("  -> Scroll UNLOCK")

                # Landmarks are read in BOTH states. MediaPipe runs either way, and
                # standby has to be leavable by hand — the keyboard is not where
                # your hand is when you put VISION to sleep.
                hands = result.multi_hand_landmarks
                self.hands_seen = [(palm_center(hl.landmark),
                                    dist(hl.landmark[WRIST], hl.landmark[MIDDLE_MCP]))
                                   for hl in hands] if hands else []

                if hands and self._check_fist(hands[0].landmark, now):
                    self.toggle()
                elif self.active and hands:
                    action_label = self._on_hands(hands, now)
                elif self.active:
                    self._on_no_hands(now)

                if action_label: last_label = action_label

                self._draw_hud(frame, last_label, now)
                if writer is not None:
                    writer.put(frame)
                else:
                    cv2.imshow("VISION MODE", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord('v'), ord('V')): self.toggle()
                    elif key in (ord('q'), ord('Q')): self._running = False
        finally:
            self._release_alt()          # never leave Alt held down on the desktop
            self.cap.release()
            if writer is not None:
                writer.close()
            else:
                cv2.destroyAllWindows()

    def _check_fist(self, lm, now: float) -> bool:
        """True on the single frame a held fist completes. The one gesture that is
        read while VISION is asleep, because it is the way back."""
        if not is_fist(lm):
            self.fist_start = None
            return False
        if self.fist_start is None:
            self.fist_start = now
            return False
        if now - self.fist_start < FIST_HOLD_SECS:
            return False
        self.fist_start = None
        return True

    def _on_hands(self, hand_landmarks, now: float) -> str:
        if len(hand_landmarks) >= 2:
            self._check_two_hand(hand_landmarks[0].landmark, hand_landmarks[1].landmark)
            self.palm_buf.clear()
            self._exit_mouse_mode()
            self.click_frame_cnt   = 0
            self.mouse_exit_frames = 0
            return ""

        lm = hand_landmarks[0].landmark
        cx, cy = palm_center(lm)
        tx, ty = lm[INDEX_TIP].x, lm[INDEX_TIP].y

        # Point to move, flash a peace sign to click. (These were the other way round
        # until the founder tried both — pointing at the thing you mean is the more
        # obvious of the two.)
        if is_index_only(lm):
            self.mouse_mode        = True
            self.mouse_exit_frames = 0
            self.click_frame_cnt   = 0
            self.palm_buf.clear()

            # Filter in camera space — that is where the jitter is — then map once
            # and hand the target to the cursor thread, which does the actual moving.
            fx, fy = self.smooth_x(tx, now), self.smooth_y(ty, now)
            self._cursor_target = cam_to_screen(fx, fy)

            dt  = max(0.001, now - self.trail_last_t)
            spd = dist_2d(fx, fy, self.trail_last_x, self.trail_last_y) / dt
            self.trail.append((fx, fy, now, spd))
            self.trail_last_x, self.trail_last_y, self.trail_last_t = fx, fy, now
            return "POINTER"

        if is_peace(lm) and (self.mouse_mode or self.mouse_exit_frames > 0):
            self.click_frame_cnt += 1
            if self.click_frame_cnt < CLICK_FRAMES_NEEDED:
                return "..."
            if now - self.last_click_t > CLICK_COOLDOWN:
                pyautogui.click()
                self.last_click_t      = now
                self.click_frame_cnt   = 0
                self.mouse_exit_frames = 0
                self._exit_mouse_mode()
                print("  -> Click")
                return "LEFT CLICK!"
            return ""

        if self.mouse_mode:
            # Pointing survives a few stray frames — MediaPipe drops the shape
            # constantly mid-motion, and exiting on the first miss made the cursor
            # unusable.
            self.mouse_exit_frames += 1
            if self.mouse_exit_frames > MOUSE_EXIT_TOLERANCE:
                self._exit_mouse_mode()
                self.mouse_exit_frames = 0
                self.click_frame_cnt   = 0
            return ""

        self.mouse_exit_frames = 0
        self.click_frame_cnt   = 0
        return self._process_normal(cx, cy, now, lm)

    def _on_no_hands(self, now: float):
        if self.alttab_mode:
            self._release_alt()
            self.two_hand_still_t = None
            print("  -> Alt released (hand lost)")
        self.palm_buf.clear()
        self.scr.hold = 0
        self.vol_last_y = None          # the fader is released the moment the hand goes
        self._exit_mouse_mode()
        self.click_frame_cnt = 0
        self.mouse_exit_frames = 0
        self.last_palm = None
        if self.scr.locked and self.scr.countdown is None:
            self.scr.countdown = now + LOCK_COUNTDOWN

    def _process_normal(self, cx, cy, now, lm) -> str:
        self.last_palm = (cx, cy)

        # Alt+Tab is modal: only swipes reach through it.
        if self.alttab_mode:
            self.ok_hold_start = None
            direction = self._swipe(cx, cy, now, lm)
            if direction:
                gesture = Gesture.SWIPE_LEFT if direction == "left" else Gesture.SWIPE_RIGHT
                self.last_trigger[gesture] = 0        # no cooldown while cycling windows
                self._execute_gesture(gesture)
                return f"ALT+TAB: {'PREV' if direction == 'left' else 'NEXT'}"
            return "ALT+TAB: ACTIVE"

        if is_ok(lm):
            if self.ok_hold_start is None:
                self.ok_hold_start = now
            elapsed = now - self.ok_hold_start
            if elapsed < OK_HOLD_SECS:
                return f"OK {elapsed:.1f}s / {OK_HOLD_SECS}s"
            self.ok_hold_start = None
            keyboard.press("alt")
            keyboard.press_and_release("tab")
            self.alttab_mode = True
            print("  -> Alt+Tab opened (OK gesture)")
            return "ALT+TAB!"
        self.ok_hold_start = None

        # Scroll locks: park the palm in the right zone and the hand keeps it until
        # it leaves for LOCK_COUNTDOWN. Scrolling is a long, continuous motion.
        if self.scr.locked:
            if self.scr.countdown is None:
                self.scr.countdown = now + LOCK_COUNTDOWN
            self.palm_buf.clear()
            self.vol_last_y = None
            return self._do_scroll(cy, now)

        zone = zone_at(cx, cy)
        if zone == "scroll":
            self.vol_last_y = None
            self.palm_buf.clear()
            self.scr.hold += 1
            if self.scr.hold >= ZONE_HOLD_FRAMES:
                self.scr.locked    = True
                self.scr.countdown = now + LOCK_COUNTDOWN
                self.scr.last_y    = cy
                self.scr.last_t    = now
                self.scr.hold      = 0
                self.lock_engaged_t = now
                print("  -> scroll locked")
                return "SCROLL LOCKED"
            return ""

        self.scr.hold = 0
        if zone == "vol":
            # Volume does NOT lock — being in the zone is the grip, like a fader.
            self.palm_buf.clear()
            return self._do_volume(cy)
        self.vol_last_y = None

        direction = self._swipe(cx, cy, now, lm)
        if direction:
            self._execute_gesture(Gesture.SWIPE_LEFT if direction == "left"
                                  else Gesture.SWIPE_RIGHT)
            return f"SWIPE {direction.upper()}"
        return ""

    def _swipe(self, cx, cy, now, lm) -> str | None:
        """"left", "right", or None — and only from a deliberately open palm.

        Swipes used to fire from any hand shape that wasn't already claimed, so
        simply moving a hand across the frame sent the browser back. Requiring the
        palm makes it something you do rather than something that happens to you.
        """
        if not is_open_palm(lm):
            self.palm_buf.clear()
            return None
        self.palm_buf.append((cx, cy, now))
        direction, _ = calc_swipe(self.palm_buf, SWIPE_THRESHOLD)
        if direction not in ("left", "right"):
            return None
        self.palm_buf.clear()
        return direction

    # ─── zone drags ────────────────────────────────────────────────────────────
    def _do_scroll(self, cy: float, now: float) -> str:
        dt = max(1e-3, now - self.scr.last_t)
        self.scr.last_t = now
        self.scr.last_y, delta = self._drag_delta(self.scr.last_y, cy, SCROLL_MOVE_THRESH)
        if delta is None: return "SCROLL ACTIVE"
        amount = scroll_step(delta / dt)                     # speed, not displacement
        pyautogui.scroll(amount if delta < 0 else -amount)   # hand up = scroll up
        return "SCROLL UP" if delta < 0 else "SCROLL DOWN"

    def _do_volume(self, cy: float) -> str:
        self.vol_last_y, delta = self._drag_delta(self.vol_last_y, cy, VOL_MOVE_THRESH)
        if delta is None: return "VOL ACTIVE"
        step = volume_step(delta)
        # change() returns the new level — the fader draws the real volume, not a
        # guess, and that costs no extra COM call.
        self.vol_level = volume.change(step if delta < 0 else -step) or self.vol_level
        return "VOL UP" if delta < 0 else "VOL DOWN"

    @staticmethod
    def _drag_delta(last_y, cy: float, thresh: float):
        """(new anchor, movement or None). The first frame only anchors — otherwise
        grabbing a zone would jump by wherever the hand happened to enter."""
        if last_y is None:
            return cy, None
        delta = cy - last_y
        return cy, (None if abs(delta) < thresh else delta)

    # ─── gestures ──────────────────────────────────────────────────────────────
    def _check_two_hand(self, lm1, lm2) -> None:
        """Two hands mean exactly one thing: holding them still commits Alt+Tab.

        They used to also close the focused window when swept downward — dropping
        both hands to the desk is not a decision, and Alt+F4 is not undoable. Say
        "close window" to TONY instead.
        """
        if not self.alttab_mode:
            return
        cx1, cy1 = palm_center(lm1)
        cx2, cy2 = palm_center(lm2)
        mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
        now = time.time()

        if self.two_hand_last_pos is not None:
            moved = max(abs(mx - self.two_hand_last_pos[0]),
                        abs(my - self.two_hand_last_pos[1]))
            if moved < TWO_HAND_STILL_THRESH:
                if self.two_hand_still_t is None:
                    self.two_hand_still_t = now
                elif now - self.two_hand_still_t >= TWO_HAND_STILL_SECS:
                    self._release_alt()
                    self.two_hand_still_t  = None
                    self.two_hand_last_pos = None
                    print("  -> Alt released (still)")
                    return
            else:
                self.two_hand_still_t = None
        self.two_hand_last_pos = (mx, my)

    def _execute_gesture(self, gesture: Gesture):
        now = time.time()
        if now - self.lock_engaged_t < LOCK_GESTURE_BLOCK:
            return                       # the hand is still leaving a fader
        if now - self.last_trigger.get(gesture, 0) < COOLDOWN:
            return
        self.last_trigger[gesture] = now

        if gesture == Gesture.SWIPE_LEFT:
            if self.alttab_mode:
                keyboard.press_and_release("shift+tab")
            else:
                pyautogui.hotkey("alt", "left")
        else:
            if self.alttab_mode:
                keyboard.press_and_release("tab")
            else:
                pyautogui.hotkey("alt", "right")
        print(f"  -> {gesture.name}")


    # ─── HUD ───────────────────────────────────────────────────────────────────
    def _draw_hud(self, frame, last_label, now):
        h, w = frame.shape[:2]

        if not self.active:
            # Drained of colour: you can tell VISION is asleep without reading a word.
            frame[:] = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                                    cv2.COLOR_GRAY2BGR)
            # The waking fist is the one thing still drawn in colour — without the
            # ring you would be holding a fist at a grey window with no idea whether
            # anything is watching.
            self._draw_fist_arc(frame, w, h, now)
            self._label(frame, "VISION MODE · STANDBY", 8, h - 26, 15, GOLD_DEEP)
            return

        engaged = self.vol_last_y is not None or self.scr.locked
        strength = PALM_GLOW_ENGAGED if engaged else PALM_GLOW_IDLE
        colour = CREAM if self.mouse_mode else GOLD_LITE
        for (px, py), span in self.hands_seen:
            palm_glow(frame, (px * w, py * h),
                      span * PALM_GLOW_SCALE * min(w, h), colour, strength)

        self._draw_trail(frame, w, h, now)

        self._draw_fader(frame, w, h, now, FADER_X_VOL, "VOL",
                         engaged=self.vol_last_y is not None,
                         progress=0.0, level=self.vol_level / 100.0)
        scroll_level = None
        if self.scr.locked and self.scr.last_y is not None:
            span = FADER_BOT - FADER_TOP
            scroll_level = min(1.0, max(0.0, (FADER_BOT - self.scr.last_y) / span))
        self._draw_fader(frame, w, h, now, FADER_X_SCR, "SCROLL",
                         engaged=self.scr.locked,
                         progress=min(1.0, self.scr.hold / ZONE_HOLD_FRAMES),
                         level=scroll_level,
                         countdown=self.scr.countdown)

        self._draw_ok_arc(frame, w, h, now)
        self._draw_fist_arc(frame, w, h, now)

        if self.alttab_mode:
            status, colour = "ALT+TAB", GOLD_LITE
        elif self.mouse_mode:
            status, colour = "POINTER", CREAM
        else:
            status, colour = "VISION MODE", GOLD
        self._label(frame, status, 8, h - 26, 15, colour)
        if last_label:
            sprite = text_sprite(last_label, 14, GOLD_LITE, 1)
            blit(frame, sprite, w - sprite.shape[1] - 10, h - 25)
        self._label(frame, f"{self.fps:04.1f} fps", w - 62, 8, 11, GOLD_DEEP, alpha=0.7)
        if self._hint:
            self._label(frame, self._hint, 8, 8, 11, GOLD_DEEP, alpha=0.7)

    def _label(self, frame, text, x, y, size, colour, tracking=1, alpha=1.0):
        blit(frame, text_sprite(text, size, colour, tracking), int(x), int(y), alpha)

    def _draw_trail(self, frame, w, h, now):
        """The comet behind the pointing finger. Drawn through a Catmull-Rom curve
        because the raw samples arrive far too sparsely to join with straight lines."""
        fresh = [(x, y, t, s) for x, y, t, s in self.trail if now - t <= TRAIL_FADE_S]
        if len(fresh) < 3:
            return
        curve = catmull_rom([(x * w, y * h) for x, y, _, _ in fresh])
        n = len(curve)
        for i in range(1, n):
            p = i / n                                  # 0 = oldest, 1 = at the finger
            speed = min(1.0, fresh[-1][3] * 3.0)
            col = tuple(int(c * (0.35 + 0.65 * p)) for c in GOLD_LITE)
            cv2.line(frame, (int(curve[i - 1][0]), int(curve[i - 1][1])),
                     (int(curve[i][0]), int(curve[i][1])),
                     col, max(1, int((1 + 4 * speed) * p)), cv2.LINE_AA)
        cv2.circle(frame, (int(curve[-1][0]), int(curve[-1][1])), 4, CREAM, -1, cv2.LINE_AA)

    def _draw_fader(self, frame, w, h, now, track_x, label, *, engaged,
                    progress=0.0, level=None, countdown=None):
        """One mixing-desk fader: a translucent track with a handle on it."""
        x  = int(track_x * w)
        y0, y1 = int(FADER_TOP * h), int(FADER_BOT * h)

        near = 0.0
        if self.last_palm and not self.mouse_mode:
            near = max(0.0, 1.0 - fader_distance(*self.last_palm, track_x) / GLOW_RADIUS)
        lit = max(near, progress, 1.0 if engaged else 0.0)
        if self.mouse_mode:
            lit = 0.0

        # The track, blended over a narrow strip so it stays a hint, not a bar.
        pad = 18
        rx0, rx1 = max(0, x - pad), min(w, x + pad + 1)
        roi = frame[y0:y1, rx0:rx1]
        strip = roi.copy()
        cv2.line(strip, (x - rx0, 0), (x - rx0, y1 - y0), GOLD_DEEP, 2, cv2.LINE_AA)
        if level is not None:                       # filled from the bottom to the handle
            hy = int((1.0 - level) * (y1 - y0))
            cv2.line(strip, (x - rx0, hy), (x - rx0, y1 - y0),
                     GOLD_LITE if engaged else GOLD, 3, cv2.LINE_AA)
        a = 0.20 + 0.55 * lit
        cv2.addWeighted(strip, a, roi, 1 - a, 0, roi)

        if level is not None:
            hy = int(y0 + (1.0 - level) * (y1 - y0))
            half = 9 + int(5 * lit)
            col = GOLD_LITE if engaged else GOLD
            cv2.line(frame, (x - half, hy), (x + half, hy), col, 2, cv2.LINE_AA)
            cv2.circle(frame, (x, hy), 3 + int(2 * lit), CREAM if engaged else col,
                       -1, cv2.LINE_AA)

        text = f"{max(0, countdown - now):.1f}s" if (engaged and countdown) else label
        sprite = text_sprite(text, 11, GOLD_LITE if engaged else GOLD_DEEP, 2)
        blit(frame, sprite, x - sprite.shape[1] // 2, y1 + 10, 0.35 + 0.65 * lit)

    def _draw_ok_arc(self, frame, w, h, now):
        """The OK sign has to be held for a second — show the second going by."""
        if self.ok_hold_start is None or not self.last_palm:
            return
        self._hold_ring(frame, w, h, self.last_palm,
                        (now - self.ok_hold_start) / OK_HOLD_SECS)

    def _draw_fist_arc(self, frame, w, h, now):
        if self.fist_start is None or not self.hands_seen:
            return
        self._hold_ring(frame, w, h, self.hands_seen[0][0],
                        (now - self.fist_start) / FIST_HOLD_SECS)

    @staticmethod
    def _hold_ring(frame, w, h, centre_norm, progress: float):
        """A ring that fills while a gesture is being held. Holding something for two
        seconds with no feedback feels broken long before it feels slow."""
        p = min(1.0, max(0.0, progress))
        centre = (int(centre_norm[0] * w), int(centre_norm[1] * h))
        r = int(0.13 * min(w, h))
        cv2.ellipse(frame, centre, (r, r), -90, 0, 360, GOLD_DEEP, 1, cv2.LINE_AA)
        cv2.ellipse(frame, centre, (r, r), -90, 0, int(360 * p), GOLD_LITE, 3, cv2.LINE_AA)


if __name__ == "__main__":
    # TONY launches this with its own interpreter, which under pythonw has no stdout
    # at all — so every print and every traceback here used to vanish, and a crash
    # looked like "the window flashed and closed" with nothing to read afterwards.
    from tools.launch import log_setup
    log_setup("VISION")
    print("=" * 46)
    print("  VISION MODE")
    print("  V = Active/Standby   |   Q = Quit")
    print("=" * 46)
    try:
        VisionController().run(embed="--embed" in sys.argv)
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
