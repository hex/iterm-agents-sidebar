"""The API fallback's record and its step: when sessions move to API credits and back.

Pure: the record, the reading and the clock are passed in, so each case is a
worked example from the spec's failure list.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api_fallback  # noqa: E402
from api_fallback import blank, step  # noqa: E402

NOW = 1_000_000.0
HELPER = "/opt/agents-sidebar/api-key-helper.sh"


def account(account_id, name, key=True, cap_usd=50.0):
    """An account as the reading carries it: whether it has a key, its cap, and the command for its key."""
    return {"id": account_id, "name": name, "key": key, "cap_usd": cap_usd, "command": f"{HELPER} {account_id}"}


#: One account, alice's, with a key: the fallback as it was before keys were per account.
ALICE = [account("acct-1", "alice")]
COMMAND = ALICE[0]["command"]
#: alice and bob with a key each, and a third account without one.
THREE = [account("acct-1", "alice"), account("acct-2", "bob"), account("acct-3", "Account 3", key=False)]


def reading(**changes):
    """Every account full, the setting on and alice's key stored and active: entry is due."""
    base = {"enabled": True, "blocked": "full", "room": False, "helper": "absent", "helper_command": None,
            "costs": {}, "stop_failures": [], "answer": None, "reread_tokens": None, "bridge": True,
            "active": "acct-1", "accounts": ALICE}
    return dict(base, **changes)


NO_KEY = {"accounts": [account("acct-1", "alice", key=False)]}


def capped(dollars, accounts=ALICE):
    return [dict(a, cap_usd=dollars) for a in accounts]


def run(record, steps):
    """Each (reading, now) in turn -> the last record and every effect, in order."""
    effects = []
    for seen, now in steps:
        record, done = step(record, seen, now)
        effects += done
    return record, effects


def did(effects):
    return [e["do"] if e["do"] != "notice" else f"notice {e['which']}" for e in effects]


def test_unreadable_accounts_never_start_entry():
    record, effects = step(blank(), reading(blocked="unreadable"), NOW)
    assert record["phase"] == "off"
    assert effects == []


def test_the_setting_off_or_no_key_never_starts_entry():
    for changed in ({"enabled": False}, NO_KEY):
        record, effects = step(blank(), reading(**changed), NOW)
        assert (record["phase"], effects) == ("off", []), changed


def test_one_full_account_with_auto_switch_off_starts_entry():
    """The reading's `blocked` is the gate-free decision, so a lone account
    with auto-switch off still answers "full"."""
    record, effects = step(blank(), reading(blocked="full"), NOW)
    assert record["phase"] == "entering"
    assert record["deadline"] == NOW + 60
    assert did(effects) == ["notice entry"]


def test_entry_waits_the_grace():
    record, effects = run(blank(), [(reading(), NOW), (reading(), NOW + 59)])
    assert record["phase"] == "entering"
    assert "helper_in" not in did(effects)
    record, effects = step(record, reading(), NOW + 60)
    assert record["phase"] == "on"
    assert (record["since"], record["flips"]) == (NOW + 60, 1)
    assert did(effects) == ["notice_down", "helper_in", "log"]


def test_not_now_during_entry_holds_until_an_account_has_room():
    record, _ = step(blank(), reading(), NOW)
    record, effects = step(record, reading(answer="not_now"), NOW + 10)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "not_now")
    assert did(effects) == ["notice_down"]
    record, effects = run(record, [(reading(), NOW + 40), (reading(), NOW + 200)])
    assert (record["phase"], effects) == ("off", []), "a blocked reading in between does not re-enter"
    record, effects = step(record, reading(blocked=None, room=True), NOW + 300)
    assert (record["phase"], record["hold"], effects) == ("off", None, [])
    assert step(record, reading(), NOW + 330)[0]["phase"] == "entering", "and it comes again"


def test_a_foreign_helper_never_starts_entry_and_says_why_once():
    record, effects = step(blank(), reading(helper="foreign"), NOW)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "refused")
    assert record["hold"]["why"] == "another tool's apiKeyHelper is set in settings.json"
    assert did(effects) == ["notice refused", "log"]
    record, effects = step(record, reading(helper="foreign"), NOW + 30)
    assert (record["phase"], effects) == ("off", [])


def test_a_settings_file_that_cannot_be_read_refuses_entry():
    record, _ = step(blank(), reading(helper="unreadable"), NOW)
    assert record["hold"]["why"] == "settings.json cannot be read"


