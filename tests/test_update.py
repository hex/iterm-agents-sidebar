"""The release check and the update itself.

Failure modes, written before the code: a peeled `^{}` ref line; a tag that
is not a release; `v2026.09.8` sorting after `v2026.09.19` as text; a mirror
release equal to the installed one; an installed checkout with no VERSION;
a month written without its leading zero (`v2026.9.43`, from 2026.09.43 on)
not read as a release, or read as older than a padded one;
git exiting nonzero, timing out, or printing nothing; an update script that
fails, whose text the panel must get and after which nothing restarts.

Taking a release runs code from the mirror, so it takes only commits signed
by a release key the installed checkout already trusts. Failure modes: an
unsigned commit; one signed by a key not listed, or by a listed key that has
since been revoked; a signature that is not SSH (a GPG signature would be
judged by the user's own keyring instead); a signers file read from the
working tree or from the commit it judges, rather than from that commit's
parent; an installed checkout with no signers file falling back to an
unsigned pull; a mirror head whose VERSION is not the release offered, or
is not newer than the installed one (an old signed release re-offered under
a new name); history that does not fast-forward, unless it is a rewritten
history whose head is signed by a key the installed release lists and has
not revoked (never by its own lists), that revokes every key the installed
release revoked, overwrites no untracked file, and replaces a checkout that
is itself a signed release, never one with commits of its own; an install
script that fails without printing anything; a checkout with local edits,
whose code would run unsigned; a git too old for SSH signatures failing with
git's own opaque error; two updates at once; a fetch that brings nothing new.
Any refusal leaves the checkout where it was and installs nothing.
"""
import os
import subprocess
import threading

import pytest
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


IDENTITY = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com"}


def run(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **IDENTITY}).stdout.strip()


def key(tmp_path, name):
    """A throwaway ed25519 release key -> its private key path."""
    path = tmp_path / name
    run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path), cwd=tmp_path)
    return path


def signer_line(path):
    return f'release namespaces="git" {Path(str(path) + ".pub").read_text().strip()}\n'


MARKER = "echo installed > \"$(dirname \"$0\")/marker\"\n"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """Built once: every git exec costs a second or two on a machine whose
    endpoint agent inspects each one, and each test copies this instead."""
    root = tmp_path_factory.mktemp("template")
    key(root, "release")
    key(root, "stranger")
    run("git", "init", "-q", "--bare", "-b", "main", str(root / "origin.git"), cwd=root)
    run("git", "clone", "-q", "origin.git", "seed", cwd=root)
    run("git", "clone", "-q", "origin.git", "here", cwd=root)
    return root


