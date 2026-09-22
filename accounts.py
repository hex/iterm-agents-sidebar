#!/usr/bin/env python3.10
# ABOUTME: Account meters and switching for the Agents panel: usage, pace, store, switch.
# ABOUTME: Pure decisions live here beside thin IO, following sidebar.py's split.
"""Pace rules match claude-swap's, so the panel and cswap agree on a number."""
import argparse
import fcntl
import json
import os
import random
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

WEEK_SECONDS = 604800
DAY_SECONDS = 86400
AHEAD_POINTS = 15
STORE_VERSION = 1
#: Reading cadence, after cswap's measurement of the usage endpoint: about
#: thirty requests an hour per account, as a trailing window, so a burst
#: locks the account out for up to an hour. One reading every three minutes
#: at most; an account whose usage is moving stays near that, one that sits
#: still drifts out to five minutes (the active account) or ten (the rest).
POLL_FLOOR_SECONDS = 180
ACTIVE_CEILING_SECONDS = 300
OTHER_CEILING_SECONDS = 600
POLL_CEILING_SECONDS = 1800
GROWTH = 1.5
MOVEMENT_POINTS = 1.0
RESET_SLACK_SECONDS = 60
JITTER = 0.1
RATE_LIMIT_HOLD_SECONDS = 3600
REFRESH_MARGIN_SECONDS = 300
#: Claude Code's proper-lockfile staleness: credential locks, then its config lock.
CREDENTIAL_LOCK_STALE_SECONDS = 60
CONFIG_LOCK_STALE_SECONDS = 10
#: Where the panel keeps accounts, and the Keychain services it reads and writes.
STORE_PATH = os.path.expanduser("~/.config/agents-sidebar/accounts.json")
PANEL_SERVICE = "agents-sidebar-accounts"
LIVE_SERVICE = "Claude Code-credentials"


def live_item():
    """Claude Code's credential item: its service, and the account name it files it under.

    Claude Code uses $USER, falling back to the login name when that is unset.
    """
    import pwd
    return LIVE_SERVICE, os.environ.get("USER") or pwd.getpwuid(os.geteuid()).pw_name


def pace(used, resets_at, fetched_at, window=WEEK_SECONDS):
    """Where a weekly window stands against an even spend, or None too early to say.

    Returns the percentage an even spend would have used by now, whether usage
    is at least AHEAD_POINTS over it, and whether the current rate runs past
    100% before the reset. Silent for the first day after a reset, when one
    heavy hour would read as a runaway week.
    """
    remaining = (resets_at - fetched_at) % window
    elapsed = window - remaining if remaining else 0
    if elapsed < DAY_SECONDS:
        return None
    expected = min(100.0, elapsed / window * 100)
    projected = used + used / elapsed * (window - elapsed)
    return {
        "expected": expected,
        "ahead": used - expected >= AHEAD_POINTS,
        "runs_out": projected > 100,
    }


def _epoch(stamp):
    """POSIX seconds for an ISO 8601 reset time, or None when it cannot be read."""
    if not isinstance(stamp, str):
        return None
    try:
        return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_usage(raw):
    """Normalise a GET /api/oauth/usage response, or None when it is not an object.

    Each window is {used, resets_at} with resets_at in POSIX seconds, or None
    when the response has no readable percentage for it. Per-model weekly
    limits come from `limits[]`, named by their model's display name.
    """
    if not isinstance(raw, dict):
        return None

    def window(key):
        entry = raw.get(key)
        used = _number(entry.get("utilization")) if isinstance(entry, dict) else None
        if used is None:
            return None
        return {"used": used, "resets_at": _epoch(entry.get("resets_at"))}

    models = []
    limits = raw.get("limits")
    for limit in limits if isinstance(limits, list) else []:
        if not isinstance(limit, dict):
            continue
        scope = limit.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        name = model.get("display_name") if isinstance(model, dict) else None
        used = _number(limit.get("percent"))
        if not isinstance(name, str) or not name or used is None:
            continue
        models.append({"name": name, "used": used, "resets_at": _epoch(limit.get("resets_at"))})

    return {"five_hour": window("five_hour"), "seven_day": window("seven_day"), "models": models}


class StoreError(ValueError):
    """The account store cannot be trusted; the message says why, for the panel."""


def parse_store(text):
    """The accounts in the panel's store, in order; [] when there is no store yet.

    Strict: anything torn, of an unknown version, or ambiguous raises
    StoreError rather than yielding the accounts that could be read, because a
    store rebuilt from a partial read loses the credentials of the rest.
    """
    if text is None:
        return []
    try:
        doc = json.loads(text)
    except ValueError:
        raise StoreError("store is not valid JSON") from None
    if not isinstance(doc, dict):
        raise StoreError("store is not a JSON object")
    if doc.get("version") != STORE_VERSION:
        raise StoreError(f"unknown store version {doc.get('version')}")
    accounts = doc.get("accounts")
    if not isinstance(accounts, list):
        raise StoreError("accounts is not a list")

    ids, uuids = set(), set()
    for position, account in enumerate(accounts, 1):
        ident = account.get("id") if isinstance(account, dict) else None
        if not isinstance(ident, str) or not ident:
            raise StoreError(f"account {position} has no id")
        uuid = account.get("accountUuid")
        if not isinstance(uuid, str) or not uuid:
            raise StoreError(f"account {ident} has no accountUuid")
        if ident in ids:
            raise StoreError(f"account id {ident} appears twice")
        if uuid in uuids:
            raise StoreError(f"account {uuid} is stored twice")
        ids.add(ident)
        uuids.add(uuid)
    return accounts


