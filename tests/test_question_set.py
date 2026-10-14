"""Answering an AskUserQuestion that asks several questions, step by step from the card.

Claude Code says nothing as it moves from one question of a set to the next,
so the card walks the set itself: each click answers the question it shows
and moves the card to the next, and the last step is Submit. The daemon
counts the steps it typed, so the order holds even when the page repaints.
Ways this can go wrong, and the test for each:
- a click for a step other than the next one the daemon expects (a double
  click, a stale page, a replayed request): a digit lands on the wrong question;
- a pick past a step's own options: the digit lands on Other or Chat about this;
- a single digit on a multi-select step: it toggles a box and submits
  nothing (its ticks come as a list: test_pick_any.py);
- Submit sent before every question was answered, or a pick other than 1 on it
  (2 is Cancel, which throws the whole set away);
- a set asked again, word for word, after it closed: remembered for good, it
  could never be answered.
Claude Code's picker moves between questions with the arrow keys, Left
stopping at the first and Right at the review step (measured on 2.1.296),
so each click first walks the pane to the question it was drawn for: a
question answered in the terminal no longer sends the card's pick to the
next one. The card still counts only its own clicks, so the set is walked
in order from the card.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import LEFT, RIGHT, answer_keys, next_answered, still_answered  # noqa: E402

SET = [{"header": "Colour", "question": "Pick a colour", "options": ["Red", "Green", "Blue"], "multi": False},
       {"header": "Size", "question": "Pick a size", "options": ["Small", "Large"], "multi": False}]
ASKED = {**SET[0], "more": 1, "set": SET}


def click(pick, step):
    return json.dumps({"pick": pick, "question": ASKED["question"], "step": step})


def walk(*clicks, provider=None):
    """Send clicks in turn the way the daemon does -> the keys typed for each."""
    answered, typed = None, []
    for pick, step in clicks:
        keys = answer_keys(click(pick, step), ASKED, answered, provider)
        typed.append(keys)
        if keys is not None:
            answered = next_answered(ASKED, answered)
    return typed


def test_each_step_types_its_pick_and_submit_types_one():
    assert walk((2, 0), (1, 1), (1, "submit")) == [[LEFT, LEFT, "2"], [LEFT, LEFT, RIGHT, "1"], [RIGHT, RIGHT, "1"]]


def test_a_codex_set_types_each_pick_alone_since_its_arrow_keys_were_never_measured():
    assert walk((2, 0), (1, 1), (1, "submit"), provider="openai") == [["2"], ["1"], ["1"]]


def test_a_double_click_on_a_step_types_nothing_the_second_time():
    assert walk((2, 0), (3, 0)) == [[LEFT, LEFT, "2"], None]


def test_a_click_for_a_later_step_before_the_earlier_one_types_nothing():
    assert walk((1, 1)) == [None]


def test_a_pick_past_the_steps_own_options_types_nothing():
    assert walk((2, 0), (3, 1)) == [[LEFT, LEFT, "2"], None]


def test_submit_before_the_last_question_types_nothing():
    assert walk((2, 0), (1, "submit")) == [[LEFT, LEFT, "2"], None]


def test_cancel_on_the_submit_step_is_never_typed():
    assert walk((2, 0), (1, 1), (2, "submit")) == [[LEFT, LEFT, "2"], [LEFT, LEFT, RIGHT, "1"], None]


def test_nothing_is_typed_once_the_set_is_submitted():
    assert walk((2, 0), (1, 1), (1, "submit"), (1, 0))[3] is None


def test_a_set_answered_is_remembered_while_it_stands_and_forgotten_once_it_closes():
    answered = {"s1": next_answered(ASKED, None)}
    standing = {"groups": [{"name": "AGENTS", "rows": [{"session_id": "s1", "question": ASKED}]}]}
    closed = {"groups": [{"name": "AGENTS", "rows": [{"session_id": "s1"}]}]}
    assert still_answered(answered, standing) == answered
    assert still_answered(answered, closed) == {}


def test_a_second_submit_types_nothing():
    assert walk((2, 0), (1, 1), (1, "submit"), (1, "submit"))[3] is None


def test_a_single_digit_on_a_multi_select_step_types_nothing():
    global ASKED
    kept = ASKED
    ASKED = {**SET[0], "more": 1, "set": [SET[0], dict(SET[1], multi=True)]}
    try:
        assert walk((2, 0), (1, 1)) == [[LEFT, LEFT, "2"], None]
    finally:
        ASKED = kept
