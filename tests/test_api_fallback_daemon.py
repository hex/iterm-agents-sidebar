"""The daemon's side of the API fallback: the reading it builds, the effects it carries out, its route.

Every file it touches is the test's own: settings.json, the status folder (and
so the record), hook state and the panel's settings. The Keychain and the
models endpoint are the boundary, replaced here; the live script checks them.
Ways this can go wrong, and the test for each:
- a start with no record, or one that is not on, leaves a panel-owned helper in;
- a start while on and still full loses the helper, the spend baseline or a hold;
- a helper that took itself out while the daemon was down holds as another tool's removal would;
- the record is saved after settings.json changes, so a crash between loses the cap;
- a refused key reaches settings.json;
- a Not now, from the panel or from the notice, by any sender, is lost;
- the key comes back in a reply;
- remote sessions or other agents count toward the spend or the re-read;
- a refused key reaches settings.json when another account's key would do;
- a key or cap op names an account that is not stored, or none;
- the switch turns on with no key on any account.
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accounts  # noqa: E402
import api_fallback  # noqa: E402
import sidebar  # noqa: E402
import statusline  # noqa: E402

NOW = 1_000_000.0
KEY = "sk-ant-test-" + "c3d4" * 20 + "wxyz"
#: settings.json as the world starts: the bridge installed, and one key of the user's own.
AS_READ = {"model": "opus", "statusLine": {"type": "command", "command": sidebar.BRIDGE}}


#: The stored accounts as the meters' view carries them: alice with a key, active, and bob without one.
ALICE = {"id": "acct-1", "name": "alice", "last4": "wxyz", "cap_usd": 50.0}
BOB = {"id": "acct-2", "name": "bob", "last4": None, "cap_usd": 50.0}


class Meters:
    def __init__(self, blocked="full", room=False, keys=None, active="acct-1"):
        self.view = {"blocked": blocked, "room": room, "active": active, "keys": keys or [ALICE, BOB]}
        self.store_path = None

    def fallback_view(self, now, auto):
        return dict(self.view)


@pytest.fixture
def world(tmp_path, monkeypatch):
    settings = tmp_path / "claude-settings.json"
    settings.write_text(json.dumps(AS_READ, indent=2) + "\n")
    monkeypatch.setattr(sidebar, "CLAUDE_SETTINGS", str(settings))
    monkeypatch.setattr(sidebar, "SETTINGS_FILE", tmp_path / "panel-settings.json")
    monkeypatch.setattr(sidebar, "NOTIFIER_APP", tmp_path / "no-notifier.app")
    sidebar.save_settings({"api_fallback": True})
    keys = {"stored": {"acct-1": KEY}, "validated": [], "verdicts": {}}
    monkeypatch.setattr(api_fallback, "read_key", lambda account_id: keys["stored"].get(account_id))
    monkeypatch.setattr(api_fallback, "validate_key",
                        lambda key, **_: keys["validated"].append(key) or keys["verdicts"].get(key, keys.get("verdict")))
    monkeypatch.setattr(sidebar.time, "time", lambda: world_clock["now"])
    world_clock = {"now": NOW}
    return {"settings": settings, "record": Path(sidebar.STATUS_DIR) / "api-fallback.json",
            "marker": Path(sidebar.STATUS_DIR) / "api-fallback-orphaned", "keys": keys, "clock": world_clock}


def bridge_with(world, record=None, meters=None):
    if record is not None:
        api_fallback.save(world["record"], record)
    bridge = sidebar.Bridge(None, None, meters or Meters())
    return bridge


def settings_of(world):
    return json.loads(world["settings"].read_text())


#: This checkout's command for alice's key, and for bob's.
ALICES = sidebar.own_helper_command("acct-1")
BOBS = sidebar.own_helper_command("acct-2")


def with_helper(world, command=ALICES):
    statusline.set_api_key_helper(world["settings"], command, [command])


def on_record(**changes):
    return dict(api_fallback.blank(), phase="on", since=NOW - 600, last_cost={"conv-1": 3.0}, spend={"acct-1": 1.0},
                flips=1, key_account="acct-1", command=ALICES, **changes)


def stored(world):
    return api_fallback.load(world["record"])[0]


def test_a_start_with_no_record_takes_a_stray_helper_out(world):
    with_helper(world)
    asyncio.run(bridge_with(world, meters=Meters(blocked=None)).step_fallback())
    assert settings_of(world) == AS_READ
    assert stored(world)["phase"] == "off"


def test_a_start_while_on_and_still_full_keeps_the_helper_the_baseline_and_the_count(world):
    with_helper(world)
    before = world["settings"].read_bytes()
    asyncio.run(bridge_with(world, on_record()).step_fallback())
    assert world["settings"].read_bytes() == before
    record = stored(world)
    assert (record["phase"], record["spend"], record["flips"]) == ("on", {"acct-1": 1.0}, 1)


def test_a_start_keeps_a_hold(world):
    cap = {"reason": "cap", "at": NOW - 60, "why": "cap reached"}
    held = dict(api_fallback.blank(), hold=cap, key_holds={"acct-1": cap}, last_cost={"conv-1": 55.0}, spend={"acct-1": 55.0})
    asyncio.run(bridge_with(world, held).step_fallback())
    assert (stored(world)["hold"]["reason"], stored(world)["key_holds"]) == ("cap", {"acct-1": cap})
    assert "apiKeyHelper" not in settings_of(world)


SAME_NAME = "/opt/acme/api-key-helper.sh"


@pytest.mark.parametrize("enabled,record", [(False, None), (True, None), (True, on_record())],
                         ids=["feature off", "feature on", "fallback on"])
def test_a_foreign_helper_of_the_same_file_name_survives_ten_ticks(world, enabled, record):
    sidebar.save_settings({"api_fallback": enabled})
    world["settings"].write_text(json.dumps({"model": "opus", "apiKeyHelper": SAME_NAME}, indent=2) + "\n")
    before = world["settings"].read_bytes()
    bridge = bridge_with(world, record)
    for _ in range(10):
        asyncio.run(bridge.step_fallback())
    assert world["settings"].read_bytes() == before


def test_the_command_the_record_says_was_written_is_ours(world):
    """A checkout that moved leaves its old command in settings.json: the record says it is the panel's."""
    moved = "/elsewhere/agents-sidebar/api-key-helper.sh"
    world["settings"].write_text(json.dumps({"model": "opus", "apiKeyHelper": moved}, indent=2) + "\n")
    held = dict(api_fallback.blank(), command=moved, hold={"reason": "not_now", "at": NOW, "why": "x"})
    asyncio.run(bridge_with(world, held, Meters(blocked=None)).step_fallback())
    assert "apiKeyHelper" not in settings_of(world)


