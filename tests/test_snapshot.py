"""Tests for snapshot().

Session ids, window ids, paths and titles are verbatim from the 2026-09-07
spike capture of the live iTerm2 instance.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import by_name, snapshot

WINDOW = "pty-3DB79DF4-CAA8-44F2-B92D-B359716CDFCB"

# Three real sessions, deliberately given in an order that is neither the
# desired output order nor alphabetical.
LIVE = [
    {
        "session_id": "8C1CB119-D3C8-47CF-8F93-FCBCEA1A76D1",
        "window_id": WINDOW, "tab_id": "27",
        "window_index": 1, "tab_index": 6, "pane_index": 1,
        "path": "/Users/x/Downloads", "auto_name": "zsh",
        "job_name": "nvim",
    },
    {
        "session_id": "D515C9B9-0424-4EAF-8F38-19C1957C266E",
        "window_id": WINDOW, "tab_id": "26",
        "window_index": 1, "tab_index": 5, "pane_index": 1,
        "path": "/Users/x/.claude-sessions/iterm-agents-sidebar",
        "auto_name": "✳ iterm-agents-sidebar", "job_name": "node",
    },
    {
        "session_id": "4333A75C-CB61-45DD-92E5-D7E60268038A",
        "window_id": WINDOW, "tab_id": "2",
        "window_index": 1, "tab_index": 1, "pane_index": 1,
        "path": "/Users/x/.claude-sessions/orchard",
        "auto_name": "✳ orchard", "job_name": "python3.12",
    },
]


def test_agents_group_comes_first_and_keeps_enumeration_order():
    """AGENTS above SESSIONS; within a group, the order it was handed.

    snapshot does not re-sort within a group -- note tab 26 stays ahead of tab
    2 here. Bridge supplies sessions in iTerm2 enumeration order (window, then
    tab, then split pane), which is the spatial order on screen. A list that
    re-sorts itself under you is the entropy-of-trust failure this sidebar
    exists to avoid, so the only reordering is the agents-first split.
    """
    result = snapshot(LIVE)
    assert [(g["name"], [r["label"] for r in g["rows"]]) for g in result["groups"]] == [
        ("AGENTS", ["iterm-agents-sidebar", "orchard"]),
        ("SESSIONS", ["/Users/x/Downloads"]),
    ]


def test_empty_groups_are_omitted():
    """No agents running means no AGENTS header.

    An empty group with a header reads as "the sidebar is broken" rather than
    "nothing is running", and it costs a row of a narrow panel.
    """
    result = snapshot([LIVE[0]])
    assert [g["name"] for g in result["groups"]] == ["SESSIONS"]


def test_job_column_is_shells_only():
    """jobName is what the terminal is actually doing -- but only for a shell.

    For an agent it names the foreground MCP child (the live capture had
    "node"/chrome-devtools-mcp for a Claude Code session), so an agent row
    carries no job at all rather than a misleading one.
    """
    agents, shells = snapshot(LIVE)["groups"]
    assert all("job" not in row for row in agents["rows"])
    assert [row["job"] for row in shells["rows"]] == ["nvim"]


# Two split panes of one tab, from the 2026-09-07 live Bridge smoke test. Both
# sit in the same cs directory, so both label as "claude-sessions".
SPLIT = [
    # tmux owns this pane's title, so it has no marker. It is still an agent
    # because it reports state -- which is exactly what separates it from a
    # plain shell sharing the same directory.
    {"session_id": "9C87CDF1-F37D-4B3A-BFB3-7D535FD17EBD", "window_id": WINDOW,
     "tab_id": "14", "window_index": 1, "tab_index": 5, "pane_index": 1,
     "path": "/Users/x/.claude-sessions/claude-sessions",
     "auto_name": "tmux", "job_name": None, "agent_state": "idle"},
    {"session_id": "657A9D1B-8D8F-4820-AA1C-FB5B19BD94D8", "window_id": WINDOW,
     "tab_id": "14", "window_index": 1, "tab_index": 5, "pane_index": 2,
     "path": "/Users/x/.claude-sessions/claude-sessions",
     "auto_name": "✳ general-purpose", "job_name": None},
]


def test_split_panes_sharing_a_label_are_still_distinguishable():
    """Live bug: the smoke test produced two identical "claude-sessions" rows.

    Indistinguishable rows mean clicking one can focus the other -- the
    entropy-of-trust failure this sidebar exists to avoid. Panes are numbered
    only when a tab actually has more than one.
    """
    rows = snapshot(SPLIT)["groups"][0]["rows"]
    assert [row["position"] for row in rows] == ["t5·1", "t5·2"]


def test_a_lone_pane_is_not_numbered():
    """A "·1" on every row is noise in a narrow panel."""
    lone = dict(SPLIT[0], tab_index=2, pane_index=1, session_id="only")
    assert snapshot([lone])["groups"][0]["rows"][0]["position"] == "t2"


def test_tab_position_is_an_index_not_iterm2s_tab_id():
    """tab_id is monotonic and unbounded -- the live capture had t27 across six
    tabs. A number that looks like a position and is not one is exactly the
    misleading display the design forbids.
    """
    assert snapshot([SPLIT[0]])["groups"][0]["rows"][0]["position"] == "t5"


def test_window_is_shown_only_when_there_is_more_than_one():
    """Tab indices restart per window, so t5 alone is ambiguous across windows.
    With one window the prefix is pure noise.
    """
    second = dict(SPLIT[0], window_index=2, window_id="pty-other", session_id="w2")
    positions = [r["position"] for r in snapshot([SPLIT[0], second])["groups"][0]["rows"]]
    assert positions == ["w1·t5", "w2·t5"]


def test_a_shell_with_no_foreground_job_shows_no_job_column():
    """Live: a new shell rendered "~  ?  t4·3".

    An idle shell has no foreground process, so iTerm2 reports no jobName. That
    is not the same as being unable to read it, and the two are
    indistinguishable from here -- both arrive as None. "?" asserts uncertainty
    that was never established; omitting the column asserts nothing.
    """
    idle = dict(LIVE[0], job_name=None)
    assert "job" not in snapshot([idle])["groups"][0]["rows"][0]


def test_a_shell_with_a_foreground_job_still_shows_it():
    assert snapshot([LIVE[0]])["groups"][0]["rows"][0]["job"] == "nvim"


def test_agent_rows_carry_state_colour_and_context():
    """State comes from the hook, colour from the cs session dir, context from
    user.claudeStatus. All three are optional -- a session with none of them is
    still a row.
    """
    row = dict(LIVE[1], agent_state="working", colour="orange", context=27)
    got = snapshot([row])["groups"][0]["rows"][0]
    assert (got["state"], got["colour"], got["context"]) == ("working", "orange", 27)


def test_rows_carry_the_task_the_session_reported():
    """What the session says it is doing, as the daemon read it; a session
    with no note has no key, never an empty one."""
    task = {"title": "Fix login", "activity": "Reading code", "percent": 35, "done": False,
            "reported_at": 1789000000}
    got = snapshot([dict(LIVE[1], task=task)])["groups"][0]["rows"][0]
    assert got["task"] == task
    assert "task" not in snapshot([dict(LIVE[1], task=None)])["groups"][0]["rows"][0]


def test_codex_rows_say_which_agent_they_are():
    row = dict(LIVE[1], agent_state="working", provider="openai", model="gpt-6-astra", effort="medium")
    got = snapshot([row])["groups"][0]
    assert got["name"] == "AGENTS"
    assert (got["rows"][0]["provider"], got["rows"][0]["model"]) == ("openai", "gpt-6-astra")


def test_claude_rows_carry_no_provider():
    """Claude rows are the default the page already draws, unmarked."""
    row = dict(LIVE[1], agent_state="working", provider="claude")
    assert "provider" not in snapshot([row])["groups"][0]["rows"][0]


def test_agent_rows_carry_their_subagents_and_when_they_blocked():
    row = dict(LIVE[1], agent_state="blocked", blocked_since=1789462240,
               subagents=[{"type": "Explore", "since": 50}])
    got = snapshot([row])["groups"][0]["rows"][0]
    assert got["blocked_since"] == 1789462240
    assert got["subagents"] == [{"type": "Explore", "since": 50}]


def test_agent_rows_carry_when_their_turn_began():
    row = dict(LIVE[1], agent_state="working", working_since=1789462000)
    assert snapshot([row])["groups"][0]["rows"][0]["working_since"] == 1789462000
    idle = dict(LIVE[1], agent_state="idle", working_since=None)
    assert "working_since" not in snapshot([idle])["groups"][0]["rows"][0]


def test_no_subagents_and_no_gate_are_absent():
    got = snapshot([dict(LIVE[1], agent_state="idle", blocked_since=None,
                         subagents=[])])["groups"][0]["rows"][0]
    assert "blocked_since" not in got and "subagents" not in got


def test_missing_signals_are_absent_rather_than_defaulted():
    """Same rule as the job column: a key that is not there asserts nothing, a
    key with a placeholder asserts something false. A session whose state we
    cannot read is not "idle".
    """
    got = snapshot([LIVE[1]])["groups"][0]["rows"][0]
    assert "state" not in got and "colour" not in got and "context" not in got


def test_shell_rows_get_colour_but_never_state_or_context():
    """A plain shell has no agent state and no context window. It can still sit
    in a cs session directory and carry that colour.

    No agent_state here on purpose: a terminal that reports one is an agent by
    definition, so a "shell with state" is not a thing that can exist.
    """
    got = snapshot([dict(LIVE[0], colour="cyan")])["groups"][0]["rows"][0]
    assert got["colour"] == "cyan"
    assert "state" not in got and "context" not in got


# Two sessions sharing one cs directory: a parent and a subagent. Captured live
# on 2026-09-07 -- "general-purpose" is a subagent type, not a session name.
FAMILY = [
    {"session_id": "parent", "window_id": WINDOW, "tab_id": "2",
     "window_index": 1, "tab_index": 2, "pane_index": 1,
     "path": "/Users/x/.claude-sessions/claude-sessions",
     "auto_name": "✳ claude-sessions", "job_name": None},
    # `team` is what makes this a teammate rather than a session that happens
    # to share the tab: it comes off its own transcript, where an ordinary
    # session carries none.
    {"session_id": "child", "window_id": WINDOW, "tab_id": "2",
     "window_index": 1, "tab_index": 2, "pane_index": 3,
     "path": "/Users/x/.claude-sessions/claude-sessions",
     "auto_name": "✳ general-purpose", "job_name": None,
     "team": "session-393d65ed"},
]


def test_sessions_sharing_a_directory_form_one_group():
    """A cs directory is one logical session however many panes it occupies.
    The first pane is the parent; later ones are its subagents.
    """
    rows = snapshot(FAMILY)["groups"][0]["rows"]
    assert [r["depth"] for r in rows] == [0, 1]


def test_a_subagent_is_labelled_by_what_it_is():
    """The parent keeps the directory name. A child is named by its agent type,
    which is the only thing distinguishing it -- calling it "claude-sessions"
    again would produce two identical rows.
    """
    rows = snapshot(FAMILY)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["claude-sessions", "general-purpose"]


def test_a_lone_session_is_not_indented():
    assert snapshot([FAMILY[0]])["groups"][0]["rows"][0]["depth"] == 0


def test_a_subagent_sits_next_to_its_own_parent():
    """Live bug: general-purpose lives in the claude-sessions directory, but an
    unrelated session was enumerated between the two, so the child rendered
    nested under the wrong parent. Depth without adjacency is a lie.
    """
    interloper = dict(FAMILY[0], session_id="other", pane_index=2,
                      path="/Users/x/.claude-sessions/delegate-try",
                      auto_name="✳ delegate-try")
    ordered = [FAMILY[0], interloper, FAMILY[1]]
    rows = snapshot(ordered)["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("claude-sessions", 0), ("general-purpose", 1), ("delegate-try", 0)]


def test_a_subagent_prefers_its_own_name_over_its_type():
    """Live: the pane reports name 'agy-executor (node ...)' while its title
    says '✳ general-purpose'. The name is what Claude Code shows on the
    teammate badge, and it identifies the agent; the type does not.
    """
    named = dict(FAMILY[1], session_name="agy-executor (node /path/to/thing)")
    rows = snapshot([FAMILY[0], named])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["claude-sessions", "agy-executor"]


def test_a_subagent_without_a_name_falls_back_to_its_type():
    rows = snapshot(FAMILY)["groups"][0]["rows"]
    assert rows[1]["label"] == "general-purpose"


def test_a_plain_shell_in_a_session_directory_is_not_a_subagent():
    """Live bug: a shell sitting in ~/.claude-sessions/atlas rendered nested under
    the atlas session, labelled with its own prompt title
    'x@macbook:~/.claude-sessions/atlas'.

    Sharing a directory is not enough. A subagent pane carries Claude Code's
    U+2733 marker or has reported a state; a shell has neither.
    """
    shell_pane = {
        "session_id": "shell", "window_id": WINDOW, "tab_id": "3",
        "window_index": 1, "tab_index": 3, "pane_index": 2,
        "path": "/Users/x/.claude-sessions/atlas",
        "auto_name": "zsh", "job_name": None,
        "session_name": "x@macbook:~/.claude-sessions/atlas",
    }
    parent = dict(FAMILY[0], path="/Users/x/.claude-sessions/atlas",
                  auto_name="✳ atlas", session_id="atlas")
    groups = {g["name"]: g["rows"] for g in snapshot([parent, shell_pane])["groups"]}
    assert [(r["label"], r["depth"]) for r in groups["AGENTS"]] == [("atlas", 0)]
    # And it is not an agent at all: a path says which directory a terminal is
    # in, not what is running there.
    assert [r["label"] for r in groups["SESSIONS"]] == ["/Users/x/.claude-sessions/atlas"]


def test_an_orphan_subagent_is_shown_flat_rather_than_guessed_at():
    """Accepted limitation, recorded rather than hidden.

    If a subagent's parent has not reported state yet, the parent is listed as
    a shell and the subagent has no family to join. It then renders flat under
    the directory name instead of nested.

    The alternative -- treating any marked pane whose title differs from its
    current directory as a subagent -- was tried and was worse: a session that
    cd's into a subdirectory became a child of itself. This resolves on its own
    the moment the parent reports, which every live session does.
    """
    orphan = dict(FAMILY[1], session_name="agy-executor (node /x)")
    rows = snapshot([orphan])["groups"][0]["rows"]
    # Flat, and named by its own marked title rather than the directory it
    # happens to share with a parent that has not reported.
    assert [(r["label"], r["depth"]) for r in rows] == [("general-purpose", 0)]


def test_a_session_that_cd_s_elsewhere_is_not_a_subagent_of_itself():
    """Live regression: comparing a pane's title to its CURRENT directory
    basename broke the moment a session cd'd into a subdirectory -- orchard
    working in ~/.claude-sessions/orchard/src became a child of nothing,
    labelled with its own name string.

    A subagent is a marked pane that differs from the PARENT already listed in
    that family, not one that differs from wherever it happens to be standing.
    """
    wandered = {
        "session_id": "orchard", "window_id": WINDOW, "tab_id": "1",
        "window_index": 1, "tab_index": 1, "pane_index": 1,
        "path": "/Users/x/.claude-sessions/orchard/src/deep",
        "auto_name": "✳ orchard", "job_name": None,
        "session_name": "cs: orchard (python /x)", "agent_state": "idle",
    }
    rows = snapshot([wandered])["groups"][0]["rows"]
    # Labelled from its marked title, so the cd does not rename it either.
    assert [(r["label"], r["depth"]) for r in rows] == [("orchard", 0)]


def _agent(**over):
    base = {"session_id": "s0", "window_id": "w", "tab_id": "t",
            "window_index": 0, "tab_index": 0, "pane_index": 0,
            "path": "/Users/x/.claude-sessions/demo", "auto_name": "✳ demo",
            "session_name": "cs: demo", "job_name": None,
            "agent_state": "working", "agents": 2, "context": 30,
            "model": "Opus 5", "colour": None, "branch": None}
    base.update(over)
    return base


def test_subagents_are_reported_without_a_branch():
    """The count was nested under the branch check, so a session whose HEAD
    could not be read lost its subagents too. The two facts are unrelated.
    """
    row = snapshot([_agent(branch=None)])["groups"][0]["rows"][0]
    assert row["agents"] == 2


def test_a_session_reports_its_open_shells():
    shells = [{"label": "npm test", "command": "cd ~/repo && npm test"}]
    row = snapshot([_agent(shells=shells)])["groups"][0]["rows"][0]
    assert row["shells"] == [{"label": "npm test", "command": "cd ~/repo && npm test"}]


def test_no_shells_is_not_reported_at_all():
    """Absent rather than zero, like every other optional signal here."""
    assert "shells" not in snapshot([_agent(shells=[])])["groups"][0]["rows"][0]


def test_a_session_reports_when_it_started():
    """The moment, not the elapsed time: an age would change on every
    rebuild and push a frame the page has no reason to redraw."""
    row = snapshot([_agent(started_at=1789638277)])["groups"][0]["rows"][0]
    assert row["started_at"] == 1789638277


def test_a_session_started_at_the_epoch_still_reports_it():
    """Zero is a real answer here, unlike zero shells. Falsy checks would
    drop it and the row would claim not to know.
    """
    assert snapshot([_agent(started_at=0)])["groups"][0]["rows"][0]["started_at"] == 0


def test_an_unreadable_title_does_not_take_down_the_other_sessions():
    """Bridge stores None for any variable iTerm2 refuses, so auto_name can be
    None -- and dict.get's default does not apply to a key that is present.
    One such session used to raise AttributeError out of snapshot(), which
    left the whole panel with no data at all rather than one row reading "?".
    """
    unreadable = {
        "session_id": "0FA8C3E4-1B72-4A55-9C0D-2E6B4F118D93",
        "window_id": WINDOW, "tab_id": "31",
        "window_index": 1, "tab_index": 7, "pane_index": 1,
        "path": None, "auto_name": None, "job_name": None,
    }
    result = snapshot(LIVE + [unreadable])
    labels = [r["label"] for g in result["groups"] for r in g["rows"]]
    assert labels == ["iterm-agents-sidebar", "orchard", "/Users/x/Downloads", "?"]


def test_two_sessions_in_one_repo_are_not_parent_and_child():
    """Live 2026-09-08: `cs: beacon` rendered nested under `atlas`. They share a
    window and a working directory and nothing else -- atlas in tab 1, beacon
    in tab 2, two cs sessions that happen to be open on the same repo.

    Sharing a directory was the whole test for parentage, and a directory is
    the one thing two unrelated sessions most often share. A pane spawned by an
    agent is a split of that agent's own tab, so the tab is what makes them a
    family.
    """
    here = "/Users/x/.claude-sessions/atlas"
    atlas = {"session_id": "A8246470", "window_id": WINDOW, "tab_id": "2",
           "window_index": 1, "tab_index": 1, "pane_index": 2,
           "path": here, "auto_name": "✳ atlas", "job_name": None}
    beacon = {"session_id": "18A6993D", "window_id": WINDOW, "tab_id": "3",
                "window_index": 1, "tab_index": 2, "pane_index": 1,
                "path": here, "auto_name": "✳ cs: beacon", "job_name": None}
    rows = snapshot([atlas, beacon])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [("atlas", 0), ("cs: beacon", 0)]


def test_a_split_pane_beside_its_agent_is_still_a_child():
    """The other half of the rule: same tab, same directory, marked title. That
    is what a spawned pane looks like, and it must keep nesting.
    """
    rows = snapshot(FAMILY)["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("claude-sessions", 0), ("general-purpose", 1)]


def test_the_same_directory_in_another_window_is_not_a_family():
    """Two windows on one repo is the same mistake with more distance."""
    here = "/Users/x/.claude-sessions/claude-sessions"
    elsewhere = dict(FAMILY[1], window_id="pty-OTHER", window_index=2,
                     tab_id="9", tab_index=1, pane_index=1)
    rows = snapshot([FAMILY[0], elsewhere])["groups"][0]["rows"]
    assert [r["depth"] for r in rows] == [0, 0]


def test_a_session_reports_its_effort_level():
    row = snapshot([_agent(effort="xhigh")])["groups"][0]["rows"][0]
    assert row["effort"] == "xhigh"


def test_an_unknown_effort_is_not_reported_at_all():
    assert "effort" not in snapshot([_agent(effort=None)])["groups"][0]["rows"][0]


def _terminal(job):
    return {"session_id": "t0", "window_id": "w", "tab_id": "t",
            "window_index": 0, "tab_index": 0, "pane_index": 0,
            "path": "/Users/x/src/app", "auto_name": "app", "session_name": "app",
            "job_name": job, "agent_state": None}


def test_a_terminal_running_a_command_says_so():
    row = snapshot([_terminal("npm")])["groups"][0]["rows"][0]
    assert row["job"] == "npm"
    assert row["running"] is True


def test_a_terminal_at_its_prompt_is_not_running_anything():
    """At a prompt the foreground process is the shell itself, which is not a
    command anyone ran. Showing "zsh" beside a row would read as busy."""
    for shell in ("zsh", "-zsh", "bash", "fish", "sh"):
        row = snapshot([_terminal(shell)])["groups"][0]["rows"][0]
        assert "running" not in row and "job" not in row, shell


def test_a_terminal_whose_job_cannot_be_read_claims_nothing():
    row = snapshot([_terminal(None)])["groups"][0]["rows"][0]
    assert "running" not in row and "job" not in row


def test_a_shell_carries_the_title_its_tab_was_given():
    """Live: a tab titled "erp-jdoe-mac" by hand, in
    ~/.claude-sessions/iterm-agents-sidebar, where iTerm2's autoName had
    shrunk to "..gents-sidebar". The title is how its owner tells it apart.
    """
    named = dict(LIVE[0], session_name="erp-jdoe-mac", auto_name="..gents-sidebar")
    assert snapshot([named])["groups"][0]["rows"][0]["title"] == "erp-jdoe-mac"


def test_a_shell_whose_title_is_just_its_shell_or_path_has_none():
    """zsh's default title is user@host:path, and iTerm2's autoName is the
    shell's name; neither says anything the row does not already."""
    default = dict(LIVE[0], session_name="x@macbook:~/Downloads", auto_name="zsh")
    assert "title" not in snapshot([default])["groups"][0]["rows"][0]
    plain = dict(LIVE[0], session_name="zsh", auto_name="zsh")
    assert "title" not in snapshot([plain])["groups"][0]["rows"][0]


