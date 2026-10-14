# ABOUTME: Answering a pick-any (multiSelect) AskUserQuestion from its card's checkboxes.
# ABOUTME: One Submit types the ticked digits, Tab, and on a lone question the review's Submit.
"""Measured on Claude Code 2.1.296: a digit toggles its box and the cursor
stays; Tab moves to the next question, or from the last to the review step,
where 1 submits and 2 cancels the whole set; the digit after the last option
ticks an empty "Type something" box. The card cannot see the pane, so its
ticks are its own and go in one burst at Submit.

Ways this can go wrong, and the test for each:
- a pick list that names the free-text box, zero, a duplicate (which would
  toggle a box back off) or nothing at all;
- a single number on a pick-any question, or a list on a pick-one question;
- a second Submit on the same question;
- a pick-any step inside a set out of order, or taken as the whole set;
- a Codex card: its multi-select keys were never measured.
Known and accepted (2026-10-13): boxes already ticked in the pane are
flipped by the card's digits, since nothing reports them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import LEFT, RIGHT, answer_keys, next_answered  # noqa: E402

ASKED = {"header": "Colours", "question": "Which colours?", "options": ["Red", "Green", "Blue"],
         "multi": True, "more": 0}


def click(pick, question=ASKED["question"], **extra):
    return json.dumps({"pick": pick, "question": question, **extra})


def test_submit_on_a_lone_question_types_the_ticks_then_tab_then_the_reviews_submit():
    """Left first: a pane already on the review step goes back to the question."""
    assert answer_keys(click([1, 3]), ASKED, None) == [LEFT, "1", "3", "\t", "1"]


def test_ticks_are_typed_in_order_whatever_order_they_were_clicked():
    assert answer_keys(click([3, 1]), ASKED, None) == [LEFT, "1", "3", "\t", "1"]


def test_a_pick_list_naming_the_free_text_box_or_zero_types_nothing():
    assert answer_keys(click([1, 4]), ASKED, None) is None
    assert answer_keys(click([0, 2]), ASKED, None) is None


def test_a_box_named_twice_types_nothing():
    """Its second digit would untick it."""
    assert answer_keys(click([2, 2]), ASKED, None) is None


def test_submit_with_nothing_ticked_types_nothing():
    assert answer_keys(click([]), ASKED, None) is None


def test_a_pick_list_of_anything_but_whole_numbers_types_nothing():
    assert answer_keys(click(["1"]), ASKED, None) is None
    assert answer_keys(click([True]), ASKED, None) is None
    assert answer_keys(click([[1]]), ASKED, None) is None


def test_a_single_number_on_a_pick_any_question_types_nothing():
    assert answer_keys(click(1), ASKED, None) is None


def test_a_pick_list_on_a_pick_one_question_types_nothing():
    assert answer_keys(click([1]), dict(ASKED, multi=False), None) is None


def test_a_second_submit_on_the_same_question_types_nothing():
    assert answer_keys(click([1]), ASKED, next_answered(ASKED, None)) is None


def test_a_codex_card_is_not_answered_from_its_checkboxes():
    assert answer_keys(click([1]), ASKED, None, "openai") is None
    assert answer_keys(click([1]), ASKED, None, "claude") == [LEFT, "1", "\t", "1"]


SET = [{"header": "Size", "question": "Which size?", "options": ["Small", "Large"], "multi": False},
       {"header": "Colours", "question": "Which colours?", "options": ["Red", "Green", "Blue"], "multi": True},
       {"header": "Pets", "question": "Which pets?", "options": ["Cat", "Dog"], "multi": True}]
IN_SET = {**SET[0], "more": 2, "set": SET}


def walk(*clicks):
    """Send clicks in turn the way the daemon does -> the keys typed for each."""
    answered, typed = None, []
    for pick, step in clicks:
        keys = answer_keys(click(pick, IN_SET["question"], step=step), IN_SET, answered)
        typed.append(keys)
        if keys is not None:
            answered = next_answered(IN_SET, answered)
    return typed


def test_each_step_of_a_set_walks_the_pane_to_its_own_question_first():
    """Left as many times as there are questions reaches the first from
    anywhere, Right then counts to the step; the review step is Right from
    anywhere. A pane moved on in the terminal is walked back first."""
    assert walk((2, 0), ([1, 3], 1), ([2], 2), (1, "submit")) == [
        [LEFT, LEFT, LEFT, "2"], [LEFT, LEFT, LEFT, RIGHT, "1", "3", "\t"],
        [LEFT, LEFT, LEFT, RIGHT, RIGHT, "2", "\t"], [RIGHT, RIGHT, RIGHT, "1"]]


def test_a_pick_any_step_out_of_order_types_nothing():
    assert walk(([1], 1)) == [None]
    assert walk((2, 0), ([1], 2)) == [[LEFT, LEFT, LEFT, "2"], None]
