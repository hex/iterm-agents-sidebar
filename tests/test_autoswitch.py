"""Deciding when the daemon switches accounts on its own, and to which.

Pure: readings and the clock are passed in, so each case is a worked example.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import (binding, burn_rates, confirm_balance, exhausted_models, runs_out, switch_decision,
                      switch_outlook)

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


def test_quota_about_to_return_unused_is_worth_moving_to_before_anything_is_full():
    """Asked 2026-09-22: "get the most of our account limits and make them last
    longer". 80 points that return in an hour are spent there, not the 70 that
    have to last six days."""
    states = {"acct-1": state(usage(30, 30, 20, week_reset=NOW + 6 * DAY)),
              "acct-2": state(usage(20, 20, 20, week_reset=NOW + HOUR))}
    assert decide(states, (A, B)) == {
        "act": "balance", "account_id": "acct-2", "why": "weekly: 80% left for 1h there, 70% for 6d here"}


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


def test_a_full_account_takes_any_emptier_one_when_none_is_ten_points_better():
    """Asked 2026-09-22 with the strip at work 94, hex 90, home 100: holding for
    three days spends nothing. When no account is ten points better, a strictly
    emptier one under 100 still gives the session more room than the one it is
    on."""
    states = {"acct-1": state(usage(95, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B)) == {"act": "switch", "account_id": "acct-2", "why": "5-hour at 95%"}


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


# Which windows count. Asked 2026-09-22: "this puts a heavy accent on fable
# and I don't understand why". A model's own weekly limit only binds while a
# session runs that model; the 5-hour and the weekly bind always.

def test_a_model_limit_no_session_runs_decides_nothing():
    assert binding(usage(30, 40, 100), NOW, models={"opus"}) == {
        "figure": 40, "window": "weekly", "resets_at": NOW + 3 * DAY}


def test_a_model_limit_a_session_runs_still_binds():
    assert binding(usage(30, 40, 95), NOW, models={"fable"})["window"] == "Fable"


def test_sessions_on_another_model_are_not_pushed_off_an_account_by_its_fable_limit():
    """The strip on 2026-09-22, with every session on Opus: Fable at 94 forces
    nothing. What moves them is home's week coming back in 19 hours."""
    states = {"acct-1": state(usage(49, 63, 94, week_reset=NOW + 2 * DAY)),
              "acct-2": state(usage(0, 51, 90)),
              "acct-3": state(usage(0, 81, 100, week_reset=NOW + 19 * HOUR))}
    assert switch_decision("acct-1", states, [A, B, C], NOW, models={"opus"}) == {
        "act": "balance", "account_id": "acct-3", "why": "weekly: 19% left for 19h there, 37% for 2d here"}


# A model limit full on every account. No switch can help it, so it leaves the
# decision and is reported with its first reset instead.

ALL_FABLE_FULL = {"acct-1": state(usage(49, 63, 100, week_reset=NOW + 2 * DAY)),
                  "acct-2": state(usage(0, 51, 100)),
                  "acct-3": state(usage(0, 81, 100, week_reset=NOW + 19 * HOUR))}


def test_a_model_limit_full_on_every_account_is_exhausted_and_says_when_it_returns():
    assert exhausted_models(ALL_FABLE_FULL, [A, B, C], NOW) == [
        {"model": "Fable", "resets_at": NOW + 19 * HOUR, "account_id": "acct-3"}]


def test_an_account_not_read_keeps_a_model_from_counting_as_exhausted():
    states = dict(ALL_FABLE_FULL, **{"acct-3": {"outcome": "failed", "usage": None}})
    assert exhausted_models(states, [A, B, C], NOW) == []


def test_an_account_that_needs_a_login_does_not_hold_a_model_back_from_exhausted():
    states = dict(ALL_FABLE_FULL, **{"acct-3": {"outcome": "needs_login", "usage": None}})
    assert [m["model"] for m in exhausted_models(states, [A, B, dict(C, needsLogin=True)], NOW)] == ["Fable"]


def test_sessions_only_on_an_exhausted_model_have_nothing_to_switch_for():
    assert switch_decision("acct-1", ALL_FABLE_FULL, [A, B, C], NOW, models={"fable"}) == {
        "act": "blocked", "why": "Fable is full on every account"}


def test_an_exhausted_model_leaves_the_other_windows_to_decide():
    states = dict(ALL_FABLE_FULL, **{"acct-1": state(usage(92, 63, 100, week_reset=NOW + 2 * DAY))})
    assert switch_decision("acct-1", states, [A, B, C], NOW, models={"fable", "opus"}) == {
        "act": "switch", "account_id": "acct-3", "why": "5-hour at 92%"}, "the week that returns first"


