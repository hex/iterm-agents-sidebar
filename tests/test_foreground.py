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
    (shells, started, _, _), panes, _ = sidebar.read_system()
    assert ran.count("/bin/ps") == 1
    assert shells == {5001: [{"label": "ls", "command": "ls"}]}
    assert started[5001] == 1789638277
    assert panes == {170: {"job": "codex", "path": "/Users/x/atlas"}}
