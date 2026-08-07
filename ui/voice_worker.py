"""VoiceWorker — runs the shared TONY voice loop on a QThread and emits UI signals.

The loop itself lives in `session.py` (the console entry point runs the very same one);
this class only translates its events into Qt signals for the tray.
"""
from __future__ import annotations
import threading

from PySide6.QtCore import QObject, Signal, Slot

from config import settings
from commands import build_commands, apply_custom_triggers


class VoiceWorker(QObject):
    """The tray shows only two things: whether TONY is listening, and a popup
    after a command. So the loop's transcript/window_reset events are dropped
    here rather than carried to a widget that would ignore them."""

    state_changed = Signal(str)     # idle | listening | heard | executed | no_match
    executed      = Signal(str)     # response text  -> popup
    failed        = Signal(str)     # problem text   -> muted popup
    window_opened = Signal()
    window_closed = Signal()
    type_mode     = Signal(bool)    # dictation on/off -> a banner that does not fade
    shutdown_requested = Signal()   # "turn off yourself" -> app.py quits

    def __init__(self) -> None:
        super().__init__()
        self.cfg = settings.load()
        self._commands = apply_custom_triggers(build_commands(), self.cfg)
        self._stop = False
        self._hotkey_evt = threading.Event()

    def _report(self, event: str, arg=None) -> None:
        """Translate a session event into Qt signals for the tray."""
        if event == "ready":
            self.state_changed.emit("idle")
        elif event == "window_open":
            self.window_opened.emit(); self.state_changed.emit("listening")
        elif event == "window_closed":
            self.window_closed.emit(); self.state_changed.emit("idle")
        elif event == "executed":
            self.executed.emit(arg); self.state_changed.emit("executed")
        elif event == "no_match":
            self.failed.emit("didn't catch that")
            self.state_changed.emit("no_match")
        elif event == "type_mode":
            self.type_mode.emit(bool(arg))
        elif event == "shutdown":
            self.shutdown_requested.emit()
        elif event == "failed":
            # Surface it — under pythonw the traceback would otherwise only reach
            # tony.log, which nobody reads.
            self.failed.emit(f"couldn't do that ({arg})")
            self.state_changed.emit("no_match")
        # "heard", "typed" and "window_reset" are deliberately ignored: the tray no
        # longer displays transcripts, dictation shows up in the app being typed into,
        # and with the countdown ring gone a window reset has nothing to redraw.

    @Slot()
    def run(self) -> None:
        from session import run_session
        run_session(self.cfg, self._commands, self._report,
                    should_stop=lambda: self._stop, hotkey_evt=self._hotkey_evt)

    def stop(self) -> None:
        self._stop = True
        self._hotkey_evt.set()   # unblock wait_for_wake so the thread exits promptly
