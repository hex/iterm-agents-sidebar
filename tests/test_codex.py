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


def test_a_weekly_window_carries_its_even_spend_mark():
    # 363280 s left of 604800 means 241520 s gone: an even spend is at 39.93%.
    pace = limits_from_lines([_token_count(WEEKLY_ONLY)], now=NOW)["windows"][0]["pace"]
    assert round(pace["expected"], 2) == 39.93 and pace["ahead"] is False


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


def test_a_session_is_read_from_its_rollout_file(tmp_path):
    rollout = tmp_path / "rollout-2026-09-15T16-33-01-x.jsonl"
    rollout.write_text("\n".join([TURN_CONTEXT, TOKEN_COUNT]) + "\n")
    assert read_session(str(rollout)) == {"effort": "medium", "context": 6}
