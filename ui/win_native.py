"""Win32 (ctypes) helpers for the no-activate overlay, focus tracking, and DPI."""
from __future__ import annotations
import ctypes

def enable_dpi_awareness() -> None:
    """Per-monitor DPI aware so capture/record coords and the overlay are pixel-correct.
    Must be called BEFORE QApplication is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080   # keep it out of the taskbar / alt-tab

def set_no_activate(hwnd: int) -> None:
    """Window shows and is clickable but never becomes foreground (won't steal focus)."""
    u = ctypes.windll.user32
    ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)

def get_foreground() -> int:
    return ctypes.windll.user32.GetForegroundWindow()

def set_foreground(hwnd: int) -> None:
    if hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)

def own_hwnd(widget) -> int:
    """The HWND of a Qt widget (after it's created)."""
    return int(widget.winId())


_WM_NCLBUTTONDOWN = 0x00A1
_HTCAPTION = 2

def start_native_drag(hwnd: int) -> None:
    """Hand the drag to Windows instead of moving the window from Qt.

    Dragging means re-positioning the window on every mouse move, and this window is
    WS_EX_LAYERED and topmost — moving one of those per input event is the same class
    of synchronous Win32 geometry work that wedged the GUI thread once already
    (see ui/tray.py's popup note). Telling Windows the press landed on a title bar
    makes the OS run its own modal move loop: Qt never touches geometry at all.
    """
    u = ctypes.windll.user32
    u.ReleaseCapture()
    u.SendMessageW(hwnd, _WM_NCLBUTTONDOWN, _HTCAPTION, 0)


# ponytail: drop_no_activate() and ForegroundTracker lived here to serve the Settings
# panel (which needed keyboard focus) and its click-to-run command rows (which needed
# focus handed back before sending a hotkey). Both were deleted with the panel — the
# tray is now logo-only and never takes focus at all, which is the simpler guarantee.