TEAM = [
    {"session_id": "lead", "window_id": WINDOW, "tab_id": "50",
     "window_index": 1, "tab_index": 3, "pane_index": 1,
     "path": "/Users/x/.claude-sessions/fignity",
     "auto_name": "✳ fignity", "job_name": None,
     "claude_session": "6a4d1211-632c-4c8e-9c0a-000000000001"},
    # Spawned into a subdirectory of its lead's, in a split of the same tab.
    # Its process names its lead outright with --parent-session-id.
    {"session_id": "reviewer", "window_id": WINDOW, "tab_id": "50",
     "window_index": 1, "tab_index": 3, "pane_index": 3,
     "path": "/Users/x/.claude-sessions/fignity/fignity-project",
     "auto_name": "✳ feature-dev:code-reviewer", "job_name": None,
     "team": "session-0da70176", "agent_name": "review-351",
     "parent_session": "6a4d1211-632c-4c8e-9c0a-000000000001"},
]


def test_a_teammate_nests_under_the_lead_it_names_wherever_it_runs():
    """Live, 2026-09-16: a code-reviewer teammate ran in fignity/fignity-project
    while its lead sat in fignity, and the directory rule left it top-level,
    labelled by its type. The process says who its parent is; that beats
    any resemblance."""
    rows = snapshot(TEAM)["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [("fignity", 0), ("review-351", 1)]


def test_a_teammate_enumerated_before_its_lead_still_sits_under_it():
    rows = snapshot([TEAM[1], TEAM[0]])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [("fignity", 0), ("review-351", 1)]


def test_a_teammate_whose_lead_is_not_listed_stays_flat():
    orphan = dict(TEAM[1], parent_session="not-here")
    rows = snapshot([TEAM[0], orphan])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [("fignity", 0), ("review-351", 0)]


def test_a_blocked_row_carries_what_it_is_asking():
    """The notice offers the question's options as buttons, so the row has to
    carry the question itself, not only that there is one."""
    asked = {"header": "Icon", "question": "Which icon?", "options": ["Dots"], "multi": False, "more": 0}
    row = dict(LIVE[1], agent_state="blocked", blocked_since=1789462240, question=asked)
    assert snapshot([row])["groups"][0]["rows"][0]["question"] == asked
    quiet = dict(LIVE[1], agent_state="working", question=None)
    assert "question" not in snapshot([quiet])["groups"][0]["rows"][0]


MAIN = {"session_id": "atlas", "window_id": WINDOW, "tab_id": "60",
        "window_index": 1, "tab_index": 4, "pane_index": 1,
        "path": "/Users/x/.claude-sessions/atlas",
        "auto_name": "✳ atlas", "job_name": None, "branch": "main"}
LINKED = {"session_id": "atlas-wt", "window_id": WINDOW, "tab_id": "61",
          "window_index": 1, "tab_index": 5, "pane_index": 1,
          "path": "/Users/x/.claude-sessions/atlas@worktree",
          "auto_name": "✳ atlas@worktree", "job_name": None,
          "branch": "cs/worktree", "worktree_of": "/Users/x/.claude-sessions/atlas"}
OTHER = {"session_id": "beacon", "window_id": WINDOW, "tab_id": "62",
         "window_index": 1, "tab_index": 6, "pane_index": 1,
         "path": "/Users/x/.claude-sessions/beacon",
         "auto_name": "✳ beacon", "job_name": None, "branch": "main"}


def test_a_worktree_session_follows_the_session_whose_repo_it_is_and_is_named_by_its_feature():
    """Asked on 2026-09-16 about a cs feature session in `<repo>@worktree`: not a
    teammate, "it should stay under the main session like a different
    session but maybe add a visual connection line between them". Named
    by the feature, the part after the `@` in cs's directory name: "we are
    only interested in the feature name which is worktree, the branch is
    already there". So: its own card, right after the main one, tied to it."""
    rows = snapshot([MAIN, OTHER, LINKED])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("atlas", 0), ("worktree", 0), ("beacon", 0)]
    assert rows[1]["worktree_of"] == "atlas"
    assert "worktree_of" not in rows[0]


