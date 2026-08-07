"""Wake word dinleyici — 'Tony'. Sürekli, hafif (Vosk, kurulu).

Neden Vosk: her zaman açık çalışacağı için ultra-hafif olmalı; Vosk zaten kurulu
ve 0-Old'da kanıtlı. Komut STT'si (faster-whisper) ancak uyandıktan sonra çalışır.
ponytail: openWakeWord'e özel 'Tony' modeli gerekirse yükseltme kancası burada.
"""
from __future__ import annotations
import json
import queue

import sounddevice as sd
import vosk

from . import audio_state


def _wake_hit(text: str, wake_word: str) -> tuple[bool, str]:
    """Metinde wake word var mı? Varsa (True, sonrasındaki komut) döner.

    Kelime-sınırı eşleşmesi — 0-Old'un düz substring'inden daha az yanlış tetik.
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
        # path verilmezse dil paketini indirir/yükler (ilk sefer ~40MB, internet).
        self._model = vosk.Model(path) if path else vosk.Model(lang="en-us")
        self._q: queue.Queue[bytes] = queue.Queue()
        print(f"[wake] Ready. Waiting for '{self.wake_word}'.")

    def _callback(self, indata, frames, time_, status):
        if audio_state.is_speaking.is_set():
            return  # TONY konuşuyor → kendini duymasın
        self._q.put(bytes(indata))

    def wait_for_wake(self, interrupt=None) -> str:
        """Wake word duyulana dek bloklar. Aynı cümledeki komutu (varsa) döner.

        `interrupt`: set edilirse (örn. hotkey) bekleme hemen "" döner — mic stream kapanır.
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
    # ponytail self-check: wake eşleşme mantığı (ses donanımı gerektirmez)
    assert _wake_hit("hey tony open chrome", "tony") == (True, "open chrome")
    assert _wake_hit("tony", "tony") == (True, "")
    assert _wake_hit("antony sang", "tony") == (False, "")   # substring değil, kelime
    assert _wake_hit("what is the weather", "tony") == (False, "")
    print("wake logic OK")
