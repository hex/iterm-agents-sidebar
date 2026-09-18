"""Tests for clearing what dead sessions leave in the hook's state directory.

The hook removes a session's files at SessionEnd. A session that is killed,
or whose machine restarts, never sends one.
"""
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)

NOW = 1_800_000_000
DAY = 24 * 60 * 60
OLD, NEW = NOW - 2 * DAY, NOW - 60


def test_a_dead_sessions_files_are_stale_together():
    entries = [("dead", OLD), ("dead.lock", OLD), ("dead.published", OLD), ("dead.4242.tmp", OLD)]
    assert sorted(sidebar.stale_state_entries(entries, NOW, live=set())) == [
        "dead", "dead.4242.tmp", "dead.lock", "dead.published"]


def test_a_session_with_a_card_keeps_everything_however_old():
    """An agent left idle overnight has written nothing for a day."""
    entries = [("idle", OLD), ("idle.lock", OLD), ("idle.published", OLD)]
    assert sidebar.stale_state_entries(entries, NOW, live={"idle"}) == []


def test_a_session_that_wrote_lately_keeps_its_old_lock():
    """Its card may be missing for one rebuild; its lock is never touched."""
    entries = [("busy", NEW), ("busy.lock", OLD)]
    assert sidebar.stale_state_entries(entries, NOW, live=set()) == []


def test_the_sweep_removes_only_what_is_stale(tmp_path):
    for name, mtime in [("dead", OLD), ("dead.lock", OLD), ("dead.published", OLD),
                        ("idle", OLD), ("busy", NEW), ("busy.lock", OLD)]:
        (tmp_path / name).write_text("{}")
        os.utime(tmp_path / name, (mtime, mtime))
    sidebar.sweep_state_dir(NOW, live={"idle"}, directory=str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["busy", "busy.lock", "idle"]


def test_the_sweep_of_a_missing_state_directory_is_not_an_error(tmp_path):
    sidebar.sweep_state_dir(NOW, live=set(), directory=str(tmp_path / "absent"))
