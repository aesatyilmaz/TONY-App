"""Wake-word listener — "Tony". Always on, and therefore has to be cheap.

Why Vosk and not Whisper: this one runs every second the machine is awake, so it must
stay tiny and CPU-only. Whisper is the opposite trade — accurate and expensive — so it
is loaded only once the wake word has already been heard.

ponytail: if "Tony" ever needs a purpose-trained detector, openWakeWord drops in here.
"""
from __future__ import annotations
import json
import queue

import sounddevice as sd
import vosk

from . import audio_state


def _wake_hit(text: str, wake_word: str) -> tuple[bool, str]:
    """Is the wake word in this text? If so, (True, whatever came after it).

    Matched on a word boundary, not as a substring: "antony" is not "tony", and a
    plain substring test fires on every one of them.
    """
    words = text.lower().split()
    for i, w in enumerate(words):
        if w == wake_word:
            return True, " ".join(words[i + 1:]).strip()
    return False, ""


class WakeListener:
    def __init__(self, cfg: dict):
        self.wake_word = cfg["wake_word"].lower()
        path = cfg.get("vosk_model_path")
        print("[wake] Loading Vosk model…")
        # Without a path, Vosk downloads its language pack on first use (~40MB).
        self._model = vosk.Model(path) if path else vosk.Model(lang="en-us")
        self._q: queue.Queue[bytes] = queue.Queue()
        print(f"[wake] Ready. Waiting for '{self.wake_word}'.")

    def _callback(self, indata, frames, time_, status):
        if audio_state.is_speaking.is_set():
            return  # TONY is playing audio — do not let it hear itself
        self._q.put(bytes(indata))

    def wait_for_wake(self, interrupt=None) -> str:
        """Block until the wake word is heard. Returns the rest of that sentence.

        The trailing text is what makes "Tony, volume up" work in one breath.

        `interrupt`: when set (the hotkey does this) the wait returns "" at once and
        the microphone stream closes.
        """
        rec = vosk.KaldiRecognizer(self._model, 16000)
        while not self._q.empty():
            self._q.get()
        with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                               channels=1, callback=self._callback):
            while True:
                if interrupt is not None and interrupt.is_set():
                    return ""
                try:
                    data = self._q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if interrupt is not None and interrupt.is_set():
                    return ""
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                    hit, trailing = _wake_hit(text, self.wake_word)
                    if hit:
                        print("[wake] 🔵 Awake.")
                        return trailing


if __name__ == "__main__":
    # ponytail self-check: the matching logic, no audio hardware needed
    assert _wake_hit("hey tony open chrome", "tony") == (True, "open chrome")
    assert _wake_hit("tony", "tony") == (True, "")
    assert _wake_hit("antony sang", "tony") == (False, "")   # a word, not a substring
    assert _wake_hit("what is the weather", "tony") == (False, "")
    print("wake logic OK")
