"""Tests for reading agent state, context usage and session colour.

Payload shapes are verbatim from the 2026-09-07 hook experiment and from live
iTerm2 user variables.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar  # noqa: E402

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


def test_a_pid_no_process_could_hold_is_unknown():
    """A pid too large for the kernel is nobody's, so the claim has no writer."""
    raw = json.dumps({"state": "idle", "pid": 2 ** 31, "ts": 1788774165})
    assert parse_state(raw) == "unknown"
    assert parse_state('{"state": "idle", "pid": Infinity}') == "unknown"


def test_a_subagent_since_that_is_no_moment_is_dropped():
    """json.loads accepts NaN and Infinity, and neither is a time."""
    from sidebar import parse_subagents
    for since in ("NaN", "Infinity"):
        raw = '{"subagents": [{"id": "a", "type": "Explore", "since": %s}]}' % since
        assert parse_subagents(raw)[0]["since"] is None


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
    assert parse_subagents(raw) == [{"type": "Explore", "since": 50, "ended": None, "name": None, "model": None, "depth": 0},
                                    {"type": None, "since": 90, "ended": None, "name": None, "model": None, "depth": 0}]


def test_parse_subagents_drops_what_it_cannot_read():
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [{"type": 7, "since": "soon"}, "x",
                                    {"type": "Plan", "since": 10}]})
    assert parse_subagents(raw) == [{"type": None, "since": None, "ended": None, "name": None, "model": None, "depth": 0},
                                    {"type": "Plan", "since": 10, "ended": None, "name": None, "model": None, "depth": 0}]
    assert parse_subagents(json.dumps({"subagents": "many"})) == []
    assert parse_subagents("garbage") == []
    assert parse_subagents(None) == []


def test_parse_subagents_puts_a_nested_subagent_under_the_one_that_started_it():
    """The hook lists every depth flat and oldest first; a subagent's own
    subagent belongs directly below it, one step further in."""
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [
        {"id": "a1", "type": "general-purpose", "since": 10},
        {"id": "b1", "type": "Explore", "since": 20},
        {"id": "a2", "parent": "a1", "type": "claude-code-guide", "since": 30},
        {"id": "a3", "parent": "a2", "type": "Explore", "since": 40},
        {"id": "a4", "parent": "a1", "type": "Plan", "since": 50}]})
    assert [(s["since"], s["depth"]) for s in parse_subagents(raw)] == [
        (10, 0), (30, 1), (40, 2), (50, 1), (20, 0)]


def test_parse_subagents_does_not_indent_under_a_parent_it_cannot_show():
    """A parent from before the turn, or one the hook never listed, leaves
    its child at the top rather than indented under nothing."""
    from sidebar import parse_subagents
    raw = json.dumps({"subagents": [
        {"id": "a2", "parent": "gone", "type": "Explore", "since": 30},
        {"id": "x", "parent": "y", "since": 40}, {"id": "y", "parent": "x", "since": 50}]})
    assert [(s["since"], s["depth"]) for s in parse_subagents(raw)] == [(30, 0), (40, 0), (50, 0)]


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
                                     "name": "read:theirs", "model": "Fable 5.1", "depth": 0}]


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


from sidebar import agent_variable, parse_codex

CLAUDE_RAW = json.dumps({"state": "idle", "pid": 701, "ts": 1789480000})
CODEX_RAW = json.dumps({"state": "working", "pid": 51201, "ts": 1789480300, "model": "gpt-6-astra",
                        "transcript_path": "/Users/jane/.codex/sessions/2026/09/15/rollout-x.jsonl"})


def test_a_codex_pane_reads_its_codex_variable():
    assert agent_variable(None, CODEX_RAW) == (CODEX_RAW, "openai")


def test_a_claude_pane_reads_its_claude_variable():
    assert agent_variable(CLAUDE_RAW, None) == (CLAUDE_RAW, "claude")
    assert agent_variable(CLAUDE_RAW, "") == (CLAUDE_RAW, "claude")


def test_a_pane_that_reported_nothing_has_no_agent_variable():
    assert agent_variable(None, None) == (None, None)


def test_when_both_are_set_the_newer_report_wins():
    """A Claude killed without SessionEnd leaves its variable behind; Codex
    started later in the same pane reports after it."""
    assert agent_variable(CLAUDE_RAW, CODEX_RAW) == (CODEX_RAW, "openai")
    newer_claude = json.dumps({"state": "working", "pid": 702, "ts": 1789480900})
    assert agent_variable(newer_claude, CODEX_RAW) == (newer_claude, "claude")


