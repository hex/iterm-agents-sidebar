# Remote control: kept across account switches, and shown on the card

Designed 2026-10-10 on `spec/remote-control`.

When the panel switches accounts, Claude Code drops Remote Control in every
session that had it on, and each one needs `/remote-control` typed again by
hand. With a new experimental setting on, the panel turns it back on for
those sessions once they are idle. Every Claude card also shows whether its
session has Remote Control on, setting or not.

The request (2026-10-10): "when auto switch is on and /remote-control is
enabled, when the switch happens the /remote-control connection drops and
you have to run it again to enable it, we need a switch that does this
automatically, also maybe we can have a small symbol somewhere where remote
control is enabled for a session".

Decided:

- **After any switch the panel makes**, automatic or by hand, and only for
  sessions that had Remote Control on just before it (picked: "After any
  switch" over "after an auto-switch only" and "whenever it drops"). A
  disconnect you make yourself is never undone.
- **The mod turns it back on** with `$.command.run({command:
  "remote-control"})`, after reading its own state file again (picked: "The
  mod runs it" over the daemon typing `/remote-control` and Enter into the
  pane, which would mix into a half-typed prompt).
- **The mark is a live fact, always shown** (picked: "Always, as a live
  fact" over "only with the setting on" and "only when it needs you"):
  solid while Remote Control is on, dimmed while the panel is bringing it
  back.
- **The mark is a glyph after the card's name** (picked: variant B of four
  rendered on a live card at 380 px, dark; the others were a chip with the
  word "remote" on the facts line, the glyph alone on the facts line, and
  the glyph in the card's corner beside the provider mark). Lab:
  `.cs/local/rc-mark-variants.png`, script `.cs/local/rc_variants.mjs`
  (session files, not in the repo).
- **Experimental, off by default**, beside Link cards.
- The three design sections behind §2 to §4 were approved in dialogue on
  2026-10-10 ("Looks right" on each), and this spec was approved the same
  day with the §5 and §6.5 picks below.

## 1. What Claude Code does today

Read in Claude Code 2.1.296 (strings also in 2.1.292) and measured where
marked.

- A running session's state file is `~/.claude/sessions/<pid>.json`, with
  `pid`, `sessionId`, `cwd`, `status` (`idle`, `busy` or `waiting`),
  `bridgeSessionId`, `name` and `version`. `bridgeSessionId` is a string
  while Remote Control is attached and `null` once it is not (measured).
- No statusline payload, hook input or `$.session` call carries Remote
  Control state (35 statusline payloads checked). The state file is the
  only source, and the panel never reads the pane's screen for it.
- An account switch (`accounts.py` rewrites the Keychain item and
  `oauthAccount`) sends Claude Code no event. Its credential watcher keeps
  Remote Control for a fresh credential of the same account and logs
  "disarming" for a different one. After the 10:26 auto-switch on
  2026-10-10, three sessions bound to the old account read
  `bridgeSessionId: null` (correlation, not a timed measurement).
- **Check 1, measured 2026-10-10** (`.cs/local/rc_check1.py` with a probe
  mod, Claude Code 2.1.296): in a session started with Remote Control off,
  `$.command.run({command: "remote-control"})` resolved `{}` about 3.5 s
  later, `bridgeSessionId` was set within 5 s, `status` stayed `idle` and
  no dialog opened. Run while Remote Control was **on**, the same call
  opened the Remote Control menu (Disconnect / Show QR code / Continue),
  `status` went to `waiting`, and the call stayed unresolved until the menu
  was dismissed; one Escape dismissed it and Remote Control stayed on. So
  the command is not a plain toggle-off, but running it while on leaves a
  menu in your way: the mod must read the state first.
- **Check 2** (a real switch to another account and back, timing the drop)
  was skipped (picked: "Skip check 2"): the live account carries
  `needsLogin`, so `accounts.py` would refuse the switch back
  (`SwitchRefused("log in to … again")`). The live E2E (§8) times the drop
  on the next real switch.

## 2. Daemon (`sidebar.py`)

### Reading the state

Each rebuild reads `~/.claude/sessions/<agent_pid>.json` for every Claude
row that has an `agent_pid`, in one `asyncio.to_thread` batch so the event
loop never waits on the disk. The file is parsed at this boundary into one
of three readings:

- **on**: `bridgeSessionId` is a non-empty string;
- **off**: `bridgeSessionId` is `null`, or the key is absent (a session
  that has never had Remote Control on writes no key; measured, §7);
- **unknown**: the file is missing (the agent is gone or has not written it
  yet), is not whole JSON, its `pid` is not the row's `agent_pid`, or
  `bridgeSessionId` is of any other type. A malformed file logs one line
  naming the path and what was wrong, once per pid and fault; a missing one
  logs nothing.

Each reading keeps the time it was taken. A row that is not Claude, or has
no `agent_pid`, has no reading.

### What the frame carries

Each Claude row gets `remote`, one of:

| `remote` | when | the card shows |
|---|---|---|
| `"on"` | the reading is on | the mark, solid |
| `"reconnecting"` | the row is owed (below) and its reading is off | the mark, dimmed |
| `"lost"` | the row's re-enable failed (below), for up to 10 minutes | no mark; the line "Remote control did not come back: run /remote-control" |
| `null` | anything else, every non-Claude row included | nothing |

`"lost"` is a fourth value beyond the three approved in dialogue: the
line under the card needs the frame to say it is due, and a separate field
would let a row be "on" and "lost" at once.

### The setting

`DEFAULT_SETTINGS["keep_remote"] = False`, under the `links` entry with the
same "Experimental" comment form. The page row (§3) reads "Keep remote
control after a switch", note "When the panel switches accounts, sessions
that had remote control on get it back once they are idle, under the
account switched to." (§5)

Turning it off clears the owed list, deletes every untaken
`remote-control.json` the daemon wrote, and drops any `"lost"` state. A
mod that already took its file finishes what it started (one command), and
the daemon ignores its result.

### Noticing a switch

Both switch paths (the auto-switch in `watch_accounts` and the hand switch
through `meters.switch`) end in `_switch_locked`, which sets
`meters.last_switch = {"at", "from", "to", "why", "auto"}`. The rebuild
compares `last_switch["at"]` with the last one it saw; a new value is a
switch, whichever path made it. No second hook in either path.

With the setting on, a new switch builds the **owed list**: every Claude
row whose last reading was **on**. (Amended 2026-10-10 after the final
review: `last_switch["at"]` is the time the account work began, seconds
before the switch shows, so readings taken in between postdate it and a
"taken before `at`" rule owed nothing after an auto-switch. Picked: "Owe any
pane last read on".)
Each entry is keyed by the row's pane (a pane outlives `/clear` and a
resume; a session id does not) and holds the switch time and the session
id and `agent_pid` seen then. A second switch while entries are owed adds the newly owed
rows and moves every entry's switch time to the new one.

The owed list lives in daemon memory only. A daemon restart forgets it:
those sessions keep Remote Control off and show no line (my default; the
restart is rare and the mark already shows them off).

### When it drops

On each rebuild, for each owed entry:

1. **No drop within 2 minutes** of the switch (the reading stayed on): the
   entry is forgotten. Claude Code keeps Remote Control when it judges the
   new credential to be the same account; whatever it judges, a session
   that never dropped is owed nothing.
2. **The reading turns off**: the daemon writes `remote-control.json` into
   the session's links folder, `~/.claude/agents-sidebar-links/<session
   id>/`, through `links.write_file` (staged, 0600, renamed into place):

   ```json
   {"switch_at": 1791619414.5, "expires": 1791619714.5}
   ```

   `expires` is 5 minutes after the write. The file carries no command and
   no text: it only says "turn it back on", and the mod decides what runs.
   The row now reads `"reconnecting"`.
3. **The reading turns on again** (by the mod or by hand): the entry is
   cleared and the daemon logs one line, `remote control back on
   "<label>" after the switch`.
4. **It does not come back**: the entry moves to **lost** and the row
   reads `"lost"` when any of these happens first:
   - the mod files a `failed` result (below);
   - the file passes its `expires` untaken (no mod in the session, the
     plugin off, or the session never idle);
   - 2 minutes pass after the mod filed `done` and the reading is still off.

   The daemon logs `remote control did not come back on "<label>":
   <reason>` once. A lost entry clears when the reading turns on, the pane
   goes, or 10 minutes pass.

The mod's result comes back as `remote-control-result.json` in the same
folder, read with `links.read_json` (the guarded reader) and deleted once
read:

```json
{"switch_at": 1791619414.5, "outcome": "done" | "already-on" | "failed", "reason": "…"}
```

A result whose `switch_at` is not the owed entry's is stale and deleted
unread. `already-on` clears the entry like a reconnect.

## 3. Page (`page.html`)

### The mark

Variant B: the Phosphor regular `broadcast` glyph (path data added to
`META_ICONS` as `remote`), 11 px, `var(--dim)` ink (amended 2026-10-10:
`var(--fg)` read as black beside a resting card's grey name; asked for "more
gray"), 6 px after the card's
name, on the name's baseline as the lab drew it. `"reconnecting"` draws the
same glyph at 35 % opacity. No motion in either state: resting chrome stays
still, and the static GPU guard (`tests/test_page_motion_cost.py`) needs no
new entry.

The lab put the glyph inside the name's `.run`. A name too long for the row
fades out under `.label`'s mask, which would fade the glyph with it, and the
glide that shows a long name would carry it away. The build keeps the glyph
outside the clipped run, so a long name fades before the glyph and the
glyph never moves; checked in the page E2E (§8).

Screen readers: the glyph is `aria-hidden`; the card's spoken summary (the
one that speaks the task and the facts line) adds "remote control on" or
"remote control reconnecting".

### The line

`"lost"` adds a line at the card's foot in the refusal recipe (`p.refusal`
style: warn ink, 11 px, under the card's content), `role="status"`, text
"Remote control did not come back: run /remote-control". Shown as the lab
drew it, with no button: the command is yours to type.

### The setting row

`SETTING_ROWS` gets `{k: "keep_remote", label: "Keep remote control after
a switch", note: "When the panel switches accounts, sessions that had
remote control on get it back once they are idle, under the account
switched to."}` under
`{head: "Experimental"}`, after Link cards. `assets/make-settings.py`
redraws `assets/settings.svg`; `tests/test_figures.py` counts 29 labels.

## 4. The mod (`plugin/hooks/link.tsx`)

The mod's existing one-second `tick` (run for every session, whatever the
Link cards setting) also looks for `remote-control.json` in its own folder.
No new hook, no new module (one hooks module per plugin, one hook per
event).

1. **Take it**: rename `remote-control.json` to
   `remote-control-taken.json`, as asks are taken, so a second tick never
   runs it twice. A file past `expires` is deleted and nothing runs; the
   daemon's own expiry covers it.
2. **Find its own state file**: list `~/.claude/sessions/`, read each
   `<pid>.json` with `readJson`, keep the one whose `sessionId` is
   `$.session.id()`. None found: wait, as for a busy session, and file
   `failed`, reason "no session state file", only past `expires` (amended
   2026-10-10 after the final review: a read mid-rewrite, or the ~2 s after
   `/clear` before the file names the new id, would otherwise fail a job the
   next tick would finish. Picked: "Wait, fail at expiry"). The file is found
   again on every tick, never kept.
3. **Wait for idle**: each tick re-reads that file; it runs nothing until
   `status` is `idle`, so it never relies on how `$.command.run` behaves in
   a busy or waiting session (unmeasured). Past the taken file's `expires`
   it files `failed`, reason "the session did not go idle".
4. **Check, then run**: if `bridgeSessionId` is set, file `already-on` and
   stop: running the command now would open the Remote Control menu (§1).
   Otherwise `await $.command.run({command: "remote-control"})`; resolved,
   file `done`; rejected, file `failed` with the rejection's message.
5. Delete `remote-control-taken.json`. The result is written with
   `writeWhole` (dot-file, 0600, rename).

The mod never decides on its own that Remote Control should be on: it acts
only on the daemon's file, the file names no command, and the command is
fixed in the mod.

## 5. Changing account under a running remote session

Claude Code drops Remote Control on a switch to a **different** account on
purpose ("disarming"). Every switch the panel makes is to a different
login: the store keys accounts by `accountUuid` and refuses two entries
with the same one (`accounts.py`, `StoreError`). So turning Remote Control
back on always attaches the session to the **new** login's Remote Control:
it then shows in that login's session list at claude.ai/code and on phones
signed in to it, and no longer in the old one's. With two logins of
different owners (personal and work, say), the session and its
conversation become reachable from the other login.

Decided 2026-10-10 (picked: "Re-enable, say so" over keeping the note
as it was and over re-enabling only between logins with the same email):
re-enable after any switch, and the setting's note says it happens under
the account switched to.

## 6. Failure modes, written before the code

1. The daemon reads a state file of a pid that has since been reused by
   another process's agent: `pid` inside the file is checked against the
   row's `agent_pid`; a mismatch reads unknown.
2. A state file half-written as it is read: not whole JSON, unknown; the
   next rebuild reads it again.
3. A switch while the rebuild is mid-read: the owed list takes the
   previous rebuild's readings, so a reading already off (dropped by this
   switch) is never counted as "had it on", and one taken after the stamp
   but before the switch showed still counts (amended, see §2).
4. A switch after which Claude Code keeps Remote Control: no drop in 2
   minutes, nothing owed, nothing written.
5. You turn Remote Control off yourself within the 2 minutes after a switch
   that Claude Code did not drop it for: the daemon takes your disconnect
   for the drop and turns it back on. Without an event from Claude Code the
   two look the same. Decided 2026-10-10 (picked: "Accept the bound" over
   a 30 s window, which could miss a slow drop): the gap stays, bounded to
   a manual disconnect inside that window.
6. The mod is not loaded (plugin off, an old install): the file expires
   untaken, the row reads `"lost"`, the line says what to type.
7. The session is mid-turn for more than 5 minutes: the mod files `failed`
   ("the session did not go idle"); the line appears. You run the command
   when the turn ends.
8. The session sits on a permission prompt (`status: waiting`): treated as
   not idle, as 7.
9. Remote Control came back on its own before the mod ran (a same-account
   credential refresh): the check finds it on, files `already-on`, no menu
   opens.
10. `/clear` between the drop and the mod's tick: the session id changes,
    so the file sits in the old id's folder that no mod reads. The daemon
    writes into the folder of the session id on the row at drop time, and
    if the row's session id changes while owed, it moves an untaken file to
    the new folder.
11. The agent in an owed pane exits and another `claude` starts there: each
    owed entry also holds the row's `agent_pid` at the switch, and a row
    with a different `agent_pid` forgets the entry, so the new session is
    never turned on. `/clear` and an in-session resume keep the process, and
    so the entry.
12. The setting is turned off while files are out: §2 deletes the untaken
    files; a taken one runs once; its result is ignored.
13. A symlink or directory planted as `remote-control.json` or its result:
    `links.read_json` and `links.write_file` refuse non-regular files
    (`S_ISREG` before `fdopen`), as they do for drops.

## 7. Checks before the build

Measured 2026-10-10 with `.cs/local/rc_check2.py` and the probe mod
`.cs/local/rcprobe` (Claude Code 2.1.296), in a throwaway haiku session in
**default** permission mode with the user's settings and hooks loaded and
`--settings` turning `remoteControlAtStartup` off. Output kept in
`.cs/local/rc_check4.out`.

1. Done: §1 check 1 (bypass mode).
2. **Pass.** In default mode the mod lists `~/.claude/sessions/` and reads
   its own state file through `$.fs` with no prompt, and
   `$.command.run({command: "remote-control"})` resolved `{}` about 4 s
   after the request with `bridgeSessionId` set and `status` idle, as in
   bypass mode. Before Remote Control was ever on, the file had no
   `bridgeSessionId` key at all, not `null` (§2 reads that as off).
3. **Pass.** After `/clear`, `$.session.id()` changed and the same
   `<pid>.json` carried the new `sessionId` within 2 s, so the lookup by
   `sessionId` holds; Remote Control stayed on across the `/clear`.
4. **The card stays idle under the menu.** With the Remote Control menu
   open (`status: waiting` in the state file), the panel's row read
   `state: "idle"` for 9 s; the card does not ask for attention. One Escape
   closed the menu and `command.run` resolved `{}`. The mark reads on
   throughout, which is true.

Probe trap, for the next one: the probe ran anything that was not a
`state` request, so the driver's initial `control(0, "none")` was a run of
its own and the next run opened the menu; and `--setting-sources project`
turns off the user hooks that give the panel a row's state.

## 8. Tests

- **Daemon** (`tests/`): the reading parser (on, off, every unknown case,
  pid mismatch, the once-per-fault log); the owed list from a switch (only
  readings before the switch, same-account no-drop forgetting, a second
  switch); the file written on drop with its expiry; reconnect clears and
  logs; each way to "lost" (failed result, expired untaken, done but still
  off after 2 minutes); lost clears on reconnect, pane gone, 10 minutes;
  stale and malformed results; the setting off clearing everything; the
  `/clear` move of an untaken file.
- **Mod** (kit tests in `plugin/`): takes the file once; waits for idle;
  `already-on` without running; `done` and `failed`; expiry while busy;
  no state file found. The engine's `$.command.run` is mocked in the kit as
  the existing tests mock `AskUserQuestion`.
- **Page E2E** (`.cs/local/`, headless Chrome at 380 px, both themes): the
  mark solid for `"on"`, at 35 % for `"reconnecting"`, absent with the line
  for `"lost"`, absent for `null`; a long name fades before the glyph and
  the glyph stays put through the name's glide; the spoken summary; the
  setting row and its note.
- **Live E2E** (`.cs/local/`, a throwaway Claude session in a trusted
  scratch folder, the repo plugin loaded): a session with Remote Control on,
  then a real switch the panel makes, measuring when `bridgeSessionId` goes
  null, then that the mod turns it back on and the card goes dimmed then
  solid. Needs a second account that can be switched back from; run when
  one is logged in.

## 9. Docs

- `docs/usage.md`: the mark, the line, the setting.
- `docs/integrations.md`: the two new files in a session's links folder,
  and that the daemon reads `~/.claude/sessions/<pid>.json`.
- `README.md`: the settings figure and the experimental list.
- `docs/development.md`: the files list.

## Defaults set in this spec

The 2-minute drop window, the 5-minute file expiry, the 2 minutes after
`done`, the 10-minute line, the in-memory owed list, the `"lost"` frame
value, and the glyph's 11 px size and 35 % dim, all changeable.

## Not in this design

Codex and omp sessions (they have no Remote Control); turning Remote
Control on for a session that never had it; a button on the line that runs
the command; telling the phone side anything.