def test_another_tools_command_never_reaches_the_hold_the_snapshot_or_the_log(world, monkeypatch):
    command = "echo sk-ant-test-inline-not-a-real-key"
    world["settings"].write_text(json.dumps(dict(AS_READ, apiKeyHelper=command), indent=2) + "\n")
    entered_late = dict(api_fallback.blank(), phase="entering", deadline=NOW - 1)
    real = statusline.api_key_helper
    # The foreign helper lands between the reading and the write: the writer's own refusal is what is said.
    monkeypatch.setattr(statusline, "api_key_helper", lambda path, ours: ("absent", None))
    bridge = bridge_with(world, entered_late)
    asyncio.run(bridge.step_fallback())
    monkeypatch.setattr(statusline, "api_key_helper", real)
    refused_by_writer = stored(world)["hold"]["why"]
    assert stored(world)["key_holds"] == {}, "another tool's helper is no verdict on alice's key"
    bridge = bridge_with(world, api_fallback.blank())
    asyncio.run(bridge.step_fallback())
    shown = json.dumps(sidebar.fallback_snapshot(stored(world), sidebar.load_settings(), None, True, [ALICE, BOB]))
    log = (Path(sidebar.STATUS_DIR) / "daemon.log").read_text()
    assert "another tool's apiKeyHelper" in refused_by_writer
    for said in (refused_by_writer, shown, log, world["record"].read_text()):
        assert "sk-ant-test-inline" not in said
    assert "another tool's apiKeyHelper" in stored(world)["hold"]["why"]


def test_a_helper_another_tool_took_out_holds(world):
    asyncio.run(bridge_with(world, on_record()).step_fallback())
    record = stored(world)
    assert (record["phase"], record["hold"]["reason"]) == ("off", "helper_gone")


def test_a_helper_that_took_itself_out_ends_it_with_no_hold_and_the_marker_goes(world):
    world["marker"].write_text("")
    asyncio.run(bridge_with(world, on_record(), Meters(blocked=None)).step_fallback())
    record = stored(world)
    assert (record["phase"], record["hold"], record["flips"]) == ("off", None, 2)
    assert not world["marker"].exists()


