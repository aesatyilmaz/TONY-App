"""Configuration. One source of defaults; config/settings.json overrides any of them.

settings.json is gitignored — it is where personal values live (the dashboard URL, a
Claude install path) so this file stays publishable.
"""
from __future__ import annotations
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # the repo root
_OVERRIDE = Path(__file__).resolve().parent / "settings.json"

# ponytail: flat dict — TONY is voice command-and-control (no LLM, no TTS).
DEFAULTS: dict = {
    "wake_word": "tony",
    "vosk_model_path": None,           # None → vosk Model(lang="en-us") (first run downloads)
    "stt_model": "small",              # faster-whisper; better accuracy, still light
    "stt_language": "en",
    "command_max_seconds": 8.0,        # command recording cap
    "command_silence_seconds": 1.0,    # this much silence = command done
    # Active window: after "Tony", keep listening this long WITHOUT the wake word.
    # Rolling: each executed command resets the timer (spec §2).
    "active_window_seconds": 20.0,
    # Dictation ends itself after this much silence — a mode that outlives the
    # founder leaving the desk types the next conversation into whatever has focus.
    # Short on purpose (his call): re-entering costs two words, and the exit only
    # counts silence, so it never cuts a sentence you are in the middle of.
    "type_mode_idle_seconds": 5.0,
    # --- command tuning knobs (spec §2.2; editable later from the UI settings) ---
    "volume_step": 5,                  # VK_VOLUME_UP presses per command (1 press ≈ 2%)
    "scroll_amount": 10,               # scroll strength (control.scroll multiplies ×100)
    "fuzzy_threshold": 86,             # rapidfuzz WRatio 0-100; below this = ignore (calibrated, plan Task 4 Step 4)
    # --- app launch targets (spec §5 "Open") ---
    "gmail_urls": [
        "https://mail.google.com/mail/u/0/#inbox",
        "https://mail.google.com/mail/u/1/#inbox",
    ],
    # Personal — set yours in config/settings.json (gitignored); this repo is public.
    "dashboard_url": "",
    "translate_to": "tr",              # "translate this" target language
    # Claude desktop app; resolved with fallback in actions/apps.py.
    "claude_path": None,               # None → try default install path then `start claude`
    "activate_hotkey": "ctrl+alt+t",   # alternate trigger to wake word (Task 8)
    "gallery_dir": None,               # None → BASE_DIR/gallery (screenshot command)
    "custom_triggers": {},             # {command_name: [extra trigger words]} — UI Settings "+ add"
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if _OVERRIDE.exists():
        try:
            cfg.update(json.loads(_OVERRIDE.read_text(encoding="utf-8")))
        except Exception as e:  # a malformed JSON file must not take the app down
            print(f"[config] could not read settings.json, using defaults: {e}")
    return cfg


if __name__ == "__main__":
    c = load()
    assert c["wake_word"] == "tony"
    assert c["active_window_seconds"] == 20.0
    assert 0 < c["fuzzy_threshold"] <= 100
    assert len(c["gmail_urls"]) == 2
    print("config OK:", {k: c[k] for k in ("wake_word", "stt_model", "active_window_seconds")})
