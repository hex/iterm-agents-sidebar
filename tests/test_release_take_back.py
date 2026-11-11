# ABOUTME: Tests release.sh's take_back, run from the script's own text in a scratch repository whose `github`
# ABOUTME: remote is a bare repository in a temp folder; nothing is pushed anywhere real and nothing is signed.
import os
import re
import subprocess
from pathlib import Path

RELEASE = Path(__file__).resolve().parent.parent / "release.sh"
VERSION = "2026.11.7"
# Git with no global or system config, so no signing, hooks or templates of the machine reach the scratch repos.
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


def take_back_text():
    """The take_back function exactly as release.sh defines it."""
    found = re.search(r"^take_back\(\) \{\n.*?^\}\n", RELEASE.read_text(), re.S | re.M)
    assert found, "release.sh defines take_back"
    return found.group(0)


def mid_release(tmp_path, remote_url):
    """A repository caught where release.sh pushes: the bump on main, public moved and the tag made."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "work")
    git(repo, "branch", "public")
    before = {"main": git(repo, "rev-parse", "main"), "public": git(repo, "rev-parse", "public")}
    git(repo, "commit", "-q", "--allow-empty", "-m", f"Release {VERSION}")
    commit = git(repo, "commit-tree", "-m", f"{VERSION}: summary", "-p", "public",
                 git(repo, "rev-parse", "public^{tree}"))
    git(repo, "branch", "-f", "public", commit)
    git(repo, "tag", "-a", f"v{VERSION}", "-m", "summary", commit)
    git(repo, "remote", "add", "github", str(remote_url))
    return repo, before


def bare(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    return remote


def exit_mid_push(repo, before, pushing=1):
    """Exit as release.sh does when its push exits non-zero: the EXIT trap runs take_back."""
    script = (f"set -euo pipefail\nversion={VERSION}\nremote=github\npublic_before={before['public']}\n"
              f"bumped=1; published=0; check=\"\"; pushing={pushing}\n"
              + take_back_text() + "trap take_back EXIT\nexit 1\n")
    return subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True, env=ENV)


def state(repo):
    return {"main": git(repo, "rev-parse", "main"), "public": git(repo, "rev-parse", "public"),
            "tag": git(repo, "tag", "-l", f"v{VERSION}")}


def test_a_push_that_landed_though_it_reported_failure_is_not_taken_back(tmp_path):
    repo, before = mid_release(tmp_path, bare(tmp_path))
    git(repo, "push", "-q", "--atomic", "github", "public:main", f"v{VERSION}")
    kept = state(repo)
    ran = exit_mid_push(repo, before)
    assert ran.returncode == 1
    assert state(repo) == kept
    assert ran.stderr == (f"v{VERSION} is on github although the push reported a failure: kept the tag, "
                          f"public and the bump; make the release page by hand\n")


def test_a_push_that_did_not_land_is_taken_back(tmp_path):
    repo, before = mid_release(tmp_path, bare(tmp_path))
    ran = exit_mid_push(repo, before)
    assert (ran.returncode, ran.stderr) == (1, "")
    assert state(repo) == {"main": before["main"], "public": before["public"], "tag": ""}


def test_a_remote_that_cannot_be_asked_keeps_everything(tmp_path):
    repo, before = mid_release(tmp_path, tmp_path / "missing.git")
    kept = state(repo)
    ran = exit_mid_push(repo, before)
    assert ran.returncode == 1
    assert state(repo) == kept
    assert ran.stderr.splitlines()[-1] == (f"could not check github for v{VERSION} (git ls-remote exit 128): kept the "
                                           f"tag, public and the bump; check github before re-running")


def test_a_failure_before_the_push_is_taken_back_without_asking_the_remote(tmp_path):
    repo, before = mid_release(tmp_path, tmp_path / "missing.git")
    ran = exit_mid_push(repo, before, pushing=0)
    assert (ran.returncode, ran.stderr) == (1, "")
    assert state(repo) == {"main": before["main"], "public": before["public"], "tag": ""}


def test_the_scripts_own_push_step_asks_the_remote_when_the_push_fails(tmp_path):
    repo, before = mid_release(tmp_path, tmp_path / "missing.git")
    kept = state(repo)
    push_step = re.search(r"^git tag -a .*?\n(.*?^published=1\n)", RELEASE.read_text(), re.S | re.M).group(1)
    script = (f"set -euo pipefail\nversion={VERSION}\nremote=github\npublic_before={before['public']}\n"
              f"bumped=1; published=0; check=\"\"; pushing=0\n" + take_back_text() + "trap take_back EXIT\n" + push_step)
    ran = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True, env=ENV)
    assert ran.returncode != 0
    assert state(repo) == kept
    assert ran.stderr.splitlines()[-1] == (f"could not check github for v{VERSION} (git ls-remote exit 128): kept the "
                                           f"tag, public and the bump; check github before re-running")
