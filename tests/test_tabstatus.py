# ABOUTME: Guards tabstatus.py: what each agent's tab says under its title, when it is written and
# ABOUTME: cleared, and that a tab another writer owns (iTerm2's cc-status hooks) is never fought over.
"""Ways this can go wrong, and the tests that catch each:
- a tab says something the card does not (wrong word, a stale question, a
  done on a teammate or on a session already looked at);
- agent text breaks the line: a newline, a control character, a detail too
  long for the space under a tab;
- a resting session keeps a word nobody vouches for;
- the daemon writes a Claude tab while cc-status owns it, so the two fight;
- a word of the daemon's stays behind after the session is handed back, the
  daemon dies, or the setting goes off;
- a cc-status word stays on a Claude tab for good after the hand-over;
- a steady panel sends calls every reading;
- a failing session floods the log, or an older iTerm2 gets a call per tab
  per reading.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tabstatus  # noqa: E402
from tabstatus import Status  # noqa: E402


def card(sid, state, **more):
    return dict({"session_id": sid, "state": state, "depth": 0}, **more)


# ------------------------------------------------------------- one tab's line

def test_a_working_card_says_working_and_what_it_says_it_is_doing():
    row = card("a", "working", doing="Running the tests", agents=2, shells=[{"command": "npm run dev"}])
    assert tabstatus.status_of(row, set()) == Status("working", "Running the tests", 3)


def test_a_blocked_card_shows_its_question():
    row = card("a", "blocked", question={"question": "Ship it?", "options": ["Yes", "No"], "multi": False, "more": 0},
               doing="Deciding")
    assert tabstatus.status_of(row, set()) == Status("needs you", "Ship it?", 0)


def test_a_blocked_card_waiting_on_a_permission_shows_the_tool_and_what_it_wants():
    gate = {"tool": "Bash", "summary": "rm -rf build", "id": "toolu_1"}
    assert tabstatus.status_of(card("a", "blocked", question=gate), set()) == Status("needs you", "Bash: rm -rf build", 0)
    bare = {"tool": "WebFetch", "summary": "", "id": "toolu_2"}
    assert tabstatus.status_of(card("a", "blocked", question=bare), set()) == Status("needs you", "WebFetch", 0)


def test_a_blocked_card_with_no_question_falls_back_to_what_it_was_doing_then_to_nothing():
    assert tabstatus.status_of(card("a", "blocked", doing="Editing page.html"), set()) == \
        Status("needs you", "Editing page.html", 0)
    assert tabstatus.status_of(card("a", "blocked"), set()) == Status("needs you", "", 0)


def test_only_a_card_that_finished_unseen_says_done_and_with_no_detail():
    assert tabstatus.status_of(card("a", "idle", agents=1), {"a"}) == Status("done", "", 1)
    assert tabstatus.status_of(card("a", "idle"), set()) is None
    teammate = dict(card("t", "idle"), depth=1)
    assert tabstatus.status_of(teammate, {"t"}) is None


def test_a_session_at_rest_or_unread_shows_nothing():
    for state in ("idle", "unknown"):
        assert tabstatus.status_of(card("a", state), set()) is None
    assert tabstatus.status_of({"session_id": "a", "depth": 0}, {"a"}) is None


def test_one_line_folds_whitespace_drops_controls_and_clips_to_sixty():
    assert tabstatus.one_line("  Fix\nthe\t\tbuild \x1b[31mnow\x07 ") == "Fix the build [31mnow"
    long = "word " * 20
    assert tabstatus.one_line(long) == "word word word word word word word word word word word word…"
    assert len(tabstatus.one_line(long)) == 60
    assert tabstatus.one_line("x" * 60) == "x" * 60


def test_a_detail_reaches_the_call_as_one_literal_line():
    """The wire string is the iterm2 library's (invocation_string escapes \\ and
    "); what crosses into it is one clean line with every character kept."""
    hostile = 'say "hi"); iterm2.quit(\\(session.name)\nnext'
    row = card("a", "working", doing=hostile)
    assert tabstatus.status_of(row, set()).args("a") == {
        "session_id": "a", "status": "working", "detail": 'say "hi"); iterm2.quit(\\(session.name) next',
        "dot_color": "#ff9501", "text_color": "#ff9501", "background_tasks": 0}


