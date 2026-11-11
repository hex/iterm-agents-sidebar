"""Settings live server-side, not in localStorage.

The daemon takes an ephemeral port, so the page's origin changes on every
restart and anything stored per-origin is lost with it.
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar import DEFAULT_SETTINGS, load_settings, save_settings


def test_missing_file_yields_the_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.json") == DEFAULT_SETTINGS


def test_the_sheet_remembers_closed_cards_and_keeps_only_named_folds(tmp_path):
    store = tmp_path / "settings.json"
    assert load_settings(store).get("sheet_folds") == ["on_card"]
    save_settings({"sheet_folds": ["on_card", "alerts", 7, None, "", "alerts"]}, store)
    assert load_settings(store)["sheet_folds"] == ["on_card", "alerts"]
    save_settings({"sheet_folds": []}, store)
    assert load_settings(store)["sheet_folds"] == []
    assert sidebar._clean({"sheet_folds": "on_card"})["sheet_folds"] == ["on_card"]


def test_card_anatomy_defaults_to_task_for_a_new_install(tmp_path):
    assert load_settings(tmp_path / "settings.json").get("card_anatomy") == "task"


def test_card_anatomy_keeps_a_saved_sheet_name_first_until_chosen(tmp_path):
    store = tmp_path / "settings.json"
    store.write_text('{"volume": 0.2}')
    assert load_settings(store)["card_anatomy"] == "name"
    save_settings({"volume": 0.4}, store)
    assert load_settings(store)["card_anatomy"] == "name"
    for value in ["task", "name"]:
        save_settings({"card_anatomy": value}, store)
        assert load_settings(store)["card_anatomy"] == value


def test_a_saved_setting_survives_a_reload(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"volume": 0.9, "order": "name"}, store)
    reloaded = load_settings(store)
    assert reloaded["volume"] == 0.9 and reloaded["order"] == "name"


def test_saving_one_key_keeps_the_rest(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"volume": 0.2}, store)
    save_settings({"order": "name"}, store)
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
    status, _, body = server.handle("POST", "/settings?token=t", b'{"order": "attention"}')
    assert status == 200 and json.loads(body)["order"] == "attention"
    assert load_settings(store)["order"] == "attention"


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



def test_the_task_line_is_shown_by_default():
    assert sidebar.DEFAULT_SETTINGS["show_task"] is True
    assert "show_objective" not in sidebar.DEFAULT_SETTINGS


def test_every_piece_of_the_task_line_can_be_turned_off_and_starts_on():
    """The bar, the activity and the report age are each the session's own
    claim; a panel that shows fewer of them is still a working panel."""
    for key in ("show_task_bar", "show_task_activity", "show_task_age", "show_task_list"):
        assert sidebar.DEFAULT_SETTINGS[key] is True


def test_turning_off_a_task_line_piece_survives_a_reload(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"show_task_bar": False}, store)
    assert load_settings(store)["show_task_bar"] is False
    assert load_settings(store)["show_task_activity"] is True


def test_notices_are_on_by_default_and_each_moment_can_be_turned_off(tmp_path):
    """A banner is the only signal that reaches you in another application,
    so it starts on; a question and a finished turn are separate switches
    under it, shaped like the sound pair."""
    for key in ("notify", "notify_blocked", "notify_done"):
        assert sidebar.DEFAULT_SETTINGS[key] is True
    store = tmp_path / "s.json"
    save_settings({"notify_done": False}, store)
    assert load_settings(store)["notify_done"] is False
    assert load_settings(store)["notify_blocked"] is True



def test_linking_cards_starts_off_and_turning_it_on_survives_a_reload(tmp_path):
    """Linking is experimental: a panel that never asked for it links nothing."""
    assert sidebar.DEFAULT_SETTINGS["links"] is False
    store = tmp_path / "s.json"
    save_settings({"links": True}, store)
    assert load_settings(store)["links"] is True


def test_codex_hears_the_memory_index_only_once_the_switch_the_panel_saved_is_on(tmp_path):
    """The index goes to OpenAI, so a panel that never turned the switch on sends nothing. The Codex
    hook reads the sheet the daemon writes, at the same place under HOME."""
    spec = importlib.util.spec_from_file_location(
        "emit_state", Path(__file__).resolve().parent.parent / "plugin" / "hooks-handlers" / "emit-state.py")
    emit_state = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(emit_state)
    assert sidebar.SETTINGS_FILE.relative_to(Path.home()) == Path(".claude/agents-sidebar-settings.json")
    store = tmp_path / ".claude" / "agents-sidebar-settings.json"
    store.parent.mkdir()
    save_settings({}, store)
    assert (load_settings(store)["codex_memory_note"], emit_state.memory_switch_on(str(tmp_path))) == (False, False)
    save_settings({"codex_memory_note": True}, store)
    assert emit_state.memory_switch_on(str(tmp_path)) is True


# -------------------------------------------------------------------- version

def test_the_version_is_the_file_s_first_line(tmp_path):
    (tmp_path / "VERSION").write_text("2026.09.3\n")
    assert sidebar.version(tmp_path / "VERSION") == "2026.09.3"


def test_no_version_file_means_no_version(tmp_path):
    assert sidebar.version(tmp_path / "VERSION") is None


def test_the_limits_foot_starts_open_and_stays_folded_once_folded(tmp_path):
    """The accounts and limits at the panel's foot show in full until their
    head is clicked; folded, they stay folded across a save and a reload."""
    assert sidebar.DEFAULT_SETTINGS["limits_folded"] is False
    store = tmp_path / "s.json"
    save_settings({"limits_folded": True}, store)
    assert load_settings(store)["limits_folded"] is True


def test_history_opens_on_sessions_until_the_activity_tab_is_shown(tmp_path):
    """The tab History last showed is the one it opens on, across a reload
    of the panel and a restart of the daemon."""
    store = tmp_path / "settings.json"
    assert load_settings(store)["history_tab"] == "sessions"
    for tab in ("activity", "sessions"):
        assert save_settings({"history_tab": tab}, store)["history_tab"] == tab
        assert load_settings(store)["history_tab"] == tab


def test_a_history_tab_that_is_not_one_of_them_is_refused():
    for junk in ("Activity", "ports", "", None, 1, True, ["activity"]):
        assert sidebar._clean({"history_tab": junk})["history_tab"] == "sessions"


def test_the_shown_history_tab_comes_back_in_the_settings_the_page_takes(tmp_path):
    """The page replaces its settings with this reply, so a tab the reply
    left out would snap back to Sessions."""
    server, store = _server(tmp_path)
    status, _, body = server.handle("POST", "/settings?token=t", b'{"history_tab": "activity"}')
    assert status == 200 and json.loads(body)["history_tab"] == "activity"
    assert json.loads(server.handle("GET", "/settings?token=t", b"")[2])["history_tab"] == "activity"


def test_switching_accounts_automatically_is_off_until_asked_for():
    assert DEFAULT_SETTINGS["auto_switch"] is False


def test_cards_are_grouped_by_agent_unless_told_otherwise(tmp_path):
    """One of four: a tag after the name, a mark in the corner, cards grouped
    under a head per agent, or nothing beyond the glyph on the facts line."""
    store = tmp_path / "settings.json"
    assert DEFAULT_SETTINGS["provider_mark"] == "groups"
    for choice in ("corner", "groups", "off", "tag"):
        assert save_settings({"provider_mark": choice}, store)["provider_mark"] == choice
        assert load_settings(store)["provider_mark"] == choice


def test_a_way_of_marking_the_agent_that_is_not_one_of_them_is_refused():
    """Refused as a number that is not one is: the default stands."""
    for junk in ("stripe", "", None, 3, True, ["tag"]):
        assert sidebar._clean({"provider_mark": junk})["provider_mark"] == "groups"


def test_shell_names_keep_the_panel_face_until_another_is_chosen(tmp_path):
    """One of three: the panel's own face, SF Mono, or the terminal's font."""
    store = tmp_path / "settings.json"
    assert DEFAULT_SETTINGS["shell_font"] == "system"
    for choice in ("mono", "terminal", "system"):
        assert save_settings({"shell_font": choice}, store)["shell_font"] == choice
        assert load_settings(store)["shell_font"] == choice


def test_a_face_for_shell_names_that_is_not_one_of_them_is_refused():
    for junk in ("Menlo", "", None, 1, True, ["mono"]):
        assert sidebar._clean({"shell_font": junk})["shell_font"] == "system"


def test_session_rows_are_cards_until_another_style_is_chosen(tmp_path):
    """One of six: today's cards, hairlines between rows, air between them,
    rules inset to the text column, outlines with the canvas for a fill, or
    Serenity's quiet list."""
    store = tmp_path / "settings.json"
    assert DEFAULT_SETTINGS["card_style"] == "cards"
    for choice in ("hairlines", "air", "inset", "outlines", "serenity", "cards"):
        assert save_settings({"card_style": choice}, store)["card_style"] == choice
        assert load_settings(store)["card_style"] == choice