def test_a_marker_from_a_helper_that_could_not_read_the_key_ends_it_the_same_way(world):
    """The helper leaves one marker for both ways it steps aside, so the daemon needs no way to tell them apart."""
    world["marker"].write_text("")
    asyncio.run(bridge_with(world, on_record(), Meters(blocked=None)).step_fallback())
    record = stored(world)
    assert (record["phase"], record["hold"]) == ("off", None)
    assert record["last_flip"]["why"] == "the helper took itself out"


def test_after_the_helper_took_itself_out_entry_comes_again_through_its_notice(world):
    world["marker"].write_text("")
    asyncio.run(bridge_with(world, on_record()).step_fallback())
    assert stored(world)["phase"] == "entering"
    assert "apiKeyHelper" not in settings_of(world)


def test_a_marker_left_while_the_helper_is_still_in_changes_nothing_and_goes(world):
    with_helper(world)
    world["marker"].write_text("")
    asyncio.run(bridge_with(world, on_record()).step_fallback())
    assert stored(world)["phase"] == "on"
    assert not world["marker"].exists()


def entering(world, meters=None):
    record = dict(api_fallback.blank(), phase="entering", deadline=NOW - 1)
    return bridge_with(world, record, meters)


def test_entry_validates_the_key_and_saves_the_record_before_settings_change(world, monkeypatch):
    seen_at_write = []
    real = statusline.set_api_key_helper

    def watching(path, command, ours):
        seen_at_write.append(api_fallback.load(world["record"])[0]["phase"])
        real(path, command, ours)
    monkeypatch.setattr(statusline, "set_api_key_helper", watching)
    asyncio.run(entering(world).step_fallback())
    assert settings_of(world) == dict(AS_READ, apiKeyHelper=ALICES)
    assert seen_at_write == ["on"]
    assert world["keys"]["validated"] == [KEY]
    assert stored(world)["phase"] == "on"


def test_a_start_that_finds_the_writing_mark_and_no_helper_goes_off_with_no_hold(world):
    asyncio.run(bridge_with(world, on_record(writing=True), Meters(blocked=None)).step_fallback())
    record = stored(world)
    assert (record["phase"], record["hold"], record["writing"]) == ("off", None, False)
    assert "apiKeyHelper" not in settings_of(world)


def test_the_writing_mark_is_saved_before_the_write_and_cleared_after(world, monkeypatch):
    marks_at_write = []
    real = statusline.set_api_key_helper

    def watching(path, command, ours):
        marks_at_write.append(api_fallback.load(world["record"])[0]["writing"])
        real(path, command, ours)
    monkeypatch.setattr(statusline, "set_api_key_helper", watching)
    asyncio.run(entering(world).step_fallback())
    assert marks_at_write == [True]
    assert (stored(world)["phase"], stored(world)["writing"]) == ("on", False)


def test_the_record_is_saved_only_when_it_changed(world, monkeypatch):
    bridge = bridge_with(world, on_record())
    with_helper(world)
    world["record"].unlink()
    saves = []
    real = api_fallback.save
    monkeypatch.setattr(api_fallback, "save", lambda path, record: saves.append(record) or real(path, record))
    asyncio.run(bridge.step_fallback())
    assert saves == [] and not world["record"].exists(), "a tick that moved nothing writes nothing"
    bridge.meters = Meters(blocked=None, room=True)
    asyncio.run(bridge.step_fallback())
    assert [record["phase"] for record in saves] == ["leaving"]


def test_a_refused_key_never_reaches_settings(world):
    world["keys"]["verdict"] = api_fallback.KeyProblem("refused", "the key was refused (401)")
    before = world["settings"].read_bytes()
    asyncio.run(entering(world).step_fallback())
    assert world["settings"].read_bytes() == before
    record = stored(world)
    assert (record["phase"], record["hold"]["reason"], record["hold"]["why"], record["flips"]) == (
        "off", "refused", "the key was refused (401)", 0)


@pytest.fixture
def posted_notices(world, tmp_path, monkeypatch):
    """A stand-in notifier that records each post, so a test counts the notices a user would see."""
    app = tmp_path / "Agents.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    posts = tmp_path / "posts"
    exe = app / "Contents" / "MacOS" / "agents-notifier"
    exe.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> "{posts}"\n')
    exe.chmod(0o755)
    monkeypatch.setattr(sidebar, "NOTIFIER_APP", app)
    sidebar.save_settings({"notify": True, "api_fallback": True})
    return lambda: posts.read_text().splitlines() if posts.exists() else []


