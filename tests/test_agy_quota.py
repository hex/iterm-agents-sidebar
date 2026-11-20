"""Antigravity quota read from `agy -p /quota --output-format json`.

REPLY is the shape agy 1.5.12 printed on a personal Google login, with its
descriptions shortened; its figures are kept as they came.
"""
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agy_quota
from agy_quota import Quota, find_agy, quota_from_reply

#: Read at import, before the suite's fixture points it into each test's folder.
DEFAULT_AGY_FOLDER = agy_quota.AGY_FOLDER

NOW = 1795124000  # 2026-11-19T21:33:20Z
REPLY = {
    "conversation_id": "", "status": "SUCCESS", "duration_seconds": 0, "num_turns": 0,
    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    "command": {"name": "usage", "data": {"description": "Within each group, models share a weekly limit and a 5-hour limit.",
        "groups": [
            {"name": "Gemini Models",
             "description": "Models within this group: Gemini 4 Neon, Gemini 4 Hydrogen, Orchestrator (Neon), Gemini 3.8 Flash",
             "buckets": [
                 {"id": "gemini-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                  "remaining_fraction": 0.971721887588501, "reset_time": "2026-11-26T21:15:41Z"},
                 {"id": "gemini-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                  "remaining_fraction": 0.916106641292572, "reset_time": "2026-11-20T02:15:41Z"}]},
            {"name": "Claude and GPT models",
             "description": "Models within this group: Claude Opus 5.5, Claude Sonnet 5.5, GPT-OSS 120B",
             "buckets": [
                 {"id": "3p-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
                  "remaining_fraction": 1, "reset_time": "2026-11-26T21:33:20Z"},
                 {"id": "3p-5h", "name": "Five Hour Limit Remaining", "window": "5h",
                  "remaining_fraction": 1, "reset_time": "2026-11-20T02:33:20Z"}]},
            {"name": "Gemini 4 Argon",
             "description": "For paid Pro plans, Argon quota is separate.",
             "buckets": [
                 {"id": "gemini-argon-wtu-weekly", "name": "Gemini 4 Argon Weekly Limit", "window": "weekly",
                  "remaining_fraction": 0.987063467502594, "reset_time": "2026-11-26T11:31:45Z"}]}]}}}


def _reply(**changes):
    return json.dumps({**REPLY, **changes})


def test_each_group_reads_as_its_windows_shortest_first_in_percent_used():
    quota = quota_from_reply(json.dumps(REPLY), NOW)
    gemini = quota["groups"][0]
    assert gemini["name"] == "Gemini Models"
    assert [(w["label"], w["used"], w["minutes"]) for w in gemini["windows"]] == [
        ("5-hour", 8.4, 300), ("Weekly", 2.8, 10080)]
    assert gemini["windows"][0]["resets_at"] == 1795140941  # 2026-11-20T02:15:41Z


def test_a_group_names_its_models_from_agys_description():
    groups = quota_from_reply(json.dumps(REPLY), NOW)["groups"]
    assert groups[1]["models"] == ["Claude Opus 5.5", "Claude Sonnet 5.5", "GPT-OSS 120B"]
    # A description that lists no models leaves the list empty.
    assert groups[2]["models"] == []


def test_a_group_with_a_weekly_window_alone_keeps_it():
    argon = quota_from_reply(json.dumps(REPLY), NOW)["groups"][2]
    assert [(w["label"], w["used"]) for w in argon["windows"]] == [("Weekly", 1.3)]


def test_a_weekly_window_carries_its_even_spend_mark_and_a_five_hour_none():
    gemini = quota_from_reply(json.dumps(REPLY), NOW)["groups"][0]
    five, weekly = gemini["windows"]
    assert five["pace"] is None
    # Reset 2026-11-26T21:15:41Z (1795727741) is 603741 s away: the week has
    # run 1059 s, under a day, so there is no mark yet.
    assert weekly["pace"] is None
    # Two days on it has run 173859 s of 604800, 28.7% of the week.
    later = quota_from_reply(json.dumps(REPLY), NOW + 2 * 86400)["groups"][0]["windows"][1]
    assert round(later["pace"]["expected"], 1) == 28.7


def test_a_reply_that_is_not_a_quota_reads_as_none():
    assert quota_from_reply("not json", NOW) is None
    assert quota_from_reply(_reply(status="ERROR"), NOW) is None
    assert quota_from_reply(_reply(command={"name": "usage", "data": {"groups": []}}), NOW) is None
    assert quota_from_reply("[1, 2]", NOW) is None


def test_a_bucket_with_an_unknown_window_or_no_figure_is_left_out():
    groups = [{"name": "Odd", "buckets": [{"window": "monthly", "remaining_fraction": 0.5},
                                          {"window": "5h", "remaining_fraction": None},
                                          {"window": "5h", "remaining_fraction": True}]},
              {"name": "Fine", "buckets": [{"window": "5h", "remaining_fraction": 0.25, "reset_time": "bad"}]}]
    quota = quota_from_reply(_reply(command={"name": "usage", "data": {"groups": groups}}), NOW)
    assert [g["name"] for g in quota["groups"]] == ["Fine"]
    assert quota["groups"][0]["windows"][0] == {"label": "5-hour", "used": 75.0, "resets_at": None,
                                                "minutes": 300, "pace": None}


def test_used_stays_within_nought_and_a_hundred():
    groups = [{"name": "G", "buckets": [{"window": "5h", "remaining_fraction": -0.2},
                                        {"window": "weekly", "remaining_fraction": 1.4}]}]
    windows = quota_from_reply(_reply(command={"name": "usage", "data": {"groups": groups}}), NOW)["groups"][0]["windows"]
    assert [w["used"] for w in windows] == [100.0, 0.0]


class Agy:
    """Stands in for `agy`: answers each ask with the next (exit code, stdout, stderr), or raises it."""

    def __init__(self, *answers):
        self.answers, self.asks = list(answers), 0

    def __call__(self, path):
        self.asks += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def test_a_reading_shows_in_the_snapshot_and_the_next_ask_waits_its_interval():
    agy = Agy((0, json.dumps(REPLY), ""), (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    assert quota.step(NOW, True) is True
    snap = quota.snapshot(NOW)
    assert [g["name"] for g in snap["groups"]] == ["Gemini Models", "Claude and GPT models", "Gemini 4 Argon"]
    assert "as_of" not in snap
    assert quota.step(NOW + agy_quota.READ_SECONDS - 1, True) is False
    assert agy.asks == 1
    quota.step(NOW + agy_quota.READ_SECONDS, True)
    assert agy.asks == 2


def test_without_agy_nothing_runs_and_nothing_shows():
    agy = Agy()
    quota = Quota(find=lambda: None, run=agy)
    assert quota.step(NOW, True) is False
    assert quota.snapshot(NOW) is None
    assert agy.asks == 0


def test_a_failed_ask_keeps_the_last_figures_and_says_how_old_they_are():
    agy = Agy((0, json.dumps(REPLY), ""), (1, "", ""), subprocess.TimeoutExpired("agy", 60))
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW, True)
    assert quota.step(NOW + agy_quota.READ_SECONDS, True) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    # A second failure in a row changes nothing the foot draws.
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS, True) is False
    assert len(said) == 2 and all(line.startswith("antigravity quota not read:") for line in said)


#: What a signed-out agy 1.5.13 printed once its 60 s wait for a sign-in ran out.
SIGNED_OUT = (1, '{"status":"ERROR","error":"authentication failed or timed out"}',
              "Authentication required. Please visit the URL to log in:\n"
              "https://accounts.google.com/o/oauth2/auth?client_id=x\n")
#: A failed run for some other reason, with agy's own error in its JSON reply.
UNAVAILABLE = (1, '{"status":"ERROR","error":"quota service unavailable"}', "")


def _asks(*answers):
    """The log lines of one ask per answer, each READ_SECONDS after the last."""
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=Agy(*answers), log=lambda *words: said.append(" ".join(words)))
    for n in range(len(answers)):
        quota.step(NOW + n * agy_quota.READ_SECONDS, True)
    return said


def test_a_failed_run_is_logged_once_with_agys_own_error():
    said = _asks(UNAVAILABLE, UNAVAILABLE)
    assert len(said) == 1
    assert "agy /quota exited 1: quota service unavailable" in said[0]


def test_a_failed_run_with_no_reply_is_logged_once_with_the_last_line_agy_wrote_on_stderr():
    said = _asks((1, "", "Loading tools\nError: not signed in\n\n"), (1, "", "Loading tools\nError: not signed in\n\n"))
    assert len(said) == 1
    assert said[0].endswith("agy /quota exited 1: Error: not signed in")


#: What agy wrote on stderr while it could not reach Google through a proxy.
PROXY_SAYS = "proxyconnect tcp: dial tcp 10.0.0.1:3128: i/o timeout\n"


@pytest.mark.parametrize("stderr", [PROXY_SAYS, PROXY_SAYS.encode()], ids=["text", "bytes"])
def test_a_run_that_times_out_is_logged_with_the_last_line_agy_wrote_on_stderr(stderr):
    said = _asks(subprocess.TimeoutExpired("agy", 60, output="", stderr=stderr))
    assert len(said) == 1
    assert "within 60 s" in said[0] and "proxyconnect tcp" in said[0]


#: What agy printed before a process outside its group kept the run's pipes open past the timeout.
HELD_REPLY = '{"status":"ERROR","error":"quota service unavailable"}\n'


@pytest.mark.parametrize("output", [HELD_REPLY, HELD_REPLY.encode()], ids=["text", "bytes"])
def test_a_run_that_times_out_after_agy_answered_is_logged_with_its_answer(output):
    said = _asks(subprocess.TimeoutExpired("agy", 60, output=output, stderr=""))
    assert len(said) == 1
    assert "within 60 s" in said[0] and "quota service unavailable" in said[0]


def test_a_run_that_times_out_with_no_output_says_so():
    said = _asks(subprocess.TimeoutExpired("agy", 60, output=None, stderr=None))
    assert said == ["antigravity quota not read: agy did not answer within 60 s: no message"]


def test_a_failure_is_logged_again_after_a_good_reading():
    said = _asks(UNAVAILABLE, (0, json.dumps(REPLY), ""), UNAVAILABLE)
    assert len(said) == 2 and said[0] == said[1]


@pytest.mark.parametrize("signed_out", [
    SIGNED_OUT,
    subprocess.TimeoutExpired("agy", agy_quota.TIMEOUT_SECONDS, output="",
                              stderr="Authentication required. Please visit the URL to log in:\n"
                                     "  https://accounts.google.com/o/oauth2/auth?x=y\n"),
], ids=["its-wait-for-a-sign-in-ran-out", "the-panels-timeout-came-first"])
def test_a_signed_out_agy_is_asked_again_only_after_a_reload_or_the_setting_going_off_and_on(signed_out):
    """Signed out, agy wants a browser sign-in and waits a minute for it: asking every few minutes
    would only wait that minute again."""
    agy = Agy((0, json.dumps(REPLY), ""), signed_out, signed_out, signed_out)
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW - agy_quota.READ_SECONDS, True)
    assert quota.step(NOW, True) is True
    assert said == ["antigravity quota not read: agy is signed out; asking again after a press of reload"]
    assert quota.snapshot(NOW)["as_of"] == NOW - agy_quota.READ_SECONDS
    for later in (agy_quota.READ_SECONDS, agy_quota.QUIET_READ_SECONDS, 2 * agy_quota.QUIET_READ_SECONDS):
        assert quota.step(NOW + later, True) is False
    assert agy.asks == 2
    pressed = NOW + 2 * agy_quota.QUIET_READ_SECONDS + 2 * agy_quota.RELOAD_FLOOR_SECONDS
    quota.reload(pressed, True)
    assert agy.asks == 3
    # Still signed out: it waits again, and says nothing new.
    assert quota.step(pressed + agy_quota.QUIET_READ_SECONDS, True) is False
    assert agy.asks == 3 and len(said) == 1
    quota.step(pressed + agy_quota.QUIET_READ_SECONDS, False)
    quota.step(pressed + agy_quota.QUIET_READ_SECONDS + 30, True)
    assert agy.asks == 4


def test_a_reset_lifts_the_pause_and_the_next_step_asks_at_once():
    """Settings resets the quota when the setting changes, so switching it off and on again works
    however quickly it is done, with no tick in between to see it off."""
    agy = Agy((0, json.dumps(REPLY), ""), SIGNED_OUT, (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW - agy_quota.READ_SECONDS, True)
    quota.step(NOW, True)
    assert quota.signed_out is True
    assert quota.reset() is True
    assert quota.signed_out is False and quota.snapshot(NOW) is None
    assert quota.step(NOW + 1, True) is True
    assert agy.asks == 3


def test_an_ask_already_in_flight_when_the_setting_is_switched_counts_for_nothing():
    """A signed-out agy keeps its run waiting up to a minute: the switch must win over that answer."""
    agy = HeldLast((0, json.dumps(REPLY), ""), SIGNED_OUT)
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW - agy_quota.READ_SECONDS, True)
    step = threading.Thread(target=quota.step, args=(NOW, True))
    step.start()
    assert agy.started.wait(timeout=5)
    quota.reset()
    agy.release.set()
    step.join(timeout=5)
    assert not step.is_alive()
    assert quota.signed_out is False and quota.snapshot(NOW) is None and said == []
    agy.answers.append((0, json.dumps(REPLY), ""))
    assert quota.step(NOW + 1, True) is True
    assert agy.asks == 3


def test_a_run_that_fails_for_another_reason_is_asked_again_on_time():
    agy = Agy((0, json.dumps(REPLY), ""), UNAVAILABLE, UNAVAILABLE)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    quota.step(NOW + agy_quota.READ_SECONDS, True)
    quota.step(NOW + 2 * agy_quota.READ_SECONDS, True)
    assert agy.asks == 3


def test_a_failed_run_that_says_nothing_is_logged_as_such():
    said = _asks((1, "", ""))
    assert said == ["antigravity quota not read: agy /quota exited 1: no message"]


def test_agys_message_is_cut_to_its_first_characters():
    said = _asks((1, "", "x" * 1000 + "\n"))
    assert said == ["antigravity quota not read: agy /quota exited 1: " + "x" * agy_quota.REASON_CHARS]


def _gemini_buckets(*buckets):
    """REPLY with the Gemini group's buckets replaced by these."""
    gemini, *rest = REPLY["command"]["data"]["groups"]
    return _reply(command={"name": "usage", "data": {"groups": [{**gemini, "buckets": list(buckets)}, *rest]}})


GEMINI_5H = REPLY["command"]["data"]["groups"][0]["buckets"][1]


@pytest.mark.parametrize("bucket, window, reason", [
    ({"id": "gemini-daily", "window": "daily", "remaining_fraction": 0.5, "reset_time": "2026-11-20T21:33:20Z"},
     "daily", "unknown window"),
    ({"id": "gemini-weekly", "window": "weekly", "reset_time": "2026-11-26T21:15:41Z"},
     "weekly", "no remaining_fraction"),
], ids=["unknown-window", "no-remaining-fraction"])
def test_a_bucket_the_foot_cannot_draw_is_logged_once_with_its_group(bucket, window, reason):
    """Google names the windows, so a new one can come without an agy update."""
    answer = (0, _gemini_buckets(bucket, GEMINI_5H), "")
    agy = Agy(answer, answer)
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW, True)
    assert said == [f"antigravity quota: Gemini Models window {window!r} not drawn ({reason})"]
    # The group still shows the window it can draw.
    assert [w["label"] for w in quota.snapshot(NOW)["groups"][0]["windows"]] == ["5-hour"]
    quota.step(NOW + agy_quota.READ_SECONDS, True)
    assert agy.asks == 2 and len(said) == 1


def _one_bucket(bucket):
    return _reply(command={"name": "usage", "data": {"groups": [{"name": "Odd", "buckets": [bucket]}]}})


@pytest.mark.parametrize("answer", [
    (0, _one_bucket({"window": ["5h"], "remaining_fraction": 0.5}), ""),
    (0, _one_bucket({"window": "5h", "remaining_fraction": 10 ** 400}), ""),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
], ids=["window-a-list", "fraction-of-400-digits", "output-not-utf-8"])
def test_a_reply_that_cannot_be_read_is_a_failed_ask_and_waits_its_interval(answer):
    agy = Agy((0, json.dumps(REPLY), ""), answer)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert quota.step(NOW + agy_quota.READ_SECONDS, True) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    # The account loop's next tick runs no agy.
    assert quota.step(NOW + agy_quota.READ_SECONDS + 30, True) is False
    assert agy.asks == 2


def test_a_reply_nested_too_deep_to_parse_is_a_failed_ask():
    """json.loads raises RecursionError, not ValueError, on arrays nested this deep."""
    deep = "[" * 200000
    agy = Agy((0, json.dumps(REPLY), ""), (0, deep, ""), (1, deep, ""))
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW, True)
    for n in (1, 2):
        quota.step(NOW + n * agy_quota.READ_SECONDS, True)
        snap = quota.snapshot(NOW + n * agy_quota.READ_SECONDS)
        assert snap["as_of"] == NOW
        assert snap["groups"][0]["windows"][0]["used"] == 8.4
        assert len(said) == n and said[-1].startswith("antigravity quota not read:")
    assert agy.asks == 3


