"""What a plain terminal is running, when iTerm2 cannot say.

Inside tmux, iTerm2 reports no jobName for a pane, so the row showed only its
directory. tmux knows each pane's tty, and the tty's foreground process group
knows the command. Sample lines are the real shape of
`ps -ww -eo pid=,ppid=,pgid=,tpgid=,tty=,lstart=,%cpu=,rss=,args=` and `tmux list-panes -a -F`, taken
from a live tmux pane running the Codex CLI on 2026-09-15.
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

PS = """\
 2801     1  2801  4828 ttys000 Thu Sep 17 09:44:37 2026 0.0 0 -zsh
 3291  2801  2826  4828 ttys000 Thu Sep 17 09:44:37 2026 0.0 0 /Users/x/.cache/gitstatus/gitstatusd-darwin-arm64 -G v1.5.4
 4828  2801  4828  4828 ttys000 Thu Sep 17 10:00:00 2026 0.0 0 /Users/x/.nvm/versions/node/v25.1.0/bin/node /Users/x/.nvm/versions/node/v25.1.0/bin/codex
 4907  4828  4828  4828 ttys000 Thu Sep 17 10:00:01 2026 0.0 0 /Users/x/node_modules/@openai/codex-darwin-arm64/vendor/codex
 5863  4828  5863  4828 ttys000 Thu Sep 17 10:01:00 2026 0.0 0 /opt/homebrew/bin/uv tool uvx --from some-mcp-server
 7001     1  7001  7001 ttys003 Thu Sep 17 10:02:00 2026 0.0 0 -bash
 7100  7001  7100  7100 ttys004 Thu Sep 17 12:00:00 2026 0.0 0 nvim README.md
 7200  7001  7200  7200 ttys005 Thu Sep 17 12:00:05 2026 0.0 0 /opt/homebrew/bin/python3 -m http.server
 9999     1  9999     0 ??      Thu Sep 17 09:00:00 2026 0.0 0 /usr/sbin/cfprefsd agent
"""


def test_the_foreground_group_leader_names_each_tty():
    assert sidebar.parse_foreground(PS) == {
        "ttys000": "codex", "ttys003": "-bash", "ttys004": "nvim", "ttys005": "python3"}


def test_a_script_run_by_an_interpreter_is_named_by_the_script():
    assert sidebar.foreground_command("/usr/bin/node /usr/local/bin/codex --yolo") == "codex"
    assert sidebar.foreground_command("python3.12 /opt/tools/serve.py") == "serve.py"


def test_an_interpreter_given_only_flags_keeps_its_own_name():
    assert sidebar.foreground_command("/opt/homebrew/bin/python3 -m http.server") == "python3"


def test_tmux_panes_map_to_their_ttys_and_directories():
    listing = ("%170 /dev/ttys001 /Users/x/.claude-sessions/atlas\n"
               "%206 /dev/ttys000 /Users/x/My Projects/orchard\n\ngarbage\n")
    assert sidebar.parse_tmux_panes(listing) == {
        170: {"tty": "ttys001", "path": "/Users/x/.claude-sessions/atlas"},
        206: {"tty": "ttys000", "path": "/Users/x/My Projects/orchard"}}


def test_a_pane_tmux_gives_no_directory_has_none():
    assert sidebar.parse_tmux_panes("%9 /dev/ttys009 \n") == {9: {"tty": "ttys009", "path": None}}


WIDE = """\
 2801     1  2801  4828 ttys000 Thu Sep 17 09:44:37 2026 0.0 0 -zsh
 4828  2801  4828  4828 ttys000 Thu Sep 17 10:00:00 2026 0.0 0 /Users/x/.nvm/versions/node/v25.1.0/bin/node /Users/x/.nvm/versions/node/v25.1.0/bin/codex
 4907  4828  4828  4828 ttys000 Thu Sep 17 10:00:01 2026 0.0 0 /Users/x/node_modules/@openai/codex-darwin-arm64/vendor/codex
 5001     1  5001  5001 ttys003 Thu Sep 17 09:44:37 2026 0.0 0 /Users/x/.local/bin/claude
 5002  5001  5002  5001 ttys003 Thu Sep 17 12:00:00 2026 0.0 0 /bin/zsh -c source /Users/x/.claude/shell-snapshots/snapshot-zsh-1-a.sh && eval 'ls'
 9999     1  9999     0 ??      Thu Sep 17 09:00:00 2026 0.0 0 /usr/sbin/cfprefsd agent
