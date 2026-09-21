#!/usr/bin/env python3.10
# ABOUTME: Codex CLI rate limits for the Agents panel, read from Codex's own session logs.
# ABOUTME: Local files only: no network, and Codex's login is never touched.
"""Codex records its limits in every `token_count` event of a rollout log."""
import json
import os
import stat

from accounts import DAY_SECONDS, _epoch, pace

SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
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


def limits_from_lines(lines, now):
    """The last limits reading among a rollout's lines, or None when it has none.

    Returns {"windows": [...]}, shortest window first, each {label, used,
    resets_at, minutes, pace}, with pace worked out as for account meters. A window whose reset time has passed reads as empty.
    """
    for line in reversed(list(lines)):
        reading = _rate_limits(line)
        if reading is None:
            continue
        limits, written_at = reading
        # An event without a stamp is taken as fresh; there is nothing better to say.
        read_at = written_at if written_at is not None else now
        windows = [w for w in (_window(limits.get(k), now, read_at) for k in ("primary", "secondary")) if w]
        if windows:
            return {"windows": sorted(windows, key=lambda w: w["minutes"])}
    return None


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


def _tail_lines(path):
    # Opened without blocking and checked once open: a pipe would otherwise
    # hold the read until a writer came, and a check before the open can be
    # raced.
    with open(os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise OSError(f"{path} is not a regular file")
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - TAIL_BYTES))
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