def test_an_ask_that_raises_still_moves_the_next_one():
    agy = Agy((0, json.dumps(REPLY), ""), RuntimeError("unforeseen"), (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    with pytest.raises(RuntimeError):
        quota.step(NOW + agy_quota.READ_SECONDS, True)
    assert quota.step(NOW + agy_quota.READ_SECONDS + 30, True) is False
    assert agy.asks == 2


def test_a_first_ask_that_fails_shows_nothing():
    quota = Quota(find=lambda: "/bin/agy", run=Agy(OSError("gone")))
    quota.step(NOW, True)
    assert quota.snapshot(NOW) is None


def test_exit_code_2_is_a_failed_ask_like_any_other():
    """agy exits 2 on a flag it does not know, with its usage text and no quota."""
    agy = Agy((0, json.dumps(REPLY), ""), (2, "", ""), (0, json.dumps(REPLY), ""))
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW, True)
    assert quota.step(NOW + agy_quota.READ_SECONDS, True) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap and snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    assert len(said) == 1
    # The next ask is the usual interval away, not an hour.
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS - 1, True) is False
    assert agy.asks == 2
    quota.step(NOW + 2 * agy_quota.READ_SECONDS, True)
    assert agy.asks == 3


def test_a_window_whose_reset_has_passed_reads_empty_until_the_next_reading():
    quota = Quota(find=lambda: "/bin/agy", run=Agy((0, json.dumps(REPLY), "")))
    quota.step(NOW, True)
    after = 1795140941  # the Gemini 5-hour window's reset
    five, weekly = quota.snapshot(after)["groups"][0]["windows"]
    assert (five["used"], five["resets_at"]) == (0.0, None)
    assert weekly["used"] == 2.8


