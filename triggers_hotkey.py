"""Global hotkey trigger — press to open the active window without saying 'Tony'.

Uses the `keyboard` lib (already a dep). Default combo ctrl+alt+t; override in config.
ponytail: a threading.Event the main loop can also wait on, alongside the wake word.
"""
from __future__ import annotations
import threading
import keyboard


def start_hotkey(combo: str, event: threading.Event) -> None:
    """Register `combo` to set `event` whenever pressed. Non-blocking."""
    keyboard.add_hotkey(combo, event.set)
    print(f"[hotkey] '{combo}' → activate")
