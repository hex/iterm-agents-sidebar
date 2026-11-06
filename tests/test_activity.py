"""The activity report: per day, project and provider, what Claude Code and Codex did.

Built from hand-made transcripts and rollouts under tmp_path, in the shapes
Claude Code and Codex write them; nothing here reads this machine's own logs
except the timing test at the end, which only reads.
"""
import datetime
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import activity
import sidebar

UTC = datetime.timezone.utc
#: Noon on Thursday 5 November 2026, UTC.
NOW = int(datetime.datetime(2026, 11, 5, 12, 0, tzinfo=UTC).timestamp())
CONVERSATION = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def _write(path, rows, age=3600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(path, (NOW - age, NOW - age))
    return path


def _transcript(tmp_path, conversation, rows, cwd="/work/app", entrypoint="cli", agent=None, age=3600):
    """A conversation's transcript, or with `agent` one of its subagents', each row stamped
    with the directory, conversation and entry point Claude Code writes on every line."""
    folder = tmp_path / "projects" / cwd.replace("/", "-")
    path = folder / f"{conversation}.jsonl" if agent is None else folder / conversation / "subagents" / agent
    return _write(path, [dict({"cwd": cwd, "sessionId": conversation, "entrypoint": entrypoint}, **row)
                         for row in rows], age)


def _reply(at, message_id, input=0, output=0, cache_read=0, cache_write=0, block=0):
    """One content block of a reply. Claude Code writes a line per block, each with the reply's whole usage."""
    return {"type": "assistant", "timestamp": at, "apiBlockIndex": block,
            "message": {"id": message_id, "role": "assistant",
                        "usage": {"input_tokens": input, "output_tokens": output,
                                  "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write,
                                  "cache_creation": {"ephemeral_5m_input_tokens": cache_write,
                                                     "ephemeral_1h_input_tokens": 0}}}}


def _prompt(at, content="rename the helper", origin="human", **extra):
    row = {"type": "user", "timestamp": at, "message": {"role": "user", "content": content}}
    if origin is not None:
        row["turnOrigin"] = origin
    return dict(row, **extra)


def _report(tmp_path, days=1, cache=None, tz=UTC):
    return activity.report(str(tmp_path / "projects"), str(tmp_path / "sessions"), days, NOW,
                           {} if cache is None else cache, tz=tz)


def _tokens(input=0, output=0, cache_read=0, cache_write=0):
    return {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write}


def test_a_reply_written_as_several_blocks_counts_its_usage_once(tmp_path):
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-05T09:00:00.000Z"),
        _reply("2026-11-05T09:00:05.000Z", "msg_01", input=10, output=200, cache_read=5000, cache_write=300, block=0),
        _reply("2026-11-05T09:00:06.000Z", "msg_01", input=10, output=200, cache_read=5000, cache_write=300, block=1),
        _reply("2026-11-05T09:00:07.000Z", "msg_01", input=10, output=200, cache_read=5000, cache_write=300, block=2),
        _reply("2026-11-05T09:00:09.000Z", "msg_02", input=1, output=20, cache_read=100),
    ])
    assert _report(tmp_path) == {
        "generated_at": NOW,
        "days": [{"date": "2026-11-05", "claude": [
            {"project": "/work/app", "scratch": False, "entrypoint": "cli", "conversations": 1, "prompts": 1,
             "tokens": _tokens(input=11, output=220, cache_read=5100, cache_write=300)}], "codex": []}],
        "conversations": [],
        "unread": []}


def test_a_line_counts_on_the_day_it_fell_on_here_not_in_utc_and_every_day_of_the_window_is_listed(tmp_path):
    """Two hours east of UTC, 21:30Z is 23:30 on the 4th and 22:30Z is half past midnight on the 5th."""
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-04T21:30:00.000Z"),
        _reply("2026-11-04T21:30:05.000Z", "msg_01", input=3, output=30),
        _prompt("2026-11-04T22:30:00.000Z"),
        _reply("2026-11-04T22:30:05.000Z", "msg_02", input=4, output=40),
    ])
    east = datetime.timezone(datetime.timedelta(hours=2))
    assert _report(tmp_path, days=3, tz=east)["days"] == [
        {"date": "2026-11-05", "claude": [{"project": "/work/app", "scratch": False, "entrypoint": "cli",
                                           "conversations": 1, "prompts": 1, "tokens": _tokens(input=4, output=40)}],
         "codex": []},
        {"date": "2026-11-04", "claude": [{"project": "/work/app", "scratch": False, "entrypoint": "cli",
                                           "conversations": 1, "prompts": 1, "tokens": _tokens(input=3, output=30)}],
         "codex": []},
        {"date": "2026-11-03", "claude": [], "codex": []}]


