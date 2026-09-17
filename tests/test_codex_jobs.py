"""Tests for the Codex jobs a Claude session started through the codex plugin.

The job shape is the plugin's state.json as read on 2026-09-17 (codex 1.0.6,
lib/state.mjs), with placeholder paths and ids.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar  # noqa: E402

SESSION = "00000000-0000-4000-8000-000000000001"


def job(**fields):
    base = {"id": "task-aaa-111", "kind": "task", "kindLabel": "rescue", "title": "Codex Task",
            "workspaceRoot": "/tmp/example", "jobClass": "task", "summary": "<task>",
            "sessionId": SESSION, "status": "running", "phase": "verifying", "pid": 4242,
            "createdAt": "2026-09-17T15:00:00.000Z", "startedAt": "2026-09-17T15:00:01.000Z",
            "updatedAt": "2026-09-17T15:00:05.000Z",
            "request": {"cwd": "/tmp/example", "prompt": "a long prompt"}}
    return {**base, **fields}


def state(*jobs, version=1):
    return json.dumps({"version": version, "config": {}, "jobs": list(jobs)})


def test_a_state_file_reads_as_jobs_without_their_prompts_or_results():
    [got] = sidebar.parse_codex_state(state(job(result="{...}", rendered="# Review")))
    assert got == {"id": "task-aaa-111", "session": SESSION, "kind": "rescue",
                   "status": "running", "phase": "verifying", "pid": 4242,
                   "since": 1789657201, "ended": None}


def test_a_finished_job_ends_when_it_completed():
    [got] = sidebar.parse_codex_state(state(job(status="completed", phase="done", pid=None,
                                                completedAt="2026-09-17T15:03:00.000Z")))
    assert (got["status"], got["ended"]) == ("completed", 1789657380)


def test_what_cannot_be_read_is_left_out():
    assert sidebar.parse_codex_state(state(job(), version=2)) == []
    assert sidebar.parse_codex_state(state(job(sessionId=None), job(status=7), "x")) == []
    assert sidebar.parse_codex_state("{broken") == []
    assert sidebar.parse_codex_state(json.dumps({"version": 1, "jobs": "many"})) == []


PROMPT_AT = 1789657000


def rows(*jobs, session=SESSION, turn_started=PROMPT_AT, live=(4242,)):
    parsed = sidebar.parse_codex_state(state(*jobs))
    return sidebar.codex_job_rows(parsed, session, turn_started, set(live))


def test_a_running_job_is_a_row_under_the_session_that_started_it():
    assert rows(job()) == [{"id": "task-aaa-111", "parent": None, "type": "rescue",
                            "since": 1789657201, "ended": None, "name": None, "model": None,
                            "provider": "codex", "phase": "verifying"}]
    assert rows(job(), session="00000000-0000-4000-8000-000000000002") == []


def test_a_running_job_whose_process_is_gone_is_not_running():
    """Two jobs in the store still read running from July: the companion
    died mid-job and never wrote the end."""
    assert rows(job(), live=()) == []


def test_a_queued_job_has_no_process_yet_and_is_believed():
    [got] = rows(job(status="queued", phase="queued", pid=None, startedAt=None))
    assert (got["ended"], got["since"]) == (None, 1789657200)


def test_a_job_that_ended_this_turn_stays_and_one_from_an_earlier_turn_does_not():
    ended = dict(status="completed", phase="done", pid=None, completedAt="2026-09-17T15:03:00.000Z")
    [got] = rows(job(**ended))
    assert (got["ended"], got["phase"]) == (1789657380, "done")
    assert rows(job(**ended), turn_started=1789657400) == []
    assert rows(job(**ended), turn_started=None) == []


def test_codex_rows_take_their_place_among_subagents_by_start_time():
    """A job belongs to the session, not to the subagent that may have
    started it, so it sits at the top level and never splits a subtree."""
    subs = [{"since": 10, "depth": 0}, {"since": 30, "depth": 1},
            {"since": 50, "depth": 0}]
    got = sidebar.merge_codex_rows(subs, [{"since": 20, "provider": "codex"},
                                          {"since": 60, "provider": "codex"}])
    assert [(r["since"], r["depth"]) for r in got] == [(10, 0), (30, 1), (20, 0), (50, 0), (60, 0)]


def test_the_turn_start_is_read_off_the_state_variable():
    assert sidebar.parse_turn_started(json.dumps({"turn_started": 1789657000})) == 1789657000
    assert sidebar.parse_turn_started(json.dumps({"state": "idle"})) is None
    assert sidebar.parse_turn_started("garbage") is None
    assert sidebar.parse_turn_started(None) is None


def test_every_workspace_store_is_read_and_a_broken_one_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sidebar, "CODEX_JOBS_DIR", str(tmp_path))
    for name, text in (("a-1", state(job(id="task-a"))), ("b-2", state(job(id="task-b"))),
                       ("c-3", "{broken")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "state.json").write_text(text)
    (tmp_path / "d-4").mkdir()
    assert sorted(j["id"] for j in sidebar.read_codex_jobs()) == ["task-a", "task-b"]
    monkeypatch.setattr(sidebar, "CODEX_JOBS_DIR", str(tmp_path / "absent"))
    assert sidebar.read_codex_jobs() == []
