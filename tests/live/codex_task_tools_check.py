#!/usr/bin/env python3
# ABOUTME: Live check of the Codex task tools against the installed codex: one codex exec turn calls this checkout's
# ABOUTME: server, which writes its note under a scratch HOME named by the session id Codex prints.
"""Rerun against each new Codex: that the model sees the tools, that their
annotations spare the call an approval, and that _meta.threadId is the
session id rest on behaviour only a run can show. The server comes from
`-c` overrides, so ~/.codex/config.toml is never written (its hash is
checked before and after); the hooks in ~/.codex/hooks.json still run, as
for any Codex turn. One turn on the logged-in Codex account, under a minute.

    python3 tests/live/codex_task_tools_check.py
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SERVER = ROOT / "plugin" / "hooks-handlers" / "codex-task-tools.py"
CONFIG = Path.home() / ".codex" / "config.toml"
PROMPT = ("Call the agents-sidebar task_begin tool with title 'Probe the task tools', then call task_report with "
          "activity 'Checking the note' and percent 50, then reply with both tool results' text only. "
          "Do not run shell commands.")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def digest():
    return hashlib.sha256(CONFIG.read_bytes()).hexdigest() if CONFIG.exists() else None


def main():
    before = digest()
    with tempfile.TemporaryDirectory() as scratch:
        home, cwd = Path(scratch) / "home", Path(scratch) / "cwd"
        home.mkdir()
        cwd.mkdir()
        run = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
             "-c", 'mcp_servers.agents-sidebar.command="python3"',
             "-c", f"mcp_servers.agents-sidebar.args=[{json.dumps(str(SERVER))}]",
             "-c", f"mcp_servers.agents-sidebar.env={{HOME={json.dumps(str(home))}}}", PROMPT],
            cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=240)
        out = ANSI.sub("", run.stdout + run.stderr)
        session = re.search(r"^session id: (\S+)$", out, re.MULTILINE)
        notes = sorted((home / ".claude" / "agents-sidebar-tasks").glob("*.json"))
        checks = {
            "codex exec exits 0": run.returncode == 0,
            "task_begin and task_report completed": all(
                f"mcp: agents-sidebar/{tool} (completed)" in out for tool in ("task_begin", "task_report")),
            "no PermissionRequest hook fired": "PermissionRequest" not in out,
            "the one note is named by the session id": bool(session) and [p.stem for p in notes] == [session.group(1)],
            "the note holds the report": bool(notes) and {
                key: json.loads(notes[0].read_text())[key] for key in ("title", "activity", "percent", "done")} == {
                "title": "Probe the task tools", "activity": "Checking the note", "percent": 50, "done": False},
            "~/.codex/config.toml unchanged": digest() == before,
        }
    for name, held in checks.items():
        print(f"{'PASS' if held else 'FAIL'}  {name}")
    if not all(checks.values()):
        print(out[-4000:], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
