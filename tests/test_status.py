"""Tests for reading Claude Code's statusline payload.

Field paths are taken from cs-statusline:318-334, which parses the real
payload, rather than from a shape I imagined.
"""
import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)


def test_the_payload_carries_the_only_true_context_figure():
    """Claude Code publishes the context-window size nowhere else. The [1m]
    suffix is stripped from the model id before the request goes out, so a
    percentage cannot be derived from the transcript at all.
    """
    payload = json.dumps({
        "context_window": {"used_percentage": 26},
        "model": {"display_name": "Opus 5 (1M context)", "id": "claude-opus-5[1m]"},
        "effort": {"level": "high"},
    })
    got = sidebar.parse_status(payload)
    assert (got["context"], got["model"], got["effort"]) == (26, "Opus 5", "high")


def test_a_payload_missing_the_fields_reports_nothing():
    """Rendering nothing is the contract. A row shows no percentage rather
    than a stale or invented one.
    """
    assert sidebar.parse_status(json.dumps({"session_id": "x"})) == {
        "context": None, "model": None, "effort": None, "details": {},
        "transcript": None}


def test_unreadable_input_is_not_a_crash():
    """The bridge writes atomically, but a truncated or absent file must
    degrade to nothing, never to a guess or a traceback.
    """
    for raw in ("", None, "not json", "[1,2]", '{"context_window": "wrong"}'):
        assert sidebar.parse_status(raw) == {
            "context": None, "model": None, "effort": None, "details": {},
        "transcript": None}


def test_no_pid_means_no_reading():
    """A session whose claude pid could not be resolved has no file to read.
    Unknown, not zero.
    """
    assert sidebar.read_status(None)["context"] is None
    assert sidebar.read_status(0)["context"] is None


def test_a_pid_with_no_file_reports_nothing():
    assert sidebar.read_status(999999)["context"] is None


def run_bridge(tmp_path, payload, original=None):
    """Run the real bridge against a throwaway HOME."""
    import os
    import subprocess
    env = dict(os.environ, HOME=str(tmp_path))
    if original is not None:
        d = tmp_path / ".claude" / "agents-sidebar-status"
        d.mkdir(parents=True)
        (d / "original-statusline").write_text(original)
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    done = subprocess.run([str(script)], input=payload, env=env,
                          capture_output=True, text=True, timeout=10)
    return done


def test_the_bridge_renders_the_displaced_statusline(tmp_path):
    """First responsibility. A sidebar that eats the user's statusline is a
    worse tool than one that shows no context figure.
    """
    done = run_bridge(tmp_path, '{"context_window":{"used_percentage":26}}',
                      original="cat > /dev/null; printf 'the original ran'")
    assert done.stdout == "the original ran"


def test_the_bridge_publishes_the_payload_for_its_parent(tmp_path):
    """Keyed by $PPID, which is the claude process -- the same pid the hook
    already reports, so no separate correlation step exists to get wrong.
    """
    import os
    run_bridge(tmp_path, json.dumps({
        "context_window": {"used_percentage": 26},
        "model": {"display_name": "Opus 5 (1M context)"},
        "effort": {"level": "high"}}), original="cat > /dev/null")
    written = list((tmp_path / ".claude" / "agents-sidebar-status").glob("*.json"))
    assert len(written) == 1
    assert written[0].stem.isdigit()
    got = sidebar.parse_status(written[0].read_text())
    assert (got["context"], got["model"], got["effort"]) == (26, "Opus 5", "high")


def test_the_bridge_survives_a_payload_it_cannot_parse(tmp_path):
    """Claude Code changing the payload shape must not cost the user their
    statusline. Nothing is published; the original still renders.
    """
    done = run_bridge(tmp_path, "not json at all",
                      original="cat > /dev/null; printf 'still here'")
    assert done.stdout == "still here"
    leftover = list((tmp_path / ".claude" / "agents-sidebar-status").iterdir())
    assert [p.name for p in leftover] == ["original-statusline"]


def test_the_pid_comes_out_of_the_state_variable():
    """The hook already resolves claude's pid and publishes it. Reusing it as
    the key into the statusline files means there is no second correlation
    step that can disagree with the first.
    """
    raw = json.dumps({"state": "idle", "pid": 4321, "agents": 0, "ts": 1})
    assert sidebar.parse_pid(raw) == 4321