def test_a_mid_grace_change_takes_the_notice_down():
    """Room arrived, a stale reading, the setting turned off, the key forgotten,
    or another tool's helper: the entry is no longer due."""
    for changed in ({"blocked": None, "room": True}, {"blocked": None}, {"blocked": "unreadable"},
                    {"enabled": False}, NO_KEY, {"helper": "foreign"}):
        entering, _ = step(blank(), reading(), NOW)
        record, effects = step(entering, reading(**changed), NOW + 30)
        assert (record["phase"], record["hold"], did(effects)) == ("off", None, ["notice_down"]), changed


ROOM = {"blocked": None, "room": True, "helper": "ours", "helper_command": COMMAND}
STILL_FULL = {"helper": "ours", "helper_command": COMMAND}


def on_since(start=NOW, costs=None):
    """A record that entered at `start`, its helper written, with `costs` as the spend baseline."""
    record, _ = step(blank(), reading(costs=costs or {}), start - 60)
    record, _ = step(record, reading(costs=costs or {}), start)
    assert record["phase"] == "on"
    return dict(record, writing=False)


def test_exit_waits_for_room():
    record, effects = step(on_since(), reading(**STILL_FULL), NOW + 30)
    assert (record["phase"], effects) == ("on", [])


def test_room_asks_first_and_the_removal_comes_after_the_grace():
    record, effects = step(on_since(), reading(**dict(ROOM, reread_tokens=4000)), NOW + 30)
    assert (record["phase"], record["deadline"]) == ("leaving", NOW + 90)
    assert effects == [{"do": "notice", "which": "exit", "tokens": 4000}]
    held, effects = step(record, reading(**ROOM), NOW + 89)
    assert (held["phase"], effects) == ("leaving", [])
    record, effects = step(held, reading(**ROOM), NOW + 90)
    assert (record["phase"], record["hold"], record["since"], record["flips"]) == ("off", None, None, 2)
    assert did(effects) == ["notice_down", "helper_out", "log"]


def test_room_gone_during_the_grace_stays_on_credits():
    leaving, _ = step(on_since(), reading(**ROOM), NOW + 30)
    record, effects = step(leaving, reading(**STILL_FULL), NOW + 60)
    assert (record["phase"], record["deadline"], did(effects)) == ("on", None, ["notice_down"])


def test_not_now_on_the_way_out_asks_again_after_half_an_hour():
    leaving, _ = step(on_since(), reading(**ROOM), NOW + 30)
    record, effects = step(leaving, reading(**dict(ROOM, answer="not_now")), NOW + 40)
    assert (record["phase"], record["ask_again_at"], did(effects)) == ("on", NOW + 1840, ["notice_down"])
    assert step(record, reading(**ROOM), NOW + 1839)[0]["phase"] == "on"
    assert step(record, reading(**ROOM), NOW + 1840)[0]["phase"] == "leaving"


def test_the_cap_ends_it_at_once_holds_and_a_raise_lifts_the_hold():
    start = on_since()
    record, _ = step(start, reading(**dict(STILL_FULL, costs={"s1": 49.0})), NOW + 30)
    assert record["phase"] == "on", "under the cap nothing happens"
    record, effects = step(record, reading(**dict(STILL_FULL, costs={"s1": 50.01})), NOW + 60)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "cap")
    assert did(effects) == ["helper_out", "notice cap", "log"]
    held, effects = step(record, reading(helper="absent"), NOW + 90)
    assert (held["phase"], held["hold"]["reason"], effects) == ("off", "cap", []), "no re-entry while full"
    still, _ = step(held, reading(accounts=capped(50.0), helper="absent"), NOW + 120)
    assert still["hold"]["reason"] == "cap"
    lifted, effects = step(still, reading(accounts=capped(60.0), helper="absent"), NOW + 150)
    assert (lifted["phase"], lifted["hold"], effects) == ("off", None, [])
    assert api_fallback.spent(lifted) == pytest.approx(50.01), "the figure stays readable after the exit"


def test_a_new_fallback_starts_its_spend_from_zero():
    record, _ = step(on_since(), reading(**dict(STILL_FULL, costs={"s1": 51.0})), NOW + 30)
    record, _ = step(record, reading(accounts=capped(60.0), helper="absent"), NOW + 60)
    entering, _ = step(record, reading(accounts=capped(60.0), helper="absent", costs={"s1": 51.0}), NOW + 90)
    again, _ = step(entering, reading(accounts=capped(60.0), helper="absent", costs={"s1": 51.0}), NOW + 150)
    assert (again["phase"], api_fallback.spent(again)) == ("on", 0)


