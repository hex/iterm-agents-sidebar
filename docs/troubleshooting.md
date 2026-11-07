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
| `accounts hidden: <error>` in the foot | The panel can't read the account store, `~/.config/agents-sidebar/accounts.json` | Fix that file; the error says what is wrong with it |

Some failures show only in `~/.claude/agents-sidebar-status/daemon.log`:

| Line in `daemon.log` | What it means | What to do |
| --- | --- | --- |
| `no notifier at <path>; run install.sh` | `Agents.app` is missing, so no notices go out | `./install.sh`; it needs `swiftc` |
| `resume refused <session>` | A resume click found the session gone, not resumable, or a resume already under way | Nothing; click again once the card offers it |
| `answer refused <session> <text>` | A click on a card's answer came after the question changed or was already answered | Answer in the pane |
| `auto-switch: nowhere to go, <why>` | The panel should leave the account, but no other account fits | Wait for a reset, or add an account |
| `auto-switch refused: <why>` | An automatic switch failed, and the login did not change | Act on the reason it gives |
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
