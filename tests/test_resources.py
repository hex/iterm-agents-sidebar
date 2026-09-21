"""Tests for how much CPU and memory a session's process tree is using.

A session is more than its claude process: MCP servers, shells, builds and
subagents hang off it by parent pid. Sample lines are the shape of
`ps -ww -eo pid=,ppid=,pgid=,tpgid=,tty=,lstart=,%cpu=,rss=,args=`.
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)

PS = """\
  100     1   100   100 ttys001 Thu Sep 17 12:00:00 2026  12.5 300000 /Users/x/.local/bin/claude
  110   100   110   100 ttys001 Thu Sep 17 12:00:01 2026   4.0  80000 npm exec some-mcp@1.0
  111   110   110   100 ttys001 Thu Sep 17 12:00:01 2026  90.0 120000 node /x/some-mcp/index.js
  200     1   200   200 ttys002 Thu Sep 17 12:00:02 2026   1.5 250000 /Users/x/.local/bin/claude
  210   200   210   200 ttys002 Thu Sep 17 12:00:03 2026   0.0  10000 /bin/zsh -c make
  300   100   300   300 ttys003 Thu Sep 17 12:00:04 2026  50.0 400000 /Users/x/.local/bin/claude --agent-name review
    9     1     9     9 ??       Thu Sep 17 11:00:00 2026   0.1   2000 /usr/sbin/cfprefsd agent