def next_poll(interval, outcome, now, moved=False, active=False, reset_at=None, jitter=JITTER):
    """When to read an account's usage next, given how the last reading went.

    A good reading halves the interval toward the floor when usage moved
    since the last one and grows it toward the ceiling when it did not; a
    failure backs off by half again up to the outer ceiling; a 429 holds off
    for an hour without growing the interval, since cswap polls the same
    budget and the limit clears on its own. Nothing is scheduled past a
    known window reset, where the stored figures stop being true. A little
    jitter keeps this poller and cswap from lining up.
    """
    if outcome == "ok":
        ceiling = ACTIVE_CEILING_SECONDS if active else OTHER_CEILING_SECONDS
        if interval is None:
            chosen = POLL_FLOOR_SECONDS
        elif moved:
            chosen = max(POLL_FLOOR_SECONDS, interval // 2)
        else:
            chosen = max(POLL_FLOOR_SECONDS, min(ceiling, int(interval * GROWTH)))
    elif outcome == "failed":
        chosen = int(interval * GROWTH)
    elif outcome == "rate_limited":
        return {"interval": interval, "at": now + RATE_LIMIT_HOLD_SECONDS}
    else:
        raise ValueError(f"unknown poll outcome {outcome!r}")
    if jitter:
        chosen = int(chosen * (1 + random.random() * jitter))
    chosen = min(POLL_CEILING_SECONDS, chosen)
    at = now + chosen
    if reset_at is not None and now < reset_at + RESET_SLACK_SECONDS < at:
        at = reset_at + RESET_SLACK_SECONDS
    return {"interval": chosen, "at": at}


def worst_window(usage):
    """The highest percentage used across an account's windows, or None."""
    figures = [w["used"] for w in (usage.get("five_hour"), usage.get("seven_day")) if w]
    figures += [m["used"] for m in usage.get("models") or []]
    return max(figures) if figures else None


def next_reset(usage, now):
    """The nearest window reset after `now`, or None."""
    windows = [usage.get("five_hour"), usage.get("seven_day")] + list(usage.get("models") or [])
    resets = [w["resets_at"] for w in windows if w and w.get("resets_at") is not None and w["resets_at"] > now]
    return min(resets) if resets else None


def read_now_states(states, now):
    """Every account due at once, except one read within the floor.

    The reload button asks for this; the floor keeps a button held down from
    spending the hour's budget.
    """
    out = {}
    for account_id, state in states.items():
        fetched = state.get("fetched_at")
        fresh = fetched is not None and now - fetched < POLL_FLOOR_SECONDS
        out[account_id] = state if fresh else dict(state, next_at=0)
    return out


#: Automatic switching. At 90 rather than 95 a running Claude Code, which
#: takes about half a minute to pick a new login up from the Keychain, still
#: has an account that answers while it does.
SWITCH_THRESHOLD = 90
SWITCH_MARGIN_POINTS = 10
TIE_POINTS = 5
SWITCH_COOLDOWN_SECONDS = 300
PICKUP_SECONDS = 60
PROJECTION_HORIZON_SECONDS = 600
RESET_NEAR_SECONDS = 600
RATE_MIN_SECONDS = 60
FULL = 100


def _windows(usage):
    """(name, window) for each window a reading holds, under the names a person reads."""
    named = [("5-hour", usage.get("five_hour")), ("weekly", usage.get("seven_day"))]
    named += [(m["name"], m) for m in usage.get("models") or []]
    return [(name, window) for name, window in named if window]


def binding(usage, now):
    """The fullest window of a reading: {figure, window, resets_at}, or None.

    None too when any window's reset has passed since the reading: the figures
    describe a window that no longer exists, and only a new reading says what
    the account holds now.
    """
    windows = _windows(usage or {})
    if not windows or any(w["resets_at"] is not None and w["resets_at"] <= now for _, w in windows):
        return None
    name, window = max(windows, key=lambda pair: pair[1]["used"])
    return {"figure": window["used"], "window": name, "resets_at": window["resets_at"]}


def burn_rates(earlier_usage, earlier_at, usage, fetched_at):
    """Points a second each window rose between two readings of the same window."""
    if not earlier_usage or earlier_at is None or fetched_at - earlier_at < RATE_MIN_SECONDS:
        return {}
    before = dict(_windows(earlier_usage))
    rates = {}
    for name, window in _windows(usage):
        was = before.get(name)
        if was is None or was["resets_at"] != window["resets_at"]:
            continue
        rates[name] = max(0.0, (window["used"] - was["used"]) / (fetched_at - earlier_at))
    return rates


def runs_out(usage, rates):
    """The first window to reach 100 at its rate: {window, seconds from the reading}, or None.

    A window that resets before it fills does not run out; the reading's own
    time, `usage["fetched_at"]`, is what its reset is measured from.
    """
    fetched_at = usage.get("fetched_at")
    soonest = None
    for name, window in _windows(usage):
        left = FULL - window["used"]
        rate = rates.get(name, 0.0)
        if left > 0 and rate <= 0:
            continue
        seconds = max(0.0, left / rate) if left > 0 else 0.0
        resets_at = window["resets_at"]
        if fetched_at is not None and resets_at is not None and fetched_at + seconds >= resets_at:
            continue
        if soonest is None or seconds < soonest["seconds"]:
            soonest = {"window": name, "seconds": seconds}
    return soonest


ACTIVE_READING_MAX_AGE_SECONDS = ACTIVE_CEILING_SECONDS + 30
STAY = {"act": "stay"}


def _why(mine, out, age):
    if mine["figure"] >= SWITCH_THRESHOLD or out is None:
        return f"{mine['window']} at {mine['figure']:.0f}%"
    minutes = max(1, round((out["seconds"] - age) / 60))
    return f"{out['window']} on course for 100% in {minutes} min"


def switch_decision(active_id, states, accounts, now, last_switch=None):
    """What the daemon should do about the active account now.

    {"act": "stay"}, {"act": "read", account_id} when a figure the decision
    rests on is too old to act on, {"act": "switch", account_id, why}, or
    {"act": "blocked", why} when the account should be left and nothing
    emptier exists.
    """
    state = states.get(active_id) or {}
    fetched = state.get("fetched_at")
    if state.get("outcome") != "ok" or fetched is None or now - fetched > ACTIVE_READING_MAX_AGE_SECONDS:
        return STAY
    mine = binding(state["usage"], now)
    if mine is None:
        return {"act": "read", "account_id": active_id}
    since = now - last_switch["at"] if last_switch else None
    if since is not None and since < PICKUP_SECONDS:
        return STAY
    age = now - fetched
    rates = burn_rates(state.get("earlier_usage"), state.get("earlier_at"), state["usage"], fetched)
    out = runs_out(dict(state["usage"], fetched_at=fetched), rates)
    emergency = out is not None and out["seconds"] - age <= PICKUP_SECONDS
    on_course = out is not None and out["seconds"] - age <= PROJECTION_HORIZON_SECONDS
    returns_soon = mine["resets_at"] is not None and mine["resets_at"] - now <= RESET_NEAR_SECONDS
    if not (on_course or (mine["figure"] >= SWITCH_THRESHOLD and not returns_soon)):
        return STAY
    if not emergency and since is not None and since < SWITCH_COOLDOWN_SECONDS:
        return STAY

    candidates, passed_over = [], False
    for account in accounts:
        other = states.get(account["id"]) or {}
        if account["id"] == active_id or account.get("needsLogin") or other.get("usage") is None:
            continue
        theirs = binding(other["usage"], now)
        if theirs is None or now - other["fetched_at"] > POLL_FLOOR_SECONDS:
            held = other.get("outcome") == "rate_limited" and other.get("next_at", 0) > now
            if held or now - other.get("tried_at", 0) < POLL_FLOOR_SECONDS:
                passed_over = True
                continue
            return {"act": "read", "account_id": account["id"]}
        candidates.append((account["id"], theirs))

    target = _target(mine, candidates, emergency)
    if target is None:
        if any(c[1]["figure"] < mine["figure"] for c in candidates):
            return STAY
        why = "the other accounts cannot be read" if passed_over else "every account is full"
        return {"act": "blocked", "why": why}
    return {"act": "switch", "account_id": target, "why": _why(mine, out, age)}


def _target(mine, candidates, emergency):
    """The account id a switch from `mine` would go to, or None when none fits.

    Ordinarily a target sits under the threshold and a margin under the active
    account; in an emergency anything emptier will do. The emptiest wins, and
    near-equal ones go to whichever resets sooner, so quota about to expire is
    spent first.
    """
    if emergency:
        fit = [c for c in candidates if c[1]["figure"] < mine["figure"]]
    else:
        fit = [c for c in candidates if c[1]["figure"] < SWITCH_THRESHOLD
               and c[1]["figure"] <= mine["figure"] - SWITCH_MARGIN_POINTS]
    if not fit:
        return None
    lowest = min(c[1]["figure"] for c in fit)
    tied = [c for c in fit if c[1]["figure"] - lowest <= TIE_POINTS]
    return min(tied, key=lambda c: (c[1]["resets_at"] is None, c[1]["resets_at"] or 0, c[1]["figure"]))[0]


#: Within this many points of the threshold a switch counts as near.
NEAR_POINTS = 10


def switch_outlook(active_id, states, accounts, now):
    """Where a switch would go now, and whether one is near: {to, near, why}, or None.

    The same ranking as `switch_decision`, without its gates: it says what the
    panel can expect, not what the daemon is about to do. `to` is None when no
    stored account fits; `why` names the window that makes a switch near.
    """
    state = states.get(active_id) or {}
    fetched = state.get("fetched_at")
    if state.get("outcome") != "ok" or fetched is None:
        return None
    mine = binding(state["usage"], now)
    if mine is None:
        return None
    age = now - fetched
    rates = burn_rates(state.get("earlier_usage"), state.get("earlier_at"), state["usage"], fetched)
    out = runs_out(dict(state["usage"], fetched_at=fetched), rates)
    on_course = out is not None and out["seconds"] - age <= PROJECTION_HORIZON_SECONDS
    near = on_course or mine["figure"] >= SWITCH_THRESHOLD - NEAR_POINTS
    candidates = []
    for account in accounts:
        other = states.get(account["id"]) or {}
        if account["id"] == active_id or account.get("needsLogin") or other.get("usage") is None:
            continue
        theirs = binding(other["usage"], now)
        if theirs is not None:
            candidates.append((account["id"], theirs))
    return {"to": _target(mine, candidates, emergency=False), "near": near,
            "why": _why(mine, out, age) if near else None}


def needs_refresh(expires_at_ms, active, now):
    """Whether the panel should spend a stored refresh token now.

    Never for the active account: Claude Code owns that token, and spending it
    logs out every running session. Otherwise when the access token expires
    within the margin, or carries no expiry to trust.
    """
    if active:
        return False
    if not isinstance(expires_at_ms, (int, float)) or isinstance(expires_at_ms, bool):
        return True
    return expires_at_ms / 1000 - now <= REFRESH_MARGIN_SECONDS


def _refresh_token(blob):
    oauth = blob.get("claudeAiOauth") if isinstance(blob, dict) else None
    token = oauth.get("refreshToken") if isinstance(oauth, dict) else None
    return token if isinstance(token, str) and token else None


def merge_credential(target, live):
    """The credential to write when switching: the target's account token, the live rest.

    Everything outside `claudeAiOauth` (MCP logins, plugin secrets) belongs to
    this machine, not to an account, so it always comes from the live item.
    """
    oauth = target.get("claudeAiOauth") if isinstance(target, dict) else None
    if not isinstance(oauth, dict):
        raise ValueError("target credential has no claudeAiOauth")
    return {**(live if isinstance(live, dict) else {}), "claudeAiOauth": oauth}


def account_for(accounts, oauth_account):
    """The stored account a live `oauthAccount` belongs to, or None."""
    uuid = oauth_account.get("accountUuid") if isinstance(oauth_account, dict) else None
    return next((a for a in accounts if uuid and a["accountUuid"] == uuid), None)


def should_resync(stored, live):
    """Whether the live credential is a newer copy of a stored account's token.

    The caller has already matched the two by accountUuid. A live item without
    a refresh token is never copied, since it would replace one that works.
    """
    fresh = _refresh_token(live)
    return fresh is not None and fresh != _refresh_token(stored)


class SwitchRefused(Exception):
    """A switch that must not start; the message is shown to the user as is."""


NICKNAME_MAX_CHARS = 40


def nickname(text):
    """The alias to store for what was typed: trimmed, or None to fall back to the default name."""
    alias = text.strip()
    if len(alias) > NICKNAME_MAX_CHARS:
        raise ValueError(f"a nickname is at most {NICKNAME_MAX_CHARS} characters")
    return alias or None


def _name(account, email=None):
    """What the panel calls an account: its alias, its email, or "Account N" from its id."""
    return account.get("alias") or email or "Account " + account["id"].removeprefix("acct-")


def plan_switch(accounts, target_id, live_oauth_account, claude_dir, claude_json, claude_dir_resolved=None):
    """How to switch the active login to `target_id`: {"steps": [...], "undo": {...}}.

    Refusals are decided here, before any step runs. The target's token is
    refreshed first, outside the locks, because that network call proves the
    login is alive. Writes then happen under Claude Code's two credential
    locks, taken in its order, so a refresh it is running cannot overwrite the
    switch. Under the locks the live login is read again and must still be the
    outgoing account, since cswap may have switched since this plan was made;
    only then is it saved to its own slot and replaced.

    Claude Code names its second credential lock after the config directory's
    resolved path, so `claude_dir_resolved` is where a symlinked one points.

    `undo` maps each write to Claude Code's login onto the step that puts back
    what `read_live` read. When a step fails, the runner undoes every started
    write in reverse, then releases the locks it holds, so the Keychain and
    ~/.claude.json never name different accounts.
    """
    target = next((a for a in accounts if a["id"] == target_id), None)
    if target is None:
        raise SwitchRefused(f"no stored account {target_id}")
    outgoing = account_for(accounts, live_oauth_account)
    if outgoing is target:
        raise SwitchRefused(f"{_name(target)} is already active")
    if outgoing is None:
        raise SwitchRefused("the current login is not a stored account; add it first")
    if target.get("needsLogin"):
        raise SwitchRefused(f"log in to {_name(target)} again")

    refresh_lock = f"{claude_dir.rstrip('/')}/.oauth_refresh.lock"
    legacy_lock = f"{(claude_dir_resolved or claude_dir).rstrip('/')}.lock"
    config_lock = f"{claude_json}.lock"
    steps = [
        ("refresh", target_id),
        ("lock", refresh_lock, CREDENTIAL_LOCK_STALE_SECONDS),
        ("lock", legacy_lock, CREDENTIAL_LOCK_STALE_SECONDS),
        ("read_live",),
        ("verify_live_is", outgoing["id"]),
        ("backup_live_credential", outgoing["id"]),
        ("write_live_credential", target_id),
        ("lock", config_lock, CONFIG_LOCK_STALE_SECONDS),
        ("write_oauth_account", target_id),
        ("unlock", config_lock),
        ("unlock", legacy_lock),
        ("unlock", refresh_lock),
    ]
    undo = {
        "write_live_credential": ("restore_live_credential",),
        "write_oauth_account": ("restore_oauth_account",),
    }
    return {"steps": steps, "undo": undo}


def claude_paths(env, home, exists):
    """Claude Code's config directory and global config file, resolved as it does.

    CLAUDE_CONFIG_DIR replaces the home directory for both; a legacy
    `.config.json` inside the config directory wins over `.claude.json`.
    """
    base = env.get("CLAUDE_CONFIG_DIR") or ""
    claude_dir = base or f"{home}/.claude"
    legacy = f"{claude_dir}/.config.json"
    if exists(legacy):
        return claude_dir, legacy
    return claude_dir, f"{base or home}/.claude.json"


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


#: Apple's binary by absolute path: an earlier `security` on PATH must not see secrets.
SECURITY = "/usr/bin/security"
#: `security -i` reads each command with a 4096-byte fgets buffer; a longer line
#: is cut mid-argument. The margin covers line-terminator accounting.
SECURITY_LINE_LIMIT = 4096 - 64
SECURITY_TIMEOUT_SECONDS = 5
NOT_FOUND_EXIT = 44


class KeychainError(Exception):
    """A `security` call failed for a reason other than the item being absent."""


def _security_quote(value):
    """Quote a name for a `security -i` line, which it re-parses shell-style."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_command(service, account, value):
    """The argv and stdin that store `value` as a generic password, as (argv, stdin).

    The value goes hex-encoded through `security -i` on stdin so it never shows
    in a process listing. Only a line too long for that buffer falls back to
    argv, because a truncated line would silently fail to write.
    """
    hex_value = value.encode("utf-8").hex()
    line = (f"add-generic-password -U -a {_security_quote(account)} "
            f"-s {_security_quote(service)} -X {hex_value}\n")
    if len(line.encode("utf-8")) <= SECURITY_LINE_LIMIT:
        return [SECURITY, "-i"], line
    return [SECURITY, "add-generic-password", "-U", "-a", account, "-s", service, "-X", hex_value], None


def read_result(returncode, stdout, stderr):
    """The secret a `find-generic-password -w` call printed, None when absent.

    Any exit other than success or not-found raises, so a locked or denied
    Keychain is never mistaken for an account with no stored login.
    """
    if returncode == 0:
        return stdout[:-1] if stdout.endswith("\n") else stdout
    if returncode == NOT_FOUND_EXIT:
        return None
    raise KeychainError(f"security failed (rc={returncode}: {stderr.strip().rstrip('.')})")


def _run_security(argv, stdin=None):
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True,
                              timeout=SECURITY_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise KeychainError(f"security timed out after {SECURITY_TIMEOUT_SECONDS}s") from None


def read_secret(service, account):
    """The generic password stored under service and account, or None."""
    result = _run_security([SECURITY, "find-generic-password", "-a", account, "-s", service, "-w"])
    return read_result(result.returncode, result.stdout, result.stderr)


def write_secret(service, account, value):
    """Create or replace the generic password under service and account."""
    argv, stdin = write_command(service, account, value)
    result = _run_security(argv, stdin)
    if result.returncode != 0:
        raise KeychainError(f"security failed (rc={result.returncode}: {result.stderr.strip()})")


def delete_secret(service, account):
    """Remove the generic password under service and account; absent is fine."""
    result = _run_security([SECURITY, "delete-generic-password", "-a", account, "-s", service])
    if result.returncode not in (0, NOT_FOUND_EXIT):
        raise KeychainError(f"security failed (rc={result.returncode}: {result.stderr.strip()})")


#: Per lock, so the credential pair waits at most twice this before refusing.
LOCK_TIMEOUT_SECONDS = 9
#: Faster than Claude Code's 5 s touches, so a held lock never looks stale.
LOCK_TOUCH_SECONDS = 3


class LockTimeout(Exception):
    """A Claude Code lock stayed held by a live holder past the wait."""


class DirLock:
    """Hold one of Claude Code's proper-lockfile directory locks.

    The directory is the lock and mkdir is the mutex. A directory older than
    `stale` seconds belongs to a holder that died, so it is removed and taken;
    a younger one is waited on, with jitter, until `timeout`. While held, a
    thread keeps touching it so Claude Code never judges it stale. The parent
    directory is never created: a missing one means the path is wrong.
    """

    def __init__(self, path, stale, timeout=LOCK_TIMEOUT_SECONDS, touch_every=LOCK_TOUCH_SECONDS):
        self.path, self.stale, self.timeout, self.touch_every = path, stale, timeout, touch_every
        self._stop = threading.Event()
        self._toucher = None

    def __enter__(self):
        started = time.monotonic()
        while True:
            try:
                os.mkdir(self.path)
                break
            except FileExistsError:
                pass
            if time.monotonic() - started >= self.timeout:
                raise LockTimeout("Claude Code is refreshing, try again")
            try:
                age = time.time() - os.stat(self.path).st_mtime
            except FileNotFoundError:
                continue
            if age > self.stale:
                try:
                    os.rmdir(self.path)
                except OSError:
                    time.sleep(0.05)
                continue
            time.sleep(min(0.25 + random.random() * 0.25,
                           max(0.0, self.timeout - (time.monotonic() - started))))
        self._toucher = threading.Thread(target=self._touch, daemon=True)
        self._toucher.start()
        return self

    def _touch(self):
        while not self._stop.wait(self.touch_every):
            try:
                os.utime(self.path)
            except OSError:
                return

    def __exit__(self, *exc):
        self._stop.set()
        self._toucher.join(timeout=1)
        try:
            os.rmdir(self.path)
        except FileNotFoundError:
            pass
        return False


#: Claude Code's public OAuth client and token endpoint, as found in its binary.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REFRESH_TIMEOUT_SECONDS = 10
#: macOS's own CA bundle. iTerm2's bundled Python points OpenSSL at a path on
#: the machine it was built on, so its default context verifies nothing.
SYSTEM_CA_BUNDLE = "/etc/ssl/cert.pem"


def _tls():
    if os.path.exists(SYSTEM_CA_BUNDLE):
        return ssl.create_default_context(cafile=SYSTEM_CA_BUNDLE)
    return ssl.create_default_context()


def refresh_body(blob):
    """The token-endpoint request that spends this credential's refresh token."""
    token = _refresh_token(blob)
    if token is None:
        raise ValueError("credential has no refresh token")
    return json.dumps({"grant_type": "refresh_token", "refresh_token": token,
                       "client_id": OAUTH_CLIENT_ID}).encode()


def apply_refresh(blob, response, now_ms):
    """A copy of the credential carrying the successor tokens from a refresh response.

    A response without a new refresh token keeps the old one, which the server
    left valid; anything else in the credential is carried over untouched.
    """
    access = response.get("access_token") if isinstance(response, dict) else None
    lifetime = response.get("expires_in") if isinstance(response, dict) else None
    if not isinstance(access, str) or not access or _number(lifetime) is None:
        raise ValueError("refresh response has no access token and lifetime")
    oauth = dict(blob["claudeAiOauth"], accessToken=access, expiresAt=now_ms + int(lifetime * 1000))
    if isinstance(response.get("refresh_token"), str) and response["refresh_token"]:
        oauth["refreshToken"] = response["refresh_token"]
    if isinstance(response.get("scope"), str) and response["scope"]:
        oauth["scopes"] = response["scope"].split()
    return {**blob, "claudeAiOauth": oauth}


def refresh_verdict(status, body):
    """What a failed refresh says about the token: invalid_grant, invalid_client or transient.

    Only a 400/401/403 whose JSON `error` names the rejection counts. Anything
    ambiguous is transient, because calling a live login dead makes the user
    log in again for nothing.
    """
    if status not in (400, 401, 403):
        return "transient"
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError):
        return "transient"
    return error if error in ("invalid_grant", "invalid_client") else "transient"


