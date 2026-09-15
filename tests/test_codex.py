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

from codex import limits_from_lines, read_limits

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
