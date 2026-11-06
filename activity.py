#!/usr/bin/env python3.10
# ABOUTME: The activity report: per day, project and provider, what Claude Code and Codex did, from their own logs.
# ABOUTME: Local files only; a file's figures are kept on disk against its size and mtime, so only a changed one is read again.
"""Claude Code writes a transcript per conversation under ~/.claude/projects;
every line carries when it was written and the directory it ran in, and a
reply carries its token usage. Codex writes a rollout per thread under
~/.codex/sessions, with its running token totals. Days are this machine's
days, from each line's own time, never from when the file was last written."""
import datetime
import hashlib
import json
import os
import re
import time
from pathlib import Path

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
#: The window the report covers when none is asked for, and the longest it will, in days.
DAYS = 7
MOST_DAYS = 30
CONVERSATION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: The report's name for each count in a Claude reply's usage, and Claude's own.
CLAUDE_TOKENS = (("input", "input_tokens"), ("output", "output_tokens"),
                 ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))
#: The same for a model's line in a Claude cost-state.
COST_TOKENS = (("input", "inputTokens"), ("output", "outputTokens"),
               ("cache_read", "cacheReadInputTokens"), ("cache_write", "cacheCreationInputTokens"))
#: The same for a Codex token_count total; cached tokens are inside input, reasoning inside output.
CODEX_TOKENS = (("input", "input_tokens"), ("cached_input", "cached_input_tokens"), ("output", "output_tokens"),
                ("reasoning_output", "reasoning_output_tokens"), ("total", "total_tokens"))


def _local_day(stamp, tz):
    """An ISO 8601 time with its offset, as Claude Code and Codex write it -> the day it fell
    on in `tz`, or in this machine's time when `tz` is None, as YYYY-MM-DD."""
    if not isinstance(stamp, str):
        raise ValueError(f"no time: {stamp!r}")
    # Python 3.10, which runs the daemon, reads no "Z".
    moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"a time with no offset: {stamp!r}")
    return moment.astimezone(tz).date().isoformat()


#: Where Claude Code puts a subagent's worktree inside the checkout it came from.
WORKTREES = "/.claude/worktrees/"


def _project(cwd):
    """The directory a line ran in -> the project its work counts to: a worktree, or a
    directory inside one, is the checkout's."""
    if not isinstance(cwd, str):
        return None
    return cwd.split(WORKTREES, 1)[0] if WORKTREES in cwd else cwd


#: Where a throwaway run does its work: the system's temporary roots, by either of the names
#: macOS gives them.
SCRATCH_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _scratch(project):
    """Whether a project is a scratch dir: one of the temporary roots, or a folder under one."""
    return project is not None and any(project == root or project.startswith(root + "/") for root in SCRATCH_ROOTS)


def _count(value):
    """A token count as written: a whole number, or nothing for none of that kind."""
    if value is None:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"not a token count: {value!r}")
    return value


def _plus(counts, more):
    return [have + extra for have, extra in zip(counts, more)]


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    return value


