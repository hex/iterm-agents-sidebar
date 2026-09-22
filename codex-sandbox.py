#!/usr/bin/env python3
# ABOUTME: Adds one directory to [sandbox_workspace_write] writable_roots in Codex's
# ABOUTME: config.toml, touching nothing else; refuses layouts it cannot read for certain.
"""Usage: codex-sandbox.py <config.toml> <directory>

Codex writes only inside its workspace, and the task note the agent keeps
lives outside it, so that directory has to be named here. The standard
library reads TOML but does not write it, so this is a line edit of one
table: the table is created when absent, the key added when absent, the
directory appended to a one-line array when missing. An array laid out over
several lines is left alone with a message, exit 2, rather than guessed at.
The first run keeps a copy of the file as it was.
"""
import os
import re
import shutil
import sys

TABLE = "[sandbox_workspace_write]"
KEY = re.compile(r'^(\s*writable_roots\s*=\s*)\[(.*)\]\s*$')
OPEN = re.compile(r'^\s*writable_roots\s*=\s*\[\s*$')


def edited(lines, directory):
    """-> the lines with the directory named, or None when nothing changes."""
    quoted = f'"{directory}"'
    try:
        head = next(i for i, line in enumerate(lines) if line.strip() == TABLE)
    except StopIteration:
        tail = [] if not lines or lines[-1] == "" else [""]
        return lines + tail + [TABLE, f"writable_roots = [{quoted}]"]
    end = next((i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for i in range(head + 1, end):
        if OPEN.match(lines[i]):
            raise ValueError("writable_roots spans several lines")
        m = KEY.match(lines[i])
        if not m:
            continue
        if quoted in m.group(2):
            return None
        inside = m.group(2).strip()
        lines[i] = f"{m.group(1)}[{inside + ', ' if inside else ''}{quoted}]"
        return lines
    lines.insert(head + 1, f"writable_roots = [{quoted}]")
    return lines


def main(path, directory):
    text = open(path).read() if os.path.exists(path) else ""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    try:
        result = edited(lines, directory)
    except ValueError as why:
        print(f"{path}: {why}; add {directory} to it by hand", file=sys.stderr)
        sys.exit(2)
    if result is None:
        return
    backup = path + ".before-agents-sidebar"
    if text and not os.path.exists(backup):
        shutil.copyfile(path, backup)
    tmp = path + ".agents-sidebar.tmp"
    with open(tmp, "w") as out:
        out.write("\n".join(result) + "\n")
    os.replace(tmp, path)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__.split("\n")[0])
    main(sys.argv[1], sys.argv[2])