def test_running_out_of_credits_or_a_refused_key_ends_it_at_once_and_holds():
    for error in ("billing_error", "authentication_failed"):
        record, effects = step(on_since(), reading(**dict(STILL_FULL, stop_failures=[error])), NOW + 30)
        assert (record["phase"], record["hold"]["reason"]) == ("off", error)
        assert did(effects) == ["helper_out", f"notice {error}", "log"]
        held, effects = step(record, reading(), NOW + 60)
        assert (held["phase"], effects) == ("off", []), "no re-entry while full"


def test_another_stop_failure_changes_nothing():
    record, effects = step(on_since(), reading(**dict(STILL_FULL, stop_failures=["rate_limit"])), NOW + 30)
    assert (record["phase"], effects) == ("on", [])


def test_a_stop_failure_while_off_changes_nothing():
    record, effects = step(blank(), reading(blocked=None, stop_failures=["billing_error"]), NOW)
    assert (record, effects) == (blank(), [])


def test_a_helper_gone_while_on_goes_off_and_writes_nothing():
    for state in ("absent", "foreign"):
        record, effects = step(on_since(), reading(helper=state), NOW + 30)
        assert (record["phase"], record["hold"]["reason"]) == ("off", "helper_gone"), state
        assert did(effects) == ["log"], state


def test_settings_that_cannot_be_read_hold_position():
    record, effects = step(on_since(), reading(helper="unreadable", stop_failures=["billing_error"]), NOW + 30)
    assert (record["phase"], effects) == ("on", [])


def test_the_setting_turned_off_or_the_last_key_forgotten_ends_it_with_no_hold():
    for changed in ({"enabled": False}, NO_KEY):
        record, effects = step(on_since(), reading(**dict(STILL_FULL, **changed)), NOW + 30)
        assert (record["phase"], record["hold"], did(effects)) == ("off", None, ["helper_out", "log"]), changed


def test_what_ends_it_at_once_goes_in_order():
    gone_and_off = step(on_since(), reading(helper="absent", enabled=False, stop_failures=["billing_error"]), NOW + 30)
    assert gone_and_off[0]["hold"]["reason"] == "helper_gone", "nothing to write comes before a write"
    off_and_failed = step(on_since(), reading(**dict(STILL_FULL, enabled=False, stop_failures=["billing_error"])), NOW + 30)
    assert off_and_failed[0]["hold"] is None, "turned off outranks a failure: no hold for a choice made"
    failed_and_over = step(on_since(), reading(**dict(STILL_FULL, stop_failures=["billing_error"], costs={"s1": 99.0})), NOW + 30)
    assert failed_and_over[0]["hold"]["reason"] == "billing_error", "a failure outranks the cap"
    over_and_room = step(on_since(), reading(**dict(ROOM, costs={"s1": 99.0})), NOW + 30)
    assert over_and_room[0]["phase"] == "off", "the cap does not wait out a grace"


def test_the_grace_on_the_way_out_does_not_delay_what_ends_it_at_once():
    leaving, _ = step(on_since(), reading(**ROOM), NOW + 30)
    record, effects = step(leaving, reading(**dict(ROOM, stop_failures=["billing_error"])), NOW + 40)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "billing_error")
    assert did(effects) == ["notice_down", "helper_out", "notice billing_error", "log"]


def test_spend_counts_each_rise_and_a_session_that_left_keeps_its_share():
    record = on_since(costs={"s1": 5.0})
    record, _ = step(record, reading(**dict(STILL_FULL, costs={"s1": 7.5, "s2": 1.25})), NOW + 30)
    assert api_fallback.spent(record) == 3.75, "a session first seen after entry counts from 0"
    record, _ = step(record, reading(**dict(STILL_FULL, costs={"s2": 2.0})), NOW + 60)
    assert api_fallback.spent(record) == 4.5, "a session that left keeps its share"


def test_a_cost_lower_than_the_last_is_a_new_process_and_adds_from_zero():
    """A reviewer's resumed session: 120 at entry, then a restart that counts up from 0 again."""
    record = on_since(costs={"s1": 120.0})
    for later, cost in enumerate((0.0, 40.0), start=1):
        record, effects = step(record, reading(**dict(STILL_FULL, costs={"s1": cost})), NOW + 30 * later)
        assert (record["phase"], effects) == ("on", []), cost
    assert api_fallback.spent(record) == 40.0
    record, effects = step(record, reading(**dict(STILL_FULL, costs={"s1": 80.0})), NOW + 90)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "cap")
    assert api_fallback.spent(record) == 80.0
    assert did(effects) == ["helper_out", "notice cap", "log"]