def test_a_settings_file_saved_before_card_styles_loads_as_cards(tmp_path):
    store = tmp_path / "settings.json"
    store.write_text(json.dumps({"shell_font": "mono"}))
    assert load_settings(store)["card_style"] == "cards"


def test_a_card_style_that_is_not_one_of_them_is_refused():
    for junk in ("Hairlines", "flat", "", None, 2, True, ["air"]):
        assert sidebar._clean({"card_style": junk})["card_style"] == "cards"


def test_a_stored_muted_flag_is_ignored(tmp_path):
    """Mute everything was a second off switch for sounds; a file that still
    carries it loads without it."""
    store = tmp_path / "settings.json"
    store.write_text(json.dumps({"muted": True}))
    assert "muted" not in load_settings(store)


def test_order_can_be_by_hand(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"order": "hand"}, store)
    assert load_settings(store)["order"] == "hand"


def test_a_hand_order_keeps_names_once_in_their_order(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"hand_order": ["beacon", "atlas", "beacon", "", 7, None, "cobalt"]}, store)
    assert load_settings(store)["hand_order"] == ["beacon", "atlas", "cobalt"]


def test_a_hand_order_that_is_not_a_list_is_ignored(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"hand_order": "atlas"}, store)
    assert load_settings(store)["hand_order"] == []