def test_the_faces_are_the_panels_dark_colours_and_none_is_cc_statuss():
    """The tab bar cannot follow the panel's theme, so a tab wears the dark
    values; and the daemon knows its own dots only while cc-status uses none."""
    page = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")
    dark = page[page.index("@media (prefers-color-scheme: dark)"):]

    def token(name):
        return re.search(rf"--{name}:\s*(#[0-9a-f]{{6}})", dark).group(1)
    assert (tabstatus.FACES["needs you"], tabstatus.FACES["done"]) == (token("blocked-border"), token("sev-ok"))
    assert tabstatus.SIGNATURE.isdisjoint(tabstatus.CC_PALETTE)


def test_a_clear_sets_every_field():
    """A colour survives a status change unless rewritten, so a clear names all five."""
    assert tabstatus.clear_args("a") == {"session_id": "a", "status": "", "detail": "", "dot_color": "",
                                         "text_color": "", "background_tasks": 0}


# ------------------------------------------------------------- which tabs, and what changes

ON = {"tab_status": True, "offer_tab_status": True}
OFF = {"tab_status": False, "offer_tab_status": True}


def test_wanted_yields_local_claude_tabs_while_iterm2s_hooks_are_installed_or_unreadable():
    """cc-status writes local Claude sessions only. A settings.json that cannot
    be read is no proof it is gone. Codex, omp and remote rows are always ours."""
    rows = [card("c", "working"), card("x", "working", provider="openai"), card("o", "blocked", provider="omp"),
            card("r", "working", host="build-box")]
    working, needs = Status("working", "", 0), Status("needs you", "", 0)
    assert tabstatus.wanted(rows, set(), ON, "present") == ({"x": working, "o": needs, "r": working}, {"c"})
    assert tabstatus.wanted(rows, set(), ON, "unreadable") == ({"x": working, "o": needs, "r": working}, {"c"})
    assert tabstatus.wanted(rows, set(), ON, "absent") == ({"c": working, "x": working, "o": needs, "r": working}, set())


def test_wanted_is_nothing_with_the_setting_off():
    assert tabstatus.wanted([card("x", "working", provider="openai"), card("c", "working")], set(), OFF, "present") == ({}, set())


def test_two_rows_on_one_session_show_the_one_that_most_needs_you():
    """Plain tmux puts several agents in one iTerm2 session."""
    rows = [card("a", "working", provider="openai"), card("a", "blocked", provider="omp"), card("a", "idle", provider="omp")]
    assert tabstatus.wanted(rows, {"a"}, ON, "absent") == ({"a": Status("needs you", "", 0)}, set())


def test_plan_writes_the_changed_clears_the_gone_and_releases_the_yielded():
    working, needs = Status("working", "", 0), Status("needs you", "Ship it?", 0)
    have = {"same": working, "changed": working, "gone": working, "handed": working, "foreign": None}
    want = {"same": working, "changed": needs, "fresh": working, "foreign": working}
    assert tabstatus.plan(want, have, {"handed"}) == tabstatus.Plan(
        writes={"changed": needs, "fresh": working, "foreign": working}, clears={"gone"}, releases={"handed"})


def test_the_page_hears_unavailable_first_and_contested_only_while_it_would_offer():
    assert tabstatus.notice(ON, "present", available=False) == "unavailable"
    assert tabstatus.notice(OFF, "absent", available=False) == "unavailable"
    assert tabstatus.notice(ON, "present", available=True) == "contested"
    assert tabstatus.notice(dict(ON, offer_tab_status=False), "present", available=True) is None
    assert tabstatus.notice(OFF, "present", available=True) is None
    assert tabstatus.notice(ON, "unreadable", available=True) is None
    assert tabstatus.notice(ON, "absent", available=True) is None