"""


def test_one_process_listing_serves_shells_start_times_and_foreground_jobs(monkeypatch, tmp_path, utc):
    """One ps per rebuild, however many facts come off it: each exec costs
    tens of milliseconds on the event loop and is inspected by every
    endpoint agent on the machine."""
    tmux = tmp_path / "tmux"
    tmux.write_text("#!/bin/sh\n")
    ran = []

    def fake_run(argv, **_):
        ran.append(argv[0])
        out = WIDE if argv[0] == "/bin/ps" else "%170 /dev/ttys000 /Users/x/atlas\n"
        return type("Done", (), {"stdout": out})()

    monkeypatch.setattr(sidebar.subprocess, "run", fake_run)
    monkeypatch.setattr(sidebar, "TMUX_PATHS", (str(tmux),))
    (shells, started, _, _), panes, _, _, _, _ = sidebar.read_system()
    assert ran.count("/bin/ps") == 1
    assert shells == {5001: [{"label": "ls", "command": "ls"}]}
    assert started[5001] == 1789638277
    assert panes == {170: {"job": "codex", "path": "/Users/x/atlas", "tty": "ttys000"}}


def test_a_codex_subcommand_names_itself_so_only_the_tui_reads_as_codex():
    """`codex exec` and `codex app-server` are not a person's session: the
    panel shows a card for the interactive TUI alone."""
    from sidebar import foreground_command
    node = "/Users/x/.nvm/versions/node/v25.1.0/bin/node /Users/x/.nvm/versions/node/v25.1.0/bin/codex"
    assert foreground_command(node) == "codex"
    assert foreground_command(node + " exec 'reply ok'") == "codex exec"
    assert foreground_command(node + " app-server") == "codex app-server"
    assert foreground_command(node + " --model gpt-6-astra") == "codex"


def test_a_tmux_table_names_its_host_and_its_panes():
    out = ("box %0 /dev/ttys001 /private/tmp\n"
           "box %4 /dev/ttys005 /srv/My App\n\ngarbage\n")
    assert sidebar.parse_tmux_table(out) == {
        "host": "box",
        "panes": {0: {"tty": "ttys001", "path": "/private/tmp"},
                  4: {"tty": "ttys005", "path": "/srv/My App"}}}


def test_a_tmux_table_with_no_pane_names_no_host():
    assert sidebar.parse_tmux_table("") == {"host": None, "panes": {}}


LOCAL_PANES = {4: {"job": "claude", "path": "/Users/x/atlas", "tty": "ttys004"}}
TABLES = {"here": {"host": "desk", "panes": {4: {"tty": "ttys004", "path": "/Users/x/atlas"}}},
          "there": {"host": "box", "panes": {4: {"tty": "ttys005", "path": "/srv/app"}}}}


def test_a_pane_of_a_tmux_server_on_this_machine_is_the_local_pane():
    assert sidebar.tmux_pane("here", TABLES, 4, "desk", LOCAL_PANES) == LOCAL_PANES[4]


def test_a_pane_of_a_tmux_server_elsewhere_never_takes_the_local_pane_of_its_number():
    assert sidebar.tmux_pane("there", TABLES, 4, "desk", LOCAL_PANES) == {"path": "/srv/app", "host": "box"}


def test_a_pane_of_a_connection_that_was_not_read_is_left_to_iterm2():
    assert sidebar.tmux_pane("lost", TABLES, 4, "desk", LOCAL_PANES) == {}


def test_a_session_outside_tmux_has_no_pane():
    assert sidebar.tmux_pane(None, TABLES, None, "desk", LOCAL_PANES) == {}


def test_a_tmux_session_whose_tab_names_no_connection_is_the_local_pane():
    assert sidebar.tmux_pane(None, {}, 4, "desk", LOCAL_PANES) == LOCAL_PANES[4]


def test_a_foreign_pane_the_table_does_not_list_has_a_host_and_no_path():
    assert sidebar.tmux_pane("there", TABLES, 9, "desk", LOCAL_PANES) == {"path": None, "host": "box"}


def test_this_machines_name_stops_at_its_first_dot(monkeypatch):
    monkeypatch.setattr(sidebar.socket, "gethostname", lambda: "desk.example.com")
    assert sidebar.local_host() == "desk"


def test_a_tmux_table_names_its_host_without_control_characters_and_clipped():
    assert sidebar.parse_tmux_table("bo\x1bx %0 /dev/ttys001 /srv\n")["host"] == "box"
    assert sidebar.parse_tmux_table("h" * 200 + " %0 /dev/ttys001 /srv\n")["host"] == "h" * 64
