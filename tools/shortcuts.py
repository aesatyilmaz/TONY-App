"""Windows shortcuts for TONY — a desktop icon and/or start-on-boot.

User-level only: no admin, no registry. Both are just a .lnk pointing at
`pythonw.exe app.py` with the TONY icon, one on the Desktop and one in the
Startup folder.

Usage:
    python tools/shortcuts.py --desktop        # put TONY on the Desktop
    python tools/shortcuts.py --startup        # also launch it on boot
    python tools/shortcuts.py --status         # what's installed (read-only)
    python tools/shortcuts.py --remove         # remove both
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent           # the repo root
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
ICON = PROJECT_DIR / "ui" / "assets" / "tony.ico"

DESKTOP = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "TONY.lnk"
STARTUP = (Path(os.environ.get("APPDATA", "")) /
           r"Microsoft\Windows\Start Menu\Programs\Startup" / "TONY.lnk")


def _ps_quote(p) -> str:
    """Escape for a PowerShell single-quoted string (a path may contain an apostrophe)."""
    return str(p).replace("'", "''")


def _create(link: Path) -> None:
    if not PYTHONW.exists():
        sys.exit(f"pythonw.exe not found next to {sys.executable} — "
                 "run this with the Python you want TONY to start with.")
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{_ps_quote(link)}'); "
        f"$s.TargetPath = '{_ps_quote(PYTHONW)}'; "
        f"$s.Arguments = '\"{_ps_quote(PROJECT_DIR / 'app.py')}\"'; "
        f"$s.WorkingDirectory = '{_ps_quote(PROJECT_DIR)}'; "
        f"$s.Description = 'TONY - local voice command and control'; "
        + (f"$s.IconLocation = '{_ps_quote(ICON)}'; " if ICON.exists() else "")
        + "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True)
    print(f"  created {link}" if link.exists() else f"  FAILED to create {link}")


def _remove(link: Path) -> None:
    if link.exists():
        link.unlink()
        print(f"  removed {link}")
    else:
        print(f"  nothing at {link}")


def status() -> None:
    for name, link in (("Desktop", DESKTOP), ("Startup", STARTUP)):
        print(f"{name:8} {'installed  ' if link.exists() else 'not installed  '}{link}")
    if not ICON.exists():
        print(f"note: icon missing at {ICON} — shortcuts will use the Python icon.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--desktop", action="store_true", help="create the Desktop shortcut")
    p.add_argument("--startup", action="store_true", help="launch TONY on boot")
    p.add_argument("--remove", action="store_true", help="remove both shortcuts")
    p.add_argument("--status", action="store_true", help="report what's installed")
    a = p.parse_args()
    if not any((a.desktop, a.startup, a.remove, a.status)):
        p.print_help()
        return
    if a.remove:
        print("Removing TONY shortcuts:")
        _remove(DESKTOP); _remove(STARTUP)
        return
    if a.desktop:
        print("Desktop shortcut:")
        _create(DESKTOP)
    if a.startup:
        print("Start on boot:")
        _create(STARTUP)
    if a.status:
        status()


if __name__ == "__main__":
    main()
