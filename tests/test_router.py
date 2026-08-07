"""Router + registry integrity tests. ponytail: the money path gets the one check."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commands import build_commands, apply_custom_triggers
from router import match
from config import settings

CMDS = build_commands()
THRESH = settings.load()["fuzzy_threshold"]


def _name(transcript):
    c = match(transcript, CMDS, THRESH)
    return c.name if c else None


def test_exact():
    assert _name("scroll down") == "scroll_down"
    assert _name("copy") == "copy"
    assert _name("open youtube") == "open_youtube"


def test_fuzzy_forgives_stt_errors():
    assert _name("scrol down") == "scroll_down"
    assert _name("open you tube") == "open_youtube"
    assert _name("volyum up") == "volume_up"


def test_aliases():
    assert _name("louder") == "volume_up"
    assert _name("reload page") == "refresh"


def test_disambiguation():
    assert _name("next track") == "next_track"
    assert _name("next tab") == "next_tab"
    assert _name("go back") == "nav_back"


def test_below_threshold_returns_none():
    assert _name("what is the weather like today") is None
    assert _name("tell me a joke about cats") is None
    assert _name("") is None


def test_bare_words_dont_greedily_match_longer_triggers():
    # WRatio's partial_ratio would otherwise let a bare word win a multi-word
    # trigger (e.g. "stop" -> "stop recording"). Single-token queries must not
    # silently fire a longer, unrelated (and here privacy-sensitive) command.
    # "back"/"forward" and "stop" are real (exact) triggers now, so those DO match.
    assert _name("stop") == "stop_listening"
    assert _name("close") is None
    assert _name("next") is None
    assert _name("back") == "nav_back"
    assert _name("forward") == "nav_forward"


def test_conversation_does_not_fire_commands():
    """A sentence that merely CONTAINS a trigger must not execute it.

    The mic stays open for 20s after the wake word, so ordinary talk gets
    transcribed. WRatio's partial_ratio scored all of these above the threshold
    before the length guard — the first one WM_CLOSEs whatever the user is in.
    """
    assert _name("can you close this window for me later") is None
    assert _name("i think we should stop recording the meeting now") is None
    assert _name("i will select all of them tomorrow") is None
    assert _name("the next tab over has the spreadsheet") is None
    assert _name("hit enter when you are ready and then we can go") is None


def test_natural_phrasing_still_matches():
    """The guard allows a couple of filler words — don't make it unusable."""
    assert _name("volume up please") == "volume_up"
    assert _name("okay scroll down") == "scroll_down"


def test_stop_listening():
    assert _name("stop listening") == "stop_listening"
    assert _name("stop") == "stop_listening"


def test_capture_and_recording_commands():
    assert _name("screenshot") == "screenshot"
    assert _name("capture window") == "capture_window"
    assert _name("start recording") == "start_recording"
    assert _name("stop recording") == "stop_recording"
    assert _name("stop recording") != "stop_listening"


def test_triggers_are_globally_unique():
    seen = {}
    for c in CMDS:
        for t in c.triggers:
            assert t not in seen, f"duplicate trigger {t!r} in {c.name} and {seen[t]}"
            seen[t] = c.name


def test_custom_triggers_extend_routing_without_breaking_originals():
    cmds = apply_custom_triggers(build_commands(), {"custom_triggers": {"volume_up": ["make it loud"]}})
    assert match("make it loud", cmds, THRESH).name == "volume_up"
    assert match("volume up", cmds, THRESH).name == "volume_up"  # original still works
    assert match("louder", cmds, THRESH).name == "volume_up"