class Mirror:
    """A bare origin, a seed clone that publishes to it, and the installed
    clone `here`, which already carries one signed release."""

    def __init__(self, tmp_path, template, install_body=MARKER):
        import shutil
        shutil.copytree(template, tmp_path, dirs_exist_ok=True)
        self.tmp = tmp_path
        self.release_key = tmp_path / "release"
        self.origin = tmp_path / "origin.git"
        self.seed, self.here = tmp_path / "seed", tmp_path / "here"
        # A clone records its origin's absolute path: point the copies at their own.
        for clone in (self.seed, self.here):
            run("git", "remote", "set-url", "origin", str(self.origin), cwd=clone)
        self.write("install.sh", "#!/bin/sh\n" + install_body, mode=0o755)
        self.write("release-signers", signer_line(self.release_key))
        self.write("release-revoked", "")
        self.write("VERSION", "2026.9.19\n")
        self.publish()
        run("git", "pull", "-q", "origin", "main", cwd=self.here)
        run("git", "branch", "-q", "--set-upstream-to=origin/main", cwd=self.here)

    def write(self, name, text, mode=None):
        (self.seed / name).write_text(text)
        if mode:
            (self.seed / name).chmod(mode)
        run("git", "add", name, cwd=self.seed)

    def rewrite(self, version, signed_with="release"):
        """Replace the mirror's history with a new root holding the staged
        tree at `version`, as a history rewrite and force-push would."""
        self.write("VERSION", version + "\n")
        tree = run("git", "write-tree", cwd=self.seed)
        sign = [] if signed_with is None else [
            "-c", "gpg.format=ssh", "-c", f"user.signingkey={self.tmp / signed_with}"]
        root = run("git", *sign, "commit-tree", tree, *(["-S"] if signed_with else []),
                   "-m", "rewritten", cwd=self.seed)
        run("git", "reset", "-q", root, cwd=self.seed)
        run("git", "push", "-q", "-f", "origin", "HEAD:main", cwd=self.seed)
        return root

    def publish(self, version=None, signed_with="release", message="release"):
        """Commit what is staged, signed as release.sh signs, and push it."""
        if version:
            self.write("VERSION", version + "\n")
        tree = run("git", "write-tree", cwd=self.seed)
        parents = []
        head = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=self.seed,
                              capture_output=True, text=True).stdout.strip()
        if head:
            parents = ["-p", head]
        sign = [] if signed_with is None else [
            "-c", "gpg.format=ssh", "-c", f"user.signingkey={self.tmp / signed_with}"]
        commit = run("git", *sign, "commit-tree", tree, *parents,
                     *(["-S"] if signed_with else []), "-m", message, cwd=self.seed)
        run("git", "reset", "-q", commit, cwd=self.seed)
        run("git", "push", "-q", "origin", "HEAD:main", cwd=self.seed)
        return commit


def checkout(tmp_path, template, install_body):
    """An install one signed release behind the mirror."""
    mirror = Mirror(tmp_path, template, install_body)
    mirror.publish("2026.9.20")
    return mirror.here


def test_taking_a_release_pulls_and_reinstalls(tmp_path, template):
    here = checkout(tmp_path, template, MARKER)
    assert update.take(here, "2026.9.20") == (True, "")
    assert (here / "VERSION").read_text() == "2026.9.20\n"
    assert (here / "marker").read_text() == "installed\n"


def test_a_failing_install_reports_its_output_and_can_be_retried(tmp_path, template):
    """The checkout goes back to the release that runs, so the offer stays
    and the next press verifies and installs again."""
    here = checkout(tmp_path, template, "echo 'error: iterm2env-3.10 not found' >&2; exit 1\n")
    before = head(here)
    assert update.take(here, "2026.9.20") == (False, "error: iterm2env-3.10 not found\n")
    assert head(here) == before
    assert (here / "VERSION").read_text() == "2026.9.19\n"
    assert update.take(here, "2026.9.20") == (False, "error: iterm2env-3.10 not found\n")


def test_an_install_that_fails_silently_is_still_a_failure(tmp_path, template):
    here = checkout(tmp_path, template, "exit 3\n")
    before = head(here)
    assert update.take(here, "2026.9.20") == (False, "install.sh exited with status 3 and printed nothing\n")
    assert head(here) == before


def head(here):
    return run("git", "rev-parse", "HEAD", cwd=here)


def assert_refused(mirror, offered, text):
    """Refused with exactly `text`, the checkout where it was, nothing installed."""
    before = head(mirror.here)
    assert update.take(mirror.here, offered) == (False, text)
    assert head(mirror.here) == before
    assert not (mirror.here / "marker").exists()


def test_an_unsigned_release_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    commit = mirror.publish("2026.9.20", signed_with=None)
    assert_refused(mirror, "2026.9.20", f"refused: {commit[:12]} carries no SSH signature\n")


def test_a_release_signed_by_an_unlisted_key_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    commit = mirror.publish("2026.9.20", signed_with="stranger")
    assert_refused(mirror, "2026.9.20", f"refused: {commit[:12]} is not signed with a release key\n")


