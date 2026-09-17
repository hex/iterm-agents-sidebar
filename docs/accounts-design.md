# Accounts in the panel: usage meters and switching

Status: approved 2026-09-15 (R2, 600 s poll floor, account line above the 5-hour bar).
Superseded on the poll floor: the shipped floor is 180 s
(`POLL_FLOOR_SECONDS` in `accounts.py`), taken from cswap's own cadence on
2026-09-16. Read `accounts.py` and `docs/accounts.md` for what runs.

## The request

The panel's foot shows every Claude Code account's usage (5-hour, weekly, and
each per-model weekly limit, always) with pace, and lets you switch the active
account from the panel.

The panel does this on its own. It keeps its own account store, reads usage
itself and switches itself. It does not call the `cswap` CLI, does not read or
write cswap's store, and does not replace or uninstall anything. cswap keeps
running beside it.

## Facts this rests on

Read in claude-swap 0.22.0's source on 2026-09-15 and checked on this machine.
File references are to `site-packages/claude_swap/`; they document how the
protocol works, not files the panel touches.

- **The active account is global here.** The live `claude` processes carry no
  `CLAUDE_CONFIG_DIR`, so every session reads the one Keychain item
  `Claude Code-credentials` (account attribute `$USER`) and `~/.claude.json` →
  `oauthAccount`. A switch changes every session at once.
- **No `~/.claude/.credentials.json` exists**, so running sessions pick a switch
  up only when Claude Code's ~30 s Keychain cache expires.
- **The credential blob** is `{"claudeAiOauth": {accessToken, refreshToken,
  expiresAt, scopes, ...}, ...}`. Keys such as `mcpOAuth` and `pluginSecrets`
  belong to the machine, not the account, and always come from the live item.
- **Refresh tokens are one-time use.** Presenting a spent one returns
  `invalid_grant`; the account then needs a fresh login.
- **cswap is running** (`cswap watch`), refreshes the tokens of accounts that
  are not active, and quarantines a slot after one `invalid_grant`
  (`usage_store.py:227`). Its menubar and `auto` can also switch accounts.
- **Usage budget is small**: about 28-30 requests per account per trailing hour
  on `GET api.anthropic.com/api/oauth/usage`, shared by every client using that
  account's token; a 429 can lock polling out for an hour.
- **Claude Code locks its credential** with `proper-lockfile` directories
  (`<config>/.oauth_refresh.lock`, then `~/.claude.lock`, stale after 60 s)
  while it refreshes. A switch that lands inside that window is overwritten by
  the old account's refreshed token (`claude_locks.py:19-25`). cswap takes the
  same pair before it switches.

## The accepted risk

The user chose this shape knowing the following, and the panel must say it rather
than hide it.

Two tools now hold copies of the same accounts' refresh tokens, and each token
works once. Whichever tool refreshes first leaves the other with a spent copy.
Concretely:

1. **cswap refreshes an inactive account** (it does this routinely). The panel's
   copy of that account's refresh token is now dead. If the panel later switches
   to that account, Claude Code works until the access token expires, then fails
   to refresh, and **every session is logged out of that account** until someone
   runs `/login` for it.
2. **The panel refreshes an inactive account** (R2, chosen). cswap's copy dies;
   cswap quarantines that slot on its next refresh, and its menubar shows the
   account as needing a login even though the panel's copy works.
3. **Both tools switch** within seconds of each other. The Claude Code lock pair
   serialises the writes, but the last writer wins, and the panel shows whatever
   `~/.claude.json` says afterwards.

Mitigations reduce how often this happens and make it visible when it does.
None removes it; only running one tool does.

## Mitigations

### R. Who refreshes inactive accounts' tokens

Chosen: **R2, the panel refreshes inactive accounts itself**, so it works
without cswap. Rejected: R1 (never refresh, inactive meters go stale).

- **Never the active account.** Claude Code owns that token; refreshing it
  would log out every running session. The panel reads the live one instead.
- **Only when needed**: when a stored access token is within 5 minutes of
  `expiresAt` and a usage poll is due, and just before a switch to that account.
- **Consume gate, per account**: take the account's lock file
  (`~/.config/agents-sidebar/locks/<id>.lock`, flock) → re-read the stored blob
  under the lock → POST `platform.claude.com/v1/oauth/token` → write the
  successor blob before releasing the lock. A successor token is never dropped:
  if the Keychain write fails, the blob goes to a 0600 file beside the store and
  the next start retries the write.
- **`invalid_grant`** marks the account `needs login` at once (one strike, as
  cswap does) and never retries that token.

### S. Keeping the panel's copies current

Always on, whichever R is chosen:

- **Capture from the live item.** "Add this account" snapshots the live
  `Claude Code-credentials` blob and `oauthAccount`. To add a second account,
  `/login` as it in Claude Code, then Add again.
- **Resync while active.** Whenever the live `oauthAccount.accountUuid` matches
  a stored account, the panel copies the live blob over its stored one if the
  refresh token differs. Claude Code rotates the active account's token, so this
  keeps the copy of the account you are using on the newest lineage.
- **Back up before switching away.** The outgoing live blob is saved into its
  account's slot first, under the lock pair, and only when its `accountUuid`
  matches that slot. A live credential that matches no stored account refuses
  the switch rather than overwrite a slot.

### D. Detecting a dead copy

- **Before switching**, the panel refreshes the target (R2 gate). Success
  proves the lineage is alive and hands Claude Code a token no other tool holds.
  `invalid_grant` refuses the switch: "log in to <alias> again".
- **After switching**, the panel reads usage with the live token once Claude
  Code's cache has turned over (~35 s). A 401, or `oauthAccount` gone from
  `~/.claude.json`, shows "<alias> is logged out, run /login" on the account
  line.
