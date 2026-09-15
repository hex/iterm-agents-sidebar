"""Claude Code's directory locks, exercised on real directories in a temp folder.

proper-lockfile's protocol: the lock is a directory, mkdir is the mutex, a lock
whose mtime is older than its staleness belongs to a dead holder, and a live
holder keeps touching it.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import DirLock, LockTimeout


def test_a_free_lock_is_held_as_a_directory_and_removed_on_release(tmp_path):
    path = tmp_path / ".oauth_refresh.lock"
    with DirLock(str(path), stale=60):
        assert path.is_dir()
    assert not path.exists()


def test_a_lock_a_live_holder_keeps_fresh_times_out(tmp_path):
    path = tmp_path / ".claude.lock"
    path.mkdir()
    started = time.monotonic()
    with pytest.raises(LockTimeout, match="Claude Code is refreshing, try again"):
        with DirLock(str(path), stale=60, timeout=0.4):
            pass
    assert 0.4 <= time.monotonic() - started < 2
    assert path.is_dir(), "a lock we never took must not be removed"


def test_a_lock_older_than_its_staleness_is_taken_over(tmp_path):
    path = tmp_path / ".claude.json.lock"
    path.mkdir()
    old = time.time() - 11
    os.utime(path, (old, old))
    with DirLock(str(path), stale=10, timeout=1):
        assert time.time() - path.stat().st_mtime < 5
    assert not path.exists()


def test_a_held_lock_is_touched_so_nobody_takes_it_over(tmp_path):
    path = tmp_path / ".oauth_refresh.lock"
    with DirLock(str(path), stale=60, touch_every=0.1):
        old = time.time() - 30
        os.utime(path, (old, old))
        time.sleep(0.35)
        assert time.time() - path.stat().st_mtime < 1


def test_releasing_a_lock_someone_removed_does_not_raise(tmp_path):
    path = tmp_path / ".claude.lock"
    with DirLock(str(path), stale=60):
        path.rmdir()
    assert not path.exists()


def test_the_lock_is_not_taken_when_its_parent_directory_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        with DirLock(str(tmp_path / "absent" / ".oauth_refresh.lock"), stale=60, timeout=0.2):
            pass


def test_a_second_holder_waits_for_the_first_to_release(tmp_path):
    path = str(tmp_path / ".claude.lock")
    order = []
    first_holds = threading.Event()

    def first():
        with DirLock(path, stale=60):
            order.append("first in")
            first_holds.set()
            time.sleep(0.3)
            order.append("first out")

    thread = threading.Thread(target=first)
    thread.start()
    first_holds.wait(2)
    with DirLock(path, stale=60, timeout=3):
        order.append("second in")
    thread.join()
    assert order == ["first in", "first out", "second in"]
