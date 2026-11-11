# API credits when every account is full

Approved 2026-11-09, after a design consult and six live probes against
Claude Code 2.1.319. Auto-switch moves sessions between subscription
accounts; when every account is full it can only say so. This adds one more
place to go: prepaid API credits, through one key, until a subscription has
room again.

## Goals, in order

1. **Continuity.** A session that would stop at a full account keeps working.
2. **Credits only while nothing else has room.** The API is a last resort,
   never a cheaper-looking target, and the fallback ends at the first reading
   that shows room.
3. **Nothing changes for an install that never turns it on.**
4. **Every effect is visible:** that sessions run on credits, roughly what they
   have spent, and what stops working while they do.

## What was measured

Throwaway sessions, `claude -p` in stream-json mode with `--no-session-persistence`.
Each row is a run, not a reading of the docs.

| Probe | Result |
|---|---|
| No `apiKeyHelper` | `apiKeySource: none`, the subscription login answers |
| Helper prints nothing, or exits 1 | The turn fails: "Your apiKeyHelper script is failing". No fall back to the login |
| Helper prints an invalid key | 10 retries on 401 `authentication_failed` over 256 s, then "Invalid API key"; the `StopFailure` hook fires with `error: "authentication_failed"` |
| Helper added to project settings mid-session | The next turn runs on `apiKeyHelper` |
| Helper removed again | The next turn is back on the login, and answers the failed turn's prompt too |
| Same add and remove in user settings (`CLAUDE_CONFIG_DIR` scratch folder, no login there) | `apiKeySource` goes `none` → `apiKeyHelper` → `none` with no restart; the turns themselves failed for want of a login, so this measures the source only |
| Helper in a `--settings` flag file | Read at start only; a running session ignores both edits |
| `ANTHROPIC_API_KEY=""` in the environment | Does not block the helper |
| A real key through the helper, Haiku, 44 turns in two sessions | About $0.020 spent from the organisation's promotional credit; the Console's month-to-date spend showed it within minutes. No workspace limit was set, so no refusal was tested |
| First turn of a session against later ones on the same key | $0.0041 against about $0.0004: the first turn pays to write the prompt cache |

From the docs: a plugin's settings honour only `agent` and `subagentStatusLine`;
no environment variable names the helper command; settings watching covers
user, project, local and managed settings.

The prompt cache belongs to the billing owner, so a flip from the login to
the key, or back, makes every session active within the cache's lifetime pay
once to write its whole conversation again, at the new owner's price. The
first-turn row is that cost for a short conversation; a long one scales with
its context.

So the only switch that reaches running sessions is the `apiKeyHelper` key in
a watched settings file, and the helper must be absent, not empty, while the
fallback is off.

## The exception to the settings.json rule

`install.sh` records why the panel never co-edits `~/.claude/settings.json`:
there is no lock and no owner field, and other tools rewrite the file from
templates. The statusline bridge is the one key the panel writes, once, on a
click. This feature writes one more key, `apiKeyHelper`, on its own, and is a
deliberate, narrow exception to that rule:

- Only that key changes; every other key is written back as read.
- The file is read, changed and replaced through `statusline.py`'s writer
  (temporary file, `os.replace`, keeping the file's mode, writing through a
  symlink to its target, and leaving non-ASCII text as it is), then read back
  and compared with the
  intended result. On a mismatch the step runs once more from a fresh read;
  a second mismatch stops it, leaves the file as it is, and shows the
  refusal.
- The panel owns a helper only when its command is exactly the one its
  record says it wrote, or this checkout's own shell-quoted helper command; a
  shared file name is not enough. A helper set by anything else is never
  touched, its command is never repeated in the panel, a notice or the log,
  and the fallback stays off and says why.
- Losing the key is safe: a template rewrite or a `chezmoi apply` that drops
  it sends sessions back to the subscription, where they were.

## The key

Each account may carry a key of its own, so the sessions of an account bill
the Console organisation that goes with it. A key lives in the Keychain beside
the account logins (`agents-sidebar-accounts`, account `api-key:<account id>`)
and nowhere else; removing an account removes its key. It enters through a
password field on that account's row in the settings card, crosses to the
daemon once over the panel's token-guarded endpoint, and is never sent back:
the page shows its last four characters. The accounts store keeps, per
account, those four characters and the account's spend cap.

