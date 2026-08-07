"""Design tokens (docs/UI-DESIGN.md §7.0), font resolution, and the QSS builder.

Two hard Qt lessons are baked in here:

1. **QSS font fallback chains do not work.** `font-family: 'Lora', serif` does NOT
   walk the list — Qt hands the whole string to QFont and, when nothing matches,
   lands on the default UI face (Tahoma on this machine). That silently turned the
   entire vintage-serif design into a sans. Fonts are therefore resolved *once*
   against QFontDatabase.families() (`family()`) and handed out as real QFonts
   (`font()`); QSS below carries colour/border/radius only, never a font.
2. **QSS has no letter-spacing.** The tracked uppercase labels are core to the
   look, so tracking comes from QFont.setLetterSpacing via `font(tracking=...)`.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

# ── palette (exact hex from design §7.0) ──────────────────────────────────────
CREAM   = "#F4ECDD"; CREAM2 = "#EDE3D0"; BEIGE = "#DCCDB0"; WHITE = "#FBF7EF"
BROWN   = "#5A4632"; BROWN_SOFT = "#8A745A"; BLACK = "#1E1A15"
GOLD    = "#C9A227"; GOLD_LITE = "#E4C868"; GOLD_DEEP = "#9C7A16"
CLAY    = "#A05A3C"                      # no-match / muted popup

# Glass: Qt has no backdrop-filter (design §8.1), so the frost is faked with a
# near-opaque cream fill + a gold hairline + an inset top highlight (glyphs.py).
GLASS_RGBA  = (251, 247, 239, 244)
POPUP_RGBA  = (251, 247, 239, 248)
STROKE_RGBA = (201, 162, 39, 140)        # --stroke-gold  rgba(201,162,39,0.55)
STROKE_GOLD = "rgba(201,162,39,0.55)"

# ── fonts ─────────────────────────────────────────────────────────────────────
# The design calls for Cinzel / Cinzel Decorative / Lora. Nothing is downloaded:
# drop those TTFs into ui/fonts/ and they win automatically (load_fonts), else the
# closest vintage serifs that ship with Windows take over.
#   display (logo)  Cinzel Decorative → Palatino Linotype  — humanist Roman capitals
#   title  (labels) Cinzel            → Constantia         — crisp tracked small caps
#   body   (text)   Lora              → Georgia            — Lora's nearest cousin
_CHAINS = {
    "display": ("Cinzel Decorative", "Cinzel", "Palatino Linotype", "Book Antiqua",
                "Constantia", "Georgia", "Times New Roman"),
    "title":   ("Cinzel", "Constantia", "Palatino Linotype", "Georgia", "Times New Roman"),
    "body":    ("Lora", "Georgia", "Constantia", "Palatino Linotype", "Times New Roman"),
}


def load_fonts() -> None:
    """Register bundled TTF/OTFs if ui/fonts/ exists. No network, ever (design §7)."""
    d = Path(__file__).resolve().parent / "fonts"
    if not d.is_dir():
        return
    for f in (*d.glob("*.ttf"), *d.glob("*.otf")):
        QFontDatabase.addApplicationFont(str(f))
    family.cache_clear()


@lru_cache(maxsize=None)
def family(role: str) -> str:
    have = set(QFontDatabase.families())
    for name in _CHAINS[role]:
        if name in have:
            return name
    return "Times New Roman"


def font(role: str = "body", size: float = 13, *, italic: bool = False,
         bold: bool = False, tracking: float = 0.0) -> QFont:
    """A ready-to-use QFont. `size` is CSS px (= Qt logical px), `tracking` is
    absolute px of letter-spacing (CSS em × size)."""
    f = QFont(family(role))
    f.setPixelSize(max(1, round(size)))
    f.setItalic(italic)
    f.setWeight(QFont.Bold if bold else QFont.Normal)
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return f


def qss() -> str:
    """Colour only — fonts are set in code (see module docstring). The pill is
    logo-only now, so this is all the stylesheet the UI still needs: it keeps every
    child widget from painting an opaque system background over the glass."""
    return f"""
    QWidget {{ color: {BROWN}; background: transparent; }}
    """
