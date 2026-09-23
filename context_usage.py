#!/usr/bin/env python3.10
# ABOUTME: What fills a Claude conversation's context, read by running Claude Code's own /context on a fork.
# ABOUTME: The fork writes no transcript and fires no hooks; its category table is parsed into token counts.
"""Claude Code's /context, asked of a conversation without touching it.

The statusline payload carries only the total. The categories exist only in
/context, and a headless fork of the conversation prints them without a
model call.
"""
import json
import re
import subprocess
import threading
from pathlib import Path

#: The binary, not the `claude` on PATH: that is a shell alias for many,
#: and the daemon runs outside any shell.
CLAUDE = Path.home() / ".local" / "bin" / "claude"
#: A fork reads in about 7 s on a long conversation.
TIMEOUT_SECONDS = 30

#: /context's summary line, e.g. `**Tokens:** 122.6k / 1m (12%)`.
TOTAL = re.compile(r"^\*\*Tokens:\*\* (\S+) / (\S+) ", re.MULTILINE)
CATEGORY_HEADING = "### Estimated usage by category"
#: A count as /context prints it: 10, 2.4k, 1m.
COUNT = re.compile(r"(\d+(?:\.\d+)?)([km]?)")
SCALE = {"": 1, "k": 1_000, "m": 1_000_000}


class Refused(Exception):
    """A breakdown that cannot be read; the message says why, for the panel."""


def tokens(text, name):
    match = COUNT.fullmatch(text)
    if match is None:
        raise Refused(f"unreadable token count {text!r} for {name}")
    return round(float(match[1]) * SCALE[match[2]])


def parse(report):
    """/context's markdown -> {"used", "window", "categories": [{"name", "tokens"}]}."""
    total = TOTAL.search(report)
    if total is None:
        raise Refused("no token total in /context's output")
    _, heading, rest = report.partition(CATEGORY_HEADING)
    if not heading:
        raise Refused("no category table in /context's output")
    categories = []
    # The table runs to the first line that is not a row; the header row and
    # its rule are the first two rows.
    for line in rest.strip().splitlines()[2:]:
        if not line.startswith("|"):
            break
        name, count = (cell.strip() for cell in line.strip("|").split("|")[:2])
        categories.append({"name": name, "tokens": tokens(count, name)})
    if not categories:
        raise Refused("no category table in /context's output")
    return {"used": tokens(total[1], "the total"), "window": tokens(total[2], "the window"),
            "categories": categories}


def command(conversation):
    """The fork's argument list. Hooks off: with them on, every SessionStart
    and SessionEnd hook runs for a throwaway session, and the read takes three
    times as long. No persistence: without it, the fork saves a full copy of
    the conversation as a transcript of its own."""
    return ["-p", "--resume", conversation, "--fork-session", "--no-session-persistence",
            "--settings", '{"disableAllHooks":true}', "--output-format", "json", "/context"]


def read(path, conversation, binary=CLAUDE, timeout=TIMEOUT_SECONDS):
    """Run /context on a fork of `conversation` from `path` -> parse()'s breakdown.

    From the conversation's own directory, since the memory files it loads
    depend on it. Raises Refused with the reason when there is no breakdown.
    """
    try:
        done = subprocess.run([str(binary), *command(conversation)], cwd=path, capture_output=True,
                              text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except OSError as error:
        raise Refused(f"cannot run {binary}: {error.strerror}") from error
    except subprocess.TimeoutExpired as error:
        raise Refused(f"/context took longer than {timeout} s") from error
    if done.returncode != 0:
        said = done.stderr.strip().splitlines()
        raise Refused(f"claude exited {done.returncode}: {said[-1] if said else 'no message'}")
    try:
        entries = json.loads(done.stdout)
    except ValueError:
        entries = None
    if not isinstance(entries, list):
        raise Refused("claude printed no JSON list")
    result = next((entry for entry in entries if isinstance(entry, dict) and entry.get("type") == "result"), None)
    if result is None:
        raise Refused("claude printed no result")
    if result.get("is_error") is not False:
        raise Refused(f"/context failed: {result.get('result')}")
    if result.get("local_command") != "context" or not isinstance(result.get("result"), str):
        raise Refused("claude answered something other than /context")
    return parse(result["result"])


class Reads:
    """The reads under way, one at a time per session: a second click while a
    fork runs would start a second fork of the same conversation."""

    def __init__(self, binary=CLAUDE):
        self.binary = binary
        self._lock = threading.Lock()
        self._running = set()

    def run(self, session_id, path, conversation):
        with self._lock:
            if session_id in self._running:
                raise Refused("already reading this session's context")
            self._running.add(session_id)
        try:
            return read(path, conversation, binary=self.binary)
        finally:
            with self._lock:
                self._running.discard(session_id)
