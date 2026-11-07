# ABOUTME: Guards tabunderline.py with real `defaults` over the test's own plist: a line under iTerm2's selected tab
# ABOUTME: the record says the panel set to 0 goes back as it was, one the user changed since stays, the record goes.
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tabunderline  # noqa: E402
from conftest import iterm_prefs as prefs  # noqa: E402

KEY = "MinimalSelectedTabUnderlineProminence"


def user_sets(*value):
    subprocess.run(["/usr/bin/defaults", "write", tabunderline.DOMAIN, KEY, *value], check=True)


def recorded(tmp_path, record):
    path = tmp_path / "tab-underline.json"
    path.write_text(json.dumps(record))
    return path


def record_left(tmp_path):
    path = tmp_path / "tab-underline.json"
    return json.loads(path.read_text()) if path.exists() else None


def put_back(path):
    logged = []
    asyncio.run(tabunderline.put_back(path, logged.append))
    return logged


def test_a_line_held_over_an_unset_setting_goes_back_to_unset_and_the_record_goes(tmp_path):
    """`defaults delete` of the last key leaves the file holding nothing."""
    path = recorded(tmp_path, {"kept": None})
    user_sets("-float", "0")
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path), logged) == ({}, None, ["tab underline put back"])


@pytest.mark.parametrize("kept, stored", [
    ({"type": "float", "value": "0.4"}, 0.4000000059604645),
    ({"type": "string", "value": "0.5"}, "0.5"),
    ({"type": "integer", "value": "2"}, 2),
    ({"type": "boolean", "value": "1"}, True),
], ids=["float", "string", "integer", "boolean"])
def test_a_value_of_the_users_goes_back_as_it_was_in_its_own_type(tmp_path, kept, stored):
    """`defaults write -float` stores a single-precision 0.4, which reads back as 0.4000000059604645."""
    path = recorded(tmp_path, {"kept": kept})
    user_sets("-float", "0")
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path), logged) == ({KEY: stored}, None, ["tab underline put back"])


def user_deletes():
    subprocess.run(["/usr/bin/defaults", "delete", tabunderline.DOMAIN, KEY], check=True, capture_output=True)


@pytest.mark.parametrize("change, users", [
    (lambda: user_sets("-float", "0.7"), {KEY: 0.699999988079071}),
    (lambda: user_sets("-string", "1"), {KEY: "1"}),
    (user_deletes, {}),
], ids=["float", "string", "deleted"])
def test_a_line_the_user_changed_since_is_left_as_they_set_it_and_the_record_goes(tmp_path, change, users):
    path = recorded(tmp_path, {"kept": {"type": "float", "value": "0.4"}})
    user_sets("-float", "0")
    change()
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path), logged) == (users, None, ["tab underline taken back"])


def test_a_line_the_user_hid_themselves_stays_hidden_and_the_record_goes(tmp_path):
    path = recorded(tmp_path, {"aside": True})
    user_sets("-float", "0")
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path), logged) == ({KEY: 0.0}, None, [])


def test_without_a_record_nothing_is_read_or_written(tmp_path):
    user_sets("-float", "0")
    logged = put_back(tmp_path / "tab-underline.json")
    assert (prefs(), record_left(tmp_path), logged) == ({KEY: 0.0}, None, [])


def iterm_prefs_in(tmp_path, monkeypatch):
    """iTerm2's settings in a folder of their own, for a test to take write access away from."""
    folder = tmp_path / "locked"
    folder.mkdir()
    monkeypatch.setattr(tabunderline, "DOMAIN", str(folder / "com.googlecode.iterm2"))
    return folder


@pytest.mark.parametrize("kept, verb, complaint", [
    ({"type": "float", "value": "0.4"}, "write", "Could not write domain {domain}; exiting"),
    (None, "delete", "Domain ({domain}) not found. Defaults have not been changed."),
], ids=["write", "delete, its complaint over two lines"])
def test_a_line_that_cannot_be_put_back_is_logged_and_its_record_kept_for_the_next_start(
        tmp_path, monkeypatch, kept, verb, complaint):
    folder = iterm_prefs_in(tmp_path, monkeypatch)
    path = recorded(tmp_path, {"kept": kept})
    user_sets("-float", "0")
    folder.chmod(0o555)
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path)) == ({KEY: 0.0}, {"kept": kept})
    assert logged == [f"tab underline: defaults {verb} said {complaint.format(domain=tabunderline.DOMAIN)}"]
    folder.chmod(0o755)
    assert put_back(path) == ["tab underline put back"]
    assert record_left(tmp_path) is None


def test_a_record_that_cannot_be_read_is_logged_and_the_line_left_as_it_is(tmp_path):
    path = tmp_path / "tab-underline.json"
    path.write_text("{")
    user_sets("-float", "0")
    logged = put_back(path)
    assert (prefs(), path.read_text()) == ({KEY: 0.0}, "{")
    assert logged == [f"tab underline: {path} unreadable: Expecting property name enclosed in double quotes: "
                      "line 1 column 2 (char 1)"]


@pytest.mark.parametrize("record, why", [
    ({"kept": {"type": "dictionary", "value": "{}"}}, "kept is no value this module writes back: "
                                                       "{'type': 'dictionary', 'value': '{}'}"),
    ({"kept": {"type": "boolean", "value": "true"}}, "kept is no value this module writes back: "
                                                      "{'type': 'boolean', 'value': 'true'}"),
    ({"aside": False}, "neither held nor aside: {'aside': False}"),
    ([], "neither held nor aside: []"),
], ids=["a type defaults cannot write back", "a boolean as a word", "aside false", "not an object"])
def test_a_record_in_any_other_shape_is_logged_and_nothing_is_put_back(tmp_path, record, why):
    path = recorded(tmp_path, record)
    user_sets("-float", "0")
    logged = put_back(path)
    assert (prefs(), record_left(tmp_path)) == ({KEY: 0.0}, record)
    assert logged == [f"tab underline: {path} unreadable: {why}"]