def request_refresh(blob, now_ms):
    """Spend the credential's refresh token.

    Returns ("ok", successor), ("unreadable", raw reply) when the server
    answered but its reply cannot be applied, or (verdict, None) when it
    refused or could not be reached.
    """
    request = urllib.request.Request(OAUTH_TOKEN_URL, data=refresh_body(blob), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "agents-sidebar"})
    try:
        with urllib.request.urlopen(request, timeout=REFRESH_TIMEOUT_SECONDS, context=_tls()) as reply:
            text = reply.read().decode(errors="replace")
    except urllib.error.HTTPError as error:
        return refresh_verdict(error.code, error.read().decode(errors="replace")), None
    except (urllib.error.URLError, OSError):
        return "transient", None
    return read_refresh_reply(blob, text, now_ms)


def read_refresh_reply(blob, text, now_ms):
    """("ok", successor) from a successful refresh reply, or ("unreadable", text) whole."""
    try:
        return "ok", apply_refresh(blob, json.loads(text), now_ms)
    except (ValueError, TypeError):
        return "unreadable", text


def save_pending(store_dir, account_id, text, suffix=".json"):
    """Write text the Keychain could not take to a private file, and return its path.

    `.json` holds a successor credential to retry into the Keychain; `.reply`
    holds a token-endpoint reply that could not be read, kept for a person.
    """
    path = os.path.join(store_dir, "pending", account_id + suffix)
    _write_private(path, text)
    return path


