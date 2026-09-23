"""One pass of the meter loop against real Keychain items and the real endpoints.

Scratch items stand in for Claude Code's credential and the panel's stored
ones. Every token is one that was never issued, so the endpoints refuse them
and nothing is spent.
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import AccountMeters, delete_secret, load_store, save_store, write_secret

SCRATCH_SERVICE = "agents-sidebar-test"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain and network")
FAR_FUTURE_MS = 4_000_000_000_000


def _credential(tag):
    return json.dumps({"claudeAiOauth": {"accessToken": f"never-issued-access-{tag}",
                                         "refreshToken": f"never-issued-refresh-{tag}",
                                         "expiresAt": FAR_FUTURE_MS}})


@pytest.fixture
def world(tmp_path):
    tag = uuid.uuid4().hex[:8]
    live = f"test-live-{tag}"
    accounts = [{"id": f"test-{tag}-1", "alias": "work", "accountUuid": "uuid-active"},
                {"id": f"test-{tag}-2", "alias": "home", "accountUuid": "uuid-other"}]
    store = str(tmp_path / "store" / "accounts.json")
    save_store(store, accounts)
    for account in accounts:
        write_secret(SCRATCH_SERVICE, account["id"], _credential(account["id"]))
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-active"}}))
    yield {"store": store, "live": live, "claude_json": str(claude_json), "accounts": accounts}
    for item in [live] + [a["id"] for a in accounts]:
        delete_secret(SCRATCH_SERVICE, item)
        delete_secret(SCRATCH_SERVICE, item + ".login")


def test_one_pass_reads_every_account_and_marks_a_dead_inactive_login(world):
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    snap = meters.snapshot()

    active, other = snap["accounts"]
    assert snap["active"] == active["id"] and active["active"]
    assert active["outcome"] in ("unauthorized", "rate_limited")
    assert not active["needs_login"], "the active login is Claude Code's to refresh, never ours"
    assert other["needs_login"], "a refused inactive token is refreshed, and the refresh is refused"
    assert load_store(world["store"])[1].get("needsLogin") is True


def test_one_pass_copies_a_rotated_active_token_into_the_panels_item(world):
    from accounts import read_secret
    rotated = _credential("rotated-by-claude-code")
    write_secret(SCRATCH_SERVICE, world["live"], rotated)
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert read_secret(SCRATCH_SERVICE, world["accounts"][0]["id"]) == rotated


def test_an_unreadable_store_is_reported_not_rebuilt(world):
    Path(world["store"]).write_text("{ torn")
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert meters.snapshot() == {"active": None, "accounts": [], "error": "store is not valid JSON",
                                 "last_switch": None, "next_switch": None, "live": None}
    assert Path(world["store"]).read_text() == "{ torn"


def test_adding_the_live_login_makes_it_due_and_names_it(world, tmp_path):
    other_store = str(tmp_path / "fresh" / "accounts.json")
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    meters = AccountMeters(other_store, SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    added = meters.add(now=1000)
    try:
        assert added == {"id": "acct-1", "name": "Account 1"}
        assert [a["accountUuid"] for a in load_store(other_store)] == ["uuid-active"]
        meters.tick(now=1000)
        assert meters.snapshot()["active"] == "acct-1"
    finally:
        delete_secret(SCRATCH_SERVICE, "acct-1")
        delete_secret(SCRATCH_SERVICE, "acct-1.login")


def test_one_pass_keeps_the_active_accounts_login_block_for_switching_back(world):
    from accounts import read_secret
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    login = {"accountUuid": "uuid-active", "emailAddress": "alice@example.com", "displayName": "Alice"}
    Path(world["claude_json"]).write_text(json.dumps({"oauthAccount": login}))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert json.loads(read_secret(SCRATCH_SERVICE, world["accounts"][0]["id"] + ".login")) == login


def test_one_pass_names_unaliased_accounts_by_the_email_in_their_login_block(world):
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    save_store(world["store"], [dict(a, alias=None) for a in world["accounts"]])
    Path(world["claude_json"]).write_text(json.dumps(
        {"oauthAccount": {"accountUuid": "uuid-active", "emailAddress": "alice@example.com"}}))
    write_secret(SCRATCH_SERVICE, world["accounts"][1]["id"] + ".login",
                 json.dumps({"accountUuid": "uuid-other", "emailAddress": "bob@example.com"}))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert [a["name"] for a in meters.snapshot()["accounts"]] == ["alice@example.com", "bob@example.com"]


def test_switching_through_the_meters_refuses_a_dead_target_and_says_so(world, tmp_path):
    from accounts import SwitchRefused, login_item
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    other = world["accounts"][1]["id"]
    write_secret(SCRATCH_SERVICE, login_item(other), json.dumps({"accountUuid": "uuid-other"}))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"], claude_dir=str(claude_dir))
    with pytest.raises(SwitchRefused, match="log in to home again"):
        meters.switch(other, now=1000)
    assert load_store(world["store"])[1]["needsLogin"] is True


def test_renaming_stores_the_nickname_and_an_empty_one_clears_it(world):
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    account_id = world["accounts"][1]["id"]
    assert meters.rename(account_id, " laptop ") == {"id": account_id, "name": "laptop"}
    assert load_store(world["store"])[1]["alias"] == "laptop"
    meters.rename(account_id, "")
    assert load_store(world["store"])[1]["alias"] is None


def test_renaming_an_account_the_store_does_not_have_is_refused(world):
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    with pytest.raises(ValueError, match="no stored account acct-99"):
        meters.rename("acct-99", "ghost")


def _reading(five, now):
    return {"usage": {"five_hour": {"used": five, "resets_at": now + 9000}, "seven_day": None, "models": []},
            "fetched_at": now, "tried_at": now, "outcome": "ok", "interval": 300,
            "next_at": now + 9000, "earlier_usage": None, "earlier_at": None}


def _meters_with_readings(world, tmp_path, active_five):
    from accounts import login_item
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    ids = [a["id"] for a in world["accounts"]]
    write_secret(SCRATCH_SERVICE, login_item(ids[1]), json.dumps({"accountUuid": "uuid-other"}))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"], claude_dir=str(claude_dir))
    meters.states = {ids[0]: _reading(active_five, 1000), ids[1]: _reading(5.0, 1000)}
    return meters


def test_a_pass_with_switching_off_leaves_a_full_account_alone(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=95.0)
    assert meters.tick(now=1000) == []
    assert load_store(world["store"])[1].get("needsLogin") is None


def test_a_pass_with_switching_on_tries_the_switch_and_reports_a_refusal(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=95.0)
    events = meters.tick(now=1000, auto=True)
    assert events == [{"kind": "refused", "why": "log in to home again"}]
    assert load_store(world["store"])[1]["needsLogin"] is True
    assert meters.tick(now=1030, auto=True) == [{"kind": "blocked", "why": "every account is full"}]
    assert meters.tick(now=1060, auto=True) == [], "said once, not every pass"


def test_a_pass_with_switching_on_leaves_a_roomy_account_alone(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=40.0)
    assert meters.tick(now=1000, auto=True) == []


def test_an_unreadable_store_decides_nothing_with_switching_on(world):
    Path(world["store"]).write_text("{ torn")
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    assert meters.tick(now=1000, auto=True) == []
    assert meters.snapshot()["error"] == "store is not valid JSON"


def test_the_snapshot_names_the_live_login_before_any_account_is_stored(world, tmp_path):
    """The Add button has to say whose login it would store."""
    Path(world["claude_json"]).write_text(json.dumps(
        {"oauthAccount": {"accountUuid": "uuid-active", "emailAddress": "jane.roe@example.com"}}))
    meters = AccountMeters(str(tmp_path / "fresh" / "accounts.json"), SCRATCH_SERVICE,
                           (SCRATCH_SERVICE, world["live"]), world["claude_json"])
    meters.tick(now=1000)
    assert meters.snapshot()["accounts"] == []
    assert meters.snapshot()["live"] == "jane.roe@example.com"


def test_the_snapshot_says_when_claude_code_has_no_login(world, tmp_path):
    Path(world["claude_json"]).write_text("{}")
    meters = AccountMeters(str(tmp_path / "fresh" / "accounts.json"), SCRATCH_SERVICE,
                           (SCRATCH_SERVICE, world["live"]), world["claude_json"])
    meters.tick(now=1000)
    assert meters.snapshot()["live"] is None


def _weekly_reading(five, weekly, now):
    return dict(_reading(five, now), usage={"five_hour": {"used": five, "resets_at": now + 9000},
                                            "seven_day": {"used": weekly, "resets_at": now + 3 * 86400},
                                            "models": []})


def test_a_balance_is_tried_only_once_a_second_reading_proposes_it(world, tmp_path):
    """The loop keeps the streak: the same reading twice is one comparison, a
    new reading that says the same makes the move."""
    meters = _meters_with_readings(world, tmp_path, active_five=20.0)
    ids = [a["id"] for a in world["accounts"]]
    meters.states = {ids[0]: _weekly_reading(20.0, 60.0, 1000), ids[1]: _weekly_reading(5.0, 10.0, 1000)}
    assert meters.tick(now=1000, auto=True) == []
    assert meters.tick(now=1030, auto=True) == []
    meters.states[ids[0]] = _weekly_reading(20.0, 60.0, 1300)
    meters.states[ids[1]]["fetched_at"] = 1300
    assert meters.tick(now=1300, auto=True) == [{"kind": "refused", "why": "log in to home again"}]