def test_a_worktree_session_waits_for_the_main_session_teammates():
    rows = snapshot([TEAM[0], OTHER, TEAM[1],
                     dict(LINKED, worktree_of=TEAM[0]["path"])])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("fignity", 0), ("review-351", 1), ("worktree", 0), ("beacon", 0)]


def test_a_worktree_session_in_a_plain_directory_is_named_by_its_branch():
    """No `@` to read a feature from: the branch is the next best name."""
    plain = dict(LINKED, path="/Users/x/src/atlas-wt", auto_name="✳ atlas-wt")
    rows = snapshot([MAIN, plain])["groups"][0]["rows"]
    assert rows[1]["label"] == "cs/worktree"


def test_a_worktree_session_whose_main_session_is_not_open_keeps_its_place_and_name():
    rows = snapshot([OTHER, LINKED])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["beacon", "atlas@worktree"]
    assert "worktree_of" not in rows[1]


def test_cards_keep_the_terminal_order_unless_asked_for_names():
    """The default is the order iTerm2 enumerates windows, tabs and panes, so
    a card sits where its terminal does."""
    rows = snapshot([OTHER, MAIN])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["beacon", "atlas"]


def test_sorting_by_name_orders_the_top_level_cards():
    rows = snapshot([OTHER, MAIN], sort_by_name=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "beacon"]