def test_a_baseline_is_taken_only_at_entry():
    record = on_since(costs={"s1": 10.0})
    record, _ = step(record, reading(**dict(STILL_FULL, costs={"s1": 2.0})), NOW + 30)
    record, _ = step(record, reading(**dict(STILL_FULL, costs={"s1": 3.0})), NOW + 60)
    assert api_fallback.spent(record) == 3.0, "the restart's cost, not its rise from the entry figure"


def test_a_stray_helper_comes_out_whenever_the_record_says_it_should_not_be_in():
    for start in (dict(blank(), flips=2), step(blank(), reading(), NOW - 10)[0]):
        record, effects = step(start, reading(helper="ours", blocked=None, enabled=False), NOW)
        assert record["phase"] == "off"
        assert "helper_out" in did(effects), start["phase"]


def test_a_setting_never_turned_on_and_a_blank_record_emit_nothing():
    for state in ("absent", "ours", "foreign", "unreadable"):
        assert step(blank(), reading(helper=state, enabled=False), NOW) == (blank(), []), state


def test_a_restart_on_the_way_out_keeps_the_helper():
    leaving, _ = step(on_since(), reading(**ROOM), NOW + 30)
    record, effects = step(leaving, reading(**ROOM), NOW + 40)
    assert (record["phase"], effects) == ("leaving", [])


def test_a_refused_entry_takes_its_flip_back_and_holds():
    record = api_fallback.refused(on_since(), "the key was refused (401)", NOW + 1)
    assert (record["phase"], record["flips"], record["since"]) == ("off", 0, None)
    assert record["hold"] == {"reason": "refused", "at": NOW + 1, "why": "the key was refused (401)"}


def test_saving_a_key_lifts_a_refused_hold_and_no_other():
    refused = api_fallback.refused(blank(), "bad", NOW)
    assert api_fallback.key_saved(refused, "acct-1")["hold"] is None
    over, _ = step(on_since(), reading(**dict(STILL_FULL, costs={"s1": 99.0})), NOW + 30)
    saved = api_fallback.key_saved(over, "acct-1")
    assert saved["hold"]["reason"] == "cap"
    assert step(saved, reading(helper="absent"), NOW + 60)[0]["hold"]["reason"] == "cap", \
        "a cap is the account's spend, whatever key it uses"


def test_a_missing_record_loads_off_and_says_nothing(tmp_path):
    assert api_fallback.load(tmp_path / "api-fallback.json") == (blank(), None)


def test_a_record_round_trips(tmp_path):
    record = on_since(costs={"s1": 1.5})
    api_fallback.save(tmp_path / "api-fallback.json", record)
    assert api_fallback.load(tmp_path / "api-fallback.json") == (record, None)
    assert (tmp_path / "api-fallback.json").stat().st_mode & 0o077 == 0


def test_an_unreadable_record_loads_off_and_reports_it(tmp_path):
    path = tmp_path / "api-fallback.json"
    for text in ("not json", "[]", json.dumps(dict(blank(), phase="sideways")),
                 json.dumps(dict(blank(), hold={"reason": "whim", "at": 1, "why": "x"})),
                 json.dumps(dict(blank(), phase="on", since=1, key_account=None))):
        path.write_text(text)
        record, problem = api_fallback.load(path)
        assert record == blank(), text
        assert str(path) in problem, text


def test_each_flip_is_recorded_for_the_switch_line():
    record = on_since()
    assert record["last_flip"] == {"at": NOW, "to": "api", "why": "every account is full"}
    leaving, _ = step(record, reading(**ROOM), NOW + 30)
    back, _ = step(leaving, reading(**ROOM), NOW + 90)
    assert back["last_flip"] == {"at": NOW + 90, "to": "subscription", "why": "an account has room"}
    capped, _ = step(on_since(), reading(**dict(STILL_FULL, costs={"s1": 99.0})), NOW + 30)
    assert capped["last_flip"] == {"at": NOW + 30, "to": "subscription", "why": "cap reached"}
    assert api_fallback.refused(on_since(), "bad", NOW + 1)["last_flip"] is None, "a refused entry never flipped"


def test_a_helper_that_took_itself_out_ends_the_fallback_with_no_hold():
    """The daemon was down and the helper went back to the subscription on
    its own: entry may come again through its notice."""
    for record in (on_since(), step(on_since(), reading(**ROOM), NOW + 30)[0]):
        back = api_fallback.orphaned(record, NOW + 100)
        assert (back["phase"], back["hold"], back["deadline"], back["flips"]) == ("off", None, None, 2)
        assert back["last_flip"] == {"at": NOW + 100, "to": "subscription",
                                     "why": "the helper took itself out"}