def test_a_commit_cannot_list_the_key_it_is_signed_with(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.write("release-signers", signer_line(tmp_path / "stranger"))
    commit = mirror.publish("2026.9.20", signed_with="stranger")
    assert_refused(mirror, "2026.9.20", f"refused: {commit[:12]} is not signed with a release key\n")


def test_a_key_listed_by_an_earlier_signed_release_signs_the_next(tmp_path, template):
    """A rotation is a signed commit; an install that skipped it still takes
    what comes after, judging each commit by its parent's list."""
    mirror = Mirror(tmp_path, template)
    mirror.write("release-signers", signer_line(tmp_path / "stranger"))
    mirror.publish("2026.9.20")
    mirror.publish("2026.9.21", signed_with="stranger")
    assert update.take(mirror.here, "2026.9.21") == (True, "")
    assert (mirror.here / "marker").read_text() == "installed\n"


def test_a_revoked_key_signs_nothing_after_its_revocation(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.write("release-revoked", Path(str(tmp_path / "release") + ".pub").read_text())
    mirror.write("release-signers", signer_line(tmp_path / "release") + signer_line(tmp_path / "stranger"))
    mirror.publish("2026.9.20")
    commit = mirror.publish("2026.9.21")
    assert_refused(mirror, "2026.9.21", f"refused: {commit[:12]} is not signed with a release key\n")


def test_an_install_without_a_signers_file_takes_nothing(tmp_path, template):
    """No fallback to an unsigned pull: that would be the bypass."""
    mirror = Mirror(tmp_path, template)
    run("git", "rm", "-q", "release-signers", cwd=mirror.seed)
    mirror.publish("2026.9.20")
    run("git", "pull", "-q", "origin", "main", cwd=mirror.here)
    commit = mirror.publish("2026.9.21")
    assert_refused(mirror, "2026.9.21", f"refused: {commit[:12]}^ has no release-signers\n")


def test_a_gpg_signature_is_refused_even_when_the_keyring_trusts_it(tmp_path, template, monkeypatch, request):
    """verify-commit judges a GPG signature by the user's own keyring; only
    the release list may decide."""
    if not __import__("shutil").which("gpg"):
        pytest.skip("gpg is not installed")
    import tempfile
    # gpg-agent's socket lives in GNUPGHOME, and a pytest path is past its
    # length limit; the agent it starts is stopped again at the end.
    home = tempfile.mkdtemp(prefix="gpg", dir="/tmp")
    monkeypatch.setenv("GNUPGHOME", home)
    request.addfinalizer(lambda: (subprocess.run(["gpgconf", "--kill", "gpg-agent"], env={**os.environ, "GNUPGHOME": home}),
                                  __import__("shutil").rmtree(home, ignore_errors=True)))
    # Never the user's own keyring: gpg is told its home on every call.
    run("gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
        "--quick-gen-key", "Mallory <m@example.com>", "ed25519", "sign", "never", cwd=tmp_path)
    fingerprint = run("gpg", "--homedir", home, "--list-secret-keys", "--with-colons", cwd=tmp_path)
    fingerprint = [line.split(":")[9] for line in fingerprint.splitlines() if line.startswith("fpr")][0]
    mirror = Mirror(tmp_path, template)
    mirror.write("VERSION", "2026.9.20\n")
    tree = run("git", "write-tree", cwd=mirror.seed)
    commit = run("git", "-c", f"user.signingkey={fingerprint}", "commit-tree", tree,
                 "-p", head(mirror.seed), "-S", "-m", "gpg", cwd=mirror.seed)
    run("git", "push", "-q", "origin", f"{commit}:refs/heads/main", cwd=mirror.seed)
    # The keyring accepts it: without the pin this commit would be taken.
    assert subprocess.run(["git", "verify-commit", commit], cwd=mirror.seed,
                          capture_output=True).returncode == 0
    assert_refused(mirror, "2026.9.20", f"refused: {commit[:12]} carries no SSH signature\n")
    # The same GPG-signed commit with an SSH-looking signature header after
    # its own: git verifies the first, so the keyring would still decide.
    header, _, message = run("git", "cat-file", "commit", commit, cwd=mirror.seed).partition("\n\n")
    forged_text = (header + "\ngpgsig -----BEGIN SSH SIGNATURE-----\n U1NIU0lH\n -----END SSH SIGNATURE-----"
                   + "\n\n" + message + "\n")
    forged = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=mirror.seed,
                            input=forged_text, capture_output=True, text=True, check=True).stdout.strip()
    assert subprocess.run(["git", "verify-commit", forged], cwd=mirror.seed,
                          capture_output=True).returncode == 0
    run("git", "push", "-q", "-f", "origin", f"{forged}:refs/heads/main", cwd=mirror.seed)
    assert_refused(mirror, "2026.9.20", f"refused: {forged[:12]} is not signed with a release key\n")


def test_a_bogus_release_tag_does_not_block_the_signed_release(tmp_path, template):
    """Tags are unsigned: anyone who can push one decides what is offered,
    but what is taken is the signed VERSION, so a tag cannot hold it back."""
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    assert update.take(mirror.here, "2026.12.1") == (True, "")
    assert (mirror.here / "VERSION").read_text() == "2026.9.20\n"


def test_an_old_signed_release_offered_again_is_refused(tmp_path, template):
    """A signed commit that only winds VERSION back, offered under its own
    name, is still not newer than what is installed."""
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.18")
    assert_refused(mirror, "2026.9.18", "refused: 2026.9.18 is not newer than the installed 2026.9.19\n")


def test_a_checkout_with_its_own_commits_is_not_reset_onto_a_rewritten_history(tmp_path, template):
    """Commits made in the checkout also continue nothing on the mirror; a
    reset would drop them, so only a signed release is moved."""
    mirror = Mirror(tmp_path, template)
    (mirror.here / "mine.py").write_text("mine\n")
    run("git", "add", "mine.py", cwd=mirror.here)
    run("git", "commit", "-q", "-m", "mine", cwd=mirror.here)
    mirror.rewrite("2026.9.20")
    assert_refused(mirror, "2026.9.20",
                   "refused: the mirror's history does not continue this checkout's, "
                   "which is not a signed release\n")
    assert (mirror.here / "mine.py").read_text() == "mine\n"


def test_a_rewritten_history_that_is_not_newer_is_refused(tmp_path, template):
    """A rewrite replaying the installed release is not a newer one."""
    mirror = Mirror(tmp_path, template)
    mirror.rewrite("2026.9.19")
    assert_refused(mirror, "2026.9.19", "refused: 2026.9.19 is not newer than the installed 2026.9.19\n")


def test_an_unsigned_rewritten_history_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    root = mirror.rewrite("2026.9.20", signed_with=None)
    assert_refused(mirror, "2026.9.20", f"refused: {root[:12]} carries no SSH signature\n")


def test_a_rewritten_history_signed_by_an_unlisted_key_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    root = mirror.rewrite("2026.9.20", signed_with="stranger")
    assert_refused(mirror, "2026.9.20", f"refused: {root[:12]} is not signed with a release key\n")


def test_a_rewritten_history_cannot_list_the_key_it_is_signed_with(tmp_path, template):
    """With no parent to judge it, the installed release's lists decide,
    never the rewritten head's own."""
    mirror = Mirror(tmp_path, template)
    mirror.write("release-signers", signer_line(tmp_path / "stranger"))
    root = mirror.rewrite("2026.9.20", signed_with="stranger")
    assert_refused(mirror, "2026.9.20", f"refused: {root[:12]} is not signed with a release key\n")


def test_a_rewritten_history_signed_by_a_key_the_install_revoked_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.write("release-revoked", Path(str(tmp_path / "release") + ".pub").read_text())
    mirror.write("release-signers", signer_line(tmp_path / "release") + signer_line(tmp_path / "stranger"))
    mirror.publish("2026.9.20", signed_with="release")
    run("git", "pull", "-q", "origin", "main", cwd=mirror.here)
    root = mirror.rewrite("2026.9.21", signed_with="release")
    assert_refused(mirror, "2026.9.21", f"refused: {root[:12]} is not signed with a release key\n")


def test_a_rewritten_history_cannot_take_back_a_revocation(tmp_path, template):
    """A signed head from a divergent line that never revoked a key would,
    once taken, let that key sign the releases after it."""
    mirror = Mirror(tmp_path, template)
    mirror.write("release-revoked", Path(str(tmp_path / "stranger") + ".pub").read_text())
    mirror.publish("2026.9.20")
    run("git", "pull", "-q", "origin", "main", cwd=mirror.here)
    mirror.write("release-revoked", "")
    root = mirror.rewrite("2026.9.21")
    assert_refused(mirror, "2026.9.21", f"refused: {root[:12]} takes back a key the installed release revoked\n")


def test_a_rewrite_does_not_overwrite_an_untracked_file(tmp_path, template):
    """A fast-forward stops at an untracked file the release would replace;
    the reset that follows a rewrite must stop there too."""
    mirror = Mirror(tmp_path, template)
    (mirror.here / "notes.txt").write_text("mine\n")
    mirror.write("notes.txt", "the release's\n")
    mirror.rewrite("2026.9.20")
    assert_refused(mirror, "2026.9.20", "refused: the release would overwrite untracked notes.txt\n")
    assert (mirror.here / "notes.txt").read_text() == "mine\n"


def test_a_failing_install_after_a_rewrite_goes_back_to_the_installed_release(tmp_path, template):
    mirror = Mirror(tmp_path, template, "echo 'error: broken' >&2; exit 1\n")
    before = head(mirror.here)
    mirror.rewrite("2026.9.20")
    assert update.take(mirror.here, "2026.9.20") == (False, "error: broken\n")
    assert head(mirror.here) == before
    assert (mirror.here / "VERSION").read_text() == "2026.9.19\n"


def test_a_rewritten_history_signed_by_a_trusted_key_is_taken(tmp_path, template):
    """The mirror's history was rewritten: its head continues nothing here,
    but it is a newer release signed by a key the installed one lists."""
    mirror = Mirror(tmp_path, template)
    root = mirror.rewrite("2026.9.20")
    assert update.take(mirror.here, "2026.9.20") == (True, "")
    assert head(mirror.here) == root
    assert (mirror.here / "VERSION").read_text() == "2026.9.20\n"
    assert (mirror.here / "marker").read_text() == "installed\n"


def test_local_changes_to_tracked_files_stop_the_update(tmp_path, template):
    """Edited code in the checkout would run unsigned after the merge."""
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    (mirror.here / "install.sh").write_text("#!/bin/sh\necho mine\n")
    assert_refused(mirror, "2026.9.20", "refused: local changes to tracked files; commit or discard them first\n")


def test_untracked_files_do_not_stop_the_update(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    (mirror.here / "notes.txt").write_text("mine\n")
    assert update.take(mirror.here, "2026.9.20") == (True, "")


def test_a_mirror_with_nothing_newer_is_refused(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    assert_refused(mirror, "2026.9.19", "refused: the mirror has nothing newer\n")


def test_a_git_too_old_for_ssh_signatures_says_so(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    git = fake_git(tmp_path, "echo 'git version 2.32.1 (Apple Git-133)'\n")
    before = head(mirror.here)
    assert update.take(mirror.here, "2026.9.20", git=git) == (
        False, "refused: git 2.32.1 is too old to check release signatures; 2.34 or newer is needed\n")
    assert head(mirror.here) == before


def test_a_second_update_while_one_runs_is_turned_away(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    with update.RUNNING:
        assert update.take(mirror.here, "2026.9.20") == (False, "an update is already running\n")
    assert update.take(mirror.here, "2026.9.20") == (True, "")


def test_nothing_on_offer_takes_nothing(tmp_path, template):
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    assert_refused(mirror, None, "refused: no release is on offer\n")


def test_the_mirror_checked_is_the_one_the_checkout_updates_from(tmp_path, template):
    """A fork installed with AGENTS_SIDEBAR_REPO lists its own releases, and
    the fetch goes to the same place."""
    mirror = Mirror(tmp_path, template)
    assert update.origin(mirror.here) == str(mirror.origin)
    run("git", "remote", "remove", "origin", cwd=mirror.here)
    assert update.origin(mirror.here) is None


def test_a_checkout_named_by_a_relative_path_installs_its_own_script(tmp_path, template, monkeypatch):
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    # "." joined to "install.sh" is a bare name, which exec looks up on PATH.
    monkeypatch.chdir(mirror.here)
    assert update.take(".", "2026.9.20") == (True, "")
    assert (mirror.here / "marker").read_text() == "installed\n"


def test_a_merge_cannot_bring_back_a_revoked_key(tmp_path, template):
    """Release B revokes a key its ancestor A trusted. A merge whose first
    parent is A would be judged by A's lists; only a straight line of
    commits from the installed release is taken."""
    mirror = Mirror(tmp_path, template)
    trusted_by_a = head(mirror.seed)
    mirror.write("release-signers", signer_line(tmp_path / "release") + signer_line(tmp_path / "stranger"))
    mirror.publish("2026.9.20")
    mirror.write("release-revoked", Path(str(tmp_path / "release") + ".pub").read_text())
    mirror.publish("2026.9.21", signed_with="stranger")
    run("git", "pull", "-q", "origin", "main", cwd=mirror.here)
    b = head(mirror.seed)
    mirror.write("VERSION", "2026.9.22\n")
    tree = run("git", "write-tree", cwd=mirror.seed)
    merge = run("git", "-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / 'release'}",
                "commit-tree", tree, "-p", trusted_by_a, "-p", b, "-S", "-m", "merge", cwd=mirror.seed)
    run("git", "push", "-q", "origin", f"{merge}:refs/heads/main", cwd=mirror.seed)
    assert_refused(mirror, "2026.9.22", f"refused: {merge[:12]} is a merge; releases are a straight line\n")


def test_the_commit_taken_is_the_commit_verified(tmp_path, template):
    """A fetch by any other process between the checks and the merge must
    not move what is merged onto a commit nobody checked."""
    mirror = Mirror(tmp_path, template)
    mirror.publish("2026.9.20")
    verified = run("git", "rev-parse", "HEAD", cwd=mirror.seed)
    mirror.write("VERSION", "2026.9.21\n")
    unsigned = mirror.publish(signed_with=None, message="unsigned")
    run("git", "push", "-q", "-f", "origin", f"{verified}:refs/heads/main", cwd=mirror.seed)
    # A git that lets the unsigned commit reach the upstream ref just as the
    # merge starts.
    racing = fake_git(tmp_path, f"""case " $* " in
  *" merge "*) /usr/bin/env git -C "{mirror.seed}" push -q -f origin {unsigned}:refs/heads/main
               /usr/bin/env git -C "{mirror.here}" fetch -q origin ;;
esac
exec /usr/bin/env git "$@"
""")
    assert update.take(mirror.here, "2026.9.20", git=racing) == (True, "")
    assert head(mirror.here) == verified


def test_the_release_comes_from_origin_whatever_the_branch_tracks(tmp_path, template):
    """Releases are listed from origin, so they are fetched from there too,
    not from a stale upstream on another remote."""
    mirror = Mirror(tmp_path, template)
    run("git", "clone", "-q", "--bare", str(mirror.origin), str(tmp_path / "other.git"), cwd=tmp_path)
    run("git", "remote", "add", "other", str(tmp_path / "other.git"), cwd=mirror.here)
    run("git", "fetch", "-q", "other", cwd=mirror.here)
    run("git", "branch", "-q", "--set-upstream-to=other/main", cwd=mirror.here)
    mirror.publish("2026.9.20")
    assert update.take(mirror.here, "2026.9.20") == (True, "")
    assert (mirror.here / "VERSION").read_text() == "2026.9.20\n"
