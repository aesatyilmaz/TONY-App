"""Uygulama açma — Windows (2-Jarvis open_app.py'den port, İngilizce çıktı)."""
from __future__ import annotations
import os
import shutil
import subprocess

APP_ALIASES = {
    "edge": "msedge", "microsoft edge": "msedge",
    "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox",
    "terminal": "cmd", "cmd": "cmd", "powershell": "powershell",
    "explorer": "explorer", "file explorer": "explorer",
    "spotify": "Spotify", "vscode": "code", "vs code": "code", "code": "code",
    "discord": "Discord", "slack": "Slack", "whatsapp": "WhatsApp",
    "telegram": "Telegram", "zoom": "Zoom", "notepad": "notepad",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "calculator": "calc", "task manager": "taskmgr",
    "settings": "ms-settings:", "paint": "mspaint", "wordpad": "wordpad",
    "snipping tool": "SnippingTool", "photos": "ms-photos:", "maps": "bingmaps:",
    "mail": "outlookmail:", "calendar": "outlookcal:", "store": "ms-windows-store:",
    "music": "mswindowsmusic:", "notion": "Notion",
    "claude": "claude", "claude ai": "claude",
}
URI_SCHEMES = {"ms-settings:", "ms-photos:", "bingmaps:", "outlookmail:",
               "outlookcal:", "ms-windows-store:", "mswindowsmusic:"}


def open_app(app_name: str) -> str:
    if not app_name:
        return "No application name given."
    resolved = APP_ALIASES.get(app_name.lower().strip(), app_name)

    if any(resolved.startswith(s) for s in URI_SCHEMES):
        try:
            os.startfile(resolved)  # type: ignore[attr-defined]
            return f"Opened {app_name}."
        except Exception as e:
            return f"Could not open '{app_name}': {e}"

    exe = shutil.which(resolved)
    if exe:
        try:
            subprocess.Popen([exe], shell=False)
            return f"Opened {app_name}."
        except Exception as e:
            return f"Could not open '{app_name}': {e}"

    # ponytail: no `start "" "<name>"` via shell=True here. os.startfile below is
    # ShellExecute — it already resolves Start-menu names and App Paths, so the shell
    # branch was redundant, and a name containing a quote would have escaped the
    # quoting into arbitrary commands the day someone wires this to a config value.
    try:
        os.startfile(resolved)  # type: ignore[attr-defined]
        return f"Opened {app_name}."
    except Exception as e:
        return f"'{app_name}' not found or could not be opened: {e}"