def test_the_outlook_names_an_exhausted_model():
    got = switch_outlook("acct-1", ALL_FABLE_FULL, [A, B, C], NOW, models={"fable"})
    assert got["exhausted"] == [{"model": "Fable", "resets_at": NOW + 19 * HOUR, "account_id": "acct-3"}]


def test_the_strip_of_2026_09_22_moves_to_the_emptier_fable_limit():
    states = {"acct-1": state(usage(49, 63, 94, week_reset=NOW + 2 * DAY)),
              "acct-2": state(usage(0, 51, 90)),
              "acct-3": state(usage(0, 81, 100, week_reset=NOW + 19 * HOUR))}
    assert switch_decision("acct-1", states, [A, B, C], NOW, models={"fable"}) == {
        "act": "switch", "account_id": "acct-2", "why": "Fable at 94%"}


def test_a_full_account_never_moves_to_one_just_as_full():
    states = {"acct-1": state(usage(95, 10, 10)), "acct-2": state(usage(95, 10, 10)),
              "acct-3": state(usage(20, 20, 100))}
    assert decide(states) == {"act": "blocked", "why": "every account is full"}


def test_between_roomy_targets_the_weekly_quota_that_returns_sooner_is_spent_first():
    """40 points a day left on one, 12 on the other: the first goes back to
    100 tomorrow whether it is used or not."""
    states = {"acct-1": state(usage(92, 10, 10)),
              "acct-2": state(usage(10, 40, 40, week_reset=NOW + 5 * DAY)),
              "acct-3": state(usage(10, 60, 60, week_reset=NOW + DAY))}
    assert decide(states)["account_id"] == "acct-3"


def test_an_account_under_the_amber_band_beats_more_runway_above_it():
    states = {"acct-1": state(usage(92, 10, 10)),
              "acct-2": state(usage(75, 20, 20, week_reset=NOW + HOUR)),
              "acct-3": state(usage(30, 60, 60, week_reset=NOW + 5 * DAY))}
    assert decide(states)["account_id"] == "acct-3"


# Balancing while nothing is full. Each move costs a session about half a
# minute of pickup, so it takes a clear gain, a quiet half hour since the last
# switch, and the same answer on two readings.

CALM = {"acct-1": state(usage(20, 60, 60, week_reset=NOW + 3 * DAY)),
        "acct-2": state(usage(10, 30, 30, week_reset=NOW + 3 * DAY))}


def test_a_clearly_roomier_account_is_proposed_as_a_balance():
    """40 points over three days against 70: 1.75 times the runway."""
    assert decide(CALM, (A, B)) == {
        "act": "balance", "account_id": "acct-2", "why": "weekly: 70% left for 3d there, 40% for 3d here"}


def test_a_small_gain_is_not_worth_a_balance():
    states = dict(CALM, **{"acct-2": state(usage(10, 55, 55, week_reset=NOW + 3 * DAY))})
    assert decide(states, (A, B)) == STAY_ACT


def test_a_balance_only_goes_to_an_account_under_the_amber_band():
    states = dict(CALM, **{"acct-2": state(usage(75, 30, 30, week_reset=NOW + 3 * DAY))})
    assert decide(states, (A, B)) == STAY_ACT


def test_a_balance_waits_half_an_hour_after_any_switch():
    assert decide(CALM, (A, B), last_switch={"at": NOW - 20 * 60}) == STAY_ACT
    assert decide(CALM, (A, B), last_switch={"at": NOW - 31 * 60})["act"] == "balance"


def test_a_balance_never_asks_for_a_reading():
    states = dict(CALM, **{"acct-2": state(usage(10, 30, 30, week_reset=NOW + 3 * DAY), fetched_at=NOW - 20 * 60)})
    assert decide(states, (A, B)) == STAY_ACT


def test_no_reset_time_means_no_balance():
    bare = {"five_hour": {"used": 20, "resets_at": None}, "seven_day": {"used": 60, "resets_at": None}}
    states = dict(CALM, **{"acct-1": state(bare)})
    assert decide(states, (A, B)) == STAY_ACT


PROPOSED = {"act": "balance", "account_id": "acct-2", "why": "w"}


def test_a_balance_is_taken_on_the_second_reading_that_proposes_it():
    streak, go = confirm_balance(None, PROPOSED, NOW)
    assert go is False
    streak, go = confirm_balance(streak, PROPOSED, NOW)
    assert go is False, "the same reading twice is one comparison"
    streak, go = confirm_balance(streak, PROPOSED, NOW + 300)
    assert go is True