def test_reload_asks_at_once_unless_the_last_ask_was_a_moment_ago():
    agy = Agy((0, json.dumps(REPLY), ""), (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert quota.reload(NOW + agy_quota.RELOAD_FLOOR_SECONDS - 1, True) is False
    assert agy.asks == 1
    quota.reload(NOW + agy_quota.RELOAD_FLOOR_SECONDS, True)
    assert agy.asks == 2


class HeldAgy:
    """Stands in for an agy that answers only once `answer` is set, counting its runs."""

    def __init__(self):
        self.answer, self.started = threading.Event(), threading.Event()
        self.runs = self.in_flight = self.most_in_flight = 0
        self._count = threading.Lock()

    def __call__(self, path):
        with self._count:
            self.runs += 1
            self.in_flight += 1
            self.most_in_flight = max(self.most_in_flight, self.in_flight)
        self.started.set()
        self.answer.wait(timeout=10)
        with self._count:
            self.in_flight -= 1
        return 0, json.dumps(REPLY), ""


def test_an_ask_while_another_is_in_flight_skips_rather_than_queue_another_agy():
    agy = HeldAgy()
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    first = threading.Thread(target=quota.reload, args=(NOW, True))
    first.start()
    assert agy.started.wait(timeout=5)
    said = {}
    helpers = [
        threading.Thread(target=lambda: said.update(step=quota.step(NOW + agy_quota.READ_SECONDS, True))),
        threading.Thread(target=lambda: said.update(reload=quota.reload(NOW + 2 * agy_quota.RELOAD_FLOOR_SECONDS, True))),
    ]
    for helper in helpers:
        helper.start()
        helper.join(timeout=1)
    waiting = [helper.is_alive() for helper in helpers]
    runs_while_held = agy.runs
    agy.answer.set()
    for thread in [first, *helpers]:
        thread.join(timeout=5)
    assert (waiting, runs_while_held) == ([False, False], 1)
    assert said == {"step": False, "reload": False}
    assert (agy.runs, agy.most_in_flight) == (1, 1)


class HeldLast:
    """Stands in for agy: each ask takes the next answer, and the last answer waits for `release`."""

    def __init__(self, *answers):
        self.answers, self.asks = list(answers), 0
        self.started, self.release = threading.Event(), threading.Event()

    def __call__(self, path):
        self.asks += 1
        answer = self.answers.pop(0)
        if not self.answers:
            self.started.set()
            self.release.wait(timeout=10)
        return answer


def _press_while_held(quota, agy, asked):
    """A step's ask at `asked` held in agy, and a press of reload meanwhile: -> what the press returned."""
    step = threading.Thread(target=quota.step, args=(asked, True))
    step.start()
    assert agy.started.wait(timeout=5)
    began = time.monotonic()
    pressed = quota.reload(asked + 2 * agy_quota.RELOAD_FLOOR_SECONDS, True)
    assert time.monotonic() - began < 1
    agy.release.set()
    step.join(timeout=5)
    assert not step.is_alive()
    return pressed


def test_a_reload_pressed_while_a_step_asks_brings_the_next_ask_within_five_minutes():
    agy = HeldLast(*[(0, json.dumps(REPLY), "")] * 4)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 2) == [5 * 60, 10 * 60]
    assert quota.gap == 20 * 60
    asked = NOW + 35 * 60
    assert _press_while_held(quota, agy, asked) is False
    assert agy.asks == 4 and quota.asked_at == asked
    assert quota.gap == agy_quota.READ_SECONDS
    assert quota.next_at <= asked + agy_quota.READ_SECONDS


def test_a_reload_pressed_while_a_step_hears_agy_is_signed_out_clears_that_pause():
    agy = HeldLast((0, json.dumps(REPLY), ""), SIGNED_OUT)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    asked = NOW + agy_quota.READ_SECONDS
    assert _press_while_held(quota, agy, asked) is False
    assert agy.asks == 2
    assert quota.signed_out is False
    assert quota.next_at <= asked + agy_quota.READ_SECONDS


def test_a_reload_whose_own_ask_hears_agy_is_signed_out_stays_paused():
    agy = Agy((0, json.dumps(REPLY), ""), SIGNED_OUT)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert quota.reload(NOW + agy_quota.READ_SECONDS, True) is True
    assert agy.asks == 2 and quota.signed_out is True
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS, True) is False
    assert agy.asks == 2


