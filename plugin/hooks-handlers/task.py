#!/usr/bin/env python3
"""The note a session writes about its own work, for the Agents sidebar.

ABOUTME: One JSON file per session: task title, percent, activity, done.
ABOUTME: Run by the agent itself; the hook tells it when and how.

    task.py --session <id> begin --title "Fix the login bug"
    task.py --session <id> report --activity "Reading code" --percent 35
    task.py --session <id> report --activity "Assessing task" --unknown

Self-reported, not measured. What keeps it honest is the time of the last
report, which the panel shows, and that a new request starts a new task.
A hundred percent means done and locks the task; more work needs `begin`.
"""
import argparse
import json
import os
import re
import sys
import time
import uuid

TASKS_DIR = os.path.expanduser("~/.claude/agents-sidebar-tasks")
TITLE_WIDTH = 80
ACTIVITY_WIDTH = 40

_SESSION = re.compile(r"^[A-Za-z0-9._-]+$")
#: Control characters and the bidi overrides that could make a label read as
#: something else on the card.
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f‪-‮⁦-⁩]")


def clean(text, width):
    return _UNPRINTABLE.sub("", text)[:width].strip()


def note_path(session_id):
    return os.path.join(TASKS_DIR, f"{session_id}.json")


def read_note(path):
    """The note at path, or None when there is none or it cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            note = json.load(fh)
    except (OSError, ValueError):
        return None
    return note if isinstance(note, dict) and "task" in note else None


def write_note(path, note):
    """Whole and then renamed into place: the daemon reads on a timer."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(note, fh)
    os.replace(tmp, path)


def begin(title, now):
    title = clean(title, TITLE_WIDTH)
    if not title:
        raise ValueError("title is empty")
    return {"task": uuid.uuid4().hex, "title": title, "activity": None,
            "percent": None, "done": False, "ts": round(now)}


def report(note, activity, percent, now):
    if note is None:
        raise ValueError("no task yet: run begin first")
    if note.get("done"):
        raise ValueError("task is done: begin a new one for more work")
    activity = clean(activity, ACTIVITY_WIDTH)
    if not activity:
        raise ValueError("activity is empty")
    if percent is not None and not 0 <= percent <= 100:
        raise ValueError("percent must be 0 to 100")
    done = percent == 100
    return dict(note, activity="Done" if done else activity, percent=percent,
                done=done, ts=round(now))


def parse(argv):
    parser = argparse.ArgumentParser(prog="task.py", add_help=True)
    parser.add_argument("--session", required=True)
    verbs = parser.add_subparsers(dest="verb", required=True)
    b = verbs.add_parser("begin")
    b.add_argument("--title", required=True)
    r = verbs.add_parser("report")
    r.add_argument("--activity", required=True)
    how = r.add_mutually_exclusive_group(required=True)
    how.add_argument("--percent", type=int)
    how.add_argument("--unknown", action="store_true")
    return parser.parse_args(argv)


def main(argv):
    try:
        args = parse(argv)
    except SystemExit as error:
        return int(error.code or 0)
    if not _SESSION.match(args.session):
        print("task.py: session id must be a plain token", file=sys.stderr)
        return 1
    path = note_path(args.session)
    try:
        if args.verb == "begin":
            note = begin(args.title, time.time())
        else:
            note = report(read_note(path), args.activity,
                          None if args.unknown else args.percent, time.time())
        write_note(path, note)
    except (ValueError, OSError) as error:
        print(f"task.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
