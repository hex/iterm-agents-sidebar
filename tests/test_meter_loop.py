"""One pass of the meter loop against scratch Keychain items and supplied refusals.

Scratch items stand in for Claude Code's credential and the panel's stored
ones. Tokens were never issued; usage and refresh refusals are supplied at the
request boundaries without contacting the OAuth endpoints.
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import AccountMeters, delete_secret, load_store, save_store, write_secret

SCRATCH_SERVICE = "agents-sidebar-test"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain")
FAR_FUTURE_MS = 4_000_000_000_000


def _credential(tag):
    return json.dumps({"claudeAiOauth": {"accessToken": f"never-issued-access-{tag}",
                                         "refreshToken": f"never-issued-refresh-{tag}",
                                         "expiresAt": FAR_FUTURE_MS}})


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("accounts.request_refresh", lambda blob, now_ms: ("invalid_grant", None))
    monkeypatch.setattr("accounts.request_usage", lambda access_token: ("unauthorized", None))
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


def test_an_inactive_account_whose_stored_login_is_gone_asks_for_a_login(world):
    """Nothing to refresh is no passing fault: the panel asks for the login again rather than
    saying, reading after reading, that it cannot refresh one."""
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    delete_secret(SCRATCH_SERVICE, world["accounts"][1]["id"])
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert meters.snapshot()["accounts"][1]["needs_login"]
    assert load_store(world["store"])[1].get("needsLogin") is True


def test_one_pass_copies_a_rotated_active_token_into_the_panels_item(world):
    from accounts import read_secret
    rotated = _credential("rotated-by-claude-code")
    write_secret(SCRATCH_SERVICE, world["live"], rotated)
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert read_secret(SCRATCH_SERVICE, world["accounts"][0]["id"]) == rotated


def test_a_fresh_login_to_a_flagged_account_clears_its_log_in_again(world):
    """Seen 2026-09-29: two accounts logged into again, one of them active,
    still read "log in to ... again", since nothing ever dropped the flag."""
    save_store(world["store"], [dict(a, needsLogin=True) for a in world["accounts"]])
    write_secret(SCRATCH_SERVICE, world["live"], _credential("logged-in-again"))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    active, other = meters.snapshot()["accounts"]
    assert not active["needs_login"] and not load_store(world["store"])[0].get("needsLogin")
    assert other["needs_login"], "an account nobody logged into keeps its flag"


def test_adding_a_flagged_account_again_clears_its_log_in_again(world):
    save_store(world["store"], [dict(a, needsLogin=True) for a in world["accounts"]])
    write_secret(SCRATCH_SERVICE, world["live"], _credential(world["accounts"][0]["id"]))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.add(now=1000)
    assert not load_store(world["store"])[0].get("needsLogin")


def test_an_unreadable_store_is_reported_not_rebuilt(world):
    Path(world["store"]).write_text("{ torn")
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert meters.snapshot() == {"active": None, "accounts": [], "error": "store is not valid JSON",
                                 "last_switch": None, "next_switch": None, "exhausted": [], "live": None}
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


def _fable_full(weekly, resets_at, now, outcome="ok"):
    return dict(_reading(0.0, now - 60), outcome=outcome, tried_at=now - 10, next_at=now + 600,
                usage={"five_hour": None, "seven_day": {"used": weekly, "resets_at": resets_at},
                       "models": [{"name": "Fable", "used": 100.0, "resets_at": resets_at}]})


def test_a_model_full_on_every_account_reaches_the_panel_with_switching_off_and_the_active_reading_refused(world):
    """The switch outlook says nothing while the active account's last reading
    failed, yet each account's last figures still show Fable full everywhere,
    and the panel's bars are drawn from those figures, not from the outlook."""
    now = 10_000
    work, home = (a["id"] for a in world["accounts"])
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.states = {work: _fable_full(67.0, now + 86400, now, outcome="rate_limited"),
                     home: _fable_full(83.0, now + 15 * 3600, now)}
    assert meters.tick(now=now) == []
    snap = meters.snapshot()
    assert snap["next_switch"] is None
    assert snap["exhausted"] == [{"model": "Fable", "resets_at": now + 15 * 3600, "account_id": home,
                                  "account": "home"}]


def _unreadable_refresh(world, monkeypatch):
    """One pass in which the home account's refresh reply cannot be read."""
    monkeypatch.setattr("accounts.request_refresh", lambda blob, now_ms: ("unreadable", "<html>maintenance</html>"))
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    return meters


def test_an_unreadable_refresh_reply_asks_for_a_login(world, monkeypatch):
    meters = _unreadable_refresh(world, monkeypatch)
    home = world["accounts"][1]["id"]
    reply = Path(world["store"]).parent / "pending" / f"{home}.reply"
    assert reply.read_text() == "<html>maintenance</html>"
    assert load_store(world["store"])[1].get("needsLogin") is True
    assert meters.snapshot()["accounts"][1]["needs_login"] is True


def test_a_switch_stopped_by_an_unreadable_refresh_reply_asks_for_a_login(world, tmp_path, monkeypatch):
    from accounts import SwitchRefused, login_item
    monkeypatch.setattr("accounts.request_refresh", lambda blob, now_ms: ("unreadable", "<html>maintenance</html>"))
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    home = world["accounts"][1]["id"]
    write_secret(SCRATCH_SERVICE, login_item(home), json.dumps({"accountUuid": "uuid-other"}))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"], claude_dir=str(claude_dir))
    with pytest.raises(SwitchRefused, match=f"it is kept in pending/{home}.reply and home needs a login$"):
        meters.switch(home, now=1000)
    assert load_store(world["store"])[1]["needsLogin"] is True


def _stuck(world, account_id):
    """An account left with an unreadable reply and a stale successor, and flagged for a login."""
    from accounts import save_pending
    store_dir = str(Path(world["store"]).parent)
    save_pending(store_dir, account_id, "<html>maintenance</html>", suffix=".reply")
    save_pending(store_dir, account_id, _credential("stale-successor"))
    save_store(world["store"], [dict(a, needsLogin=True) if a["id"] == account_id else a
                                for a in world["accounts"]])
    return Path(store_dir) / "pending"


def test_adding_an_account_again_clears_what_an_unreadable_reply_left(world):
    from accounts import read_secret, refresh_account
    work = world["accounts"][0]["id"]
    pending = _stuck(world, work)
    write_secret(SCRATCH_SERVICE, world["live"], _credential("logged-in-again"))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.add(now=1000)
    assert sorted(p.name for p in pending.iterdir()) == []
    assert load_store(world["store"])[0].get("needsLogin") is None
    assert refresh_account(str(pending.parent), SCRATCH_SERVICE, work, now_ms=0) == "invalid_grant"
    assert read_secret(SCRATCH_SERVICE, work) == _credential("logged-in-again")


def test_a_fresh_login_in_claude_code_clears_what_an_unreadable_reply_left(world):
    work = world["accounts"][0]["id"]
    pending = _stuck(world, work)
    write_secret(SCRATCH_SERVICE, world["live"], _credential("logged-in-again"))
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"])
    meters.tick(now=1000)
    assert sorted(p.name for p in pending.iterdir()) == []
    assert load_store(world["store"])[0]["needsLogin"] is False