def test_entry_saves_a_writing_mark_with_the_command_it_will_write():
    entering, _ = step(blank(), reading(), NOW - 60)
    record, effects = step(entering, reading(), NOW)
    assert (record["phase"], record["writing"], record["command"]) == ("on", True, COMMAND)
    assert "helper_in" in did(effects)


def test_a_crash_while_writing_with_no_helper_goes_off_with_no_hold():
    """A daemon that stopped mid-entry is not another tool's doing: the helper never reached the file."""
    record = dict(on_since(), writing=True)
    after, effects = step(record, reading(helper="absent"), NOW + 30)
    assert (after["phase"], after["hold"], after["writing"], after["flips"]) == ("off", None, False, 0)
    assert did(effects) == ["log"]
    assert step(after, reading(helper="absent"), NOW + 60)[0]["phase"] == "entering", "and entry can come again"


def test_a_crash_while_writing_with_the_helper_in_clears_the_mark_and_stays_on():
    record = dict(on_since(), writing=True)
    after, effects = step(record, reading(**STILL_FULL), NOW + 30)
    assert (after["phase"], after["writing"], effects) == ("on", False, [])


def test_a_crash_between_a_moves_save_and_its_write_writes_the_new_command_again():
    """The file still runs alice's key, which the record moved away from: the write is due again."""
    record = dict(on_since(), writing=True, key_account="acct-2", command=THREE[1]["command"])
    after, effects = step(record, reading(**dict(STILL_FULL, accounts=THREE)), NOW + 30)
    assert (after["phase"], after["writing"], after["key_account"], effects) == ("on", True, "acct-2", [{"do": "helper_in"}])


def test_a_helper_missing_with_no_writing_mark_is_another_tools_doing():
    after, _ = step(dict(on_since(), writing=False), reading(helper="absent"), NOW + 30)
    assert after["hold"]["reason"] == "helper_gone"


def test_a_refused_entry_clears_the_writing_mark():
    assert api_fallback.refused(dict(on_since(), writing=True), "bad", NOW + 1)["writing"] is False


def retrying(record=None):
    """An entry whose key could not be checked: off, no hold, trying again."""
    record = record or step(step(blank(), reading(), NOW - 60)[0], reading(), NOW)[0]
    return api_fallback.unavailable(record, "the API did not answer (timed out)")


def test_a_key_that_could_not_be_checked_leaves_the_fallback_off_with_no_hold_and_says_so_once():
    record, effects = retrying()
    assert (record["phase"], record["hold"], record["flips"], record["writing"]) == ("off", None, 0, False)
    assert record["retrying"] == "the API did not answer (timed out)"
    assert did(effects) == ["notice unavailable", "log"]
    assert effects[0]["why"] == "the API did not answer (timed out)"
    again, effects = api_fallback.unavailable(dict(record, phase="on", flips=1, writing=True), "still down")
    assert (again["phase"], again["retrying"], effects) == ("off", "the API did not answer (timed out)", []), \
        "one notice and one log line for the whole blocked episode"


def test_a_retry_goes_straight_to_the_write_with_no_notice_or_grace():
    record, _ = retrying()
    record, effects = step(record, reading(), NOW + 30)
    assert (record["phase"], record["writing"]) == ("on", True)
    assert did(effects) == ["helper_in"]


def test_a_retry_stops_when_the_blocked_state_ends_and_the_next_one_may_say_so_again():
    record, _ = retrying()
    record, effects = step(record, reading(blocked=None, room=True), NOW + 30)
    assert (record["phase"], record["retrying"], effects) == ("off", None, [])


def test_a_retry_respects_another_tools_helper():
    record, _ = retrying()
    record, effects = step(record, reading(helper="foreign"), NOW + 30)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "refused")
    assert record["retrying"] is None


def test_a_real_refusal_ends_a_retry():
    record, _ = retrying()
    record, _ = step(record, reading(), NOW + 30)
    assert api_fallback.refused(record, "the key was refused (401)", NOW + 31)["retrying"] is None


NO_BRIDGE = "the spend cap needs the statusline bridge, which is not installed"


def test_no_statusline_bridge_refuses_entry_and_says_why_once():
    record, effects = step(blank(), reading(bridge=False), NOW)
    assert (record["phase"], record["hold"]["reason"], record["hold"]["why"]) == ("off", "no_bridge", NO_BRIDGE)
    assert did(effects) == ["notice refused", "log"]
    assert effects[0]["why"] == NO_BRIDGE
    record, effects = step(record, reading(bridge=False), NOW + 30)
    assert (record["phase"], effects) == ("off", [])