def test_a_key_that_cannot_be_checked_holds_nothing_retries_each_tick_and_says_so_once(world, posted_notices):
    world["keys"]["verdict"] = api_fallback.KeyProblem("unavailable", "the API answered 503")
    before = world["settings"].read_bytes()
    bridge = entering(world)
    log = Path(sidebar.STATUS_DIR) / "daemon.log"

    async def ticks():
        for _ in range(4):
            await bridge.step_fallback()
            world["clock"]["now"] += 30
        for _ in range(200):
            if posted_notices():
                break
            await asyncio.sleep(0.01)
    asyncio.run(ticks())
    record = stored(world)
    assert (record["phase"], record["hold"], record["retrying"]) == ("off", None, "the API answered 503")
    assert world["settings"].read_bytes() == before
    assert len(world["keys"]["validated"]) == 4, "one try on each tick"
    assert len([post for post in posted_notices() if "the API answered 503" in post]) == 1
    assert log.read_text().count("the API answered 503") == 1
    world["keys"]["verdict"] = None
    asyncio.run(bridge.step_fallback())
    record = stored(world)
    assert (record["phase"], record["retrying"], record["writing"], record["flips"]) == ("on", None, False, 1)
    assert settings_of(world)["apiKeyHelper"] == ALICES


def test_entry_is_refused_with_its_reason_while_the_bridge_is_not_installed(world):
    world["settings"].write_text(json.dumps({"model": "opus"}, indent=2) + "\n")
    before = world["settings"].read_bytes()
    asyncio.run(bridge_with(world, api_fallback.blank()).step_fallback())
    assert stored(world)["hold"]["reason"] == "no_bridge"
    assert stored(world)["hold"]["why"] == "the spend cap needs the statusline bridge, which is not installed"
    assert world["settings"].read_bytes() == before


def test_a_bridge_gone_while_on_takes_the_helper_out_and_holds(world):
    world["settings"].write_text(json.dumps({"model": "opus", "apiKeyHelper": ALICES}, indent=2) + "\n")
    asyncio.run(bridge_with(world, on_record()).step_fallback())
    assert stored(world)["hold"]["reason"] == "no_bridge"
    assert settings_of(world) == {"model": "opus"}


def test_the_switch_cannot_turn_on_while_the_bridge_is_not_installed(world):
    installed = {"state": False}
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None,
                             settings_path=world["settings"].parent / "route-settings.json",
                             bridge_fn=lambda: installed["state"], keys_fn=lambda: True)
    _, _, body = server.handle("POST", "/settings?token=t", json.dumps({"api_fallback": True, "volume": 0.25}).encode())
    assert (json.loads(body)["api_fallback"], json.loads(body)["volume"]) == (False, 0.25), "the rest of the change still lands"
    installed["state"] = True
    _, _, body = server.handle("POST", "/settings?token=t", json.dumps({"api_fallback": True}).encode())
    assert json.loads(body)["api_fallback"] is True
    installed["state"] = False
    _, _, body = server.handle("POST", "/settings?token=t", json.dumps({"api_fallback": False}).encode())
    assert json.loads(body)["api_fallback"] is False, "turning it off never needs the bridge"


def test_a_key_the_store_names_and_the_keychain_lacks_refuses_entry(world):
    world["keys"]["stored"] = {}
    asyncio.run(entering(world).step_fallback())
    assert stored(world)["hold"]["why"] == "no API key is stored for acct-1"
    assert world["keys"]["validated"] == []


def test_a_not_now_from_the_panel_holds(world):
    record = dict(api_fallback.blank(), phase="entering", deadline=NOW + 50)
    bridge = bridge_with(world, record)

    async def go():
        bridge.loop = asyncio.get_running_loop()
        await asyncio.to_thread(bridge.fallback_op, "not_now", {})
        await asyncio.sleep(0.05)
        await bridge.fallback_idle()
    asyncio.run(go())
    assert stored(world)["hold"]["reason"] == "not_now"


class Poster:
    """A notice sender as the daemon reads it: lines, then its exit."""
    def __init__(self, lines):
        self.lines = [line.encode() + b"\n" for line in lines] + [b""]
        self.stdout = self
        self.returncode = None

    async def readline(self):
        return self.lines.pop(0)

    async def wait(self):
        self.returncode = 0


