"""Fuzzy command router — transcript → best Command (or None). No model, deterministic.

rapidfuzz WRatio over every trigger phrase; the closest trigger above the threshold
wins. Fuzzy matching is the safety net that lets a small/base Whisper be enough:
misheard text still snaps to the nearest known command (spec §2 & §3).
"""
from __future__ import annotations
import re
from rapidfuzz import process, fuzz


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", s.lower()).strip()


# Words people say around a command without meaning one. "tony" is here because
# saying the wake word again mid-session is a reflex — and if that reflex is treated
# as a failed command it burns the turn and the real command right after it is missed.
# "right" is NOT in here, and must not be. It is a filler in speech ("right, scroll
# down") but it is also a DIRECTION, and stripping it killed both of snap_right's
# triggers outright — "snap right" reached the matcher as "snap" and matched nothing,
# so that command was dead for as long as it existed. "alright" covers the
# conversational use; a leading "right" costs one extra word, which the length guard
# already tolerates. test_no_trigger_can_be_erased_by_its_own_router pins this.
_FILLERS = {
    "tony", "okay", "ok", "alright", "so", "well", "and", "then",
    "hmm", "hm", "uh", "um", "er", "ah", "oh", "eh", "mhm", "yeah", "yep", "yes",
    "hey", "please", "now", "just", "like", "can", "you",
}


# Spoken numbers. Whisper writes bare numerals as digits ("40") but often spells
# out words inside a phrase ("forty"), so both have to be understood.
_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def parse_amount(text: str) -> int | None:
    """The number in 'volume down 40' / 'louder thirty five', or None.

    Returns a percentage the caller can act on; commands that take no amount
    simply ignore it.
    """
    words = _norm(text).split()
    for i, w in enumerate(words):
        if w.isdigit():
            return int(w)
        if w in _TENS:
            nxt = words[i + 1] if i + 1 < len(words) else ""
            return _TENS[w] + (_UNITS[nxt] if nxt in _UNITS and _UNITS[nxt] < 10 else 0)
        if w in _UNITS:
            return _UNITS[w]
    return None


def _is_number_word(w: str) -> bool:
    return w.isdigit() or w in _TENS or w in _UNITS


def strip_fillers(text: str) -> str:
    """Drop filler words from both ends: 'tony new tab' -> 'new tab'.

    Numbers go too, wherever they are: 'volume down 40' must still match the
    'volume down' trigger — the amount is read separately by parse_amount().
    """
    words = [w for w in _norm(text).split() if not _is_number_word(w)]
    while words and words[0] in _FILLERS:
        words.pop(0)
    while words and words[-1] in _FILLERS:
        words.pop()
    return " ".join(words)


_TYPE_EXITS = ("stop typing", "stop dictation", "exit type mode", "done typing")


def is_exit_phrase(text: str, threshold: float = 88) -> bool:
    """True when an utterance is asking to leave type mode.

    Stricter than command routing, and length-guarded the same way commands are: in
    here every word that is not an exit gets typed, so "...and then we can stop
    typing all of this" is a sentence being dictated, not an instruction. Erring
    toward typing is the recoverable mistake — "clear this" undoes it, while being
    dropped out mid-paragraph costs the paragraph.
    """
    q = strip_fillers(text)
    if not q or len(q.split()) > 4:
        return False
    best = process.extractOne(q, _TYPE_EXITS, scorer=fuzz.WRatio)
    return bool(best and best[1] >= threshold)


def is_only_filler(text: str) -> bool:
    """True when the whole utterance was throat-clearing — ignore it and keep
    listening, rather than answering 'didn't catch that' and eating the turn."""
    words = _norm(text).split()
    return bool(words) and all(w in _FILLERS for w in words)


def match(transcript: str, commands: list, threshold: float, slack: int = 2):
    """Return the best-matching Command, or None if nothing clears `threshold`.

    Two guards, both against WRatio's substring-friendly `partial_ratio`:

    * **too short** — a bare "stop"/"close"/"next" must not win a longer trigger
      ("stop recording"). A single-token query is scored with whole-string
      `ratio` instead, which still forgives single-word STT typos.
    * **too long** — a sentence that merely *contains* a trigger must not fire it.
      The mic is always on during the 20s window, so "can you close this window
      for me later" would otherwise WM_CLOSE the user's unsaved work. A transcript
      may exceed its trigger by `slack` words, no more.
    """
    q = strip_fillers(transcript)      # "tony new tab" / "okay scroll down" -> the command
    if not q:
        return None
    trigger_to_cmd = {t: c for c in commands for t in c.triggers}
    words = len(q.split())
    scorer = fuzz.ratio if words <= 1 else fuzz.WRatio
    best = process.extractOne(q, list(trigger_to_cmd), scorer=scorer)
    if not best or best[1] < threshold:
        return None
    trigger_words = len(best[0].split())
    # Too long: a sentence merely CONTAINING a trigger must not fire it.
    # Too short: a trigger's opening words must not fire it either — "turn off" is
    # the front of "turn off yourself", and that one shuts TONY down. Every command
    # already lists its own short forms as triggers, so nothing legitimate needs the
    # partial. (Single-word queries are scored whole-string, so they're already safe.)
    if trigger_words - 0 > words > 1:
        return None
    if words > trigger_words + slack:
        return None
    return trigger_to_cmd[best[0]]
