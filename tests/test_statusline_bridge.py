# ABOUTME: Runs the statusline bridge with disposable commands and cached lines.
# ABOUTME: Checks missing-command diagnostics without reaching the user's statusline.
import os
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent


def render(home, command):
    status = home / ".claude" / "agents-sidebar-status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "original-statusline").write_text(command)
    line = status / f"{os.getpid()}.line"
    line.write_text("cached line\n")
    result = subprocess.run(["bash", str(REPO / "plugin" / "statusline-bridge.sh")],
                            input="{}", capture_output=True, text=True, timeout=10,
                            env={"HOME": str(home), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0
    assert result.stderr == ""
    return result.stdout, line.read_text()


def test_a_missing_command_replaces_the_cached_line(tmp_path):
    assert render(tmp_path, "missing-status-command") == (
        "status line: missing-status-command not found\n", "status line: missing-status-command not found\n")


@pytest.mark.parametrize("prefix", ["", "bash "])
def test_a_missing_script_is_named_even_when_quoted(tmp_path, prefix):
    script = tmp_path / "gone status.sh"
    expected = f"status line: {script} not found\n"
    assert render(tmp_path, f"{prefix}'{script}' --quiet") == (expected, expected)


def test_a_missing_interpreter_is_named_instead_of_its_existing_script(tmp_path):
    script = tmp_path / "status.py"
    script.write_text("print('status')\n")
    assert render(tmp_path, f"python999 '{script}'") == (
        "status line: python999 not found\n", "status line: python999 not found\n")


def test_a_command_name_with_a_carriage_return_stays_on_one_line(tmp_path):
    assert render(tmp_path, "'missing\rstatus'") == (
        "status line: missing status not found\n", "status line: missing status not found\n")


def test_other_command_failures_keep_the_cached_line(tmp_path):
    assert render(tmp_path, "printf 'unfinished'; exit 9") == ("cached line\n", "cached line\n")


def test_a_successful_command_replaces_the_cached_line(tmp_path):
    assert render(tmp_path, "printf 'current line\\n'") == ("current line\n", "current line\n")


def test_a_shell_comment_does_not_break_the_missing_command_message(tmp_path):
    assert render(tmp_path, "missing-status-command # user's status") == (
        "status line: missing-status-command not found\n", "status line: missing-status-command not found\n")
