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
| A tick on a weekly line | Where an even spend across the week would be |
| A warm percentage | 15 points or more past that tick |
| `as of 14:02` | The last reading failed; these are the figures from then |
| `log in to <name> again` | That account's login stopped working |

The foot shows an account's nickname, or its email if it has none. Click a name
to set a nickname: Enter saves, Esc cancels, and an empty name goes back to the
email.

## Switching

Point at an account and click the **Switch** button over its bars, then click
**Confirm switch** within 4 seconds. Running sessions pick up the new account
within about 30 seconds.

The panel first refreshes that account's token, which proves its login still
works. Then it swaps Claude Code's credential and the account in
`~/.claude.json` while holding Claude Code's own locks. If a step fails after a
write, the panel puts the old login back and says so.

Under the active account's bars, one line says where the last switch went, why,
and how long ago. A chip marks a switch the panel made on its own.

## Switching on its own

Off by default. The **Auto-switch** control above the accounts lets the panel
leave the active account before a limit stops your sessions. It moves when the account's
fullest window, the 5-hour, the weekly or the Fable limit, reaches 90%, or when
the rate it is filling at would reach 100% within ten minutes. It waits instead
when that window resets within ten minutes and would not fill first.

It picks the account with the most room, at least ten points better and under
90% itself; near-equal accounts are split by whichever resets sooner. A reading
older than three minutes is taken again before the switch. Automatic switches
are at least five minutes apart, except that an account already at 100% is left
at once. When every account is full it stays put and says so once in the
daemon log.

While a switch is near, a line under the control says where it would go and
why (`switching soon to spare · Fable at 86%`), or that nowhere fits.

Each switch posts a macOS notice with the reason and writes a line to
`~/.claude/agents-sidebar-status/daemon.log`. Run this or `cswap auto`, not
both: two engines would trade the login between them.

## How often it reads

The panel reads usage at most every 3 minutes per account
(`POLL_FLOOR_SECONDS`), which is how often cswap measured the endpoint allows.

- Usage moved since the last reading: read twice as often, down to that floor.
- Usage sitting still: read less often, up to 5 minutes for the active account
  and 10 for the others, and never later than a window's reset.
- A failed reading: back off to 30 minutes. A 429: wait an hour.

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
