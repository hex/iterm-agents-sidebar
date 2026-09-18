# Automatic Account Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The daemon switches the active Claude account on its own before a limit stalls a session, behind one off-by-default setting.

**Architecture:** The decision is a set of pure functions in `accounts.py` over the readings `AccountMeters` already holds. `AccountMeters.tick(now, auto)` carries a decision out through the code `switch()` already uses and returns what happened; `Bridge` logs it and posts a macOS notice. The panel shows the last switch, by hand or automatic, on one styled line in the account strip.

**Tech Stack:** Python 3 stdlib, pytest, one hand-written `page.html` (vanilla DOM, Phosphor icon paths), the Swift `agents-notifier` sender.

**Spec:** `docs/superpowers/specs/2026-09-18-account-autoswitch-design.md`

## Global Constraints

- stdlib only; no new dependency.
- Constants, verbatim from the spec: `SWITCH_THRESHOLD = 90`, `SWITCH_MARGIN_POINTS = 10`, `TIE_POINTS = 5`, `SWITCH_COOLDOWN_SECONDS = 300`, `PICKUP_SECONDS = 60`, `PROJECTION_HORIZON_SECONDS = 600`, `RESET_NEAR_SECONDS = 600`, `RATE_MIN_SECONDS = 60`; a target reading older than `POLL_FLOOR_SECONDS` (180) is read again.
- No model is named in code: the Fable limit arrives through `models`.
- Setting `auto_switch`, default `False`. No threshold control, no strategy selector.
- TDD, one test then its code. Expected values are the literals in the spec's table, never recomputed from the code under test.
- Fixtures use `alice`, `bob`, `example.com`, `acct-N` only.
- Every source file keeps its two `ABOUTME:`-style opening lines as they are; comments say what the code does, never what it used to do.
- Run the suite as `python3 -m pytest -q > /tmp/as.out 2>&1; echo $?; tail -3 /tmp/as.out`, never `| tail && ...`.
- Panel taste (memory `feedback_panel-visual-taste`): no left accent bars, plain tint hovers, no rotating or popping shapes; icons only from Phosphor.
- Work on branch `feat/account-autoswitch`, cut from `design/account-autoswitch`.

## Files

- `accounts.py`: the decision functions after `read_now_states`; `record` keeps the earlier reading; `AccountMeters` gains `last_switch`, `tick(now, auto=False)` returning events, and `_switch_locked`.
- `tests/test_autoswitch.py` (new): the pure decision tests.
- `tests/test_meters.py`, `tests/test_meter_loop.py`: `record` and loop changes.
- `sidebar.py`: `auto_switch` default, `switch_notice_argv`, `Bridge.read_accounts` passes the setting and reports events.
- `tests/test_notify.py`, `tests/test_settings.py`: notice argv, the default.
- `page.html`: the setting row and the switch line.
- `docs/accounts.md`, `docs/accounts-design.md`, `README.md`.

---

### Task 1: The binding figure and the burn rate

**Files:**
- Modify: `accounts.py` (after `read_now_states`, about line 226; `record`, about line 807)
- Create: `tests/test_autoswitch.py`
- Modify: `tests/test_meters.py`

**Interfaces:**
- Produces: `binding(usage, now) -> {"figure": float, "window": str, "resets_at": float|None} | None`; `burn_rates(earlier_usage, earlier_at, usage, fetched_at) -> {window_name: points_per_second}`; `runs_out(usage, rates) -> {"window": str, "seconds": float} | None` (seconds counted from the reading); `record(...)` results gain `earlier_usage`, `earlier_at`, `tried_at`. Window names are `"5-hour"`, `"weekly"`, and a model's own `name`.

- [ ] **Step 1: Write the failing tests**

