#!/usr/bin/env python3.10
# ABOUTME: Codex CLI rate limits for the Agents panel, read from Codex's own session logs.
# ABOUTME: Local files only: no network, and Codex's login is never touched.
"""Codex records its limits in every `token_count` event of a rollout log."""
import json
import os

from accounts import DAY_SECONDS, pace

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


def _window(raw, now):
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
    # The even-spend mark only means something for windows of a day or more.
    even = (pace(float(used), resets_at, now, window=seconds)
            if resets_at is not None and seconds >= DAY_SECONDS else None)
    return {"label": _label(minutes), "used": float(used), "resets_at": resets_at, "minutes": minutes,
            "pace": even}


def _rate_limits(line):
    try:
        event = json.loads(line)
    except ValueError:
        return None
    payload = event.get("payload") if isinstance(event, dict) else None
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    return limits if isinstance(limits, dict) else None


def limits_from_lines(lines, now):
    """The last limits reading among a rollout's lines, or None when it has none.

    Returns {"windows": [...]}, shortest window first, each {label, used,
    resets_at, minutes, pace}, with pace worked out as for account meters. A window whose reset time has passed reads as empty.
    """
    for line in reversed(list(lines)):
        limits = _rate_limits(line)
        if limits is None:
            continue
        windows = [w for w in (_window(limits.get(k), now) for k in ("primary", "secondary")) if w]
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
    with open(path, "rb") as f:
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
