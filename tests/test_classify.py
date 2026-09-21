"""Tests for classify().

Every expected value here comes from real iTerm2 session data captured by the
spike on 2026-09-07, not from re-running classify's own logic. Where a case did
not occur live, the test says so.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import agent_name, classify


def test_cs_session_running_claude_code():
    """Live capture: the session this was developed in.

    iTerm2 reported path=/Users/x/.claude-sessions/iterm-agents-sidebar
    and autoName="✳ iterm-agents-sidebar". Note jobName was "node"
    (chrome-devtools-mcp) -- which is exactly why jobName is not the detector.
    """
    assert classify(
        "/Users/x/.claude-sessions/iterm-agents-sidebar",
        "✳ iterm-agents-sidebar",
    ) == ("agent", "iterm-agents-sidebar")


def test_claude_code_outside_a_cs_session_dir():
    """Spec literal, not a live capture.

    Every agent session in the 2026-09-07 spike happened to sit under
    ~/.claude-sessions, so this case did not occur in the data. It is still
    real: Claude Code run straight from a project checkout has no cs dir, and
    only the U+2733 marker iTerm2 reports in autoName identifies it.
    """
    assert classify(
        "/Users/x/src/acme",
        "✳ acme",
    ) == ("agent", "acme")


def test_cs_session_whose_title_tmux_stole():
    """Live capture: session 9C87CDF1 in the 2026-09-07 spike.

    path=/Users/x/.claude-sessions/claude-sessions but autoName was
    plain "tmux" -- Claude Code running inside tmux, and tmux owns the title.
    The U+2733 marker is absent. The path alone is NOT enough -- a shell cd'd
    into a session directory has the same path and is not an agent -- so what
    identifies this one is that it has reported a state, which only a running
    Claude session does.
    """
    assert classify(
        "/Users/x/.claude-sessions/claude-sessions",
        "tmux",
        agent_state="idle",
    ) == ("agent", "claude-sessions")


def test_the_marked_title_names_the_session_not_the_folder():
    """Supersedes an earlier rule that took the label from the path basename.

    Live: the orchard session cd'd into ~/.claude-sessions/chezmoi -- another
    session's directory -- and was listed as "chezmoi". A cwd says where a
    terminal is standing; Claude Code's marked title says which session it is,
    and that survives any cd.

    A subagent pane's title names the agent rather than the session, which is
    what its row wants anyway, so snapshot relabels children separately.
    """
    assert classify(
        "/Users/x/.claude-sessions/chezmoi", "✳ orchard",
    ) == ("agent", "orchard")


def test_an_unmarked_agent_still_falls_back_to_its_folder():
    """tmux ate the title, so there is nothing to read it from."""
    assert classify(
        "/Users/x/.claude-sessions/claude-sessions", "tmux",
        agent_state="idle",
    ) == ("agent", "claude-sessions")


def test_plain_shell_in_the_home_directory():
    """Spec literal: no plain shell existed in the live spike data.

    The path basename of the home directory is the username, which reads as a
    person rather than a place. Home renders as "~".
    """
    assert classify(str(Path.home()), "zsh") == ("shell", "~")


def test_an_unreadable_cwd_still_has_a_name_when_the_title_gives_one():
    """iTerm2 returns None for a variable it cannot resolve.

    An earlier version rendered "?" here, because the path was the only source
    of a label. It is not: the marked title names the session, and reading it
    is not a guess -- it is Claude Code stating which session this is. "?"
    remains the answer only when nothing at all is readable, which the next
    test covers.
    """
    assert classify(None, "✳ iterm") == ("agent", "iterm")


def test_unreadable_cwd_and_title_is_still_a_row():
    """Both variables missing. The session exists and must still be listed --
    dropping it would be a silent lie about what is running.
    """
    assert classify(None, None) == ("shell", "?")


def test_a_shell_sitting_in_a_session_directory_is_not_an_agent():
    """Live bug: a shell in ~/.claude-sessions/atlas was listed as an agent and
    nested under the atlas session.

    A path says which directory you are in, not what is running there.
    """
    assert classify(
        "/Users/x/.claude-sessions/atlas", "zsh",
    ) == ("shell", "/Users/x/.claude-sessions/atlas")


def test_the_agent_marker_is_not_part_of_the_name():
    """Claude Code prefixes a subagent pane's title with the marker. A row
    reading "* general-purpose" is showing punctuation as if it were a name.
    Seen live 2026-09-07 on a general-purpose subagent under atlas.
    """
    assert agent_name("✳ general-purpose") == "general-purpose"
    assert agent_name("✳ general-purpose (node /path/mcp)") == "general-purpose"


def test_a_name_without_the_marker_is_unchanged():
    assert agent_name("agy-executor (node /path/mcp)") == "agy-executor"
    assert agent_name("cs: atlas") == "cs: atlas"


def test_a_plain_shell_is_named_by_its_path_with_home_as_tilde():
    """A terminal is a place. Its prompt shows the path from home, and the
    row says the same thing the prompt does. Live: a shell at
    ~/.claude-sessions/iterm-agents-sidebar rendered as "iterm-agents-sidebar",
    which is also the name of the agent card above it.
    """
    assert classify(str(Path.home() / "src" / "acme"), "zsh") == ("shell", "~/src/acme")


def test_a_terminal_running_codex_is_an_agent_before_it_reports():
    """Codex creates its session at the first prompt, so a TUI sitting at its
    prompt publishes nothing; the process is still evidence enough for a card,
    and the state badge stays away until a hook speaks. Measured on
    codex-cli 0.155 on 2026-09-18."""
    assert classify("/Users/x/work/repo", "zsh", None, agent_job=True) == ("agent", "repo")
    assert classify("/Users/x/work/repo", "zsh", None) == ("shell", "/Users/x/work/repo")


def test_an_omp_title_says_what_the_session_is_doing():
    """omp writes its state into the title itself: `π > label` at the user's
    turn, `π ! label` while an approval or a question waits, and a spinner
    frame between the two while it works (omp 18.2.5,
    src/utils/title-generator.ts). The working title is a live capture from
    2026-09-21, its label swapped for a plain one."""
    from sidebar import omp_title_state
    assert omp_title_state("π > Fix login") == "idle"
    assert omp_title_state("π ⠋ Fix login") == "working"
    assert omp_title_state("π ! Fix login") == "blocked"


def test_an_omp_title_without_a_label_still_carries_the_state():
    from sidebar import omp_title_state
    assert omp_title_state("π >") == "idle"
    assert omp_title_state("π !") == "blocked"
    assert omp_title_state("π ⠹") == "working"


def test_the_working_mark_is_whatever_is_not_one_of_the_other_two():
    """The spinner's frames are a setting, and a host that cannot animate gets
    a colon, so working is read by elimination."""
    from sidebar import omp_title_state
    assert omp_title_state("π : Fix login") == "working"
    assert omp_title_state("π ◐ Fix login") == "working"


def test_an_omp_title_with_its_states_switched_off_is_omp_doing_something_unknown():
    from sidebar import omp_title_state
    assert omp_title_state("π: Fix login") == "unknown"
    assert omp_title_state("π") == "unknown"


def test_a_title_that_is_not_omps_says_nothing():
    from sidebar import omp_title_state
    assert omp_title_state("✳ iterm-agents-sidebar") is None
    assert omp_title_state("πthon notes") is None
    assert omp_title_state("zsh") is None
    assert omp_title_state("") is None
    assert omp_title_state(None) is None


def test_an_omp_title_names_what_the_session_is_about():
    from sidebar import omp_title_topic
    assert omp_title_topic("π > Fix login") == "Fix login"
    assert omp_title_topic("π ⠋ Fix the login page") == "Fix the login page"
    assert omp_title_topic("π: Fix login") == "Fix login"


def test_an_omp_title_with_no_label_names_nothing():
    from sidebar import omp_title_topic
    assert omp_title_topic("π >") is None
    assert omp_title_topic("π") is None
    assert omp_title_topic("zsh") is None
    assert omp_title_topic(None) is None