"""


def test_the_listing_reads_each_process_parent_cpu_and_memory():
    table = sidebar.parse_resources(PS)
    assert table[111] == (110, 90.0, 120000, "ttys001")
    assert table[9] == (1, 0.1, 2000, None)
    assert len(table) == 7


def test_a_session_counts_its_whole_tree():
    table = sidebar.parse_resources(PS)
    # 200 + its shell: 1.5 + 0.0 %, 250000 + 10000 KB.
    assert sidebar.tree_usage(table, 200, stop_at={100, 200, 300}) == (1.5, 260000)


def test_a_session_stops_at_another_session_below_it():
    """A teammate spawned by the lead is its own card; counting it under the
    lead as well would light both for one busy process."""
    table = sidebar.parse_resources(PS)
    # 100 + 110 + 111, not 300: 12.5 + 4 + 90 %, 300000 + 80000 + 120000 KB.
    assert sidebar.tree_usage(table, 100, stop_at={100, 200, 300}) == (106.5, 500000)


def test_a_session_whose_process_is_gone_uses_nothing():
    assert sidebar.tree_usage(sidebar.parse_resources(PS), 4242, stop_at=set()) == (0.0, 0)


def test_a_line_that_does_not_parse_is_skipped():
    raw = "  1  1  1  1 ?? Thu Sep 17 11:00:00 2026 n/a n/a launchd\n" + PS
    assert 1 not in sidebar.parse_resources(raw)


def test_the_real_listing_reads_this_process():
    """The fixture shape is only worth something if ps prints it."""
    import os
    table = sidebar.parse_resources(sidebar.read_process_listing())
    parent, cpu, rss, _ = table[os.getpid()]
    assert parent == os.getppid() and cpu >= 0 and rss > 0


def test_a_session_under_both_thresholds_is_not_heavy():
    settings = {"cpu_threshold": 100, "memory_threshold": 2.0}
    assert sidebar.heavy_on(99.9, 2 * 1024 * 1024 - 1, settings) == []


def test_a_session_over_a_threshold_names_what_is_high():
    """At the threshold counts: 100 % is one whole core, which is what the
    setting says. Memory is in GB of resident KB."""
    settings = {"cpu_threshold": 100, "memory_threshold": 2.0}
    assert sidebar.heavy_on(100.0, 1024, settings) == ["cpu"]
    assert sidebar.heavy_on(0.0, 2 * 1024 * 1024, settings) == ["memory"]
    assert sidebar.heavy_on(350.0, 9 * 1024 * 1024, settings) == ["cpu", "memory"]


def test_the_defaults_are_one_core_and_two_gigabytes():
    assert sidebar.DEFAULT_SETTINGS["cpu_threshold"] == 100
    assert sidebar.DEFAULT_SETTINGS["memory_threshold"] == 2.0


def test_a_heavy_session_says_so_in_the_snapshot_and_a_light_one_says_nothing():
    base = {"session_id": "s0", "window_id": "w", "tab_id": "t",
            "window_index": 0, "tab_index": 0, "pane_index": 0,
            "path": "/Users/x/.claude-sessions/demo", "auto_name": "demo",
            "session_name": "cs: demo", "job_name": None, "agent_state": "working"}
    heavy = sidebar.snapshot([dict(base, heavy=["memory"])])["groups"][0]["rows"][0]
    light = sidebar.snapshot([dict(base, heavy=[])])["groups"][0]["rows"][0]
    assert heavy["heavy"] == ["memory"]
    assert "heavy" not in light


def test_a_chip_holds_through_a_dip_below_the_threshold():
    """Under load a busy process reads anywhere from a quarter to most of a
    core from one listing to the next, so the verdict alone would flicker."""
    seen = {}
    assert sidebar.hold_heavy(seen, ["cpu"], 100, now=0) == ["cpu"]
    assert sidebar.hold_heavy(seen, [], 100, now=2) == ["cpu"]
    assert sidebar.hold_heavy(seen, [], 100, now=14) == ["cpu"]
    assert sidebar.hold_heavy(seen, [], 100, now=16) == []


def test_a_fresh_reading_renews_the_hold():
    seen = {}
    sidebar.hold_heavy(seen, ["memory"], 7, now=0)
    sidebar.hold_heavy(seen, ["memory"], 7, now=10)
    assert sidebar.hold_heavy(seen, [], 7, now=20) == ["memory"]


def test_holds_keep_their_kind_order_and_their_session():
    seen = {}
    sidebar.hold_heavy(seen, ["memory"], 7, now=0)
    assert sidebar.hold_heavy(seen, ["cpu"], 7, now=1) == ["cpu", "memory"]
    assert sidebar.hold_heavy(seen, [], 8, now=1) == []


def test_a_session_that_is_gone_is_forgotten():
    seen = {}
    sidebar.hold_heavy(seen, ["cpu"], 7, now=0)
    sidebar.forget_heavy(seen, live={8})
    assert seen == {}


def test_the_listing_names_each_process_by_its_program():
    names = sidebar.parse_commands(PS)
    assert names[111] == "node"
    assert names[110] == "npm"
    assert names[100] == "claude"


def test_a_tree_names_what_uses_the_most_of_each():
    table, names = sidebar.parse_resources(PS), sidebar.parse_commands(PS)
    # Under 100, node burns the CPU (90.0) and claude holds the memory (300000 KB).
    assert sidebar.tree_hogs(table, names, 100, stop_at={100, 200, 300}) == {
        "cpu": "node", "memory": "claude"}


def test_a_tree_that_is_gone_names_nothing():
    table, names = sidebar.parse_resources(PS), sidebar.parse_commands(PS)
    assert sidebar.tree_hogs(table, names, 4242, stop_at=set()) == {}


def test_a_heavy_kind_carries_a_round_figure_and_its_hog():
    # 187.4 % of a core and 3.27 GB resident, both held heavy.
    usage = sidebar.usage_shown(["cpu", "memory"], 187.4, int(3.27 * 1024 * 1024),
                                {"cpu": "node", "memory": "claude"})
    assert usage == {"cpu": {"percent": 190, "top": "node"},
                     "memory": {"gb": 3.3, "top": "claude"}}


def test_a_kind_that_is_not_heavy_carries_no_figure():
    """The figures move on every reading; only a heavy session pays for that."""
    usage = sidebar.usage_shown(["memory"], 187.4, int(3.27 * 1024 * 1024), {"memory": "claude"})
    assert usage == {"memory": {"gb": 3.3, "top": "claude"}}
    assert sidebar.usage_shown([], 187.4, 100, {}) == {}


def test_a_heavy_session_carries_its_figures_into_the_snapshot():
    base = {"session_id": "s0", "window_id": "w", "tab_id": "t",
            "window_index": 0, "tab_index": 0, "pane_index": 0,
            "path": "/Users/x/.claude-sessions/demo", "auto_name": "demo",
            "session_name": "cs: demo", "job_name": None, "agent_state": "working"}
    usage = {"memory": {"gb": 3.3, "top": "node"}}
    heavy = sidebar.snapshot([dict(base, heavy=["memory"], usage=usage)])["groups"][0]["rows"][0]
    light = sidebar.snapshot([dict(base, heavy=[], usage={})])["groups"][0]["rows"][0]
    assert heavy["usage"] == usage
    assert "usage" not in light
