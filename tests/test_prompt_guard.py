# ABOUTME: Guards the prompt verb: text meant as an agent's next input is refused where it cannot land.
# ABOUTME: A waiting prompt would take the text as its answer, a gone or exited agent leaves a shell, and a
# ABOUTME: program in front of the agent (outside its tty's foreground group) would take the text instead.
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar import prompt_refusal


def test_a_session_the_panel_no_longer_lists_is_refused():
    assert prompt_refusal(None) == "the session has gone"


def test_a_session_waiting_on_you_is_refused():
    """A waiting prompt would take the text as its answer."""
    assert prompt_refusal({"session_id": "abc", "state": "blocked"}) == "it is waiting on you"


def test_a_session_whose_agent_has_exited_is_refused():
    """The pane is back at a shell, which would run the text as a command."""
    assert prompt_refusal({"session_id": "abc", "state": "exited"}) == "the agent has exited"


@pytest.mark.parametrize("state", ["working", "idle", "unknown", None])
def test_a_session_at_its_own_prompt_or_mid_turn_takes_the_text(state):
    """Mid-turn the agent queues it. A Codex pane that has published no state
    yet has no state key at all, and is still the agent's own prompt."""
    row = {"session_id": "abc"} if state is None else {"session_id": "abc", "state": state}
    assert prompt_refusal(row) is None


def test_a_session_with_another_program_in_front_of_its_agent_is_refused():
    """The text would go to that program, not the agent."""
    assert prompt_refusal({"session_id": "abc", "state": "idle", "in_front": "nvim"}) == "nvim is in front"


@pytest.mark.parametrize("state,reason", [("blocked", "it is waiting on you"),
                                          ("exited", "the agent has exited")])
def test_a_waiting_or_exited_agent_is_refused_for_that_whatever_is_in_front(state, reason):
    """The agent's own state is what the person can act on."""
    assert prompt_refusal({"session_id": "abc", "state": state, "in_front": "zsh"}) == reason


class Pane:
    """An iTerm2 session that records what is typed into it."""
    def __init__(self):
        self.typed = []

    async def async_send_text(self, text):
        self.typed.append(text)


class App:
    def __init__(self, pane):
        self.pane = pane

    def get_session_by_id(self, session_id):
        return self.pane if session_id == "abc" else None


class Quiet:
    def broadcast(self, frame):
        pass


def bridge_over(monkeypatch, tmp_path, state):
    """A Bridge whose last rebuild lists "abc" in that state, over one pane."""
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    b = sidebar.Bridge(None, Quiet())
    b.app = App(Pane())
    b.latest = {"groups": [{"name": "AGENTS", "rows": [{"session_id": "abc", "state": state}]}]}
    return b


def test_a_prompt_that_reaches_the_daemon_after_the_agent_began_waiting_types_nothing(monkeypatch, tmp_path):
    """The server checked a rebuild ago, and a notice's Reply is not checked
    there at all; the daemon checks again before typing, and says why."""
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    asyncio.run(b.act("abc", "prompt", "run the tests\n"))
    assert b.app.pane.typed == []
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == "prompt refused abc it is waiting on you\n"


def test_a_prompt_to_an_idle_agent_is_typed_with_enter_on_its_own(monkeypatch, tmp_path):
    b = bridge_over(monkeypatch, tmp_path, "idle")
    asyncio.run(b.act("abc", "prompt", "/compact\n"))
    assert b.app.pane.typed == ["/compact", "\r"]


def test_a_prompt_to_a_closed_pane_is_logged_as_refused(monkeypatch, tmp_path):
    """A notice's Reply can outlive its pane; the refusal reaches daemon.log,
    not only the Script Console, which a shell cannot read."""
    b = bridge_over(monkeypatch, tmp_path, "idle")
    b.latest = {"groups": [{"name": "AGENTS", "rows": []}]}
    asyncio.run(b.act("gone1234", "prompt", "run the tests\n"))
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == "prompt refused gone1234 the session has gone\n"


def test_a_prompt_to_a_pane_whose_agent_has_left_types_nothing(monkeypatch, tmp_path):
    """A notice's Reply to a finished turn can arrive after the agent exited
    and its pane became a plain shell row, which would run the text."""
    b = bridge_over(monkeypatch, tmp_path, "idle")
    b.latest = {"groups": [{"name": "AGENTS", "rows": []},
                           {"name": "SESSIONS", "rows": [{"session_id": "abc", "label": "zsh"}]}]}
    asyncio.run(b.act("abc", "prompt", "run the tests\n"))
    assert b.app.pane.typed == []
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == "prompt refused abc no agent runs there\n"


