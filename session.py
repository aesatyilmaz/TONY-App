"""The one voice loop: wake → rolling active window → STT → route → run.

Both entry points drive this — `main.py` (console) and `ui/voice_worker.py` (tray).
They differ ONLY in how they report, so they pass a `report(event, arg)` callback
instead of each keeping their own copy of the loop.

ponytail: this file exists because the loop was duplicated and the copies drifted
(one flashed the UI open on "Tony, stop", the other didn't). One loop, two reporters.

Events passed to `report`: "ready", "window_open", "window_reset", "window_closed",
"heard" (transcript), "executed" (response text), "no_match" (transcript),
"failed" (why the action raised), "shutdown" (the user said to turn TONY off —
`run_session` has already returned; the caller quits).
"""
from __future__ import annotations

import threading
import time

from router import match, is_only_filler, is_exit_phrase, parse_amount

# Longest transcript still plausible as someone TRYING to give a command. Past this
# it's the room talking, and TONY should stay quiet rather than report a miss.
_COMMAND_ATTEMPT_WORDS = 6


def run_session(cfg: dict, commands: list, report, should_stop=None,
                ears=None, whisper=None, hotkey_evt: threading.Event | None = None,
                register_hotkey: bool = True, recorder=None) -> None:
    """Listen and execute until `should_stop()` is true (console mode: forever).

    Everything after `should_stop` is an injection seam so the loop is testable with
    fakes; left at its default, each one resolves to the real microphone path.
    """
    import atexit

    if ears is None or whisper is None:
        from core import wake, stt as _stt
        ears = ears or wake.WakeListener(cfg)
        whisper = whisper or _stt.WhisperSTT(cfg["stt_model"], cfg["stt_language"])
    if recorder is None:
        from core import stt as recorder            # provides record_utterance()

    if hotkey_evt is None:
        hotkey_evt = threading.Event()
    if register_hotkey:
        from triggers_hotkey import start_hotkey
        start_hotkey(cfg["activate_hotkey"], hotkey_evt)

    if register_hotkey:                             # real run — clean up child processes
        from actions import screen_record
        import vision
        atexit.register(screen_record.stop_recording)   # finalize an in-progress take
        atexit.register(vision.close_vision)            # don't leave the camera on
    should_stop = should_stop or (lambda: False)
    window = cfg["active_window_seconds"]
    threshold = cfg["fuzzy_threshold"]

    last = [None, ""]        # (command, the words that ran it) — for "again"

    def type_mode() -> None:
        """Stop routing; type what is heard, until told to stop.

        The active window does NOT run out in here. A dictation that timed out
        mid-sentence and started interpreting the rest as commands would be worse
        than one that never started.

        Getting out has to work when the STT does not, so there are three ways and
        only one of them involves being understood:
          * the exit phrases (router.is_exit_phrase),
          * the global hotkey — the same key that wakes TONY, checked between
            utterances; silence ends an utterance in about a second, so the key takes
            effect about that fast,
          * and going quiet. A mode that survives the founder walking away is a mode
            that types the next conversation in the room into whatever has focus.
        """
        from actions import control
        idle_limit = cfg.get("type_mode_idle_seconds", 60.0)
        report("type_mode", True)
        try:
            quiet_since = time.monotonic()
            while not should_stop():
                if hotkey_evt.is_set():
                    hotkey_evt.clear()
                    return
                if time.monotonic() - quiet_since > idle_limit:
                    return
                # give_up: stop holding the microphone once the silence has already
                # outlasted the idle limit, so the check below happens on time rather
                # than after the next full-length recording.
                audio = recorder.record_utterance(cfg["command_max_seconds"],
                                                  cfg["command_silence_seconds"],
                                                  idle_limit)
                text = (whisper.transcribe(audio) if audio.size else "").strip()
                if not text:
                    continue
                if is_exit_phrase(text):
                    return
                control.type_text(text + " ")
                report("typed", text)
                quiet_since = time.monotonic()
        finally:
            report("type_mode", False)

    def execute(cmd, text: str) -> None:
        # "again" is the one command that has no action of its own: it stands in for
        # whatever ran last, TEXT AND ALL, so a spoken amount comes with it —
        # "volume down 40", "again", "again" walks down in forties.
        if cmd.name == "repeat":
            if last[0] is None:
                report("failed", "nothing to repeat yet")
                return
            cmd, text = last
        if cmd.name == "type_mode":
            report("heard", text)
            type_mode()
            return

        report("heard", text)
        # "volume down 40" — a spoken number rides along for the commands that
        # accept one; the rest never look at it.
        amount = parse_amount(text)
        call_cfg = {**cfg, "amount": amount} if amount is not None else cfg
        if cmd.wants_phrase:
            # One more utterance, taken whole: this is an ARGUMENT, not dictation.
            # It is never routed — "research" followed by "close window" looks up
            # the words "close window", which is exactly what was asked for.
            audio = recorder.record_utterance(
                cfg["command_max_seconds"], cfg["command_silence_seconds"],
                cfg.get("type_mode_idle_seconds", 5.0))
            phrase = (whisper.transcribe(audio) if audio.size else "").strip()
            if not phrase:
                report("failed", f"{cmd.name}: heard nothing to work with")
                return
            call_cfg = {**call_cfg, "phrase": phrase}
        try:
            cmd.run(call_cfg)
        except Exception as e:
            # One bad action must not kill an always-on assistant. Unguarded, a
            # missing Pillow / bad claude_path / non-numeric volume_step raised
            # straight out of the worker thread and the tray froze on its last
            # state with nothing shown.
            report("failed", f"{cmd.name}: {e}")
            return
        last[:] = [cmd, text]     # only what actually ran is worth repeating
        report("executed", cmd.response(call_cfg))   # so the popup says the real amount

    report("ready", None)
    while not should_stop():
        hotkey_evt.clear()                                   # drop stale sets
        trailing = ears.wait_for_wake(interrupt=hotkey_evt)
        hotkey_evt.clear()
        if should_stop():
            break

        # One-shot: "Tony, volume up". Route it first so "Tony, stop" stays asleep
        # instead of flashing the window open.
        trailing_cmd = match(trailing, commands, threshold) if trailing.strip() else None
        if trailing_cmd is not None and trailing_cmd.name == "stop_listening":
            continue
        if trailing_cmd is not None and trailing_cmd.name == "turn_off":
            report("executed", trailing_cmd.response(cfg))
            report("shutdown", None)
            return

        report("window_open", None)
        deadline = time.monotonic() + window
        if trailing_cmd is not None:
            execute(trailing_cmd, trailing)
            deadline = time.monotonic() + window

        while time.monotonic() < deadline and not should_stop():
            audio = recorder.record_utterance(cfg["command_max_seconds"],
                                              cfg["command_silence_seconds"])
            text = whisper.transcribe(audio) if audio.size else ""
            if not text or is_only_filler(text):
                # Saying "tony" again out of reflex, or an "okay"/"hmm", must not
                # count as a failed command: that would answer "didn't catch that"
                # and spend the turn the real command was about to use.
                continue
            cmd = match(text, commands, threshold)
            if cmd is None:
                # The mic hears the room, not just the founder — music, a video, someone
                # talking. Those transcribe into long sentences, and answering each one
                # with "didn't catch that" turns an open window into a popup machine.
                # A command attempt is short; anything longer was never meant for TONY.
                if len(text.split()) <= _COMMAND_ATTEMPT_WORDS:
                    report("no_match", text)
                continue
            if cmd.name == "stop_listening":
                report("heard", text)
                report("executed", cmd.response(cfg))
                break
            if cmd.name == "turn_off":
                report("heard", text)
                report("executed", cmd.response(cfg))
                report("shutdown", None)
                return
            execute(cmd, text)
            deadline = time.monotonic() + window            # rolling window
            report("window_reset", None)

        hotkey_evt.clear()          # a hotkey pressed during the window must not re-open it
        report("window_closed", None)
