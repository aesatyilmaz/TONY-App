"""Computer-use self-check — key parsing + media mapping (presses NO real keys).

Real pyautogui calls would type into the focused window, so only pure logic is tested here.
Run:  python -m pytest tests/test_control.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions import control  # noqa: E402


def test_combo_parsing_and_alias_normalization():
    assert control._split_combo("ctrl+c") == ["ctrl", "c"]
    assert control._split_combo("win + d") == ["winleft", "d"]
    assert control._split_combo("Alt+Tab") == ["alt", "tab"]
    assert control._norm("escape") == "esc"
    assert control._norm("Windows") == "winleft"


def test_media_mapping():
    assert control._MEDIA["mute"] == "volumemute"
    assert control._MEDIA["next"] == "nexttrack"
    assert control._MEDIA["prev"] == "prevtrack"


def test_invalid_input_returns_message_without_pressing_keys():
    assert control.press_hotkey("").startswith("No keys")
    assert control.scroll("sideways").startswith("Scroll direction")
    assert control.media_control("boop").startswith("Unknown media")
