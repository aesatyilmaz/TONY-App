"""GUI-thread watchdog — turns "it froze again" into a stack trace.

TONY has frozen several times (window goes black, app stops responding, no Python
traceback because nothing raises — the Qt event loop simply stops being serviced).
Each diagnosis so far has been an educated guess at which of several plausible
mechanisms did it. This removes the guessing: a plain thread notes when the GUI
loop last ran, and if it stalls it dumps EVERY thread's stack to tony.log, which
names the exact call that is blocking.

Costs nothing: the GUI side is one integer store per heartbeat.
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import time
import traceback
from datetime import datetime

STALL_SECONDS = 5.0          # a GUI loop that hasn't ticked this long is wedged
_beat = time.monotonic()
_reported = False


def heartbeat() -> None:
    """Call from a QTimer on the GUI thread. Deliberately trivial."""
    global _beat, _reported
    _beat = time.monotonic()
    _reported = False


def _dump(stalled_for: float) -> None:
    out = sys.stderr
    print(f"\n=== GUI THREAD STALLED {stalled_for:.1f}s "
          f"at {datetime.now():%H:%M:%S} — all thread stacks follow ===", file=out)
    for tid, frame in sys._current_frames().items():
        name = next((t.name for t in threading.enumerate() if t.ident == tid), "?")
        print(f"\n--- thread {tid} ({name}) ---", file=out)
        traceback.print_stack(frame, file=out)
    # faulthandler adds the C-level frames Python's own traceback cannot show —
    # which is where a blocked Win32/COM call actually sits.
    print("\n--- native stacks ---", file=out)
    faulthandler.dump_traceback(file=out)
    print("=== end of stall report ===\n", file=out)
    out.flush()


def start(stall_seconds: float = STALL_SECONDS) -> threading.Thread:
    """Watch the GUI heartbeat from a daemon thread."""
    def loop():
        global _reported
        while True:
            time.sleep(1.0)
            late = time.monotonic() - _beat
            if late > stall_seconds and not _reported:
                _reported = True          # one report per stall, not one per second
                try:
                    _dump(late)
                except Exception:
                    pass
    t = threading.Thread(target=loop, name="tony-watchdog", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    # ponytail self-check: a stall is detected and reported exactly once.
    start(stall_seconds=0.5)
    heartbeat()
    time.sleep(2.5)                       # no heartbeats -> one report
    assert _reported, "the watchdog failed to notice a stall"
    heartbeat()
    assert not _reported, "a heartbeat must re-arm it"
    print("watchdog OK (detected the stall, then re-armed)")
