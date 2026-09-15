"""Running a switch plan on real files, real lock folders and scratch Keychain items.

A temp folder stands in for ~/.claude and ~/.claude.json, and a scratch item for
Claude Code's credential. Refresh tokens are ones that were never issued.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import (SwitchRefused, delete_secret, load_store, login_item, plan_switch,
                      read_secret, run_switch, save_store, write_secret)

SCRATCH_SERVICE = "agents-sidebar-test"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain")

ALICE_LOGIN = {"accountUuid": "uuid-alice", "emailAddress": "alice@example.com"}
BOB_LOGIN = {"accountUuid": "uuid-bob", "emailAddress": "bob@example.com"}


def _credential(tag, **extra):
    return json.dumps({"claudeAiOauth": {"accessToken": f"never-issued-access-{tag}",
                                         "refreshToken": f"never-issued-refresh-{tag}",
                                         "expiresAt": 4_000_000_000_000}, **extra})


@pytest.fixture
def world(tmp_path):
    tag = uuid.uuid4().hex[:8]
    alice, bob, live = f"test-{tag}-a", f"test-{tag}-b", f"test-{tag}-live"
    accounts = [{"id": alice, "alias": "work", "accountUuid": "uuid-alice"},
                {"id": bob, "alias": "home", "accountUuid": "uuid-bob"}]
    store = str(tmp_path / "store" / "accounts.json")
    save_store(store, accounts)
    live_text = _credential("alice-live", mcpOAuth={"server": "machine"})
    write_secret(SCRATCH_SERVICE, live, live_text)
    write_secret(SCRATCH_SERVICE, alice, _credential("alice-stored"))
    write_secret(SCRATCH_SERVICE, login_item(alice), json.dumps({"accountUuid": "uuid-alice"}))
    write_secret(SCRATCH_SERVICE, bob, _credential("bob"))
    write_secret(SCRATCH_SERVICE, login_item(bob), json.dumps(BOB_LOGIN))
    claude_dir = tmp_path / "home" / ".claude"
    claude_dir.mkdir(parents=True)
    (tmp_path / "config").mkdir()
    claude_json = tmp_path / "config" / ".claude.json"
    claude_json.write_text(json.dumps({"oauthAccount": ALICE_LOGIN, "numStartups": 7}))
    w = {"store": store, "accounts": accounts, "live": (SCRATCH_SERVICE, live), "live_text": live_text,
         "claude_dir": str(claude_dir), "claude_json": str(claude_json), "alice": alice, "bob": bob}
    yield w
    for item in (alice, bob, live, login_item(alice), login_item(bob)):
        delete_secret(SCRATCH_SERVICE, item)


def _plan(w):
    return plan_switch(w["accounts"], w["bob"], ALICE_LOGIN, claude_dir=w["claude_dir"],
                       claude_json=w["claude_json"])


def _run(w, plan, **kw):
    run_switch(plan, w["store"], SCRATCH_SERVICE, w["live"], w["claude_json"], now=1000, **kw)


def _nothing_changed(w):
    assert read_secret(*w["live"]) == w["live_text"]
    assert json.loads(Path(w["claude_json"]).read_text()) == {"oauthAccount": ALICE_LOGIN, "numStartups": 7}
    assert os.listdir(w["claude_dir"]) == []
    assert not Path(w["claude_dir"] + ".lock").exists()


def test_a_switch_swaps_the_login_and_saves_the_outgoing_one(world):
    plan = _plan(world)
    plan["steps"] = [s for s in plan["steps"] if s[0] != "refresh"]
    _run(world, plan)

    live = json.loads(read_secret(*world["live"]))
    assert live["claudeAiOauth"] == json.loads(_credential("bob"))["claudeAiOauth"]
    assert live["mcpOAuth"] == {"server": "machine"}, "machine keys stay with the machine"
    assert json.loads(Path(world["claude_json"]).read_text()) == {"oauthAccount": BOB_LOGIN, "numStartups": 7}
    assert read_secret(SCRATCH_SERVICE, world["alice"]) == world["live_text"]
    assert json.loads(read_secret(SCRATCH_SERVICE, login_item(world["alice"]))) == ALICE_LOGIN
    assert os.listdir(world["claude_dir"]) == [] and not Path(world["claude_dir"] + ".lock").exists()


def test_a_refused_refresh_stops_the_switch_and_marks_the_login_dead(world):
    with pytest.raises(SwitchRefused, match="log in to home again"):
        _run(world, _plan(world))
    _nothing_changed(world)
    assert load_store(world["store"])[1]["needsLogin"] is True


def test_a_failure_after_the_credential_write_puts_it_back(world):
    """The config folder is read-only, so taking the config lock fails right
    after Claude Code's credential was replaced."""
    plan = _plan(world)
    plan["steps"] = [s for s in plan["steps"] if s[0] != "refresh"]
    folder = Path(world["claude_json"]).parent
    os.chmod(folder, 0o500)
    try:
        with pytest.raises(SwitchRefused, match="switch undone"):
            _run(world, plan, lock_timeout=0.5)
    finally:
        os.chmod(folder, 0o700)
    _nothing_changed(world)


def test_a_held_claude_code_lock_refuses_without_writing(world):
    plan = _plan(world)
    plan["steps"] = [s for s in plan["steps"] if s[0] != "refresh"]
    held = Path(world["claude_dir"]) / ".oauth_refresh.lock"
    held.mkdir()
    with pytest.raises(SwitchRefused, match="Claude Code is refreshing, try again"):
        _run(world, plan, lock_timeout=0.5)
    held.rmdir()
    _nothing_changed(world)


def test_a_login_that_changed_since_planning_refuses_without_writing(world):
    plan = _plan(world)
    plan["steps"] = [s for s in plan["steps"] if s[0] != "refresh"]
    carol = {"oauthAccount": {"accountUuid": "uuid-carol"}, "numStartups": 7}
    Path(world["claude_json"]).write_text(json.dumps(carol))
    with pytest.raises(SwitchRefused, match="the login changed"):
        _run(world, plan)
    assert read_secret(*world["live"]) == world["live_text"]
    assert json.loads(Path(world["claude_json"]).read_text()) == carol


def test_refusals_name_an_unnamed_account_as_the_panel_does(world, tmp_path):
    from accounts import update_account
    update_account(world["store"], world["bob"], alias=None)
    accounts = load_store(world["store"])
    plan = plan_switch(accounts, world["bob"], ALICE_LOGIN, claude_dir=world["claude_dir"],
                       claude_json=world["claude_json"])
    with pytest.raises(SwitchRefused, match=f"log in to Account {world['bob']} again"):
        _run(world, plan)