def test_a_bridge_taken_out_during_the_grace_refuses_the_entry():
    entering, _ = step(blank(), reading(), NOW)
    record, effects = step(entering, reading(bridge=False), NOW + 30)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "no_bridge")
    assert did(effects) == ["notice_down", "notice refused", "log"]


def test_a_bridge_that_goes_away_while_on_ends_it_as_the_cap_would():
    record, effects = step(on_since(), reading(**dict(STILL_FULL, bridge=False)), NOW + 30)
    assert (record["phase"], record["hold"]["reason"], record["hold"]["why"]) == ("off", "no_bridge", NO_BRIDGE)
    assert did(effects) == ["helper_out", "notice no_bridge", "log"]
    record, effects = step(record, reading(helper="absent", bridge=False), NOW + 60)
    assert (record["phase"], effects) == ("off", []), "no re-entry while full and without it"


def test_the_bridge_back_lifts_its_hold_and_entry_comes_again():
    record, _ = step(blank(), reading(bridge=False), NOW)
    record, effects = step(record, reading(), NOW + 30)
    assert (record["phase"], record["hold"], effects) == ("off", None, [])
    assert step(record, reading(), NOW + 60)[0]["phase"] == "entering"


def test_room_lifts_a_bridge_hold_too():
    record, _ = step(blank(), reading(bridge=False), NOW)
    assert step(record, reading(bridge=False, blocked=None, room=True), NOW + 30)[0]["hold"] is None


def test_a_failed_turn_outranks_a_missing_bridge_and_a_missing_bridge_outranks_the_cap():
    failed = step(on_since(), reading(**dict(STILL_FULL, bridge=False, stop_failures=["billing_error"])), NOW + 30)
    assert failed[0]["hold"]["reason"] == "billing_error"
    over = step(on_since(), reading(**dict(STILL_FULL, bridge=False, costs={"s1": 99.0})), NOW + 30)
    assert over[0]["hold"]["reason"] == "no_bridge", "with no bridge the figure the cap reads is gone"


# A key per account: which key the fallback uses, and what moves it to another.

def entered(accounts=THREE, active="acct-1", costs=None):
    """On after the grace, its write still to come, with `active` the active account."""
    seen = reading(accounts=accounts, active=active, costs=costs or {})
    record, _ = step(blank(), seen, NOW - 60)
    record, effects = step(record, seen, NOW)
    assert record["phase"] == "on" and "helper_in" in did(effects)
    return record


def written(record, accounts=THREE):
    """The write the step asked for went through: -> the record after it."""
    after, _ = api_fallback.checked(record, reading(accounts=accounts), {"do": "helper_in"}, None, NOW)
    return after


def on_key(accounts=THREE, active="acct-1"):
    return written(entered(accounts, active), accounts)


def running(record, accounts=THREE, **changes):
    """A reading while the record's own command is in settings.json."""
    return reading(**dict({"helper": "ours", "helper_command": record["command"], "accounts": accounts}, **changes))


def test_the_active_accounts_key_is_used_when_it_has_one():
    record = entered(active="acct-2")
    assert (record["key_account"], record["command"]) == ("acct-2", f"{HELPER} acct-2")


def test_an_active_account_with_no_key_uses_the_next_accounts_key_in_list_order():
    assert entered(active="acct-3")["key_account"] == "acct-1", "the first in the list, not the one after the active"
    later = [account("acct-1", "alice", key=False), account("acct-2", "bob", key=False), account("acct-3", "Account 3")]
    assert entered(later, active="acct-1")["key_account"] == "acct-3"
    around = [account("acct-1", "alice"), account("acct-2", "bob", key=False), account("acct-3", "Account 3")]
    assert entered(around, active="acct-2")["key_account"] == "acct-1", "list order from the top, not the one after bob"


def test_with_no_account_holding_a_key_nothing_enters():
    nobody = [dict(a, key=False) for a in THREE]
    assert step(blank(), reading(accounts=nobody), NOW) == (blank(), [])


