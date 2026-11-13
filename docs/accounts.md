# Accounts and limits

Storing logins, switching between them, and reading the meters. The README has
the short version.

## Before you store anything

If cswap (claude-swap) runs on the same machine, both tools hold copies of the
same refresh tokens, and a refresh token works only once. Every refresh the
panel does spends cswap's copy, so cswap then shows those accounts as needing a
login.

Until you store an account, the limits come from the sessions' status lines:
5-hour and weekly, as thin bars with the percentage used and the time left
until the reset. If no session sends statusline data, the panel hides those lines instead of showing zero.
Here the 5-hour bar has a tick too, and a percentage turns warm once it passes
its tick and reaches 80%.

## Adding an account

1. Click **Add <your email>** to store the login Claude Code is using now. The
   button names that login; without one it reads **Log in to Claude Code first**.
2. The panel copies its credential into its own Keychain item
   (`agents-sidebar-accounts`) and lists the account in
   `~/.config/agents-sidebar/accounts.json`. The email stays in the Keychain
   next to the credential and never goes into that file.
3. For a second account, `/login` as it in Claude Code and click Add again.

## Keeping logins after uninstall

Uninstall deletes the panel's saved account logins by default: both
`~/.config/agents-sidebar/accounts.json` and the Keychain items it names,
each account's API key (`api-key:<account id>`) among them.
The Settings confirmation counts those logins, including ones that need a new
login. Turn on **Keep my account logins** to keep them. It starts off;
turning it on changes the message to say the logins stay.

From a terminal, run `agents-sidebar uninstall --keep-accounts`, or
`./uninstall.sh --keep-accounts` from the checkout. The flag keeps the same
store and Keychain items, and the command reports where they remain. The
panel's settings, state and other data still go, including account locks.
A later install can read the saved logins again.

Either way, uninstall takes the panel's `apiKeyHelper` (see API credits below)
out of `~/.claude/settings.json`. Another tool's `apiKeyHelper` stays, and
uninstall says so.

## Reading the meters

With accounts stored, the foot lists every account behind the Claude mark. The
one your sessions run on comes first, with a green check. Each shows its 5-hour
limit, its weekly limit, and every per-model weekly limit the account has, with
the time left until each resets (`14m`, `2h`, `1d 17h`; a folded tile shows only the first unit).

