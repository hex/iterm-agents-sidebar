#!/usr/bin/env python3.10
# ABOUTME: Tells the panel when the mirror carries a newer release than the checkout it
# ABOUTME: runs from, and takes that release: a fast-forward pull, then install.sh again.
"""Releases are tags on the public mirror, `vYYYY.M.BUILD`. One listing a
day is enough: nothing here waits on it, and a release that lands between
two checks is offered at the next one.
"""
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

#: Where releases are published; the same source get.sh clones from.
MIRROR = "https://github.com/hex/iterm-agents-sidebar.git"
#: The tag shape release.sh writes; anything else on the mirror is not a release.
#: The month lost its leading zero at 2026.9.43; earlier tags carry it.
RELEASE_TAG = re.compile(r"^refs/tags/v(\d{4})\.(\d{1,2})\.(\d+)$")


def newest_release(listing):
    """-> the highest release in a `git ls-remote --tags` listing, or None.

    BUILD counts up without padding, so `2026.9.8` sorts before `2026.9.19`
    only when the parts are compared as numbers.
    """
    found = []
    for line in listing.splitlines():
        _, _, ref = line.partition("\t")
        match = RELEASE_TAG.match(ref)
        if match:
            found.append(tuple(int(part) for part in match.groups()))
    if not found:
        return None
    year, month, build = max(found)
    return f"{year}.{month}.{build}"


def _parts(release):
    return tuple(int(part) for part in release.split("."))


def offer(newest, installed):
    """-> the mirror release to offer, or None when there is nothing newer.

    A checkout without a VERSION is a working copy, not an install; the
    drawer already says so, and an offer on top of that would be noise.
    """
    if newest is None or installed is None:
        return None
    return newest if _parts(newest) > _parts(installed) else None


#: A listing is one round trip; a dead network must not hold a thread for long.
CHECK_TIMEOUT = 20