def recover_pending(store_dir, service, only=None):
    """Move saved successor credentials into the Keychain; return the account ids moved.

    A file is removed only after its Keychain write succeeded, so a failure
    leaves it for the next attempt.
    """
    folder = os.path.join(store_dir, "pending")
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    moved = []
    for name in names:
        account_id = name[:-len(".json")]
        if not name.endswith(".json") or (only is not None and account_id != only):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            write_secret(service, account_id, text)
        except KeychainError:
            continue
        os.remove(path)
        moved.append(account_id)
    return moved


def refresh_account(store_dir, service, account_id, now_ms):
    """Spend one stored account's refresh token and keep its successor. Returns the outcome.

    Under a per-account lock, so two refreshes of one account never both spend
    the same token: a successor saved earlier is moved into the Keychain first,
    and the stored credential is read again. A successor the Keychain refuses
    goes to a pending file, and an unreadable reply is kept whole; while either
    is outstanding the old token is known spent, so nothing is sent.

    Outcomes: ok, no_credential, unreadable_credential, unreadable_reply,
    pending (a successor is waiting for the Keychain), or the server's verdict
    (invalid_grant, invalid_client, transient).
    """
    locks = os.path.join(store_dir, "locks")
    os.makedirs(locks, mode=0o700, exist_ok=True)
    pending = os.path.join(store_dir, "pending", account_id)
    with open(os.path.join(locks, account_id + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if os.path.exists(pending + ".reply"):
            return "unreadable_reply"
        if os.path.exists(pending + ".json"):
            recover_pending(store_dir, service, only=account_id)
            if os.path.exists(pending + ".json"):
                return "pending"
        text = read_secret(service, account_id)
        if text is None:
            return "no_credential"
        try:
            blob = json.loads(text)
            refresh_body(blob)
        except (ValueError, AttributeError, TypeError):
            return "unreadable_credential"
        verdict, result = request_refresh(blob, now_ms)
        if verdict == "unreadable":
            save_pending(store_dir, account_id, result, suffix=".reply")
            return "unreadable_reply"
        if verdict != "ok":
            return verdict
        successor = json.dumps(result)
        try:
            write_secret(service, account_id, successor)
        except KeychainError:
            save_pending(store_dir, account_id, successor)
            return "pending"
        return "ok"


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA = "oauth-2025-04-20"
USAGE_TIMEOUT_SECONDS = 5


def usage_outcome(status, body):
    """(outcome, usage) for a usage reply: ok, unauthorized, rate_limited or failed."""
    if status == 200:
        try:
            usage = parse_usage(json.loads(body))
        except ValueError:
            usage = None
        return ("ok", usage) if usage is not None else ("failed", None)
    if status == 401:
        return "unauthorized", None
    if status == 429:
        return "rate_limited", None
    return "failed", None


def request_usage(access_token):
    """Read one account's usage with its access token: (outcome, usage)."""
    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {access_token}", "anthropic-beta": USAGE_BETA,
        "User-Agent": "agents-sidebar"})
    try:
        with urllib.request.urlopen(request, timeout=USAGE_TIMEOUT_SECONDS, context=_tls()) as reply:
            return usage_outcome(reply.status, reply.read().decode(errors="replace"))
    except urllib.error.HTTPError as error:
        return usage_outcome(error.code, error.read().decode(errors="replace"))
    except (urllib.error.URLError, OSError):
        return "failed", None