def test_a_refused_key_is_skipped_and_the_next_one_used():
    record = entered()
    refusal = api_fallback.KeyProblem("refused", "the key was refused (401)")
    moved, effects = api_fallback.checked(record, reading(accounts=THREE), {"do": "helper_in"}, refusal, NOW)
    assert (moved["phase"], moved["key_account"], moved["command"], moved["writing"]) == ("on", "acct-2", f"{HELPER} acct-2", True)
    assert moved["key_holds"]["acct-1"] == {"reason": "refused", "at": NOW, "why": "the key was refused (401)"}
    assert effects == [{"do": "helper_in", "moved": "the key was refused (401)"}]
    done, effects = api_fallback.checked(moved, reading(accounts=THREE), effects[0], None, NOW)
    assert (done["phase"], done["key_account"], done["writing"]) == ("on", "acct-2", False)
    assert effects[0] == {"do": "notice", "which": "moved", "why": "the key was refused (401)", "name": "bob"}


def test_the_last_key_refused_refuses_the_entry_as_before():
    record = entered(ALICE)
    refusal = api_fallback.KeyProblem("refused", "the key was refused (401)")
    after, effects = api_fallback.checked(record, reading(), {"do": "helper_in"}, refusal, NOW)
    assert (after["phase"], after["hold"]["reason"], after["flips"]) == ("off", "refused", 0)
    assert did(effects) == ["notice refused", "log"]


def test_a_key_at_its_cap_moves_to_the_next_key_at_once_with_a_notice_after():
    record = on_key()
    moved, effects = step(record, running(record, costs={"s1": 50.5}), NOW + 30)
    assert (moved["phase"], moved["key_account"], moved["writing"]) == ("on", "acct-2", True)
    assert moved["key_holds"]["acct-1"]["reason"] == "cap"
    assert effects == [{"do": "helper_in", "moved": "cap reached"}], "the write comes first, with no grace"
    done, effects = api_fallback.checked(moved, running(record), effects[0], None, NOW + 30)
    assert did(effects) == ["notice moved", "log"]
    assert (effects[0]["name"], effects[0]["why"]) == ("bob", "cap reached")
    assert not done["writing"]


def test_the_last_key_at_its_cap_ends_the_fallback_and_holds():
    record = on_key()
    moved, _ = step(record, running(record, costs={"s1": 50.5}), NOW + 30)
    moved = written(moved)
    ended, effects = step(moved, running(moved, costs={"s1": 101.0}), NOW + 60)
    assert (ended["phase"], ended["hold"]["reason"]) == ("off", "cap")
    assert did(effects) == ["helper_out", "notice cap", "log"]
    assert step(ended, reading(accounts=THREE), NOW + 90)[0]["phase"] == "off", "no re-entry while full"


def test_billing_error_on_the_key_in_use_moves_on():
    for error in ("billing_error", "authentication_failed"):
        record = on_key()
        moved, effects = step(record, running(record, stop_failures=[error]), NOW + 30)
        assert (moved["phase"], moved["key_account"]) == ("on", "acct-2"), error
        assert moved["key_holds"]["acct-1"]["reason"] == error
        assert effects == [{"do": "helper_in", "moved": api_fallback.EXIT_WHY[error]}]


def test_a_key_skipped_for_its_cap_or_refusal_is_not_tried_again_until_the_blocked_state_ends():
    refusal = api_fallback.KeyProblem("refused", "the key was refused (401)")
    record, _ = api_fallback.checked(entered(), reading(accounts=THREE), {"do": "helper_in"}, refusal, NOW)
    record = written(record)
    assert record["key_account"] == "acct-2"
    ended, _ = step(record, running(record, costs={"s1": 50.5}), NOW + 30)
    assert (ended["phase"], ended["hold"]["reason"]) == ("off", "cap"), "alice's refused key is not tried for bob's cap"
    held, effects = step(ended, reading(accounts=THREE), NOW + 60)
    assert (held["phase"], effects) == ("off", []), "nor while every account stays full"
    room, _ = step(held, reading(accounts=THREE, blocked=None, room=True), NOW + 90)
    assert (room["hold"], room["key_holds"]) == (None, {})
    assert entered_from(room)["key_account"] == "acct-1", "and once the blocked state ended and came again, alice's first"


def entered_from(record):
    record, _ = step(record, reading(accounts=THREE), NOW + 120)
    record, _ = step(record, reading(accounts=THREE), NOW + 180)
    return record


def test_a_capped_key_stays_skipped_while_on_another_and_a_raise_lifts_it():
    record = on_key()
    moved, _ = step(record, running(record, costs={"s1": 50.5}), NOW + 30)
    moved = written(moved)
    still, _ = step(moved, running(moved, costs={"s1": 51.0}), NOW + 60)
    assert still["key_holds"]["acct-1"]["reason"] == "cap"
    raised = [dict(THREE[0], cap_usd=80.0), *THREE[1:]]
    lifted, _ = step(still, running(still, raised, costs={"s1": 51.0}), NOW + 90)
    assert ("acct-1" in lifted["key_holds"], lifted["key_account"]) == (False, "acct-2"), "lifted, with no move back"