```python
"""Deciding when the daemon switches accounts on its own, and to which.

Pure: readings and the clock are passed in, so each case is a worked example.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from accounts import binding, burn_rates, runs_out

NOW = 1_000_000
HOUR, DAY = 3600, 86400


def usage(five, seven, fable, five_reset=NOW + 4 * HOUR, week_reset=NOW + 3 * DAY):
    return {"five_hour": {"used": five, "resets_at": five_reset},
            "seven_day": {"used": seven, "resets_at": week_reset},
            "models": [{"name": "Fable", "used": fable, "resets_at": week_reset}]}


def test_the_binding_figure_is_the_fullest_window_and_says_which():
    assert binding(usage(30, 40, 95), NOW) == {
        "figure": 95, "window": "Fable", "resets_at": NOW + 3 * DAY}


def test_a_reading_whose_window_has_since_reset_says_nothing():
    assert binding(usage(20, 20, 100, week_reset=NOW - 1), NOW) is None


def test_no_reading_has_no_binding_figure():
    assert binding(None, NOW) is None


def test_a_window_that_rose_has_a_rate_in_points_a_second():
    rates = burn_rates(usage(74, 10, 10), NOW - 120, usage(80, 10, 10), NOW)
    assert rates == {"5-hour": 0.05, "weekly": 0.0, "Fable": 0.0}


def test_a_window_that_reset_between_readings_has_no_rate():
    earlier = usage(95, 10, 10, five_reset=NOW - 30)
    assert "5-hour" not in burn_rates(earlier, NOW - 120, usage(2, 10, 10), NOW)


def test_readings_under_a_minute_apart_give_no_rates():
    assert burn_rates(usage(74, 10, 10), NOW - 59, usage(80, 10, 10), NOW) == {}


def test_a_fall_is_not_a_negative_rate():
    assert burn_rates(usage(80, 10, 10), NOW - 120, usage(74, 10, 10), NOW)["5-hour"] == 0.0


def test_a_rising_window_runs_out_when_its_rate_carries_it_to_100():
    assert runs_out(usage(80, 10, 10), {"5-hour": 0.05}) == {"window": "5-hour", "seconds": 400.0}


def test_a_full_window_has_already_run_out():
    assert runs_out(usage(30, 30, 100), {}) == {"window": "Fable", "seconds": 0.0}


def test_a_window_that_resets_before_it_fills_does_not_run_out():
    soon = usage(80, 10, 10, five_reset=NOW + 300)
    assert runs_out(dict(soon, fetched_at=NOW), {"5-hour": 0.05}) is None


def test_nothing_rising_never_runs_out():
    assert runs_out(usage(92, 10, 10), {}) is None
```

`runs_out` needs the reading's time to compare against `resets_at`; it reads it from `usage["fetched_at"]` when present, and the decision function (Task 2) passes `dict(usage, fetched_at=fetched)`.

- [ ] **Step 2: Run them and watch them fail**

Run: `python3 -m pytest tests/test_autoswitch.py -q > /tmp/as.out 2>&1; echo $?; tail -3 /tmp/as.out`
Expected: exit 2, `ImportError: cannot import name 'binding'`.

- [ ] **Step 3: Write the functions** in `accounts.py`, after `read_now_states`:

```python
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
```

- [ ] **Step 4: Run them and watch them pass**

Run: `python3 -m pytest tests/test_autoswitch.py -q > /tmp/as.out 2>&1; echo $?; tail -3 /tmp/as.out`
Expected: exit 0, `11 passed`.

- [ ] **Step 5: `record` keeps the earlier reading.** Add to `tests/test_meters.py`:

```python
def test_record_keeps_the_reading_before_this_one_and_when_it_tried():
    first = record(None, "ok", USAGE, now=0, jitter=0)
    second = record(first, "ok", moved(USAGE, 2), now=180, jitter=0)
    assert (second["earlier_usage"], second["earlier_at"], second["tried_at"]) == (USAGE, 0, 180)


def test_a_failed_reading_keeps_both_readings_and_moves_only_the_attempt():
    first = record(None, "ok", USAGE, now=0, jitter=0)
    second = record(first, "ok", moved(USAGE, 2), now=180, jitter=0)
    third = record(second, "failed", None, now=400, jitter=0)
    assert (third["earlier_at"], third["fetched_at"], third["tried_at"]) == (0, 180, 400)
```

and change the expected dict in `test_record_keeps_a_first_good_reading_and_waits_the_floor` to:

