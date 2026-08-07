"""StatsStrip — what the machine is doing, along the bottom of the reference card.

CPU and memory come from psutil, which costs microseconds. The GPU does not: reading
it means running nvidia-smi, and launching a process on the GUI thread once a second
would show up as a stutter. So it goes through QProcess — Qt starts it, waits on it,
and delivers the output back here ON THE GUI THREAD when it is done. No worker
thread, and therefore none of the cross-thread hazards that come with one.

The strip only ticks while the card is on screen. Polling hardware for a panel
nobody is looking at is work for nothing, and on a laptop it is work for nothing
that costs battery.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy

from ui import tokens

REFRESH_MS = 1000
_MUTED = "#6F5A44"
_SMI = ["--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits"]


def format_stats(cpu: float, ram: float, gpu: tuple[int, int, int] | None) -> str:
    """One line. The GPU part is dropped entirely when there is nothing to say —
    an empty "GPU —" tells the founder less than the space it takes."""
    line = f"CPU {cpu:.0f}%     RAM {ram:.0f}%"
    if gpu:
        util, used, total = gpu
        line += f"     GPU {util:.0f}%     VRAM {used / 1024:.1f} / {total / 1024:.1f} GB"
    return line


def parse_smi(text: str) -> tuple[int, int, int] | None:
    """`9, 843, 8188` → (util %, used MiB, total MiB). None if nvidia-smi said
    anything else, which includes not being installed."""
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return tuple(int(p) for p in parts)     # type: ignore[return-value]
    return None


class StatsStrip(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(tokens.font("title", 10, tracking=1.4))
        self.setStyleSheet(f"color: {_MUTED};")
        # The text is right-aligned INSIDE a label that fills its row, rather than a
        # label sized to the text. The numbers change every second in a proportional
        # serif, so a label that sized itself to the current reading would slide left
        # and right the whole time the card was open — and a label pinned to its
        # widest possible reading would push the panel wider than the panel is.
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._gpu: tuple[int, int, int] | None = None

        self._proc = QProcess(self)
        self._proc.finished.connect(self._gpu_ready)
        self._proc.errorOccurred.connect(self._gpu_gone)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._tick()
        self._timer.start(REFRESH_MS)

    def stop(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------------------
    def _tick(self) -> None:
        if self._proc.state() == QProcess.NotRunning:
            self._proc.start("nvidia-smi", _SMI)     # answer arrives at _gpu_ready
        self._render()

    def _gpu_ready(self, *_):
        text = bytes(self._proc.readAllStandardOutput()).decode(errors="ignore")
        self._gpu = parse_smi(text)
        self._render()

    def _gpu_gone(self, *_):
        self._gpu = None                             # no NVIDIA GPU, or no driver

    def _render(self) -> None:
        import psutil
        # interval=None means "since the last call", so it returns immediately
        # instead of blocking the GUI thread for a sampling window.
        self.setText(format_stats(psutil.cpu_percent(interval=None),
                                  psutil.virtual_memory().percent, self._gpu))
