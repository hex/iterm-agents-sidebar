"""Token refresh: request shape, applying a successor, reading the server's verdict.

The one live test presents a token that was never issued, which the real token
endpoint rejects without spending anything.
"""
import json
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import (OAUTH_CLIENT_ID, apply_refresh, delete_secret, read_refresh_reply, read_secret,
                      recover_pending, refresh_account, refresh_body, refresh_verdict,
                      request_refresh, save_pending, write_secret)

SCRATCH_SERVICE = "agents-sidebar-test"
live = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain and network")

BLOB = {"claudeAiOauth": {"accessToken": "old-access", "refreshToken": "old-refresh",
                          "expiresAt": 1, "scopes": ["user:inference"], "subscriptionType": "max"},
        "mcpOAuth": {"server": "machine"}}


def test_refresh_body_presents_the_stored_refresh_token_as_claude_code_does():
    assert json.loads(refresh_body(BLOB)) == {
        "grant_type": "refresh_token", "refresh_token": "old-refresh", "client_id": OAUTH_CLIENT_ID}


def test_refresh_body_refuses_a_credential_without_a_refresh_token():
    with pytest.raises(ValueError):
        refresh_body({"claudeAiOauth": {"accessToken": "a"}})


def test_apply_refresh_replaces_the_tokens_and_keeps_everything_else():
    response = {"access_token": "new-access", "refresh_token": "new-refresh",
                "expires_in": 28800, "scope": "user:inference user:profile"}
    assert apply_refresh(BLOB, response, now_ms=1_000_000) == {
        "claudeAiOauth": {"accessToken": "new-access", "refreshToken": "new-refresh",
                          "expiresAt": 1_000_000 + 28_800_000,
                          "scopes": ["user:inference", "user:profile"], "subscriptionType": "max"},
        "mcpOAuth": {"server": "machine"}}
    assert BLOB["claudeAiOauth"]["refreshToken"] == "old-refresh", "the input is not modified"


def test_apply_refresh_keeps_the_refresh_token_when_the_server_sends_none():
    result = apply_refresh(BLOB, {"access_token": "new-access", "expires_in": 60}, now_ms=0)
    assert result["claudeAiOauth"]["refreshToken"] == "old-refresh"


def test_apply_refresh_refuses_a_response_without_an_access_token():
    with pytest.raises(ValueError):
        apply_refresh(BLOB, {"expires_in": 60}, now_ms=0)


def test_read_refresh_reply_applies_a_readable_successor():
    reply = '{"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 60}'
    verdict, successor = read_refresh_reply(BLOB, reply, now_ms=0)
    assert verdict == "ok"
    assert successor["claudeAiOauth"]["refreshToken"] == "new-refresh"


@pytest.mark.parametrize("reply", ["<html>maintenance</html>", '{"token": "renamed-field"}'])
def test_read_refresh_reply_hands_back_an_unreadable_reply_whole(reply):
    """The old refresh token is spent once the server answered 200, so a reply
    that cannot be applied is kept verbatim for the caller to save, never dropped."""
    assert read_refresh_reply(BLOB, reply, now_ms=0) == ("unreadable", reply)


@pytest.mark.parametrize("status, body, verdict", [
    (400, '{"error": "invalid_grant", "error_description": "Refresh token not found"}', "invalid_grant"),
    (401, '{"error": "invalid_client"}', "invalid_client"),
    (400, '{"error": "invalid_request", "detail": "invalid_grant"}', "transient"),
    (400, "<html>bad gateway</html>", "transient"),
    (500, '{"error": "invalid_grant"}', "transient"),
    (429, "", "transient"),
])
def test_refresh_verdict_trusts_only_an_explicit_rejection(status, body, verdict):
    assert refresh_verdict(status, body) == verdict


@live
def test_the_real_token_endpoint_rejects_a_token_that_was_never_issued():
    blob = {"claudeAiOauth": {"refreshToken": "agents-sidebar-test-never-issued"}}
    assert request_refresh(blob, now_ms=0) == ("invalid_grant", None)


# The consume gate, on real files, a real scratch Keychain item and the real endpoint.


@pytest.fixture
def scratch_id():
    ident = f"test-{uuid.uuid4().hex[:12]}"
    yield ident
    delete_secret(SCRATCH_SERVICE, ident)


def test_save_pending_writes_a_private_file_named_for_the_account(tmp_path):
    path = save_pending(str(tmp_path), "a1", '{"claudeAiOauth": {}}')
    assert path == str(tmp_path / "pending" / "a1.json")
    assert Path(path).read_text() == '{"claudeAiOauth": {}}'
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@live
def test_recover_pending_moves_a_saved_successor_into_the_keychain(tmp_path, scratch_id):
    save_pending(str(tmp_path), scratch_id, '{"claudeAiOauth": {"refreshToken": "successor"}}')
    assert recover_pending(str(tmp_path), SCRATCH_SERVICE) == [scratch_id]
    assert read_secret(SCRATCH_SERVICE, scratch_id) == '{"claudeAiOauth": {"refreshToken": "successor"}}'
    assert not (tmp_path / "pending" / f"{scratch_id}.json").exists()


@live
def test_refresh_account_reports_a_dead_token_and_changes_nothing(tmp_path, scratch_id):
    stored = '{"claudeAiOauth": {"refreshToken": "agents-sidebar-test-never-issued"}}'
    write_secret(SCRATCH_SERVICE, scratch_id, stored)
    assert refresh_account(str(tmp_path), SCRATCH_SERVICE, scratch_id, now_ms=0) == "invalid_grant"
    assert read_secret(SCRATCH_SERVICE, scratch_id) == stored
    assert not (tmp_path / "pending").exists()


@live
def test_refresh_account_without_a_stored_credential_says_so(tmp_path, scratch_id):
    assert refresh_account(str(tmp_path), SCRATCH_SERVICE, scratch_id, now_ms=0) == "no_credential"


@live
def test_refresh_account_sends_nothing_while_an_unreadable_reply_is_outstanding(tmp_path, scratch_id):
    """The reply that spent the token is on disk; posting the old token again cannot work."""
    stored = '{"claudeAiOauth": {"refreshToken": "agents-sidebar-test-never-issued"}}'
    write_secret(SCRATCH_SERVICE, scratch_id, stored)
    save_pending(str(tmp_path), scratch_id, "<html>maintenance</html>", suffix=".reply")
    assert refresh_account(str(tmp_path), SCRATCH_SERVICE, scratch_id, now_ms=0) == "unreadable_reply"
    assert read_secret(SCRATCH_SERVICE, scratch_id) == stored


@live
def test_recover_pending_leaves_unreadable_replies_for_a_person(tmp_path, scratch_id):
    save_pending(str(tmp_path), scratch_id, "<html>maintenance</html>", suffix=".reply")
    assert recover_pending(str(tmp_path), SCRATCH_SERVICE) == []
    assert read_secret(SCRATCH_SERVICE, scratch_id) is None
