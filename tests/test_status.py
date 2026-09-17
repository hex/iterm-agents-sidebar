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
        "transcript": None, "session": "x"}


def test_unreadable_input_is_not_a_crash():
    """The bridge writes atomically, but a truncated or absent file must
    degrade to nothing, never to a guess or a traceback.
    """
    for raw in ("", None, "not json", "[1,2]", '{"context_window": "wrong"}'):
        assert sidebar.parse_status(raw) == {
            "context": None, "model": None, "effort": None, "details": {},
        "transcript": None, "session": None}


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


def test_the_bridge_names_its_parent_for_the_statusline_it_runs(tmp_path):
    """cs-statusline keys two per-conversation caches on its parent pid,
    because Claude Code is the same parent for every render. Under the
    bridge the render's parent is a new bridge process each tick, so the
    caches would miss every render; the bridge names the pid it is itself
    the child of in CS_STATUSLINE_PARENT, set per run, never in a profile.
    """
    import os
    done = run_bridge(tmp_path, '{"context_window":{"used_percentage":26}}',
                      original="cat > /dev/null; printf '%s' \"$CS_STATUSLINE_PARENT\"")
    assert done.stdout == str(os.getpid())


def test_the_bridge_survives_a_payload_it_cannot_parse(tmp_path):
    """Claude Code changing the payload shape must not cost the user their
    statusline. Nothing is published; the original still renders.
    """
    done = run_bridge(tmp_path, "not json at all",
                      original="cat > /dev/null; printf 'still here'")
    assert done.stdout == "still here"
    leftover = [p.name for p in (tmp_path / ".claude" / "agents-sidebar-status").iterdir()
                if not p.name.endswith(".line")]
    assert leftover == ["original-statusline"]


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


def test_the_bridge_publishes_without_jq_and_without_forking_a_parser(tmp_path):
    """Live, 2026-09-16: with eight sessions each rendering once a second the
    bridge took 1.6 s a run, Claude Code killed the overrunning renders, and a
    new session's statusline never appeared. Publishing must cost a file
    write, not a jq process.
    """
    import os
    import subprocess
    # /bin has cat, mkdir, mv and rm; jq lives elsewhere.
    env = dict(os.environ, HOME=str(tmp_path), PATH="/bin")
    d = tmp_path / ".claude" / "agents-sidebar-status"
    d.mkdir(parents=True)
    (d / "original-statusline").write_text("cat > /dev/null; printf 'rendered'")
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    assert subprocess.run(["/bin/sh", "-c", "command -v jq"], env=env, capture_output=True).returncode != 0
    payload = json.dumps({"context_window": {"used_percentage": 41}, "model": {"display_name": "Fable 5.1"}})
    done = subprocess.run([str(script)], input=payload, env=env, capture_output=True, text=True, timeout=10)
    assert done.stdout == "rendered"
    written = [p for p in d.iterdir() if p.suffix == ".json"]
    assert len(written) == 1
    assert sidebar.parse_status(written[0].read_text())["context"] == 41


def test_the_bridge_answers_from_its_last_line_while_a_slow_render_catches_up(tmp_path):
    """Live, 2026-09-16: Claude Code runs the statusline once a second and
    kills a render that is still going when the next tick comes. With eight
    sessions and a 0.9 s statusline, 349 of 349 renders in 45 s were killed,
    and a new session never showed a line. The bridge therefore prints the
    line it rendered last, at once, and renders the next one in the
    background, out of reach of the kill.
    """
    import os
    import subprocess
    import time
    env = dict(os.environ, HOME=str(tmp_path))
    d = tmp_path / ".claude" / "agents-sidebar-status"
    d.mkdir(parents=True)
    (d / "original-statusline").write_text("cat > /dev/null; sleep 4; printf 'tick'")
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    payload = '{"context_window":{"used_percentage":1}}'
    first = subprocess.run([str(script)], input=payload, env=env, capture_output=True, text=True, timeout=20)
    assert first.stdout == "tick"
    # A render is in flight for this session (the lock is fresh): this tick
    # answers from the last line and does not wait the render's four seconds.
    (d / f"{os.getpid()}.rendering").mkdir()
    started = time.monotonic()
    second = subprocess.run(["/bin/sh", "-c", f'exec "{script}"'], input=payload, env=env,
                            capture_output=True, text=True, timeout=20)
    assert second.stdout == "tick"
    assert time.monotonic() - started < 4