#: Account fields copied from Claude Code's `oauthAccount`. The email is left out.
LOGIN_FIELDS = ("accountUuid", "organizationUuid", "organizationName")


def store_text(accounts):
    """The store file's contents for these accounts."""
    return json.dumps({"version": STORE_VERSION, "accounts": accounts}, indent=2) + "\n"


def add_account(accounts, oauth_account, now, alias=None):
    """The accounts with this login added, and its entry: (accounts, account).

    A login already stored is not added twice; its entry is marked synced.
    New ids count past the highest `acct-<n>` in use, so an id is never reused.
    """
    uuid = oauth_account.get("accountUuid") if isinstance(oauth_account, dict) else None
    if not isinstance(uuid, str) or not uuid:
        raise ValueError("login has no accountUuid")
    existing = account_for(accounts, oauth_account)
    if existing is not None:
        updated = dict(existing, lastSynced=now)
        return [updated if a is existing else a for a in accounts], updated
    numbers = [int(a["id"][5:]) for a in accounts if a["id"].startswith("acct-") and a["id"][5:].isdigit()]
    account = {"id": f"acct-{max(numbers, default=0) + 1}", "alias": alias}
    account.update({field: oauth_account.get(field) for field in LOGIN_FIELDS})
    account.update(added=now, lastSynced=now)
    return accounts + [account], account


