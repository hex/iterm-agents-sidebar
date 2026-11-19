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
    """Stands in for `agy`: answers each ask with the next (exit code, stdout), or raises it."""

    def __init__(self, *answers):
        self.answers, self.asks = list(answers), 0

    def __call__(self, path):
        self.asks += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def test_a_reading_shows_in_the_snapshot_and_the_next_ask_waits_its_interval():
    agy = Agy((0, json.dumps(REPLY)), (0, json.dumps(REPLY)))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    assert quota.step(NOW) is True
    snap = quota.snapshot(NOW)
    assert [g["name"] for g in snap["groups"]] == ["Gemini Models", "Claude and GPT models", "Gemini 4 Argon"]
    assert "as_of" not in snap
    assert quota.step(NOW + agy_quota.READ_SECONDS - 1) is False
    assert agy.asks == 1
    quota.step(NOW + agy_quota.READ_SECONDS)
    assert agy.asks == 2


def test_without_agy_nothing_runs_and_nothing_shows():
    agy = Agy()
    quota = Quota(find=lambda: None, run=agy)
    assert quota.step(NOW) is False
    assert quota.snapshot(NOW) is None
    assert agy.asks == 0


def test_a_failed_ask_keeps_the_last_figures_and_says_how_old_they_are():
    agy = Agy((0, json.dumps(REPLY)), (1, ""), subprocess.TimeoutExpired("agy", 60))
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW)
    assert quota.step(NOW + agy_quota.READ_SECONDS) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    # A second failure in a row changes nothing the foot draws.
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS) is False
    assert len(said) == 2 and all(line.startswith("antigravity quota not read:") for line in said)


def _one_bucket(bucket):
    return _reply(command={"name": "usage", "data": {"groups": [{"name": "Odd", "buckets": [bucket]}]}})


@pytest.mark.parametrize("answer", [
    (0, _one_bucket({"window": ["5h"], "remaining_fraction": 0.5})),
    (0, _one_bucket({"window": "5h", "remaining_fraction": 10 ** 400})),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
], ids=["window-a-list", "fraction-of-400-digits", "output-not-utf-8"])
def test_a_reply_that_cannot_be_read_is_a_failed_ask_and_waits_its_interval(answer):
    agy = Agy((0, json.dumps(REPLY)), answer)
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW)
    assert quota.step(NOW + agy_quota.READ_SECONDS) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    # The account loop's next tick runs no agy.
    assert quota.step(NOW + agy_quota.READ_SECONDS + 30) is False
    assert agy.asks == 2


def test_an_ask_that_raises_still_moves_the_next_one():
    agy = Agy((0, json.dumps(REPLY)), RuntimeError("unforeseen"), (0, json.dumps(REPLY)))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW)
    with pytest.raises(RuntimeError):
        quota.step(NOW + agy_quota.READ_SECONDS)
    assert quota.step(NOW + agy_quota.READ_SECONDS + 30) is False
    assert agy.asks == 2


def test_a_first_ask_that_fails_shows_nothing():
    quota = Quota(find=lambda: "/bin/agy", run=Agy(OSError("gone")))
    quota.step(NOW)
    assert quota.snapshot(NOW) is None


def test_exit_code_2_is_a_failed_ask_like_any_other():
    """agy exits 2 on a flag it does not know, with its usage text and no quota."""
    agy = Agy((0, json.dumps(REPLY)), (2, ""), (0, json.dumps(REPLY)))
    said = []
    quota = Quota(find=lambda: "/bin/agy", run=agy, log=lambda *words: said.append(" ".join(words)))
    quota.step(NOW)
    assert quota.step(NOW + agy_quota.READ_SECONDS) is True
    snap = quota.snapshot(NOW + agy_quota.READ_SECONDS)
    assert snap and snap["as_of"] == NOW
    assert snap["groups"][0]["windows"][0]["used"] == 8.4
    assert len(said) == 1
    # The next ask is the usual interval away, not an hour.
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS - 1) is False
    assert agy.asks == 2
    quota.step(NOW + 2 * agy_quota.READ_SECONDS)
    assert agy.asks == 3


def test_a_window_whose_reset_has_passed_reads_empty_until_the_next_reading():
    quota = Quota(find=lambda: "/bin/agy", run=Agy((0, json.dumps(REPLY))))
    quota.step(NOW)
    after = 1795140941  # the Gemini 5-hour window's reset
    five, weekly = quota.snapshot(after)["groups"][0]["windows"]
    assert (five["used"], five["resets_at"]) == (0.0, None)
    assert weekly["used"] == 2.8


def test_reload_asks_at_once_unless_the_last_ask_was_a_moment_ago():
    agy = Agy((0, json.dumps(REPLY)), (0, json.dumps(REPLY)))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW)
    assert quota.reload(NOW + agy_quota.RELOAD_FLOOR_SECONDS - 1) is False
    assert agy.asks == 1
    quota.reload(NOW + agy_quota.RELOAD_FLOOR_SECONDS)
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
        return 0, json.dumps(REPLY)


def test_an_ask_while_another_is_in_flight_skips_rather_than_queue_another_agy():
    agy = HeldAgy()
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    first = threading.Thread(target=quota.reload, args=(NOW,))
    first.start()
    assert agy.started.wait(timeout=5)
    said = {}
    helpers = [
        threading.Thread(target=lambda: said.update(step=quota.step(NOW + agy_quota.READ_SECONDS))),
        threading.Thread(target=lambda: said.update(reload=quota.reload(NOW + 2 * agy_quota.RELOAD_FLOOR_SECONDS))),
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
    agy = Agy((0, json.dumps(REPLY)), (0, json.dumps(REPLY)), (0, json.dumps(REPLY)))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW)
    assert quota.reload(NOW + agy_quota.READ_SECONDS - 1) is True
    assert quota.step(NOW + agy_quota.READ_SECONDS) is False
    assert agy.asks == 2


def test_agy_going_away_clears_the_block():
    present = ["/bin/agy"]
    quota = Quota(find=lambda: present[0], run=Agy((0, json.dumps(REPLY))))
    quota.step(NOW)
    present[0] = None
    assert quota.step(NOW + agy_quota.READ_SECONDS) is True
    assert quota.snapshot(NOW + agy_quota.READ_SECONDS) is None


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
    assert agy_quota.run_agy("/bin/agy") == (0, "{}")
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
    assert agy_quota.run_agy("/bin/agy") == (0, "{}")
    assert len(started) == 1 and not os.path.exists(started[0].kwargs["cwd"])


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
    # The whole session goes, then what agy printed is collected.
    assert killed == [(agy.pid, signal.SIGKILL)] and agy.waits == [agy_quota.TIMEOUT_SECONDS, None]


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
    monkeypatch.setattr(agy_quota, "run_agy", lambda agy: asked.append(agy) or (0, json.dumps(REPLY)))
    quota = Quota()
    quota.step(NOW)
    assert asked == ["/bin/agy"] and quota.snapshot(NOW)


def test_no_module_beside_the_daemon_shadows_the_standard_library():
    """sidebar.py puts its own folder first on sys.path: a file there named as a standard module
    stands in for it, and on any other path order the standard one loads instead."""
    assert sorted(p.stem for p in ROOT.glob("*.py") if p.stem in sys.stdlib_module_names) == []
