"""Scheduling account readings and shaping them for the panel.

Pure: time and outcomes are passed in, so each case is a worked example.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import due, meters_snapshot, record, read_now_states

WEEK = 604800
A1 = {"id": "acct-1", "alias": "work", "accountUuid": "u1"}
A2 = {"id": "acct-2", "alias": None, "accountUuid": "u2"}
USAGE = {"five_hour": {"used": 19.0, "resets_at": 5000},
         "seven_day": {"used": 70.0, "resets_at": WEEK // 2},
         "models": [{"name": "Fable", "used": 40.0, "resets_at": WEEK // 2}]}


def test_an_account_never_read_is_due_at_once():
    assert due([A1, A2], {"acct-1": {"next_at": 900}}, now=100) == ["acct-2"]


def test_an_account_is_due_once_its_next_reading_time_arrives():
    assert due([A1], {"acct-1": {"next_at": 900}}, now=900) == ["acct-1"]


def moved(usage, by):
    """The same usage with its worst window moved by `by` points."""
    weekly = dict(usage["seven_day"], used=usage["seven_day"]["used"] + by)
    return dict(usage, seven_day=weekly)


def test_record_keeps_a_first_good_reading_and_waits_the_floor():
    """Three minutes: the endpoint admits about thirty requests an hour per
    account (cswap's measurement), and one every three minutes leaves room
    for cswap and for a reading asked for by hand."""
    assert record(None, "ok", USAGE, now=0, jitter=0) == {
        "interval": 180, "next_at": 180, "outcome": "ok", "usage": USAGE, "fetched_at": 0,
        "earlier_usage": None, "earlier_at": None, "tried_at": 0}


def test_record_keeps_the_reading_before_this_one_and_when_it_tried():
    first = record(None, "ok", USAGE, now=0, jitter=0)
    second = record(first, "ok", moved(USAGE, 2), now=180, jitter=0)
    assert (second["earlier_usage"], second["earlier_at"], second["tried_at"]) == (USAGE, 0, 180)


def test_a_failed_reading_keeps_both_readings_and_moves_only_the_attempt():
    first = record(None, "ok", USAGE, now=0, jitter=0)
    second = record(first, "ok", moved(USAGE, 2), now=180, jitter=0)
    third = record(second, "failed", None, now=400, jitter=0)
    assert (third["earlier_at"], third["fetched_at"], third["tried_at"]) == (0, 180, 400)


def test_a_window_that_moved_pulls_the_next_reading_in():
    """Usage moving a point or more between readings means someone is
    spending it; the interval halves toward the floor."""
    rested = dict(record(None, "ok", USAGE, now=0, jitter=0), interval=600, next_at=600)
    again = record(rested, "ok", moved(USAGE, 1.5), now=600, jitter=0)
    assert (again["interval"], again["next_at"]) == (300, 900)


def test_a_window_that_sits_still_lets_the_interval_grow_to_its_ceiling():
    """Five minutes for the account the sessions run on, ten for the others."""
    first = record(None, "ok", USAGE, now=0, jitter=0)
    second = record(first, "ok", USAGE, now=180, jitter=0, active=True)
    assert second["interval"] == 270
    third = record(second, "ok", USAGE, now=450, jitter=0, active=True)
    assert third["interval"] == 300
    other = record(dict(third, interval=500), "ok", USAGE, now=750, jitter=0, active=False)
    assert other["interval"] == 600


def test_a_reading_is_never_scheduled_past_a_known_reset():
    """Stored usage is wrong the moment a window rolls over, so the next
    reading lands a minute after the nearest reset if that is sooner."""
    soon = dict(USAGE, five_hour={"used": 19.0, "resets_at": 100})
    assert record(None, "ok", soon, now=0, jitter=0)["next_at"] == 160


def test_jitter_spreads_readings_so_two_pollers_do_not_line_up():
    a = record(None, "ok", USAGE, now=0, jitter=0.1)
    assert 180 <= a["interval"] <= 198


def test_record_keeps_the_last_good_reading_through_a_failure():
    good = record(None, "ok", USAGE, now=0, jitter=0)
    assert record(good, "failed", None, now=180, jitter=0) == {
        "interval": 270, "next_at": 450, "outcome": "failed", "usage": USAGE, "fetched_at": 0,
        "earlier_usage": None, "earlier_at": None, "tried_at": 180}


def test_record_holds_off_an_hour_after_a_429():
    assert record(None, "rate_limited", None, now=0, jitter=0)["next_at"] == 3600


def test_record_counts_a_refused_token_as_a_failure_for_scheduling():
    assert record(None, "unauthorized", None, now=0, jitter=0)["next_at"] == 270


def test_a_reading_asked_for_by_hand_is_due_now_unless_one_is_under_three_minutes_old():
    """The reload button asks for readings now; an account read within the
    floor is served as it is, so a button held down cannot spend the budget."""
    states = {"acct-1": {"next_at": 900, "fetched_at": 100, "interval": 600},
              "acct-2": {"next_at": 900, "fetched_at": 800, "interval": 600}}
    fresh = read_now_states(states, now=900)
    assert fresh["acct-1"]["next_at"] == 0
    assert fresh["acct-2"]["next_at"] == 900


def test_meters_snapshot_names_accounts_and_marks_the_active_one():
    snap = meters_snapshot([A1, A2], {}, active_id="acct-2")
    assert snap["active"] == "acct-2"
    assert [(a["id"], a["name"], a["active"]) for a in snap["accounts"]] == [
        ("acct-1", "work", False), ("acct-2", "Account 2", True)]


def test_meters_snapshot_names_an_account_without_an_alias_by_its_email():
    snap = meters_snapshot([A1, A2, dict(A2, id="acct-3")], {}, active_id=None,
                           emails={"acct-1": "jane.roe@example.com", "acct-2": "john.doe@example.com"})
    assert [a["name"] for a in snap["accounts"]] == ["work", "john.doe@example.com", "Account 3"]
    assert [(a["alias"], a["default_name"]) for a in snap["accounts"]] == [
        ("work", "jane.roe@example.com"), (None, "john.doe@example.com"), (None, "Account 3")]


def test_meters_snapshot_carries_weekly_pace_from_the_time_of_the_reading():
    states = {"acct-1": record(None, "ok", USAGE, now=0)}
    account = meters_snapshot([A1], states, active_id="acct-1")["accounts"][0]
    assert account["fetched_at"] == 0
    assert account["five_hour"] == {"used": 19.0, "resets_at": 5000}
    assert account["seven_day"] == {"used": 70.0, "resets_at": WEEK // 2,
                                    "pace": {"expected": 50.0, "ahead": True, "runs_out": True}}
    assert account["models"] == [{"name": "Fable", "used": 40.0, "resets_at": WEEK // 2,
                                  "pace": {"expected": 50.0, "ahead": False, "runs_out": False}}]


def test_meters_snapshot_of_an_account_never_read_has_no_figures():
    account = meters_snapshot([dict(A2, needsLogin=True)], {}, active_id=None)["accounts"][0]
    assert account == {"id": "acct-2", "name": "Account 2", "alias": None, "default_name": "Account 2",
                       "active": False, "needs_login": True,
                       "outcome": None, "fetched_at": None, "five_hour": None, "seven_day": None,
                       "models": []}


def test_meters_snapshot_says_why_when_the_store_cannot_be_read():
    assert meters_snapshot([], {}, active_id=None, error="store is not valid JSON") == {
        "active": None, "accounts": [], "error": "store is not valid JSON", "last_switch": None,
        "next_switch": None}


def test_the_snapshot_names_the_last_switch():
    last = {"at": 500, "from": "acct-1", "to": "acct-2", "why": "Fable at 98%", "auto": True}
    snap = meters_snapshot([A1, A2], {}, active_id="acct-2", emails={"acct-2": "bob@example.com"},
                           last_switch=last)
    assert snap["last_switch"] == {"at": 500, "to": "bob@example.com", "why": "Fable at 98%", "auto": True}


def test_the_snapshot_names_where_the_next_switch_would_go():
    snap = meters_snapshot([A1, A2], {}, active_id="acct-1", emails={"acct-2": "bob@example.com"},
                           next_switch={"to": "acct-2", "near": True, "why": "Fable at 86%"})
    assert snap["next_switch"] == {"to": "bob@example.com", "near": True, "why": "Fable at 86%"}


def test_the_snapshot_carries_a_switch_with_nowhere_to_go():
    snap = meters_snapshot([A1], {}, active_id="acct-1",
                           next_switch={"to": None, "near": True, "why": "5-hour at 96%"})
    assert snap["next_switch"] == {"to": None, "near": True, "why": "5-hour at 96%"}