def test_a_not_now_from_the_notice_reaches_the_fallback_through_any_sender(world):
    record = dict(api_fallback.blank(), phase="entering", deadline=NOW + 50)
    bridge = bridge_with(world, record)

    async def go():
        bridge.loop = asyncio.get_running_loop()
        await bridge.answer("some-session", Poster(['{"action": "not_now", "id": "api-fallback"}']))
        await asyncio.sleep(0.05)
        await bridge.fallback_idle()
    asyncio.run(go())
    assert stored(world)["hold"]["reason"] == "not_now"


def test_a_route_that_queues_a_change_waits_for_the_inputs_lock(world, monkeypatch):
    """Routes run on worker threads and the step drains the same inputs on the loop."""
    bridge = bridge_with(world, on_record())
    bridge.loop = asyncio.new_event_loop()
    try:
        with bridge.fallback_inputs:
            worker = threading.Thread(target=bridge.fallback_op, args=("not_now", {}))
            worker.start()
            worker.join(0.1)
            assert worker.is_alive() and bridge.fallback_answer is None, "the answer waits for the lock"
        worker.join(2)
        assert not worker.is_alive()
        assert bridge.fallback_answer == "not_now"
    finally:
        bridge.loop.close()


def test_the_record_that_cannot_be_read_is_said_in_the_log(world):
    world["record"].write_text("{ not json")
    sidebar.Bridge(None, None, Meters())
    log = (Path(sidebar.STATUS_DIR) / "daemon.log").read_text()
    assert "api-fallback.json is not a fallback record" in log


def test_the_route_takes_four_ops_and_never_returns_the_key(world):
    calls = []
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None,
                             api_fallback_fn=lambda op, request: calls.append((op, request)) or {"last4": "wxyz"})

    def post(body):
        status, _, reply = server.handle("POST", "/api-fallback?token=t", json.dumps(body).encode())
        return status, json.loads(reply)
    assert post({"op": "save_key", "account_id": "acct-1", "key": KEY}) == (200, {"ok": True, "last4": "wxyz"})
    assert post({"op": "forget_key", "account_id": "acct-1"})[0] == 200
    assert post({"op": "set_cap", "account_id": "acct-1", "cap_usd": 12.5})[0] == 200
    assert post({"op": "not_now"})[0] == 200
    assert [op for op, _ in calls] == ["save_key", "forget_key", "set_cap", "not_now"]
    assert post({"op": "enter"})[0] == 400
    assert post({"op": "save_key", "account_id": "acct-1"})[0] == 400
    assert server.handle("POST", "/api-fallback?token=x", b'{"op": "not_now"}')[0] == 403


@pytest.mark.parametrize("account_id", [None, "", "acct-1; rm -rf ~", "$(id)", 7, "api-key"])
def test_a_key_or_cap_op_needs_an_account_id_in_the_stores_format(world, account_id):
    calls = []
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None,
                             api_fallback_fn=lambda op, request: calls.append(op) or {})
    for body in ({"op": "save_key", "key": KEY}, {"op": "forget_key"}, {"op": "set_cap", "cap_usd": 5}):
        status, _, reply = server.handle("POST", "/api-fallback?token=t",
                                         json.dumps(dict(body, account_id=account_id)).encode())
        assert (status, json.loads(reply)) == (400, {"error": f"{body['op']} needs an account_id"})
    assert calls == []


@pytest.mark.parametrize("cap", [0, -5, "50", None, True])
def test_a_cap_is_a_positive_number(world, cap):
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None, api_fallback_fn=lambda op, request: {})
    status, _, reply = server.handle("POST", "/api-fallback?token=t",
                                     json.dumps({"op": "set_cap", "account_id": "acct-1", "cap_usd": cap}).encode())
    assert (status, json.loads(reply)) == (400, {"error": "set_cap needs a positive cap_usd"})


def test_a_refused_key_is_said_without_the_key(world):
    def refuse(op, request):
        raise ValueError("the key was refused (401)")
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None, api_fallback_fn=refuse)
    status, _, body = server.handle("POST", "/api-fallback?token=t",
                                    json.dumps({"op": "save_key", "account_id": "acct-1", "key": KEY}).encode())
    assert (status, json.loads(body)) == (409, {"error": "the key was refused (401)"})