# ------------------------------------------------------------- the writer

GET, SET = "iterm2.get_session_status", "iterm2.set_session_status"
#: A session's status as get_session_status answers it after a clear.
BLANK = {"status": None, "turn_open": None, "detail": None, "text_color": None, "dot_color": None, "background_tasks": 0}
#: cc-status's own working word, as it paints it.
CC_WORKING = {"status": "working", "dot_color": "#ff9500", "text_color": "#ff9500"}
CC_IDLE = {"status": "idle", "dot_color": "#888888", "text_color": "#888888"}


class ITerm:
    """iTerm2's two status functions over a table of sessions, as probed: an
    empty string empties a field, and every call answers the status after it."""
    def __init__(self, **tabs):
        self.tabs = {sid: dict(BLANK, **tab) for sid, tab in tabs.items()}
        self.calls = []
        #: sid -> the error every call on that session raises.
        self.refuse = {}

    async def invoke(self, name, args):
        self.calls.append((name, dict(args)))
        sid = args["session_id"]
        if sid in self.refuse:
            raise RuntimeError(self.refuse[sid])
        if sid not in self.tabs:
            raise RuntimeError("FAILED: No such session")
        tab = self.tabs[sid]
        if name == SET:
            tab.update({field: value if value != "" else None for field, value in args.items() if field != "session_id"})
        return dict(tab)

    def app(self):
        return App(*self.tabs)


class Session:
    def __init__(self, sid):
        self.session_id = sid


class App:
    def __init__(self, *sids):
        self.sessions = {sid: Session(sid) for sid in sids}
        self.terminal_windows = [type("W", (), {"tabs": [type("T", (), {"sessions": list(self.sessions.values())})()]})()]

    def get_session_by_id(self, sid):
        return self.sessions.get(sid)


def run(writer, app, rows, unseen, settings, hooks, log):
    asyncio.run(writer.step(app, rows, unseen, settings, hooks, log))


def needs_you(detail, background=0, colour="#ff9f0a"):
    return {"status": "needs you", "detail": detail, "dot_color": colour, "text_color": colour, "background_tasks": background}


