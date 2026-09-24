"""The release check and the update itself.

Failure modes, written before the code: a peeled `^{}` ref line; a tag that
is not a release; `v2026.09.8` sorting after `v2026.09.19` as text; a mirror
release equal to the installed one; an installed checkout with no VERSION;
a month written without its leading zero (`v2026.9.43`, from 2026.09.43 on)
not read as a release, or read as older than a padded one;
git exiting nonzero, timing out, or printing nothing; an update script that
fails, whose text the panel must get and after which nothing restarts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import update

LISTING = (
    "e6b8beda091171aade1c772759b2a84e2e52a02d\trefs/tags/v2026.09.9\n"
    "973f30746e3d8f512b5217899cf482b23abe1b06\trefs/tags/v2026.09.9^{}\n"
    "55e51d4a7c83c1d3fceaf3657ddb08a9ccf7091c\trefs/tags/v2026.09.19\n"
    "1111111111111111111111111111111111111111\trefs/tags/sketch\n"
)


def test_the_newest_release_is_read_numerically_not_as_text():
    assert update.newest_release(LISTING) == "2026.9.19"


def test_a_month_without_its_leading_zero_is_a_release_and_counts_on_from_the_padded_ones():
    listing = LISTING + "2222222222222222222222222222222222222222\trefs/tags/v2026.9.20\n"
    assert update.newest_release(listing) == "2026.9.20"


def test_a_padded_install_is_offered_the_first_unpadded_release():
    assert update.offer("2026.9.43", "2026.09.42") == "2026.9.43"
    assert update.offer("2026.9.42", "2026.09.42") is None


def test_a_mirror_without_release_tags_offers_nothing():
    assert update.newest_release("111\trefs/tags/sketch\n222\trefs/heads/main\n") is None


def test_the_installed_release_is_not_offered():
    assert update.offer("2026.09.19", "2026.09.19") is None


def test_a_newer_mirror_release_is_offered_without_the_v():
    assert update.offer("2026.09.20", "2026.09.19") == "2026.09.20"


def test_an_older_mirror_release_is_not_offered():
    assert update.offer("2026.09.9", "2026.09.19") is None


def test_an_unreleased_checkout_is_offered_nothing():
    assert update.offer("2026.09.20", None) is None


def fake_git(tmp_path, body):
    git = tmp_path / "git"
    git.write_text("#!/bin/sh\n" + body)
    git.chmod(0o755)
    return str(git)


def test_the_check_reads_the_newest_tag_off_the_mirror(tmp_path):
    git = fake_git(tmp_path, f"printf '%s' '{LISTING}'\n".replace("\n\n", "\\n"))
    assert update.check(git=git) == "2026.9.19"


def test_a_failed_listing_yields_nothing(tmp_path):
    git = fake_git(tmp_path, "echo 'fatal: unable to access' >&2; exit 128\n")
    assert update.check(git=git) is None


def test_a_hung_listing_yields_nothing(tmp_path):
    git = fake_git(tmp_path, "sleep 5\n")
    assert update.check(git=git, timeout=0.2) is None


def test_an_empty_listing_yields_nothing(tmp_path):
    assert update.check(git=fake_git(tmp_path, "exit 0\n")) is None


def checkout(tmp_path, install_body):
    """A clone of a bare repo, with a commit waiting upstream."""
    import subprocess
    run = lambda *args, cwd: subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                                            env={**__import__("os").environ,
                                                 "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com",
                                                 "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com"})
    origin = tmp_path / "origin.git"
    run("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / "seed"
    run("git", "clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / "install.sh").write_text("#!/bin/sh\n" + install_body)
    (seed / "install.sh").chmod(0o755)
    run("git", "add", "install.sh", cwd=seed)
    run("git", "commit", "-qm", "one", cwd=seed)
    run("git", "push", "-q", "origin", "main", cwd=seed)
    here = tmp_path / "here"
    run("git", "clone", "-q", str(origin), str(here), cwd=tmp_path)
    (seed / "VERSION").write_text("2026.09.20\n")
    run("git", "add", "VERSION", cwd=seed)
    run("git", "commit", "-qm", "two", cwd=seed)
    run("git", "push", "-q", "origin", "main", cwd=seed)
    return here


def test_taking_a_release_pulls_and_reinstalls(tmp_path):
    here = checkout(tmp_path, "echo installed > \"$(dirname \"$0\")/marker\"\n")
    assert update.take(here) == (True, "")
    assert (here / "VERSION").read_text() == "2026.09.20\n"
    assert (here / "marker").read_text() == "installed\n"


def test_a_pull_that_cannot_fast_forward_reports_git_and_installs_nothing(tmp_path):
    here = checkout(tmp_path, "echo installed > \"$(dirname \"$0\")/marker\"\n")
    (here / "VERSION").write_text("local\n")
    ok, text = update.take(here)
    assert ok is False
    assert "VERSION" in text and "overwritten" in text
    assert not (here / "marker").exists()


def test_a_failing_install_reports_its_output(tmp_path):
    here = checkout(tmp_path, "echo 'error: iterm2env-3.10 not found' >&2; exit 1\n")
    assert update.take(here) == (False, "error: iterm2env-3.10 not found\n")
