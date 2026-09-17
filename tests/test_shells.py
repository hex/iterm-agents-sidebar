"""Tests for counting a session's Claude Code shells.

Neither the statusline payload nor the transcript publishes this, so the
process tree is the only place the fact escapes. Sample lines are the real
shape of `ps -ww -eo pid=,ppid=,pgid=,tpgid=,tty=,lstart=,%cpu=,rss=,args=`, from a live
session on 2026-09-07 whose own footer read "2 shells".
"""
import importlib.util
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)


@pytest.fixture
def utc(monkeypatch):
    """Start stamps read as UTC for the test, and the process clock goes back
    with the variable: tzset() reads TZ once, so restoring the variable alone
    would leave every later test in the wrong zone."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()

SNAP = "/Users/x/.claude/shell-snapshots/snapshot-zsh-1788767509187-cg9f4y.sh"
ROW = "{pid} {parent} {pid} {parent} ttys001 Thu Sep 17 12:00:00 2026 0.0 0 {args}\n"
PS = "".join(ROW.format(pid=pid, parent=parent, args=args) for pid, parent, args in [
    (52583, 1, "/Users/x/.local/bin/claude"),
    (52605, 52583, "/usr/bin/caffeinate -i"),
    (53418, 52583, "npm exec chrome-devtools-mcp@1.8.0"),
    (58776, 52583, f"/bin/zsh -c source {SNAP} && eval 'ls'"),
    (97694, 52583, f"/bin/zsh -c source {SNAP} && eval 'tail -f log'"),
    (70173, 52583, "/bin/bash /some/hook.sh"),
    (16656, 1, "/Users/x/.local/bin/claude"),
    (31030, 16656, f"/bin/zsh -c source {SNAP} && eval 'pwd'"),
])


def shells_of(raw):
    return {parent: [s["command"] for s in rows] for parent, rows in sidebar.parse_processes(raw)[0].items()}


def test_a_session_reports_only_its_own_shells():
    assert shells_of(PS) == {52583: ["ls", "tail -f log"], 16656: ["pwd"]}


def test_the_marker_is_the_snapshot_not_the_shell_name():
    """Counting zsh children would catch a login shell or a user's own
    subprocess. Claude Code sources a snapshot from ~/.claude/shell-snapshots
    into every shell it opens, whatever $SHELL happens to be.
    """
    assert shells_of(ROW.format(pid=98000, parent=52583, args=f"/bin/bash -c source {SNAP} && eval 'make'")) == {52583: ["make"]}
    assert shells_of(ROW.format(pid=98001, parent=52583, args="/bin/zsh -l")) == {}


def test_processes_that_are_not_shells_are_not_counted():
    assert shells_of(ROW.format(pid=52605, parent=52583, args="/usr/bin/caffeinate -i")) == {}


def test_unreadable_output_is_not_a_crash():
    for raw in ("", None, "garbage", ROW.format(pid="notapid", parent=52583, args=f"/bin/zsh -c source {SNAP}")):
        assert shells_of(raw) == {}


# ps prints a process's start as `lstart`, a fixed calendar stamp in local
# time; the moment it started, not how long ago, so it reads the same on
# every rebuild.
def test_a_process_start_stamp_reads_as_local_time(utc):
    assert sidebar.process_start("Thu Sep 17 09:44:37 2026") == 1789638277
    assert sidebar.process_start("  Mon Jan  5 00:00:00 2026 ") == 1767571200


def test_a_start_stamp_that_makes_no_sense():
    for raw in (None, "", "soon", "11:00:36", "Thu Sep 17 09:44 2026"):
        assert sidebar.process_start(raw) is None


UPTIMES = f"""\
52583     1 52583 52583 ttys001 Thu Sep 17 09:44:37 2026 0.0 0 /Users/x/.local/bin/claude
58776 52583 58776 52583 ttys001 Thu Sep 17 20:43:32 2026 0.0 0 /bin/zsh -c source {SNAP} && eval 'ls'
97694 52583 97694 52583 ttys001 Thu Sep 17 11:04:12 2026 0.0 0 /bin/zsh -c source {SNAP} && eval 'tail -f log'
16656     1 16656 16656 ttys002 Thu Sep 17 14:16:37 2026 0.0 0 /Users/x/.local/bin/claude
"""


def test_one_listing_yields_both_shells_and_start_times(utc):
    """Both facts come off the same ps, because running it twice per rebuild
    to learn two things about the same processes would be silly.
    """
    shells, started, _, _ = sidebar.parse_processes(UPTIMES)
    assert shells == {52583: [{"label": "ls", "command": "ls"},
                              {"label": "tail -f log", "command": "tail -f log"}]}
    assert started[52583] == 1789638277
    assert started[16656] == 1789654597


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
    shells, _, _, _ = sidebar.parse_processes(f"58776 52583 58776 52583 ttys001 Thu Sep 17 20:43:32 2026 0.0 0 /bin/zsh -c source {SNAP}\n")
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
    ps = f"58776 52583 58776 52583 ttys001 Thu Sep 17 20:43:32 2026 0.0 0 /bin/zsh -c source {SNAP} && eval 'cd ~/repo && npm test' < /dev/null && pwd -P >| /tmp/claude-1-cwd\n"
    shells, _, _, _ = sidebar.parse_processes(ps)
    assert shells == {52583: [{"label": "npm test", "command": "cd ~/repo && npm test"}]}


# A teammate's colour is on its own command line, the only place it is kept:
# its transcript records a name and a team but no colour. Shape from a live
# teammate on 2026-09-15.
TEAMMATE = ("86515     1 86515 86515 ttys004 Thu Sep 17 12:00:00 2026 0.0 0 /Users/x/.local/share/claude/versions/2.1.270 "
            "--agent-id icon@session-503e9a69 --agent-name icon "
            "--team-name session-503e9a69 --agent-color blue --parent-session-id 6f594cbd\n")


def test_a_teammate_reports_the_colour_it_was_spawned_with():
    _, _, colours, _ = sidebar.parse_processes(TEAMMATE)
    assert colours == {86515: "blue"}


def test_a_session_started_without_a_colour_has_none():
    _, _, colours, _ = sidebar.parse_processes(UPTIMES)
    assert colours == {}


def test_a_teammates_parent_session_is_read_off_its_command_line():
    """Claude Code hands a teammate its lead's session id as
    --parent-session-id; nothing else the sidebar reads says who spawned it."""
    from sidebar import parse_processes
    raw = ("4242 4000 4242 4242 ttys005 Thu Sep 17 12:00:00 2026 0.0 0 /x/claude --agent-id review-351@session-0da70176 --agent-name review-351 "
           "--team-name session-0da70176 --agent-color yellow --parent-session-id 6a4d1211-632c-4c8e-9c0a-000000000001 --resume x\n")
    assert parse_processes(raw)[3] == {4242: "6a4d1211-632c-4c8e-9c0a-000000000001"}


def test_the_panels_own_task_report_is_not_a_command_running():
    """The prompt hook asks every session to run task.py; counting that run
    would make each report grow and shrink the card it describes."""
    ours = (f"/bin/zsh -c source {SNAP} && eval 'python3 /Users/x/.claude/skills/agents-sidebar/hooks-handlers/task.py"
            " --session abc report --activity Testing --percent 40' < /dev/null && pwd -P >| /tmp/claude-1-cwd")
    theirs = f"/bin/zsh -c source {SNAP} && eval 'python3 tools/task.py --all' < /dev/null && pwd -P >| /tmp/claude-2-cwd"
    shells, _, _, _ = sidebar.parse_processes(f"1 52583 1 52583 ttys001 Thu Sep 17 12:00:00 2026 0.0 0 {ours}\n2 52583 2 52583 ttys001 Thu Sep 17 12:00:01 2026 0.0 0 {theirs}\n")
    assert shells == {52583: [{"label": "python3 tools/task.py --all", "command": "python3 tools/task.py --all"}]}


def test_a_home_path_in_a_command_reads_as_tilde():
    args = (f"/bin/zsh -c source {SNAP} && eval 'python3 /Users/x/.claude/skills/x/run.py --flag' < /dev/null"
            " && pwd -P >| /tmp/claude-3-cwd")
    shells, _, _, _ = sidebar.parse_processes(f"1 5 1 5 ttys001 Thu Sep 17 12:00:00 2026 0.0 0 {args}\n", home="/Users/x")
    assert shells[5][0]["label"] == "python3 ~/.claude/skills/x/run.py --flag"