```python
    assert record(None, "ok", USAGE, now=0, jitter=0) == {
        "interval": 180, "next_at": 180, "outcome": "ok", "usage": USAGE, "fetched_at": 0,
        "earlier_usage": None, "earlier_at": None, "tried_at": 0}
```

Run `python3 -m pytest tests/test_meters.py -q`; expect the three to fail on the missing keys. Then in `record`, replace the `return` with:

```python
    return {"interval": schedule["interval"], "next_at": schedule["at"], "outcome": outcome,
            "usage": usage if fresh else previous["usage"],
            "fetched_at": now if fresh else previous["fetched_at"],
            "earlier_usage": previous["usage"] if fresh else previous.get("earlier_usage"),
            "earlier_at": previous["fetched_at"] if fresh else previous.get("earlier_at"),
            "tried_at": now}
```

Run again; expect all of `tests/test_meters.py` to pass. Fix any other test in the suite that compares a whole `record` result.

- [ ] **Step 6: Commit**

```bash
git add accounts.py tests/test_autoswitch.py tests/test_meters.py
git commit -m "Accounts: a reading's fullest window, and how fast each window is filling"
```

---

### Task 2: The decision

**Files:**
- Modify: `accounts.py` (after `runs_out`)
- Modify: `tests/test_autoswitch.py`

**Interfaces:**
- Consumes: `binding`, `burn_rates`, `runs_out`, the `record` state keys from Task 1.
- Produces: `switch_decision(active_id, states, accounts, now, last_switch=None) -> dict`, one of `{"act": "stay"}`, `{"act": "read", "account_id": str}`, `{"act": "switch", "account_id": str, "why": str}`, `{"act": "blocked", "why": str}` (`"every account is full"` or `"the other accounts cannot be read"`). `last_switch` is `{"at": float, ...}` or None. `ACTIVE_READING_MAX_AGE_SECONDS = ACTIVE_CEILING_SECONDS + 30`.

