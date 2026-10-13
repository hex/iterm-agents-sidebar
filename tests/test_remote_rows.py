# ABOUTME: A state published on another machine: recognised by its host, never checked against this machine's
# ABOUTME: processes or files, live only while its transport is in front, and answered only under its checks.
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar_rules import remote_key_refusal

STATE = {"state": "blocked", "pid": 31432, "session": "0f0e0d0c-0b0a-4a09-8807-060504030201",
         "blocked_since": 1791700000, "ts": 1791700000, "host": "box", "front": True, "cwd": "/srv/app",
         "detail": True}
raw = lambda **changes: json.dumps(dict(STATE, **changes))


def test_a_state_from_another_host_is_remote():
    assert sidebar.remote_host(raw(), "desk") == "box"


def test_a_state_from_this_host_or_from_a_hook_that_names_none_is_local():
    assert sidebar.remote_host(raw(host="desk"), "desk") is None
    assert sidebar.remote_host(json.dumps({"state": "idle", "pid": 7}), "desk") is None
    assert sidebar.remote_host(raw(host=7), "desk") is None
    assert sidebar.remote_host(None, "desk") is None


def test_a_host_name_is_clipped():
    assert sidebar.remote_host(raw(host="h" * 500), "desk") == "h" * 64


def test_a_remote_state_is_never_asked_of_the_local_process_table(monkeypatch):
    def kill(pid, signal):
        raise AssertionError("a pid from another machine was asked of this one")
    monkeypatch.setattr(sidebar.os, "kill", kill)
    assert sidebar.parse_state(raw(), remote=True) == "blocked"


def test_a_local_state_whose_writer_is_gone_still_reads_exited(monkeypatch):
    def gone(pid, signal):
        raise ProcessLookupError
    monkeypatch.setattr(sidebar.os, "kill", gone)
    assert sidebar.parse_state(raw()) == "exited"


def test_the_question_shows_only_while_it_is_the_one_the_state_names():
    asked = {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0, "since": 1791700000}
    shown = {key: item for key, item in asked.items() if key != "since"}
    assert sidebar.remote_question(raw(), json.dumps(asked)) == shown
    assert sidebar.remote_question(raw(blocked_since=1791700999), json.dumps(asked)) is None
    assert sidebar.remote_question(raw(state="working"), json.dumps(asked)) is None
    assert sidebar.remote_question(raw(), "") is None
    assert sidebar.remote_question(raw(), "not json") is None


def test_one_key_may_be_typed_only_under_every_check():
    assert remote_key_refusal("box", True, True, True) is None
    assert remote_key_refusal("box", False, True, True) == "the connection to box is not in front here"
    assert remote_key_refusal("box", True, False, True) == "something is in front of the agent on box"
    assert remote_key_refusal("box", True, None, True) == "something is in front of the agent on box"
    assert remote_key_refusal("box", True, True, False) == "the agent's title has gone from the pane"


@pytest.mark.parametrize("asked", [
    {"options": "ab"},                                             # a string is not a list of labels
    {"question": "Which one?", "options": ["This", 7]},
    {"question": "Which one?", "options": []},
    {"question": "Which one?", "options": ["x"] * 40},
    {"question": 5, "options": ["This", "That"]},
    {"question": "Which one?", "options": ["This", "That"], "multi": True},
    {"question": "Which one?", "options": ["This", "That"], "set": "ab"},
    {"question": "Which one?", "options": ["This", "That"], "more": 2},
    {"tool": "Bash", "summary": "ls"},                              # a gate is answered by its id
    {"tool": 5, "id": "f" * 32},
    {"something": "else"},
])
def test_a_question_of_the_wrong_shape_is_no_question(asked):
    """The variable is another machine's word: one the page or a notice would choke on is dropped here."""
    assert sidebar.remote_question(raw(), json.dumps(dict(asked, since=1791700000))) is None


def test_a_question_keeps_only_what_a_card_reads_and_clips_it():
    asked = {"header": "h" * 400, "question": "q" * 900, "options": ["a" * 300, "That"], "multi": False, "more": 0,
             "since": 1791700000, "extra": {"nested": True}}
    assert sidebar.remote_question(raw(), json.dumps(asked)) == {
        "header": "h" * 40, "question": "q" * 300, "options": ["a" * 60, "That"], "multi": False, "more": 0}


def test_a_tool_approval_keeps_its_tool_summary_and_id():
    asked = {"tool": "Bash", "summary": "git push", "id": "f" * 32, "since": 1791700000, "reason": "x"}
    assert sidebar.remote_question(raw(), json.dumps(asked)) == {"tool": "Bash", "summary": "git push", "id": "f" * 32}


def test_a_host_name_keeps_no_control_characters():
    """It is written into the daemon's log: a newline in it would start a line of its own there."""
    assert sidebar.remote_host(raw(host="box\n2026-10-11 00:00:00 forged"), "desk") == "box2026-10-11 00:00:00 forged"
    assert sidebar.remote_host(raw(host="\n\t"), "desk") is None


def test_a_folder_keeps_no_control_characters_and_is_clipped():
    assert sidebar.parse_cwd(raw(cwd="/srv/app\nmore")) == "/srv/appmore"
    assert sidebar.parse_cwd(raw(cwd="/" + "x" * 2000)) == "/" + "x" * 511