def test_a_snapshot_reads_what_the_foot_draws_once_while_an_ask_may_replace_it():
    reading = quota_from_reply(json.dumps(REPLY), NOW)

    class Racing(Quota):
        """The first look at what shows finds the reading and the next finds none, as when an
        ask in another thread clears it between the two."""
        looks = 0

        @property
        def _shown(self):
            self.looks += 1
            return (reading, NOW, False) if self.looks == 1 else None

        @_shown.setter
        def _shown(self, value):
            self.stored = value

    snap = Racing(find=lambda: "/bin/agy", run=Agy()).snapshot(NOW)
    assert [g["name"] for g in snap["groups"]] == ["Gemini Models", "Claude and GPT models", "Gemini 4 Argon"]
    assert "as_of" not in snap


def test_a_step_after_a_reload_waits_for_the_reloads_interval():
    agy = Agy((0, json.dumps(REPLY), ""), (0, json.dumps(REPLY), ""), (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert quota.reload(NOW + agy_quota.READ_SECONDS - 1, True) is True
    assert quota.step(NOW + agy_quota.READ_SECONDS, True) is False
    assert agy.asks == 2


def test_agy_going_away_clears_the_block():
    present = ["/bin/agy"]
    quota = Quota(find=lambda: present[0], run=Agy((0, json.dumps(REPLY), "")))
    quota.step(NOW, True)
    present[0] = None
    assert quota.step(NOW + agy_quota.READ_SECONDS, True) is True
    assert quota.snapshot(NOW + agy_quota.READ_SECONDS) is None


def test_with_the_setting_off_agy_is_never_looked_up_or_run_and_nothing_shows():
    looked = []
    agy = Agy()
    quota = Quota(find=lambda: looked.append(1) or "/bin/agy", run=agy)
    assert quota.step(NOW, False) is False
    assert quota.reload(NOW, False) is False
    assert quota.step(NOW + agy_quota.QUIET_READ_SECONDS, False) is False
    assert (looked, agy.asks) == ([], 0)
    assert quota.snapshot(NOW) is None


def test_turning_the_setting_off_clears_the_block_and_turning_it_on_asks_at_once():
    agy = Agy((0, json.dumps(REPLY), ""), (0, json.dumps(REPLY), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert quota.step(NOW + 30, False) is True
    assert quota.snapshot(NOW + 30) is None
    assert quota.step(NOW + 60, False) is False
    # On again a minute later, well inside the interval: agy is asked at once.
    quota.step(NOW + 90, True)
    assert agy.asks == 2
    assert quota.snapshot(NOW + 90)


def _changed(fraction=None, reset_time=None):
    """REPLY with the Gemini 5-hour window's figure or its reset time changed."""
    reply = json.loads(json.dumps(REPLY))
    five = reply["command"]["data"]["groups"][0]["buckets"][1]
    if fraction is not None:
        five["remaining_fraction"] = fraction
    if reset_time is not None:
        five["reset_time"] = reset_time
    return json.dumps(reply)


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _gaps(quota, agy, since, count):
    """Steps once a second after an ask at `since`: -> the seconds between each of the next `count` asks."""
    gaps, last, now = [], since, since
    while len(gaps) < count:
        now += 1
        asks = agy.asks
        quota.step(now, True)
        if agy.asks > asks:
            gaps.append(now - last)
            last = now
        assert now - last <= 2 * agy_quota.QUIET_READ_SECONDS, f"no ask in an hour after {gaps}"
    return gaps


def test_while_the_figures_hold_still_the_gap_doubles_up_to_half_an_hour():
    agy = Agy(*[(0, json.dumps(REPLY), "")] * 6)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 5) == [5 * 60, 10 * 60, 20 * 60, 30 * 60, 30 * 60]


def test_a_change_in_the_figures_brings_the_gap_back_to_five_minutes():
    agy = Agy(*[(0, json.dumps(REPLY), "")] * 3, (0, _changed(fraction=0.5), ""), (0, _changed(fraction=0.5), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 4) == [5 * 60, 10 * 60, 20 * 60, 5 * 60]


def test_readings_that_differ_only_in_their_reset_times_hold_still():
    """agy's reset times drift by a second or so from one answer to the next."""
    agy = Agy((0, json.dumps(REPLY), ""), (0, _changed(reset_time="2026-11-20T02:15:42Z"), ""),
              (0, _changed(reset_time="2026-11-20T02:15:43Z"), ""))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 2) == [5 * 60, 10 * 60]


def test_a_reload_after_a_stretch_brings_the_gap_back_to_five_minutes():
    agy = Agy(*[(0, json.dumps(REPLY), "")] * 6)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 2) == [5 * 60, 10 * 60]
    pressed = NOW + 15 * 60 + 2 * agy_quota.RELOAD_FLOOR_SECONDS
    assert quota.reload(pressed, True) is True
    assert agy.asks == 4
    assert _gaps(quota, agy, pressed, 2) == [5 * 60, 10 * 60]


def test_a_reload_the_floor_refuses_still_brings_the_next_ask_within_five_minutes():
    agy = Agy(*[(0, json.dumps(REPLY), "")] * 5)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    assert _gaps(quota, agy, NOW, 2) == [5 * 60, 10 * 60]
    asked = NOW + 15 * 60
    assert quota.reload(asked + agy_quota.RELOAD_FLOOR_SECONDS - 1, True) is False
    assert agy.asks == 3
    assert _gaps(quota, agy, asked, 2) == [5 * 60, 10 * 60]


def test_a_reset_inside_a_long_gap_still_reads_empty_on_time():
    resets = NOW + 50 * 60
    agy = Agy(*[(0, _changed(reset_time=_iso(resets)), "")] * 4)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW, True)
    # Asks at 0, 5, 15 and 35 minutes; the next is 30 minutes on, at 65.
    assert _gaps(quota, agy, NOW, 3) == [5 * 60, 10 * 60, 20 * 60]
    assert quota.step(resets, True) is False and agy.asks == 4
    five = quota.snapshot(resets)["groups"][0]["windows"][0]
    assert (five["label"], five["used"], five["resets_at"]) == ("5-hour", 0.0, None)
    assert quota.snapshot(resets - 1)["groups"][0]["windows"][0]["used"] == 8.4


HOUR = 60 * 60


def _resetting(five_hour_at, weekly_at, argon_at):
    """A reply of Gemini, 25% of its 5-hour and 10% of its weekly window spent, and Argon, 50% of
    its one weekly window, each window resetting at the time given."""
    groups = [
        {"name": "Gemini Models", "buckets": [
            {"window": "5h", "remaining_fraction": 0.75, "reset_time": _iso(five_hour_at)},
            {"window": "weekly", "remaining_fraction": 0.9, "reset_time": _iso(weekly_at)}]},
        {"name": "Gemini 4 Argon", "buckets": [
            {"window": "weekly", "remaining_fraction": 0.5, "reset_time": _iso(argon_at)}]}]
    return (0, _reply(command={"name": "usage", "data": {"groups": groups}}), "")


def _failing_since(reading):
    """A Quota that read `reading` at NOW and whose ask 5 minutes later failed."""
    quota = Quota(find=lambda: "/bin/agy", run=Agy(reading, UNAVAILABLE))
    quota.step(NOW, True)
    quota.step(NOW + agy_quota.READ_SECONDS, True)
    return quota


def _drawn(snap):
    return [(g["name"], [(w["label"], w["used"]) for w in g["windows"]]) for g in snap["groups"]]


def test_while_asks_fail_a_window_past_its_reset_shows_no_figure():
    """Nothing says what a window holds after its reset until agy answers again, so it is left out
    rather than read as 0%; Argon's only window has reset, so Argon goes too."""
    quota = _failing_since(_resetting(NOW + HOUR, NOW + 6 * 24 * HOUR, NOW + HOUR))
    snap = quota.snapshot(NOW + HOUR - 1)
    assert _drawn(snap) == [("Gemini Models", [("5-hour", 25.0), ("Weekly", 10.0)]),
                            ("Gemini 4 Argon", [("Weekly", 50.0)])]
    snap = quota.snapshot(NOW + 2 * HOUR)
    assert snap["as_of"] == NOW
    assert _drawn(snap) == [("Gemini Models", [("Weekly", 10.0)])]


def test_while_asks_fail_a_quota_whose_every_window_has_reset_shows_nothing():
    quota = _failing_since(_resetting(NOW + HOUR, NOW + HOUR, NOW + HOUR))
    assert quota.snapshot(NOW + 2 * HOUR) is None


def test_figures_a_day_old_with_every_ask_since_failing_show_nothing():
    quota = _failing_since(_resetting(NOW + HOUR, NOW + 6 * 24 * HOUR, NOW + 6 * 24 * HOUR))
    assert quota.snapshot(NOW + agy_quota.STALE_SECONDS - 1)["as_of"] == NOW
    assert quota.snapshot(NOW + agy_quota.STALE_SECONDS) is None


def test_while_asks_succeed_a_window_past_its_reset_still_reads_empty():
    quota = Quota(find=lambda: "/bin/agy", run=Agy(_resetting(NOW + HOUR, NOW + 6 * 24 * HOUR, NOW + HOUR)))
    quota.step(NOW, True)
    snap = quota.snapshot(NOW + 2 * HOUR)
    assert "as_of" not in snap
    assert [(g["name"], [(w["label"], w["used"], w["resets_at"]) for w in g["windows"]]) for g in snap["groups"]] == [
        ("Gemini Models", [("5-hour", 0.0, None), ("Weekly", 10.0, NOW + 6 * 24 * HOUR)]),
        ("Gemini 4 Argon", [("Weekly", 0.0, None)])]


def test_find_agy_takes_the_first_executable_listed_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    plain = tmp_path / "plain-agy"
    plain.write_text("")
    runnable = tmp_path / "agy"
    runnable.write_text("#!/bin/sh\n")
    runnable.chmod(0o755)
    assert find_agy((str(tmp_path / "missing"), str(plain), str(runnable))) == str(runnable)
    assert find_agy((str(plain),)) is None


def stand_in_for_popen(monkeypatch, answer=("{}", ""), check=lambda kwargs: None):
    """subprocess.Popen as run_agy sees it: each start keeps its argv, its kwargs (after `check`
    has looked at them while the run is on) and each wait's timeout, and the first wait answers
    with `answer`, (stdout, stderr), or raises it. Returns the list of starts."""
    started = []

    class Popen:
        # No process has this pid, so even a real signal to it would reach nothing.
        pid = 1 << 30

        def __init__(self, argv, **kwargs):
            check(kwargs)
            self.args, self.kwargs, self.returncode, self.waits = argv, kwargs, None, []
            started.append(self)

        def communicate(self, timeout=None):
            self.waits.append(timeout)
            if isinstance(answer, BaseException):
                if len(self.waits) == 1:
                    raise answer
                return "", ""
            self.returncode = 0
            return answer

    monkeypatch.setattr(agy_quota.subprocess, "Popen", Popen)
    return started


def test_agy_runs_quietly_out_of_any_project_with_its_log_kept_out_of_its_folder(monkeypatch):
    started = stand_in_for_popen(monkeypatch)
    assert agy_quota.run_agy("/bin/agy") == (0, "{}", "")
    [agy] = started
    assert agy.args == ["/bin/agy", "-p", "/quota", "--output-format", "json", "--log-file", "/dev/null"]
    assert agy.kwargs["env"]["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
    assert agy.waits == [agy_quota.TIMEOUT_SECONDS]
    assert agy.kwargs["stdin"] == subprocess.DEVNULL
    assert agy.kwargs["stdout"] == agy.kwargs["stderr"] == subprocess.PIPE
    assert agy.kwargs["text"] is True
    # Bytes that are not UTF-8 read as U+FFFD, so they fail as a reply, not as a decode.
    assert agy.kwargs["errors"] == "replace"
    # A session of its own, so a timeout can end what agy started as well.
    assert agy.kwargs["start_new_session"] is True


def test_each_run_starts_in_a_new_empty_folder_of_the_panels_own_and_leaves_none(tmp_path, monkeypatch):
    """agy reads .agents/hooks.json in the folder it starts in, so that folder is never one another
    program can write to."""
    folder = tmp_path / "share" / "agy"
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))

    def check(kwargs):
        cwd = kwargs["cwd"]
        assert Path(cwd).parent == folder
        assert os.listdir(cwd) == []
        assert stat.S_IMODE(os.stat(cwd).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700

    started = stand_in_for_popen(monkeypatch, check=check)
    assert agy_quota.run_agy("/bin/agy") == (0, "{}", "")
    assert len(started) == 1 and not os.path.exists(started[0].kwargs["cwd"])


def test_agy_finds_an_open_of_the_panels_own_first_on_its_path_and_it_opens_nothing(monkeypatch):
    """Signed out, agy runs `open` on a Google sign-in URL, looked up on PATH."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    started = stand_in_for_popen(monkeypatch)
    agy_quota.run_agy("/bin/agy")
    bin_folder = os.path.join(agy_quota.AGY_FOLDER, "bin")
    assert started[0].kwargs["env"]["PATH"] == bin_folder + os.pathsep + "/usr/bin:/bin"
    stub = Path(bin_folder) / "open"
    assert not stub.is_symlink() and stub.read_text() == "#!/bin/sh\nexit 0\n"
    assert stat.S_IMODE(stub.stat().st_mode) == 0o700
    assert stat.S_IMODE(os.stat(bin_folder).st_mode) == 0o700
    before = stub.stat()
    agy_quota.run_agy("/bin/agy")
    assert (stub.stat().st_ino, stub.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    stub.write_text('#!/bin/sh\nexec /usr/bin/open "$@"\n')
    agy_quota.run_agy("/bin/agy")
    assert stub.read_text() == "#!/bin/sh\nexit 0\n"
    assert stat.S_IMODE(stub.stat().st_mode) == 0o700


def test_an_open_that_is_a_link_is_replaced_with_a_file_of_the_panels_own(tmp_path, monkeypatch):
    """A link to a file that holds the stub today can point at another program tomorrow."""
    target = tmp_path / "elsewhere-open"
    target.write_text(agy_quota.OPEN_STUB)
    target.chmod(0o700)
    before = target.stat()
    bin_folder = Path(agy_quota.AGY_FOLDER) / "bin"
    bin_folder.mkdir(parents=True, mode=0o700)
    link = bin_folder / "open"
    os.symlink(target, link)
    # The link's own mode, which an lstat sees, is what the stub's would be.
    if hasattr(os, "lchmod"):
        os.lchmod(link, 0o700)
    stand_in_for_popen(monkeypatch)
    agy_quota.run_agy("/bin/agy")
    assert not os.path.islink(link)
    assert link.read_text() == agy_quota.OPEN_STUB
    assert stat.S_IMODE(os.lstat(link).st_mode) == 0o700
    after = target.stat()
    assert target.read_text() == agy_quota.OPEN_STUB
    assert (after.st_ino, after.st_mtime_ns, stat.S_IMODE(after.st_mode)) == (before.st_ino, before.st_mtime_ns, 0o700)


def _stat_as_the_stub(real_lstat, path):
    """An lstat that reports `path` as the stub was a moment ago: a plain file of mode 0700."""
    def lstat(name, *args, **kwargs):
        found = real_lstat(name, *args, **kwargs)
        if os.fspath(name) != os.fspath(path):
            return found
        fields = list(found)
        fields[stat.ST_MODE] = stat.S_IFREG | 0o700
        return os.stat_result(fields)
    return lstat


def test_an_open_swapped_for_a_fifo_after_it_was_looked_at_does_not_hold_the_run(tmp_path, monkeypatch):
    """What is trusted is what was opened: a FIFO in the stub's place must not block the ask."""
    bin_folder = Path(agy_quota.AGY_FOLDER) / "bin"
    bin_folder.mkdir(parents=True, mode=0o700)
    stub = bin_folder / "open"
    os.mkfifo(stub, 0o700)
    monkeypatch.setattr(agy_quota.os, "lstat", _stat_as_the_stub(os.lstat, stub))
    done = []
    worker = threading.Thread(target=lambda: done.append(agy_quota._stub_open(str(bin_folder))), daemon=True)
    worker.start()
    worker.join(timeout=2)
    if worker.is_alive():
        # Unblock the reader the old code left waiting, so the test does not leave it behind.
        os.close(os.open(stub, os.O_WRONLY | os.O_NONBLOCK))
        worker.join(timeout=2)
        pytest.fail("the stub check blocked on a FIFO")
    assert stat.S_ISREG(os.lstat(stub).st_mode) and stub.read_text() == agy_quota.OPEN_STUB


def test_an_open_that_holds_the_stub_but_anyone_can_write_is_written_anew(tmp_path, monkeypatch):
    bin_folder = Path(agy_quota.AGY_FOLDER) / "bin"
    bin_folder.mkdir(parents=True, mode=0o700)
    stub = bin_folder / "open"
    stub.write_text(agy_quota.OPEN_STUB)
    stub.chmod(0o777)
    monkeypatch.setattr(agy_quota.os, "lstat", _stat_as_the_stub(os.lstat, stub))
    agy_quota._stub_open(str(bin_folder))
    assert stat.S_IMODE(os.stat(stub).st_mode) == 0o700 and stub.read_text() == agy_quota.OPEN_STUB


def test_a_run_looks_open_up_in_the_panels_folder_before_the_systems(tmp_path):
    """A stand-in for agy that only says which `open` its PATH finds; `command -v` runs nothing."""
    script = tmp_path / "agy"
    script.write_text("#!/bin/sh\ncommand -v open\n")
    script.chmod(0o755)
    code, out, err = agy_quota.run_agy(str(script))
    assert (code, out.strip()) == (0, os.path.join(agy_quota.AGY_FOLDER, "bin", "open"))


def test_a_run_that_times_out_still_takes_its_folder_away(tmp_path, monkeypatch):
    folder = tmp_path / "share" / "agy"
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))
    killed = []
    monkeypatch.setattr(agy_quota.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    started = stand_in_for_popen(monkeypatch, answer=subprocess.TimeoutExpired("agy", agy_quota.TIMEOUT_SECONDS))
    with pytest.raises(subprocess.TimeoutExpired):
        agy_quota.run_agy("/bin/agy")
    [agy] = started
    assert Path(agy.kwargs["cwd"]).parent == folder
    assert not os.path.exists(agy.kwargs["cwd"])
    # The whole session goes, then what agy printed is collected, for a few seconds at most.
    assert killed == [(agy.pid, signal.SIGKILL)] and agy.waits == [agy_quota.TIMEOUT_SECONDS,
                                                                    agy_quota.KILL_GRACE_SECONDS]


def test_a_run_that_times_out_ends_what_agy_started_too(tmp_path, monkeypatch):
    """A stand-in for agy that starts a child and waits on it, as a signed-out agy waits on `open`."""
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "agy"
    script.write_text('#!/bin/sh\nsleep 30 &\necho $! > "$PIDFILE"\nwait\n')
    script.chmod(0o755)
    monkeypatch.setattr(agy_quota, "TIMEOUT_SECONDS", 1)
    monkeypatch.setenv("PIDFILE", str(pidfile))
    gone = False
    try:
        began = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            agy_quota.run_agy(str(script))
        # The run ends at its timeout, not once the child lets go of agy's output.
        assert time.monotonic() - began < 10
        child = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
        gone = True
    finally:
        # The test started that sleep, so it ends it if the run left it behind.
        if not gone and pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


@pytest.fixture
def child_that_leaves_the_session(tmp_path, monkeypatch):
    """A stand-in for agy that starts a child which leaves agy's session, as a detached updater
    would, and keeps agy's output open; then the script runs the line given. Run timeouts are a
    second. The test started that child, so it ends it afterwards: no kill of the run reaches it."""
    pidfile = tmp_path / "child.pid"
    monkeypatch.setenv("PIDFILE", str(pidfile))
    monkeypatch.setattr(agy_quota, "TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(agy_quota, "KILL_GRACE_SECONDS", 1)
    child = "import os, sys, time; os.setsid(); open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"

    def agy(then):
        script = tmp_path / "agy"
        script.write_text(f'#!/bin/sh\n"{sys.executable}" -c "{child}" "$PIDFILE" &\n{then}\n')
        script.chmod(0o755)
        return str(script)

    yield agy
    deadline = time.monotonic() + 5
    while True:
        try:
            pid = int(pidfile.read_text())
            break
        except (OSError, ValueError):
            if time.monotonic() > deadline:
                return
            time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_a_run_that_times_out_ends_even_while_a_process_that_left_agys_session_holds_its_output(
        child_that_leaves_the_session):
    agy = child_that_leaves_the_session("sleep 30")
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        agy_quota.run_agy(agy)
    # The timeout, then the grace for agy's output: not the 30 s the child holds it.
    assert time.monotonic() - began < 5


def test_a_run_whose_agy_has_exited_while_its_child_holds_the_output_times_out_with_what_it_printed(
        child_that_leaves_the_session):
    """agy is gone and only a process outside its session is left, so ending the session
    finds no live process in it."""
    agy = child_that_leaves_the_session("echo '{}'")
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        agy_quota.run_agy(agy)
    assert time.monotonic() - began < 5
    assert (raised.value.output, raised.value.stderr) == ("{}\n", "")


def test_a_folder_for_agy_that_is_a_link_is_refused_and_agy_never_runs(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    folder = tmp_path / "share" / "agy"
    folder.parent.mkdir()
    folder.symlink_to(elsewhere)
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))
    started = stand_in_for_popen(monkeypatch)
    with pytest.raises(OSError):
        agy_quota.run_agy("/bin/agy")
    assert started == [] and os.listdir(elsewhere) == []


def test_the_panels_folder_for_agy_is_not_under_the_shared_temporary_folder():
    temporary = os.path.realpath(tempfile.gettempdir())
    folder = os.path.realpath(DEFAULT_AGY_FOLDER)
    assert os.path.commonpath([folder, temporary]) != temporary
    assert DEFAULT_AGY_FOLDER == os.path.expanduser("~/.local/share/agents-sidebar/agy")


def test_a_daemons_quota_looks_agy_up_at_each_ask(monkeypatch):
    """The suite's own fixture hides agy from every daemon a test builds; this is how."""
    asked = []
    monkeypatch.setattr(agy_quota, "find_agy", lambda *paths: "/bin/agy")
    monkeypatch.setattr(agy_quota, "run_agy", lambda agy: asked.append(agy) or (0, json.dumps(REPLY), ""))
    quota = Quota()
    quota.step(NOW, True)
    assert asked == ["/bin/agy"] and quota.snapshot(NOW)


def test_no_module_beside_the_daemon_shadows_the_standard_library():
    """sidebar.py puts its own folder first on sys.path: a file there named as a standard module
    stands in for it, and on any other path order the standard one loads instead."""
    assert sorted(p.stem for p in ROOT.glob("*.py") if p.stem in sys.stdlib_module_names) == []
