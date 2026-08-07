"""Master volume, set exactly — not by counting key presses.

Pressing VK_VOLUME_DOWN n times assumes every press moves the volume by a fixed
amount (2% is the usual claim). It doesn't hold: the step depends on the audio
driver, so "volume down 30" walked the founder's machine from 50% to 0. Reading
and writing the endpoint volume through Core Audio removes the guess — 30 means 30.

Falls back to the media keys if the audio API is unavailable (no device, COM
refused), so a machine without a usable endpoint still gets approximate control.
"""
from __future__ import annotations


import threading

# Per-thread, never shared. A COM proxy belongs to the apartment that created it;
# handing one to another thread means cross-apartment marshalling, which is the
# thing we must never do here (see the apartment note below).
_tls = threading.local()

_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = -2147417850     # 0x80010106: this thread is already STA


def _endpoint():
    """The default playback device's volume interface, for THIS thread.

    ## Why the apartment matters (this froze the app)

    `CoInitialize()` joins a **single-threaded apartment**, whose contract is that
    the thread continuously pumps Windows messages. TONY's worker thread never
    does — it blocks in the microphone read and in Whisper. So once a COM proxy
    lived in that apartment, any cross-apartment call into it waited forever, and
    the GUI thread hung the moment it touched COM (opening a window is enough).
    The founder saw the pill stop responding and its window go black — a frozen
    surface, not a painting bug. Caching the proxy at module level made it worse
    by keeping the bad-apartment object alive.

    So: join a **multi-threaded apartment** (no pump required) and keep the proxy
    in thread-local storage so it is never used from another thread.
    """
    ep = getattr(_tls, "endpoint", None)
    if ep is not None:
        return ep

    from ctypes import cast, POINTER
    import comtypes
    from comtypes import CLSCTX_ALL, CoCreateInstance
    from pycaw.pycaw import IAudioEndpointVolume
    from pycaw.constants import CLSID_MMDeviceEnumerator
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator

    try:
        comtypes.CoInitializeEx(_COINIT_MULTITHREADED)
    except OSError as e:
        # Already an STA (Qt does this to the GUI thread). Don't fight it — but
        # don't cache either: an STA proxy must not outlive the call.
        if getattr(e, "winerror", None) != _RPC_E_CHANGED_MODE:
            raise
        enum = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
        dev = enum.GetDefaultAudioEndpoint(0, 1)
        return cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                    POINTER(IAudioEndpointVolume))

    enum = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
    dev = enum.GetDefaultAudioEndpoint(0, 1)          # eRender, eMultimedia
    _tls.endpoint = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                         POINTER(IAudioEndpointVolume))
    return _tls.endpoint


def current() -> int | None:
    """Master volume as 0-100, or None if it can't be read."""
    try:
        return round(_endpoint().GetMasterVolumeLevelScalar() * 100)
    except Exception:
        return None


def change(percent: int) -> int | None:
    """Move the master volume by `percent` (negative to lower). Returns the new
    level, or None if it fell back to key presses."""
    try:
        vol = _endpoint()
        now = vol.GetMasterVolumeLevelScalar() * 100
        target = max(0.0, min(100.0, now + percent))
        vol.SetMasterVolumeLevelScalar(target / 100.0, None)
        return round(target)
    except Exception:
        # No endpoint — approximate with the media keys. ponytail: this path is the
        # OLD behaviour and inherits its flaw (it assumes ~2% per press, which the
        # audio driver actually decides), so it stays a fallback, never the default.
        from . import control
        key = "volumeup" if percent > 0 else "volumedown"
        for _ in range(max(1, round(abs(percent) / 2))):
            control.media_control(key)
        return None


if __name__ == "__main__":
    # ponytail self-check: read-only, never moves the founder's volume.
    lvl = current()
    assert lvl is None or 0 <= lvl <= 100, lvl
    print(f"volume readable: {lvl}%" if lvl is not None else "no endpoint (key fallback)")
