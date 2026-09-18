# Automatic account switching

Approved 2026-09-18, after reading claude-swap 0.22's `autoswitch.py` and a
design review by Codex. The panel already reads every account's limits and
switches on a click; this adds the decision to switch without one.

## Goals, in order

1. **Continuity.** A running session never stalls at a limit.
2. **The Fable limit counts.** An account whose Fable weekly limit is spent is
   full, whatever its five-hour and weekly windows say.
3. **Little quota lost at a reset**, only where it costs no extra switch.

A switch is not free: a running Claude Code takes about 30 seconds to pick the
new login up from the Keychain, and requests in flight keep charging the old
account. So the policy makes as few switches as continuity allows, and a reset
date alone never causes one.

## The figure

An account's **binding figure** is `worst_window(usage)`: the highest
percentage used across `five_hour`, `seven_day` and every entry of `models`.
Measured on 2026-09-18 across three accounts: every account reports a Fable
entry, at 0 when unused, and Fable is the only model the endpoint lists. So
the Fable limit is part of the figure with no model named in the code and no
setting to turn it on.

Its **binding window** is the window that figure came from, and its **binding
reset** that window's `resets_at`.

A window whose `resets_at` has passed since the reading says nothing about now.
An account holding one is **unread** until its next reading, and the engine
asks for that reading at once.

## Trigger

Evaluated once per meter tick, after the active account's reading, and only
when the setting is on, two or more accounts are stored, and the active
account has a good reading no older than `ACTIVE_CEILING_SECONDS` plus one
tick.

The active account wants to leave when either holds:

- **Measured:** its binding figure is at or above `SWITCH_THRESHOLD` (90).
- **Projected:** its burn rate carries any window to 100 within
  `PROJECTION_HORIZON_SECONDS` (600, twice the active account's slowest
  reading interval, so one late reading is covered).

It stays after all when its binding reset is within `RESET_NEAR_SECONDS`
(600) and the projection to that reset stays under 100: the window returns
before it runs out, and staying costs no pickup gap.

### Burn rate

`record` keeps the previous good reading beside the current one
(`earlier_usage`, `earlier_at`). For each window present in both readings with
the same `resets_at`, at least `RATE_MIN_SECONDS` (60) apart, the rate is the
rise in points per second, never below zero. A window that reset between the
two readings, or with only one reading, has no rate, and the projection for it
is the measured figure. Only the active account is projected; an inactive
account is not being spent.

## Target

Candidates are stored accounts that are not active, do not need a login, and
are not unread. In order:

1. **Ordinary.** Binding figure under `SWITCH_THRESHOLD` and at least
   `SWITCH_MARGIN_POINTS` (10) under the active account's. The lowest figure
   wins; figures within `TIE_POINTS` (5) of the lowest are a tie, and the
   earliest binding reset wins it, so quota about to expire is spent first.
2. **Emergency**, only when the active account is at 100 or projected there
   within `PICKUP_SECONDS` (60): any candidate whose figure is under the
   active account's, lowest first, ties as above.
3. **Everything full.** When no candidate is under the active account's
   figure, the engine holds and says so once. It does not move between full
   accounts; the account whose window returns first is reached by rule 1 once
   that reset passes and its new reading lands.

Before a switch is made, a target whose reading is older than
`POLL_FLOOR_SECONDS` (180) is read again through the meter loop's own path, so
the 429 hold and the refresh gate still apply, and the decision is taken again
on the new figures. A target that cannot be read is dropped for this tick.

## Flapping

- `SWITCH_COOLDOWN_SECONDS` (300) between automatic switches. A switch made
  by hand starts the same cooldown.
- The emergency rule ignores the cooldown but not `PICKUP_SECONDS`: nothing
  moves again until the previous switch has had time to land.
- The margin makes an ordinary move one-way: the account just left is at or
  above 90, so it cannot be an ordinary target, and it is reachable again only
  through the emergency rule or after its reset.

The last automatic switch (`at`, `from`, `to`, `why`) lives in
`AccountMeters` memory. A daemon restart forgets the cooldown; the margin
still holds.

## What shows

