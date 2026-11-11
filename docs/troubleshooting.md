# Troubleshooting

| Symptom | What it means | What to do |
| --- | --- | --- |
| The panel stops drawing or responding to the pointer | The web view needs rebuilding | Right-click reload and choose **Rebuild the panel**. This opens a fresh view in every window. See [Rebuilding the panel](usage.md#rebuilding-the-panel) |
| Every row dims, `STALE` banner | The live connection failed, the daemon missed two heartbeats, a heartbeat reports an iTerm2 read failure, or the page failed to draw the latest frame. A drawing failure adds a `page error` line to `daemon.log` | A closed connection retries after two seconds. If `STALE` persists, quit the running script in Scripts > Manage > Console or stop the `venvs/3.10/bin/python` process that runs `agents_sidebar.py`. Then start it from the Scripts menu. Starting it while one runs makes a second daemon |
| A row shows `?` for its directory | iTerm2 can't report that one session's directory. The row leaves out a job it can't read | Nothing; one session costs its own row, not the list |
| The panel is white and nothing loads | Two tool identifiers named "Agents", and the menu opened the dead one | Rename the stale entry, below |
| Details has no commit calendar for a project | git refused the repository (a broken one, or one owned by another user) or did not answer in 10 s; `daemon.log` says `commits of <path> not read: ...` | Fix the repository; the panel asks git again within a minute |
| Codex cards stop appearing | Another tool's update rewrote `~/.codex/hooks.json` | `./install.sh --codex` |
| Rows show no context percentage | The statusline bridge is not installed, or `cs -statusline enable` replaced it | Install in the panel's foot, or `./install.sh`. After **Not now** the foot offers nothing until Settings > Rows > Show the foot's offers again brings it back |
| A Claude tab's status flips between iTerm2's words and the panel's | The session started before **Remove iTerm2 hooks** and still runs iTerm2's `cc-status` hook | Restart that Claude session |
| No context percentage, and no offer in the foot | `~/.claude/settings.json` is not valid JSON, so the panel offers nothing | Fix the file; the offer then shows |
| Install in the foot shows red text | `~/.claude/settings.json` stopped being valid JSON after the offer showed, so the panel wrote nothing | Fix the file, then press Install again |
| Update refused, red text in the bar | One of the checks in [Updating](usage.md#updating) failed, or `install.sh` did; the whole message is in the script console | Read the reason. `local changes to tracked files`: `git -C <checkout> status`. `git … is too old`: update git (`xcode-select --install`). `not signed with a release key` or `carries no SSH signature`: take nothing and tell the maintainer |
| The install line stops with `already installed in …` | `get.sh` no longer updates an existing install: it is fetched unsigned | Use the panel's Update button, or run that checkout's `install.sh` |
| The panel is blank after Update | The daemon restarted on a new port | Reopen it: View > Toolbelt > Agents |
| `API · refused` in the Accounts head | The API turned down every usable key when the panel checked them before moving, a key the store names is gone from the Keychain, `settings.json` refused the write, or another tool's `apiKeyHelper` is in `~/.claude/settings.json`; the chip's tooltip says which | Save a working key on an account's row in Settings > Accounts, which lifts the hold. For another tool's helper, take it out yourself; the panel never touches it. An `apiKeyHelper` that runs this checkout's `api-key-helper.sh` with no account id after it is not the panel's command: take it out by hand |
| `API · helper removed` in the Accounts head | The sessions ran on credits, and something rewrote `~/.claude/settings.json` without `apiKeyHelper`: a template, a `chezmoi apply`, a hand edit | Nothing: the sessions are back on the subscription. The panel moves to credits again once an account has had room and every account fills again |
| `API · needs the bridge` in the Accounts head | The statusline bridge is not installed, so the spend cap has no cost to read; the panel refuses to move, or moved back as at the cap | Install the bridge in the panel's foot or with `./install.sh`: that lifts the hold |
| `API · trying again` in the Accounts head | The panel could not get a verdict on the key: an HTTP status other than 401 or 403, or no answer from the API. The sessions stay on the subscription with no hold | Nothing: it tries again at each reading while the accounts stay full. It says so once for each stretch |
| `API · cap reached` in the Accounts head | The estimated spend on the last usable key passed its **Cap**, after any other key had already gone | Raise a key's cap on its row in Settings > Accounts: that lifts the hold, and the move to credits is offered again with its notice. Or wait for an account to have room |
| `API · credits ran out` or `API · key refused` | A turn on credits failed with `billing_error` or `authentication_failed` on the last usable key, in a session that took that key, so the panel took `apiKeyHelper` out | Add credits or check the key in the Console, then save that account's key again |
| `cap reached`, `credits ran out` or `key refused` on a key's row, while the sessions stay on credits | That key is passed over until an account has room; the next account's key took over and a notice named it | Nothing, or raise that key's cap, or save its key again |
| Sessions left API credits while the panel was stopped | The daemon was down while sessions ran on credits, so `api-key-helper.sh` handed out the key once more and took itself out of `~/.claude/settings.json`, leaving `api-fallback-orphaned` in the status folder | Nothing: the next daemon start reads the marker, ends the fallback with no hold, and offers the move again if every account is still full |
| A turn failed with an `apiKeyHelper` error while on credits | The helper could not read its account's key from the Keychain. It took itself out and left the same marker, so that one turn fails and later turns run on the subscription. A helper given anything but one `acct-<n>` id exits 2 and changes nothing | Check the Keychain item `agents-sidebar-accounts`/`api-key:<account id>`, then save that account's key again if it is gone |
| `Turn failed: <error>` under a card | That session's last turn ended in a `StopFailure` with that error (`rate_limit`, `billing_error`, `authentication_failed`, ...). The card is idle and the line goes at the next prompt | Act on the error. In a session that took the key in use, `billing_error` or `authentication_failed` also passes that key over to the next account's key, and ends the fallback when no usable key remains |
| A session shows no `Turn failed:` line after a failed turn, and its failures on credits leave the key in use | The session started before an update that added the hook's `StopFailure` entry, and a change to `hooks.json` reaches a running session only after `/reload-plugins` | Run `/reload-plugins` in that session, or restart it |
| `accounts hidden: <error>` in the foot | The panel can't read the account store, `~/.config/agents-sidebar/accounts.json` | Fix that file; the error says what is wrong with it |

Some failures show only in `~/.claude/agents-sidebar-status/daemon.log`:

| Line in `daemon.log` | What it means | What to do |
| --- | --- | --- |
| `no notifier at <path>; run install.sh` | `Agents.app` is missing, so no notices go out | `./install.sh`; it needs `swiftc` |
| `resume refused <session>` | A resume click found the session gone, not resumable, or a resume already under way | Nothing; click again once the card offers it |
| `answer refused <session> <text>` | A click on a card's answer came after the question changed or was already answered | Answer in the pane |
| `auto-switch: nowhere to go, <why>` | The panel should leave the account, but no other account fits | Wait for a reset, or add an account |
| `auto-switch refused: <why>` | An automatic switch failed, and the login did not change | Act on the reason it gives |
| `api fallback on: ...`, `api fallback off: <why>` | Sessions moved to API credits, or back, and why | Nothing |
| `api fallback refused: <why>` | The move to credits did not happen: the API turned down every usable key, a key the store names is not in the Keychain, the Keychain could not be read, `settings.json` refused the write, another tool's `apiKeyHelper` is set, or the statusline bridge is not installed | Act on the reason; saving a key lifts a key's hold and installing the bridge lifts the bridge's |
| `api fallback: <why>; sessions now use <name>'s key` | The key in use reached its cap, failed, was refused or was forgotten, and the next account's key took over | Nothing |
| `api fallback could not check the key: <why>; trying again ...` | The API gave no verdict on the key, an HTTP status other than 401 or 403 or no answer at all; logged once per stretch | Nothing: the panel tries again at each reading |
| `api fallback off: the daemon stopped while writing apiKeyHelper` | A start found the record's write mark set and no helper in `settings.json`: the last daemon stopped mid-entry | Nothing: the fallback is off with no hold |
| `api fallback off: the helper took itself out` | The helper took itself out, the daemon being down or the key unreadable | Nothing, or check the Keychain item |
| `api fallback: apiKeyHelper not taken out: <why>` | The panel could not take its helper out of `settings.json`, which may not be valid JSON or changed twice while the panel wrote it | Fix the file; the panel tries again at the next reading |
| `<path>/api-fallback.json is not a fallback record (...)` | The daemon could not read its record at start, so it starts with the fallback off and no hold | Nothing; the next move writes a fresh record |
| `<path>/api-fallback.json could not be read (<error>); starting off` | The daemon could not open its record at start, so it starts with the fallback off and no hold | Fix the file's or the folder's permissions; the next move writes a fresh record |
| `api fallback: took out a helper the record does not hold` | `settings.json` held the panel's own `apiKeyHelper` while the record said the fallback was not using one: a daemon stopped between writing the helper and saving the record | Nothing |
| `api fallback step failed: <error>` | A step of the fallback raised an error it does not handle and stopped there | Report the line; the next reading runs the step again |
| `tab status off: <reason>` | iTerm2 is older than 3.7.6, or the panel could read no session's status when it started, so no tab gets a status | Update iTerm2, then restart the panel |
| `status <session>: <error>` | iTerm2 refused one tab's status; said once until a call on that session works, and tried again each reading | Nothing, unless it repeats for a session that is open |
| `tab colour <session>: <error>` | iTerm2 refused to read or set one tab's colour, so that tab keeps the colour it had | Turn Settings > Look > Session colour on the tab off and on again to try again |
| `tab underline put back` or `tab underline taken back` | At its start the daemon found `tab-underline.json`, which says the panel set iTerm2's `MinimalSelectedTabUnderlineProminence` to 0. With `put back`, it put back the line under the selected tab. With `taken back`, the setting had changed since, so it left your value. Either way it then removed the record | Nothing |
| `tab underline: defaults <verb> said <message>` | At its start the daemon found `tab-underline.json`, which says the panel set iTerm2's `MinimalSelectedTabUnderlineProminence` to 0, and `defaults` refused to read or put back that setting, so the line under the selected tab stays hidden and the record stays for the next start | Restart the panel to try again, or run `defaults delete com.googlecode.iterm2 MinimalSelectedTabUnderlineProminence` and delete the record |
| `tab underline: <path> unreadable: <why>` or `tab underline: <OS error>` | The daemon could not read or remove `tab-underline.json` in the status directory. A record it could not read leaves the line under the selected tab unchanged; a line already put back keeps its record when the removal fails | For a file the panel did not write, put the setting back yourself and delete the file. Otherwise fix the folder's permissions and restart the panel |
| `page error <message> \| <stack>` | The panel could not draw a frame and shows `STALE` until one draws | Report the line; reopening the panel does not fix the frame that breaks it |
| `daemon exit: <reason>` | The daemon ended: `SystemExit(0)` after a stop, else the error that ended it | Start it from the Scripts menu; report the reason if it was not a stop |
| `reopen: no shell prompt after 10s in <path>` | A Resume on History's Sessions tab opened a tab whose shell did not appear in time, so the daemon typed nothing | Type the resume command in that tab, or try again |
| `stop-port <pid> :<port> <program>` | A card's Stop sent `SIGTERM` to that process, after checking it still held the port | Nothing; if the port is still on its card a few seconds later, the program ignored `SIGTERM`, so stop it from its own terminal |
| `ports not read: <reason>` | The daemon could not read the listening ports: `lsof` did not run or printed what it could not parse. No card shows a port until a reading works; said once until then, and tried again every 5 seconds | Act on the reason. `could not run lsof`: check that `/usr/sbin/lsof` runs. `could not read lsof`: report the line |
| `ports: could not read the environment of pid <pid>, so no card shows its ports: <reason>` | The daemon could not read the environment of a listener outside every card's process tree, so it cannot tell which agent started it. That listener shows on no card; every other card keeps its ports. Said once for each process | Nothing, unless a server an agent started is missing from its card; then report the line |

## The white panel

iTerm2 keeps every tool identifier it has seen in its `NoSyncDynamicTools`
preference, and the Toolbelt menu picks a tool by its display name. Two
identifiers both named "Agents" open whichever one iTerm2 finds first, which
can be a dead port. Rename the stale entry to bring the live one back:

```sh
defaults write com.googlecode.iterm2 NoSyncDynamicTools -dict-add <old id> \
  '{ URL = "http://127.0.0.1:1/"; name = "OLD-Agents"; }'
```

## Why STALE exists

A live connection error marks the panel `STALE` at once. A closed connection
retries after two seconds. A fresh heartbeat or a drawn frame clears `STALE`.

A heartbeat only proves the daemon is answering, so it carries the result of
its last read of iTerm2 as well. Without that, a stuck refresh would leave
every row and every permission badge looking current forever. The daemon
sends one right after the first frame of every connection, so a page opened
on a stuck daemon shows `STALE` at once. A frame the
page fails to draw counts the same way: the heartbeats keep coming, but the
list stays `STALE` until a frame draws.

## Tracing the statusline bridge

The bridge renders the statusline that was configured before the sidebar took
the slot, and the status line has one property that makes a slow render its
own worst enemy: Claude Code sets no timeout, but a render still going when it
next wants one is killed, and the kill asks for another render. A render that
loses that race can feed its own retry loop.

`AGENTS_SIDEBAR_BRIDGE_TRACE` records what each tick did and when, so a render
that never finished can be told apart from one that was merely slow. It is off
unless the variable is set, and setting it costs a `date` per event, so trace
both arms of a comparison or neither.

```sh
AGENTS_SIDEBAR_BRIDGE_TRACE=/tmp/bridge.log claude
```

Each line is `<epoch> pid=<bridge> ppid=<claude> <event> [detail]`:

| Event | Means |
| --- | --- |
| `entry` | A tick began |
| `cold` | No line rendered yet; this tick renders one and waits for it |
| `warm-printed` | The line went out: the one this tick rendered, or the last one kept when another tick holds the render or this one failed |
| `lock-taken` | This tick owns the render |
| `lock-held` / `cold-lock-held` | Another render is in flight; this tick adds nothing |
| `lock-stale` | A lock older than ten seconds was reclaimed |
| `cold-lock-age age=<n>` | How old the lock was on a tick with no line to show |
| `render-start` / `render-end rc=<n>` | The user's statusline ran, and how it ended |
| `cold-printed` / `cold-blank` | The first render produced a line, or produced nothing |
| `tick-end` | The bridge outlived its render; absent, the bridge was killed while it waited |

Reading it:

- `render-end rc=137` is a render killed with SIGKILL (128 + 9); `rc=143` is
  SIGTERM. Either means the line lost a race rather than took its time.
- `render-end` with no `tick-end` after it is the ordinary case of a slow
  render: Claude Code SIGKILLs a run still going about two seconds after it
  began, the kill took the bridge, and the render, in a process group of its
  own, finished anyway. Nothing is wrong.
- `render-start` with no `render-end` means the render itself died, and the
  lock it held sits until the ten-second sweep. Before the render had its own
  process group this was what every slow render did, and the line went most
  of a minute without a refresh.
- `render-end rc=0` a long way after its `render-start` is a render that is
  simply slow, which is a different problem with a different fix.
- `warm-printed` lands after `render-end`: the tick renders its own line and
  prints that, so the bar shows the event that caused it. The render is a
  background job in its own process group, and the tick waits for it rather
  than leaving it running, on purpose. The next section says why.

## Why the statusline goes dark

`cs-statusline` picks its light or dark palette by walking its parent pids up
to the tmux server. A render whose ancestors no longer reach that server fails
the walk and paints the dark palette, which against a light terminal reads as
a statusline that suddenly went dark.

The bridge therefore waits for every render it starts. A render started and
left makes the tick return sooner, but the bridge then exits while the render
is still going, the render's subshell is reparented to launchd, and the walk
breaks a link above the render. Tried on 2026-09-18 and reverted the same day;
`test_the_render_keeps_a_living_parent` guards it now.

The render does run in a process group of its own, which is a different thing:
the bridge is still its living parent while the walk happens, and the group
only matters two seconds later, when Claude Code's SIGKILL takes the bridge
and would otherwise take the render with it.