@pytest.fixture
def store(world, tmp_path, monkeypatch):
    """An account store of the test's own holding alice and bob, and a Keychain that is a dict."""
    path = tmp_path / "config" / "accounts.json"
    accounts.save_store(str(path), [{"id": "acct-1", "accountUuid": "uuid-a"}, {"id": "acct-2", "accountUuid": "uuid-b"}])
    items = {}
    monkeypatch.setattr(accounts, "write_secret", lambda service, item, value: items.__setitem__((service, item), value))
    monkeypatch.setattr(accounts, "delete_secret", lambda service, item: items.pop((service, item), None))
    return {"path": path, "items": items}


def route_bridge(world, store, record=None, meters=None):
    bridge = bridge_with(world, record, meters or Meters(blocked=None))
    bridge.meters.store_path = str(store["path"])
    return bridge


def run_op(bridge, op, request):
    async def go():
        bridge.loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(bridge.fallback_op, op, request)
        await asyncio.sleep(0.05)
        await bridge.fallback_idle()
        return result
    return asyncio.run(go())


def test_saving_a_key_checks_it_stores_it_for_that_account_and_lifts_its_refusal(world, store):
    refused = dict(api_fallback.refused(api_fallback.blank(), "the key was refused (401)", NOW - 10),
                   key_holds={"acct-2": {"reason": "refused", "at": NOW - 10, "why": "the key was refused (401)"}})
    bridge = route_bridge(world, store, refused)
    assert run_op(bridge, "save_key", {"account_id": "acct-2", "key": KEY}) == {"last4": "wxyz"}
    assert store["items"] == {(api_fallback.KEY_SERVICE, "api-key:acct-2"): KEY}
    assert [a.get("apiKeyLast4") for a in accounts.load_store(str(store["path"]))] == [None, "wxyz"]
    assert (stored(world)["hold"], stored(world)["key_holds"]) == (None, {})
    assert KEY not in (Path(sidebar.STATUS_DIR) / "daemon.log").read_text()


def test_a_key_for_an_account_that_is_not_stored_is_refused_before_anything_is_kept(world, store):
    with pytest.raises(ValueError, match="no stored account acct-9"):
        route_bridge(world, store).fallback_op("save_key", {"account_id": "acct-9", "key": KEY})
    assert (store["items"], world["keys"]["validated"]) == ({}, [])


def test_forgetting_and_a_cap_change_the_store_and_the_keychain(world, store):
    bridge = route_bridge(world, store)
    run_op(bridge, "save_key", {"account_id": "acct-1", "key": KEY})
    run_op(bridge, "set_cap", {"account_id": "acct-1", "cap_usd": 12.5})
    assert accounts.load_store(str(store["path"]))[0] == {"id": "acct-1", "accountUuid": "uuid-a",
                                                          "apiKeyLast4": "wxyz", "apiKeyCapUsd": 12.5}
    run_op(bridge, "forget_key", {"account_id": "acct-1"})
    assert accounts.load_store(str(store["path"]))[0] == {"id": "acct-1", "accountUuid": "uuid-a", "apiKeyCapUsd": 12.5}
    assert store["items"] == {}


def test_a_key_the_api_refuses_is_never_stored(world, store):
    world["keys"]["verdict"] = api_fallback.KeyProblem("refused", "the key was refused (401)")
    with pytest.raises(ValueError, match="refused"):
        route_bridge(world, store).fallback_op("save_key", {"account_id": "acct-1", "key": KEY})
    assert store["items"] == {}
    assert "apiKeyLast4" not in accounts.load_store(str(store["path"]))[0]


def test_the_switch_cannot_turn_on_with_no_key_on_any_account(world):
    keyed = {"state": False}
    server = sidebar.Sidebar("t", Path(__file__), lambda: {}, lambda *a: None,
                             settings_path=world["settings"].parent / "route-settings.json",
                             bridge_fn=lambda: True, keys_fn=lambda: keyed["state"])
    _, _, body = server.handle("POST", "/settings?token=t", json.dumps({"api_fallback": True}).encode())
    assert json.loads(body)["api_fallback"] is False
    keyed["state"] = True
    _, _, body = server.handle("POST", "/settings?token=t", json.dumps({"api_fallback": True}).encode())
    assert json.loads(body)["api_fallback"] is True


