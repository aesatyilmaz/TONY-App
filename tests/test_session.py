"""Voice-loop tests with fake ears/STT — no microphone, no real commands executed.

This is the loop `main.py` and the tray UI both run. It used to be duplicated in both
and the copies drifted, so it gets a real test: wake handling, the one-shot
"Tony, <command>" path, the rolling window, and stop-listening.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from commands import Command  # noqa: E402
from session import run_session  # noqa: E402

CFG = {
    "active_window_seconds": 0.3,      # keep tests fast; the real default is 20s
    "fuzzy_threshold": 86,
    "command_max_seconds": 8.0,
    "command_silence_seconds": 1.0,
    "activate_hotkey": "ctrl+alt+t",
    "type_mode_idle_seconds": 0.3,     # the real default is 60s
}

# Two fake commands: one that records that it ran, and the real stop_listening shape.
_ran: list[str] = []
COMMANDS = [
    Command("volume_up", ("volume up",), lambda cfg: "louder", lambda cfg: _ran.append("volume_up")),
    Command("stop_listening", ("stop listening", "stop"), lambda cfg: "stopped", lambda cfg: None),
    # "again" carries no action of its own — the loop swaps the last command in.
    Command("repeat", ("again",), lambda cfg: "again", lambda cfg: _ran.append("repeat")),
]


class FakeEars:
    """Yields a scripted trailing-text per wake, then stops the session."""

    def __init__(self, trailings):
        self._trailings = list(trailings)
        self.waits = 0

    def wait_for_wake(self, interrupt=None):
        self.waits += 1
        return self._trailings.pop(0) if self._trailings else ""


class FakeRecorder:
    """Feeds scripted utterances; empty audio once the script runs out."""

    def __init__(self, n_utterances):
        self.remaining = n_utterances

    def record_utterance(self, *_a):
        if self.remaining <= 0:
            return np.zeros(0, dtype=np.float32)
        self.remaining -= 1
        return np.ones(4, dtype=np.float32)


class FakeWhisper:
    def __init__(self, texts):
        self._texts = list(texts)

    def transcribe(self, _audio):
        return self._texts.pop(0) if self._texts else ""


def _run(trailings, spoken, max_wakes=1):
    """Run the session for `max_wakes` wake cycles, collecting reported events."""
    _ran.clear()
    events = []
    ears = FakeEars(trailings)
    run_session(
        CFG, COMMANDS,
        report=lambda e, a=None: events.append((e, a)),
        should_stop=lambda: ears.waits > max_wakes,   # one full cycle, then unwind
        ears=ears,
        whisper=FakeWhisper(spoken),
        recorder=FakeRecorder(len(spoken)),
        register_hotkey=False,          # no global keyboard hook in tests
    )
    return events


def _names(events):
    return [e for e, _ in events]


def test_one_shot_command_runs_and_opens_the_window():
    events = _run(trailings=["volume up"], spoken=[])
    assert "volume_up" in _ran
    assert "window_open" in _names(events)
    assert ("executed", "louder") in events


def test_stop_in_the_wake_phrase_never_opens_the_window():
    """'Tony, stop' must stay asleep — no window flash (this drifted between copies)."""
    events = _run(trailings=["stop"], spoken=[])
    assert "window_open" not in _names(events)
    assert _ran == []


def test_spoken_command_executes_and_rolls_the_window():
    events = _run(trailings=[""], spoken=["volume up"])
    assert _ran == ["volume_up"]
    assert "window_reset" in _names(events)      # rolling: window extended
    assert "window_closed" in _names(events)


def test_unmatched_speech_reports_no_match_and_runs_nothing():
    events = _run(trailings=[""], spoken=["what is the weather like today"])
    assert _ran == []
    assert ("no_match", "what is the weather like today") in events


def test_the_room_talking_does_not_produce_a_popup():
    """The mic hears music and TV, not just the founder. Those transcribe into long
    sentences; answering each with 'didn't catch that' turned an open window into a
    popup machine. Short misses still report — those are real attempts."""
    events = _run(trailings=[""], spoken=["and then she said we should go there tomorrow"])
    assert "no_match" not in _names(events)
    events = _run(trailings=[""], spoken=["volume oop"])
    assert "no_match" in _names(events)


def test_filler_does_not_consume_the_turn():
    """An involuntary "tony" mid-window must not report a failure and must leave
    the window open for the command that follows it."""
    events = _run(trailings=[""], spoken=["tony", "volume up"])
    assert _ran == ["volume_up"]                       # the real command still ran
    assert "no_match" not in _names(events)            # and no "didn't catch that"


def test_stop_listening_closes_the_window_without_running_more():
    events = _run(trailings=[""], spoken=["stop listening", "volume up"])
    assert _ran == []                            # loop broke before the 2nd utterance
    assert "window_closed" in _names(events)


def test_again_reruns_the_last_command():
    """It stands in for what ran last, and its own run() must never fire."""
    _run(trailings=[""], spoken=["volume up", "again"])
    assert _ran == ["volume_up", "volume_up"], _ran


def test_again_with_nothing_behind_it_says_so_instead_of_guessing():
    events = _run(trailings=[""], spoken=["again"])
    assert _ran == []
    assert "failed" in [e for e, _ in events]


def test_a_command_that_failed_is_not_worth_repeating():
    """Only what actually ran is remembered, or "again" re-runs a mistake."""
    boom = Command("boom", ("boom",), lambda cfg: "boom",
                   lambda cfg: (_ for _ in ()).throw(RuntimeError("nope")))
    _ran.clear()
    events = []
    ears = FakeEars([""])
    run_session(
        CFG, [*COMMANDS, boom],
        report=lambda e, a=None: events.append((e, a)),
        should_stop=lambda: ears.waits > 1,
        ears=ears, whisper=FakeWhisper(["volume up", "boom", "again"]),
        recorder=FakeRecorder(3), register_hotkey=False,
    )
    assert _ran == ["volume_up", "volume_up"], _ran   # "again" repeated the good one


class TypeSpy:
    """Stands in for actions.control — records what would have been typed."""

    def __init__(self):
        self.typed = []

    def type_text(self, text):
        self.typed.append(text)


def _type_run(spoken, spy, hotkey=None, max_wakes=1):
    import actions.control
    _ran.clear()
    events = []
    ears = FakeEars([""])
    real_type = actions.control.type_text
    actions.control.type_text = spy.type_text
    try:
        run_session(
            CFG, [*COMMANDS, Command("type_mode", ("type mode",),
                                     lambda cfg: "type mode", lambda cfg: None)],
            report=lambda e, a=None: events.append((e, a)),
            should_stop=lambda: ears.waits > max_wakes,
            ears=ears, whisper=FakeWhisper(spoken),
            recorder=FakeRecorder(len(spoken)), register_hotkey=False,
            hotkey_evt=hotkey,
        )
    finally:
        actions.control.type_text = real_type
    return events


def test_type_mode_types_instead_of_routing():
    """In here "volume up" is words, not a command — that is the whole point."""
    spy = TypeSpy()
    events = _type_run(["type mode", "hello there", "volume up", "stop typing"], spy)
    assert spy.typed == ["hello there ", "volume up "]
    assert _ran == [], "nothing may execute while dictating"
    assert ("type_mode", True) in events and ("type_mode", False) in events


def test_a_sentence_containing_the_exit_phrase_is_still_dictation():
    """Every word in here gets typed, so "we can stop typing all of this later" is
    something being said, not an instruction."""
    spy = TypeSpy()
    _type_run(["type mode", "and then we can stop typing all of this later",
               "stop typing"], spy)
    assert spy.typed == ["and then we can stop typing all of this later "]


class PressesHotkey(FakeRecorder):
    """Presses the global hotkey partway through, the way the founder would — while
    already in type mode, not before."""

    def __init__(self, n, evt, press_on):
        super().__init__(n)
        self._evt, self._press_on, self._calls = evt, press_on, 0

    def record_utterance(self, *a):
        self._calls += 1
        if self._calls == self._press_on:
            self._evt.set()
        return super().record_utterance(*a)


def test_the_hotkey_leaves_type_mode_without_being_understood():
    """The exit that does not depend on the STT working at all. Without it, one
    mishearing locks the founder in a mode that types into whatever has focus."""
    import threading, actions.control
    spy, evt, events = TypeSpy(), threading.Event(), []
    ears = FakeEars([""])
    spoken = ["type mode", "keep this", "THIS MUST NOT BE TYPED"]
    real = actions.control.type_text
    actions.control.type_text = spy.type_text
    try:
        run_session(
            CFG, [*COMMANDS, Command("type_mode", ("type mode",),
                                     lambda cfg: "type mode", lambda cfg: None)],
            report=lambda e, a=None: events.append((e, a)),
            should_stop=lambda: ears.waits > 1,
            ears=ears, whisper=FakeWhisper(spoken),
            recorder=PressesHotkey(len(spoken), evt, press_on=2),
            register_hotkey=False, hotkey_evt=evt,
        )
    finally:
        actions.control.type_text = real
    assert spy.typed == ["keep this "], spy.typed
    assert ("type_mode", False) in events


def test_type_mode_ends_itself_when_the_room_goes_quiet():
    """A mode that outlives the founder walking away types the next conversation in
    the room into whatever has focus. CFG sets the limit to 0.3s here; it is 60s live."""
    spy = TypeSpy()
    events = _type_run(["type mode"], spy)      # nothing said after entering
    assert spy.typed == []
    assert ("type_mode", False) in events


def test_type_mode_stops_holding_the_microphone_past_the_idle_limit():
    """The idle clock can only tick between recordings. Without telling the recorder
    to give up, a five-second silence rule waits out an eight-second recording first
    and is really an eight-second rule."""
    import actions.control

    seen = []

    class Watched(FakeRecorder):
        def record_utterance(self, *a):
            seen.append(a)
            return super().record_utterance(*a)

    spy, events = TypeSpy(), []
    ears = FakeEars([""])
    real = actions.control.type_text
    actions.control.type_text = spy.type_text
    try:
        run_session(
            CFG, [*COMMANDS, Command("type_mode", ("type mode",),
                                     lambda cfg: "type mode", lambda cfg: None)],
            report=lambda e, a=None: events.append((e, a)),
            should_stop=lambda: ears.waits > 1,
            ears=ears, whisper=FakeWhisper(["type mode", "hello"]),
            recorder=Watched(2), register_hotkey=False,
        )
    finally:
        actions.control.type_text = real

    # The loop records again after type mode returns, so filter rather than slice.
    assert len(seen[0]) == 2, "the command loop asks for a plain recording"
    give_ups = [a for a in seen if len(a) == 3]
    assert give_ups, "type mode never told the recorder when to give up"
    assert all(a[2] == CFG["type_mode_idle_seconds"] for a in give_ups), give_ups


def test_research_takes_the_next_utterance_whole_and_never_routes_it():
    """A spoken ARGUMENT, not dictation and not a mode. "research" then "close
    window" looks up the words "close window" — which is what was asked for, and
    would be a disaster if the second utterance went through the router."""
    got = {}
    research = Command("research", ("research",),
                       lambda cfg: f"searching {cfg.get('phrase')}",
                       lambda cfg: got.update(phrase=cfg.get("phrase")),
                       wants_phrase=True)
    _ran.clear()
    events, ears = [], FakeEars([""])
    run_session(
        CFG, [*COMMANDS, research],
        report=lambda e, a=None: events.append((e, a)),
        should_stop=lambda: ears.waits > 1,
        ears=ears, whisper=FakeWhisper(["research", "close window"]),
        recorder=FakeRecorder(2), register_hotkey=False,
    )
    assert got == {"phrase": "close window"}
    assert _ran == [], "the argument must not be executed as a command"
    assert ("executed", "searching close window") in events


def test_research_that_hears_nothing_says_so():
    research = Command("research", ("research",), lambda cfg: "searching",
                       lambda cfg: None, wants_phrase=True)
    events, ears = [], FakeEars([""])
    run_session(
        CFG, [*COMMANDS, research],
        report=lambda e, a=None: events.append((e, a)),
        should_stop=lambda: ears.waits > 1,
        ears=ears, whisper=FakeWhisper(["research"]),
        recorder=FakeRecorder(1), register_hotkey=False,
    )
    assert "failed" in [e for e, _ in events]