def test_a_worktree_counts_as_the_checkout_it_belongs_to_and_a_cs_folder_as_itself(tmp_path):
    """A subagent's worktree, or a directory inside one, is the checkout's work. A session's
    .cs folder and directories that are gone keep their own rows: the spend happened there."""
    _transcript(tmp_path, CONVERSATION, [_reply("2026-11-05T09:00:00.000Z", "msg_01", output=10)],
                cwd="/work/app")
    _transcript(tmp_path, OTHER, [_reply("2026-11-05T09:00:00.000Z", "msg_02", output=20)],
                cwd="/work/app/.claude/worktrees/agent-a1b2/pkg/cli")
    _transcript(tmp_path, "33333333-3333-4333-8333-333333333333",
                [_reply("2026-11-05T09:00:00.000Z", "msg_03", output=1)], cwd="/work/app/.cs/memory")
    assert _report(tmp_path)["days"][0]["claude"] == [
        {"project": "/work/app", "scratch": False, "entrypoint": "cli", "conversations": 2, "prompts": 0,
         "tokens": _tokens(output=30)},
        {"project": "/work/app/.cs/memory", "scratch": False, "entrypoint": "cli", "conversations": 1, "prompts": 0,
         "tokens": _tokens(output=1)}]


def test_a_project_in_or_under_a_temporary_root_is_a_scratch_dir_by_either_of_its_names(tmp_path):
    """macOS keeps its temporary roots at /tmp and /var/folders, and at /private/tmp and
    /private/var/folders under their real names; a throwaway run's work is there. A worktree
    counts to its checkout first, so one under a scratch checkout is scratch too. A folder that
    only starts with a root's name, or a tmp folder elsewhere, is a project like any other."""
    for n, cwd in enumerate(["/tmp", "/private/tmp/e2e-run", "/var/folders/jw/x1/T/probe",
                             "/private/var/folders/jw/x1/T/probe", "/tmp/e2e/.claude/worktrees/agent-a1/pkg",
                             "/tmpfoo", "/private/tmpfoo", "/var/foldersx", "/work/tmp", "/work/app"]):
        _transcript(tmp_path, f"{n:08}-1111-4111-8111-111111111111",
                    [_reply("2026-11-05T09:00:00.000Z", f"msg_{n}", output=1)], cwd=cwd)
    for name, cwd in (("r1", "/private/tmp/codex-probe"), ("r2", "/work/app")):
        _rollout(tmp_path, "2026/11/05", f"2026-11-05T09-00-00-{name}", [
            _meta("2026-11-05T09:00:00.000Z", cwd, "codex_exec", name),
            _usage("2026-11-05T09:00:30.000Z", input=7, cached=0, output=1, reasoning=0)])
    day = _report(tmp_path)["days"][0]
    assert {row["project"]: row["scratch"] for row in day["claude"]} == {
        "/tmp": True, "/private/tmp/e2e-run": True, "/var/folders/jw/x1/T/probe": True,
        "/private/var/folders/jw/x1/T/probe": True, "/tmp/e2e": True,
        "/tmpfoo": False, "/private/tmpfoo": False, "/var/foldersx": False, "/work/tmp": False, "/work/app": False}
    assert {row["project"]: row["scratch"] for row in day["codex"]} == {
        "/private/tmp/codex-probe": True, "/work/app": False}


def test_a_line_with_no_directory_is_no_scratch_dir(tmp_path):
    _transcript(tmp_path, CONVERSATION, [{"type": "assistant", "timestamp": "2026-11-05T09:00:00.000Z", "cwd": None,
                                          "message": {"id": "msg_01", "usage": {"output_tokens": 3}}}])
    assert [(row["project"], row["scratch"]) for row in _report(tmp_path)["days"][0]["claude"]] == [(None, False)]


