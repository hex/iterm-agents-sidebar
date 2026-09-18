"""Tests for how the daemon puts a large state back together.

The hook keeps the session variable small: past a ceiling it files the whole
published value under the session id and the variable carries the rest with
`detail: true`. The daemon reads the file back before any parser sees it.
"""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)

ENVELOPE = {"state": "working", "pid": 100, "session": "s-1", "agents": 2,
            "blocked_since": None, "working_since": 1789732000,
            "turn_started": 1789732000, "ts": 1789733000, "detail": True}
SUBAGENTS = [{"id": "a1", "type": "workflow-subagent", "name": "map:app-ui-layer",
              "since": 1789732485, "ended": None, "model": "claude-opus-5"}]
WHOLE = dict({k: v for k, v in ENVELOPE.items() if k != "detail"},
             subagents=SUBAGENTS, question=None)


def test_a_state_that_travelled_whole_is_left_alone(tmp_path):
    raw = json.dumps(WHOLE)
    assert sidebar.with_detail(raw, str(tmp_path)) == raw


def test_a_filed_detail_is_read_back(tmp_path):
    (tmp_path / "s-1.published").write_text(json.dumps(WHOLE))
    assert json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path))) == WHOLE


def test_a_detail_older_than_the_variable_keeps_its_subagents_and_loses_its_question(tmp_path):
    """Two hooks race: the later event's variable lands, the earlier one's file
    is what is on disk. Its question may have been answered since."""
    stale = dict(WHOLE, ts=1789732990, state="blocked",
                 question={"question": "Rows or columns?", "options": ["Rows", "Columns"]})
    (tmp_path / "s-1.published").write_text(json.dumps(stale))
    got = json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path)))
    assert got["subagents"] == SUBAGENTS
    assert got["state"] == "working" and got["ts"] == 1789733000
    assert got.get("question") is None


def test_a_detail_that_is_missing_or_broken_leaves_the_variable_as_it_came(tmp_path):
    raw = json.dumps(ENVELOPE)
    assert sidebar.with_detail(raw, str(tmp_path)) == raw
    (tmp_path / "s-1.published").write_text("{not json")
    assert sidebar.with_detail(raw, str(tmp_path)) == raw


def test_a_session_id_that_is_a_path_reads_no_file(tmp_path):
    """Any program in the pane can set the variable."""
    outside = tmp_path / "secret.published"
    outside.write_text(json.dumps(dict(WHOLE, state="blocked")))
    inner = tmp_path / "state"
    inner.mkdir()
    raw = json.dumps(dict(ENVELOPE, session="../secret"))
    assert sidebar.with_detail(raw, str(inner)) == raw


def test_what_is_not_a_state_passes_through(tmp_path):
    for raw in ("", None, "working", "[1, 2]"):
        assert sidebar.with_detail(raw, str(tmp_path)) == raw
