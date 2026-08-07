"""Mikrofon ile TTS arasında paylaşılan durum (echo-cancel el sıkışması).

TONY konuşurken mikrofon kendini duymasın diye tek bir Event paylaşılır.
0-Old'un `is_speaking_flag` desenini modül-global yerine tek yerde toplar.
"""
import threading

# TONY konuşurken set edilir → wake/kayıt callback'leri mikrofonu yok sayar.
is_speaking = threading.Event()

# TTS'i erkenden kesmek için (barge-in).
stop_speaking = threading.Event()