def test_a_prompt_is_what_a_person_typed_and_a_transcript_older_than_the_flag_is_judged_by_its_text(tmp_path):
    """Claude Code marks what a person typed with turnOrigin "human", text or pasted image alike;
    a task's notice, a scripted turn's prompt and the untagged lines that continue a turn are not
    prompts. A transcript from before the flag has a prompt as plain text, where a command, a
    hook's text and a tool's result start with "<", are marked isMeta, or are not text."""
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-05T09:00:00.000Z"),
        _prompt("2026-11-05T09:01:00.000Z", content=[{"type": "text", "text": "and this one"},
                                                     {"type": "image", "source": {"type": "base64"}}]),
        _prompt("2026-11-05T09:02:00.000Z", content="<command-name>/compact</command-name>"),
        _prompt("2026-11-05T09:03:00.000Z", content="<task-notification>done</task-notification>",
                origin="task_notification"),
        _prompt("2026-11-05T09:04:00.000Z", content="carry on", origin=None),
        _prompt("2026-11-05T09:05:00.000Z", content="a skill's text", origin=None, isMeta=True),
    ], cwd="/work/tagged")
    _transcript(tmp_path, OTHER, [
        _prompt("2026-11-05T09:00:00.000Z", content="rename the helper", origin=None),
        _prompt("2026-11-05T09:01:00.000Z", content="<command-name>/model</command-name>", origin=None),
        _prompt("2026-11-05T09:02:00.000Z", content="a skill's text", origin=None, isMeta=True),
        _prompt("2026-11-05T09:03:00.000Z", content=[{"type": "tool_result", "content": "ok"}], origin=None),
        _prompt("2026-11-05T09:04:00.000Z", content="split the module", origin=None),
    ], cwd="/work/untagged")
    assert {row["project"]: row["prompts"] for row in _report(tmp_path)["days"][0]["claude"]} == {
        "/work/tagged": 3, "/work/untagged": 2}


def test_a_subagents_usage_counts_to_its_conversation_and_its_task_is_not_a_prompt(tmp_path):
    """Subagents write their own transcripts in the conversation's folder, a workflow's one level
    further down, and some carry a session id of their own. Their replies are the conversation's
    spend; the task a subagent is given is the model's text, not a person's."""
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-05T09:00:00.000Z"),
        _reply("2026-11-05T09:00:05.000Z", "msg_01", input=1, output=10)])
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-05T09:01:00.000Z", content="look for the parser's callers", origin=None,
                isSidechain=True, sessionId="44444444-4444-4444-8444-444444444444"),
        _reply("2026-11-05T09:01:05.000Z", "msg_02", input=2, output=20, cache_read=200)],
        cwd="/work/app/.claude/worktrees/agent-a1", agent="agent-a1.jsonl")
    _transcript(tmp_path, CONVERSATION, [
        _prompt("2026-11-05T09:02:00.000Z", content="review the diff", origin=None, isSidechain=True),
        _reply("2026-11-05T09:02:05.000Z", "msg_03", input=3, output=30, cache_write=300)],
        agent="workflows/wf_0001/agent-a2.jsonl")
    _write(tmp_path / "projects" / "-work-app" / CONVERSATION / "subagents" / "workflows" / "wf_0001" / "journal.jsonl",
           [{"type": "launched"}])
    assert _report(tmp_path)["days"][0]["claude"] == [
        {"project": "/work/app", "scratch": False, "entrypoint": "cli", "conversations": 1, "prompts": 1,
         "tokens": _tokens(input=6, output=60, cache_read=200, cache_write=300)}]


def _rollout(tmp_path, folder, name, rows, age=60):
    return _write(tmp_path / "sessions" / folder / f"rollout-{name}.jsonl", rows, age)


def _meta(at, cwd, originator, ident):
    return {"timestamp": at, "type": "session_meta",
            "payload": {"id": ident, "timestamp": at, "cwd": cwd, "originator": originator, "cli_version": "0.0.0",
                        "source": "exec", "model_provider": "openai"}}


