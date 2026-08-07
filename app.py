"""TONY App UI entry — tray overlay + voice worker on a thread. Run: pythonw app.py"""
from __future__ import annotations
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.launch import log_setup, already_running, show_requested
log_setup()  # pythonw: stdout/stderr -> tony.log

from ui.win_native import enable_dpi_awareness
enable_dpi_awareness()  # BEFORE QApplication

from PySide6.QtCore import QThread, QTimer, QObject, Slot
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from ui.tray import TonyTray
from ui.info_window import InfoWindow
from ui.voice_worker import VoiceWorker

_ICON = Path(__file__).resolve().parent / "ui" / "assets" / "tony.ico"


def _install_tray_icon(app: QApplication, overlay) -> QSystemTrayIcon:
    """Notification-area icon: show/hide the pill, and a guaranteed way out."""
    icon = QSystemTrayIcon(QIcon(str(_ICON)) if _ICON.exists() else app.windowIcon(), app)
    icon.setToolTip("TONY — say \"Tony\", then a command")
    # Parent the menu to a real widget. setContextMenu does NOT take ownership, so an
    # unparented local QMenu is garbage-collected the moment this function returns and
    # right-clicking the icon silently does nothing. (QSystemTrayIcon is a QObject, not
    # a QWidget, so it cannot be a QMenu's parent.)
    menu = QMenu(overlay)
    icon.setContextMenu(menu)
    show = QAction("Show / hide TONY", menu)
    show.triggered.connect(lambda: overlay.setVisible(not overlay.isVisible()))
    quit_ = QAction("Turn off TONY", menu)
    quit_.triggered.connect(app.quit)
    menu.addAction(show)
    menu.addSeparator()
    menu.addAction(quit_)
    icon.activated.connect(
        lambda reason: overlay.setVisible(not overlay.isVisible())
        if reason == QSystemTrayIcon.Trigger else None)
    icon.show()
    return icon


class _GuiBridge(QObject):
    """Receives the worker's signals ON THE GUI THREAD.

    This class exists because of a hard freeze. A signal connected to a bare
    lambda has no receiver QObject, so Qt cannot decide it belongs to another
    thread — it runs the callable **in the emitting thread**. `worker.failed` was
    connected that way, so the voice worker was building and animating widgets
    itself, which is undefined behaviour in Qt and wedged the GUI thread. It bit
    hardest with music playing: ambient sound transcribes, matches nothing, emits
    `failed`, and the worker walked into the popup code every few seconds.

    A slot on a QObject created here (i.e. on the GUI thread) makes the connection
    queued automatically, which is the whole fix. Anything the worker triggers
    belongs on this object — never on a lambda.
    """

    def __init__(self, tray, worker, thread):
        super().__init__(tray)          # parented to a GUI-thread object
        self._tray, self._worker, self._thread = tray, worker, thread

    @Slot(str)
    def on_failed(self, text: str) -> None:
        self._tray.show_response(text, ok=False)

    @Slot()
    def on_shutdown_requested(self) -> None:
        # "turn off yourself" — let the popup be seen before the window goes.
        QTimer.singleShot(1200, lambda: shutdown(self._worker, self._thread))


def shutdown(worker, thread, code: int = 0) -> None:
    """Turn off everything TONY owns, and actually exit.

    The worker can be parked inside an up-to-8s microphone read, so waiting for a
    clean thread join would make "turn off" feel broken. Stop the child processes
    ourselves, then leave via os._exit so a stuck audio read can't hold the process
    (and the camera light) on.
    """
    worker.stop()
    thread.quit()
    thread.wait(1500)
    from actions import screen_record
    import vision
    try:
        screen_record.stop_recording()   # finalize the mp4 rather than orphan ffmpeg
        vision.close_vision()            # release the camera
    finally:
        os._exit(code)


def main():
    # The pill has no taskbar button, so Windows shows no "already running" indicator
    # and every click of the desktop icon would launch another TONY — each loading its
    # own Whisper (~0.5GB VRAM), opening its own microphone and grabbing the same
    # global hotkey. Five of them exhausted the GPU and took the app down. Refuse to
    # be second, and ask the live copy to reveal itself instead.
    # (Inside main(), not at import: importing app.py must stay side-effect free so
    # the wiring tests can build the real objects while TONY is running.)
    if already_running():
        print("TONY is already running — asked it to show itself instead.")
        raise SystemExit(0)

    import signal
    # Qt's event loop blocks in C++, so Python never runs its SIGINT handler and
    # Ctrl+C in the console does nothing. Hand SIGINT back to the OS default.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # the overlay is frameless; only the tray quits
    if _ICON.exists():
        app.setWindowIcon(QIcon(str(_ICON)))
    worker = VoiceWorker()
    thread = QThread()

    info = InfoWindow(on_turn_off=lambda: shutdown(worker, thread))
    tray = TonyTray(on_open_info=info.present)   # clicking the pill opens the list
    tray.show()
    # Parked on the tray rather than a local: the icon dies with its last reference,
    # and a local that only exists to not be collected is a comment pretending to be code.
    tray.tray_icon = _install_tray_icon(app, tray)

    # worker signals → tray slots. EVERY receiver here must be a bound method of a
    # QObject that lives on the GUI thread (`tray`, or `bridge` below) — see _GuiBridge.
    bridge = _GuiBridge(tray, worker, thread)  # noqa: F841 - kept alive by parent
    worker.state_changed.connect(tray.set_state)
    worker.executed.connect(tray.show_response)
    worker.failed.connect(bridge.on_failed)
    worker.window_opened.connect(tray.on_window_opened)
    worker.window_closed.connect(tray.on_window_closed)
    worker.type_mode.connect(tray.on_type_mode)
    worker.shutdown_requested.connect(bridge.on_shutdown_requested)

    # Clicking the desktop/taskbar icon while TONY runs should reveal it, not be a
    # no-op. The second process signals; this poll reveals the pill and drops it.
    # It doubles as the GUI heartbeat: if this stops ticking, the loop is wedged and
    # the watchdog dumps every thread's stack to tony.log — which is how we find out
    # what actually froze it instead of guessing again.
    from tools.watchdog import heartbeat, start as start_watchdog
    start_watchdog()
    reveal = QTimer()
    reveal.setInterval(400)

    def _pulse():
        heartbeat()
        if show_requested():
            tray.show()
    reveal.timeout.connect(_pulse)
    reveal.start()

    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()

    shutdown(worker, thread, app.exec())


if __name__ == "__main__":
    main()
