"""TONY App command registry — the single source of truth (spec §5).

Each Command: trigger phrases (fuzzy-matched by router.py) → run(cfg) that calls an
existing action handler, plus a fixed `response` string for UI feedback (no TTS).
ponytail: this is DATA. Adding a command = one entry, no new plumbing.
"""
from __future__ import annotations
import ctypes
import os
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

from actions import apps, web, control, screen_record, volume
from config import settings
import vision


@dataclass(frozen=True)
class Command:
    name: str
    triggers: tuple[str, ...]
    response: Callable[[dict], str]     # feedback text for the UI (takes cfg)
    run: Callable[[dict], object]       # executes the action (return value ignored)
    # "listen for one more thing, then run". The loop captures a single utterance and
    # hands it over as cfg["phrase"] — a spoken ARGUMENT, not a mode. Saying
    # "research" and then a question is one thought; a mode you have to leave is two.
    wants_phrase: bool = False


def _k(text: str) -> Callable[[dict], str]:
    """Constant response."""
    return lambda cfg: text


# --- helpers that compose the existing action handlers ---
def _hotkey(combo: str):
    return lambda cfg: control.press_hotkey(combo)


def _media(action: str):
    return lambda cfg: control.media_control(action)


def _volume_percent(cfg) -> int:
    """How much to move the volume, as a percentage.

    Spoken amount wins ("volume down 40" → 40), otherwise the configured step.
    One Windows volume-key press is ~2%, which is what turns this into presses.
    """
    said = cfg.get("amount")
    if said:
        return max(2, min(100, int(said)))
    return max(1, int(cfg["volume_step"])) * 2


def _volume(sign: int):
    """sign +1 raises, -1 lowers — by an exact percentage (see actions/volume.py)."""
    return lambda cfg: volume.change(sign * _volume_percent(cfg))


def _scroll(direction: str):
    return lambda cfg: control.scroll(direction, amount=cfg["scroll_amount"])


def _open_app(name: str):
    return lambda cfg: apps.open_app(name)


def _open_url(url_key: str = None, url: str = None):
    def run(cfg):
        web.open_url(url or cfg[url_key])
    return run


def _open_gmail(cfg):
    for u in cfg["gmail_urls"]:
        web.open_url(u)


def _open_claude(cfg):
    """Launch the Claude DESKTOP app.

    Never `shutil.which("claude")`. That finds the Claude Code CLI on PATH, and
    launching it opened a terminal — which is what the founder was getting instead
    of the app he asked for. The CLI and the app share a name and nothing else.

    The desktop app ships as an MSIX package, so there is no .exe on disk to point
    at: it is launched through its AppUserModelID via the Apps folder, which is what
    the Start menu itself does. `claude_path` still wins if it is set, for a
    classic-installer machine.
    """
    path = cfg.get("claude_path")
    if path and os.path.exists(path):
        os.startfile(path)  # type: ignore[attr-defined]
        return
    for aumid in _claude_aumids():
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{aumid}"])
            return
        except Exception:
            continue
    raise RuntimeError("the Claude desktop app is not installed — set claude_path")


_PKG_REPO = (r"Software\Classes\Local Settings\Software\Microsoft\Windows"
             r"\CurrentVersion\AppModel\Repository\Packages")


def _claude_aumids() -> list[str]:
    """Every installed Claude app's AppUserModelID.

    Read from the package repository rather than written down, because the family
    name carries a per-machine publisher hash — `Claude_pzs8sxrjxfjjc` is this
    computer's, and a literal would work on exactly one machine. Package full names
    look like `Claude_1.24012.9.0_x64__pzs8sxrjxfjjc`; the family is the first field
    and the last, rejoined.
    """
    import winreg
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PKG_REPO) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                full = winreg.EnumKey(k, i)
                if full.lower().startswith("claude_"):
                    out.append(f"{package_family(full)}!Claude")
    except OSError:
        pass
    return out