Claude Code reads one `apiKeyHelper` for every session on the machine, so one
key is in use at a time. The fallback uses the active account's key; when that
account has none, or its key is refused or at its cap, the next account with a
usable key, in the accounts' list order. Moving from one key to another
changes the billing organisation, so every active session re-reads its
context once more; it happens at once, with a notice after it, since waiting
would only spend more on a key that is done.

The helper is a script in the repository, beside the statusline bridge, run
with the account id whose key it prints (`api-key-helper.sh <account id>`,
shell-quoted), and prints that item with `security find-generic-password -w`. It never runs from
the plugin copy, which is absent for a moment during an update.

The key is checked with one `GET /v1/models` when it is saved and before each
entry. A 401 or 403 refuses the entry; the measured cost of skipping the
check is a four-minute stall per turn. A refused entry holds until the blocked
state ends or a key is saved again, so a bad key is not asked about on every
tick. Any other answer (a 429, a 5xx, no connection) is no verdict on the key:
the fallback stays off with no hold, says so once, and tries again on the
next tick.

Each key has its own cap, set beside it (default $50), against what this
fallback has spent on that key. The spend cap needs the statusline bridge, the only source of each session's
cost: while it is not installed the switch cannot be turned on and an entry is
refused, and a bridge lost while the fallback is on ends it as the cap does.
Spend is tallied per session; a cost lower than the last one seen is a new
process of that session, and its cost adds from zero.

## Entry

Evaluated after each meter tick, when the setting `api_fallback` is on and a
key is stored. The fallback calls `switch_decision` itself, outside
`_decide`, so neither the `auto_switch` setting nor `_decide`'s two-account
minimum gates it: with one account, `switch_decision` finds no candidate and
answers `blocked`.

The fallback is due when `switch_decision` is `blocked` because every account
is full, or because every running model is full on every account: the moment
auto-switch would leave the active account and has nowhere to go. A `blocked`
that means "the other accounts cannot be read" never starts it: unknown is
not full.

A `blocked` that rests on a projection alone never starts it either. With
every account blocked as full, the active account's binding figure must be at
`SWITCH_THRESHOLD` (90) or more: an account on course for 100 at 85% can calm
down on the next reading, and a trip in and straight back costs every active
session two re-reads.

When it is due, a notice says so before anything changes: "Sessions move to
API credits", with the tokens they will re-read (the sum of the cards'
context figures for sessions active in the last five minutes) and a
**Not now** action. With no answer in `NOTICE_GRACE_SECONDS` (60) the
fallback starts. Not now leaves the sessions on the full account until the
blocked state ends and comes again.

Starting there, at the switch line and not at 100, puts continuity before the
last tenth of the subscription, as auto-switch does. What a session does when
it meets a subscription limit with no fallback in place was not measured.

## Exit

The fallback ends at the first good reading where an account sessions can run
on has room: its binding figure is under `SWITCH_THRESHOLD` (90), and it is
the active account, or, with auto-switch on, the candidate `switch_decision`
would switch to. An account that needs a login, or that auto-switch would not
move to, never ends it. Before the removal, a notice says "Sessions go back to the subscription",
with the tokens they will re-read there, and a **Not now** action; with no
answer in `NOTICE_GRACE_SECONDS` the removal goes ahead. Not now keeps the
sessions on credits and asks again in 30 minutes. With a candidate, the
switch and the removal are one step. Entry at `blocked` and exit only under 90 with a usable target is the
hysteresis; a window reset drops the figure far below the line. A `StopFailure` with `billing_error` or `authentication_failed` while
the fallback is on ends that key's part in it, with the reason shown, and so
does a key's spend passing its cap. The next usable key, if any, takes over;
when none is left, the helper comes out and sessions go back to the full
account, with "cap reached" or the error shown.

Those three exits leave every account still full, so entry would be due again
on the next tick and the helper would flip straight back, at the price of
another re-read. Each of them holds the fallback as Not now does: no entry
until the blocked state ends and comes again. Raising the cap in settings
lifts the cap's hold at once, and saving a key lifts a key's hold.