def test_a_card_that_needs_you_shows_its_question_and_idle_takes_it_back():
    term, logged = ITerm(a={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    row = card("a", "blocked", question={"question": "Ship it?", "options": ["Yes", "No"]})
    run(w, app, [row], set(), ON, "absent", logged.append)
    run(w, app, [card("a", "idle")], set(), ON, "absent", logged.append)
    assert term.calls == [
        (GET, {"session_id": "a"}),
        (SET, {"session_id": "a", "status": "needs you", "detail": "Ship it?",
               "dot_color": "#ff9f0a", "text_color": "#ff9f0a", "background_tasks": 0}),
        (SET, {"session_id": "a", "status": "", "detail": "", "dot_color": "", "text_color": "", "background_tasks": 0}),
    ]
    assert term.tabs["a"] == BLANK
    assert w.have == {} and logged == []


def test_a_steady_panel_sends_nothing():
    term, logged = ITerm(x={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    for _ in range(3):
        run(w, app, [card("x", "working", provider="openai", doing="Reading")], set(), ON, "present", logged.append)
    assert [name for name, _ in term.calls] == [GET, SET]
    assert term.tabs["x"]["status"] == "working" and term.tabs["x"]["detail"] == "Reading"


def test_yielded_claude_tabs_are_never_written_while_codex_tabs_are():
    term, logged = ITerm(c=CC_WORKING, x={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("c", "blocked"), card("x", "blocked", provider="openai")], set(), ON, "present", logged.append)
    assert [call for call in term.calls if call[0] == SET] == [(SET, dict(needs_you(""), session_id="x"))]
    assert term.tabs["c"] == dict(BLANK, **CC_WORKING)


def test_a_tab_that_becomes_yielded_is_cleared_only_while_its_dot_is_still_ours():
    """iTerm2's hooks came back: a tab cc-status already wrote is its own now;
    one it has not reached yet keeps no word of ours."""
    term, logged = ITerm(a={}, b={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("a", "working"), card("b", "working")], set(), ON, "absent", logged.append)
    term.tabs["b"].update(CC_IDLE)
    del term.calls[:]
    run(w, app, [card("a", "working"), card("b", "working")], set(), ON, "present", logged.append)
    assert term.calls == [(GET, {"session_id": "a"}),
                          (SET, {"session_id": "a", "status": "", "detail": "", "dot_color": "",
                                 "text_color": "", "background_tasks": 0}),
                          (GET, {"session_id": "b"})]
    assert term.tabs["a"] == BLANK and term.tabs["b"]["status"] == "idle"
    assert w.have == {} and logged == []


def test_a_word_a_dead_daemon_left_is_corrected_on_an_owned_tab_and_cleared_on_a_yielded_one():
    left = {"status": "working", "detail": "Old", "dot_color": "#ff9501", "text_color": "#ff9501"}
    term, logged = ITerm(owned=left, idle=left, yielded=left, theirs=CC_WORKING, user={"status": "deploying", "dot_color": "#123456"}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    rows = [card("owned", "working", provider="omp", doing="New"), card("idle", "idle", provider="omp"),
            card("yielded", "idle"), card("theirs", "working")]
    run(w, app, rows, set(), ON, "present", logged.append)
    assert term.tabs["owned"]["detail"] == "New"
    assert term.tabs["idle"] == BLANK and term.tabs["yielded"] == BLANK
    assert term.tabs["theirs"] == dict(BLANK, **CC_WORKING)
    assert term.tabs["user"] == dict(BLANK, status="deploying", dot_color="#123456")
    assert w.have == {"owned": Status("working", "New", 0)} and logged == []


def test_an_unchanged_word_a_dead_daemon_left_is_adopted_without_a_write():
    left = {"status": "working", "detail": "Reading", "dot_color": "#ff9501", "text_color": "#ff9501", "background_tasks": 1}
    term, logged = ITerm(x=left), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("x", "working", provider="openai", doing="Reading", agents=1)], set(), ON, "absent", logged.append)
    assert term.calls == [(GET, {"session_id": "x"})]
    assert w.have == {"x": Status("working", "Reading", 1)}


def test_a_cc_status_word_on_a_claude_tab_is_taken_once_its_hooks_are_gone():
    """Removed by hand before the daemon started, or handed over while it runs:
    either way the idle and done words cc-status left would stay for good."""
    term, logged = ITerm(idle=CC_IDLE, busy=CC_WORKING), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    rows = [card("idle", "idle"), card("busy", "blocked")]
    run(w, app, rows, set(), ON, "absent", logged.append)
    assert term.tabs["idle"] == BLANK
    assert term.tabs["busy"] == dict(BLANK, **needs_you(None))

    term, logged = ITerm(idle=CC_IDLE, busy=CC_WORKING), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, rows, set(), ON, "present", logged.append)
    assert [name for name, _ in term.calls] == [GET, GET]
    run(w, app, rows, set(), ON, "absent", logged.append)
    assert term.tabs["idle"] == BLANK
    assert term.tabs["busy"] == dict(BLANK, **needs_you(None))
    assert w.have == {"busy": Status("needs you", "", 0)} and logged == []


def test_with_the_setting_off_cc_status_words_are_left_alone_and_ours_are_taken_back():
    ours = {"status": "done", "dot_color": "#30d158", "text_color": "#30d158"}
    term, logged = ITerm(theirs=CC_IDLE, mine=ours), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("theirs", "idle"), card("mine", "idle", provider="openai")], set(), OFF, "absent", logged.append)
    assert term.tabs["theirs"] == dict(BLANK, **CC_IDLE)
    assert term.tabs["mine"] == BLANK


