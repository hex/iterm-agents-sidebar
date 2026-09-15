# Agents sidebar

A custom tool in the iTerm2 Toolbelt that lists every terminal session across
all windows and tabs. Sessions running Claude Code, or sitting in a `cs`
session directory, sit in an `AGENTS` group at the top. Everything else falls
under `SESSIONS`. Click a row or select it with the keyboard to focus that
session.

It runs as a single iTerm2 Basic script. No pip, no virtualenv, no
dependencies beyond the standard library.

## Install

```sh
./install.sh
```

That writes a small stub into `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/`
which loads `sidebar.py` from this repo. Editing `sidebar.py` or `page.html`
needs no reinstall.

The daemon re-reads `page.html` on every request, but the Toolbelt panel only
fetches the page once, when it connects. To see a UI change, restart the script
from the Scripts menu. The new run takes a new port, and the panel follows the
re-registered URL.

To start it without restarting iTerm2, use Scripts, AutoLaunch,
`agents_sidebar`. Then open the panel with View, Toolbelt, Agents.

### The context percentage (opt-in)

```sh
./install.sh --statusline
```

Without this, rows show a branch, a model and a state, but no context figure.

Claude Code publishes the size of the context window in exactly one place: the
JSON it hands its statusline command on stdin. The `[1m]` suffix is stripped
from the model id before a request goes out, so 143k tokens is 14% of one
window or 71% of another and nothing in the transcript says which. Reading that
payload is the only way to show a percentage that agrees with the one Claude
Code draws.

`--statusline` points `statusLine.command` in `~/.claude/settings.json` at
`plugin/statusline-bridge.sh`, which publishes the payload to
`~/.claude/agents-sidebar-status/<claude pid>.json` and then renders whatever
statusline was there before. The displaced command is saved to
`~/.claude/agents-sidebar-status/original-statusline`, and the whole settings
file is backed up to `settings.json.before-agents-sidebar`.

It is opt-in because it is the one part that edits a file other tools own. `cs`
rewrites `settings.json` from a template, so `cs -statusline enable` will
displace the bridge; the statusline keeps working and the context figure stops
updating. Re-run `./install.sh --statusline` to restore it.

To undo:

```sh
cp ~/.claude/settings.json.before-agents-sidebar ~/.claude/settings.json
```

### Codex sessions (opt-in)

```sh
./install.sh --codex
```

Registers the same state hook in `~/.codex/hooks.json` for seven Codex events,
run with `--codex`, so a Codex CLI session gets a card in AGENTS too. Codex asks
once to trust the new hooks, and sessions started after that report. Entries
other tools put in that file (herdr registers its own) stay where they are, and
the install first copies the file to `hooks.json.before-agents-sidebar`. A herdr
update can rewrite the file; re-run `./install.sh --codex` if Codex cards stop
appearing.

To undo:

```sh
cp ~/.codex/hooks.json.before-agents-sidebar ~/.codex/hooks.json
```

## Using it

| Key | What it does |
| --- | --- |
| Down | Move to the next session |
| Up | Move to the previous session |
| Enter or Space | Focus the selected session |
| Cmd+Enter or Ctrl+Enter | Send a newline to the selected session |

Arrow keys only, and not Shift+Enter. iTerm2 sends printable characters to the
terminal and claims Shift+Enter for itself, so neither a `j` and `k` binding nor
a Shift+Enter one would ever fire. Enter, Space, and Enter held with Cmd, Ctrl
or Option all do reach the panel. Click an empty part of the panel first to give it keyboard
focus, because clicking a row activates that terminal and takes focus with it.

Shift+Enter exists to unblock an agent sitting at a prompt without leaving the
panel. Focus, send and close are the only three things the panel can do to a session. No
endpoint runs arbitrary code.

Each session is a card. A session doing something has a dark name and the
working dots; a resting one goes grey. A session waiting on you turns its whole
card amber with a WAITING badge, and nothing else on the panel uses that
colour. A session at rest carries a grey IDLE outline, with a faint light sweeping
through the word every two seconds (none when macOS reduces motion). One whose turn has been
working for 20 minutes or more gets a warm `long 25m` outline, since it may
have stalled; the hook stamps when your prompt started the turn. Its teammates sit
inside the card under a guide line, their working dots stacked vertically.

