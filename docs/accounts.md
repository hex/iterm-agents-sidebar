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

## Reading the meters

With accounts stored, the foot lists every account behind the Claude mark. The
one your sessions run on comes first, with a green check. Each shows its 5-hour
limit, its weekly limit, and every per-model weekly limit the account has, with
the time left until each resets (`2h`, `3d`, `14m`).

| What you see | What it means |
| --- | --- |
| Green bar | Under 70% of the window used |
| Amber bar | 70% or more used |
| Red bar and red percentage | 90% or more used |
| A tick on a weekly line | Where an even spend across the week would be. None in the first day after a reset |
| A warm percentage | 15 points or more past that tick |
| `as of 14:02` | The last reading failed; these are the figures from then |
| `log in to <name> again` | That account's login stopped working |
| `reading...` | The first reading is on its way |
| `no reading yet` | The first reading failed; the panel tries again later |
| `not a stored login` | Claude Code runs on a login the panel has not stored |

The foot shows an account's nickname, or its email if it has none, or
`Account N` without either. Click a name to set a nickname: Enter saves, Esc
cancels, and an empty name goes back to the email.

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
and how long ago. A chip marks a switch the panel made on its own.

## Switching on its own

Off by default. The **Auto-switch** control above the accounts, shown once you
store two or more, lets the panel move your sessions between accounts so the
quota you have lasts, and so no session stops at a limit while another account
has room.

**Which limits count.** An account's figure is its fullest window among the
5-hour, the weekly, and the weekly limit of each model your Claude sessions and
their subagents run. A Fable limit counts while a session runs Fable, and not
while every session runs Opus. A session whose model is not known yet counts
for nothing until it reports one, a few seconds after it starts; only when no
session has reported a model does every limit count. A model limit at 100% on every account decides nothing: no switch
can help it, so the other limits decide until the first one returns, and the
chip says `Fable full everywhere` with that account and time in its tooltip.
If that model is the only one running, the panel stays put and says why once,
in `daemon.log`.

**Leaving a full account.** It leaves when that figure reaches 90%, or when the
rate it is filling at would reach 100% within ten minutes. It waits instead
when that window resets within ten minutes and would not fill first. It goes to
an account at least ten points better and under 90%; when none is, to one at
least three points emptier than the active one and under 100%. It never goes to
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
under 90% whose 5-hour window is under 70%, waits half an hour after any
switch, uses readings up to 15 minutes old without asking for new ones, and
happens only when two readings of the active account agree on the same target.
It never goes to an account whose own readings show it filling, one whose
5-hour window was not read, or one with a weekly limit that does not say when
it resets. With no Claude session running, nothing switches.

**Choosing among accounts.** The panel takes an account under 90% with room in
its 5-hour window (under 70%) first, then any account under 90%, then the rest. Among those, the most weekly
runway wins. Runways within 10% of each other go to the one that resets
sooner, then to the emptier 5-hour window.

While a switch is near, meaning the active account is at 80% or more or a
window is on course for 100%, a chip beside the control names where it would go
(`→ spare soon`), or says `nowhere to go`; point at it for the reason (`Fable
at 86%`, or a window on course for 100%).

Each automatic switch writes a line to
`~/.claude/agents-sidebar-status/daemon.log`, and posts a macOS notice with the
reason when notifications are on in Settings and the install built
`Agents.app`. Run this or `cswap auto`, not both: two engines would trade the
login between them.

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
passed reads 0% until Codex reports again.

`docs/accounts-design.md` has the design this came from.
