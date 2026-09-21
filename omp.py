#!/usr/bin/env python3.10
# ABOUTME: What an omp session says about itself, for its card in the Agents panel.
# ABOUTME: Local files only: omp's own session log, found through the terminal it runs on.
"""omp files each session as a JSONL log and notes, per terminal, which log
the omp on that terminal is writing."""
import datetime
import json
import math
import os
import re
import sqlite3
import stat

#: One file per terminal omp has run on, named after the tty: the directory it
#: started in, the session log, and a stat of that directory, a line each. omp
#: never removes one, so it speaks only for a terminal with a live omp on it.
TERMINALS_DIR = os.path.expanduser("~/.omp/agent/terminal-sessions")
#: omp's cache of every provider's model list: a row per provider, its models
#: a JSON array, each naming its `provider`, `id` and `contextWindow`.
MODELS_DB = os.path.expanduser("~/.omp/agent/models.db")
_TTY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


def _open(path):
    # Opened without blocking and checked once open: a pipe would otherwise
    # hold the read until a writer came, and a check before the open can be
    # raced.
    f = open(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb")
    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
        f.close()
        raise OSError(f"{path} is not a regular file")
    return f


def _read(path, limit):
    with _open(path) as f:
        return f.read(limit).decode("utf-8", errors="replace")


def _read_from(path, offset):
    """A file's whole lines from `offset` on, and where the next reading starts.

    A last line omp is still writing is left for that next reading. A file
    shorter than `offset` is a different file under the same name, and is
    read from its top.
    """
    with _open(path) as f:
        if os.fstat(f.fileno()).st_size < offset:
            offset = 0
        f.seek(offset)
        data = f.read()
    whole = data[:data.rfind(b"\n") + 1]
    return whole.decode("utf-8", errors="replace").splitlines(), offset + len(whole), offset


def session_file(terminals_dir, tty):
    """The session log of the omp on a terminal (`ttys008`, `/dev/ttys008`), or None.

    omp names the file after the device with its slashes as dashes.
    """
    if not isinstance(tty, str):
        return None
    tty = tty.removeprefix("/dev/").replace("/", "-")
    if not _TTY.match(tty):
        return None
    try:
        lines = _read(os.path.join(terminals_dir, tty), 64 * 1024).splitlines()
    except OSError:
        return None
    return lines[1] if len(lines) > 1 and lines[1].endswith(".jsonl") else None


def _text(value):
    return value if isinstance(value, str) and value else None


def _epoch(stamp):
    """An entry's `timestamp` (2026-09-21T12:18:43.470Z) as seconds, or None."""
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _note_agents(facts, entry, message, told):
    """What a tool result says of the subagents omp has spawned.

    A `task` result lists every subagent it spawned under `progress`, while
    its `async` names the first alone. `facts["agents"]` is {subagent id:
    what is known of it}, in the order they were spawned.
    """
    if message.get("toolName") != "task" or not isinstance(told.get("progress"), list):
        return
    for spawned in told["progress"]:
        if isinstance(spawned, dict) and _text(spawned.get("id")):
            facts["agents"][spawned["id"]] = {
                "id": spawned["id"], "type": _text(spawned.get("agent")), "since": _epoch(entry.get("timestamp")),
                "ended": None, "model": None, "effort": None}


def _ended(agent, now):
    # An end with no time to it is still an end: a subagent left without one
    # would read as running for good.
    return now if now is not None else agent["since"] or 0


def _note_hub_agent(facts, job, now):
    """What the hub says of one subagent: its model, and whether it still runs.

    The hub gives how long a job has run, which dates one no `task` result
    was seen for. The model comes as `provider/model`.
    """
    ran = job.get("durationMs")
    began = now - ran / 1000 if now is not None and isinstance(ran, (int, float)) and not isinstance(ran, bool) else None
    agent = facts["agents"].setdefault(job["id"], {"id": job["id"], "type": None, "since": began, "ended": None,
                                                   "model": None, "effort": None})
    agent["model"] = (_text(job.get("resolvedModelIdentity")) or "").partition("/")[2] or agent["model"]
    agent["effort"] = _text(job.get("resolvedThinkingLevel")) or agent["effort"]
    if job.get("status") in ("completed", "failed", "cancelled") and agent["ended"] is None:
        agent["ended"] = _ended(agent, now)


def _note_jobs(facts, entry):
    """What one log entry says of the commands omp has running in the background.

    A bash result says a job started, under the command its call gave; omp's
    hub lists jobs with a status each; an `async-result` message names the
    ones that ended. `facts["jobs"]` is {job id: command} for those running.
    """
    kind, message = entry.get("type"), entry.get("message")
    data, details = entry.get("data"), entry.get("details")
    if kind == "custom" and entry.get("customType") == "tool_execution_start" and isinstance(data, dict):
        args = data.get("args")
        call, command = _text(data.get("toolCallId")), _text(args.get("command") if isinstance(args, dict) else None)
        if data.get("toolName") == "bash" and call and command:
            facts["commands"][call] = command
    elif kind == "message" and isinstance(message, dict) and message.get("role") == "toolResult":
        command = facts["commands"].pop(message.get("toolCallId"), None) \
            if isinstance(message.get("toolCallId"), str) else None
        told = message.get("details") if isinstance(message.get("details"), dict) else {}
        _note_agents(facts, entry, message, told)
        started = told.get("async")
        if isinstance(started, dict) and started.get("state") == "running" and _text(started.get("jobId")) \
                and started.get("type") != "task":
            facts["jobs"][started["jobId"]] = command or started["jobId"]
        for job in told["jobs"] if message.get("toolName") == "hub" and isinstance(told.get("jobs"), list) else []:
            if not isinstance(job, dict) or not _text(job.get("id")):
                continue
            if job.get("type") == "task":
                _note_hub_agent(facts, job, _epoch(entry.get("timestamp")))
            elif job.get("status") == "running":
                facts["jobs"].setdefault(job["id"], _text(job.get("label")) or job["id"])
            else:
                facts["jobs"].pop(job["id"], None)
    elif kind == "custom_message" and entry.get("customType") == "async-result" and isinstance(details, dict):
        for job in details["jobs"] if isinstance(details.get("jobs"), list) else []:
            if isinstance(job, dict) and isinstance(job.get("jobId"), str):
                facts["jobs"].pop(job["jobId"], None)
                agent = facts["agents"].get(job["jobId"])
                if agent and agent["ended"] is None:
                    agent["ended"] = _ended(agent, _epoch(entry.get("timestamp")))


def fold(facts, lines):
    """What a session's log lines add to what is known of it.

    Every answer adds its price, and every tool omp starts states its
    intent, the line omp shows above its own status bar. Commands sent to
    the background are followed until they end. The model is whichever answered last, or the one chosen since: omp notes a
    choice as `provider/model`, and one made for another role (a small model
    for titles, say) is not the session's.
    """
    facts = dict(facts, jobs=dict(facts["jobs"]), commands=dict(facts["commands"]),
                 agents={name: dict(agent) for name, agent in facts["agents"].items()})
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind, message = entry.get("type"), entry.get("message")
        _note_jobs(facts, entry)
        if kind == "message" and isinstance(message, dict) and message.get("role") == "user" \
                and not message.get("steering"):
            # A finished subagent stays in sight until the next prompt; a
            # word said to omp mid-turn is marked as steering, and is none.
            facts["agents"] = {name: agent for name, agent in facts["agents"].items() if agent["ended"] is None}
        elif kind == "message" and isinstance(message, dict) and message.get("role") == "assistant":
            if _text(message.get("model")):
                facts["model"], facts["provider"] = message["model"], _text(message.get("provider"))
            snapshot = message.get("contextSnapshot")
            tokens = snapshot.get("promptTokens") if isinstance(snapshot, dict) else None
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                facts["prompt_tokens"] = tokens
            usage = message.get("usage")
            price = usage.get("cost") if isinstance(usage, dict) else None
            total = price.get("total") if isinstance(price, dict) else None
            if isinstance(total, (int, float)) and not isinstance(total, bool) \
                    and math.isfinite(total) and total >= 0:
                facts["cost"] = (facts["cost"] or 0) + total
        elif kind == "custom" and entry.get("customType") == "tool_execution_start":
            data = entry.get("data")
            facts["doing"] = _text(data.get("intent") if isinstance(data, dict) else None) or facts["doing"]
        elif kind == "model_change" and entry.get("role") in (None, "default"):
            provider, slash, model = (_text(entry.get("model")) or "").partition("/")
            if slash and model:
                facts["model"], facts["provider"] = model, provider
        elif kind == "thinking_level_change":
            facts["effort"] = _text(entry.get("thinkingLevel")) or facts["effort"]
    return facts


NOTHING_KNOWN = {"model": None, "provider": None, "effort": None, "prompt_tokens": None, "cost": None,
                 "doing": None, "jobs": {}, "commands": {}, "agents": {}}
#: {session log: (where the next reading starts, what is known so far)}. A log
#: runs to megabytes and is read every rebuild, so only what omp has added
#: since is read; a terminal has one log at a time, so this stays small.
_readings = {}


#: (the cache's stamp, {(provider, model): window}). The cache runs to
#: megabytes and changes when omp refreshes a provider, not per rebuild.
_windows = (None, {})


def _stamp(path):
    # omp writes through a write-ahead log, so the newest word can be in it.
    stamps = []
    for name in (path, path + "-wal"):
        try:
            stamps.append(os.stat(name).st_mtime_ns)
        except OSError:
            stamps.append(None)
    return path, tuple(stamps)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _dearer_past(model):
    """The prompt size past which a model bills at a higher rate, or None.

    omp holds such a model under that size, so that it compacts before a
    request crosses into the dearer tier: the window it works in is the
    threshold, whatever the model could take.
    """
    cost = model.get("cost")
    tier = cost.get("longContext") if isinstance(cost, dict) else None
    return _count(tier.get("inputThreshold")) if isinstance(tier, dict) else None


def context_windows(models_db):
    """{(provider, model id): the window omp works in, in tokens} from its model cache."""
    global _windows
    stamp = _stamp(models_db)
    if _windows[0] == stamp:
        return _windows[1]
    windows = {}
    try:
        db = sqlite3.connect(f"file:{models_db}?mode=ro", uri=True, timeout=0.5)
        try:
            rows = db.execute("SELECT models FROM model_cache").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        rows = []
    for (models,) in rows:
        try:
            models = json.loads(models)
        except (ValueError, TypeError):
            continue
        for model in models if isinstance(models, list) else []:
            if not isinstance(model, dict):
                continue
            key, window = (_text(model.get("provider")), _text(model.get("id"))), _count(model.get("contextWindow"))
            if all(key) and window:
                windows[key] = min(window, _dearer_past(model) or window)
    _windows = (stamp, windows)
    return windows


def _figures(facts, models_db):
    window = context_windows(models_db).get((facts["provider"], facts["model"]))
    tokens = facts["prompt_tokens"]
    context = min(100, round(100 * tokens / window)) if window and tokens is not None else None
    cost = round(facts["cost"], 2) if facts["cost"] is not None else None
    return {"model": facts["model"], "effort": facts["effort"], "context": context, "cost": cost,
            "doing": facts["doing"]}


def _shown(facts, models_db, path=None):
    return {**_figures(facts, models_db), "jobs": list(facts["jobs"].values()),
            "agents": [_agent_shown(path, agent, models_db) for agent in facts["agents"].values()]}


def _folded(path):
    """What a log says so far, read from where the last reading stopped; None
    when it cannot be read."""
    offset, facts = _readings.get(path, (0, NOTHING_KNOWN))
    try:
        lines, end, began = _read_from(path, offset)
    except OSError:
        _readings.pop(path, None)
        return None
    facts = fold(NOTHING_KNOWN if began != offset else facts, lines)
    _readings[path] = (end, facts)
    return facts


def _agent_shown(session_path, agent, models_db):
    """A subagent with what its own log adds: omp files one beside the
    session's, `<session log minus .jsonl>/<subagent id>.jsonl`, in the
    session log's shapes. The hub's word on model and effort stands where
    the log has none."""
    own = _folded(os.path.join(session_path[:-len(".jsonl")], agent["id"] + ".jsonl")) \
        if session_path and session_path.endswith(".jsonl") and "/" not in agent["id"] else None
    figures = _figures(own, models_db) if own else _figures(NOTHING_KNOWN, models_db)
    return {**agent, "model": figures["model"] or agent["model"], "effort": figures["effort"] or agent["effort"],
            "context": figures["context"], "cost": figures["cost"], "doing": figures["doing"]}


def read_session(terminals_dir, tty, models_db=MODELS_DB):
    """The model, effort, context %, cost and background commands of the omp on a terminal; unknowns when it cannot be read.

    Context is the last prompt's tokens against the window omp's model cache
    gives that provider's model. Cost is every answer's price as omp worked
    it out, added up, in dollars to the cent.
    """
    path = session_file(terminals_dir, tty)
    facts = _folded(path) if path is not None else None
    return _shown(facts, models_db, path) if facts else _shown(NOTHING_KNOWN, models_db)
