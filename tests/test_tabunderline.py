# ABOUTME: Guards tabunderline.py with real `defaults` over the test's own plist: the line under iTerm2's selected tab
# ABOUTME: hidden while the tint is on, what was there put back, a value the user changed left, and a daemon's restart.
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


def held(tmp_path):
    path = tmp_path / "tab-underline.json"
    return json.loads(path.read_text()) if path.exists() else None


def step(underline, on, logged):
    asyncio.run(underline.step(on, logged.append))


def test_turned_on_over_an_unset_line_it_writes_zero_and_holds_that_nothing_was_there(tmp_path):
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert prefs() == {KEY: 0.0}
    assert held(tmp_path) == {"kept": None}
    assert logged == []


def test_turned_off_it_takes_the_zero_out_again_where_nothing_was_there(tmp_path):
    """`defaults delete` of the last key leaves the file holding nothing."""
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    step(u, False, logged)
    assert prefs() == {}
    assert held(tmp_path) is None
    assert logged == []


@pytest.mark.parametrize("value, kept, stored", [
    (["-float", "0.4"], {"type": "float", "value": "0.4"}, 0.4000000059604645),
    (["-string", "0.5"], {"type": "string", "value": "0.5"}, "0.5"),
    (["-int", "2"], {"type": "integer", "value": "2"}, 2),
    (["-bool", "true"], {"type": "boolean", "value": "1"}, True),
], ids=["float", "string", "integer", "boolean"])
def test_a_value_of_the_users_goes_back_as_it_was_in_its_own_type(tmp_path, value, kept, stored):
    """`defaults write -float` stores a single-precision 0.4, which reads back as 0.4 and is written back to the
    same bits."""
    user_sets(*value)
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: 0.0}, {"kept": kept})
    step(u, False, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: stored}, None, [])


@pytest.mark.parametrize("value, stored", [
    (["-float", "0"], 0.0), (["-string", "0.0"], "0.0"), (["-int", "0"], 0), (["-bool", "false"], False),
], ids=["float", "string", "integer", "boolean"])
def test_a_line_the_user_already_hid_is_theirs_and_stays_hidden_once_the_tint_goes_off(tmp_path, value, stored):
    """Zero in any type the user stored it in. The record says the line is theirs, so a restart leaves it too."""
    user_sets(*value)
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: stored}, {"aside": True})
    step(u, False, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: stored}, None, ["tab underline own"])


def user_deletes():
    subprocess.run(["/usr/bin/defaults", "delete", tabunderline.DOMAIN, KEY], check=True, capture_output=True)


@pytest.mark.parametrize("change, users", [
    (lambda: user_sets("-float", "0.7"), {KEY: 0.699999988079071}),
    (lambda: user_sets("-string", "1"), {KEY: "1"}),
    (user_deletes, {}),
], ids=["float", "string", "deleted"])
def test_a_line_the_user_showed_again_while_held_is_left_as_they_set_it_when_the_tint_goes_off(tmp_path, change, users):
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    change()
    step(u, False, logged)
    assert (prefs(), held(tmp_path), logged) == (users, None, ["tab underline taken back"])


def test_a_restarted_daemon_finds_the_line_shown_again_and_leaves_it_to_the_user_for_good(tmp_path):
    """While the tint stays on: dropping the record would make the next restart hide the line again."""
    logged, path = [], tmp_path / "tab-underline.json"
    step(tabunderline.Underline(path), True, logged)
    user_sets("-float", "0.7")
    step(tabunderline.Underline(path), True, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: 0.699999988079071}, {"aside": True}, ["tab underline taken back"])
    step(tabunderline.Underline(path), True, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: 0.699999988079071}, {"aside": True}, ["tab underline taken back"])


def test_a_restarted_daemon_keeps_holding_its_own_zero_and_puts_back_what_the_first_one_kept(tmp_path):
    logged, path = [], tmp_path / "tab-underline.json"
    user_sets("-float", "0.4")
    step(tabunderline.Underline(path), True, logged)
    step(tabunderline.Underline(path), True, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: 0.0}, {"kept": {"type": "float", "value": "0.4"}})
    step(tabunderline.Underline(path), False, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: 0.4000000059604645}, None, [])


def test_a_line_shown_again_while_the_same_daemon_holds_it_is_not_read_again_until_the_tint_changes(tmp_path):
    """No `defaults` call on a rebuild where the setting stayed as it was: the record still says held."""
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    user_sets("-float", "0.7")
    step(u, True, logged)
    assert (prefs(), held(tmp_path), logged) == ({KEY: 0.699999988079071}, {"kept": None}, [])


def iterm_prefs_in(tmp_path, monkeypatch):
    """iTerm2's settings in a folder of their own, for a test to take write access away from."""
    folder = tmp_path / "locked"
    folder.mkdir()
    monkeypatch.setattr(tabunderline, "DOMAIN", str(folder / "com.googlecode.iterm2"))
    return folder


def test_a_line_that_cannot_be_hidden_is_logged_and_nothing_is_held(tmp_path, monkeypatch):
    folder = iterm_prefs_in(tmp_path, monkeypatch)
    folder.chmod(0o555)
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert (prefs(), held(tmp_path)) == ({}, None)
    assert logged == [f"tab underline: defaults write said Could not write domain {folder}/com.googlecode.iterm2; exiting"]