def test_sorting_by_name_keeps_a_teammate_under_its_lead():
    """Sorting the rows flat would scatter children away from their parent,
    and an indent under an unrelated row is a lie the eye believes."""
    rows = snapshot([TEAM[0], TEAM[1], MAIN], sort_by_name=True)["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("atlas", 0), ("fignity", 0), ("review-351", 1)]


def test_sorting_by_name_keeps_a_worktree_docked_to_its_session():
    rows = snapshot([OTHER, MAIN, LINKED], sort_by_name=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "worktree", "beacon"]


def test_sorting_by_name_ignores_case():
    upper = dict(OTHER, session_id="Zephyr", path="/Users/x/.claude-sessions/Anvil",
                 auto_name="✳ Anvil")
    rows = snapshot([MAIN, upper], sort_by_name=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["Anvil", "atlas"]


def test_sorting_by_name_survives_a_nested_row_with_nothing_above_it():
    """Both placement rules put a child after its parent, so a leading nested
    row should be impossible; sorting is not the place to find out otherwise.
    With no card above it to belong to, it sorts as a card of its own."""
    assert [r["label"] for r in by_name([{"label": "orphan", "depth": 1},
                                         {"label": "atlas", "depth": 0}])] == ["atlas", "orphan"]


def test_a_codex_terminal_is_a_card_with_its_provider_and_no_state():
    """Before its first prompt a Codex TUI has published nothing, so the card
    says which agent it is and claims nothing about what it is doing."""
    groups = snapshot([{
        "session_id": "0D3E6F55-0000-4000-8000-000000000001",
        "window_id": WINDOW, "tab_id": "9",
        "window_index": 1, "tab_index": 2, "pane_index": 1,
        "path": "/Users/x/work/repo", "auto_name": "zsh", "job_name": "codex",
        "agent_job": True, "provider": "openai",
    }])["groups"]
    [group] = [g for g in groups if g["rows"]]
    [row] = group["rows"]
    assert group["name"] == "AGENTS"
    assert (row["label"], row["provider"]) == ("repo", "openai")
    assert "state" not in row and "job" not in row


def test_a_lead_counts_the_teammates_working_under_it():
    """A teammate runs in its own pane with its own state, so a lead can read
    idle while work goes on under it. The count says so without the lead
    claiming to be working itself."""
    from sidebar import mark_busy_teammates
    rows = [{"depth": 0, "state": "idle"}, {"depth": 1, "state": "working"},
            {"depth": 1, "state": "idle"}, {"depth": 0, "state": "working"},
            {"depth": 1, "state": "working"}, {"depth": 0, "state": "idle"}]
    mark_busy_teammates(rows)
    assert [r.get("busy_kids") for r in rows] == [1, None, None, 1, None, None]


def omp_card(state):
    [row] = [r for g in snapshot([{
        "session_id": "0D3E6F55-0000-4000-8000-000000000002",
        "window_id": WINDOW, "tab_id": "9",
        "window_index": 1, "tab_index": 2, "pane_index": 1,
        "path": "/Users/x/work/repo", "auto_name": "π > Fix login", "job_name": "bun",
        "provider": "omp", "agent_state": state, "topic": "Fix login", "doing": "Validate shell scripts",
    }])["groups"] for r in g["rows"]]
    return row


def test_an_omp_card_says_what_its_session_is_about_and_what_it_is_doing():
    """omp names each session in its title and states each tool's intent. Both are the
    agent's live word, not a task note: no age to go stale by, no estimate."""
    row = omp_card("working")
    assert (row["topic"], row["doing"]) == ("Fix login", "Validate shell scripts")
    assert "task" not in row


def test_an_omp_card_at_rest_does_not_say_it_is_doing_something():
    """The last intent stands in omp's log while it waits for the next
    prompt; on a card that reads as work going on."""
    row = omp_card("idle")
    assert row["topic"] == "Fix login" and "doing" not in row


def of(provider, base, **changes):
    return dict(base, provider=provider, agent_state="idle", **changes)


def test_grouping_by_agent_gathers_each_agents_cards_and_keeps_their_order():
    """Claude first, then the others in a fixed order, so a group does not
    move when a session of another agent opens above it."""
    third = dict(OTHER, session_id="comet", tab_id="63", tab_index=7,
                 path="/Users/x/.claude-sessions/comet", auto_name="✳ comet")
    rows = snapshot([of("omp", OTHER), MAIN, of("openai", third), of("omp", dict(third, session_id="dune",
                     path="/Users/x/.claude-sessions/dune", auto_name="✳ dune", tab_id="64", tab_index=8))],
                    group_by_provider=True)["groups"][0]["rows"]
    assert [(r["label"], r.get("provider", "claude")) for r in rows] == [
        ("atlas", "claude"), ("comet", "openai"), ("beacon", "omp"), ("dune", "omp")]


def test_grouping_by_agent_keeps_a_worktree_docked_to_its_session():
    rows = snapshot([of("omp", OTHER), MAIN, LINKED], group_by_provider=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "worktree", "beacon"]


def test_grouping_by_agent_and_sorting_by_name_sort_inside_each_group():
    zed = dict(OTHER, session_id="zed", tab_id="65", tab_index=9, path="/Users/x/.claude-sessions/zed",
               auto_name="✳ zed")
    rows = snapshot([zed, of("omp", OTHER), MAIN], sort_by_name=True,
                    group_by_provider=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "zed", "beacon"]


def test_an_agent_the_order_does_not_name_comes_after_the_ones_it_does():
    rows = snapshot([of("goose", OTHER), MAIN], group_by_provider=True)["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "beacon"]


def test_agent_rows_carry_their_open_tasks_only_when_there_are_some():
    tasks = [{"id": "3", "status": "pending", "subject": "Registry flags", "doing": ""}]
    got = snapshot([dict(LIVE[1], agent_state="working", tasks=tasks)])["groups"][0]["rows"][0]
    assert got["tasks"] == tasks
    bare = snapshot([dict(LIVE[1], agent_state="working", tasks=[])])["groups"][0]["rows"][0]
    assert "tasks" not in bare


def test_a_session_named_base_at_feature_follows_the_base_session_by_name_when_git_says_nothing():
    """Seen 2026-09-22 on another machine: `freya` and `freya@s3` side by side
    as strangers, because the worktree's `.git` did not resolve to the path
    the `freya` shell reported. The cs name says which project it is: a
    directory `<base>@<feature>` beside a session directory `<base>` docks
    there, and only there -- a `<base>` in another folder is another project."""
    by_name = dict(LINKED, worktree_of=None)
    rows = snapshot([MAIN, OTHER, by_name])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("atlas", 0), ("worktree", 0), ("beacon", 0)]
    assert rows[1]["worktree_of"] == "atlas"
    elsewhere = dict(MAIN, path="/Users/x/other/atlas", session_id="atlas-2")
    rows = snapshot([elsewhere, by_name])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "atlas@worktree"]
    assert "worktree_of" not in rows[1]


def test_the_models_that_decide_switching_are_those_claude_sessions_and_their_subagents_run():
    from sidebar import running_models
    snap = {"groups": [
        {"name": "AGENTS", "rows": [
            {"state": "working", "model": "Opus 5.5",
             "subagents": [{"model": "claude-fable-5-1"}, {"model": None, "provider": "codex"}]},
            {"state": "idle", "model": "gpt-6", "provider": "codex"},
            {"state": "idle", "model": "Sonnet 5", "provider": "claude"}]},
        {"name": "SESSIONS", "rows": [{"label": "zsh"}]}]}
    assert running_models(snap) == {"opus", "fable", "sonnet"}


def test_a_claude_session_whose_model_is_not_known_yet_leaves_every_limit_deciding():
    from sidebar import running_models
    snap = {"groups": [{"name": "AGENTS", "rows": [{"state": "working", "model": "Opus 5.5"},
                                                   {"state": "working"}]}]}
    assert running_models(snap) is None
    assert running_models({"groups": []}) == set()


def test_an_exited_session_runs_no_model():
    """Its process is gone, and the statusline file that named its model
    goes with it: counted, it would leave every limit deciding."""
    from sidebar import running_models
    snap = {"groups": [{"name": "AGENTS", "rows": [{"state": "working", "model": "Opus 5.5"},
                                                   {"state": "exited", "model": "Fable 5.1"},
                                                   {"state": "exited"}]}]}
    assert running_models(snap) == {"opus"}


def test_a_finished_subagent_does_not_count_and_a_running_one_without_a_model_is_unknown():
    from sidebar import running_models
    finished = {"groups": [{"name": "AGENTS", "rows": [
        {"state": "working", "model": "Opus 5.5", "subagents": [{"model": "claude-fable-5-1", "ended": 1790000000}]}]}]}
    assert running_models(finished) == {"opus"}
    blind = {"groups": [{"name": "AGENTS", "rows": [
        {"state": "working", "model": "Opus 5.5", "subagents": [{"model": None, "ended": None}]}]}]}
    assert running_models(blind) is None
