#!/usr/bin/env python3.10
# ABOUTME: Tells the panel when the mirror carries a newer release than the checkout it
# ABOUTME: runs from, and takes that release: a fast-forward pull, then install.sh again.
"""Releases are tags on the public mirror, `vYYYY.MM.BUILD`. One listing a
day is enough: nothing here waits on it, and a release that lands between
two checks is offered at the next one.
"""
import os
import re
import subprocess
from pathlib import Path

#: Where releases are published; the same source get.sh clones from.
MIRROR = "https://github.com/hex/iterm-agents-sidebar.git"
#: The tag shape release.sh writes; anything else on the mirror is not a release.
RELEASE_TAG = re.compile(r"^refs/tags/v(\d{4})\.(\d{2})\.(\d+)$")


def newest_release(listing):
    """-> the highest release in a `git ls-remote --tags` listing, or None.

    BUILD counts up without padding, so `2026.09.8` sorts before `2026.09.19`
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
    return f"{year}.{month:02d}.{build}"


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


#: install.sh writes a handful of files; the pull is the only network step.
TAKE_TIMEOUT = 120


def take(here, git="git"):
    """Bring the checkout the daemon runs from up to the mirror and install it
    -> (ok, text). The text is what the panel shows when ok is False: git's
    refusal or install.sh's complaint, whichever stopped it. A refused pull
    installs nothing.
    """
    here = Path(here)
    for command in ([git, "-C", str(here), "pull", "-q", "--ff-only"],
                    [str(here / "install.sh")]):
        try:
            ran = subprocess.run(command, capture_output=True, text=True, timeout=TAKE_TIMEOUT,
                                 env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        except subprocess.TimeoutExpired:
            return (False, f"{command[0]} gave up after {TAKE_TIMEOUT} s")
        if ran.returncode != 0:
            return (False, ran.stdout + ran.stderr)
    return (True, "")