#: `ps -ww -eo pid=,ppid=,pgid=,tpgid=,tty=,lstart=,%cpu=,rss=,args=` in the
#: shapes measured 2026-10-05: a Claude under a `cs` bash wrapper (bash leads
#: the foreground group, Claude is a member), and a Claude whose pane has an
#: editor in front of it.
GROUPS_PS = """\
 8000     1  8000  8001 ttys006 Mon Oct  5 09:00:00 2026 0.0 0 -zsh
 8001  8000  8001  8001 ttys006 Mon Oct  5 09:00:01 2026 0.0 0 bash /Users/x/.local/bin/cs atlas
 8002  8001  8001  8001 ttys006 Mon Oct  5 09:00:02 2026 0.0 0 /Users/x/.local/bin/claude
 9000     1  9000  9200 ttys007 Mon Oct  5 09:00:00 2026 0.0 0 -zsh
 9100  9000  9100  9200 ttys007 Mon Oct  5 09:00:01 2026 0.0 0 /Users/x/.local/bin/claude
 9200  9100  9200  9200 ttys007 Mon Oct  5 09:00:02 2026 0.0 0 nvim /tmp/claude-prompt.md
 7000     1  7000  7000 ttys008 Mon Oct  5 09:00:00 2026 0.0 0 -zsh
 7100  7000  7100  7000 ttys008 Mon Oct  5 09:00:01 2026 0.0 0 /Users/x/.local/bin/claude
 6000     1  6000  6500 ttys009 Mon Oct  5 09:00:00 2026 0.0 0 -zsh
 6100  6000  6100  6500 ttys009 Mon Oct  5 09:00:01 2026 0.0 0 /Users/x/.local/bin/claude
 6600  6000  6500  6500 ttys009 Mon Oct  5 09:00:02 2026 0.0 0 less
"""


def in_front(listing, pid, tty):
    return sidebar.program_in_front(pid, tty, sidebar.parse_process_groups(listing),
                                    sidebar.parse_args(listing))


def test_an_agent_behind_another_program_names_that_program():
    """Text typed into the pane would reach the editor, not the agent."""
    assert in_front(GROUPS_PS, 9100, "ttys007") == "nvim"


def test_an_agent_in_the_foreground_group_it_does_not_lead_is_in_front():
    """Under `cs`, bash leads the group and Claude is a member: text typed
    into the pane reaches Claude."""
    assert in_front(GROUPS_PS, 8002, "ttys006") is None


def test_a_suspended_agent_has_its_shell_in_front_named_without_the_login_dash():
    """Ctrl-Z hands the pane back to the shell, which would run the text."""
    assert in_front(GROUPS_PS, 7100, "ttys008") == "zsh"


def test_a_row_with_no_agent_pid_makes_no_claim_about_the_front():
    """A Codex TUI that has published nothing names no process; the guard
    then asks only whether it waits or has exited."""
    assert in_front(GROUPS_PS, None, "ttys007") is None


def test_an_agent_pid_the_listing_does_not_hold_makes_no_claim_about_the_front():
    """A gone agent is the exited clause's to say."""
    assert in_front(GROUPS_PS, 4242, "ttys007") is None


def test_an_agent_on_another_terminal_than_its_pane_makes_no_claim_about_the_front():
    """The front of the agent's own terminal says nothing about where text
    typed into this pane goes."""
    assert in_front(GROUPS_PS, 7100, "ttys006") is None


def test_a_foreground_group_whose_leader_has_gone_is_another_program():
    """`cat log | less` keeps the pane after cat exits; the group outlives
    the leader that would have named it."""
    assert in_front(GROUPS_PS, 6100, "ttys009") == "another program"


from sidebar_rules import typing_refusal

REMOTE = {"session_id": "abc", "state": "blocked", "host": "box"}


def test_a_reply_to_a_remote_session_is_refused():
    assert prompt_refusal(dict(REMOTE, state="idle")) == "replies do not reach a remote session yet"
    assert prompt_refusal(REMOTE) == "replies do not reach a remote session yet"


def test_a_local_row_is_typed_into_as_before():
    assert typing_refusal({"session_id": "abc", "state": "idle"}, ["fix it", "\r"]) is None
    assert typing_refusal(None, ["1"]) is None


def test_a_remote_row_takes_one_key_while_it_waits_on_you():
    assert typing_refusal(REMOTE, ["2"]) is None
    assert typing_refusal(REMOTE, ["\x1b"]) is None