def test_a_different_answer_starts_the_count_again():
    streak, _ = confirm_balance(None, PROPOSED, NOW)
    streak, go = confirm_balance(streak, dict(PROPOSED, account_id="acct-3"), NOW + 300)
    assert go is False
    assert confirm_balance(streak, STAY_ACT, NOW + 600) == (None, False)


def test_the_panel_is_told_which_account_an_exhausted_model_returns_on_first():
    from accounts import meters_snapshot
    outlook = switch_outlook("acct-1", ALL_FABLE_FULL, [A, B, C], NOW, models={"fable"})
    shaped = meters_snapshot([dict(A, alias="work"), dict(B, alias="hex"), dict(C, alias="home")],
                             ALL_FABLE_FULL, "acct-1", next_switch=outlook)
    assert shaped["next_switch"]["exhausted"] == [
        {"model": "Fable", "resets_at": NOW + 19 * HOUR, "account_id": "acct-3", "account": "home"}]


def test_weekly_room_about_to_return_is_spent_even_when_the_week_is_mostly_used():
    """The strip of 2026-09-23 with every session on Opus: home has 19% of its
    week left and gets it all back in three hours. Its 5-hour window is empty,
    so nothing stops it spending that before the reset."""
    states = {"acct-1": state(usage(0, 64, 96, week_reset=NOW + 2 * DAY)),
              "acct-2": state(usage(0, 51, 90, week_reset=NOW + 2 * DAY)),
              "acct-3": state(usage(0, 81, 100, week_reset=NOW + 3 * HOUR))}
    assert switch_decision("acct-1", states, [A, B, C], NOW, models={"opus"}) == {
        "act": "balance", "account_id": "acct-3", "why": "weekly: 19% left for 3h there, 36% for 2d here"}


def test_two_nearly_full_accounts_do_not_trade_the_login_back_and_forth():
    """96 against 95: the move would buy one point and cost half a minute of
    pickup, and the next reading could send it straight back."""
    states = {"acct-1": state(usage(96, 10, 10)), "acct-2": state(usage(95, 10, 10))}
    assert decide(states, (A, B)) == STAY_ACT


# Codex review of 2026-09-23: cases the first build got wrong.

def test_a_balance_never_goes_to_an_account_already_on_course_to_fill():
    """Its last two readings show it filling: 35 then 65 in three minutes, so
    it would be full within four minutes of that reading."""
    rising = state(usage(65, 20, 20, week_reset=NOW + DAY), fetched_at=NOW - 60,
                   earlier=usage(35, 20, 20, week_reset=NOW + DAY), earlier_at=NOW - 240)
    states = {"acct-1": state(usage(20, 60, 60, week_reset=NOW + 3 * DAY)), "acct-2": rising}
    assert decide(states, (A, B)) == STAY_ACT


def test_an_account_whose_5_hour_window_is_unknown_is_no_balance_target():
    blind = {"five_hour": None, "seven_day": {"used": 20, "resets_at": NOW + DAY}, "models": []}
    states = {"acct-1": state(usage(20, 60, 60, week_reset=NOW + 3 * DAY)), "acct-2": state(blind)}
    assert decide(states, (A, B)) == STAY_ACT


def test_a_weekly_limit_without_a_reset_time_leaves_the_runway_unknown():
    partial = {"five_hour": {"used": 10, "resets_at": NOW + HOUR},
               "seven_day": {"used": 20, "resets_at": NOW + DAY},
               "models": [{"name": "Fable", "used": 89, "resets_at": None}]}
    states = {"acct-1": state(usage(20, 60, 60, week_reset=NOW + 3 * DAY)), "acct-2": state(partial)}
    assert switch_decision("acct-1", states, [A, B], NOW, models={"fable"}) == STAY_ACT


def test_an_old_reading_cannot_declare_a_model_full_everywhere():
    states = dict(ALL_FABLE_FULL, **{"acct-2": state(usage(0, 51, 100), fetched_at=NOW - 2 * HOUR,
                                                    outcome="failed", tried_at=NOW - 60)})
    assert exhausted_models(states, [A, B, C], NOW) == []


def test_with_no_claude_session_running_nothing_switches():
    assert switch_decision("acct-1", CALM, [A, B], NOW, models=set()) == STAY_ACT


def test_the_outlook_promises_no_switch_when_only_an_exhausted_model_runs():
    states = dict(ALL_FABLE_FULL, **{"acct-1": state(usage(92, 63, 100, week_reset=NOW + 2 * DAY))})
    got = switch_outlook("acct-1", states, [A, B, C], NOW, models={"fable"})
    assert (got["to"], got["near"]) == (None, False)
    assert got["exhausted"][0]["model"] == "Fable"
