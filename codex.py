#!/usr/bin/env python3.10
# ABOUTME: Codex CLI rate limits for the Agents panel, read from Codex's own session logs.
# ABOUTME: Local files only: no network, and Codex's login is never touched.
"""Codex records its limits in every `token_count` event of a rollout log."""
import json
import os
import sqlite3
import stat

from accounts import DAY_SECONDS, _epoch, pace

SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
#: Codex's own database, where it titles each conversation.
STATE_DB = os.path.expanduser("~/.codex/state_5.sqlite")
#: How much of a rollout's end to read; readings repeat every turn, so the last one is near the end.
TAIL_BYTES = 256 * 1024
#: Newest rollouts to look through when the newest has no reading yet.
ROLLOUTS_TO_TRY = 3


def _label(minutes):
    if minutes == 10080:
        return "Weekly"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}-day"
    if minutes % 60 == 0:
        return f"{minutes // 60}-hour"
    return f"{minutes}-min"


def _window(raw, now, read_at):
    if not isinstance(raw, dict):
        return None
    used, minutes, resets_at = raw.get("used_percent"), raw.get("window_minutes"), raw.get("resets_at")
    if not isinstance(used, (int, float)) or not isinstance(minutes, int) or minutes <= 0:
        return None
    if not isinstance(resets_at, (int, float)):
        resets_at = None
    if resets_at is not None and resets_at <= now:
        # The window has reset since Codex last reported it.
        used, resets_at = 0.0, None
    seconds = minutes * 60
    # The even-spend mark only means something for windows of a day or more,
    # and stands as of the reading, as an account meter's does: worked out at
    # the rebuild instead it would creep with the clock and change the
    # snapshot every tick.
    even = (pace(float(used), resets_at, read_at, window=seconds)
            if resets_at is not None and seconds >= DAY_SECONDS else None)
    return {"label": _label(minutes), "used": float(used), "resets_at": resets_at, "minutes": minutes,
            "pace": even}


def _rate_limits(line):
    """A rollout line -> (its rate_limits, when Codex wrote it), or None."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    payload = event.get("payload") if isinstance(event, dict) else None
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    return (limits, _epoch(event.get("timestamp"))) if isinstance(limits, dict) else None


#: The limit Codex counts an ordinary request against. Other limit_ids are
#: further allowances the server reports beside it, such as Luna Reserve.
PLAN_LIMIT = "codex"
#: What Codex itself calls the reserve's limit (tui/src/model_catalog.rs).
LIMIT_NAMES = {"gpt_reserve": "Luna Reserve"}
#: The model Codex switches to when the plan's usage is used up and it moves
#: onto Luna Reserve (tui/src/model_catalog.rs LUNA_RESERVE_MODEL). Codex
#: compares it ignoring case.
RESERVE_MODEL = "gpt-reserve"


def _turn_model(line):
    """A turn_context line's model, or None for any other line."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("type") != "turn_context":
        return None
    payload = event.get("payload")
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) else None


def _windows(limits, now, read_at):
    return sorted((w for w in (_window(limits.get(k), now, read_at) for k in ("primary", "secondary")) if w),
                  key=lambda w: w["minutes"])


def limits_from_lines(lines, now):
    """The last limits reading among a rollout's lines, or None when it has none.

    Returns {"windows": [...]}, shortest window first, each {label, used,
    resets_at, minutes, pace}, with pace worked out as for account meters. A
    window whose reset time has passed reads as empty.

    Each reading names one limit, and the plan's windows come from its last
    reading on the plan limit. Codex logs one limit per line, and when the
    server reports several the last written wins, so a reading on another
    limit says nothing about where the account stands. The account is on
    reserve when its newest turn ran on the reserve model: then the newest
    reading on another limit is returned as "reserve" {label, used,
    resets_at, minutes, pace} (issue #1 saw a reserve window drawn as the
    weekly bar, and later a reserve shown on a plan at 5%).
    """
    lines = list(lines)
    model = next((m for m in map(_turn_model, reversed(lines)) if m is not None), None)
    on_reserve = model is not None and model.lower() == RESERVE_MODEL
    reserve = None
    for line in reversed(lines):
        reading = _rate_limits(line)
        if reading is None:
            continue
        limits, written_at = reading
        # An event without a stamp is taken as fresh; there is nothing better to say.
        read_at = written_at if written_at is not None else now
        windows = _windows(limits, now, read_at)
        if not windows:
            continue
        limit_id = limits.get("limit_id") or PLAN_LIMIT
        if limit_id == PLAN_LIMIT:
            return {"windows": windows, **({"reserve": reserve} if reserve else {})}
        if on_reserve and reserve is None:
            label = limits.get("limit_name") or LIMIT_NAMES.get(limit_id) or limit_id
            reserve = {**windows[-1], "label": label}
    return {"windows": [], "reserve": reserve} if reserve else None


#: Day folders to look in; a session started days ago can still be the one writing.
DAYS_TO_SCAN = 7


def _children(path, descending=True):
    try:
        return sorted((os.path.join(path, n) for n in os.listdir(path)), reverse=descending)
    except OSError:
        return []