def _write_private(path, text):
    """Replace a file atomically with owner-only permissions, creating its folder 0700."""
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    temp = path + ".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def load_store(path):
    """The stored accounts; raises StoreError when the file cannot be trusted."""
    return parse_store(_read_text(path))


def save_store(path, accounts):
    """Write the store atomically, readable only by its owner."""
    _write_private(path, store_text(accounts))


def login_item(account_id):
    """The Keychain account holding a stored account's `oauthAccount` block.

    A switch writes that block back into Claude Code's config, and it carries
    the email, so it lives beside the credential rather than in the store file.
    """
    return account_id + ".login"


def add_live_account(store_path, service, live_item, claude_json, now):
    """Copy the login Claude Code is using into the store, and return its entry.

    `live_item` is the (service, account) of Claude Code's credential. The
    credential is written to the panel's Keychain item before the store names
    the account, so the store never lists an account it has no token for.
    """
    with open(claude_json, encoding="utf-8") as f:
        login = json.load(f).get("oauthAccount")
    if not isinstance(login, dict) or not login.get("accountUuid"):
        raise ValueError("no login in Claude Code's config")
    credential = read_secret(*live_item)
    if credential is None:
        raise ValueError("no live credential in the Keychain")
    with _store_lock(store_path) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        accounts, account = add_account(load_store(store_path), login, now)
        write_secret(service, account["id"], credential)
        write_secret(service, login_item(account["id"]), json.dumps(login))
        save_store(store_path, accounts)
    return account


def due(accounts, states, now):
    """The ids of accounts whose next reading time has come; never-read ones first come due."""
    return [a["id"] for a in accounts if states.get(a["id"], {}).get("next_at", 0) <= now]


def record(state, outcome, usage, now, active=False, jitter=JITTER):
    """An account's polling state after a reading attempt with this outcome.

    A good reading replaces the figures and when they were taken; anything
    else keeps the last good figures, so the panel can show them as stale.
    """
    # A first reading has no interval yet; a good one starts at the floor and
    # a failed one backs off from it.
    previous = state or {"interval": None if outcome == "ok" else POLL_FLOOR_SECONDS,
                         "usage": None, "fetched_at": None}
    fresh = outcome == "ok"
    before = worst_window(previous["usage"]) if previous.get("usage") else None
    after = worst_window(usage) if fresh and usage else None
    moved = before is not None and after is not None and abs(after - before) >= MOVEMENT_POINTS
    schedule = next_poll(previous["interval"],
                         outcome if outcome in ("ok", "rate_limited") else "failed", now,
                         moved=moved, active=active,
                         reset_at=next_reset(usage, now) if fresh and usage else None, jitter=jitter)
    return {"interval": schedule["interval"], "next_at": schedule["at"], "outcome": outcome,
            "usage": usage if fresh else previous["usage"],
            "fetched_at": now if fresh else previous["fetched_at"],
            "earlier_usage": previous["usage"] if fresh else previous.get("earlier_usage"),
            "earlier_at": previous["fetched_at"] if fresh else previous.get("earlier_at"),
            "tried_at": now}


def _with_pace(window, fetched_at):
    return dict(window, pace=pace(window["used"], window["resets_at"], fetched_at)
                if window["resets_at"] is not None else None)


def meters_snapshot(accounts, states, active_id, error=None, emails=None, last_switch=None,
                    next_switch=None, live=None):
    """What the panel receives about accounts: names, which is active, figures and pace.

    Pace is worked out here from the reading's own time, so the snapshot only
    changes when a reading does. Names are aliases, else the email from
    `emails` (id -> email), else "Account N" from the id, which stays put when
    another account is removed. `last_switch` is the loop's record of the
    latest switch and `next_switch` its outlook; the panel gets targets by name.
    `live` is the email Claude Code is logged in with, stored or not, so the
    panel can say whose login "Add" would store; None when it has none.
    """
    emails = emails or {}
    shaped = []
    for account in accounts:
        state = states.get(account["id"]) or {}
        usage = state.get("usage") or {}
        fetched = state.get("fetched_at")
        weekly = usage.get("seven_day")
        shaped.append({
            "id": account["id"], "name": _name(account, emails.get(account["id"])),
            "alias": account.get("alias"),
            "default_name": _name({"id": account["id"]}, emails.get(account["id"])),
            "active": account["id"] == active_id, "needs_login": bool(account.get("needsLogin")),
            "outcome": state.get("outcome"), "fetched_at": fetched,
            "five_hour": usage.get("five_hour"),
            "seven_day": _with_pace(weekly, fetched) if weekly else None,
            "models": [_with_pace(m, fetched) for m in usage.get("models", [])],
        })
    shown = None
    if last_switch:
        target = next((a for a in accounts if a["id"] == last_switch["to"]), {"id": last_switch["to"]})
        shown = {"at": last_switch["at"], "to": _name(target, emails.get(target["id"])),
                 "why": last_switch["why"], "auto": last_switch["auto"]}
    outlook = None
    if next_switch:
        to = next_switch["to"]
        target = next((a for a in accounts if a["id"] == to), {"id": to}) if to else None
        outlook = dict(next_switch, to=_name(target, emails.get(to)) if target else None)
    return {"active": active_id, "accounts": shaped, "error": error, "last_switch": shown,
            "next_switch": outlook, "live": live}


def _store_lock(store_path):
    locks = os.path.join(os.path.dirname(store_path), "locks")
    os.makedirs(locks, mode=0o700, exist_ok=True)
    return open(os.path.join(locks, "store.lock"), "a")