def check(git="git", mirror=MIRROR, timeout=CHECK_TIMEOUT):
    """-> the newest release on the mirror, or None when the mirror could not
    say: no network, a hung connection, a listing with no releases. The
    absence is the answer; nothing here retries.
    """
    try:
        listed = subprocess.run(
            [git, "ls-remote", "--tags", "--refs", mirror],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return None
    if listed.returncode != 0:
        return None
    return newest_release(listed.stdout)


def origin(here, git="git"):
    """-> the URL the checkout fetches releases from, or None when it has no
    origin: a working copy that updates some other way."""
    try:
        told = subprocess.run([git, "-C", str(here), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    return told.stdout.strip() or None if told.returncode == 0 else None


#: A GitHub remote in either form git writes it, an https URL (perhaps with
#: credentials in it) or ssh's `git@github.com:`, down to owner and repo.
GITHUB_REMOTE = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def repository_page(remote):
    """-> the GitHub page of the repository `remote` names, or None for a
    remote that is not on GitHub. A checkout with no origin, such as one whose
    remote has another name, updates from the mirror, so it leads there.

    Built from owner and repo alone: anything else in the remote, a token
    among it, never reaches the page.
    """
    found = GITHUB_REMOTE.match(remote or MIRROR)
    return f"https://github.com/{found[1]}/{found[2]}" if found else None


def releases_page(remote):
    """-> the GitHub page listing the releases `remote` publishes, or None."""
    repository = repository_page(remote)
    return f"{repository}/releases" if repository else None


#: The pages the panel may ask the daemon to open, by name.
GITHUB_PAGES = {"repository": repository_page, "releases": releases_page}
#: `open` hands the URL to the default browser and returns.
OPEN_TIMEOUT = 10


def open_github(remote, page, run=subprocess.run):
    """Open `remote`'s GitHub page named `page`, one of GITHUB_PAGES, in the
    default browser. The panel names the page and the daemon builds its URL,
    so the URL is never the page's to choose."""
    url = GITHUB_PAGES[page](remote)
    if url is None:
        raise Refused(f"this checkout's origin is not on GitHub, so it has no {page} page")
    try:
        run(["open", url], check=True, timeout=OPEN_TIMEOUT, capture_output=True, text=True)
    except subprocess.CalledProcessError as failed:
        raise Refused(f"could not open {url}: {failed.stderr.strip()}") from failed
    except (subprocess.TimeoutExpired, OSError) as failed:
        raise Refused(f"could not open {url}: {failed}") from failed


#: install.sh writes a handful of files; the fetch is the only network step.
TAKE_TIMEOUT = 120
#: The public keys a release may be signed with, and those no longer trusted,
#: in the formats git's gpg.ssh.allowedSignersFile and revocationFile take.
SIGNERS, REVOKED = "release-signers", "release-revoked"


#: The first git that verifies SSH signatures (gpg.format=ssh).
SSH_SIGNING_GIT = (2, 34)
#: Held for the whole of an update; the server answers each request on its
#: own thread, so two clicks would otherwise run two.
RUNNING = threading.Lock()


class Refused(Exception):
    """A step of an update said no; its text is what the panel shows."""


def _git(git, here, *args, check=True):
    """-> git's stdout; a nonzero exit raises Refused with git's own words."""
    try:
        ran = subprocess.run([git, "-C", str(here), *args], capture_output=True, text=True,
                             timeout=TAKE_TIMEOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise Refused(f"git {args[0]} gave up after {TAKE_TIMEOUT} s")
    if check and ran.returncode != 0:
        raise Refused(ran.stdout + ran.stderr)
    return ran


def _verify(git, here, commit, scratch, judge=None):
    """Refuse unless `commit` carries an SSH signature by a key its parent
    lists and has not revoked; `judge` names another commit whose lists
    decide instead.

    The lists are the parent's, never the working tree's and never the
    commit's own: a commit cannot vouch for itself, and a key rotation, being
    a signed commit, takes effect for the commits after it.
    """
    # verify-commit judges a GPG signature by the user's own keyring, which a
    # stranger's key can be in; only the release list may decide.
    body = _git(git, here, "cat-file", "commit", commit).stdout
    if "\ngpgsig -----BEGIN SSH SIGNATURE-----" not in body.partition("\n\n")[0]:
        raise Refused(f"refused: {commit[:12]} carries no SSH signature\n")
    judge, named = (judge, judge[:12]) if judge else (f"{commit}^", f"{commit[:12]}^")
    for name in (SIGNERS, REVOKED):
        listed = _git(git, here, "show", f"{judge}:{name}", check=False)
        if listed.returncode != 0:
            raise Refused(f"refused: {named} has no {name}\n")
        (scratch / name).write_text(listed.stdout)
    # GPG and X.509 verifiers are switched off: git judges the first signature
    # header, and a GPG one ahead of an SSH one would be judged by the user's
    # keyring, which the header check above cannot see past.
    signed = _git(
        git, here, "-c", "gpg.program=/usr/bin/false", "-c", "gpg.x509.program=/usr/bin/false", "-c", f"gpg.ssh.allowedSignersFile={scratch / SIGNERS}",
        "-c", f"gpg.ssh.revocationFile={scratch / REVOKED}",
        "verify-commit", commit, check=False)
    if signed.returncode != 0:
        raise Refused(f"refused: {commit[:12]} is not signed with a release key\n")


def _git_version(git):
    """-> git's version as a tuple of ints, e.g. (2, 54, 0)."""
    told = subprocess.run([git, "version"], capture_output=True, text=True, timeout=TAKE_TIMEOUT)
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", told.stdout)
    if told.returncode != 0 or not match:
        raise Refused(told.stdout + told.stderr)
    return tuple(int(part or 0) for part in match.groups()), match.group(0)


def _fast_forward(here, offered, git):
    """Every check before the checkout moves, then the move -> the commit it
    moved from. Raises Refused at the first no."""
    if not offered:
        raise Refused("refused: no release is on offer\n")
    version, named = _git_version(git)
    if version[:2] < SSH_SIGNING_GIT:
        raise Refused(f"refused: git {named} is too old to check release signatures; "
                      f"{'.'.join(map(str, SSH_SIGNING_GIT))} or newer is needed\n")
    # Edited code in the checkout would run, unsigned, once it is merged over.
    if _git(git, here, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        raise Refused("refused: local changes to tracked files; commit or discard them first\n")
    # origin's own head, the remote releases are listed from, whatever the
    # branch tracks; resolved once, since another fetch could move a ref
    # between these checks and the merge, onto a commit none of them saw.
    _git(git, here, "fetch", "-q", "origin", "HEAD")
    target = _git(git, here, "rev-parse", "--verify", "FETCH_HEAD^{commit}").stdout.strip()
    installed_commit = _git(git, here, "rev-parse", "--verify", "HEAD").stdout.strip()
    continues = _git(git, here, "merge-base", "--is-ancestor", "HEAD", target, check=False).returncode == 0
    with tempfile.TemporaryDirectory() as scratch:
        if continues:
            _verify_line(git, here, target, Path(scratch))
        else:
            _verify_rewrite(git, here, installed_commit, target, Path(scratch))
    # What is taken is the signed VERSION, never the tag that offered it:
    # tags are unsigned, and one must not be able to hold a release back.
    mirrored = _git(git, here, "show", f"{target}:VERSION").stdout.strip()
    installed = _git(git, here, "show", "HEAD:VERSION").stdout.strip()
    if _parts(mirrored) <= _parts(installed):
        raise Refused(f"refused: {mirrored} is not newer than the installed {installed}\n")
    if continues:
        _git(git, here, "merge", "-q", "--ff-only", target)
    else:
        _git(git, here, "reset", "-q", "--hard", target)
    return installed_commit


def _verify_rewrite(git, here, installed_commit, target, scratch):
    """Refuse unless `target`, the head of a rewritten history that continues
    nothing here, may replace the installed release.

    No chain of parents leads back to the installed release, so it vouches
    for the head itself, as a parent vouches for its child: the head must be
    signed by a key the installed release lists and has not revoked. Only a
    signed release vouches: commits made in the checkout also continue
    nothing on the mirror, and a reset would drop them.
    """
    # Judged as it was taken, by its parent's lists; a release with no
    # parent, by its own.
    has_parent = _git(git, here, "rev-parse", "-q", "--verify", f"{installed_commit}^", check=False).returncode == 0
    try:
        _verify(git, here, installed_commit, scratch, judge=None if has_parent else installed_commit)
    except Refused:
        raise Refused("refused: the mirror's history does not continue this checkout's, "
                      "which is not a signed release\n") from None
    _verify(git, here, target, scratch, judge=installed_commit)
    # The head's own lists judge every release after it: one that leaves out
    # a key the installed release revoked would trust that key again.
    if not _revoked(git, here, installed_commit) <= _revoked(git, here, target):
        raise Refused(f"refused: {target[:12]} takes back a key the installed release revoked\n")
    # A fast-forward stops at an untracked file it would replace; the reset
    # that takes a rewrite would replace it without a word.
    added = set(_git(git, here, "diff", "--name-only", "-z", "--diff-filter=A",
                     installed_commit, target).stdout.split("\0")) - {""}
    untracked = set(_git(git, here, "ls-files", "--others", "-z").stdout.split("\0")) - {""}
    for path in sorted(added & untracked):
        raise Refused(f"refused: the release would overwrite untracked {path}\n")


def _revoked(git, here, commit):
    """-> the keys `commit` lists in release-revoked, one entry per line."""
    listed = _git(git, here, "show", f"{commit}:{REVOKED}", check=False).stdout
    return {line.strip() for line in listed.splitlines() if line.strip()}


def _verify_line(git, here, target, scratch):
    """Refuse unless the commits from HEAD to `target` are a straight line,
    each signed by a key its parent lists."""
    commits = _git(git, here, "rev-list", "--reverse", f"HEAD..{target}").stdout.split()
    if not commits:
        raise Refused("refused: the mirror has nothing newer\n")
    # A merge is judged by its first parent's lists, which can be older than
    # the installed release's; with none, every commit's parent is the one
    # before it, back to the installed HEAD.
    for merge in _git(git, here, "rev-list", "--min-parents=2", f"HEAD..{target}").stdout.split():
        raise Refused(f"refused: {merge[:12]} is a merge; releases are a straight line\n")
    for commit in commits:
        _verify(git, here, commit, scratch)


def _install(here):
    """Run the checkout's install.sh -> None, or what to show when it failed."""
    try:
        ran = subprocess.run([str(here / "install.sh")], capture_output=True, text=True,
                             timeout=TAKE_TIMEOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return f"install.sh gave up after {TAKE_TIMEOUT} s"
    except OSError as failed:
        return f"install.sh could not run: {failed}\n"
    if ran.returncode == 0:
        return None
    # An empty text would read as success to the caller, and the daemon would
    # restart onto a half-installed release.
    return ran.stdout + ran.stderr or f"install.sh exited with status {ran.returncode} and printed nothing\n"


def take(here, offered, git="git"):
    """Bring the checkout the daemon runs from up to the mirror's newest
    signed release and install it -> (ok, text). `offered` is the release the
    panel offered, and only says there is one: what is taken is the signed
    VERSION. The text is what the panel shows when ok is False. Every commit
    taken must carry an SSH signature by a release key its parent lists; a
    refusal moves nothing and installs nothing.
    """
    # Absolute, or "." would make install.sh a bare name exec looks up on PATH.
    here = Path(here).resolve()
    if not RUNNING.acquire(blocking=False):
        return (False, "an update is already running\n")
    try:
        try:
            installed_commit = _fast_forward(here, offered, git)
        except Refused as refused:
            return (False, str(refused))
        failed = _install(here)
        if failed is not None:
            # Back to the release that runs: its VERSION keeps the offer up,
            # and the next press verifies and installs again. The tree was
            # clean before the merge, so nothing of the user's is lost.
            back = _git(git, here, "reset", "-q", "--hard", installed_commit, check=False)
            if back.returncode != 0:
                failed += f"and the checkout could not go back to {installed_commit[:12]}: {back.stderr}"
            return (False, failed)
        return (True, "")
    finally:
        RUNNING.release()