def package_family(full_name: str) -> str:
    """`Claude_1.24012.9.0_x64__pzs8sxrjxfjjc` → `Claude_pzs8sxrjxfjjc`."""
    parts = full_name.split("_")
    return f"{parts[0]}_{parts[-1]}"


def _copy_selection() -> str:
    """Copy whatever is selected in the focused app and hand it back.

    The clipboard is emptied first on purpose. Without that there is no way to tell
    "nothing was selected" from "the selection happens to be what was already on the
    clipboard", and the difference matters — one should search, the other should say
    so. If nothing arrives, the old contents go back: TONY does not get to quietly
    eat what the founder had copied.
    """
    import pyperclip
    before = pyperclip.paste()
    pyperclip.copy("")
    control.press_hotkey("ctrl+c")
    for _ in range(25):          # the focused app owns the clipboard; give it a moment
        time.sleep(0.02)
        got = pyperclip.paste()
        if got.strip():
            return got.strip()
    pyperclip.copy(before)
    return ""


def _selection_to(url_template: str):
    """Send the current selection somewhere on the web. `{q}` is the text, `{to}` the
    target language. Truncated: a URL is not a place to put an essay, and every
    search engine ignores the tail anyway."""
    def run(cfg):
        text = _copy_selection()
        if not text:
            raise RuntimeError("nothing is selected")
        web.open_url(url_template.format(q=quote_plus(text[:1500]),
                                         to=cfg.get("translate_to") or "tr"))
    return run


def _phrase_to(url_template: str):
    """Send a SPOKEN phrase somewhere on the web. The sibling of _selection_to, for
    when nothing is selected because the thought is still in your head."""
    def run(cfg):
        q = (cfg.get("phrase") or "").strip()
        if not q:
            raise RuntimeError("nothing to look up")
        web.open_url(url_template.format(q=quote_plus(q[:1500]),
                                         to=cfg.get("translate_to") or "tr"))
    return run


def _clear_field(cfg):
    """Select all, then delete — the "no, start over" of dictation."""
    control.press_hotkey("ctrl+a")
    control.press_key("delete")


def _open_gallery(cfg):
    d = gallery_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(str(d))  # type: ignore[attr-defined]