def test_malformed_custom_triggers_are_survivable():
    """settings.json is hand-edited, so wrong types must not crash or poison routing.

    The nasty one: a bare string used to be iterated per CHARACTER, and a 1-letter
    trigger scores 100 against a 1-token transcript — so saying "a" fired a command.
    """
    base = build_commands()
    for bad in ("a string", None, 42, {"volume_up": [None, "", "  "]}):
        out = apply_custom_triggers(base, {"custom_triggers": bad})
        assert all(len(t) > 1 for c in out for t in c.triggers)
    out = apply_custom_triggers(base, {"custom_triggers": {"volume_up": "make it loud"}})
    assert match("make it loud", out, THRESH).name == "volume_up"   # one trigger, not 12


def test_filler_words_around_a_command_do_not_break_it():
    """Saying the wake word again mid-session is a reflex — "tony new tab" must
    still be a new tab, not a miss that costs the founder his turn."""
    assert _name("tony new tab") == "new_tab"
    assert _name("okay scroll down") == "scroll_down"
    assert _name("hmm volume up") == "volume_up"
    assert _name("so open youtube please") == "open_youtube"


def test_a_spoken_amount_is_read_without_breaking_the_match():
    """'volume down 40' must still route to volume_down AND yield 40 — Whisper
    writes bare numerals as digits but spells them out inside a phrase, so both
    forms have to work."""
    from router import parse_amount
    for text, amount in [("volume down 40", 40), ("louder 35", 35),
                         ("turn it down fifty", 50), ("quieter thirty five", 35),
                         ("volume up", None)]:
        assert parse_amount(text) == amount, text
        assert _name(text) in ("volume_up", "volume_down"), text


def test_the_amount_drives_the_volume_step_and_the_response():
    from commands import _volume_percent
    cfg = {"volume_step": 5}
    assert _volume_percent(cfg) == 10                      # configured default
    assert _volume_percent({**cfg, "amount": 40}) == 40    # what was said wins
    assert _volume_percent({**cfg, "amount": 500}) == 100  # clamped to something sane
    assert _volume_percent({**cfg, "amount": 1}) == 2      # never a no-op


def test_volume_asks_for_an_exact_delta_not_a_pile_of_key_presses():
    """'volume down 30' from 50 must land on 20. Counting VK_VOLUME_DOWN presses
    assumed 2% per press, which is driver-dependent — it walked the founder's
    machine to 0. Records the delta asked for; never touches real audio."""
    from actions import volume
    import commands

    asked = []
    real, volume.change = volume.change, lambda pct: asked.append(pct)
    try:
        by_name = {c.name: c for c in commands.build_commands()}
        by_name["volume_down"].run({"volume_step": 5, "amount": 30})
        by_name["volume_up"].run({"volume_step": 5, "amount": 30})
        by_name["volume_up"].run({"volume_step": 5})        # no amount → configured step
    finally:
        volume.change = real
    assert asked == [-30, +30, +10]


def test_a_triggers_opening_words_do_not_fire_it():
    """Mirror of the too-long guard. 'turn off' is the front of 'turn off yourself',
    which SHUTS TONY DOWN — a partial must never be enough. Every command lists its
    own short forms, so nothing legitimate depends on matching a prefix."""
    assert _name("turn off") is None
    assert _name("turn off yourself") == "turn_off"      # the full phrase still works
    assert _name("turn yourself off") == "turn_off"
    # and ordinary talk containing "turn off" was already safe
    for s in ("turn off the lights", "can you turn off the music", "turn it off"):
        assert _name(s) != "turn_off", s


def test_pure_filler_is_ignored_rather_than_failed():
    """These must be ignorable so the loop keeps waiting for the real command."""
    from router import is_only_filler
    for f in ("tony", "okay", "hmm", "uh", "yeah", "tony okay"):
        assert is_only_filler(f), f
        assert _name(f) is None
    # …but an actual sentence is still a genuine miss worth reporting
    assert not is_only_filler("what is the weather like today")


