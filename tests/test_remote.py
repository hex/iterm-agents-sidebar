# ABOUTME: Tests for remote.py: reading a session's Remote Control from its state file, owing it back after a panel
# ABOUTME: switch, the ask and result files in the session's folder, and what each card shows. Values come from the spec.
import json
import os

import pytest

import links
import remote

PID = 4242


def state_file(tmp_path, pid=PID, **fields):
    path = tmp_path / f"{pid}.json"
    path.write_text(json.dumps({"pid": pid, "sessionId": "s-1", "status": "idle", **fields}))
    return path


def test_a_string_bridge_reads_on_and_a_null_or_absent_one_off(tmp_path):
    assert remote.read_state(state_file(tmp_path, bridgeSessionId="session_01x"), PID, 5.0) == remote.Reading("on", 5.0)
    assert remote.read_state(state_file(tmp_path, bridgeSessionId=None), PID, 5.0) == remote.Reading("off", 5.0)
    assert remote.read_state(state_file(tmp_path), PID, 5.0) == remote.Reading("off", 5.0)


def test_a_missing_file_reads_unknown_with_no_fault(tmp_path):
    assert remote.read_state(tmp_path / "9.json", 9, 5.0) == remote.Reading("unknown", 5.0)


@pytest.mark.parametrize("text, fault", [
    ('{"pid": 4242, "bridgeSess', "not whole JSON"),
    ("[1, 2]", "not a JSON object"),
    ('{"pid": 77, "bridgeSessionId": "session_01x"}', "pid 77, not 4242"),
    ('{"pid": 4242, "bridgeSessionId": 3}', "bridgeSessionId 3"),
    ('{"pid": 4242, "bridgeSessionId": ""}', "bridgeSessionId ''"),
])
def test_a_file_claude_code_would_not_write_reads_unknown_and_names_the_fault(tmp_path, text, fault):
    (tmp_path / f"{PID}.json").write_text(text)
    assert remote.read_state(tmp_path / f"{PID}.json", PID, 5.0) == remote.Reading("unknown", 5.0, fault)


def test_a_symlinked_or_oversized_state_file_reads_unknown(tmp_path):
    real = state_file(tmp_path, pid=1, bridgeSessionId="session_01x")
    os.symlink(real, tmp_path / f"{PID}.json")
    assert remote.read_state(tmp_path / f"{PID}.json", PID, 5.0).state == "unknown"
    big = tmp_path / "8.json"
    big.write_text(json.dumps({"pid": 8, "pad": "x" * remote.STATE_MAX}))
    assert remote.read_state(big, 8, 5.0) == remote.Reading("unknown", 5.0, f"{big.stat().st_size} bytes, over {remote.STATE_MAX}")


def test_read_all_reads_each_panes_own_pid(tmp_path):
    state_file(tmp_path, pid=1, bridgeSessionId="session_01x")
    state_file(tmp_path, pid=2)
    assert remote.read_all(tmp_path, {"p1": 1, "p2": 2}, 5.0) == {"p1": remote.Reading("on", 5.0),
                                                                    "p2": remote.Reading("off", 5.0)}


ON, OFF = "on", "off"
END = {"agent": "a-id", "agent_pid": PID, "label": "alpha"}


def r(state, at):
    return {"p1": remote.Reading(state, at)}


def keeper_owing(tmp_path):
    """A keeper with remote control on in p1 before a switch at 100, read off at 101: the ask is filed."""
    k = remote.Keeper(tmp_path)
    assert k.step({"p1": END}, r(ON, 90.0), None, True, 90.0) == []
    assert k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0) == []
    return k


def ask(tmp_path, agent="a-id"):
    path = tmp_path / agent / remote.ASK
    return json.loads(path.read_text()) if path.exists() else None


def test_a_session_on_before_a_switch_and_off_after_it_is_asked_to_turn_it_back_on(tmp_path):
    k = keeper_owing(tmp_path)
    assert ask(tmp_path) == {"switch_at": 100.0, "expires": 401.0}
    assert oct((tmp_path / "a-id" / remote.ASK).stat().st_mode & 0o777) == "0o600"
    assert k.remote("p1") == "reconnecting"


