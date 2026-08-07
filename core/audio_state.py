"""Shared state between the microphone and anything that plays audio.

Nothing speaks in TONY today — there is no TTS — but both events survive because the
wake listener and the recorder still honour them, and they are the seam a speaking
TONY would need. One shared Event, not a flag per module: the point is that every
microphone callback consults the same object.
"""
import threading

# Set while TONY is playing audio → the wake and recording callbacks drop what the
# microphone hears, so it cannot answer itself.
is_speaking = threading.Event()

# Cut playback early (barge-in).
stop_speaking = threading.Event()
