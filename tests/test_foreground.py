"""What a plain terminal is running, when iTerm2 cannot say.

Inside tmux, iTerm2 reports no jobName for a pane, so the row showed only its
directory. tmux knows each pane's tty, and the tty's foreground process group
knows the command. Sample lines are the real shape of
`ps -ww -eo pid=,pgid=,tpgid=,tty=,args=` and `tmux list-panes -a -F`, taken
from a live tmux pane running the Codex CLI on 2026-09-15.
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)

PS = """\
 2801  2801  4828 ttys000  -zsh
 3291  2826  4828 ttys000  /Users/x/.cache/gitstatus/gitstatusd-darwin-arm64 -G v1.5.4
 4828  4828  4828 ttys000  /Users/x/.nvm/versions/node/v25.1.0/bin/node /Users/x/.nvm/versions/node/v25.1.0/bin/codex
 4907  4828  4828 ttys000  /Users/x/node_modules/@openai/codex-darwin-arm64/vendor/codex
 5863  5863  4828 ttys000  /opt/homebrew/bin/uv tool uvx --from some-mcp-server
 7001  7001  7001 ttys003  -bash
 7100  7100  7100 ttys004  nvim README.md
 7200  7200  7200 ttys005  /opt/homebrew/bin/python3 -m http.server
 9999  9999     0 ??       /usr/sbin/cfprefsd agent
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