def test_forgetting_the_key_in_use_moves_to_the_next_key():
    record = on_key()
    forgot = [dict(THREE[0], key=False), *THREE[1:]]
    moved, effects = step(record, running(record, forgot), NOW + 30)
    assert (moved["phase"], moved["key_account"], moved["key_holds"]) == ("on", "acct-2", {})
    assert effects == [{"do": "helper_in", "moved": "the key was forgotten"}]


def test_forgetting_the_last_key_ends_the_fallback_with_no_hold():
    record = on_key(ALICE)
    ended, effects = step(record, running(record, NO_KEY["accounts"]), NOW + 30)
    assert (ended["phase"], ended["hold"]) == ("off", None)
    assert did(effects) == ["helper_out", "log"]


def test_spend_is_tallied_per_key():
    record = written(entered(costs={"s1": 10.0, "s2": 1.0}))
    record, _ = step(record, running(record, costs={"s1": 12.0, "s2": 1.5}), NOW + 30)
    assert record["spend"] == {"acct-1": 2.5}
    record, _ = step(record, running(record, stop_failures=["billing_error"], costs={"s1": 12.0, "s2": 1.5}), NOW + 60)
    record = written(record)
    record, _ = step(record, running(record, costs={"s1": 15.0, "s2": 2.0}), NOW + 90)
    assert record["spend"] == {"acct-1": 2.5, "acct-2": 3.5}
    assert api_fallback.spent(record) == 6.0


def test_a_key_that_cannot_be_checked_on_a_move_ends_the_fallback_and_tries_again():
    record = on_key()
    moved, effects = step(record, running(record, costs={"s1": 50.5}), NOW + 30)
    unanswered = api_fallback.KeyProblem("unavailable", "the API answered 503")
    ended, effects = api_fallback.checked(moved, running(record), effects[0], unanswered, NOW + 30)
    assert (ended["phase"], ended["hold"], ended["retrying"]) == ("off", None, "the API answered 503")
    assert did(effects) == ["helper_out", "notice unavailable", "log"]


def test_a_move_on_the_way_out_keeps_the_way_out_pending():
    record = on_key()
    leaving, _ = step(record, running(record, blocked=None, room=True), NOW + 30)
    moved, effects = step(leaving, running(leaving, blocked=None, room=True, stop_failures=["billing_error"]), NOW + 40)
    assert (moved["phase"], moved["key_account"], did(effects)) == ("leaving", "acct-2", ["helper_in"])


def test_key_holds_round_trip_and_a_bad_one_is_refused(tmp_path):
    record = dict(on_key(), key_holds={"acct-1": {"reason": "cap", "at": NOW, "why": "cap reached"}})
    api_fallback.save(tmp_path / "api-fallback.json", record)
    assert api_fallback.load(tmp_path / "api-fallback.json") == (record, None)
    (tmp_path / "api-fallback.json").write_text(json.dumps(dict(blank(), key_holds={"acct-1": {"reason": "whim"}})))
    assert api_fallback.load(tmp_path / "api-fallback.json")[0] == blank()


# Which failures are the key in use's: a failure counts against a key only in a session whose last
# fetch before it took that key. 2026-11-10: three keys were held in 92 s for failures that came
# from sessions still on the subscription and on the first key.

FETCHES = {101: [(NOW + 10, "acct-1"), (NOW + 70, "acct-2")], 102: [(NOW + 12, "acct-1")]}


def failure(error, pid, at):
    return {"error": error, "pid": pid, "at": at}


def test_a_failure_in_a_session_on_the_key_in_use_is_that_keys():
    assert api_fallback.failures_on_key([failure("billing_error", 101, NOW + 80)], FETCHES, "acct-2") == [
        "billing_error"]


def test_a_failure_in_a_session_still_on_an_earlier_key_is_not_the_key_in_uses():
    assert api_fallback.failures_on_key([failure("billing_error", 102, NOW + 80),
                                         failure("billing_error", 101, NOW + 40)], FETCHES, "acct-2") == []


def test_a_failure_in_a_session_that_never_took_a_key_is_no_keys():
    """It ran on the subscription: the settings had not reached it yet."""
    assert api_fallback.failures_on_key([failure("billing_error", 103, NOW + 80),
                                         failure("billing_error", None, NOW + 80),
                                         failure("billing_error", 101, NOW + 5)], FETCHES, "acct-1") == []
