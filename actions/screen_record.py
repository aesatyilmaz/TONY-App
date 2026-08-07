"""Full-monitor screen recording via ffmpeg (gdigrab) — the active window's monitor."""
from __future__ import annotations
import ctypes
import subprocess
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg

_MONITOR_DEFAULTTONEAREST = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def active_monitor_rect() -> tuple[int, int, int, int]:
    """(x, y, w, h) of the monitor the foreground window is on, in virtual-screen coords."""
    user32 = ctypes.windll.user32
    # HMONITOR is a real pointer — without restype ctypes truncates it to c_int on x64.
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    hwnd = user32.GetForegroundWindow()
    hmon = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if hmon and user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
        r = info.rcMonitor
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    # Failure would leave the struct zeroed → "-video_size 0x0" to ffmpeg and a
    # raise from ImageGrab. Fall back to the primary monitor instead.
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


_proc: subprocess.Popen | None = None


def start_recording(dest_dir: Path) -> str:
    global _proc
    if _proc is not None and _proc.poll() is None:
        return "already recording"
    dest_dir.mkdir(parents=True, exist_ok=True)
    x, y, w, h = active_monitor_rect()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = dest_dir / f"recording_{ts}.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-f", "gdigrab", "-framerate", "30",
           "-offset_x", str(x), "-offset_y", str(y),
           "-video_size", f"{w}x{h}", "-i", "desktop",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           str(out)]
    _proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)  # stderr inherited: ffmpeg init
                                                            # errors show in the console
    time.sleep(0.4)
    if _proc.poll() is not None:   # gdigrab failed to init — died instantly
        _proc = None
        return "couldn't start recording"
    return "recording started"


def stop_recording() -> str:
    global _proc
    if _proc is None or _proc.poll() is not None:
        return "not recording"
    try:
        _proc.communicate(input=b"q", timeout=15)  # graceful finalize → playable mp4
    except subprocess.TimeoutExpired:
        _proc.terminate()  # ponytail: last resort — hard-kill loses the take (no moov
                            # atom written); upgrade to a longer wait or a watchdog if
                            # this fires in practice.
    _proc = None
    return "recording saved"