- [ ] **Step 1: Write the first failing test** (one row of the spec's table; add the rest one at a time in Step 5):

```python
from accounts import switch_decision


def state(reading, fetched_at=NOW, earlier=None, earlier_at=None, outcome="ok", tried_at=None):
    return {"usage": reading, "fetched_at": fetched_at, "outcome": outcome,
            "earlier_usage": earlier, "earlier_at": earlier_at,
            "tried_at": fetched_at if tried_at is None else tried_at, "next_at": fetched_at + 180}


A, B, C = ({"id": "acct-1"}, {"id": "acct-2"}, {"id": "acct-3"})


def decide(states, accounts=(A, B, C), last_switch=None):
    return switch_decision("acct-1", states, list(accounts), NOW, last_switch)


def test_a_full_active_account_moves_to_the_emptiest_one():
    states = {"acct-1": state(usage(92, 40, 30)),
              "acct-2": state(usage(70, 60, 50, week_reset=NOW + 2 * HOUR)),
              "acct-3": state(usage(20, 20, 20, week_reset=NOW + 4 * DAY))}
    assert decide(states) == {"act": "switch", "account_id": "acct-3", "why": "5-hour at 92%"}
```

- [ ] **Step 2: Run it and watch it fail** with `ImportError: cannot import name 'switch_decision'`.

- [ ] **Step 3: Write the function:**

```python
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

    if emergency:
        fit = [c for c in candidates if c[1]["figure"] < mine["figure"]]
    else:
        fit = [c for c in candidates if c[1]["figure"] < SWITCH_THRESHOLD
               and c[1]["figure"] <= mine["figure"] - SWITCH_MARGIN_POINTS]
    if not fit:
        if any(c[1]["figure"] < mine["figure"] for c in candidates):
            return STAY
        why = "the other accounts cannot be read" if passed_over else "every account is full"
        return {"act": "blocked", "why": why}
    lowest = min(c[1]["figure"] for c in fit)
    tied = [c for c in fit if c[1]["figure"] - lowest <= TIE_POINTS]
    target = min(tied, key=lambda c: (c[1]["resets_at"] is None, c[1]["resets_at"] or 0, c[1]["figure"]))
    return {"act": "switch", "account_id": target[0], "why": _why(mine, out, age)}
```

- [ ] **Step 4: Run it and watch it pass.**

- [ ] **Step 5: Add the remaining rows, one at a time, running after each.** Each is a row of the spec's table; the expected value is the table's, written here as a literal. If a row fails, the function is wrong or the row is: say which before changing either.

```python
def test_an_account_with_its_fable_limit_spent_is_not_a_target():
    states = {"acct-1": state(usage(30, 40, 95)), "acct-2": state(usage(20, 20, 100)),
              "acct-3": state(usage(60, 50, 70))}
    assert decide(states) == {"act": "switch", "account_id": "acct-3", "why": "Fable at 95%"}


def test_a_sooner_reset_alone_moves_nothing():
    states = {"acct-1": state(usage(30, 30, 20, week_reset=NOW + 6 * DAY)),
              "acct-2": state(usage(20, 20, 20, week_reset=NOW + HOUR))}
    assert decide(states, (A, B)) == STAY_ACT


def test_between_near_equal_targets_the_sooner_reset_wins():
    states = {"acct-1": state(usage(92, 10, 10)),
              "acct-2": state(usage(40, 40, 40, five_reset=NOW + 5 * DAY, week_reset=NOW + 5 * DAY)),
              "acct-3": state(usage(42, 38, 41, five_reset=NOW + DAY, week_reset=NOW + DAY))}
    assert decide(states)["account_id"] == "acct-3"


def test_a_window_about_to_reset_is_waited_out():
    states = {"acct-1": state(usage(92, 10, 10, five_reset=NOW + 300)), "acct-2": state(usage(20, 20, 20))}
    assert decide(states, (A, B)) == STAY_ACT


def test_a_window_on_course_for_100_moves_before_the_threshold():
    rising = state(usage(80, 10, 10), earlier=usage(74, 10, 10), earlier_at=NOW - 120)
    assert decide({"acct-1": rising, "acct-2": state(usage(20, 20, 20))}, (A, B)) == {
        "act": "switch", "account_id": "acct-2", "why": "5-hour on course for 100% in 7 min"}


def test_a_target_less_than_ten_points_better_is_not_worth_the_move():
    states = {"acct-1": state(usage(95, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B)) == STAY_ACT


def test_nothing_moves_while_the_last_switch_is_still_landing():
    states = {"acct-1": state(usage(100, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B), last_switch={"at": NOW - 59}) == STAY_ACT


def test_a_full_account_is_left_inside_the_cooldown_for_anything_emptier():
    states = {"acct-1": state(usage(100, 10, 10)), "acct-2": state(usage(88, 10, 10))}
    assert decide(states, (A, B), last_switch={"at": NOW - 120}) == {
        "act": "switch", "account_id": "acct-2", "why": "5-hour at 100%"}


def test_the_cooldown_holds_an_ordinary_move():
    states = {"acct-1": state(usage(92, 10, 10)), "acct-2": state(usage(20, 20, 20))}
    assert decide(states, (A, B), last_switch={"at": NOW - 120}) == STAY_ACT


def test_a_target_read_long_ago_is_read_again_first():
    states = {"acct-1": state(usage(92, 10, 10)), "acct-2": state(usage(20, 20, 20), fetched_at=NOW - 400)}
    assert decide(states, (A, B)) == {"act": "read", "account_id": "acct-2"}


def test_a_target_whose_window_has_reset_is_read_again_first():
    spent = state(usage(20, 20, 100, week_reset=NOW - 60), fetched_at=NOW - 400)
    assert decide({"acct-1": state(usage(92, 10, 10)), "acct-2": spent}, (A, B)) == {
        "act": "read", "account_id": "acct-2"}


def test_a_target_that_was_just_tried_and_is_still_old_is_passed_over():
    tried = state(usage(20, 20, 20), fetched_at=NOW - 400, outcome="failed", tried_at=NOW - 20)
    assert decide({"acct-1": state(usage(92, 10, 10)), "acct-2": tried}, (A, B)) == {
        "act": "blocked", "why": "the other accounts cannot be read"}


def test_nowhere_emptier_is_said_not_acted_on():
    states = {"acct-1": state(usage(96, 10, 10)), "acct-2": state(usage(97, 10, 10)),
              "acct-3": state(usage(5, 5, 5))}
    accounts = (A, B, dict(C, needsLogin=True))
    assert decide(states, accounts) == {"act": "blocked", "why": "every account is full"}


def test_an_old_reading_of_the_active_account_decides_nothing():
    states = {"acct-1": state(usage(99, 10, 10), fetched_at=NOW - 400), "acct-2": state(usage(5, 5, 5))}
    assert decide(states, (A, B)) == STAY_ACT
```

with `STAY_ACT = {"act": "stay"}` beside `NOW`. The projected row's minutes: 80 rising 0.05 points a second fills in 400 s, which is 6.67 minutes, rounded to 7.

- [ ] **Step 6: Watch one test fail by breaking the code.** In a copy (`cp accounts.py /tmp/accounts.keep`), change `SWITCH_MARGIN_POINTS = 10` to `0`, run `tests/test_autoswitch.py`, and confirm `test_a_target_less_than_ten_points_better...` fails. Restore with `cp /tmp/accounts.keep accounts.py`. Never `git checkout` the file.

- [ ] **Step 7: Commit**

```bash
git add accounts.py tests/test_autoswitch.py
git commit -m "Accounts: when to leave the active account, and for which"
```

---

### Task 3: The meter loop carries a decision out

**Files:**
- Modify: `accounts.py` (`meters_snapshot`, `AccountMeters`)
- Modify: `tests/test_meters.py`, `tests/test_meter_loop.py`

**Interfaces:**
- Consumes: `switch_decision` from Task 2.
- Produces: `AccountMeters.tick(now, auto=False) -> list[dict]`, events `{"kind": "switched", "name": str, "why": str}`, `{"kind": "blocked", "why": str}`, `{"kind": "refused", "why": str}`; `AccountMeters.last_switch`; snapshot key `"last_switch": {"at", "to", "why", "auto"} | None` where `to` is the target's display name.

- [ ] **Step 1: Failing test for the snapshot**, in `tests/test_meters.py`:

```python
def test_the_snapshot_names_the_last_switch():
    last = {"at": 500, "from": "acct-1", "to": "acct-2", "why": "Fable at 98%", "auto": True}
    snap = meters_snapshot([A1, A2], {}, active_id="acct-2", emails={"acct-2": "bob@example.com"},
                           last_switch=last)
    assert snap["last_switch"] == {"at": 500, "to": "bob@example.com", "why": "Fable at 98%", "auto": True}
```

Update the whole-dict assertion at the `error="store is not valid JSON"` test to include `"last_switch": None`. Run; expect `TypeError: unexpected keyword argument 'last_switch'`.

- [ ] **Step 2: Implement.** `meters_snapshot(accounts, states, active_id, error=None, emails=None, last_switch=None)`; before the `return`:

```python
    shown = None
    if last_switch:
        target = next((a for a in accounts if a["id"] == last_switch["to"]), {"id": last_switch["to"]})
        shown = {"at": last_switch["at"], "to": _name(target, emails.get(target["id"])),
                 "why": last_switch["why"], "auto": last_switch["auto"]}
    return {"active": active_id, "accounts": shaped, "error": error, "last_switch": shown}
```

Run `tests/test_meters.py`; expect pass.

- [ ] **Step 3: Failing loop tests**, in `tests/test_meter_loop.py`. The scratch tokens were never issued, so a real switch is refused at its refresh; that refusal is the path this test can run for real. The switch that succeeds is covered by `tests/test_switch_run.py` and by the live check in Task 6.

```python
def _reading(five, now):
    return {"usage": {"five_hour": {"used": five, "resets_at": now + 9000}, "seven_day": None, "models": []},
            "fetched_at": now, "tried_at": now, "outcome": "ok", "interval": 300,
            "next_at": now + 9000, "earlier_usage": None, "earlier_at": None}


def _meters_with_readings(world, tmp_path, active_five):
    from accounts import login_item
    write_secret(SCRATCH_SERVICE, world["live"], _credential("live"))
    ids = [a["id"] for a in world["accounts"]]
    write_secret(SCRATCH_SERVICE, login_item(ids[1]), json.dumps({"accountUuid": "uuid-other"}))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    meters = AccountMeters(world["store"], SCRATCH_SERVICE, (SCRATCH_SERVICE, world["live"]),
                           world["claude_json"], claude_dir=str(claude_dir))
    meters.states = {ids[0]: _reading(active_five, 1000), ids[1]: _reading(5.0, 1000)}
    return meters


def test_a_pass_with_switching_off_leaves_a_full_account_alone(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=95.0)
    assert meters.tick(now=1000) == []
    assert load_store(world["store"])[1].get("needsLogin") is None


def test_a_pass_with_switching_on_tries_the_switch_and_reports_a_refusal(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=95.0)
    events = meters.tick(now=1000, auto=True)
    assert events == [{"kind": "refused", "why": "log in to home again"}]
    assert load_store(world["store"])[1]["needsLogin"] is True
    assert meters.tick(now=1030, auto=True) == [{"kind": "blocked", "why": "every account is full"}]
    assert meters.tick(now=1060, auto=True) == [], "said once, not every pass"


def test_a_pass_with_switching_on_leaves_a_roomy_account_alone(world, tmp_path):
    meters = _meters_with_readings(world, tmp_path, active_five=40.0)
    assert meters.tick(now=1000, auto=True) == []
```

Run; expect `TypeError: tick() got an unexpected keyword argument 'auto'`.

- [ ] **Step 4: Implement in `AccountMeters`.** In `__init__` add `self.last_switch = None` and `self._said = None`. Replace `tick` and `switch`, and have `_tick` end by passing `last_switch=self.last_switch` to `meters_snapshot`:

```python
    def tick(self, now, auto=False):
        """Read what is due; with `auto`, leave a full account. -> what happened, for the log."""
        with self._one_at_a_time:
            self._tick(now)
            return self._decide(now) if auto else []

    def _decide(self, now):
        accounts = load_store(self.store_path)
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
```

`_one_at_a_time` is a plain `threading.Lock`, so `_decide` must call `_tick` and `_switch_locked`, never `tick` or `switch`. The refusal test's second pass reads `blocked` because the refused target is now `needsLogin` and nothing else is stored.

- [ ] **Step 5: Run** `python3 -m pytest tests/test_meter_loop.py tests/test_meters.py tests/test_autoswitch.py -q`; expect pass. The loop tests touch the network and Keychain and may take several seconds.

- [ ] **Step 6: Commit**

```bash
git add accounts.py tests/test_meters.py tests/test_meter_loop.py
git commit -m "Accounts: the meter loop leaves a full account when asked to"
```

---

### Task 4: The daemon: setting, log and notice

**Files:**
- Modify: `sidebar.py` (`DEFAULT_SETTINGS` about line 82; beside `notify_argv` about line 195; `Bridge.read_accounts` about line 2520; `Bridge.account_op` about line 2502)
- Modify: `tests/test_settings.py`, `tests/test_notify.py`

**Interfaces:**
- Consumes: `AccountMeters.tick(now, auto) -> list[dict]` from Task 3.
- Produces: setting key `auto_switch`; `switch_notice_argv(app, name, why) -> list[str]`; `switch_log_line(event) -> str`.

- [ ] **Step 1: Failing tests.** In `tests/test_settings.py`:

```python
def test_switching_accounts_automatically_is_off_until_asked_for():
    assert DEFAULT_SETTINGS["auto_switch"] is False
```

In `tests/test_notify.py` (import `switch_notice_argv`, `switch_log_line` from `sidebar`):

```python
def test_an_automatic_switch_posts_one_plain_notice_under_its_own_id():
    assert switch_notice_argv("/Apps/Agents.app", "bob@example.com", "Fable at 98%") == [
        "/Apps/Agents.app/Contents/MacOS/agents-notifier", "post", "--id", "account-switch",
        "--title", "Switched to bob@example.com", "--body", "Fable at 98%"]


def test_each_account_event_reads_as_one_log_line():
    assert switch_log_line({"kind": "switched", "name": "bob@example.com", "why": "Fable at 98%"}) == \
        "auto-switch -> bob@example.com (Fable at 98%)"
    assert switch_log_line({"kind": "blocked", "why": "every account is full"}) == \
        "auto-switch: nowhere to go, every account is full"
    assert switch_log_line({"kind": "refused", "why": "log in to home again"}) == \
        "auto-switch refused: log in to home again"
```

Run; expect `KeyError: 'auto_switch'` and an `ImportError`.

- [ ] **Step 2: Implement.** Add `"auto_switch": False,` to `DEFAULT_SETTINGS` after `"notify_done"`, with the comment `# Leave an account that is filling up, without being asked.` Check how `load_settings` clamps: a boolean key needs whatever the other booleans have there, and nothing more. After `notify_argv`:

```python
#: One standing notice for account switches: a second switch replaces the first.
SWITCH_NOTICE_ID = "account-switch"


def switch_notice_argv(app, name, why):
    """agents-notifier's argv for an account the daemon switched to on its own."""
    exe = str(Path(app) / "Contents" / "MacOS" / "agents-notifier")
    return [exe, "post", "--id", SWITCH_NOTICE_ID, "--title", f"Switched to {name}", "--body", why]


def switch_log_line(event):
    """One account event from the meter loop, as the log says it."""
    if event["kind"] == "switched":
        return f"auto-switch -> {event['name']} ({event['why']})"
    if event["kind"] == "blocked":
        return f"auto-switch: nowhere to go, {event['why']}"
    return f"auto-switch refused: {event['why']}"
```

In `Bridge.read_accounts`, replace the `tick` call:

```python
                auto = bool(load_settings()["auto_switch"])
                events = await asyncio.to_thread(self.meters.tick, time.time(), auto)
                for event in events:
                    self.log(switch_log_line(event))
                    if event["kind"] == "switched":
                        await self.notify_switch(event["name"], event["why"])
```

and add beside `notify`:

```python
    async def notify_switch(self, name, why):
        """Say that the daemon changed the login, since nobody clicked anything."""
        settings = load_settings()
        argv = switch_notice_argv(NOTIFIER_APP, name, why)
        if not settings["notify"] or settings["muted"] or not os.access(argv[0], os.X_OK):
            return
        try:
            poster = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except OSError as error:
            self.log(f"notify switch: {error!r}")
            return
        asyncio.ensure_future(poster.wait())
```

Before writing `notify_switch`, read how `announce` in `page.html` and `Bridge.notify` treat `muted` and `notify` today and match it; if `muted` silences sound only, drop it from the condition. The sender removes its notice when its parent dies and takes it down on SIGTERM, so the poster is left running and reaped by `poster.wait()`.

- [ ] **Step 3: Run** `python3 -m pytest tests/test_settings.py tests/test_notify.py tests/test_server.py -q`; expect pass.

- [ ] **Step 4: Commit**

```bash
git add sidebar.py tests/test_settings.py tests/test_notify.py
git commit -m "Daemon: a setting to leave a full account, a log line and a notice when it does"
```

---

### Task 5: The panel: the setting and the switch line

**Files:**
- Modify: `page.html` (`SETTING_ROWS` about line 2890; `.acct-status` CSS about line 1106; `accountNotice` uses about lines 2114-2123, 2232; `paintAccounts`)

**Interfaces:**
- Consumes: snapshot `accounts.last_switch = {at, to, why, auto} | null` from Task 3; setting `auto_switch` from Task 4.

The line that appears after a switch today is `accountNotice`: unstyled text, `switched to <name>; running sessions pick it up within about 30 s`, cut off by an ellipsis at panel width, and never cleared. The owner asked for it to look better. It becomes the one place a switch is shown, by hand or automatic.

- [ ] **Step 1: The setting row.** In `SETTING_ROWS`, after the Focus rows:

```js
  {head: "Accounts"},
  {k: "auto_switch", label: "Switch before a limit"},
```

- [ ] **Step 2: Variants before building.** UI guesses in this project get corrected, so show first. Build a static lab page in the scratchpad at the panel's real width (380px, `zoom: 1`, light and dark), with the account strip and three treatments of the line, each for a manual switch, an automatic one, and a refusal:
  - **A, two quiet lines:** Phosphor `arrows-left-right` 12px, `Switched to home` in `--fg` 500, the age right-aligned with the clock icon as `.task-age` does; under it in `--dim` 11px the reason (`Fable at 98%`) or, for a manual switch, `sessions pick it up in about 30 s`. Wraps instead of truncating.
  - **B, one line with a chip:** `Switched to home` then a tint chip (`auto`) in the same recipe as the existing `.word` chips, reason in the tooltip and after a middot when it fits.
  - **C, a fading line:** as A, but it fades out after 60 s for a manual switch and stays for an automatic one until the next snapshot in which a person has opened the panel.
  A refusal uses `--warn` text and the Phosphor `warning` icon, no fill. No left bar, no motion beyond an opacity fade.
  Open it in the browser and ask the owner for a letter with `AskUserQuestion`. Do not proceed without one.

- [ ] **Step 3: Build the chosen treatment.** One function, `switchLine(snapshotAccounts)`, returns the element or null: a pending or failed local action (`accountNotice`, which now holds `{kind: "pending"|"refused"|"info", text}`) wins, else `last_switch` from the snapshot. The age is worked out from `last_switch.at` on each paint. Replace the three `acct-status` appends of `accountNotice` with it. The success branch of the Switch click sets `accountNotice = null`, since the snapshot's `last_switch` now says it. Icons come from Phosphor regular, `fill: currentColor`, 12px.

- [ ] **Step 4: Check it.** `node --check` on the extracted script, as the repo has no JavaScript test harness. Then measure in the WKWebView harness at 380px in both themes: the line's text is not truncated (`scrollWidth <= clientWidth`), its contrast is at least 4.5:1 (add the pair to `tests/test_page_contrast.py` if a new token is introduced), and the strip's height does not jump between the pending and the settled state. The harness never fills `#groups`, but the account strip paints, which is all this needs.

- [ ] **Step 5: Commit**

```bash
git add page.html tests/test_page_contrast.py
git commit -m "Page: a switch says where it went and why, on a line made for it"
```

---

### Task 6: Docs, the whole suite, and the live check

**Files:**
- Modify: `docs/accounts.md`, `docs/accounts-design.md:164-165`, `README.md` (settings table), `docs/superpowers/specs/2026-09-18-account-autoswitch-design.md` (`projected` is `runs_out`; `record` also keeps `tried_at`)

- [ ] **Step 1: Docs.** `docs/accounts.md` gains a section "Switching on its own": what triggers it (90%, or on course for 100% within ten minutes), that the Fable limit counts, how it picks, the cooldown, what is shown, that it is off by default, and one sentence: run this or `cswap auto`, not both, since two engines would trade the login between them. `docs/accounts-design.md`: replace "Not built: auto-switching near a limit. cswap's `auto` keeps doing that if it is on, and the panel reflects the result." with a pointer to the spec. README settings table: one row. All prose that ships goes through `/write-as-me` and Vale (`vale --config ~/.claude/vale/.vale.ini --output=line --no-wrap <file>`).

- [ ] **Step 2: The whole suite.**

Run: `python3 -m pytest -q > /tmp/as.out 2>&1; echo $?; tail -3 /tmp/as.out`
Expected: exit 0, no failures, and no output other than the pass line.

- [ ] **Step 3: Commit, then deploy locally.** `./install.sh` (never piped into `head`), `cmp` the installed hook copy, restart the daemon, reopen the panel (the port changes).

- [ ] **Step 4: Live check with the owner.** With the setting on, the active account at Fable 98% on 2026-09-18 should be left for the empty account on the first pass: expect the `auto-switch -> ...` line in `~/.claude/agents-sidebar-status/daemon.log`, the notice, the green check moving, and the switch line. Confirm with `/status` in a session after 30 s. If the figures have moved under 90 by then, say so and wait for a real crossing rather than lowering the threshold to force one.

- [ ] **Step 5: Merge** per `superpowers:finishing-a-development-branch`; the release question from the handoff (everything after `2026.09.10` is unreleased) goes to the owner afterwards.