def test_a_hand_order_keeps_at_most_two_hundred_names(tmp_path):
    store = tmp_path / "settings.json"
    names = [f"s{i:03}" for i in range(250)]
    save_settings({"hand_order": names}, store)
    assert load_settings(store)["hand_order"] == names[:200]


def test_the_finished_settings_and_the_tab_status_default_on(tmp_path):
    s = load_settings(tmp_path / "none.json")
    assert {k: s[k] for k in ("finished_first", "finished_wash", "mark_badge", "tab_status", "offer_tab_status")} == \
        {"finished_first": True, "finished_wash": True, "mark_badge": True, "tab_status": True, "offer_tab_status": True}


def test_a_new_setting_takes_its_default_on_an_install_that_saved_before_it(tmp_path):
    """The tab status and the session colour on the tab default on everywhere,
    not only where nothing was saved yet."""
    store = tmp_path / "settings.json"
    store.write_text('{"mark_badge": false, "offer_statusline": false}')
    s = load_settings(store)
    assert (s["tab_status"], s["offer_tab_status"], s["tab_colour"], s["mark_badge"]) == (True, True, True, False)


def test_api_credits_are_off_until_asked_for(tmp_path):
    """The spec's promise: nothing changes for an install that never turns it on."""
    assert load_settings(tmp_path / "nope.json")["api_fallback"] is False


def test_the_spend_cap_is_no_panel_setting(tmp_path):
    """Each account's key carries its own cap, in the account store."""
    store = tmp_path / "settings.json"
    saved = save_settings({"api_fallback": True, "api_fallback_cap_usd": 12.5}, store)
    assert (saved["api_fallback"], "api_fallback_cap_usd" in saved) == (True, False)
