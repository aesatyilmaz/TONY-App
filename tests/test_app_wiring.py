"""End-to-end wiring check for the UI entry point — offscreen, no window shown.

`app.py` connects six worker signals to six tray slots and installs a tray icon.
A renamed slot or a signal the worker never emits fails silently at runtime (Qt
logs a warning and the tray just stops updating), and the founder only finds out
by watching the app do nothing. This builds the real objects, pushes every event
`session.py` can emit through the worker's reporter, and fails loudly instead.

Run: python -m pytest tests/test_app_wiring.py -v
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

# every event run_session() reports, with a representative payload — including the
# two the worker deliberately drops ("heard", "window_reset"), which must stay harmless
SESSION_EVENTS = [
    ("ready", None),
    ("window_open", None),
    ("heard", "turn it up"),
    ("executed", "increased volume by 10%"),
    ("window_reset", None),
    ("no_match", "uhh whatever"),
    ("failed", "open_claude: boom"),
    ("window_closed", None),
]


def _wire():
    """Exactly the wiring app.py does."""
    import app as A
    from ui.tray import TonyTray
    from ui.info_window import InfoWindow
    from ui.voice_worker import VoiceWorker

    worker = VoiceWorker()
    info = InfoWindow(on_turn_off=lambda: None)
    tray = TonyTray(on_open_info=info.present)
    worker.state_changed.connect(tray.set_state)
    worker.executed.connect(tray.show_response)
    worker.failed.connect(lambda text: tray.show_response(text, ok=False))
    worker.window_opened.connect(tray.on_window_opened)
    worker.window_closed.connect(tray.on_window_closed)
    icon = A._install_tray_icon(_app, tray)
    return worker, tray, icon


def test_every_session_event_reaches_the_tray_without_raising():
    worker, _tray, _icon = _wire()
    for event, arg in SESSION_EVENTS:
        worker._report(event, arg)
        _app.processEvents()


def test_worker_loads_the_real_command_set():
    worker, _tray, _icon = _wire()
    assert len(worker._commands) > 40      # the full registry, not an empty list
    assert any(c.name == "stop_listening" for c in worker._commands)


def test_no_worker_signal_lands_on_a_bare_lambda():
    """THE freeze. A signal connected to a bare lambda has no receiver QObject, so
    Qt runs it **in the emitting thread** — the voice worker was building and
    animating widgets itself, which is undefined behaviour in Qt and wedged the GUI
    thread. Confirmed from a live py-spy dump of the frozen process:

        Thread "Dummy-1" (the worker):
            _enter        (ui/tray.py)
            show_message  (ui/tray.py)
            show_response (ui/tray.py)
            <lambda>      (app.py:101)     <-- here
            _report       (ui/voice_worker.py)

    Every worker signal must land on a bound method of a GUI-thread QObject.
    """
    import ast
    import inspect
    import app as A

    src = inspect.getsource(A.main)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"):
            continue
        target = node.func.value
        # only signals coming off the worker matter — the GUI's own timers are fine
        if not (isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "worker"):
            continue
        arg = node.args[0] if node.args else None
        assert not isinstance(arg, (ast.Lambda, ast.Call)), (
            f"worker.{target.attr} is connected to a lambda — it will run on the "
            f"worker thread and touch widgets from there")
        assert isinstance(arg, ast.Attribute), (
            f"worker.{target.attr} must connect to a bound method of a GUI QObject")


def test_a_second_launch_reveals_the_running_copy_instead_of_dying_quietly():
    """Clicking the desktop icon while TONY runs must show TONY. It used to exit in
    silence, which is indistinguishable from "the app won't start" — the founder hit
    exactly that, and Task Manager showed it running the whole time.

    Also pins that importing app.py has no side effects: the guard belongs in main(),
    or these tests can't even build the objects while TONY is running.
    """
    import importlib
    import uuid
    from tools import launch

    importlib.reload(launch)          # fresh handles for this check
    # Its own names: a real TONY running on this machine holds the production mutex,
    # and the test would then be asserting against the founder's live app.
    tag = uuid.uuid4().hex[:8]
    launch._MUTEX_NAME = f"Local\\TONY_test_{tag}"
    launch._WAKE_EVENT_NAME = f"Local\\TONY_test_show_{tag}"

    assert launch.already_running() is False, "first acquire must be free"
    assert launch.show_requested() is False, "nobody has asked yet"

    assert launch.already_running() is True, "second acquire sees the live copy"
    assert launch.show_requested() is True, "…and asks it to reveal itself"
    assert launch.show_requested() is False, "the request auto-resets: one per click"


def test_glow_follows_listening_state():
    """The whole UI is now one signal: glowing means TONY is listening."""
    worker, tray, _icon = _wire()
    worker._report("window_open")
    _app.processEvents()
    assert tray._glow_on is True
    worker._report("window_closed")
    _app.processEvents()
    assert tray._glow_on is False


def test_tray_icon_offers_a_way_out():
    """The overlay is frameless and stays out of alt-tab: without this menu the
    only way to stop TONY is Task Manager — and it starts on boot.

    The menu must also SURVIVE: setContextMenu doesn't take ownership, so an
    unparented QMenu is garbage-collected and right-click silently does nothing —
    which is exactly what the founder hit.
    """
    _worker, _tray, icon = _wire()
    import gc
    gc.collect()
    menu = icon.contextMenu()
    assert menu is not None and menu.parent() is not None, "menu will be GC'd"
    labels = [a.text() for a in menu.actions() if a.text()]
    assert any("Turn off" in l for l in labels), labels