- **Stale age on every inactive row**, so a copy that cswap has probably rotated
  (last resync long ago) looks old rather than trustworthy.

### L. Locks

The panel takes Claude Code's lock pair, in Claude Code's order and with its
staleness rules, before any write to `Claude Code-credentials` or
`~/.claude.json`. If the pair stays held for more than 18 s, the switch refuses:
"Claude Code is refreshing, try again". Because cswap takes the same pair, this
also keeps a panel switch and a cswap switch from interleaving.

### P. Polling alongside cswap

Both tools poll the same accounts from the same budget. The panel polls at a
600 s floor (cswap's floor is 180 s), backs off ×1.5 to 1800 s on failure, and
after a 429 keeps its last reading for an hour. At 600 s the panel adds 6
requests per account per hour to cswap's worst case of 20.

## Store

- **Metadata:** `~/.config/agents-sidebar/accounts.json`, mode 0600, written
  atomically (temp file, fsync, rename), read strictly. A torn or unknown file
  hides the accounts section and is never rebuilt from what could be read.
  Shape: `{version: 1, accounts: [{id, alias, accountUuid, organizationUuid,
  organizationName, added, lastSynced, needsLogin?}]}`. Emails are not stored
  here; the panel reads them from each account's `<id>.login` Keychain item.
- **Credentials:** Keychain generic password, service
  `agents-sidebar-accounts`, account `<id>`. Written through
  `/usr/bin/security -i` with hex values so no secret appears in argv, within
  its 4032-byte line limit.
- **Switch writes:** the target's `claudeAiOauth` merged with the machine keys of
  the live item into `Claude Code-credentials`; only `oauthAccount` replaced in
  `~/.claude.json`, under `~/.claude.json.lock`.

## Units

A new `accounts.py` beside `sidebar.py`, split like the existing code:

- **Pure, tested:** store parsing; usage-response normalising (5 h, 7 d,
  `limits[]` per model); pace; the poll planner; the resync decision (copy or
  not); the switch plan (which locks, which reads, which writes, in order) as
  data; blob merging (account keys from the target, machine keys from live).
- **IO, thin:** `security` subprocess, `urllib` requests, `os.mkdir`/`os.utime`
  for proper-lockfile directories, atomic file writes.

The snapshot gains one top-level `accounts` object; rows stay as they are.

Not built: auto-switching near a limit. cswap's `auto` keeps doing that if it is
on, and the panel reflects the result.

## Pace, one definition

Copy cswap's `pace.py` rules, and use them everywhere in the panel:

- weekly windows only (overall weekly and every per-model weekly), window 604 800 s;
- `elapsed = window − ((resets_at − fetched_at) mod window)`; no pace in the
  first 24 h after a reset;
- `expected = elapsed / window × 100`;
- ahead of pace when `used − expected ≥ 15`;
- runs out before reset when `used + used/elapsed × (window − elapsed) > 100`.

The footer shipped today warms at "≥ 80 % and past the tick" and puts a tick on
the 5-hour bar too. Those rules change to the above, so the panel and cswap
never disagree about the same number. The 5-hour bar keeps its reset time and
loses the tick.

## Foot layout (sketch)

```
WAITING ON YOU · 2                 (unchanged)
─────────────────────────────────
work ▾                    3 accts
5-hour  ━━━━━──────────  19%  16:10
Weekly  ━━━━━━──│──────  33%  Thu
Fable   ━━━━━━━━│──────  50%  Thu
$11.63 · 4 sessions
```

The footer lists every account at all times: its name, its 5-hour, weekly and
per-model bars (stale ones marked with their age), and Switch under each
account that is not active. Switch arms on the first click ("Switch to atlas?") and
acts on the second. After it lands: "Active in about 30 s for running
sessions." Names are the nickname, else the email from the account's login block, else
"Account 3". Clicking a name edits the nickname in place (Enter saves, Esc
cancels, empty clears).

## Failure behaviour (fail loud, never corrupt)

| Situation | What the panel does |
|---|---|
| Claude Code holds its lock pair for > 18 s | Switch refuses: "Claude Code is refreshing, try again" |
| Keychain locked or `security` errors | Meters show their last reading as stale; Switch refuses |
| `accounts.json` unreadable or unknown shape | Accounts section hidden with one grey line saying why; nothing written |
| Live credential matches no stored account | Switch refuses rather than overwrite a slot; offers "Add this account" |
| Target refresh returns `invalid_grant` | Account marked needs login; Switch refuses: "log in to <alias> again" |
| After a switch, live token 401 or `oauthAccount` gone | Account line: "<alias> is logged out, run /login" |
| Usage 429 | Keep last reading, mark it stale with its age, back off (P) |

## Testing

- TDD on every pure unit, in vertical slices: parsing, pace, poll planner,
  resync decision, refresh decision, switch plan, blob merge. Fixtures shaped like real usage
  responses and credential blobs, with tokens and identities replaced.
- Keychain writes, lock acquisition against a live Claude Code, and the switch
  itself cannot be tested without mocks, which we do not write. They get:
  - a `--dry-run` switch that prints the plan (locks, reads, writes, in order)
    without writing, run against the real machine;
  - a scratch Keychain service name for exercising the `security` read/write
    code with a throwaway value;
  - one supervised real switch there and back, by the user, before merge.
- Ships without automated tests: the `security` subprocess wrapper, the lock
  directory dance against a live Claude Code, the switch IO. Same category as
  `Bridge` today, but these write credentials.

## Decisions

1. R2: the panel refreshes inactive accounts itself (user decision, 2026-09-15).
2. Poll floor 600 s.
3. Account line above the 5-hour bar.