@pytest.mark.parametrize("strokes", [["2\n"], ["2", "\r"], ["\r"], ["\n"], ["3 use the other one\n"], ["yes"], []])
def test_a_remote_row_takes_no_line_and_no_text(strokes):
    assert typing_refusal(REMOTE, strokes) == "replies do not reach a remote session yet"


def test_a_remote_row_that_is_not_waiting_takes_no_key():
    assert typing_refusal(dict(REMOTE, state="working"), ["2"]) == "it is not waiting on you"
    assert typing_refusal(dict(REMOTE, state="unknown"), ["2"]) == "it is not waiting on you"


def test_a_remote_row_says_why_its_own_checks_refuse():
    row = dict(REMOTE, remote_refusal="the agent's title has gone from the pane")
    assert typing_refusal(row, ["2"]) == "the agent's title has gone from the pane"


def remote_bridge(monkeypatch, tmp_path, **changes):
    """A Bridge whose last frame lists "abc" as a remote card with one question standing."""
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    row = {"session_id": "abc", "state": "blocked", "host": "box",
           "question": {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0}}
    b.latest = {"groups": [{"name": "AGENTS", "rows": [dict(row, **changes)]}]}
    return b


def test_an_answer_types_its_digit_into_a_remote_pane_that_passes_its_checks(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": 2, "question": "Which one?"})))
    assert b.app.pane.typed == ["2"]


PICK_ANY = {"question": "Which ones?", "options": ["This", "That", "Other"], "multi": True, "more": 0}


def test_a_pick_any_submit_types_each_key_on_its_own(monkeypatch, tmp_path):
    """Measured on Claude Code 2.1.296: "13\\t1" sent as one write left the
    question unanswered, so each key lands as its own write, an arrow whole."""
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    b.latest["groups"][0]["rows"][0]["question"] = PICK_ANY
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": [3, 1], "question": "Which ones?"})))
    assert b.app.pane.typed == ["\x1b[D", "1", "3", "\t", "1"]


def test_a_pick_any_submit_is_not_typed_into_a_remote_pane(monkeypatch, tmp_path):
    """A remote pane takes one key at a time, so a burst of ticks is refused whole."""
    b = remote_bridge(monkeypatch, tmp_path, question=PICK_ANY)
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": [1], "question": "Which ones?"})))
    assert b.app.pane.typed == [] and b.answered == {}


def test_an_answer_is_not_typed_into_a_remote_pane_that_fails_its_checks(monkeypatch, tmp_path):
    """Nothing is typed, and the click is not remembered as an answer: the next one can still land."""
    b = remote_bridge(monkeypatch, tmp_path, remote_refusal="the agent's title has gone from the pane")
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": 1, "question": "Which one?"})))
    assert b.app.pane.typed == [] and b.answered == {}
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == (
        "answer refused abc the agent's title has gone from the pane\n")


def test_a_notices_reply_is_not_typed_into_a_remote_pane(monkeypatch, tmp_path):
    """Other, then the text, then Enter: a line a shell there could run."""
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "send", "3use the other one\n"))
    assert b.app.pane.typed == []
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == (
        "typing refused abc replies do not reach a remote session yet\n")


def test_a_notices_button_types_its_one_key_into_a_remote_pane_that_passes(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "send", "1"))
    assert b.app.pane.typed == ["1"]


def test_a_local_pane_is_typed_into_as_before(monkeypatch, tmp_path):
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    asyncio.run(b.act("abc", "send", "3use the other one\n"))
    assert b.app.pane.typed == ["3use the other one", "\r"]


def test_the_daemon_types_in_one_place():
    source = (Path(__file__).resolve().parent.parent / "sidebar.py").read_text()
    assert source.count("async_send_text(") == 1


def test_a_remote_row_out_of_reach_says_so_before_saying_it_is_not_waiting():
    """With the link gone the state reads unknown; the reason worth giving is the link."""
    row = dict(REMOTE, state="unknown", remote_refusal="the connection to box is not in front here")
    assert typing_refusal(row, ["2"]) == "the connection to box is not in front here"


@pytest.mark.parametrize("key", ["\x03", "\x04", "\x1a", "a", "Y", " ", "0x"])
def test_a_remote_row_takes_only_a_digit_y_or_escape(key):
    """Every key the panel types as an answer is one of those; anything else has no business in a remote pane."""
    assert typing_refusal(REMOTE, [key]) == "replies do not reach a remote session yet"


@pytest.mark.parametrize("key", ["1", "9", "0", "y", "\x1b"])
def test_a_remote_row_takes_each_answer_key(key):
    assert typing_refusal(REMOTE, [key]) is None