def test_any_api_key_reads_the_store(tmp_path):
    path = tmp_path / "accounts.json"
    assert sidebar.any_api_key(str(path)) is False, "no store"
    accounts.save_store(str(path), [{"id": "acct-1", "accountUuid": "uuid-a"}])
    assert sidebar.any_api_key(str(path)) is False
    accounts.save_store(str(path), [{"id": "acct-1", "accountUuid": "uuid-a"},
                                    {"id": "acct-2", "accountUuid": "uuid-b", "apiKeyLast4": "wxyz"}])
    assert sidebar.any_api_key(str(path)) is True


TWO_KEYS = [ALICE, dict(BOB, last4="abcd")]
BOBS_KEY = "sk-ant-test-" + "e5f6" * 20 + "abcd"


def test_a_refused_key_at_entry_is_skipped_and_the_next_accounts_key_reaches_settings(world):
    world["keys"]["stored"] = {"acct-1": KEY, "acct-2": BOBS_KEY}
    world["keys"]["verdicts"] = {KEY: api_fallback.KeyProblem("refused", "the key was refused (401)")}
    asyncio.run(entering(world, Meters(keys=TWO_KEYS)).step_fallback())
    assert world["keys"]["validated"] == [KEY, BOBS_KEY]
    assert settings_of(world)["apiKeyHelper"] == BOBS
    record = stored(world)
    assert (record["phase"], record["key_account"], record["writing"]) == ("on", "acct-2", False)
    assert record["key_holds"]["acct-1"]["reason"] == "refused"


def test_a_key_at_its_cap_moves_the_helper_to_the_next_accounts_key(world, posted_notices):
    world["keys"]["stored"] = {"acct-1": KEY, "acct-2": BOBS_KEY}
    with_helper(world)
    bridge = bridge_with(world, on_record(), Meters(keys=TWO_KEYS))
    bridge.rows = [{"provider": "claude", "conversation": "conv-1", "details": {"cost": 53.0}}]

    async def tick():
        await bridge.step_fallback()
        for _ in range(200):
            if posted_notices():
                break
            await asyncio.sleep(0.01)
    asyncio.run(tick())
    assert settings_of(world)["apiKeyHelper"] == BOBS
    record = stored(world)
    assert (record["phase"], record["key_account"], record["spend"]) == ("on", "acct-2", {"acct-1": 51.0})
    assert record["key_holds"]["acct-1"]["reason"] == "cap"
    assert [post for post in posted_notices() if "bob's API key" in post], "a notice after the move names the key"


def test_the_snapshot_never_carries_a_key(world):
    record = on_record()
    shown = sidebar.fallback_snapshot(record, sidebar.load_settings(), 42000, True, [ALICE, BOB])
    assert shown == {"enabled": True, "phase": "on", "deadline": None, "since": NOW - 600, "spent_usd": 1.0,
                     "hold": None, "key_account": "acct-1", "key_name": "alice",
                     "keys": [{"id": "acct-1", "name": "alice", "last4": "wxyz", "cap_usd": 50.0, "spent_usd": 1.0,
                               "hold": None},
                              {"id": "acct-2", "name": "bob", "last4": None, "cap_usd": 50.0, "spent_usd": 0,
                               "hold": None}],
                     "reread_tokens": 42000, "last_flip": None, "retrying": None, "bridge": True}


ROWS = [
    {"provider": "claude", "conversation": "conv-1", "agent_state": "working", "details": {"cost": 1.25, "recache": 40000}},
    {"provider": "claude", "conversation": "conv-2", "agent_state": "idle", "idle_since": NOW - 100,
     "details": {"cost": 0.5, "recache": 2000}},
    {"provider": "claude", "conversation": "conv-3", "agent_state": "idle", "idle_since": NOW - 900,
     "details": {"cost": 7.0, "recache": 90000}},
    {"provider": "claude", "conversation": "conv-4", "agent_state": "working", "host": "bob-mini",
     "details": {"cost": 9.0, "recache": 50000}},
    {"provider": "openai", "conversation": "conv-5", "agent_state": "working", "details": {"cost": 3.0, "recache": 1}},
    {"provider": "claude", "conversation": None, "agent_state": "working", "details": {"cost": 4.0}},
]


def test_spend_counts_this_machines_claude_sessions_by_conversation():
    assert sidebar.fallback_costs(ROWS) == {"conv-1": 1.25, "conv-2": 0.5, "conv-3": 7.0}


def test_the_reread_counts_sessions_active_in_the_last_five_minutes():
    assert sidebar.reread_tokens(ROWS, NOW) == 42000
    assert sidebar.reread_tokens([ROWS[2]], NOW) is None


