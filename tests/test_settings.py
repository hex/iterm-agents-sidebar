"""Settings live server-side, not in localStorage.

The daemon takes an ephemeral port, so the page's origin changes on every
restart and anything stored per-origin is lost with it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar import DEFAULT_SETTINGS, load_settings, save_settings


def test_missing_file_yields_the_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == DEFAULT_SETTINGS


def test_a_saved_setting_survives_a_reload(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"volume": 0.9, "muted": True}, store)
    reloaded = load_settings(store)
    assert reloaded["volume"] == 0.9 and reloaded["muted"] is True


def test_saving_one_key_keeps_the_rest(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"volume": 0.2}, store)
    save_settings({"muted": True}, store)
    assert load_settings(store)["volume"] == 0.2


def test_unknown_keys_are_dropped(tmp_path):
    """The page posts what it knows; the daemon decides what exists. An
    unknown key is a version mismatch, not a new setting.
    """
    store = tmp_path / "settings.json"
    save_settings({"volume": 0.5, "wat": 1}, store)
    assert "wat" not in load_settings(store)


def test_a_corrupt_file_falls_back_rather_than_crashing(tmp_path):
    """A half-written file must not take the daemon down on next start."""
    store = tmp_path / "settings.json"
    store.write_text("{not json")
    assert load_settings(store) == DEFAULT_SETTINGS


def test_values_are_clamped_to_something_sane(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"volume": 40, "context_threshold": -5}, store)
    got = load_settings(store)
    assert got["volume"] == 1.0 and got["context_threshold"] == 0


def _server(tmp_path):
    from sidebar import Sidebar
    page = tmp_path / "page.html"
    page.write_text("x")
    store = tmp_path / "settings.json"
    return Sidebar(token="t", page_path=page, snapshot_fn=lambda: {"groups": []},
                   action_fn=lambda *a: None, settings_path=store), store


def test_get_settings_returns_json(tmp_path):
    server, _ = _server(tmp_path)
    status, ctype, body = server.handle("GET", "/settings?token=t", b"")
    assert status == 200 and ctype == "application/json"
    assert json.loads(body)["volume"] == DEFAULT_SETTINGS["volume"]


def test_post_settings_persists_and_returns_the_result(tmp_path):
    server, store = _server(tmp_path)
    status, _, body = server.handle("POST", "/settings?token=t", b'{"muted": true}')
    assert status == 200 and json.loads(body)["muted"] is True
    assert load_settings(store)["muted"] is True


def test_settings_need_the_token_like_everything_else(tmp_path):
    server, _ = _server(tmp_path)
    assert server.handle("GET", "/settings?token=wrong", b"")[0] == 403


def test_the_panel_has_a_text_size_and_it_starts_where_it_is():
    """1.0 is whatever the stylesheet says. The control multiplies that, so a
    default of anything else would mean the panel disagrees with its own CSS.
    """
    assert sidebar.DEFAULT_SETTINGS["ui_scale"] == 1.0


def test_text_size_is_clamped_to_something_usable():
    """Below about 0.8 the 9px metadata stops being readable; above 1.6 a row
    no longer fits the 250px the Toolbelt gives us.
    """
    assert sidebar.SETTING_RANGES["ui_scale"] == (0.8, 1.6)
    assert sidebar._clean({"ui_scale": 4})["ui_scale"] == 1.6
    assert sidebar._clean({"ui_scale": 0.1})["ui_scale"] == 0.8


def test_a_text_size_that_is_not_a_number_is_refused():
    assert sidebar._clean({"ui_scale": "big"})["ui_scale"] == 1.0


def test_background_shells_can_be_hidden_and_start_shown(tmp_path):
    """The page shows shell rows unless this is off, so it must survive a save
    rather than be dropped as an unknown key."""
    assert sidebar.DEFAULT_SETTINGS["show_shells"] is True
    store = tmp_path / "s.json"
    save_settings({"show_shells": False}, store)
    assert load_settings(store)["show_shells"] is False


def test_focusing_a_blocked_session_is_off_until_asked_for(tmp_path):
    """Taking the keyboard away from whatever you are typing in is not a
    default anyone should discover by having it happen."""
    assert sidebar.DEFAULT_SETTINGS["focus_blocked"] is False
    store = tmp_path / "s.json"
    save_settings({"focus_blocked": True}, store)
    assert load_settings(store)["focus_blocked"] is True


def test_going_back_after_a_blocked_session_resumes_is_on_and_saves(tmp_path):
    """It only ever undoes a move focus_blocked made, so it is on by default;
    focus_blocked itself stays off."""
    assert sidebar.DEFAULT_SETTINGS["return_after_blocked"] is True
    store = tmp_path / "s.json"
    save_settings({"return_after_blocked": False}, store)
    assert load_settings(store)["return_after_blocked"] is False


def test_background_shells_start_folded_and_can_start_expanded(tmp_path):
    """Folded into one line until asked for; the setting flips the default and
    must survive a save."""
    assert sidebar.DEFAULT_SETTINGS["expand_shells"] is False
    store = tmp_path / "s.json"
    save_settings({"expand_shells": True}, store)
    assert load_settings(store)["expand_shells"] is True