def _cost(row):
    """A cost-state line -> {"cost_usd", "started", "models"}; ValueError when it is not one."""
    models = row.get("modelUsage")
    if not isinstance(models, dict) or not all(isinstance(m, dict) for m in models.values()):
        raise ValueError("no modelUsage")
    return {"cost_usd": _number(row.get("totalCostUSD")),
            # Milliseconds.
            "started": int(_number(row.get("startTime")) // 1000),
            "models": {model: dict({name: _count(usage.get(raw)) for name, raw in COST_TOKENS},
                                   cost_usd=_number(usage.get("costUSD")))
                       for model, usage in models.items()}}


def _plain_prompt(row):
    """Whether a user line from before Claude Code marked prompts is one: plain text, where a
    command, a hook's text and a tool's result start with "<", are isMeta, or are not text."""
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return (isinstance(content, str) and bool(content.strip()) and not content.lstrip().startswith("<")
            and not row.get("isMeta"))


def _unreadable(bad):
    """The problem a file's unreadable lines make, by their numbers, or none."""
    if not bad:
        return []
    if len(bad) == 1:
        return [f"line {bad[0]} cannot be read"]
    return [f"{len(bad)} lines cannot be read, the first line {bad[0]}"]


def _rows(path, bad):
    """(line number, object) for each line of a JSON Lines file. A line that is not an
    object goes into `bad`, by number, except an unfinished last line: its writer is still
    writing it, and the next read takes it whole."""
    with open(path, "rb") as f:
        for number, line in enumerate(f, 1):
            if line.isspace():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                if line.endswith(b"\n"):
                    bad.append(number)
                continue
            if isinstance(row, dict):
                yield number, row
            else:
                bad.append(number)


def claude_file(path, subagent, tz=None):
    """One transcript -> {"days": {day: {(project, entrypoint): {"prompts", "tokens"}}}, "cost", "problems": [text]}.

    A reply is written once per content block with the whole reply's usage on
    each line, so its usage counts once, by its message id. A prompt is a line
    whose turnOrigin is "human". A transcript with no turnOrigin on any line
    is from before Claude Code wrote one, and its prompts are judged by their
    text; in one that has it, an untagged line continues a turn. A subagent's
    transcript (`subagent`) has replies and no prompts: its task is the
    model's text.

    `cost` is the conversation's from its last cost-state line, which Claude
    Code rewrites as the cost grows, with the project of its first line; None
    when it has none.
    """
    days, seen, bad = {}, set(), []
    tagged, plain = False, []
    cost, first = None, None
    for number, row in _rows(path, bad):
        kind = row.get("type")
        if kind == "cost-state" and not subagent:
            cost = (number, row)
            continue
        if kind not in ("user", "assistant"):
            continue
        try:
            day = _local_day(row.get("timestamp"), tz)
            usage = None
            if kind == "assistant":
                message = row.get("message") if isinstance(row.get("message"), dict) else {}
                ident = message.get("id") or row.get("uuid")
                if isinstance(message.get("usage"), dict) and ident not in seen:
                    seen.add(ident)
                    usage = [_count(message["usage"].get(raw)) for _, raw in CLAUDE_TOKENS]
        except ValueError:
            bad.append(number)
            continue
        key = (_project(row.get("cwd")), row.get("entrypoint"))
        if first is None:
            first = key[0]
        cell = days.setdefault(day, {}).setdefault(key, {"prompts": 0, "tokens": [0] * len(CLAUDE_TOKENS)})
        if kind == "user" and not subagent:
            if "turnOrigin" in row:
                tagged = True
                cell["prompts"] += row["turnOrigin"] == "human"
            elif _plain_prompt(row):
                plain.append(cell)
        if usage:
            cell["tokens"] = _plus(cell["tokens"], usage)
    if not tagged:
        for cell in plain:
            cell["prompts"] += 1
    if cost:
        try:
            cost = dict(project=first, **_cost(cost[1]))
        except ValueError:
            bad.append(cost[0])
            cost = None
    return {"days": days, "cost": cost, "problems": _unreadable(sorted(bad))}


def codex_file(path, tz=None):
    """One rollout -> {"project", "originator", "days": {day: {"turns", "tokens"}}, "problems": [text]}.

    The first session_meta is the rollout's own; one after it describes the
    thread it was forked from. A turn is a task_started event. Codex writes
    running totals, so a day's tokens are how far they rose between the
    previous token_count and each of that day's. Totals that fall mean the
    counter started again, and count from zero there.
    """
    meta, days, bad, last, fell = None, {}, [], None, None
    for number, row in _rows(path, bad):
        kind, payload = row.get("type"), row.get("payload")
        if kind == "session_meta":
            if meta is None and isinstance(payload, dict):
                meta = payload
            continue
        event = payload.get("type") if kind == "event_msg" and isinstance(payload, dict) else None
        try:
            day = _local_day(row.get("timestamp"), tz)
            info = payload.get("info") if event == "token_count" else None
            totals = (info.get("total_token_usage") if isinstance(info, dict) else None)
            totals = [_count(totals.get(raw)) for _, raw in CODEX_TOKENS] if isinstance(totals, dict) else None
        except ValueError:
            bad.append(number)
            continue
        cell = days.setdefault(day, {"turns": 0, "tokens": [0] * len(CODEX_TOKENS)})
        cell["turns"] += event == "task_started"
        if totals:
            if last and any(total < was for total, was in zip(totals, last)):
                fell, last = fell or number, None
            cell["tokens"] = _plus(cell["tokens"], [total - was for total, was in
                                                    zip(totals, last or [0] * len(CODEX_TOKENS))])
            last = totals
    problems = _unreadable(bad) + ([f"its token totals fell at line {fell}"] if fell else [])
    if meta is None:
        # Nothing to count against; an empty rollout has merely not begun.
        return {"project": None, "originator": None, "days": {},
                "problems": problems + (["no session_meta line"] if days else [])}
    return {"project": _project(meta.get("cwd")), "originator": meta.get("originator"), "days": days,
            "problems": problems}


def _codex_files(sessions_dir):
    """Every rollout under Codex's sessions folder, whichever day's folder it started in."""
    for where, _, names in os.walk(sessions_dir):
        for name in names:
            if name.startswith("rollout-") and name.endswith(".jsonl"):
                yield os.path.join(where, name)


def _claude_files(projects_dir, unread):
    """(path, conversation, subagent) of every transcript Claude Code keeps: a conversation's
    own, and its subagents' under <conversation>/subagents/, a workflow's one level further
    down. A subagent's line can carry a session id of its own, so its conversation is the
    folder it is in. A project folder that cannot be listed goes into `unread`."""
    try:
        folders = list(os.scandir(projects_dir))
    except FileNotFoundError:
        return
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            entries = list(os.scandir(folder.path))
        except OSError as failure:
            unread.append({"path": folder.path, "error": str(failure)})
            continue
        for entry in entries:
            stem, ext = os.path.splitext(entry.name)
            if ext == ".jsonl" and CONVERSATION.fullmatch(stem) and entry.is_file():
                yield entry.path, stem, False
            elif CONVERSATION.fullmatch(entry.name) and entry.is_dir():
                for where, _, names in os.walk(os.path.join(entry.path, "subagents")):
                    for name in names:
                        if name.startswith("agent-") and name.endswith(".jsonl"):
                            yield os.path.join(where, name), entry.name, True


def _figures(path, kind, read, start, cache, kept):
    """A file's figures: from `cache` while its size and mtime are what they were read at, by the
    reader of its `kind`, else `read(path)`, and either way into `kept`. None for a file last
    written before `start`, which has nothing in the window. Raises OSError when the file cannot
    be read."""
    # Stat before reading: a write after the read then shows as a change next time.
    stat = os.stat(path)
    if stat.st_mtime < start:
        return None
    key = (kind, stat.st_size, stat.st_mtime_ns)
    held = cache.get(path)
    figures = held[1] if held and held[0] == key else read(path)
    kept[path] = (key, figures)
    return figures


def _window(days, now, tz):
    """The window's days, newest first, as YYYY-MM-DD, and when its first one began."""
    today = datetime.datetime.fromtimestamp(now, tz).date()
    dates = [today - datetime.timedelta(days=back) for back in range(days)]
    # With no tz the midnight is naive, which timestamp() reads as this machine's.
    start = datetime.datetime.combine(dates[-1], datetime.time.min, tzinfo=tz)
    return [d.isoformat() for d in dates], start.timestamp()


def report(projects_dir, sessions_dir, days, now, cache, tz=None):
    """The activity of the last `days` days, newest first; see docs/development.md.

    `cache` is a dict the caller keeps between reports: each file's figures,
    against the reader ("claude" or "codex"), size and mtime they were read
    at. It keeps only the files of the last window.
    """
    dates, start = _window(days, now, tz)
    claude = {date: {} for date in dates}
    codex = {date: {} for date in dates}
    unread, kept, costs = [], {}, []
    for path, conversation, subagent in _claude_files(projects_dir, unread):
        try:
            figures = _figures(path, "claude", lambda p: claude_file(p, subagent, tz), start, cache, kept)
        except OSError as failure:
            unread.append({"path": path, "error": str(failure)})
            continue
        if figures is None:
            continue
        unread += [{"path": path, "error": problem} for problem in figures["problems"]]
        if figures["cost"] and any(day in claude for day in figures["days"]):
            costs.append(dict(session_id=conversation, **figures["cost"]))
        for day, cells in figures["days"].items():
            if day not in claude:
                continue
            for key, cell in cells.items():
                merged = claude[day].setdefault(key, {"conversations": set(), "prompts": 0,
                                                     "tokens": [0] * len(CLAUDE_TOKENS)})
                merged["conversations"].add(conversation)
                merged["prompts"] += cell["prompts"]
                merged["tokens"] = _plus(merged["tokens"], cell["tokens"])
    for path in _codex_files(sessions_dir):
        try:
            figures = _figures(path, "codex", lambda p: codex_file(p, tz), start, cache, kept)
        except OSError as failure:
            unread.append({"path": path, "error": str(failure)})
            continue
        if figures is None:
            continue
        unread += [{"path": path, "error": problem} for problem in figures["problems"]]
        for day, cell in figures["days"].items():
            if day not in codex:
                continue
            merged = codex[day].setdefault((figures["project"], figures["originator"]),
                                           {"rollouts": 0, "turns": 0, "tokens": [0] * len(CODEX_TOKENS)})
            merged["rollouts"] += 1
            merged["turns"] += cell["turns"]
            merged["tokens"] = _plus(merged["tokens"], cell["tokens"])
    cache.clear()
    cache.update(kept)
    out = []
    for date in dates:
        rows = [{"project": where, "scratch": _scratch(where), "entrypoint": entrypoint,
                 "conversations": len(cell["conversations"]),
                 "prompts": cell["prompts"],
                 "tokens": {name: n for (name, _), n in zip(CLAUDE_TOKENS, cell["tokens"])}}
                for (where, entrypoint), cell in claude[date].items()]
        rows.sort(key=lambda r: (-sum(r["tokens"].values()), r["project"] or "", r["entrypoint"] or ""))
        threads = [{"project": where, "scratch": _scratch(where), "originator": originator,
                    "rollouts": cell["rollouts"], "turns": cell["turns"],
                    "tokens": {name: n for (name, _), n in zip(CODEX_TOKENS, cell["tokens"])}}
                   for (where, originator), cell in codex[date].items()]
        threads.sort(key=lambda r: (-r["tokens"]["total"], r["project"] or "", r["originator"] or ""))
        out.append({"date": date, "claude": rows, "codex": threads})
    unread.sort(key=lambda u: u["path"])
    costs.sort(key=lambda c: (-c["cost_usd"], c["session_id"]))
    return {"generated_at": int(now), "days": out, "conversations": costs, "unread": unread}


#: The kept file's layout; a file in any other is not read.
KEPT_FORMAT = 1
#: What made the kept figures: this file's own text, hashed. Any edit to the parsers or to the
#: shapes they return can change what a kept entry means, and a hash cannot be forgotten the
#: way a number to raise by hand can. Read as the module loads, so it is the text this process
#: runs even after an update rewrites the file and before the daemon restarts.
PARSE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SCALAR = (str, int, float, bool, type(None))
_MODEL_KEYS = {name for name, _ in COST_TOKENS} | {"cost_usd"}


def local_zone():
    """This machine's time zone, which a report with no tz cuts its days in: its names, and its
    offsets west of UTC standard and in summer, as this process read them."""
    return [*time.tzname, time.timezone, time.altzone]


def kept(cache, zone):
    """`cache` as report() leaves it, its days cut in `zone` -> the kept file's content, for JSON.
    parse_kept reads it back."""
    files = {}
    for path, ((kind, size, mtime_ns), figures) in cache.items():
        if kind == "claude":
            # A day's cells are keyed by (project, entrypoint); JSON keys are text alone.
            figures = dict(figures, days={day: [[*where, cell["prompts"], cell["tokens"]] for where, cell in cells.items()]
                                          for day, cells in figures["days"].items()})
        files[path] = {"kind": kind, "size": size, "mtime_ns": mtime_ns, "figures": figures}
    return {"format": KEPT_FORMAT, "parse": PARSE, "zone": zone, "files": files}


def _check(ok, where, value):
    """ValueError naming the part of the kept file and its value, unless `ok`."""
    if not ok:
        shown = repr(value)
        raise ValueError(f"{where} is {shown if len(shown) <= 120 else shown[:119] + '…'}")


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_counts(value, n):
    return isinstance(value, list) and len(value) == n and all(_is_count(v) for v in value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_place(value):
    return value is None or isinstance(value, str)


def _is_problems(value):
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _claude_figures(raw, where):
    """A kept transcript's figures -> them as claude_file returns them."""
    _check(isinstance(raw, dict) and set(raw) == {"days", "cost", "problems"} and isinstance(raw["days"], dict),
           where, raw)
    days = {}
    for day, cells in raw["days"].items():
        _check(_DAY.fullmatch(day) and isinstance(cells, list), f"{where}.days[{day!r}]", cells)
        days[day] = {}
        for n, cell in enumerate(cells):
            _check(isinstance(cell, list) and len(cell) == 4 and _is_place(cell[0]) and isinstance(cell[1], _SCALAR)
                   and _is_count(cell[2]) and _is_counts(cell[3], len(CLAUDE_TOKENS))
                   and (cell[0], cell[1]) not in days[day], f"{where}.days[{day!r}][{n}]", cell)
            days[day][(cell[0], cell[1])] = {"prompts": cell[2], "tokens": cell[3]}
    cost = raw["cost"]
    if cost is not None:
        _check(isinstance(cost, dict) and set(cost) == {"project", "cost_usd", "started", "models"}
               and _is_place(cost["project"]) and _is_number(cost["cost_usd"])
               and isinstance(cost["started"], int) and not isinstance(cost["started"], bool)
               and isinstance(cost["models"], dict), f"{where}.cost", cost)
        for model, usage in cost["models"].items():
            _check(isinstance(usage, dict) and set(usage) == _MODEL_KEYS and _is_number(usage["cost_usd"])
                   and all(_is_count(usage[name]) for name, _ in COST_TOKENS), f"{where}.cost.models[{model!r}]", usage)
    _check(_is_problems(raw["problems"]), f"{where}.problems", raw["problems"])
    return {"days": days, "cost": cost, "problems": raw["problems"]}


def _codex_figures(raw, where):
    """A kept rollout's figures, which are as codex_file returns them."""
    _check(isinstance(raw, dict) and set(raw) == {"project", "originator", "days", "problems"}
           and _is_place(raw["project"]) and isinstance(raw["originator"], _SCALAR) and isinstance(raw["days"], dict),
           where, raw)
    for day, cell in raw["days"].items():
        _check(_DAY.fullmatch(day) and isinstance(cell, dict) and set(cell) == {"turns", "tokens"}
               and _is_count(cell["turns"]) and _is_counts(cell["tokens"], len(CODEX_TOKENS)),
               f"{where}.days[{day!r}]", cell)
    _check(_is_problems(raw["problems"]), f"{where}.problems", raw["problems"])
    return raw


_FIGURES = {"claude": _claude_figures, "codex": _codex_figures}


def parse_kept(data, zone):
    """The kept file's bytes -> a cache for report(), its days cut in `zone`. ValueError saying why
    for a file another format, another activity.py or another time zone made, and for one that is
    not wholly the shape kept() writes."""
    try:
        saved = json.loads(data)
    # RecursionError: nesting deeper than the decoder goes.
    except (ValueError, RecursionError) as failure:
        raise ValueError(f"not JSON: {failure}") from None
    _check(isinstance(saved, dict), "the file", saved)
    if not (_is_count(saved.get("format")) and saved["format"] == KEPT_FORMAT):
        raise ValueError(f"format {saved.get('format')!r}, where this daemon reads {KEPT_FORMAT}")
    if saved.get("parse") != PARSE:
        raise ValueError("made by another activity.py")
    if saved.get("zone") != zone:
        raise ValueError(f"made in time zone {saved.get('zone')!r}, where this daemon is in {zone!r}")
    _check(set(saved) == {"format", "parse", "zone", "files"} and isinstance(saved["files"], dict),
           "the file", saved)
    cache = {}
    for path, entry in saved["files"].items():
        where = f"files[{path!r}]"
        _check(isinstance(entry, dict) and set(entry) == {"kind", "size", "mtime_ns", "figures"}
               and isinstance(entry["kind"], str) and entry["kind"] in _FIGURES
               and _is_count(entry["size"]) and _is_count(entry["mtime_ns"]), where, entry)
        cache[path] = ((entry["kind"], entry["size"], entry["mtime_ns"]),
                       _FIGURES[entry["kind"]](entry["figures"], f"{where}.figures"))
    return cache
