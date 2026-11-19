"""Antigravity quota read from `agy -p /quota --output-format json`.

REPLY is the shape agy 1.5.12 printed on a personal Google login, with its
descriptions shortened; its figures are kept as they came.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
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


def test_a_first_ask_that_fails_shows_nothing():
    quota = Quota(find=lambda: "/bin/agy", run=Agy(OSError("gone")))
    quota.step(NOW)
    assert quota.snapshot(NOW) is None


def test_a_login_without_account_quota_hides_the_block_and_waits_an_hour():
    agy = Agy((0, json.dumps(REPLY)), (agy_quota.NO_QUOTA_EXIT, ""), (0, json.dumps(REPLY)))
    quota = Quota(find=lambda: "/bin/agy", run=agy)
    quota.step(NOW)
    assert quota.step(NOW + agy_quota.READ_SECONDS) is True
    assert quota.snapshot(NOW + agy_quota.READ_SECONDS) is None
    assert quota.step(NOW + 2 * agy_quota.READ_SECONDS) is False
    assert agy.asks == 2
    quota.step(NOW + agy_quota.READ_SECONDS + agy_quota.NO_QUOTA_SECONDS)
    assert agy.asks == 3 and quota.snapshot(NOW + agy_quota.READ_SECONDS + agy_quota.NO_QUOTA_SECONDS)


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


def test_agy_runs_quietly_out_of_any_project_with_its_log_kept_out_of_its_folder(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(agy_quota.subprocess, "run", fake_run)
    assert agy_quota.run_agy("/bin/agy") == (0, "{}")
    assert seen["argv"] == ["/bin/agy", "-p", "/quota", "--output-format", "json", "--log-file", "/dev/null"]
    assert seen["env"]["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
    assert seen["timeout"] == agy_quota.TIMEOUT_SECONDS
    assert seen["stdin"] == subprocess.DEVNULL


def test_each_run_starts_in_a_new_empty_folder_of_the_panels_own_and_leaves_none(tmp_path, monkeypatch):
    """agy reads .agents/hooks.json in the folder it starts in, so that folder is never one another
    program can write to."""
    folder = tmp_path / "share" / "agy"
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))
    cwds = []

    def fake_run(argv, **kwargs):
        cwd = kwargs["cwd"]
        cwds.append(cwd)
        assert Path(cwd).parent == folder
        assert os.listdir(cwd) == []
        assert stat.S_IMODE(os.stat(cwd).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(agy_quota.subprocess, "run", fake_run)
    assert agy_quota.run_agy("/bin/agy") == (0, "{}")
    assert len(cwds) == 1 and not os.path.exists(cwds[0])


def test_a_run_that_times_out_still_takes_its_folder_away(tmp_path, monkeypatch):
    folder = tmp_path / "share" / "agy"
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))
    cwds = []

    def fake_run(argv, **kwargs):
        cwds.append(kwargs["cwd"])
        raise subprocess.TimeoutExpired(argv, agy_quota.TIMEOUT_SECONDS)

    monkeypatch.setattr(agy_quota.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        agy_quota.run_agy("/bin/agy")
    assert len(cwds) == 1 and Path(cwds[0]).parent == folder
    assert not os.path.exists(cwds[0])


def test_a_folder_for_agy_that_is_a_link_is_refused_and_agy_never_runs(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    folder = tmp_path / "share" / "agy"
    folder.parent.mkdir()
    folder.symlink_to(elsewhere)
    monkeypatch.setattr(agy_quota, "AGY_FOLDER", str(folder))
    runs = []
    monkeypatch.setattr(agy_quota.subprocess, "run", lambda argv, **kwargs: runs.append(argv))
    with pytest.raises(OSError):
        agy_quota.run_agy("/bin/agy")
    assert runs == [] and os.listdir(elsewhere) == []


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