Rows read `t3` for the third tab, `t3.2` for the second pane of a split tab,
and `w2.t3` once a second window exists. The number is a position you can count
to, not iTerm2's internal tab id.

After the model, a bracketed letter gives the session's effort level: `[l]`, `[m]`,
`[h]`, `[xh]` or `[mx]`, in the colours Claude Code's `/effort` picker uses.

A Codex session's card carries the OpenAI mark before its name and shows the
same working, waiting, idle and long badges. Its model comes from the hook;
effort and context come from the tail of its session log, where context is the
figure Codex's own `/status` shows, as percent used. It has no teammates and no
background-shell line.

Bring a blocked session forward, in settings, focuses a session the moment it
starts waiting on you. It is off by default, and like the sounds it only acts
while the panel is open.

Under it, Go back once it resumes (on by default) returns you to the pane you
were in once that session stops waiting on you. It only goes back if you are
still on the session it brought you to; move somewhere yourself and you stay
there. Chained blocks unwind in order.

Right-click an agent row, or press Shift+F10 on a selected one, for `/compact`,
`/rotate`, `/clear` and Close. Any other row offers Close alone. Close shuts
the iTerm2 pane, and it and `/clear` both ask for a second click. Option-right-click opens the
web view's own menu instead, with Reload and Inspect Element.

A teammate wears the badge colour Claude Code gave it when it was spawned,
read off its process's `--agent-color` argument, which is the only place that
colour is kept.

A plain terminal at its prompt shows a shell mark in its session colour where an agent shows its square. One running a command shows the working dots and the command's
name, and goes quiet when it is back at its prompt. Inside tmux iTerm2 reports
neither a pane's command nor its directory reliably, so the panel asks tmux for
the pane's tty and directory and names the tty's foreground process. A script
run by an interpreter shows under the script's name: `node .../bin/codex` shows as
`codex`.

The panel's foot, above the gear, holds two quiet pieces. While any session
waits on you, a queue lists them oldest first with how long each has waited
(`12m`, `<1m`); click one to focus it. Nothing waiting, no queue. Under it sit
the account limits and, under a dotted rule, a coin mark with what the running
Claude Code sessions report having spent at API prices, then a terminal mark with
how many sessions report it. Hover either for what it counts.

Until you store an account, the limits come from the sessions' status lines:
5-hour and weekly as hairlines with the percentage used and the time left until
the reset. With
no statusline data from any session those lines disappear rather than read zero.

Click **Add this account** to store the login Claude Code is using right now.
The panel copies its credential into its own Keychain item
(`agents-sidebar-accounts`) and lists the account in
`~/.config/agents-sidebar/accounts.json`. The email stays in the Keychain, next
to the credential, and never goes into that file. For a second
account, `/login` as it in Claude Code and click Add again.

With accounts stored, the foot lists every account behind the Claude mark, the
one your sessions run on first and labelled `active`; the others sit dimmed
until you point at one. Each shows its 5-hour limit, its weekly limit, and every
per-model weekly limit the account has (Fable, for example), with the time left
until each resets (`2h`, `3d`, `14m`). Bars are green, amber from 70%, and red
with a red percentage from 90%, the bands cswap uses. A tick on a weekly line
marks where an even spend across the week would be, and a percentage 15 points
or more past its tick turns warm. The foot shows an account's nickname,
or its email when it has none. Click a name to give it a nickname: Enter saves,
Esc cancels, and an empty name goes back to the email. A reading that failed
shows its last figures with `as of 14:02`, and
an account whose login no longer works says `log in to <name> again`.

The panel reads usage at most every 10 minutes per account, backing off to 30
minutes when a reading fails and waiting an hour after a 429. It refreshes the
tokens of the accounts you are not using, and never touches the active one,
which belongs to Claude Code.