def test_every_command_appears_in_exactly_one_group():
    """The info panel renders GROUPS; a command missing from it is invisible to the
    user, and a stale name in it would crash the panel. Catch both here."""
    from commands import GROUPS
    names = [c.name for c in CMDS]
    listed = [n for _, members in GROUPS for n in members]
    assert sorted(listed) == sorted(names), (
        f"ungrouped: {set(names) - set(listed)} | stale in GROUPS: {set(listed) - set(names)}")
    assert len(listed) == len(set(listed)), "a command is listed in two groups"


def test_custom_trigger_cannot_hijack_a_builtin():
    out = apply_custom_triggers(build_commands(), {"custom_triggers": {"stop_recording": ["stop"]}})
    assert match("stop", out, THRESH).name == "stop_listening"


def test_every_command_has_response_and_run():
    """Empty is allowed, but only where the command's own effect is the feedback —
    opening vision mode grows the pill in front of you, so a popup saying so would be
    narrating what you are already watching. Everything else must say something."""
    cfg = {"volume_step": 5, "scroll_amount": 3}
    silent = {"open_vision", "close_vision"}
    for c in CMDS:
        assert callable(c.run)
        assert isinstance(c.response(cfg), str)
        assert bool(c.response(cfg)) is (c.name not in silent), c.name


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_the_claude_command_targets_the_desktop_app_not_the_cli():
    """"open claude" was launching the Claude Code CLI, which opens a terminal — it
    is on PATH under the same name and is not the app the founder asked for. The
    desktop app ships as an MSIX package, so it is addressed by AppUserModelID."""
    import inspect
    from commands import _open_claude, package_family

    # the docstring says "shutil.which" too — read the body, not the explanation
    body = inspect.getsource(_open_claude).split('"""')[2]
    assert "shutil.which" not in body, "which('claude') finds the CLI, not the app"
    assert "shell:AppsFolder" in body

    # The family name carries a per-machine publisher hash — this is why it is read
    # from the package repository instead of written down.
    assert package_family("Claude_1.24012.9.0_x64__pzs8sxrjxfjjc") == "Claude_pzs8sxrjxfjjc"
    assert package_family("Foo_2.0_arm64__abc123xyz") == "Foo_abc123xyz"


def test_no_trigger_can_be_erased_by_its_own_router():
    """A trigger has to survive the normalisation every transcript goes through.

    strip_fillers() drops number words from anywhere ("volume down 40" must still
    reach the "volume down" trigger) and filler words from both ends. So a trigger
    containing either arrives at the matcher as something shorter than itself and can
    never be said out loud — "one more" turned up as "more" and matched nothing.
    Cheap to check, and the failure is otherwise invisible until the founder tries it.
    """
    from router import strip_fillers
    for c in CMDS:
        for t in c.triggers:
            assert strip_fillers(t) == t, \
                f"{c.name}: {t!r} reaches the matcher as {strip_fillers(t)!r}"


def test_every_trigger_routes_to_its_own_command():
    """Say a trigger exactly and you must get the command that owns it.

    Uniqueness of the strings is not enough — the matcher is fuzzy, so a trigger that
    sits whole inside another one can lose to its neighbour. That is what kept
    "close vision mode" out of close_vision: "vision mode" is open_vision's trigger,
    and asking to close vision mode would have opened it. This catches that class of
    collision the moment a trigger is added or reworded.
    """
    for c in CMDS:
        for t in c.triggers:
            got = match(t, CMDS, THRESH)
            assert got is not None and got.name == c.name, \
                f"{t!r} belongs to {c.name} but routed to {got and got.name}"


def test_the_new_commands_route():
    assert _name("again") == "repeat"
    assert _name("do that again") == "repeat"
    assert _name("save") == "save"
    assert _name("save this") == "save"
    assert _name("clear this") == "clear_field"
    assert _name("search this") == "search_this"
    assert _name("google this") == "search_this"
    assert _name("translate this") == "translate_this"
    assert _name("open gallery") == "open_gallery"
    # the near neighbours they could have swallowed
    assert _name("select all") == "select_all"
    assert _name("space") == "space"
    assert _name("close tab") == "close_tab"
