"""The picture, handed from the vision mode process to TONY's UI.

Vision mode keeps its own process — the camera and MediaPipe must never share a thread
with the voice loop — but its picture belongs inside TONY's window, not in a second
window of its own. So the child renders exactly as before and drops the finished
frame here; the panel picks it up.

Shared memory rather than a pipe: 640x480x3 at 30fps is ~26MB/s, and a pipe would
copy every byte of it twice. This hands over the same bytes.

Two slots, one counter. The writer fills the slot the reader is not looking at and
only then publishes the new sequence number, so a frame is never half-written when
it is read — the reader's slot stays untouched for another two frames, which at
30fps is 66ms of headroom it will never need.
"""
from __future__ import annotations

from multiprocessing import shared_memory

import numpy as np

NAME = "TONY_vision_frame"
W, H = 640, 480

_SLOTS = 2
_HEADER = 8                        # one int64 sequence number
_SLOT_BYTES = W * H * 3
_SIZE = _HEADER + _SLOTS * _SLOT_BYTES


def _views(buf):
    seq = np.ndarray((1,), np.int64, buffer=buf)
    slots = [np.ndarray((H, W, 3), np.uint8, buffer=buf,
                        offset=_HEADER + i * _SLOT_BYTES) for i in range(_SLOTS)]
    return seq, slots


class Writer:
    """The vision mode process's end. One per process; closing it releases the block."""

    def __init__(self):
        try:
            self._shm = shared_memory.SharedMemory(name=NAME, create=True, size=_SIZE)
        except FileExistsError:
            # A reader is still holding the block open from a previous vision mode run.
            # Windows frees it with the last handle, so reusing it is correct — and
            # refusing to start over a leftover buffer would be absurd.
            self._shm = shared_memory.SharedMemory(name=NAME)
        self._seq, self._slots = _views(self._shm.buf)
        self._seq[0] = 0

    def put(self, frame) -> None:
        n = int(self._seq[0]) + 1
        self._slots[n % _SLOTS][:] = frame
        self._seq[0] = n           # published only once every pixel is in place

    def close(self) -> None:
        try:
            self._seq[0] = -1      # tell the panel this was a clean exit, not a hang
            del self._seq, self._slots
            self._shm.close()
            self._shm.unlink()
        except Exception:
            pass


class Reader:
    """TONY's end. Raises FileNotFoundError when vision mode is not running — that is the
    normal case, and it is how the panel knows to stay hidden."""

    def __init__(self):
        self._shm = shared_memory.SharedMemory(name=NAME)
        self._seq, self._slots = _views(self._shm.buf)
        self._last = 0        # 0 means "nothing published yet", not "frame zero"

    def get(self):
        """The newest frame if there is one, None if nothing changed, and False once
        vision mode has shut down."""
        n = int(self._seq[0])
        if n < 0:
            return False
        if n == self._last:
            return None
        self._last = n
        return self._slots[n % _SLOTS]

    def close(self) -> None:
        try:
            del self._seq, self._slots
            self._shm.close()
        except Exception:
            pass
