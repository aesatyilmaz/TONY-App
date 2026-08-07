"""TONY App — headless voice command-and-control (the UI lives in app.py).

Flow:  "Tony" (wake) → 20s rolling active window → Whisper STT → fuzzy router → run action.
No LLM, no TTS, no chat. Usage:
    python main.py            # voice mode
    python main.py text       # keyboard mode (mic-free router test)
"""
from __future__ import annotations
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # torch+ctranslate2 OpenMP
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import settings          # noqa: E402
from commands import build_commands, apply_custom_triggers  # noqa: E402
from router import match              # noqa: E402

_COMMANDS = build_commands()


def _handle(text: str, cfg: dict):
    """Route one transcript. Returns the matched Command, or None."""
    cmd = match(text, _COMMANDS, cfg["fuzzy_threshold"])
    if cmd is None:
        print(f"🚫 no match: {text!r}")
        return None
    print(f"👤 {text!r} → ⚡ {cmd.name}")
    cmd.run(cfg)
    print(f"🤖 {cmd.response(cfg)}")
    return cmd


def run_text_mode(cfg: dict) -> None:
    print("⌨️  Keyboard mode. Exit: empty line / Ctrl+C.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        _handle(text, cfg)


def run_voice_mode(cfg: dict) -> None:
    """Console mode — the shared loop in session.py, reporting to stdout."""
    from session import run_session

    window = cfg["active_window_seconds"]
    printers = {
        "ready":         lambda a: print("✅ TONY ready. Say 'Tony' or press the hotkey.  (Exit: Ctrl+C)"),
        "window_open":   lambda a: print(f"🔵 Active window open ({window:.0f}s)."),
        "window_closed": lambda a: print("⏱️  Active window closed."),
        "heard":         lambda a: print(f"👤 {a!r}"),
        "executed":      lambda a: print(f"🤖 {a}"),
        "no_match":      lambda a: print(f"🚫 no match: {a!r}"),
        "failed":        lambda a: print(f"⚠️  action failed — {a}"),
        "shutdown":      lambda a: print("🛑 turning off, as asked."),
    }
    run_session(cfg, _COMMANDS, lambda event, arg=None: printers.get(event, lambda a: None)(arg))


def main() -> None:
    global _COMMANDS
    # There is no pill out here, so vision mode gets its own window instead of drawing
    # into one that does not exist. Left embedded, "open vision" in console mode
    # turns the camera on and shows nothing at all.
    import vision
    vision.EMBED = False
    cfg = settings.load()
    _COMMANDS = apply_custom_triggers(_COMMANDS, cfg)  # once, not per-transcript
    text_mode = len(sys.argv) > 1 and sys.argv[1].lower() == "text"
    try:
        (run_text_mode if text_mode else run_voice_mode)(cfg)
    except KeyboardInterrupt:
        pass
    print("\n👋 TONY closed.")


if __name__ == "__main__":
    main()
