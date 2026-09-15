"""Tests for reading agent state, context usage and session colour.

Payload shapes are verbatim from the 2026-09-07 hook experiment and from live
iTerm2 user variables.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import parse_context, parse_state


def test_parse_state_reads_a_live_payload():
    """What the hook emits via OSC 1337 SetUserVar.

    The timestamp has to be recent: a working claim now ages out, so the fixed
    one this test originally carried would read as stale forever.
    """
    import time
    raw = json.dumps({"state": "working", "pid": os.getpid(), "ts": time.time()})
    assert parse_state(raw) == "working"


def test_a_dead_writer_reports_unknown_not_its_last_claim():
    """The council's central warning about SetUserVar: it is last-writer-wins
    with no concept of death. A session killed mid-turn leaves "working" in the
    variable forever, which is exactly the plausible-but-false display this
    design forbids.

    PID 0 can never be a real Claude process, so it stands in for a dead one.
    """
    raw = json.dumps({"state": "working", "pid": 0, "ts": 1788774165})
    assert parse_state(raw) == "unknown"


def test_garbage_is_unknown_rather_than_a_guess():
    assert parse_state("not json at all") == "unknown"
    assert parse_state("") is None
    assert parse_state(None) is None


def test_parse_context_reads_the_live_claudestatus_string():
    """Verbatim from iTerm2 user.claudeStatus on 2026-09-07. This session read
    27%, and orchard read 88%.
    """
    assert parse_context("✱ claude-opus-5  ──●───────  270k (27%) 🟢") == 27
    assert parse_context("✱ claude-opus-5  ───────●──  886k (88%) 🔴") == 88


def test_parse_context_of_a_fresh_session():
    """Also live: a session that had not yet used any context."""
    assert parse_context("✱ unknown  ●─────────  0 (0%) 🟢") == 0


def test_parse_context_returns_none_when_it_cannot_tell():
    assert parse_context("") is None
    assert parse_context(None) is None
    assert parse_context("no percentage here") is None


def test_session_colour_reads_the_cs_state_file(tmp_path):
    """cs keeps the colour /color set in .cs/local/state, one `key: value` per
    line; this is the line shape of a real state file.
    """
    from sidebar import session_colour
    state = tmp_path / ".cs" / "local" / "state"
    state.parent.mkdir(parents=True)
    state.write_text("claude_session_id: 1234\nclaude_session_color: orange\n")
    assert session_colour(str(tmp_path)) == "orange"


def test_session_colour_of_a_directory_that_is_not_a_cs_session():
    """/Users/x is deliberately NOT used here: home turns out to be a
    cs session itself (cyan, created 2026-07-06), which an earlier version of
    this test got wrong. /tmp has no .cs directory.
    """
    from sidebar import session_colour
    assert session_colour("/tmp") is None
    assert session_colour(None) is None


def test_home_is_itself_a_cs_session_and_gets_its_colour():
    """Not a special case, just true on this machine. The ~ row in the sidebar
    is genuinely a cs session and should be tinted like one.
    """
    from sidebar import session_colour
    assert session_colour(str(Path.home())) == "cyan"


def test_parse_model_reads_the_live_claudestatus_string():
    """Verbatim from iTerm2 user.claudeStatus on 2026-09-07. The "claude-"
    prefix is on every model and carries no information in a 250px row.
    """
    from sidebar import parse_model
    assert parse_model("✱ claude-opus-5  ──●───────  270k (27%) 🟢") == "opus-5"


def test_parse_model_of_a_session_that_has_not_reported_one():
    """Live: a fresh session reported the literal string "unknown". That is not
    a model name, and printing it would be worse than printing nothing.
    """
    from sidebar import parse_model
    assert parse_model("✱ unknown  ●─────────  0 (0%) 🟢") is None
    assert parse_model("") is None
    assert parse_model(None) is None


def test_parse_agents_reads_the_live_subagent_count():
    """Subagents run inside their parent's process with no terminal of their
    own, so the count only reaches the sidebar because the parent tallies it.
    """
    from sidebar import parse_agents
    raw = json.dumps({"state": "working", "pid": os.getpid(), "agents": 4, "ts": 1})
    assert parse_agents(raw) == 4


def test_parse_agents_when_none_are_running():
    from sidebar import parse_agents
    assert parse_agents(json.dumps({"state": "idle", "pid": os.getpid()})) == 0
    assert parse_agents("garbage") == 0
    assert parse_agents(None) == 0


def test_parse_model_keeps_a_display_name_whole():
    """Live: claude-council reported '✱ Fable 5.1  ...'. Splitting on the first
    space truncated it to 'Fable'. claude-status emits either a model id
    (claude-opus-5) or a display name (Fable 5.1) depending on which branch
    resolved it, and the field is separated by TWO spaces, not one.
    """
    from sidebar import parse_model
    assert parse_model("✱ Fable 5.1  ──●───────  244k (24%) 🟢") == "Fable 5.1"
    assert parse_model("✱ claude-opus-5  ──●───────  270k (27%) 🟢") == "opus-5"


def _checked_out_branch():
    """This repo's branch as git itself reports it -- an answer reached without
    the .git/HEAD parsing under test, and true on whatever branch the tests run."""
    import subprocess
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=Path(__file__).resolve().parent, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_git_branch_reads_this_repo():
    """Read from the real repository rather than a fixture, so the format
    cannot drift out from under the test.
    """
    from sidebar import git_branch
    here = Path(__file__).resolve().parent.parent
    assert git_branch(str(here)) == _checked_out_branch()


def test_git_branch_from_a_subdirectory():
    """A session that cd's deeper is still on the same branch."""
    from sidebar import git_branch
    assert git_branch(str(Path(__file__).resolve().parent)) == _checked_out_branch()