def newest_rollouts(sessions_dir, count=ROLLOUTS_TO_TRY):
    """The most recently written rollout logs, newest first.

    Codex files them under year/month/day; only the newest day folders are
    listed, so the cost stays flat as the archive grows.
    """
    days = [d for y in _children(sessions_dir) for m in _children(y) for d in _children(m)]
    rollouts = []
    for day in days[:DAYS_TO_SCAN]:
        for path in _children(day):
            if os.path.basename(path).startswith("rollout-") and path.endswith(".jsonl"):
                try:
                    rollouts.append((os.path.getmtime(path), path))
                except OSError:
                    continue
    return [path for _, path in sorted(rollouts, reverse=True)[:count]]


def _tail_lines(path, size=TAIL_BYTES):
    # Opened without blocking and checked once open: a pipe would otherwise
    # hold the read until a writer came, and a check before the open can be
    # raced.
    with open(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError(f"{path} is not a regular file")
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - size))
        return f.read().decode("utf-8", errors="replace").splitlines()


def read_limits(sessions_dir, now):
    """Codex's latest limits from its newest rollouts, or None when there are none to read."""
    for path in newest_rollouts(sessions_dir):
        try:
            limits = limits_from_lines(_tail_lines(path), now)
        except OSError:
            continue
        if limits is not None:
            return limits
    return None


def _event(line):
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) and isinstance(event.get("payload"), dict) else None


#: How far back the asked turn is looked for: a long turn of tool output can
#: push its opening context well past the tail the limits read.
REPLY_TAIL_BYTES = 4 * 1024 * 1024


def asked_reply(rollout_path, nonce):
    """The final agent message of the turn whose hook context carried `(link ‹nonce›)`.

    None while that turn has not completed (or cannot be found); its
    last_agent_message, "" when it had none or was interrupted, once it has.
    """
    if not rollout_path:
        return None
    try:
        lines = _tail_lines(rollout_path, REPLY_TAIL_BYTES)
    except OSError:
        return None
    mark = f"(link {nonce})"
    current = asked = None
    for line in lines:
        event = _event(line)
        if event is None:
            continue
        payload = event["payload"]
        kind = payload.get("type")
        if kind == "task_started":
            current = payload.get("turn_id")
        elif kind == "message" and payload.get("role") == "developer" and asked is None:
            parts = payload.get("content") if isinstance(payload.get("content"), list) else []
            if any(isinstance(part, dict) and mark in str(part.get("text") or "") for part in parts):
                asked = current
        elif kind == "task_complete" and asked is not None and payload.get("turn_id") == asked:
            return payload.get("last_agent_message") or ""
        elif kind == "turn_aborted" and asked is not None and payload.get("turn_id") == asked:
            # Interrupted, it has no answer: the book refuses an empty one.
            return ""
    return None


#: Tokens Codex counts as always in the window (system prompt, tools) and leaves
#: out of its context figure. Fitted to `/status`: 27371 of 258400 reads "94% left".
BASELINE_TOKENS = 12000


def context_used(tokens, window):
    """Percent of the window used, as Codex's `/status` reports it (100 minus its "% left")."""
    usable = window - BASELINE_TOKENS
    left = 100 * (usable - max(0, tokens - BASELINE_TOKENS)) / usable
    return 100 - round(max(0.0, left))


def session_from_lines(lines):
    """A running session's reasoning effort and context % from its rollout's lines.

    Effort comes from the last `turn_context`. Context is the last turn's
    tokens against the model's window, less the fixed baseline Codex leaves
    out of its own figure: `total_token_usage` adds up every turn,
    so it runs far past the window and says nothing about how full it is.
    Either is None until the rollout has reported it.
    """
    effort = context = None
    for line in reversed(list(lines)):
        event = _event(line)
        if event is None:
            continue
        payload = event["payload"]
        if effort is None and event.get("type") == "turn_context":
            effort = payload.get("effort")
        if context is None and payload.get("type") == "token_count" and isinstance(payload.get("info"), dict):
            used = (payload["info"].get("last_token_usage") or {}).get("total_tokens")
            window = payload["info"].get("model_context_window")
            if isinstance(used, int) and isinstance(window, int) and window > BASELINE_TOKENS:
                context = context_used(used, window)
        if effort is not None and context is not None:
            break
    return {"effort": effort, "context": context}


def read_session(rollout_path):
    """session_from_lines for one rollout file; unknowns when it cannot be read."""
    try:
        return session_from_lines(_tail_lines(rollout_path)) if rollout_path else session_from_lines([])
    except OSError:
        return session_from_lines([])


def thread_name(session_id, db_path=None):
    """The title Codex gave a conversation, as its status line shows it, or None.

    Read-only and short on patience: the database is Codex's, written while it
    runs, and a rebuild must not wait on its lock.
    """
    if not session_id:
        return None
    try:
        db = sqlite3.connect(f"file:{db_path or STATE_DB}?mode=ro", uri=True, timeout=0.2)
    except sqlite3.Error:
        return None
    try:
        row = db.execute("SELECT name FROM threads WHERE id = ?", (session_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        db.close()
    return row[0] if row and row[0] else None

