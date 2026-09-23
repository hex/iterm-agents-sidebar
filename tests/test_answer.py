"""Answering an AskUserQuestion prompt from the buttons on its card.

A click is keystrokes typed into a pane, so everything that could make them
land on the wrong prompt is refused. Ways this can go wrong, and the test for
each:
- the question the buttons were drawn for has been answered in the terminal
  and another has replaced it: the digit would pick an option nobody saw;
- a second click on the same standing question (a double click, or the next
  question of a set, which Claude Code shows while the row still names the
  first): the digit would answer a question nobody read;
- a multi-select question: a digit toggles a box and submits nothing, so the
  card would claim an answer it never gave;
- a pick past the last option, zero, or not a number at all: the digit would
  land on Other, or move a cursor;
- a tool gate or no question at all: there are no options to pick;
- a malformed request body from the page;
- the same question asked again, word for word, after the first was
  answered and closed: remembered for good, it could never be answered.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import answer_keys, still_answered  # noqa: E402

ASKED = {"header": "Scope", "question": "Same checkout, or across worktrees?",
         "options": ["Same checkout only", "Across worktrees", "Both, marked apart"],
         "multi": False, "more": 0}


def click(pick, question=ASKED["question"]):
    return json.dumps({"pick": pick, "question": question})


def test_a_pick_on_the_standing_question_sends_its_number():
    assert answer_keys(click(2), ASKED, None) == "2"


def test_the_last_option_is_a_valid_pick():
    assert answer_keys(click(3), ASKED, None) == "3"


def test_a_click_meant_for_a_question_that_has_since_changed_sends_nothing():
    replaced = dict(ASKED, question="Ship it now?")
    assert answer_keys(click(1), replaced, None) is None


def test_a_second_click_on_an_answered_question_sends_nothing():
    assert answer_keys(click(1), ASKED, ASKED) is None


def test_a_new_question_after_an_answered_one_can_be_answered():
    replaced = dict(ASKED, question="Ship it now?")
    assert answer_keys(click(1, "Ship it now?"), replaced, ASKED) == "1"


def test_a_multi_select_question_is_never_answered_from_the_card():
    assert answer_keys(click(1), dict(ASKED, multi=True), None) is None


def test_a_pick_past_the_last_option_sends_nothing():
    assert answer_keys(click(4), ASKED, None) is None


def test_a_pick_of_zero_sends_nothing():
    assert answer_keys(click(0), ASKED, None) is None


def test_a_pick_that_is_not_a_whole_number_sends_nothing():
    assert answer_keys(click("2"), ASKED, None) is None
    assert answer_keys(click(True), ASKED, None) is None
    assert answer_keys(click(1.5), ASKED, None) is None


def test_a_tool_gate_has_nothing_to_pick():
    """A tool gate names no question, so a click that names none matches it."""
    assert answer_keys(click(1, None), {"tool": "Bash", "summary": "git push"}, None) is None


def test_no_standing_question_sends_nothing():
    assert answer_keys(click(1), None, None) is None


def test_a_malformed_request_sends_nothing():
    assert answer_keys("2", ASKED, None) is None
    assert answer_keys(None, ASKED, None) is None
    assert answer_keys("[1]", ASKED, None) is None


def panel(question):
    return {"groups": [{"name": "AGENTS", "rows": [{"session_id": "abc", "question": question}]}]}


def test_an_answered_question_still_standing_stays_answered():
    assert still_answered({"abc": ASKED}, panel(ASKED)) == {"abc": ASKED}


def test_an_answered_question_that_closed_is_forgotten_so_it_can_be_asked_again():
    assert still_answered({"abc": ASKED}, panel(None)) == {}


def test_a_session_that_left_the_panel_is_forgotten():
    assert still_answered({"gone": ASKED}, panel(ASKED)) == {}
