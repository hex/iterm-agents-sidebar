"""The panel's account store on disk, and adding the live login to it.

Live tests stand a scratch Keychain item in for Claude Code's credential, so no
real login is read or copied.
"""
import json
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import (add_account, add_live_account, delete_secret, load_store, read_secret,
                      save_store, store_text, write_secret)

SCRATCH_SERVICE = "agents-sidebar-test"
live = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain")

LIVE_LOGIN = {"accountUuid": "uuid-alice", "emailAddress": "alice@example.com",
              "organizationUuid": "org-1", "organizationName": "Example Org"}


def test_add_account_records_the_login_without_its_email():
    accounts, account = add_account([], LIVE_LOGIN, now=1000)
    assert account == {"id": "acct-1", "alias": None, "accountUuid": "uuid-alice",
                       "organizationUuid": "org-1", "organizationName": "Example Org",
                       "added": 1000, "lastSynced": 1000}
    assert accounts == [account]
    assert "alice@example.com" not in store_text(accounts)


def test_add_account_numbers_past_the_highest_id_in_use():
    existing = [{"id": "acct-1", "accountUuid": "u1"}, {"id": "acct-4", "accountUuid": "u4"}]
    _, account = add_account(existing, LIVE_LOGIN, now=1000)
    assert account["id"] == "acct-5"


def test_add_account_for_a_login_already_stored_only_marks_it_synced():
    first, stored = add_account([], LIVE_LOGIN, now=1000)
    again, account = add_account(first, LIVE_LOGIN, now=2000)
    assert len(again) == 1
    assert account == dict(stored, lastSynced=2000)


def test_add_account_refuses_a_login_without_an_account_uuid():
    with pytest.raises(ValueError):
        add_account([], {"emailAddress": "alice@example.com"}, now=1000)


def test_saved_store_reads_back_and_is_private(tmp_path):
    path = tmp_path / "agents-sidebar" / "accounts.json"
    accounts, _ = add_account([], LIVE_LOGIN, now=1000)
    save_store(str(path), accounts)
    assert load_store(str(path)) == accounts
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert [p.name for p in path.parent.iterdir()] == ["accounts.json"]


def test_a_missing_store_loads_as_no_accounts(tmp_path):
    assert load_store(str(tmp_path / "accounts.json")) == []


@pytest.fixture
def scratch():
    ids = {"live": f"test-live-{uuid.uuid4().hex[:8]}"}
    yield ids
    delete_secret(SCRATCH_SERVICE, ids["live"])
    for account_id in ids.get("stored", []):
        delete_secret(SCRATCH_SERVICE, account_id)
        delete_secret(SCRATCH_SERVICE, account_id + ".login")


@live
def test_add_live_account_copies_the_live_credential_then_records_the_account(tmp_path, scratch):
    credential = '{"claudeAiOauth": {"refreshToken": "scratch-refresh"}}'
    write_secret(SCRATCH_SERVICE, scratch["live"], credential)
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"oauthAccount": LIVE_LOGIN, "numStartups": 3}))
    store = tmp_path / "store" / "accounts.json"

    account = add_live_account(str(store), SCRATCH_SERVICE, (SCRATCH_SERVICE, scratch["live"]),
                               str(claude_json), now=1000)
    scratch["stored"] = [account["id"]]

    assert read_secret(SCRATCH_SERVICE, account["id"]) == credential
    assert json.loads(read_secret(SCRATCH_SERVICE, account["id"] + ".login")) == LIVE_LOGIN
    assert load_store(str(store)) == [account]


@live
def test_add_live_account_refuses_when_nobody_is_logged_in(tmp_path, scratch):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"numStartups": 3}))
    store = tmp_path / "accounts.json"
    with pytest.raises(ValueError, match="no login"):
        add_live_account(str(store), SCRATCH_SERVICE, (SCRATCH_SERVICE, scratch["live"]),
                         str(claude_json), now=1000)
    assert not store.exists()


def test_update_account_changes_only_the_named_fields_of_one_account(tmp_path):
    from accounts import update_account
    path = str(tmp_path / "accounts.json")
    accounts, first = add_account([], LIVE_LOGIN, now=1000)
    accounts, second = add_account(accounts, dict(LIVE_LOGIN, accountUuid="uuid-bob"), now=1000)
    save_store(path, accounts)
    update_account(path, second["id"], needsLogin=True)
    assert load_store(path) == [first, dict(second, needsLogin=True)]


def test_update_account_of_an_account_no_longer_stored_changes_nothing(tmp_path):
    from accounts import update_account
    path = str(tmp_path / "accounts.json")
    accounts, _ = add_account([], LIVE_LOGIN, now=1000)
    save_store(path, accounts)
    update_account(path, "acct-9", needsLogin=True)
    assert load_store(path) == accounts