"Ends" and "room" are read from the active account's binding figure, or from
a `switch` decision to an account that needs no login, never from a decision
that merely is not `blocked`: `switch_decision` also stays put for a stale
reading, the minute after a switch and the cooldown. `switch_decision` names
why it is blocked in a field of its own (`full`, `model_full`,
`unreadable`), so the fallback never reads its English.

Whether the fallback is on, any hold, when it started, each session's spend
and the helper command last written are kept in `api-fallback.json` in the status folder, written before the
settings file changes, so a restart neither resets the cap nor loses a hold.
At daemon start, and on each tick, the settings file is brought in line with
that record: on in the record keeps the helper, anything else takes a
panel-owned helper out. When the record says on but the helper has gone from
the file (a template rewrite, a `chezmoi apply`), the file wins: the fallback
goes off, holds as after a cap, and the log says so; the daemon never writes
the key back against another tool. A restart while the fallback is on and accounts are
still full therefore costs no extra flip. The record is marked as writing
before the helper goes in and unmarked after, so a start that finds the mark
and no helper knows the missing helper as its own crash: off, no hold.

A daemon that stays down cannot enforce the cap, so the helper guards itself.
Each time Claude Code asks it for the key, it checks that the daemon named in
`endpoint.json` is alive (its pid, and only that field, is read). While it is,
the helper prints the key. When it is not, the helper prints the key once
more, so the turn in flight completes, takes its own `apiKeyHelper` entry out
of `~/.claude/settings.json` through the same key-only writer, and leaves an
`api-fallback-orphaned` marker in the status folder. Alive means a process
whose command runs this checkout's own `sidebar.py`. A helper that cannot
read the key from the Keychain takes itself out the same way and fails that
one turn, since it has no key to print. Sessions are back on the
subscription by their next key fetch. A daemon that starts and finds the
record on, the helper gone and the marker present goes off with no hold and
deletes the marker, so entry can come again through its notice; without the
marker, a missing helper is another tool's doing and holds as above. A daemon
that is alive but stuck is not caught by this check.

## What shows

- **Settings card, Accounts section:** the switch "When every account is full,
  use API credits", then one row per account with its key field (its last
  four characters once saved) and its spend cap in dollars, with what this
  fallback has spent on that key. The switch can be turned on once any
  account has a key. Under the switch, read live, a line names what it
  changes outside the panel: `apiKeyHelper` in `~/.claude/settings.json`
  while active, and that the file may be synced to other machines.
- **Accounts fold head:** while active, a chip "on API · ERPK · $1.84", naming
  whose key is in use, in place of
  the next-switch chip. The figure is the rise in each Claude session's
  `total_cost_usd` since entry, an estimate; the Console holds the true spend.
  The chip's title says what is off: claude.ai connectors and Remote Control.
- **The switch line** records each entry and exit as it records a switch.
- **A pending entry or exit** shows in the chip with its countdown and a
  Not now button, so the choice is there with macOS notices off too; the
  notice is the second place it shows.
- **A refused entry** (bad key, foreign helper) shows as the chip's alert
  colour with the reason, and as a notice once.

## Agent context

On the first prompt after each flip, the plugin's `UserPromptSubmit` handler
adds one line: "This session now runs on API credits; claude.ai connectors and
Remote Control are unavailable until it returns to the subscription." Or the
line for the way back. The daemon snapshot carries
`api_fallback: {on, since, spent_usd, why}` for other readers. No agent ever
sees the key.

## Shape

- `api_fallback.py`: the record (`off`, `entering`, `on`, `leaving`, with
  its hold, start time, each session's last cost and accumulated spend, flip
  count, the exact `apiKeyHelper` command last written, the `writing` mark
  saved before that write and cleared after it, and `retrying`, the reason an
  entry could not get a verdict on the key) and
  `step(record, reading, now) -> (record, effects)`, pure; the record's load
  and atomic save; the key's Keychain read and write; the validation call,
  whose `KeyProblem` separates a 401 or 403 (`refused`) from everything else
  (`unavailable`). The daemon carries out the effects (notice, helper in,
  helper out, log). A helper is the panel's only when its command is exactly the
  record's or this checkout's own (`owned_commands`).