def test_git_branch_outside_a_repository():
    from sidebar import git_branch
    assert git_branch("/tmp") is None
    assert git_branch(None) is None


def test_a_working_claim_goes_unknown_once_it_stops_being_refreshed():
    """Live: fable-validator's pane claimed working for four minutes after its
    turn ended. The process was alive, so the pid check trusted it.

    Liveness alone is not enough -- it asks whether the writer exists, never
    whether it has said anything lately. Since PostToolUse is subscribed, a
    genuinely working session emits on every tool call, so a long silence
    under a working claim means we no longer know.
    """
    from sidebar import parse_state, WORKING_GOES_STALE_AFTER
    import time
    stale = json.dumps({"state": "working", "pid": os.getpid(),
                        "ts": time.time() - WORKING_GOES_STALE_AFTER - 5})
    assert parse_state(stale) == "unknown"


def test_a_recent_working_claim_is_still_believed():
    from sidebar import parse_state
    import time
    fresh = json.dumps({"state": "working", "pid": os.getpid(), "ts": time.time() - 5})
    assert parse_state(fresh) == "working"


def test_idle_does_not_go_stale():
    """Idle is a resting state -- nothing refreshes it and nothing needs to.
    Ageing it out would replace a true reading with an unknown one.
    """
    from sidebar import parse_state
    old = json.dumps({"state": "idle", "pid": os.getpid(), "ts": 1})
    assert parse_state(old) == "idle"


def test_parse_subagents_reads_type_and_start():
    from sidebar import parse_subagents
    raw = json.dumps({"state": "working", "pid": os.getpid(), "agents": 2,
                      "subagents": [{"type": "Explore", "since": 50},
                                    {"type": None, "since": 90}]})
    assert parse_subagents(raw) == [{"type": "Explore", "since": 50, "ended": None, "name": None, "model": None},
                                    {"type": None, "since": 90, "ended": None, "name": None, "model": None}]


def test_parse_subagents_drops_what_it_cannot_read():
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [{"type": 7, "since": "soon"}, "x",
                                    {"type": "Plan", "since": 10}]})
    assert parse_subagents(raw) == [{"type": None, "since": None, "ended": None, "name": None, "model": None},
                                    {"type": "Plan", "since": 10, "ended": None, "name": None, "model": None}]
    assert parse_subagents(json.dumps({"subagents": "many"})) == []
    assert parse_subagents("garbage") == []
    assert parse_subagents(None) == []


def test_parse_blocked_since():
    from sidebar import parse_blocked_since
    assert parse_blocked_since(json.dumps({"blocked_since": 1789462240})) == 1789462240
    assert parse_blocked_since(json.dumps({"blocked_since": None})) is None
    assert parse_blocked_since(json.dumps({"blocked_since": "yesterday"})) is None
    assert parse_blocked_since("garbage") is None
    assert parse_blocked_since(None) is None


def test_parse_subagents_carries_when_a_finished_one_ended():
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [{"type": "x", "since": 5, "ended": 9},
                                    {"type": "y", "since": 6, "ended": None}]})
    assert [s["ended"] for s in parse_subagents(raw)] == [9, None]


def test_parse_subagents_carries_name_and_a_short_model():
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [{"type": "workflow-subagent", "since": 5,
                                     "name": "read:theirs", "model": "claude-fable-5-1"}]})
    assert parse_subagents(raw) == [{"type": "workflow-subagent", "since": 5, "ended": None,
                                     "name": "read:theirs", "model": "Fable 5.1"}]


def test_model_ids_read_the_way_the_statusline_writes_them():
    from sidebar import short_model
    assert short_model("claude-fable-5-1") == "Fable 5.1"
    assert short_model("claude-opus-5") == "Opus 5"
    assert short_model("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert short_model("claude-sonnet-5[1m]") == "Sonnet 5"
    assert short_model("gpt-6") is None
    assert short_model("") is None
    assert short_model(None) is None


def test_parse_working_since():
    from sidebar import parse_working_since
    assert parse_working_since(json.dumps({"working_since": 1789462240})) == 1789462240
    assert parse_working_since(json.dumps({"working_since": None})) is None
    assert parse_working_since(json.dumps({"state": "idle"})) is None
    assert parse_working_since("garbage") is None
    assert parse_working_since(None) is None