def update_account(store_path, account_id, **fields):
    """Set fields on one stored account, under the store lock; an absent account is left alone."""
    with _store_lock(store_path) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        accounts = load_store(store_path)
        if not any(a["id"] == account_id for a in accounts):
            return
        save_store(store_path, [dict(a, **fields) if a["id"] == account_id else a for a in accounts])


def _live_login(claude_json):
    try:
        with open(claude_json, encoding="utf-8") as f:
            login = json.load(f).get("oauthAccount")
    except (OSError, ValueError, AttributeError):
        return None
    return login if isinstance(login, dict) else None


def _access_token(text):
    try:
        oauth = json.loads(text).get("claudeAiOauth") or {}
    except (TypeError, ValueError, AttributeError):
        return None, None
    return oauth.get("accessToken"), oauth.get("expiresAt")


class AccountMeters:
    """The meter loop's memory: one `tick` reads what is due, `snapshot` reports it.

    The active account's token is Claude Code's: it is read from the live item,
    copied into the panel's item when Claude Code has rotated it, and never
    refreshed. Inactive accounts are refreshed through the per-account gate
    when their access token is about to expire or is refused, once per reading;
    a refused refresh marks the login dead in the store.
    """

    def __init__(self, store_path, service, live_item, claude_json, claude_dir=None):
        self.store_path, self.service = store_path, service
        self.live_item, self.claude_json = live_item, claude_json
        self.claude_dir = claude_dir or os.path.join(os.path.expanduser("~"), ".claude")
        self.states = {}
        #: Account id -> email, read from its login block once and kept for names.
        self.emails = {}
        self._snapshot = meters_snapshot([], {}, None)
        #: The background loop and a reading started by Add run in threads.
        self._one_at_a_time = threading.Lock()
        #: The latest switch, by hand or not: {at, from, to, why, auto}.
        self.last_switch = None
        #: The blocked or refused event last reported, so it is said once.
        self._said = None

    def snapshot(self):
        return self._snapshot

    def tick(self, now, auto=False):
        """Read what is due; with `auto`, leave a full account. -> what happened, for the log."""
        with self._one_at_a_time:
            self._tick(now)
            return self._decide(now) if auto else []

    def _decide(self, now):
        try:
            accounts = load_store(self.store_path)
        except StoreError:
            return []
        active = account_for(accounts, _live_login(self.claude_json))
        if active is None or len(accounts) < 2:
            return []
        decision = switch_decision(active["id"], self.states, accounts, now, self.last_switch)
        for _ in accounts:
            if decision["act"] != "read":
                break
            self.states[decision["account_id"]] = dict(self.states.get(decision["account_id"]) or {}, next_at=0)
            self._tick(now)
            decision = switch_decision(active["id"], self.states, load_store(self.store_path), now,
                                       self.last_switch)
        if decision["act"] == "switch":
            try:
                result = self._switch_locked(decision["account_id"], now, why=decision["why"], auto=True)
            except SwitchRefused as refusal:
                return self._once({"kind": "refused", "why": str(refusal)})
            self._said = None
            self._tick(now)
            return [{"kind": "switched", "name": result["name"], "why": decision["why"]}]
        if decision["act"] == "blocked":
            return self._once({"kind": "blocked", "why": decision["why"]})
        self._said = None
        return []

    def _once(self, event):
        """An event the first time it is true, nothing while it stays true."""
        if event == self._said:
            return []
        self._said = event
        return [event]

    def _tick(self, now):
        try:
            accounts = load_store(self.store_path)
        except StoreError as error:
            self._snapshot = meters_snapshot([], {}, None, error=str(error))
            return
        live_login = _live_login(self.claude_json)
        active = account_for(accounts, live_login)
        live_text = read_secret(*self.live_item) if active else None
        if active and live_text and should_resync(self._stored(active["id"]), json.loads(live_text)):
            write_secret(self.service, active["id"], live_text)
            update_account(self.store_path, active["id"], lastSynced=now)
        if active:
            login = json.dumps(live_login)
            if read_secret(self.service, login_item(active["id"])) != login:
                write_secret(self.service, login_item(active["id"]), login)
            self.emails[active["id"]] = live_login.get("emailAddress")
        for account in accounts:
            if account["id"] not in self.emails:
                self.emails[account["id"]] = self._stored_email(account["id"])
        for account in accounts:
            if account["id"] not in due(accounts, self.states, now):
                continue
            if account is active:
                outcome, usage = request_usage(_access_token(live_text)[0] or "")
            elif account.get("needsLogin"):
                outcome, usage = "needs_login", None
            else:
                outcome, usage = self._read_inactive(account["id"], now)
            self.states[account["id"]] = record(self.states.get(account["id"]), outcome, usage, now,
                                                active=account is active)
        outlook = switch_outlook(active["id"], self.states, accounts, now) if active else None
        self._snapshot = meters_snapshot(load_store(self.store_path), self.states,
                                         active["id"] if active else None, emails=self.emails,
                                         last_switch=self.last_switch, next_switch=outlook,
                                         live=(live_login or {}).get("emailAddress"))

    def read_now(self, now):
        """Read every account now, except one read within the last three minutes."""
        with self._one_at_a_time:
            self.states = read_now_states(self.states, now)
            self._tick(now)
        return {"id": None, "name": "accounts"}

    def add(self, now):
        """Add the login Claude Code is using; it is read on the next tick."""
        account = add_live_account(self.store_path, self.service, self.live_item, self.claude_json, now)
        self.states.pop(account["id"], None)
        self.emails[account["id"]] = (_live_login(self.claude_json) or {}).get("emailAddress")
        return {"id": account["id"], "name": _name(account, self.emails[account["id"]])}

    def switch(self, account_id, now):
        """Make a stored account the login every session uses. Raises SwitchRefused."""
        with self._one_at_a_time:
            return self._switch_locked(account_id, now, why=None, auto=False)

    def _switch_locked(self, account_id, now, why, auto):
        stored = load_store(self.store_path)
        outgoing = account_for(stored, _live_login(self.claude_json))
        plan = plan_switch(stored, account_id, _live_login(self.claude_json), self.claude_dir,
                           self.claude_json, claude_dir_resolved=os.path.realpath(self.claude_dir))
        run_switch(plan, self.store_path, self.service, self.live_item, self.claude_json, now)
        # Read the new active account at once, through Claude Code's token this time.
        self.states.pop(account_id, None)
        self.last_switch = {"at": now, "from": outgoing["id"] if outgoing else None,
                            "to": account_id, "why": why, "auto": auto}
        target = next(a for a in stored if a["id"] == account_id)
        return {"id": account_id, "name": _name(target, self.emails.get(account_id))}

    def rename(self, account_id, text):
        """Give a stored account a nickname; empty text clears it. Raises ValueError."""
        alias = nickname(text)
        if not any(a["id"] == account_id for a in load_store(self.store_path)):
            raise ValueError(f"no stored account {account_id}")
        update_account(self.store_path, account_id, alias=alias)
        return {"id": account_id, "name": alias or _name({"id": account_id}, self.emails.get(account_id))}

    def _stored(self, account_id):
        text = read_secret(self.service, account_id)
        try:
            return json.loads(text) if text else None
        except ValueError:
            return None

    def _stored_email(self, account_id):
        try:
            login = json.loads(read_secret(self.service, login_item(account_id)) or "{}")
        except ValueError:
            return None
        return login.get("emailAddress") if isinstance(login, dict) else None

    def _read_inactive(self, account_id, now):
        token, expires_at = _access_token(read_secret(self.service, account_id))
        if needs_refresh(expires_at, active=False, now=now):
            if not self._refresh(account_id, now):
                return "refresh_failed", None
            token, _ = _access_token(read_secret(self.service, account_id))
        outcome, usage = request_usage(token or "")
        if outcome == "unauthorized" and self._refresh(account_id, now):
            token, _ = _access_token(read_secret(self.service, account_id))
            outcome, usage = request_usage(token or "")
        return outcome, usage

    def _refresh(self, account_id, now):
        result = refresh_account(os.path.dirname(self.store_path), self.service, account_id,
                                 now_ms=int(now * 1000))
        if result == "invalid_grant":
            update_account(self.store_path, account_id, needsLogin=True)
        return result == "ok"


