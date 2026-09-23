# Troubleshooting

| Symptom | What it means | What to do |
| --- | --- | --- |
| Every row dims, `STALE` banner | The daemon missed two heartbeats, or a heartbeat says it can't read iTerm2 | Quit the running script first, in Scripts > Manage > Console or by killing the `venvs/3.10/bin/python` process that runs `agents_sidebar.py`. Then start it from the Scripts menu. Starting it while one runs makes a second daemon |
| A row shows `?` for its directory | iTerm2 can't report that one session's directory. The row leaves out a job it can't read | Nothing; one session costs its own row, not the list |
| The panel is white and nothing loads | Two tool identifiers named "Agents", and the menu opened the dead one | Rename the stale entry, below |
| Codex cards stop appearing | A herdr update rewrote `~/.codex/hooks.json` | `./install.sh --codex` |
| Rows show no context percentage | The statusline bridge is not installed, or `cs -statusline enable` replaced it | Install in the panel's foot, or `./install.sh`. After **Not now** the foot offers nothing until Settings > Offer the statusline bridge brings it back |
| No context percentage, and no offer in the foot | `~/.claude/settings.json` is not valid JSON, so the panel offers nothing | Fix the file; the offer then shows |
| Install in the foot shows red text | `~/.claude/settings.json` stopped being valid JSON after the offer showed, so the panel wrote nothing | Fix the file, then press Install again |
| Update refused, red text in the bar | The checkout could not fast-forward, or `install.sh` failed; the whole message is in the script console | `git -C <checkout> status`, then `./install.sh` by hand |
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

A heartbeat only proves the daemon is answering, so it carries the result of
its last read of iTerm2 as well. Without that, a stuck refresh would leave
every row and every permission badge looking current forever.

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
| `warm-printed` | The line from last time went out; this tick is done |
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
- `warm-printed` lands before `render-start`: the tick answers from the last
  line, then renders the next one itself. The render is a background job in
  its own process group, and the tick waits for it rather than leaving it
  running, on purpose. The next section says why.

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