def test_a_report_without_a_readable_time_loses_to_one_with():
    assert agent_variable("not json", CODEX_RAW) == (CODEX_RAW, "openai")


def test_codex_variable_names_its_model_and_rollout():
    assert parse_codex(CODEX_RAW) == {
        "model": "gpt-6-astra", "transcript_path": "/Users/jane/.codex/sessions/2026/09/15/rollout-x.jsonl"}


def test_an_unreadable_codex_variable_names_nothing():
    assert parse_codex("{torn") == {"model": None, "transcript_path": None}
    assert parse_codex(None) == {"model": None, "transcript_path": None}


def test_a_codex_variable_naming_something_other_than_text_names_nothing():
    """Any process can write the variable, so a path or model that is not a
    string is not one."""
    raw = json.dumps({"model": ["gpt"], "transcript_path": {"a": 1}})
    assert parse_codex(raw) == {"model": None, "transcript_path": None}


def test_parse_session_reads_the_id_the_hook_published():
    from sidebar import parse_session
    assert parse_session('{"state": "working", "pid": 5, "session": "abc-123"}') == "abc-123"
    assert parse_session('{"state": "working", "pid": 5}') is None
    assert parse_session("not json") is None
    assert parse_session(None) is None


def test_read_task_reports_the_note_with_its_age(tmp_path, monkeypatch):
    """The note is what the session wrote about itself; the daemon adds only
    how old it is, so the page can grey a report nobody refreshed."""
    import json
    from sidebar import read_task
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tmp_path))
    (tmp_path / "abc.json").write_text(json.dumps({
        "task": "t1", "title": "Fix login", "activity": "Reading code",
        "percent": 35, "done": False, "ts": 1789000000}))
    assert read_task("abc") == {
        "title": "Fix login", "activity": "Reading code", "percent": 35, "done": False,
        "reported_at": 1789000000}


def test_read_task_of_a_session_without_a_note_or_with_a_broken_one(tmp_path, monkeypatch):
    from sidebar import read_task
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tmp_path))
    assert read_task("none") is None
    assert read_task(None) is None
    (tmp_path / "bad.json").write_text("{nope")
    assert read_task("bad") is None
    (tmp_path / "half.json").write_text('{"task": "t", "title": "x"}')
    assert read_task("half") == {
        "title": "x", "activity": None, "percent": None, "done": False, "reported_at": None}


def test_read_task_reads_only_notes_inside_the_tasks_directory(tmp_path, monkeypatch):
    """The session id comes from a pane variable any process can write, so an
    id that names a path reads nothing."""
    from sidebar import read_task
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tasks))
    (tmp_path / "outside.json").write_text('{"task": "t", "title": "elsewhere"}')
    assert read_task("../outside") is None
    assert read_task(str(tmp_path / "outside")) is None


def test_parse_question():
    from sidebar import parse_question
    asked = {"header": "Icon", "question": "Which icon?", "options": ["Dots"], "multi": False, "more": 0}
    assert parse_question(json.dumps({"question": asked})) == asked
    assert parse_question(json.dumps({"question": None})) is None
    assert parse_question("not json") is None


def test_git_main_worktree_names_the_repo_a_linked_worktree_belongs_to(tmp_path):
    """A cs feature session runs in `<repo>@worktree`, a linked worktree of
    the session's repo. The panel ties the two cards, so it needs the main
    worktree's path from the linked one, and nothing from the main one."""
    import subprocess
    from sidebar import git_main_worktree
    repo = tmp_path / "atlas"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "--allow-empty", "-m", "x"], cwd=repo, check=True)
    linked = tmp_path / "atlas@worktree"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "cs/worktree", str(linked)],
                   cwd=repo, check=True)
    assert git_main_worktree(str(linked)) == str(repo.resolve())
    assert git_main_worktree(str(linked / "sub")) == str(repo.resolve())
    assert git_main_worktree(str(repo)) is None
    assert git_main_worktree("/tmp") is None
    assert git_main_worktree(None) is None


def test_parse_tasks():
    from sidebar import parse_tasks
    tasks = [{"id": "3", "status": "in_progress", "subject": "Registry flags", "doing": "Building"}]
    assert parse_tasks(json.dumps({"tasks": tasks})) == tasks
    assert parse_tasks(json.dumps({"tasks": "six"})) == []
    assert parse_tasks(json.dumps({})) == []
    assert parse_tasks("not json") == []