- **Setting:** `auto_switch`, default off, one switch in the drawer's account
  card. No threshold control.
- **Notice:** one macOS notice through the existing sender,
  "Switched to `<name>`" with the reason as its body ("Fable at 98%",
  "5-hour at 91%", "5-hour on course for 100% in 6 min"). Follows the
  `notify` setting.
- **Log:** `Bridge.log` records every switch and its reason, and once per
  episode "nowhere to switch: every account is full" and "auto-switch
  refused: `<SwitchRefused text>`".
- The strip's green check moves as it does after a click.

## Shape

Pure, in `accounts.py`:

- `binding(usage, now)` returns `{figure, window, resets_at}` or None when
  unread.
- `burn_rates(earlier_usage, earlier_at, usage, fetched_at)` returns window
  name to points per second.
- `runs_out(usage, rates)` returns the first window to reach 100 at its rate
  and in how many seconds, or None when none does before its reset.
- `switch_decision(active_id, states, accounts, now, last_switch)` returns
  one of `{"act": "stay"}`, `{"act": "read", "account_id"}`,
  `{"act": "switch", "account_id", "why"}`, `{"act": "blocked", "why"}`.

`record` gains `earlier_usage`, `earlier_at` and `tried_at`, the last so a
target that failed to read is not asked again every tick. `AccountMeters.tick` takes
`auto=False`; when true it runs `switch_decision` after its readings, carries
out a `read` and decides again, carries out a `switch` through the code path
`switch()` uses (the `plan_switch` identity check and rollback stay), and
returns what it did so `Bridge` can log and notify. `Bridge` passes
`load_settings()["auto_switch"]`.

## Alongside cswap

`cswap auto` and cswap's menubar run the same kind of engine on the same
logins, with their own copy of each token. Two engines would trade the active
account between them. `docs/accounts.md` says to run one; the sentence in
`docs/accounts-design.md` that leaves switching to cswap is replaced by a
pointer here.

## Left out

- Switching under the threshold to spend an account that resets soon (cswap's
  `consume-first`): it buys quota with pickup gaps.
- Moving between full accounts toward the soonest reset (cswap's recovery
  axis, the source of its 47-switch oscillation).
- A threshold control, a strategy selector, per-model opt-in.
- Quarantine: a dead login is already `needsLogin` in the store.
- Projection for inactive accounts.

## Tests

Pure-function tests on worked tables, figures as (5h, 7d, Fable):

| Active | Others | Expected |
|---|---|---|
| A (92, 40, 30) | B (70, 60, 50) resets 2 h; C (20, 20, 20) resets 4 d | switch to C |
| A (30, 40, 95) | B (20, 20, 100); C (60, 50, 70) | switch to C |
| A (30, 30, 20) resets 6 d | B (20, 20, 20) resets 1 h | stay |
| A (92, 10, 10) | B (40, 40, 40) resets 5 d; C (42, 38, 41) resets 1 d | switch to C (tie, sooner reset) |
| A (92, 10, 10), 5h resets in 5 min, rate 0 | B (20, 20, 20) | stay |
| A (80, 10, 10), 5h rising 3 points a minute | B (20, 20, 20) | switch to B (projected) |
| A (95, 10, 10) | B (88, 10, 10) | stay (margin) |
| A (100, 10, 10), switched 60 s ago | B (88, 10, 10) | stay (pickup) |
| A (100, 10, 10), switched 120 s ago | B (88, 10, 10) | switch to B (emergency, inside cooldown) |
| A (92, 10, 10), switched 120 s ago | B (20, 20, 20) | stay (cooldown) |
| A (92, 10, 10) | B (20, 20, 20), read 400 s ago | read B |
| A (92, 10, 10) | B (20, 20, 100) whose Fable reset has passed | read B |
| A (96, 10, 10) | B (97, 10, 10); C needs login | blocked |

Also: `burn_rates` ignores a window that reset between readings and readings
under 60 s apart; `record` carries the earlier reading; `AccountMeters.tick`
with `auto=True` against a temp store switches, and with `auto=False` does
not; a `SwitchRefused` is reported, not raised.