| What you see | What it means |
| --- | --- |
| Green bar | Under 70% of the window used |
| Amber bar | 70% or more used |
| Red bar and red percentage | 90% or more used |
| A red bar that pulses | The window reached 98% shown and has no room left. On the account your sessions run on it keeps pulsing until the window resets or you switch; on another account it pulses once. Never with Reduce motion on |
| A tick on a weekly line | Where an even spend across the week would be right now: fill short of it means you could spend more before the reset, past it means you run out first. None in the first day after a reset. The row's hover names the tick's figure and the gap |
| A warm percentage | 15 points or more past that tick |
| `as of 14:02` | The last reading failed; these are the figures from then |
| `log in to <name> again` | That account's login stopped working, or its stored copy is no longer in the Keychain. It clears once Claude Code runs on a new login to it, or when you Add it again while logged in |
| `reading...` | The first reading is on its way |
| `no reading yet` | The first reading failed; the panel tries again later |
| `can't refresh its login` | The panel could not renew that account's expired login token, though the server has not refused the login; it tries again with each reading. With an earlier reading it says `as of 14:02, can't refresh its login` |
| `not a stored login` | Claude Code runs on a login the panel has not stored |

The foot shows an account's nickname, or its email if it has none, or
`Account N` without either. Click a name to set a nickname: Enter saves, Esc
cancels, and an empty name goes back to the email.

Click **Accounts**, or anywhere in its head outside Auto-switch and its chip,
to fold the accounts. Folded, every
account and Codex sit side by side, a tile each, the account your sessions run
on first and marked with its check. A tile shows one bar, its fullest window,
with the even-spend tick, then the percentage, the window's short name (`5h`,
`wk`, `fab` for Fable) and the time to its reset; a reserve Codex draws on
counts with its plan's windows. An account's bar passes over a model limit at
100% on every account, which reads the same on every tile and which no switch
frees, and shows the fullest of its other windows; with no other window, the
full one shows. A reading that failed keeps its bar and says
`as of 14:02` in place of the reset. Hover a tile for every window it has,
and for when a model passed over returns, such as `Fable is at 100% on every
account; back when home resets in 15h 10m`. A
second click on the head opens the foot again, and you switch accounts from
there. The fold survives reloads and daemon restarts. With no stored login,
the Claude tile comes from your sessions' own readings. While the panel cannot
read the account store, the foot stays open to say why.

## Switching

Point at an account and click the **Switch** button over its bars, then click
**Confirm switch** within 4 seconds. The buttons show only while the login
Claude Code runs on is a stored one, and never on an account that needs a new
login. A switch that fails says `not switched: <reason>`. Running sessions pick
up the new account within about 30 seconds.

The panel first refreshes that account's token, which proves its login still
works. Then it swaps Claude Code's credential and the account in
`~/.claude.json` while holding Claude Code's own locks. If a step fails after a
write, the panel puts the old login back and says so.

Under the active account's bars, one line says where the last switch went, why,
and how long ago. A chip marks a switch the panel made on its own. When a move
to API credits or back (below) is newer than the last switch, the line says
`On API credits · <why>` or `Back on the subscription · <why>` instead. A move
back holds the line for an hour, then the line names the last switch again.

## Switching on its own

Off by default. The **Auto-switch** control above the accounts, shown once you
store two or more, lets the panel move your sessions between accounts so the
quota you have lasts, and so no session stops at a limit while another account
has room.

**Which limits count.** An account's figure is its fullest window among the
5-hour, the weekly, and the weekly limit of each model your Claude sessions and
their subagents run or ran in the last ten minutes. A Fable limit counts while
a session runs Fable, and not while every session has run only Opus for ten
minutes. A subagent counts from the moment it asks for its model, so one
refused at a full Fable limit still moves the account. An account the panel
leaves a full account for is judged on every model used in the last two hours, so a model
that runs in bursts never sends the sessions to an account whose limit for it
is spent, only to leave it on the next burst. A session whose model is not known yet counts
for nothing until it reports one, a few seconds after it starts; only when no
session has reported a model does every limit count. A model limit at 100% on every account decides nothing: no switch
can help it, so the other limits decide until the first one returns. The
folded bars pass over it the same way, with Auto-switch on or off.
If that model is the only one running, the panel stays put and says why once,
in `daemon.log`.

**Leaving a full account.** It leaves when that figure reaches 90%, or when the
rate it is filling at would reach 100% within ten minutes. It waits instead
when that window resets within ten minutes and would not fill first. It goes to
an account at least ten points better and under 90%; when none is, to one at
least three points emptier than the active one and under 90%. One over 90%
itself takes the sessions only once the active account is on course for 100%
within ten minutes: until then a move between two nearly full accounts buys a
few points and costs every session what a switch costs. It never goes to
an account whose own readings show it filling. An automatic move comes at least
five minutes after the last switch, by hand or automatic. The one exception is
an account about to hit 100%: the panel leaves it after only a minute, and then
any emptier account under 100% can take the sessions. Before it compares, the
panel reads another account again when that reading is older than three
minutes. When the active account's own reading failed or is older than 330
seconds, the panel stays put without asking for a new reading.

**Balancing before anything is full.** While the active account is under the
line, or at 90% or more in a window that resets within ten minutes, the panel
moves to another account when that one has at least 1.25 times the weekly
runway: the room left in its tightest weekly window, divided by the days until
that window resets. Quota that returns tomorrow is spent before quota that has
to last a week, so less of it resets unused. A balance goes only to an account
under 90% whose 5-hour window is under 70%, or whose plan has none, waits half an hour after any
switch, uses readings up to 15 minutes old without asking for new ones, and
happens only when two readings of the active account agree on the same target.
It never goes to an account whose own readings show it filling, or one with
a weekly limit that does not say when it resets. It skips an account with a
model limit at 100%, even a model no session runs now, because the next session
on that model would leave again. The exceptions are a limit full on every
account and a week that returns within a day. With no Claude session running, nothing switches.

**Choosing among accounts.** The panel takes an account under 90% with room in
its 5-hour window (under 70%, or a plan without one) first, then any account under 90%, then the rest. Among those, the most weekly
runway wins. Runways within 10% of each other go to the one that resets
sooner, then to the emptier 5-hour window.

While a switch is near, meaning the active account is at 80% or more or a
window is on course for 100%, a chip beside the control names where it would go
(`→ spare soon`), names where it goes once the active account is about to
fill when every other one is over 90% too (`→ spare near 100%`), asks for a
login when the emptier account needs one
(`log in to spare`), or says `no better account` when none is at least 3 points
emptier; point at it for the reason (`Fable at 86%`, or a window on course for
100%) and, on `→ spare soon` and `→ spare near 100%`, for the earlier reasoning
the switch drops.

**What a switch costs.** The prompt cache belongs to the account, so after any
switch, by hand or automatic, each recently active session writes its whole
conversation to the cache again on the new account. Fable 5.2, Sonnet 5.5 and
Haiku 5.5 also tie their thinking to the account that produced it: the API
drops that earlier reasoning from every later request, without an error, and
the session carries on from its visible messages and tool results alone. Opus
5.5 and Fable 5.1 keep theirs. Hence the rules above that keep the sessions on
one account until it is about to fill.

Each automatic switch writes a line to
`~/.claude/agents-sidebar-status/daemon.log`, and posts a macOS notice with the
reason when notifications are on in Settings and the install built
`Agents.app`. Run this or `cswap auto`, not both: two engines would trade the
login between them.

## API credits when every account is full

Off by default, in Settings > Accounts. When every account is full, the
switch **When every account is full, use API credits** moves running Claude
Code sessions to prepaid API credits until an account has room again. It works
with one account, and with Auto-switch on or off. The switch waits until you
save a key on at least one account, and until the statusline bridge is
installed, because the spend cap reads each session's cost from the bridge.

**The keys.** Each stored account has a row under the switch, so its sessions
can bill the Console organisation that goes with it. Paste an Anthropic API key
into an account's field: pasting saves it, and so do Enter and its save icon (a
floppy disk). The panel refuses text not shaped like an Anthropic API key
(`sk-ant-` and 20 or more letters, digits, `-` or `_`) as `not an Anthropic API
key` without asking the API. It checks a key once against the
API's models list, refuses one the API turns down, and keeps it in the Keychain
beside the account logins (service `agents-sidebar-accounts`, account
`api-key:<account id>`, such as `api-key:acct-1`). The store keeps the key's
last four characters, which the row's **Key** column shows from then on, and
the row's trash icon, pressed twice, deletes the key. The panel never reads, writes or deletes an item named plain `api-key`
under that service: another launcher keeps one there. Only a 401 or 403 counts
as the API turning a key down. Any other status, or no answer at all, says
nothing about the key: a save reports it and keeps nothing, and a check before a
move leaves the sessions on the subscription and tries again.

**Which key.** Claude Code reads one `apiKeyHelper` for every session on the
machine, so one key is in use at a time. The panel uses the active account's
key; when that account has none, or its key is refused or at its cap, the first
other account with a usable key in the accounts' list order. A key passed over
for its cap, a refusal, `billing_error` or `authentication_failed` stays passed
over until an account has room; raising its cap lifts a cap at once, and saving
the account's key again lifts the rest. Meanwhile its row shows the hold's word,
such as `cap reached`, and says the panel skips the key until an account has
room or you raise its cap, or, for any other hold, save its key again.

**Moving to credits.** The panel moves when it would leave the active account
and no account has room: the active account's figure at 90% or more with every
other account full, or every model your sessions run full on every account. An
account it cannot read is not full, so that never starts it, and neither does
a projection alone: an account on course for 100% at 85% waits for 90%. Usage
never falls before a reset, so a move made at 90% or more cannot see room
again until a window resets. A notice says "Sessions move to API credits", with the tokens the
active sessions read again, and offers **Not now**; the Accounts head shows
the same with a countdown. The fallback's macOS notices, this one and those
below, post only when notifications are on in Settings and the install built
`Agents.app`, as a switch's do; the countdown and **Not now** in the Accounts
head work either way. With no answer in 60 seconds, the panel checks the
key against the API once more and points `apiKeyHelper` in
`~/.claude/settings.json` at `api-key-helper.sh` in the checkout with the
account id whose key it prints, as a command quoted for the shell where the
path needs it (`/path/to/checkout/api-key-helper.sh acct-1`). If that file
syncs to other machines, they get the line too, as the switch's note in
Settings says. The id must be in the store's
`acct-<n>` form before it goes into the command, and the helper refuses any
other argument without running it. When the API refuses that key, the panel
tries the next usable one at once. Running sessions take it on their next turn. **Not now**
keeps the sessions on the full account until an account has room and every
account fills again. When the API gives no verdict on the key, the panel stays
off with no hold, says so once, and tries again at each reading until it
answers or the accounts stop being full; a retry does not ask again, and the
head shows `API · trying again` meanwhile. **Not now** shows `API · not now`.

The panel refuses to move, with `API · refused` in the head, a notice and a line
in `daemon.log`, when `settings.json` holds another tool's `apiKeyHelper`, when
the daemon cannot read `settings.json`, or when it cannot read the key from the
Keychain. That hold lifts once an account has room or you save a key.

**Moving back.** The panel moves back at the first reading where an account
the sessions can run on has room: the active account under 90% on a fresh
reading, or, with Auto-switch on, an account it would switch to. An active
account on course to fill has no room only while no other account has room
either. An account that needs a login never counts. A notice says "Sessions go back to
the subscription", with **Not now**, which keeps the sessions on credits and asks
again in 30 minutes. With no answer in 60 seconds, the panel takes
`apiKeyHelper` out again.

**What it costs.** The prompt cache belongs to whoever pays, so each move
makes every recently active session write its whole conversation to the cache
again, at the new payer's price, and sessions on Fable 5.2, Sonnet 5.5 and
Haiku 5.5 lose their earlier reasoning, as with any switch. That is why each
move asks first. While on
credits, claude.ai connectors and Remote Control do not work; each session
hears so on its next prompt, and hears again once back. The Accounts head shows
`on API · <account> · $<spent>` meanwhile; point at it for the key's spend
against its cap, and a reminder that the total is an estimate and that
connectors and Remote Control are off.

**The spend caps.** Each key has its own **Cap**, in dollars on its row, $50
unless you change it, kept in the account store; it is a soft cap. The row's
**Spent** shows what this fallback spent on that key, and `in use` follows the
name of the account whose key is in use. The figure adds
up each Claude session's rises in `total_cost_usd` while that key is in use,
an estimate; the Console holds the true spend, and its own limits (prepaid
credits with auto-reload off, or a workspace spend limit) are the hard cap. A
session whose cost comes back lower than the last one seen has restarted, so
the new figure counts from 0: a session resumed at $0 is not hidden by its old
total. Each move to credits starts every key's figure from 0. The cost comes
from the statusline bridge, so with the bridge gone there is no cap to
enforce: the panel refuses to move, or moves back as at the cap, and shows
`API · needs the bridge` until the bridge returns or an account has room.

**Moving to another key.** A key past its cap, a turn that fails with
`billing_error` (credits ran out) or `authentication_failed` (the API turned the
key down), and forgetting the key in use each end that key's part at once. The
next usable key takes over with no countdown and no **Not now**: the panel
checks it against the API, rewrites `apiKeyHelper` to that account's id, and
then posts a notice naming whose key the sessions now use. The organisation
that pays changes, so each recently active session writes its conversation to
the cache once more, as at any move.

A failed turn counts against a key only in a session that took that key.
`api-key-helper.sh` notes each fetch under the asking Claude Code process's id
in `~/.claude/agents-sidebar-status/api-key-fetches/`: the time and the
account, never the key. A session whose last fetch before the failure did not
take that key either fetched none and still runs on the subscription, or still
runs on an earlier key and fails on that one, so neither failure moves the
panel to the next key. A note goes once its
process has ended.

**What ends it at once.** The last usable key passing its cap, failing with
`billing_error` or `authentication_failed`, or being forgotten; the statusline
bridge going away; and turning the switch off. The helper comes out and the
chip shows `API · cap reached`, `API · credits ran out`, `API · key refused`,
`API · needs the bridge`, or nothing for a choice you made. After a
cap, an error or a lost bridge, the panel does not move to credits again until
an account has room and every account fills again, or a key is usable again:
raising a cap lifts that key's cap at once, saving a key lifts its hold, and
installing the bridge lifts the bridge's.

**The record.** The daemon keeps whether sessions run on credits, any hold,
when the move happened, each session's last cost, the spend on each key, whose
key is in use and each key passed over with why, and the exact
`apiKeyHelper` command it wrote in `api-fallback.json` in
`~/.claude/agents-sidebar-status/`, written before `settings.json` changes, so
a restart keeps the caps' figures and any hold. At each start and each reading the
daemon brings `settings.json` in line with it. A helper is the panel's only
when its command is exactly the one the record names or this checkout's own
for one of the stored accounts; anything else, even a file also named
`api-key-helper.sh`, is another tool's and is never touched. When the record says credits but `apiKeyHelper` has gone
from the file or names another command, another tool rewrote it: the fallback
ends, holds with `API · helper removed`, and `daemon.log` says so; the panel never writes the key back against another
tool. The one exception is a daemon that stopped while writing the helper: the
record carries a mark while the write is due, so a start that finds the mark
and no helper knows the write never landed, and goes off with no hold. A start
that finds the mark and the previous key's command, from a move to another key
cut short, writes the new key's command again.

**When the daemon is down.** Nothing enforces the cap then, so the helper
checks on each key fetch that the daemon named in `endpoint.json` is running
this checkout's `sidebar.py`, or the AutoLaunch stub that loads it; it reads
only the pid from that file. When it is not, the helper hands the key out once
more, so the turn in flight completes, takes its own `apiKeyHelper` out of
`settings.json`, and leaves an `api-fallback-orphaned` marker in the status
folder. The next daemon start finds the marker and ends the fallback with no
hold. This check cannot catch a daemon that runs but hangs.

**When the key cannot be read.** A helper that cannot read its account's key
from the Keychain does the same thing, except that there is no key to hand out:
it takes itself out, leaves the marker and exits non-zero. That one turn fails;
later turns run on the subscription.

## How often it reads

The panel reads usage at most every 3 minutes per account
(`POLL_FLOOR_SECONDS`), which is how often cswap measured the endpoint allows.

- Usage moved since the last reading: read twice as often, down to that floor.
- Usage sitting still: read less often, up to 5 minutes for the active account
  and 10 for the others, and never later than a window's reset.
- A failed reading: wait 1.5 times longer each time, up to 30 minutes. A 429:
  wait an hour.

The reload button asks for fresh readings first, except for an account read in
the last 3 minutes. The panel refreshes the tokens of the accounts you are not
using, and never touches the active one, because that one belongs to Claude
Code.

## Codex limits

Behind the OpenAI mark, the foot shows Codex's own limits if you have Codex
CLI: a bar for each window Codex reports, 5-hour and weekly, or weekly alone,
depending on the plan. The panel reads them from the end of Codex's newest
session log in `~/.codex/sessions`, which Codex updates on every turn, so it
makes no request and never touches Codex's login. A window whose reset time has
passed reads 0% until Codex reports again. Under the Codex name stands the
model a new Codex session starts on and its reasoning effort, as
`~/.codex/config.toml` sets them (the selected profile's first, then the top
level's), named as Codex's own model list names the slug.

When the plan's usage is used up and Codex moves the account onto a fallback
allowance (Luna Reserve, on selected plans), it switches the session to the
reserve model, and Codex's log names both the model and the allowance. The foot
then says so under the
plan's bars and adds a row for the allowance (`Luna` for Luna Reserve) with its own usage and reset;
the row's tooltip gives the allowance's name. The plan's bars keep their last
reading, which stays used up until the plan's window resets. Back on the plan,
the row goes.

`docs/accounts-design.md` has the design this came from.
