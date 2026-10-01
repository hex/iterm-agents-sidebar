"""What the panel is told about accounts before the first reading: a daemon
that has just started names the stored accounts at once, rather than
inviting a login it has not yet looked for."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import AccountMeters, save_store


def test_the_stored_accounts_are_named_before_any_reading(tmp_path):
    store = str(tmp_path / "store" / "accounts.json")
    save_store(store, [{"id": "a-1", "alias": "work", "accountUuid": "uuid-active"},
                       {"id": "a-2", "alias": "home", "accountUuid": "uuid-other"}])
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-active",
                                                        "emailAddress": "jane.roe@example.com"}}))
    snap = AccountMeters(store, "agents-sidebar-test", ("agents-sidebar-test", "unused"),
                         str(claude_json)).snapshot()
    assert [(a["name"], a["active"], a["fetched_at"], a["outcome"]) for a in snap["accounts"]] == [
        ("work", True, None, None), ("home", False, None, None)]
    assert (snap["active"], snap["live"], snap["error"]) == ("a-1", "jane.roe@example.com", None)


def test_a_store_that_cannot_be_trusted_is_said_from_the_start(tmp_path):
    store = tmp_path / "accounts.json"
    store.write_text("{not json")
    snap = AccountMeters(str(store), "agents-sidebar-test", ("agents-sidebar-test", "unused"),
                         str(tmp_path / "missing.json")).snapshot()
    assert snap["accounts"] == [] and snap["error"]
