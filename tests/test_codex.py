"""Codex limits read from its session logs.

Event shapes are copied from real rollout files; the expected figures were
checked against `codex /status` on the same session (27% used, i.e. "73%
left", resetting 21:41 on 19 Sep, which is 1789843280).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import codex
from codex import limits_from_lines, read_limits, read_session, session_from_lines

WEEKLY_ONLY = {"limit_id": "codex", "primary": {"used_percent": 27.0, "window_minutes": 10080,
                                                "resets_at": 1789843280},
               "secondary": None, "plan_type": "plus"}
FIVE_HOUR_AND_WEEKLY = {"limit_id": "codex",
                        "primary": {"used_percent": 12.0, "window_minutes": 300, "resets_at": 1789500000},
                        "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 1789843280}}
NOW = 1789480000


def _token_count(rate_limits, ts="2026-09-15T12:03:53.951Z"):
    return json.dumps({"timestamp": ts, "type": "event_msg",
                       "payload": {"type": "token_count", "info": None, "rate_limits": rate_limits}})


def test_a_weekly_only_plan_reads_as_one_weekly_window():
    [window] = limits_from_lines([_token_count(WEEKLY_ONLY)], now=NOW)["windows"]
    assert {k: window[k] for k in ("label", "used", "resets_at", "minutes")} == {
        "label": "Weekly", "used": 27.0, "resets_at": 1789843280, "minutes": 10080}


def test_a_weekly_window_carries_its_even_spend_mark_as_of_the_reading():
    # Worked out at the event's own time, 2026-09-15T12:03:53Z = 1789473833,
    # not at the time of the rebuild: a mark that crept with the clock would
    # change the snapshot every tick. 369447 s left of 604800 means 235353 s
    # gone: an even spend is at 38.91%.
    pace = limits_from_lines([_token_count(WEEKLY_ONLY)], now=NOW)["windows"][0]["pace"]
    assert round(pace["expected"], 2) == 38.91 and pace["ahead"] is False
    later = limits_from_lines([_token_count(WEEKLY_ONLY)], now=NOW + 3600)["windows"][0]["pace"]
    assert later == pace


def test_a_five_hour_window_has_no_even_spend_mark():
    assert limits_from_lines([_token_count(FIVE_HOUR_AND_WEEKLY)], now=NOW)["windows"][0]["pace"] is None


def test_both_windows_come_out_shortest_first():
    windows = limits_from_lines([_token_count(FIVE_HOUR_AND_WEEKLY)], now=NOW)["windows"]
    assert [(w["label"], w["used"]) for w in windows] == [("5-hour", 12.0), ("Weekly", 40.0)]


def test_the_last_reading_in_the_log_wins():
    lines = [_token_count(FIVE_HOUR_AND_WEEKLY), _token_count(WEEKLY_ONLY)]
    assert [w["used"] for w in limits_from_lines(lines, now=NOW)["windows"]] == [27.0]


def test_lines_without_a_reading_or_torn_ones_are_skipped():
    lines = [_token_count(WEEKLY_ONLY), _token_count(None), '{"type": "event_msg", "payl', ""]
    assert limits_from_lines(lines, now=NOW)["windows"][0]["used"] == 27.0


def test_a_log_with_no_reading_has_no_limits():
    assert limits_from_lines([_token_count(None), "not json"], now=NOW) is None


def test_a_window_whose_reset_has_passed_reads_as_empty():
    window = limits_from_lines([_token_count(WEEKLY_ONLY)], now=1789843280)["windows"][0]
    assert (window["used"], window["resets_at"]) == (0.0, None)


# A reading on another limit than the plan's. Codex logs one limit per line,
# and when the server reports several, the last written wins (core
# state/session.rs), so such a reading comes last on an account still on its
# plan (issue #1's reporter: weekly at 5%, read as "on reserve"). Shape per
# codex-api's rate_limits.rs: x-<limit>-limit-name labels it.
RESERVE = {"limit_id": "gpt_reserve", "limit_name": "Luna Reserve",
           "primary": {"used_percent": 12.0, "window_minutes": 10080, "resets_at": 1789900000},
           "secondary": None, "plan_type": "plus"}


def _turn(model):
    return json.dumps({"timestamp": "2026-09-15T12:03:50.000Z", "type": "turn_context",
                       "payload": {"model": model, "cwd": "/tmp", "effort": "medium"}})


def test_another_limits_reading_on_the_plans_model_is_no_reserve():
    """The reporter's case: the plan at 5% and a gpt_reserve reading last."""
    lines = [_turn("gpt-6.1-sol"), _token_count(WEEKLY_ONLY), _token_count(RESERVE)]
    limits = limits_from_lines(lines, now=NOW)
    assert [w["used"] for w in limits["windows"]] == [27.0]
    assert "reserve" not in limits


