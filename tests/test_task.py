"""Tests for the task note a session writes about its own work.

The rules follow herdr-agent-progress (read 2026-09-16): a title per
request, a rough percent that may fall, a short activity, 100 locks.
"""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "task", Path(__file__).resolve().parent.parent / "plugin" / "hooks-handlers" / "task.py")
task = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task)


def run(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(task, "TASKS_DIR", str(tmp_path / "tasks"))
    code = task.main(argv)
    return code, capsys.readouterr()


def note(tmp_path):
    return json.loads((tmp_path / "tasks" / "s1.json").read_text())


def test_begin_starts_a_task_with_a_title_and_nothing_reported_yet(tmp_path, monkeypatch, capsys):
    code, out = run(["--session", "s1", "begin", "--title", "Fix the login bug"], tmp_path, monkeypatch, capsys)
    assert code == 0 and out.err == ""
    got = note(tmp_path)
    assert (got["title"], got["activity"], got["percent"], got["done"]) == ("Fix the login bug", None, None, False)
    assert len(got["task"]) >= 8 and got["ts"] > 1_700_000_000


def test_report_sets_activity_percent_and_time_and_keeps_the_task(tmp_path, monkeypatch, capsys):
    run(["--session", "s1", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    before = note(tmp_path)
    code, out = run(["--session", "s1", "report", "--activity", "Reading code", "--percent", "35"], tmp_path, monkeypatch, capsys)
    assert code == 0 and out.err == ""
    got = note(tmp_path)
    assert (got["task"], got["activity"], got["percent"], got["done"]) == (before["task"], "Reading code", 35, False)


def test_unknown_reports_an_activity_with_no_percent(tmp_path, monkeypatch, capsys):
    run(["--session", "s1", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    run(["--session", "s1", "report", "--activity", "Reading code", "--percent", "40"], tmp_path, monkeypatch, capsys)
    code, _ = run(["--session", "s1", "report", "--activity", "Assessing task", "--unknown"], tmp_path, monkeypatch, capsys)
    assert code == 0
    assert note(tmp_path)["percent"] is None


def test_a_hundred_means_done_and_locks_the_task(tmp_path, monkeypatch, capsys):
    run(["--session", "s1", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    run(["--session", "s1", "report", "--activity", "All checks pass", "--percent", "100"], tmp_path, monkeypatch, capsys)
    got = note(tmp_path)
    assert (got["done"], got["percent"], got["activity"]) == (True, 100, "Done")
    code, out = run(["--session", "s1", "report", "--activity", "More work", "--percent", "70"], tmp_path, monkeypatch, capsys)
    assert code == 1 and "done" in out.err.lower()
    assert note(tmp_path)["percent"] == 100


def test_begin_replaces_a_finished_task(tmp_path, monkeypatch, capsys):
    run(["--session", "s1", "begin", "--title", "First"], tmp_path, monkeypatch, capsys)
    run(["--session", "s1", "report", "--activity", "Done", "--percent", "100"], tmp_path, monkeypatch, capsys)
    first = note(tmp_path)["task"]
    run(["--session", "s1", "begin", "--title", "Second"], tmp_path, monkeypatch, capsys)
    got = note(tmp_path)
    assert got["task"] != first and (got["title"], got["done"], got["percent"]) == ("Second", False, None)


def test_report_without_a_task_is_refused(tmp_path, monkeypatch, capsys):
    code, out = run(["--session", "s1", "report", "--activity", "Reading", "--percent", "10"], tmp_path, monkeypatch, capsys)
    assert code == 1 and "begin" in out.err
    assert not (tmp_path / "tasks" / "s1.json").exists()


def test_text_is_cleaned_and_cut_to_its_width():
    assert task.clean("Hi\n‮ there", 80) == "Hi there"
    assert task.clean("x" * 100, 80) == "x" * 80
    assert task.clean("   ", 80) == ""


def test_an_empty_title_or_activity_is_refused(tmp_path, monkeypatch, capsys):
    code, out = run(["--session", "s1", "begin", "--title", "  "], tmp_path, monkeypatch, capsys)
    assert code == 1 and "empty" in out.err
    run(["--session", "s1", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    code, out = run(["--session", "s1", "report", "--activity", "⁦", "--percent", "5"], tmp_path, monkeypatch, capsys)
    assert code == 1 and "empty" in out.err


def test_percent_outside_the_range_is_refused(tmp_path, monkeypatch, capsys):
    run(["--session", "s1", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    code, out = run(["--session", "s1", "report", "--activity", "Reading", "--percent", "120"], tmp_path, monkeypatch, capsys)
    assert code == 1 and "0" in out.err and "100" in out.err


def test_a_session_id_that_is_not_a_plain_token_is_refused(tmp_path, monkeypatch, capsys):
    code, out = run(["--session", "../x", "begin", "--title", "Fix"], tmp_path, monkeypatch, capsys)
    assert code == 1 and "session" in out.err
    assert not (tmp_path / "x.json").exists()


def test_read_note_tolerates_a_missing_or_broken_file(tmp_path):
    assert task.read_note(str(tmp_path / "none.json")) is None
    (tmp_path / "bad.json").write_text("{not json")
    assert task.read_note(str(tmp_path / "bad.json")) is None
