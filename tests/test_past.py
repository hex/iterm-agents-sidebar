"""Past conversations: what the Past sessions fold lists and what Resume opens.

Read from Claude Code's transcripts under ~/.claude/projects. A cs session is
one row however many conversations it held; any other directory is one row
per conversation. Live ones are left out, since their card is the row.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import past

NOW = 1793500000


def _transcript(projects, cwd, conversation, lines, age=3600, name="x"):
    folder = projects / cwd.replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name if name != 'x' else conversation}.jsonl"
    path.write_text("".join(json.dumps(dict(line, cwd=cwd, sessionId=conversation)) + "\n" for line in lines))
    os.utime(path, (NOW - age, NOW - age))
    return path


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _rows(tmp_path, **over):
    return past.rows(str(tmp_path / "projects"), NOW, **dict({"live_paths": set(), "live_conversations": set()}, **over))


def test_a_plain_directory_lists_one_row_per_conversation_titled_by_its_first_prompt(tmp_path):
    work = tmp_path / "work" / "repo"; work.mkdir(parents=True)
    _transcript(tmp_path / "projects", str(work), "11111111-1111-4111-8111-111111111111",
                [{"type": "file-history-snapshot"}, _user("<system-reminder>ignored</system-reminder>"),
                 _user("Fix the login redirect\nmore")], age=600)
    _transcript(tmp_path / "projects", str(work), "22222222-2222-4222-8222-222222222222",
                [_user("Add a test for the parser")], age=7200)
    assert _rows(tmp_path) == [
        {"kind": "claude", "name": "repo", "path": str(work), "conversation": "11111111-1111-4111-8111-111111111111",
         "title": "Fix the login redirect", "at": NOW - 600},
        {"kind": "claude", "name": "repo", "path": str(work), "conversation": "22222222-2222-4222-8222-222222222222",
         "title": "Add a test for the parser", "at": NOW - 7200}]


def test_a_cs_session_is_one_row_named_after_itself_at_its_newest_conversation(tmp_path):
    session = tmp_path / "sessions" / "demo"; (session / ".cs").mkdir(parents=True)
    _transcript(tmp_path / "projects", str(session), "11111111-1111-4111-8111-111111111111", [_user("first")], age=9000)
    _transcript(tmp_path / "projects", str(session), "22222222-2222-4222-8222-222222222222", [_user("second")], age=300)
    assert _rows(tmp_path) == [
        {"kind": "cs", "name": "demo", "path": str(session), "conversation": None, "title": None, "at": NOW - 300}]


def test_live_conversations_and_open_cs_sessions_are_not_past(tmp_path):
    work = tmp_path / "work" / "repo"; work.mkdir(parents=True)
    session = tmp_path / "sessions" / "demo"; (session / ".cs").mkdir(parents=True)
    _transcript(tmp_path / "projects", str(work), "11111111-1111-4111-8111-111111111111", [_user("open now")])
    _transcript(tmp_path / "projects", str(session), "22222222-2222-4222-8222-222222222222", [_user("open now")])
    assert _rows(tmp_path, live_conversations={"11111111-1111-4111-8111-111111111111"}, live_paths={str(session)}) == []


def test_subagent_transcripts_old_ones_and_gone_directories_are_left_out(tmp_path):
    work = tmp_path / "work" / "repo"; work.mkdir(parents=True)
    _transcript(tmp_path / "projects", str(work), "11111111-1111-4111-8111-111111111111", [_user("sub")],
                name="agent-abc")
    _transcript(tmp_path / "projects", str(work), "22222222-2222-4222-8222-222222222222", [_user("old")],
                age=past.DAYS * 86400 + 1)
    _transcript(tmp_path / "projects", str(tmp_path / "gone"), "33333333-3333-4333-8333-333333333333", [_user("gone")])
    assert _rows(tmp_path) == []


def test_a_conversation_with_no_prompt_is_titled_by_nothing_and_still_listed(tmp_path):
    work = tmp_path / "work" / "repo"; work.mkdir(parents=True)
    _transcript(tmp_path / "projects", str(work), "11111111-1111-4111-8111-111111111111", [{"type": "mode"}])
    [row] = _rows(tmp_path)
    assert row["title"] is None and row["conversation"] == "11111111-1111-4111-8111-111111111111"


def test_the_list_is_capped_at_the_newest(tmp_path):
    work = tmp_path / "work" / "repo"; work.mkdir(parents=True)
    for i in range(past.MOST + 5):
        _transcript(tmp_path / "projects", str(work), f"{i:08d}-0000-4000-8000-000000000000", [_user(f"p{i}")], age=i)
    rows = _rows(tmp_path)
    assert len(rows) == past.MOST and rows[0]["title"] == "p0"


def test_no_projects_folder_is_an_empty_list(tmp_path):
    assert _rows(tmp_path) == []


def test_a_conversation_inside_a_sessions_own_folders_is_not_a_row(tmp_path):
    """Claude Code's subagent worktrees and a session's .cs folder hold
    transcripts of their own; neither is a place anyone resumes into."""
    session = tmp_path / "sessions" / "demo"; (session / ".cs" / "memory").mkdir(parents=True)
    (session / ".claude" / "worktrees" / "agent-abc").mkdir(parents=True)
    _transcript(tmp_path / "projects", str(session / ".cs" / "memory"), "11111111-1111-4111-8111-111111111111", [_user("m")])
    _transcript(tmp_path / "projects", str(session / ".claude" / "worktrees" / "agent-abc"),
                "22222222-2222-4222-8222-222222222222", [_user("w")])
    assert _rows(tmp_path) == []
