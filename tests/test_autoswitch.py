"""Deciding when the daemon switches accounts on its own, and to which.

Pure: readings and the clock are passed in, so each case is a worked example.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import binding, burn_rates, runs_out, switch_decision, switch_outlook

NOW = 1_000_000
HOUR, DAY = 3600, 86400
STAY_ACT = {"act": "stay"}


def usage(five, seven, fable, five_reset=NOW + 4 * HOUR, week_reset=NOW + 3 * DAY):
    return {"five_hour": {"used": five, "resets_at": five_reset},
            "seven_day": {"used": seven, "resets_at": week_reset},
            "models": [{"name": "Fable", "used": fable, "resets_at": week_reset}]}


def test_the_binding_figure_is_the_fullest_window_and_says_which():
    assert binding(usage(30, 40, 95), NOW) == {
        "figure": 95, "window": "Fable", "resets_at": NOW + 3 * DAY}


def test_a_reading_whose_window_has_since_reset_says_nothing():
    assert binding(usage(20, 20, 100, week_reset=NOW - 1), NOW) is None


def test_no_reading_has_no_binding_figure():
    assert binding(None, NOW) is None


def test_a_window_that_rose_has_a_rate_in_points_a_second():
    rates = burn_rates(usage(74, 10, 10), NOW - 120, usage(80, 10, 10), NOW)
    assert rates == {"5-hour": 0.05, "weekly": 0.0, "Fable": 0.0}


def test_a_window_that_reset_between_readings_has_no_rate():
    earlier = usage(95, 10, 10, five_reset=NOW - 30)
    assert "5-hour" not in burn_rates(earlier, NOW - 120, usage(2, 10, 10), NOW)


def test_readings_under_a_minute_apart_give_no_rates():
    assert burn_rates(usage(74, 10, 10), NOW - 59, usage(80, 10, 10), NOW) == {}


def test_a_fall_is_not_a_negative_rate():
    assert burn_rates(usage(80, 10, 10), NOW - 120, usage(74, 10, 10), NOW)["5-hour"] == 0.0


def test_a_rising_window_runs_out_when_its_rate_carries_it_to_100():
    assert runs_out(usage(80, 10, 10), {"5-hour": 0.05}) == {"window": "5-hour", "seconds": 400.0}


def test_a_full_window_has_already_run_out():
    assert runs_out(usage(30, 30, 100), {}) == {"window": "Fable", "seconds": 0.0}


def test_a_window_that_resets_before_it_fills_does_not_run_out():
    soon = usage(80, 10, 10, five_reset=NOW + 300)
    assert runs_out(dict(soon, fetched_at=NOW), {"5-hour": 0.05}) is None


def test_nothing_rising_never_runs_out():
    assert runs_out(usage(92, 10, 10), {}) is None


def state(reading, fetched_at=NOW, earlier=None, earlier_at=None, outcome="ok", tried_at=None):
    return {"usage": reading, "fetched_at": fetched_at, "outcome": outcome,
            "earlier_usage": earlier, "earlier_at": earlier_at,
            "tried_at": fetched_at if tried_at is None else tried_at, "next_at": fetched_at + 180}


A, B, C = ({"id": "acct-1"}, {"id": "acct-2"}, {"id": "acct-3"})


def decide(states, accounts=(A, B, C), last_switch=None):
    return switch_decision("acct-1", states, list(accounts), NOW, last_switch)


def test_a_full_active_account_moves_to_the_emptiest_one():
    states = {"acct-1": state(usage(92, 40, 30)),
              "acct-2": state(usage(70, 60, 50, week_reset=NOW + 2 * HOUR)),
              "acct-3": state(usage(20, 20, 20, week_reset=NOW + 4 * DAY))}
    assert decide(states) == {"act": "switch", "account_id": "acct-3", "why": "5-hour at 92%"}


def test_an_account_with_its_fable_limit_spent_is_not_a_target():
    states = {"acct-1": state(usage(30, 40, 95)), "acct-2": state(usage(20, 20, 100)),
              "acct-3": state(usage(60, 50, 70))}
    assert decide(states) == {"act": "switch", "account_id": "acct-3", "why": "Fable at 95%"}


def test_a_sooner_reset_alone_moves_nothing():
    states = {"acct-1": state(usage(30, 30, 20, week_reset=NOW + 6 * DAY)),
              "acct-2": state(usage(20, 20, 20, week_reset=NOW + HOUR))}
    assert decide(states, (A, B)) == STAY_ACT


def test_between_near_equal_targets_the_sooner_reset_wins():
    states = {"acct-1": state(usage(92, 10, 10)),
              "acct-2": state(usage(40, 40, 40, five_reset=NOW + 5 * DAY, week_reset=NOW + 5 * DAY)),
              "acct-3": state(usage(42, 38, 41, five_reset=NOW + DAY, week_reset=NOW + DAY))}
    assert decide(states)["account_id"] == "acct-3"


def test_a_window_about_to_reset_is_waited_out():
    states = {"acct-1": state(usage(92, 10, 10, five_reset=NOW + 300)), "acct-2": state(usage(20, 20, 20))}
    assert decide(states, (A, B)) == STAY_ACT


def test_a_window_on_course_for_100_moves_before_the_threshold():
    rising = state(usage(80, 10, 10), earlier=usage(74, 10, 10), earlier_at=NOW - 120)
    assert decide({"acct-1": rising, "acct-2": state(usage(20, 20, 20))}, (A, B)) == {
        "act": "switch", "account_id": "acct-2", "why": "5-hour on course for 100% in 7 min"}


def test_a_target_less_than_ten_points_better_is_not_worth_the_move():
    states = {"acct-1": state(usage(95, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B)) == STAY_ACT


def test_nothing_moves_while_the_last_switch_is_still_landing():
    states = {"acct-1": state(usage(100, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B), last_switch={"at": NOW - 59}) == STAY_ACT


def test_a_full_account_is_left_inside_the_cooldown_for_anything_emptier():
    states = {"acct-1": state(usage(100, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B), last_switch={"at": NOW - 120}) == {
        "act": "switch", "account_id": "acct-2", "why": "5-hour at 100%"}


def test_the_cooldown_holds_an_ordinary_move():
    states = {"acct-1": state(usage(92, 10, 10)), "acct-2": state(usage(20, 20, 20))}
    assert decide(states, (A, B), last_switch={"at": NOW - 120}) == STAY_ACT


def test_a_target_read_long_ago_is_read_again_first():
    states = {"acct-1": state(usage(92, 10, 10)), "acct-2": state(usage(20, 20, 20), fetched_at=NOW - 400)}
    assert decide(states, (A, B)) == {"act": "read", "account_id": "acct-2"}


def test_a_target_whose_window_has_reset_is_read_again_first():
    spent = state(usage(20, 20, 100, week_reset=NOW - 60), fetched_at=NOW - 400)
    assert decide({"acct-1": state(usage(92, 10, 10)), "acct-2": spent}, (A, B)) == {
        "act": "read", "account_id": "acct-2"}


def test_a_target_that_was_just_tried_and_is_still_old_is_passed_over():
    tried = state(usage(20, 20, 20), fetched_at=NOW - 400, outcome="failed", tried_at=NOW - 20)
    assert decide({"acct-1": state(usage(92, 10, 10)), "acct-2": tried}, (A, B)) == {
        "act": "blocked", "why": "the other accounts cannot be read"}


def test_nowhere_emptier_is_said_not_acted_on():
    states = {"acct-1": state(usage(96, 10, 10)), "acct-2": state(usage(97, 10, 10)),
              "acct-3": state(usage(5, 5, 5))}
    accounts = (A, B, dict(C, needsLogin=True))
    assert decide(states, accounts) == {"act": "blocked", "why": "every account is full"}


def test_an_old_reading_of_the_active_account_decides_nothing():
    states = {"acct-1": state(usage(99, 10, 10), fetched_at=NOW - 400), "acct-2": state(usage(5, 5, 5))}
    assert decide(states, (A, B)) == STAY_ACT


def outlook(states, accounts=(A, B, C)):
    return switch_outlook("acct-1", states, list(accounts), NOW)


def test_the_outlook_names_where_a_switch_would_go_while_nothing_is_near():
    states = {"acct-1": state(usage(40, 30, 30)), "acct-2": state(usage(70, 60, 50)),
              "acct-3": state(usage(20, 20, 20))}
    assert outlook(states) == {"to": "acct-3", "near": False, "why": None}


def test_the_outlook_says_a_switch_is_near_within_ten_points_of_the_line():
    states = {"acct-1": state(usage(30, 40, 86)), "acct-2": state(usage(20, 20, 20))}
    assert outlook(states, (A, B)) == {"to": "acct-2", "near": True, "why": "Fable at 86%"}


def test_the_outlook_says_a_switch_is_near_when_a_window_is_on_course():
    rising = state(usage(80, 10, 10), earlier=usage(74, 10, 10), earlier_at=NOW - 120)
    assert outlook({"acct-1": rising, "acct-2": state(usage(20, 20, 20))}, (A, B)) == {
        "to": "acct-2", "near": True, "why": "5-hour on course for 100% in 7 min"}


def test_the_outlook_has_nowhere_to_go_when_every_account_is_full():
    states = {"acct-1": state(usage(96, 10, 10)), "acct-2": state(usage(20, 20, 100))}
    assert outlook(states, (A, B)) == {"to": None, "near": True, "why": "5-hour at 96%"}


def test_the_outlook_is_empty_without_a_reading_of_the_active_account():
    assert outlook({"acct-2": state(usage(20, 20, 20))}, (A, B)) is None
