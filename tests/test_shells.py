"""Tests for counting a session's Claude Code shells.

Neither the statusline payload nor the transcript publishes this, so the
process tree is the only place the fact escapes. Sample lines are the real
shape of `ps -eo pid=,ppid=,args=`, taken from a live session on 2026-09-07
whose own footer read "2 shells".
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)

SNAP = "/Users/x/.claude/shell-snapshots/snapshot-zsh-1788767509187-cg9f4y.sh"
PS = f"""\
52583     1 /Users/x/.local/bin/claude
52605 52583 /usr/bin/caffeinate -i
53418 52583 npm exec chrome-devtools-mcp@1.8.0
58776 52583 /bin/zsh -c source {SNAP} && eval 'ls'
97694 52583 /bin/zsh -c source {SNAP} && eval 'tail -f log'
70173 52583 /bin/bash /some/hook.sh
16656     1 /Users/x/.local/bin/claude
31030 16656 /bin/zsh -c source {SNAP} && eval 'pwd'
"""


def test_a_session_reports_only_its_own_shells():
    assert sidebar.parse_shells(PS) == {52583: 2, 16656: 1}


def test_the_marker_is_the_snapshot_not_the_shell_name():
    """Counting zsh children would catch a login shell or a user's own
    subprocess. Claude Code sources a snapshot from ~/.claude/shell-snapshots
    into every shell it opens, whatever $SHELL happens to be.
    """
    ps = f"98000 52583 /bin/bash -c source {SNAP} && eval 'make'\n"
    assert sidebar.parse_shells(ps) == {52583: 1}

    assert sidebar.parse_shells("98001 52583 /bin/zsh -l\n") == {}


def test_processes_that_are_not_shells_are_not_counted():
    assert sidebar.parse_shells("52605 52583 /usr/bin/caffeinate -i\n") == {}


def test_unreadable_output_is_not_a_crash():
    for raw in ("", None, "garbage", "notapid 52583 /bin/zsh -c source " + SNAP):
        assert sidebar.parse_shells(raw) == {}


# ps reports elapsed time in four shapes depending on how long ago it started.
def test_elapsed_time_in_every_shape_ps_uses():
    assert sidebar.uptime_seconds("11:23") == 683                 # MM:SS
    assert sidebar.uptime_seconds("06:28:36") == 23316            # HH:MM:SS
    assert sidebar.uptime_seconds("2-03:04:05") == 183845         # D-HH:MM:SS
    assert sidebar.uptime_seconds("  11:00:36 ") == 39636         # padded


def test_elapsed_time_that_makes_no_sense():
    for raw in (None, "", "soon", "1:2:3:4", "--"):
        assert sidebar.uptime_seconds(raw) is None


UPTIMES = f"""\
52583     1  11:00:36 /Users/x/.local/bin/claude
58776 52583      1:41 /bin/zsh -c source {SNAP} && eval 'ls'
97694 52583   9:41:01 /bin/zsh -c source {SNAP} && eval 'tail -f log'
16656     1  06:28:36 /Users/x/.local/bin/claude
"""


def test_one_listing_yields_both_shells_and_uptime():
    """Both facts come off the same ps, because running it twice per rebuild
    to learn two things about the same processes would be silly.
    """
    shells, uptime, _ = sidebar.parse_processes(UPTIMES)
    assert shells == {52583: [{"label": "ls", "command": "ls"},
                              {"label": "tail -f log", "command": "tail -f log"}]}
    assert uptime[52583] == 39636
    assert uptime[16656] == 23316


# What a shell is running, so it can be listed under its session. The quoting
# is Claude Code's: the command is single-quoted after `eval`, an embedded
# quote becomes '"'"', and ps prints a newline as \012.
def test_the_command_a_shell_is_running():
    args = f"/bin/zsh -c source {SNAP} 2>/dev/null || true && eval 'npm run dev' < /dev/null && pwd -P >| /tmp/claude-f886-cwd"
    assert sidebar.shell_command(args) == "npm run dev"


def test_quotes_and_newlines_in_the_command_are_undone():
    args = (f"/bin/zsh -c source {SNAP} && eval 'jq -c '\"'\"'.[]'\"'\"' f\\012tail -f log'"
            " < /dev/null && pwd -P >| /tmp/claude-aed6-cwd")
    assert sidebar.shell_command(args) == "jq -c '.[]' f; tail -f log"


def test_a_shell_without_an_eval_has_no_command():
    assert sidebar.shell_command(f"/bin/zsh -c source {SNAP}") is None


def test_a_shell_whose_command_cannot_be_read_is_still_listed():
    """Dropping it would undercount; guessing would lie. It renders "?"."""
    shells, _, _ = sidebar.parse_processes(f"58776 52583 1:41 /bin/zsh -c source {SNAP}\n")
    assert shells == {52583: [{"label": "?", "command": "?"}]}


# A row shows what the shell does, not the setup in front of it. Shapes taken
# from the live panel on 2026-09-15, paths generalised.
def test_a_leading_cd_is_not_the_label():
    assert sidebar.shell_label(
        "cd /Users/x/.claude-sessions/ledger; git add a.swift && git commit -m 'wip'"
    ) == "git add a.swift && git commit -m 'wip'"
    assert sidebar.shell_label("cd ~/repo && npm test") == "npm test"


def test_leading_assignments_are_not_the_label():
    assert sidebar.shell_label(
        'S=/private/tmp/scratch; F=/x/page.html; CH="/Applications/Google Chrome.app/x"; '
        'for s in 1 3 5; do "$CH" --headless; done'
    ) == 'for s in 1 3 5; do "$CH" --headless; done'
    assert sidebar.shell_label(
        "SANDBOX_RUNTIME=container /Users/x/bin/tool --flag") == "/Users/x/bin/tool --flag"


def test_a_command_that_is_only_setup_keeps_its_text():
    """An empty row would say less than the setup does."""
    assert sidebar.shell_label("cd /x") == "cd /x"
    assert sidebar.shell_label("A=1") == "A=1"


def test_a_plain_command_is_its_own_label():
    assert sidebar.shell_label("npm run dev") == "npm run dev"


def test_a_listed_shell_carries_its_label_and_its_whole_command():
    ps = f"58776 52583 1:41 /bin/zsh -c source {SNAP} && eval 'cd ~/repo && npm test' < /dev/null && pwd -P >| /tmp/claude-1-cwd\n"
    shells, _, _ = sidebar.parse_processes(ps)
    assert shells == {52583: [{"label": "npm test", "command": "cd ~/repo && npm test"}]}


# A teammate's colour is on its own command line, the only place it is kept:
# its transcript records a name and a team but no colour. Shape from a live
# teammate on 2026-09-15.
TEAMMATE = ("86515     1  4:02 /Users/x/.local/share/claude/versions/2.1.270 "
            "--agent-id icon@session-503e9a69 --agent-name icon "
            "--team-name session-503e9a69 --agent-color blue --parent-session-id 6f594cbd\n")


def test_a_teammate_reports_the_colour_it_was_spawned_with():
    _, _, colours = sidebar.parse_processes(TEAMMATE)
    assert colours == {86515: "blue"}


def test_a_session_started_without_a_colour_has_none():
    _, _, colours = sidebar.parse_processes(UPTIMES)
    assert colours == {}
