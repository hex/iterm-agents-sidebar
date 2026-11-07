#!/usr/bin/env python3.10
# ABOUTME: Past conversations for the Sessions tab of the panel's History fold, read from Claude Code's transcripts.
# ABOUTME: Local files only; a cs session is one row, any other directory one row per conversation.
"""Claude Code writes one transcript per conversation under
~/.claude/projects/<directory with / as ->/<conversation>.jsonl, each line
carrying the directory it ran in. The fold lists the ones written to lately
that are not open now."""
import json
import os
import re

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
#: How far back the fold looks; a transcript last written before that is not listed.
DAYS = 7
#: How many rows the fold shows, newest first.
MOST = 30
#: How much of a transcript's start is read for its directory and first prompt.
HEAD_BYTES = 64 * 1024
TITLE_LIMIT = 80
CONVERSATION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _head(path):
    """A transcript's directory and first prompt, from its first lines, or (None, None)."""
    cwd = title = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(HEAD_BYTES)
    except OSError:
        return None, None
    for line in head.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        cwd = cwd or event.get("cwd")
        if title is None and event.get("type") == "user" and not event.get("isMeta"):
            title = _prompt_text(event)
        if cwd and title:
            break
    return (cwd if isinstance(cwd, str) else None), title


def _prompt_text(event):
    """The text of a user line, or None when it is a hook's or a command's, not a prompt."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = next((part.get("text") for part in content
                        if isinstance(part, dict) and part.get("type") == "text"), None)
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text or text.startswith("<"):
        return None
    return text.splitlines()[0][:TITLE_LIMIT]


def _transcripts(projects_dir, since):
    """(mtime, path, conversation) of every conversation transcript written since `since`."""
    found = []
    try:
        folders = os.listdir(projects_dir)
    except OSError:
        return found
    for folder in folders:
        folder = os.path.join(projects_dir, folder)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext != ".jsonl" or not CONVERSATION.fullmatch(stem):
                continue
            path = os.path.join(folder, name)
            try:
                written = os.path.getmtime(path)
            except OSError:
                continue
            if written >= since:
                found.append((written, path, stem))
    return found


#: Folders a tool keeps for itself inside a project: Claude Code's subagent
#: worktrees and a cs session's own files. A conversation there is a
#: subagent's or a fork's, not one anyone resumes into.
INTERNAL = ("/.claude/worktrees/", "/.cs/")


def _internal(cwd):
    return any(part in cwd + "/" for part in INTERNAL)


def rows(projects_dir, now, live_paths, live_conversations):
    """The Sessions tab's rows, newest first: {kind, name, path, conversation, title, at}.

    `kind` is "cs" for a directory with a .cs folder, one row per session
    whose `at` is its newest conversation and whose Resume goes through cs,
    else "claude", one row per conversation. A conversation open now
    (`live_conversations`) or a cs session with a card (`live_paths`) is
    not past, and a directory that is gone cannot be resumed.
    """
    out, sessions = [], {}
    for written, path, conversation in sorted(_transcripts(projects_dir, now - DAYS * 86400), reverse=True):
        cwd, title = _head(path)
        if not cwd or not os.path.isdir(cwd) or _internal(cwd):
            continue
        if os.path.isdir(os.path.join(cwd, ".cs")):
            if cwd in live_paths or cwd in sessions:
                continue
            sessions[cwd] = True
            out.append({"kind": "cs", "name": os.path.basename(cwd), "path": cwd, "conversation": None,
                        "title": None, "at": int(written)})
        else:
            if conversation in live_conversations:
                continue
            out.append({"kind": "claude", "name": os.path.basename(cwd), "path": cwd, "conversation": conversation,
                        "title": title, "at": int(written)})
        if len(out) >= MOST:
            break
    return out