def _replace_login(claude_json, login):
    """Put `login` in Claude Code's config as its oauthAccount, leaving every other key.

    Read at the moment of writing, under the config lock, so a change Claude
    Code made since the switch began is kept; written to a temp file with
    owner-only permissions and renamed over the config, as claude-swap does.
    """
    with open(claude_json, encoding="utf-8") as f:
        config = json.load(f)
    config["oauthAccount"] = login
    temp = f"{claude_json}.{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(config, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, claude_json)


def run_switch(plan, store_path, service, live_item, claude_json, now,
               lock_timeout=LOCK_TIMEOUT_SECONDS):
    """Carry out a switch plan. Raises SwitchRefused, with words for the user, when it stops.

    Before any write, a refusal leaves everything as it was. Once a write to
    Claude Code's login has started, a failure puts back what `read_live` read
    for every started write, newest first, then releases the locks; the message
    says whether that worked.
    """
    accounts = {a["id"]: a for a in load_store(store_path)}
    name = lambda account_id: _name(accounts[account_id])
    held, started, saved = [], [], {}
    try:
        for step in plan["steps"]:
            kind = step[0]
            if kind == "refresh":
                result = refresh_account(os.path.dirname(store_path), service, step[1],
                                         now_ms=int(now * 1000))
                if result == "invalid_grant":
                    update_account(store_path, step[1], needsLogin=True)
                    raise SwitchRefused(f"log in to {name(step[1])} again")
                if result == "unreadable_reply":
                    raise SwitchRefused(f"a refresh reply for {name(step[1])} could not be read; it is kept in "
                                        f"pending/{step[1]}.reply and {name(step[1])} needs a login")
                if result != "ok":
                    raise SwitchRefused(f"could not refresh {name(step[1])} ({result}); try again")
            elif kind == "lock":
                lock = DirLock(step[1], stale=step[2], timeout=lock_timeout)
                lock.__enter__()
                held.append(lock)
            elif kind == "unlock":
                lock = next(l for l in held if l.path == step[1])
                held.remove(lock)
                lock.__exit__(None, None, None)
            elif kind == "read_live":
                saved["credential"] = read_secret(*live_item)
                saved["login"] = _live_login(claude_json)
            elif kind == "verify_live_is":
                if account_for(list(accounts.values()), saved["login"]) is not accounts[step[1]]:
                    raise SwitchRefused("the login changed since the switch was planned; try again")
            elif kind == "backup_live_credential":
                write_secret(service, step[1], saved["credential"])
                write_secret(service, login_item(step[1]), json.dumps(saved["login"]))
            elif kind == "write_live_credential":
                target = read_secret(service, step[1])
                login = read_secret(service, login_item(step[1]))
                if not target or not login:
                    raise SwitchRefused(f"add {name(step[1])} again before switching to it")
                saved["target_login"] = json.loads(login)
                merged = merge_credential(json.loads(target), json.loads(saved["credential"]))
                started.append(kind)
                write_secret(*live_item, json.dumps(merged))
            elif kind == "write_oauth_account":
                started.append(kind)
                _replace_login(claude_json, saved["target_login"])
            else:
                raise ValueError(f"unknown switch step {kind!r}")
    except Exception as error:
        unrestored = []
        for kind in reversed(started):
            try:
                if kind == "write_live_credential":
                    write_secret(*live_item, saved["credential"])
                else:
                    _replace_login(claude_json, saved["login"])
            except Exception:                                    # noqa: BLE001
                unrestored.append(kind)
        for lock in reversed(held):
            lock.__exit__(None, None, None)
        reason = str(error) or type(error).__name__
        if unrestored:
            raise SwitchRefused(f"switch half done and could not be undone ({', '.join(unrestored)}): "
                                f"{reason}; run /login in Claude Code") from error
        if started:
            raise SwitchRefused(f"switch undone: {reason}") from error
        if isinstance(error, (SwitchRefused, LockTimeout)):
            raise SwitchRefused(reason) from error
        raise SwitchRefused(f"switch stopped before changing anything: {reason}") from error


def main(argv=None):
    """`accounts.py switch <id> --dry-run`: print the switch plan for this machine."""
    parser = argparse.ArgumentParser(prog="accounts.py")
    commands = parser.add_subparsers(dest="command", required=True)
    switch = commands.add_parser("switch", help="switch the active Claude Code login")
    switch.add_argument("account_id")
    switch.add_argument("--dry-run", action="store_true", help="print the steps without running them")
    switch.add_argument("--store", default=STORE_PATH)
    args = parser.parse_args(argv)

    if not args.dry_run:
        print("only --dry-run is available", file=sys.stderr)
        return 2
    claude_dir, claude_json = claude_paths(os.environ, os.path.expanduser("~"), os.path.exists)
    try:
        accounts = parse_store(_read_text(args.store))
        live = json.loads(_read_text(claude_json) or "{}").get("oauthAccount")
        plan = plan_switch(accounts, args.account_id, live, claude_dir, claude_json,
                           claude_dir_resolved=os.path.realpath(claude_dir))
    except (StoreError, SwitchRefused, ValueError) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 1
    for step in plan["steps"]:
        print(" ".join(str(part) for part in step))
    for write, undo in plan["undo"].items():
        print(f"on failure after {write}: {' '.join(undo)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
