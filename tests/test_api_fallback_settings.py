"""Putting apiKeyHelper into Claude Code's settings.json and taking it out, and nothing else.

Ways this can go wrong, and the test for each:
- a helper another tool set is changed or removed;
- any other key, one added by hand included, is lost or reordered;
- another writer's change between our read and our replace is lost;
- another writer's change after our replace goes unseen, and the result is
  taken for ours;
- the write loses the file's mode, replaces a symlink, or escapes non-ASCII text;
- a settings.json that is not JSON gets overwritten;
- a drop with nothing to drop writes the file anyway.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import statusline  # noqa: E402

HELPER = "/opt/agents-sidebar/api-key-helper.sh"
OURS = [HELPER]
FOREIGN = "/usr/local/bin/print-my-key"
SAME_NAME_ELSEWHERE = "/opt/acme/api-key-helper.sh"
FOREIGN_WITH_A_SECRET = "echo sk-ant-test-inline-not-a-real-key"
BY_HAND = {"model": "opus", "env": {"ALICE": "1"}, "statusLine": {"type": "command", "command": "bob-line"},
           "zzz_added_by_hand": [1, 2, 3]}


def write(path, settings):
    path.write_text(json.dumps(settings, indent=2) + "\n")


def read(path):
    return json.loads(path.read_text())


def test_the_state_says_whose_helper_is_there(tmp_path):
    path = tmp_path / "settings.json"
    assert statusline.api_key_helper_state(path, OURS) == "absent", "no settings.json at all"
    write(path, BY_HAND)
    assert statusline.api_key_helper_state(path, OURS) == "absent"
    write(path, dict(BY_HAND, apiKeyHelper=HELPER))
    assert statusline.api_key_helper_state(path, OURS) == "ours"
    write(path, dict(BY_HAND, apiKeyHelper=FOREIGN))
    assert statusline.api_key_helper_state(path, OURS) == "foreign"
    path.write_text("{ not json")
    assert statusline.api_key_helper_state(path, OURS) == "unreadable"


def test_a_helper_is_ours_only_by_its_exact_command_never_by_its_file_name(tmp_path):
    path = tmp_path / "settings.json"
    write(path, dict(BY_HAND, apiKeyHelper=SAME_NAME_ELSEWHERE))
    assert statusline.api_key_helper_state(path, OURS) == "foreign"
    assert statusline.api_key_helper_state(path, [HELPER, SAME_NAME_ELSEWHERE]) == "ours"
    write(path, dict(BY_HAND, apiKeyHelper=f"{HELPER} --extra"))
    assert statusline.api_key_helper_state(path, OURS) == "foreign", "a command that merely starts the same"


def test_a_helper_of_the_same_file_name_elsewhere_is_never_changed_or_removed(tmp_path):
    path = tmp_path / "settings.json"
    write(path, dict(BY_HAND, apiKeyHelper=SAME_NAME_ELSEWHERE))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        statusline.set_api_key_helper(path, HELPER, OURS)
    with pytest.raises(ValueError):
        statusline.drop_api_key_helper(path, OURS)
    assert path.read_bytes() == before


def test_the_command_runs_a_path_with_a_space_through_a_shell_with_its_account(tmp_path):
    script = tmp_path / "my checkout" / "api-key-helper.sh"
    script.parent.mkdir()
    script.write_text('#!/bin/sh\necho "printed for $1"\n')
    script.chmod(0o755)
    done = subprocess.run(["/bin/sh", "-c", statusline.helper_command(script, "acct-2")], capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, "printed for acct-2\n"), done.stderr
    assert statusline.helper_command("/opt/plain/api-key-helper.sh", "acct-12") == "/opt/plain/api-key-helper.sh acct-12"


@pytest.mark.parametrize("account_id", ["", "acct-", "acct-1 acct-2", "acct-1; touch pwned", "$(touch pwned)",
                                        "`touch pwned`", "acct-1\ntouch pwned", "../acct-1", "api-key", None, 1])
def test_a_command_is_never_made_for_an_account_id_outside_the_stores_format(account_id):
    with pytest.raises(ValueError, match="is not an account id"):
        statusline.helper_command("/opt/plain/api-key-helper.sh", account_id)


def test_a_foreign_helper_is_never_changed_and_the_refusal_never_copies_its_command(tmp_path):
    path = tmp_path / "settings.json"
    write(path, dict(BY_HAND, apiKeyHelper=FOREIGN_WITH_A_SECRET))
    before = path.read_bytes()
    for call in (lambda: statusline.set_api_key_helper(path, HELPER, OURS),
                 lambda: statusline.drop_api_key_helper(path, OURS)):
        with pytest.raises(ValueError, match="another tool's apiKeyHelper") as refusal:
            call()
        assert "sk-ant-test-inline" not in str(refusal.value)
        assert path.read_bytes() == before


def test_every_other_key_is_written_back_as_read(tmp_path):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert read(path) == dict(BY_HAND, apiKeyHelper=HELPER)
    assert list(read(path))[:4] == list(BY_HAND), "the keys keep their order"
    statusline.drop_api_key_helper(path, OURS)
    assert read(path) == BY_HAND


def test_the_write_keeps_the_files_mode(tmp_path):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    path.chmod(0o600)
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    statusline.drop_api_key_helper(path, OURS)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_write_goes_through_a_symlink_to_its_target_and_leaves_the_link(tmp_path):
    target = tmp_path / "dotfiles" / "claude-settings.json"
    target.parent.mkdir()
    write(target, BY_HAND)
    link = tmp_path / "settings.json"
    link.symlink_to(target)
    statusline.set_api_key_helper(link, HELPER, OURS)
    assert link.is_symlink() and link.resolve() == target
    assert read(target) == dict(BY_HAND, apiKeyHelper=HELPER)
    assert sorted(p.name for p in target.parent.iterdir()) == ["claude-settings.json"], "no staged file left"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dotfiles", "settings.json"]
    statusline.drop_api_key_helper(link, OURS)
    assert link.is_symlink()
    assert read(target) == BY_HAND


def test_non_ascii_text_is_written_as_is(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"env": {"NAME": "caf\u00e9"}}\n', encoding="utf-8")
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert "café" in path.read_text(encoding="utf-8")
    assert "\\u00e9" not in path.read_text(encoding="utf-8")
    assert read(path)["env"]["NAME"] == "café"


def test_a_fresh_machine_with_no_settings_gets_one_holding_only_the_helper(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert read(path) == {"apiKeyHelper": HELPER}


def test_settings_that_are_not_json_are_refused_and_left_untouched(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json")
    for call in (lambda: statusline.set_api_key_helper(path, HELPER, OURS),
                 lambda: statusline.drop_api_key_helper(path, OURS)):
        with pytest.raises(ValueError, match="not valid JSON"):
            call()
        assert path.read_text() == "{ not json"


def test_a_drop_with_no_helper_writes_nothing(tmp_path):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    os.utime(path, (1_000_000, 1_000_000))
    statusline.drop_api_key_helper(path, OURS)
    assert path.stat().st_mtime == 1_000_000
    statusline.drop_api_key_helper(tmp_path / "none.json", OURS)
    assert not (tmp_path / "none.json").exists()


def test_a_set_that_is_already_there_writes_nothing(tmp_path):
    path = tmp_path / "settings.json"
    write(path, dict(BY_HAND, apiKeyHelper=HELPER))
    os.utime(path, (1_000_000, 1_000_000))
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert path.stat().st_mtime == 1_000_000


def racing(monkeypatch, path, writes, hook):
    """Let another writer's next settings land each time the panel's write
    reaches `hook`: "fsync", once the new file is staged and before it
    replaces the old, or "replace", just after it does."""
    pending = list(writes)
    real = getattr(os, hook)

    def raced(*args):
        result = real(*args)
        if pending:
            write(path, pending.pop(0))
        return result
    monkeypatch.setattr(statusline.os, hook, raced)


def test_a_change_between_read_and_replace_is_not_lost(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    racing(monkeypatch, path, [dict(BY_HAND, theirs=True)], "fsync")
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert read(path) == dict(BY_HAND, theirs=True, apiKeyHelper=HELPER)


def test_a_change_after_the_replace_is_seen_on_read_back_and_the_step_runs_once_more(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    racing(monkeypatch, path, [dict(BY_HAND, theirs=True)], "replace")
    statusline.set_api_key_helper(path, HELPER, OURS)
    assert read(path) == dict(BY_HAND, theirs=True, apiKeyHelper=HELPER)


def test_a_second_mismatch_refuses_and_leaves_the_file_as_it_is(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    write(path, BY_HAND)
    first, second = dict(BY_HAND, theirs=1), dict(BY_HAND, theirs=2)
    racing(monkeypatch, path, [first, second], "replace")
    with pytest.raises(ValueError, match="changed while the panel wrote it"):
        statusline.set_api_key_helper(path, HELPER, OURS)
    assert read(path) == second
