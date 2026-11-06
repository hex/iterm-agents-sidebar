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
TASKS = [{"id": "3", "status": "in_progress", "subject": "Registry flags", "doing": "Building"}]
WHOLE = dict({k: v for k, v in ENVELOPE.items() if k != "detail"},
             subagents=SUBAGENTS, question=None, tasks=TASKS, tasks_done=40)


def test_a_state_that_travelled_whole_is_left_alone(tmp_path):
    raw = json.dumps(WHOLE)
    assert sidebar.with_detail(raw, str(tmp_path)) == raw


def test_a_filed_detail_is_read_back(tmp_path):
    (tmp_path / "s-1.published").write_text(json.dumps(WHOLE))
    assert json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path))) == WHOLE


def test_a_detail_older_than_the_variable_keeps_its_subagents_and_tasks_and_loses_its_question(tmp_path):
    """Two hooks race: the later event's variable lands, the earlier one's file
    is what is on disk. Its question may have been answered since; its tasks
    are the list as it was, which the next event corrects."""
    stale = dict(WHOLE, ts=1789732990, state="blocked",
                 question={"question": "Rows or columns?", "options": ["Rows", "Columns"]})
    (tmp_path / "s-1.published").write_text(json.dumps(stale))
    got = json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path)))
    assert got["subagents"] == SUBAGENTS
    assert got["tasks"] == TASKS
    assert got.get("tasks_done") == 40
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


def test_completed_task_count_accepts_only_nonnegative_integers():
    for value, expected in [(40, 40), (0, 0), (-1, None), (True, None),
                            (False, None), (1.5, None), ("40", None), (None, None)]:
        assert sidebar.parse_tasks_done(json.dumps({"tasks_done": value})) == expected
    for raw in [None, "", "{broken", "[]", "{}", "null"]:
        assert sidebar.parse_tasks_done(raw) is None


CRONS = [{"id": "6ba43431", "schedule": "*/10 * * * *", "recurring": True, "prompt": "say hello"},
         {"id": "20c147b9", "schedule": "31 13 * * *", "recurring": False, "prompt": "wake me"}]


def test_scheduled_prompts_are_read_whole_or_not_at_all():
    """Any program in the pane can set the variable; a list with one entry
    the hook would never write is not the hook's list."""
    assert sidebar.parse_crons(json.dumps({"crons": CRONS})) == CRONS
    assert sidebar.parse_crons(json.dumps({"crons": []})) == []
    for raw in [None, "", "{broken", "[]", "{}", "null", '{"crons": null}', '{"crons": "6ba43431"}',
                json.dumps({"crons": CRONS[0]})]:
        assert sidebar.parse_crons(raw) is None, raw
    without_prompt = {key: value for key, value in CRONS[1].items() if key != "prompt"}
    for second in [dict(CRONS[1], recurring=1), dict(CRONS[1], recurring="false"), dict(CRONS[1], id=7),
                   dict(CRONS[1], schedule=None), dict(CRONS[1], prompt=["wake me"]), without_prompt,
                   dict(CRONS[1], durable=True), "20c147b9"]:
        assert sidebar.parse_crons(json.dumps({"crons": [CRONS[0], second]})) is None, second


def test_a_detail_older_than_the_variable_keeps_its_scheduled_prompts_and_adds_none_it_never_listed(tmp_path):
    """The prompts change only at a Stop, so the older file's list still
    stands, and when it was listed with it; a file from before any Stop
    listed them says nothing of them."""
    for listed in (CRONS, []):
        (tmp_path / "s-1.published").write_text(json.dumps(dict(WHOLE, ts=1789732990, crons=listed,
                                                                crons_at=1789732400.125)))
        got = json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path)))
        assert (got["crons"], got["crons_at"]) == (listed, 1789732400.125)
    (tmp_path / "s-1.published").write_text(json.dumps(dict(WHOLE, ts=1789732990)))
    got = json.loads(sidebar.with_detail(json.dumps(ENVELOPE), str(tmp_path)))
    assert "crons" not in got and "crons_at" not in got


def test_when_the_scheduled_prompts_were_listed_is_read_only_as_a_moment():
    """Any program in the pane can set the variable, and a one-shot's run is
    counted from this, so it has to be a time a clock can read."""
    for value, expected in [(1789732400.125, 1789732400.125), (1789732400, 1789732400), (0, None), (-1, None),
                            (True, None), (False, None), ("1789732400", None), (None, None), ([1789732400], None)]:
        assert sidebar.parse_crons_at(json.dumps({"crons_at": value})) == expected, value
    for raw in [None, "", "{broken", "[]", "{}", "null", '{"crons_at": Infinity}', '{"crons_at": -Infinity}',
                '{"crons_at": NaN}']:
        assert sidebar.parse_crons_at(raw) is None, raw