def test_a_state_without_a_usable_pid_yields_none():
    for raw in (None, "", "not json", "{}", json.dumps({"pid": 0}),
                json.dumps({"pid": -1}), json.dumps({"pid": "x"})):
        assert sidebar.parse_pid(raw) is None


def test_the_model_name_drops_its_parenthetical():
    """The payload's display name carries the window size -- "Opus 5 (1M
    context)". A 250px row cannot hold it, and the percentage beside it is
    already normalised against that window, so the suffix says nothing the
    row does not already show.
    """
    payload = json.dumps({"model": {"display_name": "Opus 5 (1M context)"}})
    assert sidebar.parse_status(payload)["model"] == "Opus 5"


def test_a_model_name_without_a_parenthetical_is_left_alone():
    payload = json.dumps({"model": {"display_name": "Haiku 4.5"}})
    assert sidebar.parse_status(payload)["model"] == "Haiku 4.5"


def test_a_payload_older_than_the_render_interval_is_not_trusted(tmp_path, monkeypatch):
    """macOS reuses pids, and these files outlive the process they were named
    for. A live session rewrites its file every second (refreshInterval 1), so
    anything older is either a dead session or a pid that has come round again.
    Either way it describes someone else.
    """
    import os
    import time
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    stale = tmp_path / "4321.json"
    stale.write_text(json.dumps({"context_window": {"used_percentage": 99}}))
    old = time.time() - 600
    os.utime(stale, (old, old))
    assert sidebar.read_status(4321)["context"] is None


def test_a_payload_written_a_moment_ago_is_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    (tmp_path / "4321.json").write_text(
        json.dumps({"context_window": {"used_percentage": 42}}))
    assert sidebar.read_status(4321)["context"] == 42


#: The shapes below are from a payload captured off a live session on
#: 2026-09-07, not invented.
RICH = json.dumps({
    "context_window": {"used_percentage": 15},
    "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
    "effort": {"level": "high"},
    "thinking": {"enabled": True},
    "output_style": {"name": "Concise"},
    "fast_mode": False,
    "exceeds_200k_tokens": True,
    "version": "2.1.263",
    "rate_limits": {"five_hour": {"used_percentage": 7.000000000000001},
                    "seven_day": {"used_percentage": 65}},
    "cost": {"total_cost_usd": 110.123697, "total_lines_added": 40,
             "total_lines_removed": 13},
})


def test_the_details_carry_what_the_row_has_no_room_for():
    """The row shows a branch, a model and a percentage. Everything else the
    payload knows belongs behind a hover rather than nowhere.
    """
    details = sidebar.parse_status(RICH)["details"]
    assert details["model"] == "Opus 5 (1M context)"
    assert details["effort"] == "high"
    assert details["thinking"] is True
    assert details["fast_mode"] is False
    assert details["output_style"] == "Concise"
    assert details["version"] == "2.1.263"


def test_percentages_are_rounded_for_display():
    """The payload reports 7.000000000000001. Nobody wants to read that."""
    details = sidebar.parse_status(RICH)["details"]
    assert details["five_hour"] == 7
    assert details["seven_day"] == 65


def test_cost_and_lines_come_through():
    details = sidebar.parse_status(RICH)["details"]
    assert details["cost"] == 110.12
    assert details["lines_added"] == 40
    assert details["lines_removed"] == 13


def test_details_of_a_payload_that_has_none():
    """Absent fields are absent, not zero. A row with no payload shows no
    tooltip rather than a tooltip full of nulls.
    """
    assert sidebar.parse_status("{}")["details"] == {}
    assert sidebar.parse_status(None)["details"] == {}


CACHE = json.dumps({
    "rate_limits": {"five_hour": {"used_percentage": 7, "resets_at": 1788820200},
                    "seven_day": {"used_percentage": 65, "resets_at": 1789185600}},
    "prompt_cache": {"warm": True, "ttl": "1h", "expires_at": 1788808497,
                     "hit_ratio": 0.9625687753595553, "requests": 45, "misses": 1,
                     "recache_tokens_if_cold": 589037},
})


def test_a_limit_carries_when_it_resets():
    """A percentage is trivia. A percentage with a reset time is a decision:
    wait twenty minutes, or move to another session.
    """
    details = sidebar.parse_status(CACHE)["details"]
    assert details["five_hour_at"] == 1788820200
    assert details["seven_day_at"] == 1789185600


