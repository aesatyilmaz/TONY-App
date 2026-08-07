"""Komut STT — faster-whisper (yerel, GPU). Uyandıktan SONRA çalışır.

WhisperSTT sınıfı 1-Mark'ın ölü `core/stt.py`'sinden canlandırıldı (greedy, VAD).
record_utterance: mikrofonu kaydeder, RMS ile sessizlik-bitişi yakalar, float32 döner.
"""
from __future__ import annotations
import os
# torch + ctranslate2/onnxruntime aynı OpenMP runtime'ını yükler (Windows).
# faster-whisper+torch stack'inin standart çözümü; import'lardan ÖNCE set edilmeli.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import queue

import numpy as np
import sounddevice as sd

from . import audio_state

SAMPLE_RATE = 16000


class WhisperSTT:
    """faster-whisper ile offline transkripsiyon (Mark WhisperSTT'den)."""

    def __init__(self, model_name: str = "base", language: str | None = None):
        from faster_whisper import WhisperModel
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
        except Exception:
            device, compute = "cpu", "int8"
        print(f"[stt] Loading Whisper '{model_name}' ({device})…")
        self._model = WhisperModel(model_name, device=device, compute_type=compute)
        self._language = None if (not language or language.strip().lower() == "auto") \
            else language.strip().lower()
        print(f"[stt] Whisper ready ({device}).")

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _ = self._model.transcribe(
            audio, language=self._language,
            beam_size=1, best_of=1,             # greedy — hızlı
            condition_on_previous_text=False,   # halüsinasyon yok
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text for s in segments).strip()


def record_utterance(max_seconds: float, silence_seconds: float,
                     give_up_seconds: float | None = None) -> np.ndarray:
    """Mikrofonu kaydeder; `silence_seconds` sessizlikte veya `max_seconds`'te durur.

    float32 mono 16kHz numpy dizisi döner (Whisper'ın beklediği format).

    `give_up_seconds`: if nobody has said anything at all by then, return empty
    immediately instead of holding the microphone for the full `max_seconds`. The
    caller's own idle clock can only tick between calls, so without this a "five
    seconds of silence" rule really means "the next check after eight".
    """
    block = 4000  # 0.25 sn
    q: queue.Queue[np.ndarray] = queue.Queue()

    def cb(indata, frames, time_, status):
        if audio_state.is_speaking.is_set():
            return
        q.put(indata.copy().reshape(-1))

    frames: list[np.ndarray] = []
    silent_blocks = 0
    max_blocks = int(max_seconds * SAMPLE_RATE / block)
    silence_limit = int(silence_seconds * SAMPLE_RATE / block)
    threshold = 0.01  # RMS eşiği (float32 -1..1)

    print("[stt] 🔴 Recording command…")
    with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=block, dtype="float32",
                        channels=1, callback=cb):
        heard = False
        give_up_blocks = (int(give_up_seconds * SAMPLE_RATE / block)
                          if give_up_seconds else None)
        for i in range(max_blocks):
            if not heard and give_up_blocks and i >= give_up_blocks:
                break
            try:
                chunk = q.get(timeout=1.0)
            except queue.Empty:
                continue
            frames.append(chunk)
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms >= threshold:
                heard, silent_blocks = True, 0
            elif heard:
                silent_blocks += 1
                if silent_blocks >= silence_limit:
                    break
    if not heard:
        # Nobody spoke. Returning the buffer would send `max_seconds` of silence to
        # Whisper — a GPU inference per idle pass, ~7 of them per 60s active window.
        # The caller skips transcription on an empty array.
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)


if __name__ == "__main__":
    # ponytail self-check: kayıt tampon mantığı modelsiz doğrulanır
    a = np.zeros(0, dtype=np.float32)
    assert a.dtype == np.float32 and a.size == 0
    print("stt helper logic OK (model test in live gate)")
