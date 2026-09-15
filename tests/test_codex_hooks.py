"""Registering the state hook in Codex's hooks.json, beside what others put there.

The herdr entry is the one found in a real ~/.codex/hooks.json on 2026-09-15.
"""
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "codex-hooks.sh"
HANDLER = "/Users/jane/.claude/skills/agents-sidebar/hooks-handlers/emit-state.py"
EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
          "PostToolUse", "Stop", "SessionEnd"]
HERDR = {"hooks": {"SessionStart": [{"hooks": [
    {"command": "bash '/Users/jane/.codex/herdr-agent-state.sh' session", "timeout": 10, "type": "command"}]}]}}


def register(path):
    return subprocess.run(["bash", str(SCRIPT), str(path), HANDLER], capture_output=True, text=True)


def commands(path):
    doc = json.loads(path.read_text())
    return {event: [h["command"] for group in groups for h in group["hooks"]]
            for event, groups in doc["hooks"].items()}


def test_each_event_runs_the_handler_for_codex(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    assert register(hooks).returncode == 0
    got = commands(hooks)
    for event in EVENTS:
        assert f"python3 '{HANDLER}' {event} --codex" in got[event]


def test_entries_it_did_not_write_are_kept(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    register(hooks)
    assert commands(hooks)["SessionStart"] == [
        "bash '/Users/jane/.codex/herdr-agent-state.sh' session",
        f"python3 '{HANDLER}' SessionStart --codex"]


def test_registering_twice_changes_nothing(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    register(hooks)
    once = hooks.read_text()
    register(hooks)
    assert hooks.read_text() == once
    assert commands(hooks)["Stop"] == [f"python3 '{HANDLER}' Stop --codex"]


def test_a_missing_hooks_file_is_created(tmp_path):
    hooks = tmp_path / "hooks.json"
    assert register(hooks).returncode == 0
    assert sorted(commands(hooks)) == sorted(EVENTS)


def test_an_unreadable_hooks_file_is_left_alone(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text("{not json")
    result = register(hooks)
    assert result.returncode != 0
    assert hooks.read_text() == "{not json"
    assert "left unchanged" in result.stderr
