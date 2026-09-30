"""Silent-launch helpers: logging under pythonw, and a single-instance guard.

Under pythonw.exe (no console) sys.stdout/sys.stderr are both None, so any
print() or crash traceback vanishes silently. log_setup() redirects them to
tony.log in that case only — `python app.py` in a normal console is untouched.
"""
from __future__ import annotations
import ctypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Local\ = this user's session. Global\ would need SeCreateGlobalPrivilege, which a
# normal desktop launch may not have — the guard would then silently never engage.
_MUTEX_NAME = "Local\\TONY_single_instance"
_WAKE_EVENT_NAME = "Local\\TONY_show_yourself"
_VISION_READY_NAME = "Local\\TONY_vision_ready"
_ERROR_ALREADY_EXISTS = 183
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_mutex = None          # module-level: released when the process exits
_wake_event = None
_vision_ready = None   # lives as long as the vision mode process; the event dies with it

# use_last_error=True is not cosmetic: without it the error code from CreateMutexW
# can be clobbered before we read it, and a spurious "already exists" makes the
# launcher exit silently — which looks exactly like "clicking the icon does nothing".
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def frozen() -> bool:
    """True when running from a PyInstaller build rather than the source tree."""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Where TONY's own writable files belong: settings.json, gallery/, tony.log.

    From source that is the repo root. **From a build it must be the folder holding
    the .exe, not the bundle**: PyInstaller sets `__file__` to a path inside
    `_internal/`, so a path derived from it would hide the founder's settings inside
    the app's guts — and be read-only the moment the app is unzipped somewhere like
    Program Files.
    """
    return Path(sys.executable).parent if frozen() else Path(__file__).resolve().parent.parent


def log_setup(name: str = "TONY") -> None:
    if sys.stdout is not None:  # real console (python app.py) — keep it, but a redirected
        # stdout is cp1252 on Windows and dies on the first "→" (killed the voice thread)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        return
    log_path = app_dir() / "tony.log"
    f = open(log_path, "a", encoding="utf-8", buffering=1)
    # PID and name in the header: when two pythonw processes coexist, this is what
    # says which is which — vision mode runs from the same interpreter and looks
    # identical in Task Manager. Without this its crashes vanish entirely.
    f.write(f"\n--- {name} started {datetime.now():%Y-%m-%d %H:%M:%S} (pid {os.getpid()}) ---\n")
    sys.stdout = sys.stderr = f


def already_running() -> bool:
    """True if another TONY is live.

    Matters because TONY starts on boot: launching it again would put a second
    always-on microphone listener and a second global hotkey hook on the machine,
    and both copies would fire every command. A named mutex is the OS's own
    answer — Windows drops it automatically when the process dies, so a crash
    can't leave a stale lock behind (a lock file would).
    """
    global _mutex, _wake_event
    _mutex = _k32.CreateMutexW(None, False, _MUTEX_NAME)
    running = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    if running:
        # Don't just die quietly — the user clicked TONY's icon and expects to see
        # TONY. Poke the live copy so it shows its pill, then step aside.
        h = _k32.OpenEventW(_EVENT_MODIFY_STATE, False, _WAKE_EVENT_NAME)
        if h:
            _k32.SetEvent(h)
            _k32.CloseHandle(h)
    else:
        _wake_event = _k32.CreateEventW(None, True, False, _WAKE_EVENT_NAME)
    return running


def show_requested() -> bool:
    """True once when another launch asked us to reveal ourselves (auto-resets).

    Polled by the running instance; costs one syscall and never touches a window,
    so it can't repeat the per-frame-move mistake that wedged the GUI thread.
    """
    if not _wake_event:
        return False
    if _k32.WaitForSingleObject(_wake_event, 0) == 0:   # WAIT_OBJECT_0
        _k32.ResetEvent(_wake_event)
        return True
    return False


def vision_ready() -> None:
    """Called by the vision mode process once its camera is actually delivering frames.

    Popen succeeds the instant the interpreter starts, so TONY announced "vision mode
    on" and only then did the child try the camera — and when the camera was
    busy, the child died silently while the founder had already been told it worked.
    This event is what makes the announcement true.
    """
    global _vision_ready
    _vision_ready = _k32.CreateEventW(None, True, True, _VISION_READY_NAME)


def wait_for_vision(is_alive, timeout: float = 7.0) -> bool:
    """True once the vision mode process reports its camera is live; False if it exits
    first or never gets there. Returns as soon as either happens — the full timeout
    is only paid when the child hangs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = _k32.OpenEventW(_SYNCHRONIZE, False, _VISION_READY_NAME)
        if h:
            ready = _k32.WaitForSingleObject(h, 0) == 0     # WAIT_OBJECT_0
            _k32.CloseHandle(h)
            if ready:
                return True
        if not is_alive():
            return False
        time.sleep(0.1)
    return False


if __name__ == "__main__":
    # ponytail self-check: console path is a no-op; the guard is free the first time
    # and trips the second (same process re-acquiring the same name).
    before = sys.stdout
    log_setup()
    assert sys.stdout is before, "log_setup() must not touch a real console"
    assert already_running() is False, "first acquire must be free"
    assert already_running() is True, "second acquire must report the existing mutex"
    print("launch helpers OK (console no-op + single-instance guard)")
