"""What the meter loop tells the API fallback: why the active account is blocked, and whether it has room.

Readings are placed in the meters directly, so no Keychain or network is touched.
Ways this can go wrong, and the test for each:
- accounts that cannot be read count as full;
- an account that needs a login, or a switch auto-switch would not make, counts as room;
- a stale reading, or one that only says "stay", counts as room;
- a reading on course to fill counts as room and as full at once;
- a projection alone, with the figure under the switch line, starts the fallback;
- a fallback that started goes straight back on a flat reading;
- one account with auto-switch off never reads as full.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api_fallback  # noqa: E402
from accounts import AccountMeters, save_store  # noqa: E402

NOW = 1_000_000
HOUR, DAY = 3600, 86400
A = {"id": "acct-1", "accountUuid": "uuid-1"}
B = {"id": "acct-2", "accountUuid": "uuid-2"}


def usage(five, seven=10):
    return {"five_hour": {"used": five, "resets_at": NOW + 4 * HOUR},
            "seven_day": {"used": seven, "resets_at": NOW + 3 * DAY}, "models": []}


def state(reading, fetched_at=NOW, earlier=None, earlier_at=None, outcome="ok", tried_at=None):
    return {"usage": reading, "fetched_at": fetched_at, "outcome": outcome, "earlier_usage": earlier,
            "earlier_at": earlier_at, "tried_at": fetched_at if tried_at is None else tried_at,
            "next_at": fetched_at + 180}


def meters(tmp_path, accounts, states):
    store = tmp_path / "accounts.json"
    save_store(str(store), accounts)
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"oauthAccount": {"accountUuid": "uuid-1"}}))
    loop = AccountMeters(str(store), "agents-sidebar-test", ("agents-sidebar-test", "unused"), str(claude_json))
    loop.states = states
    return loop


def decided(view):
    """The part of a view that says whether to enter or leave."""
    return {"blocked": view["blocked"], "room": view["room"]}


def test_one_full_account_with_auto_switch_off_is_full(tmp_path):
    view = meters(tmp_path, [A], {"acct-1": state(usage(96))}).fallback_view(NOW, auto=False)
    assert decided(view) == {"blocked": "full", "room": False}


def test_an_account_under_the_line_has_room(tmp_path):
    view = meters(tmp_path, [A], {"acct-1": state(usage(50))}).fallback_view(NOW, auto=False)
    assert decided(view) == {"blocked": None, "room": True}


def test_an_other_account_that_cannot_be_read_is_not_full(tmp_path):
    tried = state(usage(20), fetched_at=NOW - 400, outcome="failed", tried_at=NOW - 20)
    view = meters(tmp_path, [A, B], {"acct-1": state(usage(96)), "acct-2": tried}).fallback_view(NOW, auto=False)
    assert decided(view) == {"blocked": "unreadable", "room": False}


def test_a_switch_is_room_only_when_auto_switch_would_make_it(tmp_path):
    states = {"acct-1": state(usage(96)), "acct-2": state(usage(20))}
    assert decided(meters(tmp_path, [A, B], states).fallback_view(NOW, auto=True)) == {"blocked": None, "room": True}
    assert decided(meters(tmp_path, [A, B], states).fallback_view(NOW, auto=False)) == {"blocked": None, "room": False}


def test_an_account_that_needs_a_login_is_no_room(tmp_path):
    states = {"acct-1": state(usage(96)), "acct-2": state(usage(5))}
    view = meters(tmp_path, [A, dict(B, needsLogin=True)], states).fallback_view(NOW, auto=True)
    assert decided(view) == {"blocked": "full", "room": False}


def test_a_stale_reading_of_the_active_account_says_nothing(tmp_path):
    for figure in (96, 50):
        view = meters(tmp_path, [A], {"acct-1": state(usage(figure), fetched_at=NOW - 400)}).fallback_view(NOW, auto=False)
        assert decided(view) == {"blocked": None, "room": False}, figure


def test_a_window_reset_since_the_reading_says_nothing_until_it_is_read_again(tmp_path):
    reading = dict(usage(96), five_hour={"used": 96, "resets_at": NOW - 10})
    view = meters(tmp_path, [A], {"acct-1": state(reading)}).fallback_view(NOW, auto=False)
    assert decided(view) == {"blocked": None, "room": False}


def test_an_account_on_course_to_fill_under_the_line_is_neither_full_nor_room(tmp_path):
    """Climbing fast at 85: auto-switch would leave it, so it is no account to come
    back to, but a projection alone never moves sessions onto credits."""
    climbing = state(usage(85), earlier=usage(75), earlier_at=NOW - 120)
    view = meters(tmp_path, [A], {"acct-1": climbing}).fallback_view(NOW, auto=False)
    assert decided(view) == {"blocked": None, "room": False}


def test_full_starts_at_the_switch_line_exactly(tmp_path):
    climbing = state(usage(90), earlier=usage(80), earlier_at=NOW - 120)
    assert decided(meters(tmp_path, [A], {"acct-1": climbing}).fallback_view(NOW, auto=False)) == {"blocked": "full", "room": False}


def test_a_fallback_on_course_under_ninety_never_starts_and_one_at_ninety_stays_until_a_reset(tmp_path):
    """The reviewer's flip-flop, run through the real view and step: usage climbs at
    4.5 points per 90 s while the sessions are on the subscription and stops
    climbing once they run on credits. Before the line nothing starts. After it,
    the flat readings never read as room, so there is one trip and no way back
    until the window resets."""
    loop = meters(tmp_path, [dict(A, apiKeyLast4="wxyz")], {})
    loop.models = {"opus"}
    record = api_fallback.blank()
    five, earlier, at, phases, moved = 70.0, 55.0, NOW - 300, [], []
    clock = NOW

    def reading_of(view):
        return {"enabled": True, "blocked": view["blocked"], "room": view["room"], "active": view["active"],
                "accounts": [{"id": key["id"], "name": key["name"], "key": key["last4"] is not None,
                              "cap_usd": key["cap_usd"], "command": f"/x/api-key-helper.sh {key['id']}"}
                             for key in view["keys"]],
                "helper": "ours" if record["phase"] in api_fallback.HELPER_IN else "absent",
                "helper_command": record["command"] if record["phase"] in api_fallback.HELPER_IN else None,
                "costs": {}, "stop_failures": [], "answer": None, "reread_tokens": 100000, "bridge": True}

    for _ in range(14):
        loop.states = {"acct-1": state(usage(five), fetched_at=clock, earlier=usage(earlier), earlier_at=at)}
        record, effects = api_fallback.step(record, reading_of(loop.fallback_view(clock, auto=False)), clock)
        if record["writing"]:
            record = dict(record, writing=False)
        phases.append((five, record["phase"]))
        moved += [e["do"] for e in effects if e["do"] in ("helper_in", "helper_out")]
        earlier, at = five, clock
        clock += 90
        if record["phase"] not in ("on", "leaving"):
            five = min(five + 4.5, 96.0)
    assert all(phase == "off" for figure, phase in phases if figure < 90), phases
    assert phases[-1][1] == "on"
    assert moved == ["helper_in"], "one trip, and nothing brings it back before a reset"
    assert record["flips"] == 1


def test_a_model_full_everywhere_is_its_own_reason(tmp_path):
    full_fable = dict(usage(30), models=[{"name": "Fable", "used": 100, "resets_at": NOW + DAY}])
    loop = meters(tmp_path, [A], {"acct-1": state(full_fable)})
    loop.models = {"fable"}
    assert decided(loop.fallback_view(NOW, auto=False)) == {"blocked": "model_full", "room": False}


def test_the_view_names_the_active_account_and_each_accounts_key_in_list_order(tmp_path):
    """The last four and the cap come from the store; no key is ever read for the view."""
    stored = [dict(B, alias="bob", apiKeyLast4="abcd", apiKeyCapUsd=20.0), dict(A, alias="alice")]
    view = meters(tmp_path, stored, {"acct-1": state(usage(96))}).fallback_view(NOW, auto=False)
    assert (view["active"], view["keys"]) == ("acct-1", [
        {"id": "acct-2", "name": "bob", "last4": "abcd", "cap_usd": 20.0},
        {"id": "acct-1", "name": "alice", "last4": None, "cap_usd": 50.0}])