def test_turning_the_setting_off_takes_every_word_back():
    term, logged = ITerm(x={}, o={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    rows = [card("x", "working", provider="openai"), card("o", "blocked", provider="omp")]
    run(w, app, rows, set(), ON, "present", logged.append)
    run(w, app, rows, set(), OFF, "present", logged.append)
    assert term.tabs == {"x": BLANK, "o": BLANK} and w.have == {}


def test_a_failing_session_is_logged_once_kept_and_written_when_it_answers():
    term, logged = ITerm(abcdefgh1={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    rows = [card("abcdefgh1", "working", provider="openai")]
    run(w, app, [], set(), ON, "absent", logged.append)
    term.refuse["abcdefgh1"] = "FAILED: busy"
    run(w, app, rows, set(), ON, "absent", logged.append)
    run(w, app, rows, set(), ON, "absent", logged.append)
    assert logged == ["status abcdefgh: RuntimeError('FAILED: busy')"] and w.have == {}
    del term.refuse["abcdefgh1"]
    run(w, app, rows, set(), ON, "absent", logged.append)
    assert w.have == {"abcdefgh1": Status("working", "", 0)} and term.tabs["abcdefgh1"]["status"] == "working"
    term.refuse["abcdefgh1"] = "FAILED: busy"
    run(w, app, [], set(), ON, "absent", logged.append)
    assert len(logged) == 2 and w.have == {"abcdefgh1": Status("working", "", 0)}


def test_a_closed_session_leaves_without_a_call():
    term, logged = ITerm(x={}), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("x", "working", provider="openai")], set(), ON, "absent", logged.append)
    del term.calls[:]
    run(w, App(), [card("y", "working", provider="openai")], set(), ON, "absent", logged.append)
    assert term.calls == [] and w.have == {} and logged == []


def test_an_iterm2_without_the_functions_turns_the_writer_off_after_one_call():
    term, logged = ITerm(x={}, y={}), []
    no_function = "FAILED: No function registered for invocation “iterm2.get_session_status(session_id)”."
    term.refuse = {"x": no_function, "y": no_function}
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    for _ in range(2):
        run(w, app, [card("x", "working", provider="openai")], set(), ON, "absent", logged.append)
    assert len(term.calls) == 1 and w.available is False
    assert logged == [f"tab status off: {no_function}"]
    assert tabstatus.notice(ON, "absent", w.available) == "unavailable"


def test_a_start_where_every_read_fails_turns_the_writer_off():
    term, logged = ITerm(abcdefgh1={}, abcdefgh2={}), []
    term.refuse = {"abcdefgh1": "Timeout", "abcdefgh2": "Timeout"}
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("abcdefgh1", "working", provider="openai")], set(), ON, "absent", logged.append)
    assert w.available is False and [name for name, _ in term.calls] == [GET, GET]
    assert logged == ["status abcdefgh: RuntimeError('Timeout')", "status abcdefgh: RuntimeError('Timeout')",
                      "tab status off: no session's status could be read"]
    # No sessions at all is not a failure.
    w = tabstatus.Writer(invoke=ITerm().invoke)
    run(w, App(), [], set(), ON, "absent", logged.append)
    assert w.available is True


def test_stopping_takes_back_every_word():
    term, logged = ITerm(x={}, o={}, c=CC_IDLE), []
    w, app = tabstatus.Writer(invoke=term.invoke), term.app()
    run(w, app, [card("x", "working", provider="openai"), card("o", "blocked", provider="omp"), card("c", "idle")],
        set(), ON, "absent", logged.append)
    asyncio.run(w.clear_all(logged.append))
    assert term.tabs == {"x": BLANK, "o": BLANK, "c": BLANK} and w.have == {} and logged == []