def _turn(at):
    return {"timestamp": at, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t"}}


def _usage(at, input, cached, output, reasoning):
    """A token_count event: Codex's running totals for the rollout, cached inside input and
    reasoning inside output."""
    totals = {"input_tokens": input, "cached_input_tokens": cached, "output_tokens": output,
              "reasoning_output_tokens": reasoning, "total_tokens": input + output}
    return {"timestamp": at, "type": "event_msg",
            "payload": {"type": "token_count", "rate_limits": {},
                        "info": {"total_token_usage": totals, "last_token_usage": totals,
                                 "model_context_window": 258400}}}


def _codex_tokens(input=0, cached_input=0, output=0, reasoning_output=0):
    return {"input": input, "cached_input": cached_input, "output": output, "reasoning_output": reasoning_output,
            "total": input + output}


def test_a_rollouts_tokens_count_on_the_day_each_total_grew_by_what_it_grew(tmp_path):
    """Codex writes running totals, so a day's tokens are how far they rose that day. The first
    session_meta is the rollout's own; a second one is the thread it was forked from."""
    _rollout(tmp_path, "2026/11/04", "2026-11-04T23-40-00-r1", [
        _meta("2026-11-04T23:40:00.000Z", "/work/app/.claude/worktrees/agent-c1", "Claude Code", "r1"),
        _meta("2026-11-04T22:00:00.000Z", "/elsewhere", "codex_exec", "r0"),
        _turn("2026-11-04T23:41:00.000Z"),
        {"timestamp": "2026-11-04T23:41:30.000Z", "type": "event_msg",
         "payload": {"type": "token_count", "info": None, "rate_limits": {}}},
        _usage("2026-11-04T23:50:00.000Z", input=1000, cached=600, output=100, reasoning=40),
        _turn("2026-11-05T00:05:00.000Z"),
        _usage("2026-11-05T00:10:00.000Z", input=2500, cached=1500, output=300, reasoning=90),
    ])
    days = _report(tmp_path, days=2)["days"]
    assert [(day["date"], day["codex"]) for day in days] == [
        ("2026-11-05", [{"project": "/work/app", "scratch": False, "originator": "Claude Code", "rollouts": 1,
                         "turns": 1,
                         "tokens": _codex_tokens(input=1500, cached_input=900, output=200, reasoning_output=50)}]),
        ("2026-11-04", [{"project": "/work/app", "scratch": False, "originator": "Claude Code", "rollouts": 1,
                         "turns": 1,
                         "tokens": _codex_tokens(input=1000, cached_input=600, output=100, reasoning_output=40)}])]


def test_a_rollout_started_weeks_ago_counts_on_the_day_it_was_written_to(tmp_path):
    """A rollout's folder is the day it started; one resumed today is today's work as well."""
    _rollout(tmp_path, "2026/10/01", "2026-10-01T10-00-00-r2", [
        _meta("2026-10-01T10:00:00.000Z", "/work/app", "codex_exec", "r2"),
        _turn("2026-10-01T10:00:01.000Z"),
        _usage("2026-10-01T10:00:30.000Z", input=50, cached=0, output=5, reasoning=0),
        _turn("2026-11-05T08:00:00.000Z"),
        _usage("2026-11-05T08:00:30.000Z", input=80, cached=10, output=9, reasoning=2)])
    _rollout(tmp_path, "2026/11/05", "2026-11-05T09-00-00-r3", [
        _meta("2026-11-05T09:00:00.000Z", "/work/app", "codex_exec", "r3"),
        _turn("2026-11-05T09:00:01.000Z"),
        _usage("2026-11-05T09:00:30.000Z", input=7, cached=0, output=1, reasoning=0)])
    assert _report(tmp_path)["days"][0]["codex"] == [
        {"project": "/work/app", "scratch": False, "originator": "codex_exec", "rollouts": 2, "turns": 2,
         "tokens": _codex_tokens(input=37, cached_input=10, output=5, reasoning_output=2)}]


def test_a_file_is_read_again_only_once_its_size_or_mtime_moves(tmp_path):
    """The cache is what keeps a week's report cheap: a file whose size and mtime are as they were
    is not opened, so a change that keeps both shows only once the file grows."""
    path = _transcript(tmp_path, CONVERSATION, [_reply("2026-11-05T09:00:00.000Z", "msg_01", output=111)])
    written = os.stat(path).st_mtime_ns
    cache = {}
    assert _report(tmp_path, cache=cache)["days"][0]["claude"][0]["tokens"] == _tokens(output=111)

    path.write_text(path.read_text().replace('"output_tokens": 111', '"output_tokens": 999'))
    os.utime(path, ns=(written, written))
    assert _report(tmp_path, cache=cache)["days"][0]["claude"][0]["tokens"] == _tokens(output=111)

    with path.open("a") as f:
        f.write(json.dumps(dict(_reply("2026-11-05T09:01:00.000Z", "msg_02", output=1),
                                cwd="/work/app", sessionId=CONVERSATION, entrypoint="cli")) + "\n")
    os.utime(path, ns=(written + 1, written + 1))
    assert _report(tmp_path, cache=cache)["days"][0]["claude"][0]["tokens"] == _tokens(output=1000)


def test_a_last_line_still_being_written_waits_for_the_next_read_and_a_broken_one_is_reported(tmp_path):
    """Claude Code appends a line at a time, so a report can catch one half written: it is left
    for the next read, which takes it whole. A line that is not JSON anywhere else is a problem
    the report names, and the rest of the file still counts."""
    path = _transcript(tmp_path, CONVERSATION, [_reply("2026-11-05T09:00:00.000Z", "msg_01", output=5)])
    rest = json.dumps(dict(_reply("2026-11-05T09:01:00.000Z", "msg_02", output=7),
                           cwd="/work/app", sessionId=CONVERSATION, entrypoint="cli")) + "\n"
    with path.open("a") as f:
        f.write(rest[:40])
    cache = {}
    first = _report(tmp_path, cache=cache)
    assert (first["days"][0]["claude"][0]["tokens"], first["unread"]) == (_tokens(output=5), [])

    with path.open("a") as f:
        f.write(rest[40:])
    assert _report(tmp_path, cache=cache)["days"][0]["claude"][0]["tokens"] == _tokens(output=12)

    broken = _transcript(tmp_path, OTHER, [_reply("2026-11-05T09:00:00.000Z", "msg_03", output=3)])
    with broken.open("a") as f:
        f.write('{"type": "assistant", "timest\n')
        for row in (_reply("not a time", "msg_04", output=4), _reply("2026-11-05T09:02:00.000Z", "msg_05", output=6)):
            f.write(json.dumps(dict(row, cwd="/work/app", sessionId=OTHER, entrypoint="cli")) + "\n")
    second = _report(tmp_path, cache=cache)
    assert second["days"][0]["claude"][0]["tokens"] == _tokens(output=21)
    assert second["unread"] == [{"path": str(broken), "error": "2 lines cannot be read, the first line 2"}]


def test_a_rollouts_totals_that_fall_or_a_rollout_with_no_session_meta_is_reported(tmp_path):
    """Codex's totals only rise; were they to fall, the counter started again, so its
    figures count from zero there and the report says so. A rollout that never says what it is
    has nothing to count against; an empty one has not begun."""
    fell = _rollout(tmp_path, "2026/11/05", "2026-11-05T08-00-00-r4", [
        _meta("2026-11-05T08:00:00.000Z", "/work/app", "codex_exec", "r4"),
        _usage("2026-11-05T08:10:00.000Z", input=500, cached=0, output=50, reasoning=0),
        _usage("2026-11-05T08:20:00.000Z", input=30, cached=0, output=3, reasoning=0),
        _usage("2026-11-05T08:30:00.000Z", input=40, cached=0, output=4, reasoning=0)])
    nameless = _rollout(tmp_path, "2026/11/05", "2026-11-05T09-00-00-r5", [
        _turn("2026-11-05T09:00:01.000Z"),
        _usage("2026-11-05T09:00:30.000Z", input=7, cached=0, output=1, reasoning=0)])
    _rollout(tmp_path, "2026/11/05", "2026-11-05T10-00-00-r6", [])
    out = _report(tmp_path)
    assert out["days"][0]["codex"] == [
        {"project": "/work/app", "scratch": False, "originator": "codex_exec", "rollouts": 1, "turns": 0,
         "tokens": _codex_tokens(input=540, output=54)}]
    assert out["unread"] == [{"path": str(fell), "error": "its token totals fell at line 3"},
                             {"path": str(nameless), "error": "no session_meta line"}]


def _append(path, rows, age=3600):
    with path.open("a") as f:
        f.write("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(path, (NOW - age, NOW - age))


def _cost(conversation, cost_usd, started, models):
    """A cost-state line: Claude Code's running cost for one run of a conversation, with no time of its own."""
    return {"type": "cost-state", "sessionId": conversation, "totalCostUSD": cost_usd, "totalAPIDuration": 1,
            "totalDuration": 2, "totalLinesAdded": 0, "totalLinesRemoved": 0, "startTime": started * 1000,
            "hasUnknownModelCost": False,
            "modelUsage": {model: {"inputTokens": i, "outputTokens": o, "cacheReadInputTokens": r,
                                   "cacheCreationInputTokens": w, "thinkingTokens": 0, "webSearchRequests": 0,
                                   "costUSD": usd} for model, (i, o, r, w, usd) in models.items()}}


def test_a_conversations_cost_is_its_last_cost_state_and_only_a_conversation_of_the_window_is_listed(tmp_path):
    """Claude Code's cost has no time, so it is a conversation's, never a day's; a conversation is
    listed when it has a line in the window, by its cost, highest first."""
    path = _transcript(tmp_path, CONVERSATION, [_prompt("2026-11-05T09:00:00.000Z"),
                                                _reply("2026-11-05T09:00:05.000Z", "msg_01", output=1)])
    _append(path, [_cost(CONVERSATION, 0.5, NOW - 7200, {"claude-opus-4-5": (1, 2, 3, 4, 0.5)}),
                   _cost(CONVERSATION, 1.75, NOW - 7200, {"claude-opus-4-5": (10, 200, 5000, 300, 1.5),
                                                          "claude-haiku-4-5": (5, 50, 0, 0, 0.25)})])
    other = _transcript(tmp_path, OTHER, [_reply("2026-11-05T10:00:00.000Z", "msg_02", output=1)],
                        cwd="/work/app/.claude/worktrees/agent-a1")
    _append(other, [_cost(OTHER, 0.25, NOW - 600, {"claude-haiku-4-5": (1, 1, 1, 1, 0.25)})])
    earlier = _transcript(tmp_path, "33333333-3333-4333-8333-333333333333",
                          [_reply("2026-11-02T10:00:00.000Z", "msg_03", output=1)])
    _append(earlier, [_cost("33333333-3333-4333-8333-333333333333", 9.0, NOW - 4 * 86400,
                            {"claude-opus-4-5": (1, 1, 1, 1, 9.0)})])
    _transcript(tmp_path, "55555555-5555-4555-8555-555555555555",
                [_reply("2026-11-05T11:00:00.000Z", "msg_04", output=1)])
    assert _report(tmp_path)["conversations"] == [
        {"session_id": CONVERSATION, "project": "/work/app", "cost_usd": 1.75, "started": NOW - 7200,
         "models": {"claude-opus-4-5": {"input": 10, "output": 200, "cache_read": 5000, "cache_write": 300,
                                        "cost_usd": 1.5},
                    "claude-haiku-4-5": {"input": 5, "output": 50, "cache_read": 0, "cache_write": 0,
                                         "cost_usd": 0.25}}},
        {"session_id": OTHER, "project": "/work/app", "cost_usd": 0.25, "started": NOW - 600,
         "models": {"claude-haiku-4-5": {"input": 1, "output": 1, "cache_read": 1, "cache_write": 1,
                                         "cost_usd": 0.25}}}]


@pytest.mark.skipif(not os.path.isdir(activity.PROJECTS_DIR), reason="no Claude Code transcripts on this machine")
def test_a_cold_report_of_today_from_this_machines_own_logs_takes_under_ten_seconds_of_cpu():
    """The panel waits on the first open of a day; a week, read once, then costs only what changed.
    Timed in this process's CPU seconds, not on the wall clock: the report does all its
    reading in this process, and a loaded machine, such as one running test suites side
    by side, stretches the wall time of the same work."""
    began = time.process_time()
    out = activity.report(activity.PROJECTS_DIR, activity.SESSIONS_DIR, 1, time.time(), {})
    took = time.process_time() - began
    assert len(out["days"]) == 1
    assert took < 10, f"a cold read of today took {took:.1f}s of CPU"


def test_two_opens_at_once_read_each_file_once(tmp_path, monkeypatch):
    """The daemon runs one report at a time over the cache it keeps: a second open waits for
    the first, then finds every file as it was read, where two at once would read a cold week
    twice over into the same cache."""
    # The daemon reads by the clock, so this transcript is written now.
    written = _transcript(tmp_path, CONVERSATION, [
        _reply(datetime.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "msg_01", output=4)])
    os.utime(written)
    monkeypatch.setattr(activity, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(activity, "SESSIONS_DIR", str(tmp_path / "sessions"))
    reads, read = [], activity.claude_file

    def slow_read(*args, **kwargs):
        reads.append(args[0])
        time.sleep(0.3)
        return read(*args, **kwargs)

    monkeypatch.setattr(activity, "claude_file", slow_read)
    bridge = sidebar.Bridge(None, None)
    results = []
    # Two days, so a midnight between writing and reading cannot move the line out of the window.
    opens = [threading.Thread(target=lambda: results.append(bridge.read_activity(2))) for _ in range(2)]
    for each in opens:
        each.start()
    for each in opens:
        each.join(5)
    assert len(reads) == 1
    assert [[row["tokens"]["output"] for day in out["days"] for row in day["claude"]] for out in results] == [[4], [4]]


def _logs_written_now(tmp_path, monkeypatch):
    """-> (a conversation's transcript with its cost, its subagent's, a rollout, a transcript last
    written ten days ago), where the daemon reads them. The daemon reads by the clock, so the
    first three are written now."""
    monkeypatch.setattr(activity, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(activity, "SESSIONS_DIR", str(tmp_path / "sessions"))
    at = datetime.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    conversation = _transcript(tmp_path, CONVERSATION, [
        _prompt(at), _reply(at, "msg_01", input=2, output=40, cache_read=900)])
    _append(conversation, [_cost(CONVERSATION, 0.5, NOW, {"claude-opus-4-5": (2, 40, 900, 0, 0.5)})])
    subagent = _transcript(tmp_path, CONVERSATION, [_reply(at, "msg_02", output=7)], agent="agent-a1.jsonl")
    rollout = _rollout(tmp_path, "2026/11/05", "2026-11-05T09-00-00-r7", [
        _meta(at, "/work/app", "codex_exec", "r7"), _turn(at),
        _usage(at, input=30, cached=10, output=3, reasoning=1)])
    for path in (conversation, subagent, rollout):
        os.utime(path)
    then = time.time() - 10 * 86400
    old = _transcript(tmp_path, OTHER, [_reply(datetime.datetime.fromtimestamp(then, UTC).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"), "msg_03", output=5)])
    os.utime(old, (then, then))
    return conversation, subagent, rollout, old


def _parses(monkeypatch):
    """-> each log the report parses, by path, in the order it parses them."""
    parsed = []
    for name in ("claude_file", "codex_file"):
        monkeypatch.setattr(activity, name, lambda path, *args, read=getattr(activity, name):
                            parsed.append(path) or read(path, *args))
    return parsed


def _logged():
    """The daemon log's lines, each without its time."""
    try:
        lines = Path(sidebar.STATUS_DIR, "daemon.log").read_text().splitlines()
    except FileNotFoundError:
        return []
    return [line[len("2026-11-05 12:00:00 "):] for line in lines]


def test_a_daemon_started_again_reads_no_log_the_last_one_read_while_it_is_as_it_was(tmp_path, monkeypatch):
    """The first open after a restart is as quick as a later one: the daemon keeps each log's
    figures in the status folder, against the log's size and mtime, so a change that keeps both
    shows only once the log grows, as it does within one daemon's life. It reads that file at its
    first open, never as it starts, and once."""
    conversation, subagent, rollout, _ = _logs_written_now(tmp_path, monkeypatch)
    parsed = _parses(monkeypatch)
    started = sidebar.Bridge(None, None)
    first = sidebar.Bridge(None, None).read_activity(2)
    assert sorted(parsed) == sorted(map(str, (conversation, subagent, rollout)))

    written = os.stat(conversation)
    conversation.write_text(conversation.read_text().replace('"output_tokens": 40', '"output_tokens": 90'))
    os.utime(conversation, ns=(written.st_atime_ns, written.st_mtime_ns))
    parsed.clear()
    again = started.read_activity(2)
    assert parsed == []
    assert [(day["claude"], day["codex"]) for day in again["days"] if day["claude"] or day["codex"]] == [(
        [{"project": "/work/app", "scratch": False, "entrypoint": "cli", "conversations": 1, "prompts": 1,
          "tokens": _tokens(input=2, output=47, cache_read=900)}],
        [{"project": "/work/app", "scratch": False, "originator": "codex_exec", "rollouts": 1, "turns": 1,
          "tokens": _codex_tokens(input=30, cached_input=10, output=3, reasoning_output=1)}])]
    assert again["conversations"] == [
        {"session_id": CONVERSATION, "project": "/work/app", "cost_usd": 0.5, "started": NOW,
         "models": {"claude-opus-4-5": {"input": 2, "output": 40, "cache_read": 900, "cache_write": 0,
                                        "cost_usd": 0.5}}}]
    assert dict(again, generated_at=None) == dict(first, generated_at=None)

    Path(sidebar.STATUS_DIR, "activity.json").unlink()
    started.read_activity(2)
    assert parsed == []


def _spoil_cell(kept, conversation, day):
    """The conversation's one Claude cell of the day, with a token count gone."""
    kept["files"][conversation]["figures"]["days"][day][0][3].pop()
    return json.dumps(kept)


@pytest.mark.parametrize("spoil, reason", [
    (lambda kept, conversation, day: json.dumps(dict(kept, format=2)), "format 2, where this daemon reads 1"),
    (lambda kept, conversation, day: json.dumps(dict(kept, parse="0" * 64)), "made by another activity.py"),
    (lambda kept, conversation, day: json.dumps(dict(kept, zone=["XST", "XDT", 3600, 7200])),
     "made in time zone ['XST', 'XDT', 3600, 7200], where this daemon is in ['UTC', 'UTC', 0, 0]"),
    (lambda kept, conversation, day: "", "not JSON: Expecting value: line 1 column 1 (char 0)"),
    (lambda kept, conversation, day: "[" * 100_000,
     "not JSON: maximum recursion depth exceeded while decoding a JSON array from a unicode string"),
    (_spoil_cell, "files[{conversation!r}].figures.days[{day!r}][0] is ['/work/app', 'cli', 1, [2, 40, 900]]"),
], ids=["format", "parse", "zone", "empty", "deep", "shape"])
def test_kept_figures_of_another_version_or_zone_or_spoiled_are_not_used_and_the_log_says_why_once(
        tmp_path, monkeypatch, utc, spoil, reason):
    """Figures another activity.py made, or made in another time zone, may count differently, so
    the daemon reads every log again rather than trust them, and so for a file it cannot parse
    whole: it is a cache, so starting cold is the recovery, and the log says once why."""
    conversation, subagent, rollout, _ = _logs_written_now(tmp_path, monkeypatch)
    sidebar.Bridge(None, None).read_activity(2)
    kept = Path(sidebar.STATUS_DIR, "activity.json")
    day = datetime.datetime.now(UTC).date().isoformat()
    kept.write_text(spoil(json.loads(kept.read_text()), str(conversation), day))
    parsed = _parses(monkeypatch)
    bridge = sidebar.Bridge(None, None)
    bridge.read_activity(2)
    bridge.read_activity(2)
    assert sorted(parsed) == sorted(map(str, (conversation, subagent, rollout)))
    assert _logged() == [f"activity: {kept} not used, {reason.format(conversation=str(conversation), day=day)};"
                         f" reading every log again"]

    parsed.clear()
    sidebar.Bridge(None, None).read_activity(2)
    assert (parsed, len(_logged())) == ([], 1)


def test_the_kept_file_is_its_owners_alone_holds_the_windows_logs_and_is_written_when_a_read_moves_it(
        tmp_path, monkeypatch):
    """Written only after a read that changed what is kept, as a file renamed over the last one;
    a log that falls out of the window leaves it, as it leaves the daemon's memory."""
    conversation, subagent, rollout, old = _logs_written_now(tmp_path, monkeypatch)
    bridge = sidebar.Bridge(None, None)
    bridge.read_activity(30)
    kept = Path(sidebar.STATUS_DIR, "activity.json")
    assert stat.S_IMODE(os.stat(kept).st_mode) == 0o600
    assert sorted(json.loads(kept.read_text())["files"]) == sorted(map(str, (conversation, subagent, rollout, old)))
    written = os.stat(kept).st_ino

    bridge.read_activity(30)
    assert os.stat(kept).st_ino == written
    bridge.read_activity(2)
    assert os.stat(kept).st_ino != written
    assert sorted(json.loads(kept.read_text())["files"]) == sorted(map(str, (conversation, subagent, rollout)))
