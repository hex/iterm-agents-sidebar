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


def test_only_our_command_leaves_a_mixed_entry(tmp_path):
    """An entry that holds another tool's command beside an old copy of ours
    keeps the other tool's."""
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"command": "bash '/Users/jane/.codex/herdr-agent-state.sh' stop", "timeout": 10, "type": "command"},
        {"command": f"python3 '{HANDLER}' Stop --codex", "timeout": 5, "type": "command"}]}]}}))
    assert register(hooks).returncode == 0
    assert commands(hooks)["Stop"] == [
        "bash '/Users/jane/.codex/herdr-agent-state.sh' stop",
        f"python3 '{HANDLER}' Stop --codex"]


def test_a_file_that_already_says_it_is_not_rewritten(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    register(hooks)
    stamp = hooks.stat().st_mtime_ns
    register(hooks)
    assert hooks.stat().st_mtime_ns == stamp


def test_remove_takes_only_our_entries_out(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    register(hooks)
    removed = subprocess.run(["bash", str(SCRIPT), "--remove", str(hooks), HANDLER],
                             capture_output=True, text=True)
    assert removed.returncode == 0
    assert commands(hooks) == {"SessionStart": ["bash '/Users/jane/.codex/herdr-agent-state.sh' session"]}


def test_remove_on_a_file_without_us_changes_nothing(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text(json.dumps(HERDR))
    before = hooks.read_text()
    subprocess.run(["bash", str(SCRIPT), "--remove", str(hooks), HANDLER], capture_output=True)
    assert hooks.read_text() == before
