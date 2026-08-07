"""Computer use: keys, hotkeys, media keys and scrolling (pyautogui).

TONY's core power. Key names as a person says them are mapped onto the names
pyautogui expects — "windows", "escape" and "return" are not what it calls them.
"""
from __future__ import annotations

import pyautogui

# Spoken key names → pyautogui key names.
_KEY_ALIASES = {
    "win": "winleft", "windows": "winleft", "cmd": "winleft", "super": "winleft",
    "control": "ctrl", "escape": "esc", "return": "enter", "delete": "del",
}
_MEDIA = {
    "playpause": "playpause", "play": "playpause", "pause": "playpause",
    "next": "nexttrack", "previous": "prevtrack", "prev": "prevtrack",
    "volumeup": "volumeup", "volume up": "volumeup",
    "volumedown": "volumedown", "volume down": "volumedown",
    "mute": "volumemute",
}


def _norm(k: str) -> str:
    k = k.strip().lower()
    return _KEY_ALIASES.get(k, k)


def _split_combo(keys: str) -> list[str]:
    return [_norm(p) for p in keys.replace(" ", "").split("+") if p]


def press_hotkey(keys: str) -> str:
    parts = _split_combo(keys)
    if not parts:
        return "No keys given."
    pyautogui.hotkey(*parts)
    return f"Pressed {'+'.join(parts)}."


def type_text(text: str) -> str:
    if not text:
        return "No text given."
    pyautogui.write(text, interval=0.01)
    return f"Typed: {text[:60]}"


def press_key(key: str, count: int = 1) -> str:
    k = _norm(key)
    if not k:
        return "No key given."
    n = max(1, int(count))
    pyautogui.press(k, presses=n)
    return f"Pressed {k}" + (f" x{n}" if n > 1 else "") + "."


def media_control(action: str) -> str:
    key = _MEDIA.get((action or "").strip().lower())
    if not key:
        return f"Unknown media action: {action}. Use playpause/next/previous/volumeup/volumedown/mute."
    pyautogui.press(key)
    return f"Media: {action}."


def scroll(direction: str, amount: int = 3) -> str:
    d = (direction or "").strip().lower()
    if d not in ("up", "down"):
        return "Scroll direction must be 'up' or 'down'."
    clicks = max(1, int(amount)) * 100
    pyautogui.scroll(clicks if d == "up" else -clicks)
    return f"Scrolled {d}."