def _close_window(cfg):
    """WM_CLOSE the foreground window — reliable across classic AND modern/UWP
    apps (alt+f4 key synthesis gets swallowed by some, e.g. Windows 11 Notepad)."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def gallery_dir(cfg) -> Path:
    # settings.BASE_DIR, not this file's folder: in a packaged build captures must land
    # next to the .exe, where the founder can find them, not inside the bundle.
    return Path(cfg.get("gallery_dir") or (settings.BASE_DIR / "gallery"))


def _capture_monitor(cfg):
    """Full-monitor screenshot of whichever monitor the foreground window is on."""
    from PIL import ImageGrab
    x, y, w, h = screen_record.active_monitor_rect()
    bbox = (x, y, x + w, y + h)
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    base = gallery_dir(cfg) / "screenshots"
    base.mkdir(parents=True, exist_ok=True)
    img.save(str(base / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"))


def build_commands() -> list[Command]:
    C = Command
    return [
        # --- Session control ---
        C("stop_listening", ("stop listening", "stop", "stop it"),
          _k("stopped listening"), lambda cfg: None),
        # Quitting by voice. Deliberately only multi-word phrases: a bare "turn off"
        # sits too close to "turn it down" / "sound off" to risk on an action that
        # can't be undone by saying something else. Note the router strips "tony" as
        # filler, so a trigger must still read correctly WITHOUT it — "turn off tony"
        # arrives here as "turn off", which is exactly what we don't want to match.
        C("turn_off", ("turn off yourself", "turn yourself off", "shut yourself down",
                       "switch yourself off"),
          _k("turning off"), lambda cfg: None),
        # Run by session.execute, which swaps in the previous command before this
        # one's own response or run is ever reached — so the popup reports what
        # actually happened, and a spoken amount rides along ("volume down 40",
        # then "again", then "again").
        # ("one more" is not a trigger here and cannot be: the router strips number
        # words from anywhere in an utterance so "volume down one" still matches, so
        # "one more" arrives as "more". test_router pins that rule for every trigger.)
        C("repeat", ("again", "do that again", "same again", "repeat that"),
          _k("again"), lambda cfg: None),
        # --- Media & System ---
        C("volume_up", ("volume up", "louder", "turn it up", "increase volume"),
          lambda cfg: f"increased volume by {_volume_percent(cfg)}%", _volume(+1)),
        C("volume_down", ("volume down", "quieter", "turn it down", "lower volume"),
          lambda cfg: f"decreased volume by {_volume_percent(cfg)}%", _volume(-1)),
        C("mute", ("mute", "unmute", "silence", "sound off", "sound on"),
          _k("toggled mute"), _media("mute")),
        C("play_pause", ("pause", "play", "resume", "pause track"),
          _k("play / pause"), _media("playpause")),
        C("next_track", ("next track", "next song", "skip song"),
          _k("next track"), _media("next")),
        C("prev_track", ("previous track", "previous song", "last song"),
          _k("previous track"), _media("previous")),
        # --- Scroll ---
        C("scroll_down", ("scroll down", "go down"),
          _k("scrolled down"), _scroll("down")),
        C("scroll_up", ("scroll up", "go up"),
          _k("scrolled up"), _scroll("up")),
        # --- Zoom ---
        C("zoom_in", ("zoom in", "bigger", "enlarge"),
          _k("zoomed in"), _hotkey("ctrl+=")),
        C("zoom_out", ("zoom out", "smaller"),
          _k("zoomed out"), _hotkey("ctrl+-")),
        C("zoom_reset", ("reset zoom", "actual size", "default zoom"),
          _k("reset zoom"), _hotkey("ctrl+0")),
        # --- Tabs & browser nav ---
        C("new_tab", ("new tab", "open a tab"), _k("opened a new tab"), _hotkey("ctrl+t")),
        C("close_tab", ("close tab", "close this tab"), _k("closed the tab"), _hotkey("ctrl+w")),
        C("next_tab", ("next tab", "switch tab"), _k("next tab"), _hotkey("ctrl+tab")),
        C("prev_tab", ("previous tab", "last tab"), _k("previous tab"), _hotkey("ctrl+shift+tab")),
        C("reopen_tab", ("reopen tab", "restore tab", "reopen closed tab"),
          _k("reopened the last tab"), _hotkey("ctrl+shift+t")),
        C("refresh", ("refresh", "reload", "reload page"), _k("refreshed"), _hotkey("f5")),
        C("nav_back", ("go back", "previous page", "back"), _k("went back"), _hotkey("alt+left")),
        C("nav_forward", ("go forward", "next page", "forward"), _k("went forward"), _hotkey("alt+right")),
        # --- Windows ---
        C("close_window", ("close window", "close app", "close this"),
          _k("closed the window"), _close_window),
        C("minimize", ("minimize", "minimize window"), _k("minimized"), _hotkey("win+down")),
        C("maximize", ("maximize", "maximize window"), _k("maximized"), _hotkey("win+up")),
        C("show_desktop", ("show desktop", "minimize everything"),
          _k("showing desktop"), _hotkey("win+d")),
        C("snap_left", ("snap left", "dock left"), _k("snapped left"), _hotkey("win+left")),
        C("snap_right", ("snap right", "dock right"), _k("snapped right"), _hotkey("win+right")),
        C("switch_window", ("switch window", "next window", "last window", "alt tab"),
          _k("switched window"), _hotkey("alt+tab")),
        # --- Editing (clipboard) ---
        C("copy", ("copy",), _k("copied"), _hotkey("ctrl+c")),
        C("paste", ("paste",), _k("pasted"), _hotkey("ctrl+v")),
        C("cut", ("cut",), _k("cut"), _hotkey("ctrl+x")),
        C("select_all", ("select all",), _k("selected all"), _hotkey("ctrl+a")),
        C("clear_field", ("clear this", "clear it", "wipe this", "start over"),
          _k("cleared"), _clear_field),
        # --- Do something with what's selected ---
        C("search_this", ("search this", "search that", "look this up", "google this"),
          _k("searching that"),
          _selection_to("https://www.google.com/search?q={q}")),
        C("research", ("research", "look up", "search for"),
          lambda cfg: f"searching “{(cfg.get('phrase') or '').strip()}”",
          _phrase_to("https://www.google.com/search?q={q}"), wants_phrase=True),
        C("translate_this", ("translate this", "translate that"),
          _k("translating that"),
          _selection_to("https://translate.google.com/?sl=auto&tl={to}"
                        "&text={q}&op=translate")),
        C("undo", ("undo",), _k("undone"), _hotkey("ctrl+z")),
        C("redo", ("redo",), _k("redone"), _hotkey("ctrl+y")),
        C("enter", ("enter", "press enter", "hit enter"),
          _k("pressed enter"), lambda cfg: control.press_key("enter")),
        C("space", ("space", "press space", "hit space", "spacebar"),
          _k("pressed space"), lambda cfg: control.press_key("space")),
        C("save", ("save", "save this", "save it", "save file"),
          _k("saved"), _hotkey("ctrl+s")),
        # Handled by the session loop, which stops routing and starts typing — see
        # session.type_mode. The triggers deliberately share no shape with the exit
        # phrases: "start typing" and "stop typing" differ by two characters, which
        # is well inside what the STT gets wrong.
        C("type_mode", ("type mode", "typing mode", "dictation mode"),
          _k("type mode"), lambda cfg: None),
        # --- Capture ---
        C("screenshot", ("screenshot", "take a screenshot"),
          _k("print screen"), lambda cfg: control.press_key("printscreen")),
        C("capture_window", ("capture window", "capture screen", "screen grab"),
          _k("captured the screen to gallery"), _capture_monitor),
        C("start_recording", ("start recording", "record screen", "screen record"),
          _k("recording started"),
          lambda cfg: screen_record.start_recording(gallery_dir(cfg) / "recordings")),
        C("stop_recording", ("stop recording", "stop record"),
          _k("recording saved"), lambda cfg: screen_record.stop_recording()),
        C("open_gallery", ("open gallery", "show gallery", "open captures"),
          _k("opened the gallery"), _open_gallery),
        # --- Open (URL / app) ---
        C("open_google", ("open google", "open chrome", "google"),
          _k("opened Chrome"), _open_app("chrome")),
        C("open_folder", ("open folder", "file explorer", "open explorer"),
          _k("opened File Explorer"), _open_app("explorer")),
        C("open_notepad", ("notepad", "open notepad"),
          _k("opened Notepad"), _open_app("notepad")),
        C("open_settings", ("open settings", "windows settings", "settings"),
          _k("opened Settings"), _open_app("settings")),
        C("open_task_manager", ("open task manager", "task manager"),
          _k("opened Task Manager"), _open_app("task manager")),
        C("open_gmail", ("open mail", "open gmail", "check mail", "emails"),
          _k("opened Gmail"), _open_gmail),
        # Whisper reliably hears "claude" as "cloud" — cheaper to accept the
        # mishearing as a trigger than to make the founder say something unnatural.
        C("open_claude", ("open claude", "claude", "open cloud", "cloud", "claude ai"),
          _k("opened Claude"), _open_claude),
        C("open_youtube", ("open youtube", "youtube"),
          _k("opened YouTube"), _open_url(url="youtube.com")),
        C("open_linkedin", ("open linkedin", "linkedin"),
          _k("opened LinkedIn"), _open_url(url="linkedin.com")),
        C("open_indeed", ("open indeed", "indeed", "jobs"),
          _k("opened Indeed"), _open_url(url="indeed.com")),
        C("open_spotify", ("open spotify", "spotify"),
          _k("opened Spotify"), _open_url(url="open.spotify.com")),
        C("open_maps", ("open maps", "maps", "google maps"),
          _k("opened Maps"), _open_url(url="https://maps.google.com/")),
        C("open_dashboard", ("open dashboard", "dashboard"),
          _k("opened the dashboard"), _open_url(url_key="dashboard_url")),
        # No response text on either: vision mode opening and closing IS the pill growing
        # and shrinking, so a popup would only say what the founder is already
        # watching happen — and it would say it anchored to a tray that is mid-resize,
        # which is how it ended up orphaned in the middle of the screen. Failure still
        # speaks: open_vision raises, and that goes through the "failed" popup.
        C("open_vision", ("open vision", "vision mode", "launch vision", "start vision"),
          _k(""), lambda cfg: vision.open_vision()),
        # Not "close vision mode": "vision mode" is open_vision's own trigger, and
        # WRatio scores a trigger that sits whole inside the transcript ~90 — well over
        # the threshold — so asking to close it could open it instead.
        C("close_vision", ("close vision", "stop vision", "turn off vision"),
          _k(""), lambda cfg: vision.close_vision()),
    ]


# How the command list is presented to the user (UI info panel). Related commands
# share a row so the reference card stays short. Kept here, next to the registry,
# so there is one source of truth; test_router asserts every command is covered.
GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Session",       ("stop_listening", "turn_off", "repeat")),
    ("Volume",        ("volume_up", "volume_down", "mute")),
    ("Playback",      ("play_pause", "next_track", "prev_track")),
    ("Scroll",        ("scroll_down", "scroll_up")),
    ("Zoom",          ("zoom_in", "zoom_out", "zoom_reset")),
    ("Tabs",          ("new_tab", "close_tab", "next_tab", "prev_tab", "reopen_tab")),
    ("Page",          ("refresh", "nav_back", "nav_forward")),
    ("Windows",       ("close_window", "minimize", "maximize", "show_desktop",
                       "snap_left", "snap_right", "switch_window")),
    ("Clipboard",     ("copy", "paste", "cut", "select_all", "clear_field")),
    ("Selection",     ("search_this", "translate_this", "research")),
    ("Undo",          ("undo", "redo")),
    ("Keys",          ("enter", "space", "save")),
    ("Dictation",     ("type_mode",)),
    ("Screenshot",    ("screenshot", "capture_window")),
    ("Recording",     ("start_recording", "stop_recording", "open_gallery")),
    ("Apps",          ("open_google", "open_folder", "open_notepad", "open_settings",
                       "open_task_manager", "open_claude")),
    # Spotify is deliberately the web player, so it belongs with the sites, not the apps.
    ("Websites",      ("open_gmail", "open_youtube", "open_linkedin", "open_indeed",
                       "open_spotify", "open_maps", "open_dashboard")),
    ("Vision mode",   ("open_vision", "close_vision")),
]


def grouped(commands: list[Command]) -> list[tuple[str, list[Command]]]:
    """[(group label, [Command, ...])] in GROUPS order — what the UI renders."""
    by_name = {c.name: c for c in commands}
    out = []
    for label, names in GROUPS:
        members = [by_name[n] for n in names if n in by_name]
        if members:
            out.append((label, members))
    return out


def apply_custom_triggers(commands: list[Command], cfg: dict) -> list[Command]:
    """Merge user-added trigger words (cfg['custom_triggers']: {command_name: [words]})."""
    extra = cfg.get("custom_triggers")
    if not isinstance(extra, dict) or not extra:
        return commands                       # hand-edited JSON shouldn't crash startup
    taken = {t: c.name for c in commands for t in c.triggers}   # never shadow a built-in
    out = []
    for c in commands:
        words = extra.get(c.name) or []
        if isinstance(words, str):            # {"volume_up": "make it loud"} — not a list
            words = [words]
        more = tuple(w.strip().lower() for w in words if isinstance(w, str) and w.strip())
        new = tuple(m for m in more if m not in taken)
        out.append(replace(c, triggers=c.triggers + new) if new else c)
        taken.update({m: c.name for m in new})
    return out