To switch, point at an account and click the **Switch** button that floats over
its bars, then click **Confirm switch** within 4 seconds. The panel first refreshes that account's token, which proves its
login still works, then swaps Claude Code's credential and the account in
`~/.claude.json` while holding Claude Code's own locks. If any step fails after a
write, the panel puts the old login back and says so. Running sessions pick the
new account up within about 30 seconds.

Under the accounts, behind the OpenAI mark, the foot shows Codex's own limits
when you have Codex CLI: a bar for each window Codex reports, 5-hour and
weekly or weekly alone depending on the plan. The panel reads them from the end
of Codex's newest session log in `~/.codex/sessions`, which Codex updates on
every turn, so it makes no request and never touches Codex's login. A window
whose reset time has passed reads 0% until Codex reports again.

If cswap (claude-swap) runs on the same machine, the two tools hold copies of
the same refresh tokens, and a refresh token works once. Each refresh by the
panel spends cswap's copy, so cswap shows those accounts as needing a login.

Inside a card, under its teammates, each running subagent gets its own row: the
name it was given (a workflow agent's label, such as `read:theirs-features`),
the model it replies with, and how long it has run. Claude Code writes the
name to the subagent's meta file and the model to its transcript, beside the
session's own; until those exist the row shows the subagent's type. A
subagent that finishes keeps its row, dimmed with a check and how long it ran,
until you send the next prompt, so a busy workflow does not shift the list
every time one of its agents ends. Click
one to focus its session. Show subagents in settings hides them.

A session's background shells fold into one line at the foot of its card, such
as "2 commands running", with the same light sweep as the IDLE badge. Click it to open or close the list; each shell then
has its own row, labelled with the command. Start expanded, under Show
background shells in settings, opens every card's list by default. Click a
shell row for the whole command and a Copy button; the popover stays put while
the list refreshes behind it. The panel finds shells in the process tree, since Claude Code
publishes them nowhere. A shell whose command the panel cannot parse shows `?`.
Show background shells in settings hides them.

## When the panel says `STALE`

Every row dims and a banner appears when the list on screen is no longer known
to be true. Two causes, one banner: the daemon has missed two heartbeats, or a
heartbeat has arrived saying the daemon itself has not managed to read iTerm2
recently. A heartbeat only proves the daemon is answering, so it carries that
verdict -- otherwise a stalled refresh would leave every row and every
permission badge looking current forever. Restart the script from the Scripts
menu.

The panel would rather show nothing than show a plausible wrong answer. A
session whose working directory or job iTerm2 cannot report renders `?` instead
of a guess, and one such session costs its own row, not the whole list.

The same rule governs the permission badge. A session's state is derived from a
record the hook keeps per session -- which subagents are alive, and which tools
are waiting on you -- rather than from whichever event fired last, because a
parent and all its subagents write to the one terminal. A gate is closed only
by the tool that opened it, or by your next prompt; nothing else may decide on
its behalf that you are no longer needed.

## Tests

```sh
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

The daemon itself needs neither. Both are test-only, and `tests/test_integration.py`
drives a real listener over real sockets.

`Bridge` is the one unit without automated tests, because it alone talks to
iTerm2, and mocking that API would only test the mock. It gets a
manual smoke test against a live iTerm2 instead.

## Notes

The tool identifier `com.hex.agents-sidebar` is permanent. `iterm2.tool`
exposes only `async_register_web_view_tool` and no way to unregister, so an identifier
stays in the Toolbelt once anything registers it. Re-registering it with a new
URL does work, which is why the daemon can take an ephemeral port and still
find its panel after a restart. iTerm2 keeps every identifier it has seen in
its `NoSyncDynamicTools` preference, and the Toolbelt menu picks a tool by its
display name, so two identifiers both named "Agents" open whichever one iTerm2
finds first, possibly a dead port and a white panel. Rename the stale entry
(`defaults write com.googlecode.iterm2 NoSyncDynamicTools -dict-add <old id>
'{ URL = "http://127.0.0.1:1/"; name = "OLD-Agents"; }'`) to bring the live one back.

The daemon binds `127.0.0.1` on an OS-assigned port and checks a random
32-byte token on every request, including the event stream.
