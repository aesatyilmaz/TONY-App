"""Vision mode lifecycle — start and stop the hand-gesture controller.

It runs as a SEPARATE PROCESS on purpose: the camera and MediaPipe would otherwise
share a thread with TONY's voice loop, and cv2's window wants a main thread of its own.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.launch import wait_for_vision                       # noqa: E402

_GESTURE = Path(__file__).resolve().parent / "gesture.py"
_proc: subprocess.Popen | None = None

# Where the picture goes. True means "into TONY's pill", which is right for app.py
# and wrong for anything without a pill: main.py's console mode has no panel to draw
# into, so an embedded vision mode there is a camera running with nothing on screen.
# main.py turns this off; the default suits the app the founder actually runs.
EMBED = True


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def open_vision() -> str:
    """Start vision mode and wait until its camera is actually live.

    The wait is the point. Popen returns the instant the interpreter starts, so this
    used to report success and only afterwards did the child try the camera — when
    the camera was busy the child died silently, having already been announced as
    open. Raising instead of returning a message is deliberate: session.execute()
    turns an exception into the "failed" popup, while a returned string is dropped
    (the popup text comes from the command's own `response`).
    """
    global _proc
    if is_running():
        return "Vision mode is already open, Sir."
    _proc = subprocess.Popen(
        [sys.executable, str(_GESTURE)] + (["--embed"] if EMBED else []),
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    if not wait_for_vision(is_running):
        if is_running():
            _proc.kill()        # hung on the camera rather than dead — don't orphan it
        _proc = None
        raise RuntimeError("the camera would not open — is another app using it?")
    return "Opened vision mode, Sir."


def close_vision() -> str:
    global _proc
    if not is_running():
        return "Vision mode is not running, Sir."
    _proc.terminate()
    try:
        _proc.wait(timeout=3)           # let the camera actually go before we return
    except subprocess.TimeoutExpired:
        _proc.kill()
    _proc = None
    _release_alt()
    return "Closed vision mode, Sir."


def _release_alt() -> None:
    """TerminateProcess runs no cleanup, so a child killed mid-Alt+Tab leaves Alt
    physically held down for the whole desktop. Key state is global — we can undo it
    from here. Harmless when Alt was never pressed."""
    try:
        import pyautogui
        pyautogui.keyUp("altleft")
        pyautogui.keyUp("alt")
    except Exception:
        pass
