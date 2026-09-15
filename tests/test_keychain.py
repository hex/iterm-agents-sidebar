"""Keychain access through /usr/bin/security: command shape, then a real round trip.

The live tests use a scratch service name and a throwaway value, and delete the
item afterwards. They never touch Claude Code's credential or the panel's store.
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import (SECURITY, SECURITY_LINE_LIMIT, KeychainError, delete_secret, read_result,
                      read_secret, write_command, write_secret)

SCRATCH_SERVICE = "agents-sidebar-test"


def test_write_command_keeps_the_value_out_of_argv():
    argv, stdin = write_command("svc", "acct", '{"token": "plain"}')
    assert argv == [SECURITY, "-i"]
    assert "plain" not in stdin
    assert stdin == ('add-generic-password -U -a "acct" -s "svc" -X '
                     + '{"token": "plain"}'.encode().hex() + "\n")


def test_write_command_quotes_names_with_spaces_and_quotes():
    _, stdin = write_command('Claude Code-credentials', 'a"b\\c', "v")
    assert '-a "a\\"b\\\\c" -s "Claude Code-credentials"' in stdin


def test_write_command_falls_back_to_argv_when_the_line_would_be_truncated():
    value = "x" * SECURITY_LINE_LIMIT
    argv, stdin = write_command("svc", "acct", value)
    assert stdin is None
    assert argv == [SECURITY, "add-generic-password", "-U", "-a", "acct", "-s", "svc",
                    "-X", value.encode().hex()]


live = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain")


@pytest.fixture
def scratch_account():
    account = f"test-{uuid.uuid4().hex[:12]}"
    yield account
    delete_secret(SCRATCH_SERVICE, account)


@live
def test_a_written_secret_reads_back_and_an_update_replaces_it(scratch_account):
    write_secret(SCRATCH_SERVICE, scratch_account, '{"refreshToken": "first"}')
    write_secret(SCRATCH_SERVICE, scratch_account, '{"refreshToken": "second"}')
    assert read_secret(SCRATCH_SERVICE, scratch_account) == '{"refreshToken": "second"}'


@live
def test_a_secret_too_long_for_one_stdin_line_still_round_trips(scratch_account):
    value = "y" * SECURITY_LINE_LIMIT
    write_secret(SCRATCH_SERVICE, scratch_account, value)
    assert read_secret(SCRATCH_SERVICE, scratch_account) == value


@live
def test_a_missing_item_reads_as_none_and_deletes_quietly(scratch_account):
    assert read_secret(SCRATCH_SERVICE, scratch_account) is None
    delete_secret(SCRATCH_SERVICE, scratch_account)


@live
def test_a_deleted_secret_is_gone(scratch_account):
    write_secret(SCRATCH_SERVICE, scratch_account, "v")
    delete_secret(SCRATCH_SERVICE, scratch_account)
    assert read_secret(SCRATCH_SERVICE, scratch_account) is None


def test_read_result_strips_only_the_newline_security_appends():
    assert read_result(0, " value \n", "") == " value "


def test_read_result_treats_exit_44_as_missing():
    assert read_result(44, "", "could not be found") is None


def test_read_result_raises_on_any_other_failure_rather_than_reading_as_missing():
    with pytest.raises(KeychainError, match="rc=51: User interaction is not allowed"):
        read_result(51, "", "User interaction is not allowed.\n")