def test_on_the_reserve_model_the_reserve_reading_is_the_reserve():
    """Codex moves onto Luna Reserve by switching the model (tui model_catalog.rs)."""
    lines = [_token_count(WEEKLY_ONLY), _turn("gpt-reserve"), _token_count(RESERVE)]
    limits = limits_from_lines(lines, now=NOW)
    assert [w["used"] for w in limits["windows"]] == [27.0]
    assert limits["reserve"]["label"] == "Luna Reserve"
    assert (limits["reserve"]["used"], limits["reserve"]["resets_at"]) == (12.0, 1789900000)


def test_on_the_reserve_model_with_no_plan_reading_the_plan_is_unread():
    limits = limits_from_lines([_turn("GPT-Reserve"), _token_count(RESERVE)], now=NOW)
    assert limits["windows"] == []
    assert limits["reserve"]["used"] == 12.0


def test_back_on_the_plans_model_the_reserve_is_gone():
    lines = [_token_count(WEEKLY_ONLY), _turn("gpt-reserve"), _token_count(RESERVE),
             _turn("gpt-6.1-sol"), _token_count(RESERVE)]
    limits = limits_from_lines(lines, now=NOW)
    assert [w["used"] for w in limits["windows"]] == [27.0]
    assert "reserve" not in limits


def test_an_unnamed_other_limit_is_labelled_by_its_id():
    unnamed = dict(RESERVE, limit_id="premium", limit_name=None)
    assert limits_from_lines([_turn("gpt-reserve"), _token_count(unnamed)], now=NOW)["reserve"]["label"] == "premium"


def test_a_reserve_reading_without_a_window_is_no_reserve():
    """A depleted-credits record names another limit but carries no window."""
    depleted = dict(RESERVE, primary=None)
    assert limits_from_lines([_turn("gpt-reserve"), _token_count(depleted)], now=NOW) is None


def _rollout(root, day, name, lines, mtime):
    folder = root / "2026" / "09" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-{name}.jsonl"
    path.write_text("\n".join(lines) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def test_read_limits_takes_the_newest_rollout(tmp_path):
    _rollout(tmp_path, "14", "old", [_token_count(FIVE_HOUR_AND_WEEKLY)], mtime=NOW - 86400)
    _rollout(tmp_path, "15", "new", [_token_count(WEEKLY_ONLY)], mtime=NOW - 60)
    assert [w["used"] for w in read_limits(str(tmp_path), now=NOW)["windows"]] == [27.0]


def test_read_limits_falls_back_past_a_new_rollout_with_no_reading_yet(tmp_path):
    _rollout(tmp_path, "14", "old", [_token_count(WEEKLY_ONLY)], mtime=NOW - 86400)
    _rollout(tmp_path, "15", "just-started", ['{"type": "session_meta"}'], mtime=NOW - 5)
    assert read_limits(str(tmp_path), now=NOW)["windows"][0]["used"] == 27.0


def test_read_limits_finds_the_last_reading_of_a_long_rollout(tmp_path):
    filler = [json.dumps({"type": "response_item", "payload": {"text": "x" * 1000}})] * 400
    _rollout(tmp_path, "15", "long", [_token_count(FIVE_HOUR_AND_WEEKLY)] + filler + [_token_count(WEEKLY_ONLY)],
             mtime=NOW)
    assert [w["used"] for w in read_limits(str(tmp_path), now=NOW)["windows"]] == [27.0]


def test_read_limits_without_codex_installed_is_none(tmp_path):
    assert read_limits(str(tmp_path / "missing"), now=NOW) is None


# Shaped as a real rollout's last turn_context and token_count on 2026-09-15.
TURN_CONTEXT = json.dumps({"type": "turn_context", "payload": {
    "cwd": "/Users/jane/project", "model": "gpt-6-astra", "effort": "medium", "approval_policy": "on-request"}})
TOKEN_COUNT = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
    "total_token_usage": {"input_tokens": 6082346, "output_tokens": 9693, "total_tokens": 6092039},
    "last_token_usage": {"input_tokens": 27581, "cached_input_tokens": 27008, "output_tokens": 280,
                         "reasoning_output_tokens": 0, "total_tokens": 27861},
    "model_context_window": 258400}, "rate_limits": WEEKLY_ONLY}})


def test_a_session_reads_its_effort_and_how_full_its_context_is():
    assert session_from_lines([TURN_CONTEXT, TOKEN_COUNT]) == {"effort": "medium", "context": 6}


def _last_turn(tokens):
    return json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": {"total_tokens": tokens}, "model_context_window": 258400}}})