- `statusline.py` gains `helper_command(path)`, the shell-quoted command,
  `set_api_key_helper(path, command, ours)` and `drop_api_key_helper(path, ours)`,
  beside the bridge's own functions. These keep the file's mode, write through
  a symlink to its target and leave non-ASCII text as it is.
- `api-key-helper.sh` at the repository root.
- `plugin/hooks/hooks.json` registers `StopFailure` to the existing handler.
- `uninstall.sh` drops the helper when it is the panel's by the same rule, and
  deletes the key unless logins are kept.
- The reading carries whether the statusline bridge is installed: the spend cap
  reads its costs from it, so the switch cannot turn on without it, entry is
  refused with a `no_bridge` hold, and a bridge lost while on ends the fallback
  as at the cap.

## Tests

The failure list comes first, and each item gets its test before its code:
blocked-unreadable starts nothing; a foreign helper is never touched; a
settings change between read and replace is not lost; a refused key never
reaches settings; a start with no record, or a record that is not on, leaves
no panel-owned helper; the helper with a dead daemon takes itself out and
leaves the marker, and with a live one changes nothing; a restart while on and still blocked keeps the helper,
the cap's baseline and any hold; an exit by the cap, `billing_error` or
`authentication_failed` does not re-enter while the blocked state lasts; the
exit waits for a reading under 90 on an account sessions can run on, never one
that needs a login; one account with auto-switch off still enters; a projection
alone never enters and a flat reading after an entry at 90 is not room; a foreign
helper, even one named `api-key-helper.sh`, survives ten ticks with the feature
off and on; a blank record with the setting off emits nothing; entry without the
bridge is refused and a bridge lost while on ends it; a restarted session's lower
cost adds from zero; a settings write keeps its mode, its symlink and its non-ASCII
text; a status other than 401 or 403 leaves the fallback off with no hold, retries
at each reading and says so once; the key's route runs off the event loop; a
helper that cannot read the key takes itself out and fails that turn; another
tool's command is never copied into anything shown or logged; only this
checkout's daemon counts as alive; a path with a space runs through the shell;
a crash mid-entry is not another tool's doing; an unchanged record is not saved;
a turn that ends in `StopFailure` goes idle with its error named until the next
prompt.

The six probes become `tests/live/` scripts against a scratch
`CLAUDE_CONFIG_DIR`, so the reload and the bad-key stall stay re-runnable
against each new Claude Code.

## Rulings

1. **Spend:** the Console's limits stay the hard cap (prepaid credits with
   auto-reload off, or a workspace spend limit), and the panel adds the soft
   cap above. Claude Code's own budget flag works in print mode only.
2. **Connectors and Remote Control:** the fallback proceeds and says so, in
   the chip's title and the agent context line.
3. **Concurrent writes to settings.json:** read back, compare, one retry,
   then refuse, as above.
4. **Credits running out:** handled through the `StopFailure` hook's
   `billing_error`, which Claude Code's hook schema lists; not measured. A
   live test runs once a workspace with a small spend limit exists.
5. **Notices:** before entry and before exit, each with Not now, as above.
   The cache re-read on each flip is the reason.
6. **Re-entry:** an exit by the cap, `billing_error` or
   `authentication_failed` holds until the blocked state ends, and the state
   behind that hold and the cap survives a daemon restart. The cap defaults
   to $50, and raising it lifts its hold.
7. **A daemon that stays down:** the helper checks the daemon is alive on
   each key fetch and takes itself out when it is not.
8. **Entry point:** the figure itself, at 90 or more; a projection alone never
   enters.
9. **A turn that ends in `StopFailure`:** the card goes idle, as after `Stop`,
   and its line names the error.
10. **A key per account:** the active account's key is used, then the other
    accounts' keys in list order; each key has its own cap.

## Left out

- Choosing the key order by hand: the accounts' list order is the order.
- Moving only some sessions to credits: the helper is global.
- Reading the credit balance: the API has no endpoint for it.