def dead_pid():
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


def test_stop_failures_are_taken_once_each_with_the_session_that_failed(tmp_path):
    (tmp_path / "sess-a").write_text(json.dumps({"pid": 4242, "stop_failure": {"error": "billing_error", "at": NOW - 5}}))
    (tmp_path / "sess-b").write_text(json.dumps({"pid": 4343, "stop_failure": {"error": "rate_limit", "at": NOW - 50}}))
    (tmp_path / "sess-c").write_text(json.dumps({"agents": {}}))
    (tmp_path / "sess-d").write_text(json.dumps({"stop_failure": {"error": "billing_error", "at": NOW - 4}}))
    (tmp_path / "sess-a.lock").write_text("")
    assert sidebar.stop_failures_since(str(tmp_path), NOW - 30) == (
        [{"error": "billing_error", "pid": 4242, "at": NOW - 5}, {"error": "billing_error", "pid": None, "at": NOW - 4}],
        NOW - 4)
    assert sidebar.stop_failures_since(str(tmp_path), NOW - 4) == ([], NOW - 4)


def test_the_key_fetches_are_read_per_live_process_and_a_dead_ones_note_goes(tmp_path):
    live, dead = os.getpid(), dead_pid()
    (tmp_path / str(live)).write_text(f"{int(NOW)} acct-1\n{int(NOW) + 60} acct-2\nnot a line\n")
    (tmp_path / str(dead)).write_text(f"{int(NOW)} acct-1\n")
    (tmp_path / "stray").write_text(f"{int(NOW)} acct-1\n")
    assert sidebar.key_fetches(str(tmp_path)) == {live: [(NOW, "acct-1"), (NOW + 60, "acct-2")]}
    assert not (tmp_path / str(dead)).exists()
    assert sidebar.key_fetches(str(tmp_path / "none")) == {}


def test_the_entry_notice_offers_not_now_and_says_the_reread(tmp_path):
    argv = sidebar.fallback_notice_argv(tmp_path / "Agents.app", {"do": "notice", "which": "entry", "tokens": 42000})
    assert argv[1:] == ["post", "--id", "api-fallback", "--title", "Sessions move to API credits",
                        "--body", "Every account is full. In 60 s, unless Not now; they re-read about 42k tokens.",
                        "--button", "not_now=Not now"]
    refused = sidebar.fallback_notice_argv(tmp_path / "Agents.app", {"do": "notice", "which": "refused", "why": "bad"})
    assert "--button" not in refused


def fail_in(world, name, pid, at, error="billing_error"):
    """A StopFailure the hook filed for the Claude Code process `pid`."""
    Path(sidebar.HOOK_STATE_DIR).mkdir(parents=True, exist_ok=True)
    (Path(sidebar.HOOK_STATE_DIR) / name).write_text(json.dumps({"pid": pid, "stop_failure": {"error": error, "at": at}}))


def took(pid, *fetches):
    """The helper's notes of the keys the Claude Code process `pid` took: (at, account id) pairs."""
    notes = Path(sidebar.STATUS_DIR) / "api-key-fetches"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / str(pid)).write_text("".join(f"{int(at)} {account}\n" for at, account in fetches))


def test_a_failure_in_a_session_that_never_took_the_key_leaves_the_key_in_use(world):
    """2026-11-10: sessions still on the subscription failed seconds after the helper went in, and
    each key in turn was held for it."""
    with_helper(world)
    bridge = bridge_with(world, on_record())
    bridge.failures_after = NOW - 60
    fail_in(world, "sess-a", os.getpid(), NOW - 10)
    asyncio.run(bridge.step_fallback())
    assert (stored(world)["phase"], stored(world)["key_account"], stored(world)["key_holds"]) == ("on", "acct-1", {})


def test_a_failure_in_a_session_on_the_key_in_use_ends_that_key(world):
    world["keys"]["stored"]["acct-2"] = "sk-ant-test-bobs-key"
    with_helper(world)
    bridge = bridge_with(world, on_record())
    bridge.failures_after = NOW - 60
    took(os.getpid(), (NOW - 30, "acct-1"))
    fail_in(world, "sess-a", os.getpid(), NOW - 10)
    asyncio.run(bridge.step_fallback())
    assert stored(world)["key_holds"]["acct-1"]["reason"] == "billing_error"