def test_context_agrees_with_codex_status():
    """Codex /status on 2026-09-15 read "94% left (27.4K used / 258K)" for a
    session whose last turn was 27371 tokens; the plain ratio says 89% left."""
    assert session_from_lines([_last_turn(27371)])["context"] == 6


def test_a_context_holding_only_the_fixed_prompt_reads_empty():
    assert session_from_lines([_last_turn(9000)])["context"] == 0


def test_context_ignores_the_session_wide_token_total():
    """total_token_usage adds up every turn: 6 M against a 258 k window."""
    assert session_from_lines([TOKEN_COUNT])["context"] == 6


def test_a_session_that_has_not_finished_a_turn_reads_as_unknown():
    no_info = json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": None}})
    assert session_from_lines([no_info, '{"torn']) == {"effort": None, "context": None}


def test_a_rollout_that_cannot_be_read_reads_as_unknown(tmp_path):
    assert read_session(str(tmp_path / "gone.jsonl")) == {"effort": None, "context": None}
    assert read_session(None) == {"effort": None, "context": None}


def test_a_rollout_path_that_is_no_ordinary_file_is_not_opened(tmp_path):
    """The path arrives in a pane variable any process can write. Opening a
    pipe waits for a writer that never comes, and the panel waits with it."""
    import threading
    pipe = tmp_path / "rollout.jsonl"
    os.mkfifo(pipe)
    read = []
    reader = threading.Thread(target=lambda: read.append(read_session(str(pipe))), daemon=True)
    reader.start()
    reader.join(timeout=2)
    assert read == [{"effort": None, "context": None}]


def test_a_session_is_read_from_its_rollout_file(tmp_path):
    rollout = tmp_path / "rollout-2026-09-15T16-33-01-x.jsonl"
    rollout.write_text("\n".join([TURN_CONTEXT, TOKEN_COUNT]) + "\n")
    assert read_session(str(rollout)) == {"effort": "medium", "context": 6}


def _threads(path, rows):
    import sqlite3
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, name TEXT)")
    db.executemany("INSERT INTO threads VALUES (?, ?)", rows)
    db.commit()
    db.close()


def test_a_codex_session_is_named_as_codex_named_its_thread(tmp_path):
    """Codex titles a conversation in its state database, and the TUI shows
    that title in its status line; nothing else records it."""
    db = tmp_path / "state_5.sqlite"
    _threads(db, [("01a0edc0-8f4a", "Inspect brief and execute tasks"), ("01a0edc0-c226", None)])
    assert codex.thread_name("01a0edc0-8f4a", str(db)) == "Inspect brief and execute tasks"
    assert codex.thread_name("01a0edc0-c226", str(db)) is None
    assert codex.thread_name("absent", str(db)) is None
    assert codex.thread_name("01a0edc0-8f4a", str(tmp_path / "missing.sqlite")) is None
    assert codex.thread_name(None, str(db)) is None


def rollout_lines(*items):
    return "\n".join(json.dumps(item) for item in items) + "\n"


def turn(turn_id, developer_text, answer, filler=0):
    yield {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn_id}}
    yield {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                 "content": [{"type": "input_text", "text": developer_text}]}}
    for _ in range(filler):
        yield {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "x" * 1000}]}}
    if answer is not None:
        yield {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id, "last_agent_message": answer}}


def test_the_asked_reply_is_the_last_message_of_the_turn_whose_context_carries_the_nonce(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t1", "Task line ...", "earlier"),
                                  *turn("t2", "Write your latest result ... (link 00aa11bb22cc33dd)", "the result", filler=300),
                                  *turn("t3", "Task line ...", "later")))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") == "the result"


def test_no_reply_until_the_asked_turn_completes_and_none_for_another_nonce(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t2", "... (link 00aa11bb22cc33dd)", None)))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") is None
    assert codex.asked_reply(str(path), "ffffffffffffffff") is None
    assert codex.asked_reply(None, "00aa11bb22cc33dd") is None
    assert codex.asked_reply(str(tmp_path / "missing.jsonl"), "00aa11bb22cc33dd") is None


def test_an_empty_last_message_is_returned_empty_for_the_book_to_refuse(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t2", "(link 00aa11bb22cc33dd)", None),
                                  {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t2",
                                                                    "last_agent_message": None}}))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") == ""


def test_an_interrupted_asked_turn_is_an_empty_reply_for_the_book_to_refuse(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t2", "(link 00aa11bb22cc33dd)", None),
                                  {"type": "event_msg", "payload": {"type": "turn_aborted", "turn_id": "t2",
                                                                    "reason": "interrupted"}}))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") == ""