def test_the_cache_reports_what_going_cold_would_cost():
    """The strongest act-now signal in the payload: a session whose cache has
    expired pays this many tokens to rebuild it on the next turn.
    """
    details = sidebar.parse_status(CACHE)["details"]
    assert details["cache_hit"] == 96
    assert details["cache_cold_at"] == 1788808497
    assert details["recache"] == 589037


def test_a_payload_without_a_cache_says_nothing_about_one():
    assert "cache_hit" not in sidebar.parse_status("{}")["details"]


# --------------------------------------------------- the name an agent was given

def _transcript(tmp_path, records):
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


def test_the_agent_name_comes_off_the_transcript(tmp_path):
    """The pane title carries the agent's TYPE -- "general-purpose" -- while
    Claude Code's own UI shows the NAME it was spawned with, "ctx-fix". That
    name never reaches iTerm2 at all. Every user, assistant and attachment
    record in the agent's own transcript is stamped with it, so this is the one
    place a row can learn what to call it.
    """
    path = _transcript(tmp_path, [
        {"type": "user", "agentName": "ctx-fix", "uuid": "1"},
        {"type": "attachment", "agentName": "ctx-fix", "uuid": "2"},
    ])
    assert sidebar.transcript_marks(path)["agent"] == "ctx-fix"


def test_a_transcript_with_no_agent_name_yields_nothing(tmp_path):
    """A parent's own transcript, or an older format. Nothing to fall back on
    is a fine answer; a guess is not.
    """
    path = _transcript(tmp_path, [{"type": "user", "uuid": "1"}])
    assert sidebar.transcript_marks(path)["agent"] is None


def test_a_missing_transcript_is_not_an_error(tmp_path):
    """This runs for every row on every rebuild. A file that has been rotated
    away must cost that row its name, not the whole snapshot.
    """
    blank = {"agent": None, "team": None}
    assert sidebar.transcript_marks(str(tmp_path / "gone.jsonl")) == blank
    assert sidebar.transcript_marks(None) == blank
    assert sidebar.transcript_marks("") == blank


def test_a_half_written_last_line_is_skipped(tmp_path):
    """Claude Code appends to this file while we read it, so the final line is
    routinely a fragment.
    """
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "user", "agentName": "ctx-fix"}) + "\n"
                    + '{"type":"assistant","agentN', encoding="utf-8")
    assert sidebar.transcript_marks(str(path))["agent"] == "ctx-fix"


def test_only_the_tail_of_a_long_transcript_is_read(tmp_path):
    """A conversation's transcript reaches megabytes and this runs per row,
    twice a second. The name is taken from the end, where it is current.
    """
    path = tmp_path / "t.jsonl"
    filler = {"type": "user", "agentName": "stale", "pad": "x" * 4000}
    with open(path, "w", encoding="utf-8") as fh:
        for _ in range(200):
            fh.write(json.dumps(filler) + "\n")
        fh.write(json.dumps({"type": "user", "agentName": "ctx-fix"}) + "\n")
    assert path.stat().st_size > sidebar.TRANSCRIPT_TAIL_BYTES
    assert sidebar.transcript_marks(str(path))["agent"] == "ctx-fix"


def test_a_short_transcript_keeps_its_first_line(tmp_path):
    """The tail read discards a line the seek cut in half. A file smaller than
    the window was never cut, so its first line is real.
    """
    path = _transcript(tmp_path, [{"type": "user", "agentName": "only-line"}])
    assert sidebar.transcript_marks(str(path))["agent"] == "only-line"


def test_a_teammate_is_marked_by_the_team_it_belongs_to(tmp_path):
    """The one fact that separates a spawned teammate from an ordinary session
    that happens to share a tab and a directory. Measured 2026-09-08 across
    every live transcript: both teammates carried teamName
    "session-393d65ed"; all seven plain cs sessions carried none.

    isSidechain does NOT separate them -- it reads False on both -- which is
    what made this worth checking rather than assuming.
    """
    path = _transcript(tmp_path, [
        {"type": "user", "agentName": "ctx-fix", "teamName": "session-393d65ed"},
    ])
    assert sidebar.transcript_marks(path) == {"agent": "ctx-fix",
                                              "team": "session-393d65ed"}


def test_an_ordinary_session_belongs_to_no_team(tmp_path):
    """Its transcript names it, but nothing claims it as anyone's teammate."""
    path = _transcript(tmp_path, [{"type": "user", "agentName": "claude-sessions"}])
    assert sidebar.transcript_marks(path) == {"agent": "claude-sessions", "team": None}