def test_back_on_clears_the_debt_and_logs_one_line(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(ON, 106.0), 100.0, True, 106.0) == ["remote control back on “alpha” after the switch"]
    assert k.remote("p1") == "on"
    assert k.step({"p1": END}, r(ON, 107.0), 100.0, True, 107.0) == []


def test_a_session_off_before_the_switch_is_owed_nothing(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(OFF, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_a_session_read_on_after_the_switch_time_but_before_the_switch_showed_is_still_owed(tmp_path):
    """The switch is stamped with the time the account work began, seconds before it shows, and readings in between
    are later than that stamp."""
    k = remote.Keeper(tmp_path)
    for at in (98.0, 100.5, 102.5):
        k.step({"p1": END}, r(ON, at), None, True, at)
    k.step({"p1": END}, r(ON, 104.0), 100.0, True, 104.0)
    k.step({"p1": END}, r(OFF, 106.0), 100.0, True, 106.0)
    assert ask(tmp_path) == {"switch_at": 100.0, "expires": 406.0}


def test_a_switch_that_keeps_remote_control_owes_nothing_after_two_minutes(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(ON, 101.0), 100.0, True, 101.0)
    k.step({"p1": END}, r(ON, 221.0), 100.0, True, 221.0)
    k.step({"p1": END}, r(OFF, 230.0), 100.0, True, 230.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_with_the_setting_off_nothing_is_owed_and_an_untaken_ask_is_taken_back(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(OFF, 102.0), 100.0, False, 102.0) == []
    assert ask(tmp_path) is None and k.remote("p1") is None
    k.step({"p1": END}, r(OFF, 103.0), 100.0, True, 103.0)
    assert ask(tmp_path) is None


def test_another_agent_in_the_pane_forgets_the_debt(tmp_path):
    k = keeper_owing(tmp_path)
    k.step({"p1": {**END, "agent_pid": 5555}}, r(OFF, 102.0), 100.0, True, 102.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_a_clear_moves_an_untaken_ask_to_the_new_conversation(tmp_path):
    k = keeper_owing(tmp_path)
    k.step({"p1": {**END, "agent": "a2-id"}}, r(OFF, 102.0), 100.0, True, 102.0)
    assert ask(tmp_path) is None
    assert ask(tmp_path, "a2-id") == {"switch_at": 100.0, "expires": 401.0}


def result(tmp_path, outcome, switch_at=100.0, reason="", agent="a-id"):
    links.write_file(tmp_path, agent, remote.RESULT, {"switch_at": switch_at, "outcome": outcome, "reason": reason})


def test_a_failed_result_shows_the_line_and_logs_the_reason(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", reason="the session did not go idle")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == [
        "remote control did not come back on “alpha”: the session did not go idle"]
    assert k.remote("p1") == "lost"
    assert not (tmp_path / "a-id" / remote.RESULT).exists()


def test_already_on_clears_the_debt_without_a_line(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "already-on")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.remote("p1") is None


def test_a_result_for_another_switch_is_dropped_unread(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", switch_at=55.0, reason="old")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.remote("p1") == "reconnecting"
    assert not (tmp_path / "a-id" / remote.RESULT).exists()


def test_done_but_still_off_two_minutes_later_is_lost(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "done")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.step({"p1": END}, r(OFF, 230.0), 100.0, True, 230.0) == []
    assert k.step({"p1": END}, r(OFF, 231.0), 100.0, True, 231.0) == [
        "remote control did not come back on “alpha”: it ran /remote-control but did not connect"]


def test_an_ask_never_taken_is_lost_when_it_expires(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(OFF, 401.0), 100.0, True, 401.0) == []
    assert k.step({"p1": END}, r(OFF, 402.0), 100.0, True, 402.0) == [
        "remote control did not come back on “alpha”: the session never took it; is the agents-sidebar plugin loaded there?"]
    assert ask(tmp_path) is None


def test_an_ask_taken_and_never_answered_is_lost_after_the_grace(tmp_path):
    k = keeper_owing(tmp_path)
    os.rename(tmp_path / "a-id" / remote.ASK, tmp_path / "a-id" / remote.TAKEN)
    assert k.step({"p1": END}, r(OFF, 431.0), 100.0, True, 431.0) == []
    assert k.step({"p1": END}, r(OFF, 432.0), 100.0, True, 432.0) == [
        "remote control did not come back on “alpha”: the session took it and never answered"]


def lost_keeper(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", reason="x")
    k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0)
    return k


def test_the_line_clears_when_remote_control_comes_back_or_after_ten_minutes(tmp_path):
    k = lost_keeper(tmp_path)
    k.step({"p1": END}, r(ON, 120.0), 100.0, True, 120.0)
    assert k.remote("p1") == "on"
    k = lost_keeper(tmp_path)
    k.step({"p1": END}, r(OFF, 710.0), 100.0, True, 710.0)
    assert k.remote("p1") == "lost"
    k.step({"p1": END}, r(OFF, 711.0), 100.0, True, 711.0)
    assert k.remote("p1") is None


def test_the_line_clears_when_the_pane_goes(tmp_path):
    k = lost_keeper(tmp_path)
    k.step({}, {}, 100.0, True, 120.0)
    assert k.remote("p1") is None


def test_a_second_switch_before_the_drop_restarts_the_window(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(ON, 101.0), 100.0, True, 101.0)
    k.step({"p1": END}, r(ON, 201.0), 200.0, True, 201.0)
    k.step({"p1": END}, r(OFF, 300.0), 200.0, True, 300.0)
    assert ask(tmp_path) == {"switch_at": 200.0, "expires": 600.0}


def test_a_fault_is_logged_once_per_pid_and_fault(tmp_path):
    k = remote.Keeper(tmp_path)
    bad = {"p1": remote.Reading("unknown", 1.0, "not whole JSON")}
    line = f"remote control: {remote.SESSIONS_DIR}/{PID}.json: not whole JSON"
    assert k.step({"p1": END}, bad, None, True, 1.0) == [line]
    assert k.step({"p1": END}, bad, None, True, 2.0) == []


def test_a_links_folder_that_is_a_symlink_loses_the_debt_with_the_reason(tmp_path):
    k = remote.Keeper(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "a-id")
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    assert k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0) == [
        "remote control did not come back on “alpha”: its links folder: the links folder for a-id is not a plain directory"]
    assert k.remote("p1") == "lost"


def test_a_directory_where_the_ask_was_never_stops_the_step_and_is_logged_once(tmp_path):
    k = keeper_owing(tmp_path)
    (tmp_path / "a-id" / remote.ASK).unlink()
    (tmp_path / "a-id" / remote.ASK).mkdir()
    lines = k.step({"p1": END}, r(OFF, 102.0), 100.0, False, 102.0)
    assert lines == [f"remote control: cannot remove {tmp_path / 'a-id' / remote.ASK}: Operation not permitted"]
    assert k.remote("p1") is None and k.owed == {}
    assert k.step({"p1": END}, r(OFF, 103.0), 100.0, False, 103.0) == []


def test_a_directory_where_the_result_was_does_not_escape_a_reconnect(tmp_path):
    k = keeper_owing(tmp_path)
    (tmp_path / "a-id" / remote.RESULT).mkdir()
    assert k.step({"p1": END}, r(ON, 106.0), 100.0, True, 106.0) == [
        f"remote control: cannot remove {tmp_path / 'a-id' / remote.RESULT}: Operation not permitted",
        "remote control back on “alpha” after the switch"]
    assert k.remote("p1") == "on"


@pytest.mark.parametrize("on", [True, False])
def test_a_result_no_debt_will_read_is_removed_once_a_minute_old(tmp_path, on):
    k = remote.Keeper(tmp_path)
    result(tmp_path, "done")
    path = tmp_path / "a-id" / remote.RESULT
    os.utime(path, (1000.0, 1000.0))
    k.step({"p1": END}, r(ON, 1059.0), None, on, 1059.0)
    assert path.exists()
    k.step({"p1": END}, r(ON, 1061.0), None, on, 1061.0)
    assert not path.exists()

