"""Scheduling account readings and shaping them for the panel.

Pure: time and outcomes are passed in, so each case is a worked example.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import due, meters_snapshot, record

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


def test_record_keeps_a_good_reading_and_waits_the_floor():
    assert record(None, "ok", USAGE, now=0) == {
        "interval": 600, "next_at": 600, "outcome": "ok", "usage": USAGE, "fetched_at": 0}


def test_record_keeps_the_last_good_reading_through_a_failure():
    good = record(None, "ok", USAGE, now=0)
    assert record(good, "failed", None, now=600) == {
        "interval": 900, "next_at": 1500, "outcome": "failed", "usage": USAGE, "fetched_at": 0}


def test_record_holds_off_an_hour_after_a_429():
    assert record(None, "rate_limited", None, now=0)["next_at"] == 3600


def test_record_counts_a_refused_token_as_a_failure_for_scheduling():
    assert record(None, "unauthorized", None, now=0)["next_at"] == 900


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
        "active": None, "accounts": [], "error": "store is not valid JSON"}
