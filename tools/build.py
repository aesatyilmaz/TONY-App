"""Build TONY App into a double-clickable Windows app.

    pip install pyinstaller
    python tools/build.py

Writes `dist/TONY App/`, containing `TONY App.exe` and everything it needs. Zip that
folder and anyone on Windows can unzip it and run it — no Python, no pip.

Afterwards, check the build without launching it:

    "dist/TONY App/TONY App.exe" --selftest

That paints the real UI offscreen, reads every bundled asset and loads the hand model.
Everything that breaks in a bundle and nowhere else is a file that is not Python, and
that is the fastest way to find out you shipped one that is missing.

Notes on the choices here:

* **One-folder, not one-file.** A one-file build unpacks its whole payload to a temp
  directory on every launch — for a bundle this size that is a visible wait, and TONY
  starts with Windows. Single-file executables are also what antivirus heuristics flag.
* **`--windowed`,** so there is no console window. TONY already survives having no
  stdout (`tools/launch.log_setup` redirects to tony.log) because that is exactly the
  situation under pythonw.exe.
* **torch is excluded.** faster-whisper only uses it to detect CUDA and falls back to
  the CPU without it, and bundling it would add four gigabytes for that one check.
* **Models are not bundled.** Vosk and Whisper download theirs on first run (~540 MB
  total) into the user's own cache. Shipping them would quadruple the download for
  everyone, including people who already have them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "TONY App"
ICON = ROOT / "ui" / "assets" / "tony.ico"

# MediaPipe's graphs are loaded at runtime by path, so a bundler that only follows
# imports leaves them out: the app then builds, starts, opens the camera and dies the
# moment a hand appears. Only the hand and palm models — the face, pose and iris
# models in the same folder are another 20 MB this app never asks for.
_MP_MODULES = ("hand_landmark", "palm_detection")

# mediapipe's package ships model_maker and the genai converters alongside the
# solutions we use, and those import machine-learning stacks we do not. PyInstaller
# follows static imports whether or not they ever run, so without this list the build
# comes out at 1.6 GB carrying jaxlib (205 MB), torch (131 MB), playwright with its own
# copy of Node (98 MB) and spaCy (77 MB) — none of which TONY touches. Excluding them
# takes it to about a third of that.
#
# Nothing here is guesswork about what is needed: `--selftest` on the built exe paints
# the UI, reads every asset and loads the hand model, and would fail loudly if one of
# these were actually required.
EXCLUDES = (
    "torch", "torchvision", "torchaudio",       # faster-whisper only probes it for CUDA
    "jax", "jaxlib", "tensorflow", "tensorflow_hub", "keras", "tf_keras",
    "spacy", "thinc", "playwright", "pandas", "scipy",
    "IPython", "jupyter", "notebook", "pytest",
)
# matplotlib is deliberately NOT in that list, however unused it looks:
# `mediapipe.solutions` imports drawing_utils in its package __init__, so reaching for
# mp.solutions.hands pulls matplotlib in. Excluding it builds fine and then fails on
# launch with ModuleNotFoundError.


def _data(src: Path, dest: str) -> list[str]:
    if not src.exists():
        sys.exit(f"missing build input: {src}")
    return ["--add-data", f"{src}{os.pathsep}{dest}"]


def data_files() -> list[str]:
    import mediapipe
    mp_root = Path(mediapipe.__file__).parent
    out: list[str] = []
    out += _data(ROOT / "ui" / "assets", "ui/assets")
    fonts = ROOT / "ui" / "fonts"
    if fonts.is_dir():
        out += _data(fonts, "ui/fonts")
    for mod in _MP_MODULES:
        out += _data(mp_root / "modules" / mod, f"mediapipe/modules/{mod}")
    return out


def main() -> None:
    for stale in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", NAME,
        "--icon", str(ICON),
        *(a for m in EXCLUDES for a in ("--exclude-module", m)),
        *data_files(),
        str(ROOT / "app.py"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)

    out = ROOT / "dist" / NAME
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"\n{out}  —  {size / 1024 / 1024:.0f} MB")
    print(f'Now check it:  "{out / (NAME + ".exe")}" --selftest')


if __name__ == "__main__":
    main()