def test_a_line_that_cannot_be_put_back_stays_held_for_the_next_try(tmp_path, monkeypatch):
    """The next time the tint goes off, or the uninstall, finds the record and tries again."""
    folder = iterm_prefs_in(tmp_path, monkeypatch)
    user_sets("-float", "0.4")
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    folder.chmod(0o555)
    step(u, False, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: 0.0}, {"kept": {"type": "float", "value": "0.4"}})
    assert logged == [f"tab underline: defaults write said Could not write domain {folder}/com.googlecode.iterm2; exiting"]
    folder.chmod(0o755)
    step(u, True, logged)
    step(u, False, logged)
    assert (prefs(), held(tmp_path), len(logged)) == ({KEY: 0.4000000059604645}, None, 1)


def test_a_record_that_cannot_be_written_leaves_the_line_as_it_is(tmp_path):
    status = tmp_path / "status"
    status.mkdir(mode=0o555)
    logged, u = [], tabunderline.Underline(status / "tab-underline.json")
    step(u, True, logged)
    assert prefs() == {}
    assert logged == [f"tab underline: [Errno 13] Permission denied: '{status}/tab-underline.json.tmp'"]


def test_a_record_that_cannot_be_read_is_logged_and_the_line_left_as_it_is(tmp_path):
    (tmp_path / "tab-underline.json").write_text("{")
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert prefs() == {}
    assert logged == [f"tab underline: {tmp_path}/tab-underline.json unreadable: Expecting property name enclosed in "
                      "double quotes: line 1 column 2 (char 1)"]


@pytest.mark.parametrize("record, why", [
    ({"kept": {"type": "dictionary", "value": "{}"}}, "kept is no value this module writes back: "
                                                       "{'type': 'dictionary', 'value': '{}'}"),
    ({"aside": False}, "neither held nor aside: {'aside': False}"),
    ([], "neither held nor aside: []"),
])
def test_a_record_in_any_other_shape_is_logged_and_nothing_is_put_back(tmp_path, record, why):
    (tmp_path / "tab-underline.json").write_text(json.dumps(record))
    user_sets("-float", "0")
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, False, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: 0.0}, record)
    assert logged == [f"tab underline: {tmp_path}/tab-underline.json unreadable: {why}"]


def test_a_value_that_could_not_be_written_back_is_left_to_the_user(tmp_path):
    """What `defaults read` prints for a dictionary writes back with every member a string."""
    user_sets("-dict", "a", "1")
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    assert (prefs(), held(tmp_path)) == ({KEY: {"a": "1"}}, {"aside": True})
    assert logged == ["tab underline: holds a dictionary, which cannot be put back; left as it is"]


def setting(key, *value):
    subprocess.run(["/usr/bin/defaults", "write", tabunderline.DOMAIN, key, *value], check=True)


@pytest.mark.parametrize("load, folder, saves, found", [
    (["-bool", "true"], "/Users/someone/Library/Mobile Documents/com~apple~CloudDocs/iTerm2", "2",
     "/Users/someone/Library/Mobile Documents/com~apple~CloudDocs/iTerm2"),
    (["-int", "1"], "/Volumes/Shared/iterm", "2", "/Volumes/Shared/iterm"),
    (["-bool", "true"], "/Volumes/Shared/iterm", "0", "/Volumes/Shared/iterm"),
    (["-bool", "true"], "/Volumes/Shared/iterm", "1", None),
    (["-bool", "true"], "/Volumes/Shared/iterm", None, None),
    (["-bool", "false"], "/Volumes/Shared/iterm", "2", None),
    (None, "/Volumes/Shared/iterm", "2", None),
    (["-bool", "true"], None, "2", None),
    (["-bool", "true"], "https://example.com/iterm2", "2", None),
], ids=["icloud", "integer", "on quit", "never", "never picked", "off", "unset", "no folder", "url"])
def test_the_folder_iterm2_shares_its_settings_from_is_read_only_while_it_loads_them_from_one_and_saves_to_it(
        load, folder, saves, found):
    """A URL is where iTerm2 reads its settings, not a folder it writes them back to. Its save mode is 0 when it
    quits, 1 never and 2 automatically, and never while no mode was picked."""
    if load:
        setting("LoadPrefsFromCustomFolder", *load)
    if folder:
        setting("PrefsCustomFolder", "-string", folder)
    if saves:
        setting("NoSyncNeverRemindPrefsChangesLostForFile", "-bool", "true")
        setting("NoSyncNeverRemindPrefsChangesLostForFile_selection", "-int", saves)
    assert asyncio.run(tabunderline.settings_folder()) == found


def test_a_complaint_defaults_spreads_over_lines_reaches_the_log_whole(tmp_path, monkeypatch):
    folder = iterm_prefs_in(tmp_path, monkeypatch)
    logged, u = [], tabunderline.Underline(tmp_path / "tab-underline.json")
    step(u, True, logged)
    folder.chmod(0o555)
    step(u, False, logged)
    assert logged == [f"tab underline: defaults delete said Domain ({folder}/com.googlecode.iterm2) not found. "
                      "Defaults have not been changed."]
    assert held(tmp_path) == {"kept": None}
