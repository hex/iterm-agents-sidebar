"""macOS notices for the two moments a session wants you back.

A notification wears its SENDER's icon and name, never anything the poster
passes, so the panel posts through a bundle of its own. What is testable
without one is the argv and the decision to post at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar import (notify_argv, notify_response, notify_wanted, response_target, Notices,
                     switch_log_line, switch_notice_argv)

APP = Path("/tmp/example.app")
EXE = str(APP / "Contents" / "MacOS" / "agents-notifier")

ASKED = {"header": "Icon", "question": "Which icon?",
         "options": ["Dots", "Square", "Rows"], "multi": False, "more": 0}


def arg(argv, flag):
    return argv[argv.index(flag) + 1]


def args(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_a_finished_turn_names_the_session_and_offers_a_reply():
    argv = notify_argv(APP, "sess-1", "fignity", "done", None)
    assert argv[:2] == [EXE, "post"]
    assert arg(argv, "--id") == "sess-1"
    assert arg(argv, "--title") == "fignity"
    assert arg(argv, "--body") == "finished a turn"
    # The reply becomes the session's next prompt; it is idle, so that is safe.
    assert arg(argv, "--reply") == "Next prompt"
    assert "--button" not in argv


def test_a_question_shows_its_text_and_its_options_as_buttons():
    argv = notify_argv(APP, "sess-1", "fignity", "blocked", ASKED)
    assert arg(argv, "--body") == "Which icon?"
    assert args(argv, "--button") == ["1=Dots", "2=Square", "3=Rows"]
    # Claude Code always offers Other; the reply field is that option.
    assert arg(argv, "--reply") == "Other"


def test_a_question_with_more_behind_it_says_so():
    asked = dict(ASKED, more=2)
    assert arg(notify_argv(APP, "s", "n", "blocked", asked), "--body") == "Which icon? (+2 more)"


def test_at_most_four_buttons_because_macos_shows_no_more():
    asked = dict(ASKED, options=["a", "b", "c", "d", "e", "f"])
    assert len(args(notify_argv(APP, "s", "n", "blocked", asked), "--button")) == 4


def test_a_multi_select_question_gets_no_buttons():
    """One button cannot express several picks, and a wrong single pick would
    be sent blind into the prompt."""
    argv = notify_argv(APP, "s", "n", "blocked", dict(ASKED, multi=True))
    assert "--button" not in argv and "--reply" not in argv
    assert arg(argv, "--body") == "Which icon?"


def test_any_other_gated_tool_says_what_it_wants_to_run_and_offers_allow():
    """One action is all macOS shows flat, so the gate gets Allow and no
    Deny; the body shows the command's first line, which is all that a
    banner has room for."""
    argv = notify_argv(APP, "s", "n", "blocked", {"tool": "Bash", "summary": "git push"})
    assert arg(argv, "--body") == "wants to run: git push"
    assert arg(argv, "--button") == "allow=Allow"
    assert argv.count("--button") == 1 and "--reply" not in argv
    bare = notify_argv(APP, "s", "n", "blocked", {"tool": "Edit", "summary": ""})
    assert arg(bare, "--body") == "wants to run: Edit"


def test_allow_sends_the_digit_for_yes():
    """Yes is option 1 on every Claude Code permission prompt."""
    gate = {"tool": "Bash", "summary": "git push"}
    assert notify_response('{"action": "allow"}', "blocked", gate) == ("send", "1")


def test_allow_for_a_gate_that_has_gone_or_is_a_question_sends_nothing():
    assert notify_response('{"action": "allow"}', "blocked", None) == (None, None)
    assert notify_response('{"action": "allow"}', "blocked", ASKED) == (None, None)
    assert notify_response('{"action": "allow"}', "done", None) == (None, None)


def test_a_question_the_hook_could_not_read_still_gets_a_plain_notice():
    assert arg(notify_argv(APP, "s", "n", "blocked", None), "--body") == "needs you"


def test_a_session_going_back_to_work_takes_its_notice_down():
    assert notify_argv(APP, "sess-1", "fignity", "clear", None) == [EXE, "remove", "--id", "sess-1"]


def test_a_nameless_session_still_gets_a_title():
    assert arg(notify_argv(APP, "sess-1", "", "done", None), "--title") == "Session"


def test_an_unknown_moment_posts_nothing():
    assert notify_argv(APP, "sess-1", "fignity", "started", None) is None


# --- what the sender prints back -------------------------------------------

def test_a_click_brings_the_session_forward():
    assert notify_response('{"action": "default"}', "blocked", ASKED) == ("bring", None)
    assert notify_response('{"action": "default"}', "done", None) == ("bring", None)


def test_a_button_sends_the_digit_that_picks_that_option():
    """Claude Code's prompt takes the option's number outright; no Enter, so
    a digit that somehow misses only moves the cursor and confirms nothing."""
    assert notify_response('{"action": "2"}', "blocked", ASKED) == ("send", "2")


def test_a_reply_to_a_question_picks_other_and_types_the_text():
    """Other is the option after the last listed one."""
    assert notify_response('{"action": "reply", "text": "neither"}', "blocked", ASKED) == ("send", "4neither\n")


def test_a_reply_to_a_finished_turn_is_the_next_prompt():
    assert notify_response('{"action": "reply", "text": "run the tests"}', "done", None) == ("send", "run the tests\n")


def test_a_button_for_a_question_that_has_gone_sends_nothing():
    """The prompt the button belonged to may have been answered in the
    terminal; keystrokes then land in whatever replaced it."""
    assert notify_response('{"action": "2"}', "blocked", None) == (None, None)
    assert notify_response('{"action": "reply", "text": "x"}', "blocked", None) == (None, None)


def test_dismissal_and_noise_do_nothing():
    assert notify_response('{"action": "dismiss"}', "blocked", ASKED) == (None, None)
    assert notify_response('not json', "blocked", ASKED) == (None, None)
    assert notify_response('{"action": "9"}', "blocked", ASKED) == (None, None)


def test_a_response_names_the_notice_it_is_for_or_falls_back_to_the_sender_own():
    """macOS hands every response for the bundle to one running sender,
    whichever notice was clicked, so the line carries the notice's id and
    the daemon routes on it. An old sender that prints no id is answering
    for itself."""
    assert response_target('{"id": "sess-2", "action": "allow"}', "sess-1") == "sess-2"
    assert response_target('{"action": "allow"}', "sess-1") == "sess-1"
    assert response_target('not json', "sess-1") == "sess-1"


# --- one standing notice per session ----------------------------------------

class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    async def wait(self):
        self.waited = True
        self.returncode = -15
        return self.returncode


def test_retiring_waits_for_the_old_sender_to_finish_taking_its_notice_down():
    """A sender's exit removes the notice by id, and the replacement shares
    that id: posted before the old one has finished, the new notice is the
    one removed. Measured 2026-09-16."""
    import asyncio
    notices = Notices()
    old = FakeProcess()
    notices.replace("sess-1", old, "done", None)
    asyncio.run(notices.retire("sess-1"))
    assert old.terminated and old.waited
    assert notices.standing("sess-1") is None
    asyncio.run(notices.retire("sess-1"))   # nothing standing: no error


def test_a_new_notice_for_a_session_replaces_the_one_standing():
    notices = Notices()
    first = FakeProcess()
    notices.replace("sess-1", first, "done", None)
    second = FakeProcess()
    notices.replace("sess-1", second, "blocked", ASKED)
    assert first.terminated and not second.terminated
    assert notices.standing("sess-1") is second


def test_a_notice_remembers_what_it_asked_so_another_sender_can_answer_it():
    notices = Notices()
    notices.replace("sess-1", FakeProcess(), "blocked", ASKED)
    assert notices.asked("sess-1") == ("blocked", ASKED)
    assert notices.asked("sess-9") is None


def test_clearing_terminates_and_forgets():
    notices = Notices()
    proc = FakeProcess()
    notices.replace("sess-1", proc, "done", None)
    notices.clear("sess-1")
    assert proc.terminated and notices.standing("sess-1") is None
    notices.clear("sess-1")                       # nothing standing: no error


def test_a_notice_that_ended_on_its_own_is_not_terminated_again():
    notices = Notices()
    proc = FakeProcess()
    proc.returncode = 0
    notices.replace("sess-1", proc, "done", None)
    notices.replace("sess-1", FakeProcess(), "done", None)
    assert not proc.terminated


def test_no_notice_for_the_session_you_are_looking_at():
    assert notify_wanted("done", "sess-1", active="sess-1", app_active=True) is False


def test_a_notice_for_that_session_when_iterm_is_behind_something_else():
    """The session is in front of its own window, but you are in another
    application -- which is exactly when a notice earns its place."""
    assert notify_wanted("done", "sess-1", active="sess-1", app_active=False) is True


def test_a_notice_for_a_session_in_another_tab_of_the_window_you_are_in():
    """cs could only ask whether the terminal was frontmost, so it went silent
    here. The panel knows which tab is in front."""
    assert notify_wanted("blocked", "sess-1", active="sess-2", app_active=True) is True


def test_unknown_focus_posts():
    """A missed question costs more than a banner you did not need."""
    assert notify_wanted("done", "sess-1", active=None, app_active=None) is True


def test_taking_a_notice_down_is_never_suppressed():
    """Removal is not noise, and the session you are looking at is the one
    most likely to have a stale notice standing."""
    assert notify_wanted("clear", "sess-1", active="sess-1", app_active=True) is True


SNAPSHOT = {"groups": [
    {"name": "AGENTS", "rows": [
        {"session_id": "sess-1", "label": "fignity", "depth": 0},
        {"session_id": "sess-2", "label": "review-351", "depth": 1},
    ]},
    {"name": "SESSIONS", "rows": [
        {"session_id": "sess-3", "label": "~/src/example", "depth": 0},
    ]},
]}


def test_the_notice_is_titled_what_the_panel_calls_the_session():
    assert sidebar.row_label(SNAPSHOT, "sess-1") == "fignity"
    assert sidebar.row_label(SNAPSHOT, "sess-3") == "~/src/example"


def test_a_teammate_is_titled_by_its_own_name_not_its_lead():
    assert sidebar.row_label(SNAPSHOT, "sess-2") == "review-351"


def test_a_session_the_snapshot_has_not_caught_up_with_has_no_name():
    assert sidebar.row_label(SNAPSHOT, "sess-9") == ""



def test_a_trailing_newline_is_typed_as_its_own_enter():
    """Text and newline in one write reach Claude Code as a pasted block, and
    a pasted newline is a line break, not a submit. Enter goes on its own."""
    from sidebar import keystrokes
    assert keystrokes("run the tests\n") == ["run the tests", "\r"]
    assert keystrokes("2") == ["2"]
    assert keystrokes("\n") == ["\r"]
    assert keystrokes("") == []


def test_an_automatic_switch_posts_one_plain_notice_under_its_own_id():
    assert switch_notice_argv("/Apps/Agents.app", "bob@example.com", "Fable at 98%") == [
        "/Apps/Agents.app/Contents/MacOS/agents-notifier", "post", "--id", "account-switch",
        "--title", "Switched to bob@example.com", "--body", "Fable at 98%"]


def test_each_account_event_reads_as_one_log_line():
    assert switch_log_line({"kind": "switched", "name": "bob@example.com", "why": "Fable at 98%"}) == \
        "auto-switch -> bob@example.com (Fable at 98%)"
    assert switch_log_line({"kind": "blocked", "why": "every account is full"}) == \
        "auto-switch: nowhere to go, every account is full"
    assert switch_log_line({"kind": "refused", "why": "log in to home again"}) == \
        "auto-switch refused: log in to home again"


def test_an_agent_that_posts_its_own_notices_gets_none_from_the_panel():
    """omp tells the terminal itself when it finishes or asks (its
    completion.notify and ask.notify settings, on by default), so a second
    banner for the same moment is noise."""
    from sidebar import notifies_itself
    assert notifies_itself({"provider": "omp"}) is True
    assert notifies_itself({"provider": "openai"}) is False
    assert notifies_itself({}) is False
