"""Tests for the pure parts of account meters: pace, usage parsing, planning.

Expected values are worked by hand from the rules in docs/accounts-design.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from accounts import (StoreError, SwitchRefused, account_for, claude_paths, merge_credential, needs_refresh, nickname,
                      next_poll, pace, parse_store, parse_usage, plan_switch, should_resync)

WEEK = 604800


def test_pace_halfway_through_the_week_expects_half_used():
    result = pace(used=40, resets_at=WEEK // 2, fetched_at=0)
    assert result == {"expected": 50.0, "ahead": False, "runs_out": False}


def test_pace_twenty_points_over_expected_is_ahead_and_runs_out():
    result = pace(used=70, resets_at=WEEK // 2, fetched_at=0)
    assert result == {"expected": 50.0, "ahead": True, "runs_out": True}


def test_pace_fourteen_points_over_is_not_yet_ahead():
    assert pace(used=64, resets_at=WEEK // 2, fetched_at=0)["ahead"] is False


def test_pace_is_silent_in_the_first_day_after_a_reset():
    assert pace(used=10, resets_at=WEEK - 3600, fetched_at=0) is None


def test_pace_is_silent_at_the_reset_instant():
    assert pace(used=10, resets_at=1000, fetched_at=1000) is None


#: Shape of GET /api/oauth/usage, as claude-swap 0.22.0 reads it (oauth.py:430-500).
USAGE = {
    "five_hour": {"utilization": 19.0, "resets_at": "2026-09-15T12:00:00+00:00"},
    "seven_day": {"utilization": 33.5, "resets_at": "2026-09-18T07:00:00.000000Z"},
    "limits": [
        {"kind": "weekly_scoped", "percent": 50,
         "scope": {"model": {"display_name": "Fable"}},
         "resets_at": "2026-09-18T07:00:00+00:00"},
    ],
}


def test_parse_usage_reads_both_windows_and_every_model_limit():
    assert parse_usage(USAGE) == {
        "five_hour": {"used": 19.0, "resets_at": 1789473600},
        "seven_day": {"used": 33.5, "resets_at": 1789714800},
        "models": [{"name": "Fable", "used": 50.0, "resets_at": 1789714800}],
    }


def test_parse_usage_leaves_out_a_window_the_response_lacks():
    assert parse_usage({"seven_day": USAGE["seven_day"]}) == {
        "five_hour": None,
        "seven_day": {"used": 33.5, "resets_at": 1789714800},
        "models": [],
    }


def test_parse_usage_keeps_a_reading_whose_reset_time_is_unreadable():
    raw = {"five_hour": {"utilization": 19.0, "resets_at": "soon"}}
    assert parse_usage(raw)["five_hour"] == {"used": 19.0, "resets_at": None}


def test_parse_usage_skips_limits_without_a_model_name_or_a_number():
    raw = {"limits": [
        {"percent": 10, "scope": {}},
        {"percent": "ten", "scope": {"model": {"display_name": "Opus"}}},
        "junk",
    ]}
    assert parse_usage(raw)["models"] == []


def test_parse_usage_refuses_a_response_that_is_not_an_object():
    assert parse_usage(["not", "usage"]) is None


def _store(*accounts, version=1):
    return json.dumps({"version": version, "accounts": list(accounts)})


ALICE = {"id": "a1", "alias": "work", "accountUuid": "uuid-alice",
         "organizationUuid": "org-1", "organizationName": "Example Org",
         "added": 1789400000, "lastSynced": 1789473600}


def test_parse_store_reads_its_accounts_in_order():
    bob = {"id": "b2", "alias": None, "accountUuid": "uuid-bob"}
    assert parse_store(_store(ALICE, bob)) == [ALICE, bob]


def test_parse_store_without_a_file_has_no_accounts():
    assert parse_store(None) == []


@pytest.mark.parametrize("text, reason", [
    ('{"version": 1, "accounts": [', "not valid JSON"),
    (_store(ALICE, version=2), "unknown store version 2"),
    (json.dumps({"version": 1}), "accounts is not a list"),
    (_store({"alias": "x", "accountUuid": "u"}), "account 1 has no id"),
    (_store({"id": "a1", "accountUuid": 7}), "account a1 has no accountUuid"),
    (_store(ALICE, dict(ALICE, accountUuid="uuid-other")), "account id a1 appears twice"),
    (_store(ALICE, dict(ALICE, id="a2")), "account uuid-alice is stored twice"),
])
def test_parse_store_refuses_a_file_it_cannot_trust(text, reason):
    with pytest.raises(StoreError, match=reason):
        parse_store(text)


def test_next_poll_after_a_still_good_reading_stops_at_the_ceiling():
    assert next_poll(interval=900, outcome="ok", now=1000, jitter=0) == {"interval": 600, "at": 1600}


def test_next_poll_after_a_failure_backs_off_by_half_again():
    assert next_poll(interval=600, outcome="failed", now=1000, jitter=0) == {"interval": 900, "at": 1900}


def test_next_poll_backoff_stops_at_half_an_hour_even_with_jitter():
    assert next_poll(interval=1500, outcome="failed", now=0) == {"interval": 1800, "at": 1800}


def test_next_poll_after_a_429_holds_off_for_an_hour():
    assert next_poll(interval=600, outcome="rate_limited", now=1000) == {"interval": 600, "at": 4600}


def test_next_poll_refuses_an_outcome_it_does_not_know():
    with pytest.raises(ValueError):
        next_poll(interval=600, outcome="maybe", now=0)


def test_needs_refresh_when_an_inactive_token_is_within_five_minutes_of_expiry():
    assert needs_refresh(expires_at_ms=1_300_000, active=False, now=1000) is True


def test_needs_refresh_not_while_the_token_has_longer_to_live():
    assert needs_refresh(expires_at_ms=1_301_000, active=False, now=1000) is False


def test_needs_refresh_never_for_the_active_account():
    assert needs_refresh(expires_at_ms=0, active=True, now=1000) is False


def test_needs_refresh_when_the_expiry_is_unknown():
    assert needs_refresh(expires_at_ms=None, active=False, now=1000) is True


def _oauth(refresh):
    return {"accessToken": "access-" + refresh, "refreshToken": refresh,
            "expiresAt": 1789473600000, "scopes": ["user:inference"]}


def test_merge_credential_takes_the_account_from_the_target_and_the_rest_from_live():
    live = {"claudeAiOauth": _oauth("live"), "mcpOAuth": {"server": "machine"}, "pluginSecrets": {"p": 1}}
    target = {"claudeAiOauth": _oauth("target"), "mcpOAuth": {"server": "stale"}}
    assert merge_credential(target, live) == {
        "claudeAiOauth": _oauth("target"), "mcpOAuth": {"server": "machine"}, "pluginSecrets": {"p": 1}}


def test_merge_credential_refuses_a_target_without_an_account_token():
    with pytest.raises(ValueError):
        merge_credential({"mcpOAuth": {}}, {"claudeAiOauth": _oauth("live")})


def test_account_for_finds_the_stored_account_the_live_login_belongs_to():
    bob = {"id": "b2", "accountUuid": "uuid-bob"}
    assert account_for([ALICE, bob], {"accountUuid": "uuid-bob"}) is bob


def test_account_for_is_none_for_a_login_the_store_does_not_know():
    assert account_for([ALICE], {"accountUuid": "uuid-carol"}) is None
    assert account_for([ALICE], None) is None


def test_should_resync_when_claude_code_has_rotated_the_active_token():
    assert should_resync({"claudeAiOauth": _oauth("r1")}, {"claudeAiOauth": _oauth("r2")}) is True


def test_should_resync_not_when_the_copy_is_already_current():
    assert should_resync({"claudeAiOauth": _oauth("r1")}, {"claudeAiOauth": _oauth("r1")}) is False


def test_should_resync_not_from_a_live_item_without_a_refresh_token():
    assert should_resync({"claudeAiOauth": _oauth("r1")}, {"claudeAiOauth": {"accessToken": "a"}}) is False


BOB = {"id": "b2", "alias": "home", "accountUuid": "uuid-bob"}


def test_plan_switch_refreshes_then_writes_under_claude_codes_locks_in_their_order():
    plan = plan_switch([ALICE, BOB], "b2", {"accountUuid": "uuid-alice"},
                       claude_dir="/home/x/.claude", claude_json="/home/x/.claude.json")
    assert plan["steps"] == [
        ("refresh", "b2"),
        ("lock", "/home/x/.claude/.oauth_refresh.lock", 60),
        ("lock", "/home/x/.claude.lock", 60),
        ("read_live",),
        ("verify_live_is", "a1"),
        ("backup_live_credential", "a1"),
        ("write_live_credential", "b2"),
        ("lock", "/home/x/.claude.json.lock", 10),
        ("write_oauth_account", "b2"),
        ("unlock", "/home/x/.claude.json.lock"),
        ("unlock", "/home/x/.claude.lock"),
        ("unlock", "/home/x/.claude/.oauth_refresh.lock"),
    ]


@pytest.mark.parametrize("target, live, accounts, reason", [
    ("c3", {"accountUuid": "uuid-alice"}, [ALICE, BOB], "no stored account c3"),
    ("a1", {"accountUuid": "uuid-alice"}, [ALICE, BOB], "work is already active"),
    ("b2", {"accountUuid": "uuid-carol"}, [ALICE, BOB], "the current login is not a stored account"),
    ("b2", None, [ALICE, BOB], "the current login is not a stored account"),
    ("b2", {"accountUuid": "uuid-alice"}, [ALICE, dict(BOB, needsLogin=True)], "log in to home again"),
])
def test_plan_switch_refuses_before_touching_anything(target, live, accounts, reason):
    with pytest.raises(SwitchRefused, match=reason):
        plan_switch(accounts, target, live, claude_dir="/c", claude_json="/c.json")


def test_plan_switch_says_how_to_undo_each_write_to_claude_codes_login():
    plan = plan_switch([ALICE, BOB], "b2", {"accountUuid": "uuid-alice"},
                       claude_dir="/c", claude_json="/c.json")
    assert plan["undo"] == {
        "write_live_credential": ("restore_live_credential",),
        "write_oauth_account": ("restore_oauth_account",),
    }


def test_claude_paths_default_to_the_home_directory():
    assert claude_paths({}, "/home/x", exists=lambda p: False) == ("/home/x/.claude", "/home/x/.claude.json")


def test_claude_paths_follow_claude_config_dir():
    assert claude_paths({"CLAUDE_CONFIG_DIR": "/cfg"}, "/home/x", exists=lambda p: False) == ("/cfg", "/cfg/.claude.json")


def test_claude_paths_prefer_a_legacy_config_json_when_one_exists():
    assert claude_paths({}, "/home/x", exists=lambda p: p == "/home/x/.claude/.config.json") == (
        "/home/x/.claude", "/home/x/.claude/.config.json")


def test_plan_switch_names_the_legacy_lock_after_the_resolved_config_directory():
    """Claude Code takes `${realpath(configDir)}.lock`, so a symlinked ~/.claude locks its target."""
    plan = plan_switch([ALICE, BOB], "b2", {"accountUuid": "uuid-alice"},
                       claude_dir="/home/x/.claude", claude_json="/home/x/.claude.json",
                       claude_dir_resolved="/dotfiles/claude")
    locks = [step[1] for step in plan["steps"] if step[0] == "lock"]
    assert locks == ["/home/x/.claude/.oauth_refresh.lock", "/dotfiles/claude.lock", "/home/x/.claude.json.lock"]


@pytest.mark.parametrize("text, alias", [("  work  ", "work"), ("", None), ("   ", None)])
def test_nickname_trims_and_an_empty_one_clears_back_to_the_default(text, alias):
    assert nickname(text) == alias


def test_nickname_refuses_one_too_long_for_the_panel():
    with pytest.raises(ValueError, match="40 characters"):
        nickname("x" * 41)
