"""Tests for commit_days(): a card's project, as commits per day for twelve weeks.

Every case runs real git on a repository made in a temporary directory, with
commit dates set through the environment.
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from sidebar import COMMIT_DAYS, commit_days  # noqa: E402

TODAY = date(2026, 10, 14)


def git(repo, *args, when=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b",
           "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b"}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{when}T12:00:00"
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def commit(repo, when, author=None):
    if author:
        git(repo, "-c", f"user.name={author}", "commit", "--allow-empty", "-m", when, when=when)
    else:
        git(repo, "commit", "--allow-empty", "-m", when, when=when)


def make_repo(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo


def test_twelve_weeks_end_today_oldest_first(tmp_path):
    repo = make_repo(tmp_path)
    for when in ["2026-07-22", "2026-07-23", "2026-07-23", "2026-10-13", "2026-10-14", "2026-10-14", "2026-10-14",
                 "2026-10-15"]:
        commit(repo, when)
    days = commit_days(str(repo), TODAY)
    assert COMMIT_DAYS == 84
    assert len(days) == 84
    # 2026-07-23 is the first of the 84 days; 2026-07-22 and 2026-10-15 fall outside.
    assert days[0] == 2
    assert days[82] == 1
    assert days[83] == 3
    assert sum(days) == 6


def test_every_ref_and_author_counts_but_not_a_stash(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "2026-10-01")
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, "2026-10-02", author="bob")
    git(repo, "checkout", "-q", "--detach")
    commit(repo, "2026-10-04")
    git(repo, "tag", "only-a-tag")
    git(repo, "checkout", "-q", "main")
    (repo / "f").write_text("x")
    git(repo, "add", "f")
    git(repo, "stash", when="2026-10-03")
    days = commit_days(str(repo), TODAY)
    assert days[83 - 13] == 1
    assert days[83 - 12] == 1
    assert days[83 - 11] == 0
    assert days[83 - 10] == 1
    assert sum(days) == 3


def test_a_subfolder_reads_its_repository(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "2026-10-10")
    (repo / "src").mkdir()
    assert sum(commit_days(str(repo / "src"), TODAY)) == 1


def test_a_repository_with_no_recent_commits_is_all_zero(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "2026-01-01")
    assert commit_days(str(repo), TODAY) == [0] * 84


def test_no_repository_reads_none(tmp_path):
    assert commit_days(str(tmp_path), TODAY) is None


def test_a_repository_with_no_commits_is_all_zero(tmp_path):
    assert commit_days(str(make_repo(tmp_path)), TODAY) == [0] * 84


def test_a_repository_git_refuses_raises_with_what_git_said(tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "2026-10-10")
    for entry in (repo / ".git" / "objects").iterdir():
        shutil.rmtree(entry)
    with pytest.raises(subprocess.CalledProcessError) as refused:
        commit_days(str(repo), TODAY)
    assert refused.value.stderr.strip() == "fatal: bad object refs/heads/main"