def test_a_render_outlives_the_term_of_the_bridge_and_its_group(tmp_path):
    """Claude Code sends the bridge's process group SIGTERM when the next
    tick comes, and nothing after (probed live, 2026-09-16: bridges that
    ignored it ran on for 20 s). The bridge ignores it, so the render
    keeps its parent and the line still lands for the tick after.
    """
    import os
    import signal
    import subprocess
    import time
    env = dict(os.environ, HOME=str(tmp_path))
    d = tmp_path / ".claude" / "agents-sidebar-status"
    d.mkdir(parents=True)
    (d / "original-statusline").write_text("cat > /dev/null; sleep 1.5; printf 'landed'")
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    bridge = subprocess.Popen([str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    bridge.stdin.write(b'{"context_window":{"used_percentage":1}}')
    bridge.stdin.close()
    # The lock appears once the bridge is past its trap and rendering; a
    # fixed half-second was not enough on a loaded machine.
    deadline = time.monotonic() + 10
    while not list(d.glob("*.rendering")) and time.monotonic() < deadline:
        time.sleep(0.05)
    os.killpg(bridge.pid, signal.SIGTERM)
    bridge.wait(timeout=20)
    deadline = time.monotonic() + 10
    while not list(d.glob("*.line")) and time.monotonic() < deadline:
        time.sleep(0.2)
    lines = list(d.glob("*.line"))
    assert [p.read_text() for p in lines] == ["landed"]


def test_a_stale_lock_does_not_freeze_the_line(tmp_path):
    """A render that died without cleaning up leaves its lock. Once a line
    exists the fast path never looked at the lock's age, so the line stayed
    as it was for good.
    """
    import os
    import subprocess
    env = dict(os.environ, HOME=str(tmp_path))
    d = tmp_path / ".claude" / "agents-sidebar-status"
    d.mkdir(parents=True)
    (d / "original-statusline").write_text("cat > /dev/null; printf 'fresh'")
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    pid = os.getpid()
    (d / f"{pid}.line").write_text("stale")
    lock = d / f"{pid}.rendering"
    lock.mkdir()
    os.utime(lock, (0, 0))
    payload = '{"context_window":{"used_percentage":1}}'
    subprocess.run([str(script)], input=payload, env=env, capture_output=True, text=True, timeout=10)
    assert (d / f"{pid}.line").read_text() == "fresh"
    assert not lock.exists()


def test_a_render_killed_outright_leaves_nothing_the_next_render_does_not_reuse(tmp_path):
    """Live, 2026-09-16: something outside the bridge SIGKILLs every session's
    in-flight render once every 30 to 60 s (traced: 20 renders started, no
    "rendered" and no EXIT trap, all within one burst). Each left a
    <pid>.line.<pid> temp file, 316 of them in an hour. The temp name must
    not carry the render's pid: the lock already grants one writer, so the
    next render overwrites the same file and nothing accumulates.
    """
    import os
    import signal
    import subprocess
    import time
    env = dict(os.environ, HOME=str(tmp_path))
    d = tmp_path / ".claude" / "agents-sidebar-status"
    d.mkdir(parents=True)
    (d / "original-statusline").write_text("cat > /dev/null; printf 'half'; sleep 5; printf 'done'")
    script = Path(__file__).resolve().parent.parent / "plugin" / "statusline-bridge.sh"
    payload = '{"context_window":{"used_percentage":1}}'
    bridge = subprocess.Popen([str(script)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env=env, start_new_session=True)
    bridge.stdin.write(payload.encode())
    bridge.stdin.close()
    pid = os.getpid()
    lock = d / f"{pid}.rendering"
    # Kill once the render is under way, not after a fixed pause: at load 100
    # the bridge had not opened its temp file two seconds in.
    deadline = time.monotonic() + 10
    while not (d / f"{pid}.line.tmp").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    os.killpg(bridge.pid, signal.SIGKILL)
    bridge.wait(timeout=5)
    assert lock.is_dir(), sorted(p.name for p in d.iterdir())
    assert (d / f"{pid}.line.tmp").exists(), sorted(p.name for p in d.iterdir())
    old = time.time() - 15
    os.utime(lock, (old, old))
    (d / "original-statusline").write_text("cat > /dev/null; printf 'fresh'")
    subprocess.run(["/bin/sh", "-c", f'exec "{script}"'], input=payload, env=env,
                   capture_output=True, text=True, timeout=10)
    assert sorted(p.name for p in d.iterdir()) == [
        f"{pid}.json", f"{pid}.line", "original-statusline"]
    assert (d / f"{pid}.line").read_text() == "fresh"


DAY = 86400


def test_status_files_a_day_old_are_stale_whatever_shape_the_bridge_gave_them():
    """Counted 2026-09-16: 492 entries for 9 live sessions. Dead sessions
    leave <pid>.json, <pid>.line and a <pid>.rendering lock; earlier bridge
    designs left <pid>.json.<pid> and <pid>.line.<pid> temp files, the
    current one <pid>.line.tmp. A live session rewrites its files every
    second, so a day-old one belongs to nobody.
    """
    now = 1_800_000_000
    old = now - DAY - 1
    entries = [
        ("123.json", old), ("123.line", old), ("123.rendering", old),
        ("37314.line.15700", old), ("37314.json.15700", old), ("123.line.tmp", old),
        ("456.json", now - 1), ("456.line", now - 30), ("456.rendering", now - DAY + 60),
        ("original-statusline", 0), ("notes.json", old), ("123.txt", old),
    ]
    assert sidebar.stale_status_entries(entries, now) == [
        "123.json", "123.line", "123.rendering",
        "37314.line.15700", "37314.json.15700", "123.line.tmp"]


def test_the_sweep_removes_stale_files_and_lock_dirs_and_keeps_the_rest(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    # Both directories, always: with a `now` set in the future and the real
    # tasks directory left in place, this test deleted every live session's
    # note on the machine each time the suite ran.
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tmp_path / "tasks"))
    now = 1_800_000_000
    old = now - DAY - 1
    (tmp_path / "123.json").write_text("{}")
    (tmp_path / "123.rendering").mkdir()
    (tmp_path / "456.json").write_text("{}")
    (tmp_path / "original-statusline").write_text("cat")
    for name in ("123.json", "123.rendering", "original-statusline"):
        os.utime(tmp_path / name, (old, old))
    os.utime(tmp_path / "456.json", (now, now))
    sidebar.sweep_status_dir(now)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["456.json", "original-statusline"]


def test_the_sweep_also_clears_day_old_task_notes(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tmp_path / "tasks"))
    (tmp_path / "tasks").mkdir()
    now = 1_800_000_000
    (tmp_path / "tasks" / "old.json").write_text("{}")
    (tmp_path / "tasks" / "live.json").write_text("{}")
    os.utime(tmp_path / "tasks" / "old.json", (now - DAY - 1, now - DAY - 1))
    os.utime(tmp_path / "tasks" / "live.json", (now - 60, now - 60))
    sidebar.sweep_status_dir(now)
    assert sorted(p.name for p in (tmp_path / "tasks").iterdir()) == ["live.json"]


def test_the_sweep_of_a_missing_directory_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path / "absent"))
    monkeypatch.setattr(sidebar, "TASKS_DIR", str(tmp_path / "absent-too"))
    sidebar.sweep_status_dir(1_800_000_000)


def test_the_payload_names_the_session_it_belongs_to():
    got = sidebar.parse_status(json.dumps({"session_id": "6a4d1211-632c-4c8e-9c0a-000000000001"}))
    assert got["session"] == "6a4d1211-632c-4c8e-9c0a-000000000001"
