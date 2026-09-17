<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/banner.svg" width="100%" alt="An iTerm2 window with the Agents sidebar docked on the right: a card per session, and the one waiting on a question turning amber">

# Agents sidebar

A tool for the iTerm2 Toolbelt that lists every terminal session in every
window and tab. Sessions running Claude Code, or sitting in a `cs` session
directory, go in an `AGENTS` group at the top. Everything else goes under
`SESSIONS`. Click a row, or select it with the keyboard, to focus that session.

It runs as a single iTerm2 Basic script. No pip, no virtualenv, nothing beyond the
standard library.

## Install

```sh
git clone https://github.com/hex/iterm-agents-sidebar.git
cd iterm-agents-sidebar
./install.sh
```

The clone is the install. The script writes a small stub into
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/`, and the stub loads
`sidebar.py` from the checkout, so leave the directory in place. Editing
`sidebar.py` or `page.html` needs no reinstall, and `git pull` updates it.

To start it without restarting iTerm2, pick Scripts, AutoLaunch,
`agents_sidebar`. Then open the panel with View, Toolbelt, Agents.

The daemon reads `page.html` again on every request, but the panel fetches the
page only once, when it connects. To see a UI change, restart the script from
the Scripts menu. The new run takes a new port and the panel follows it.

A release number reads `YYYY.MM.BUILD`, and the last part counts the releases in that month: `2026.09.1`, `2026.09.2`, then `2026.10.1`. The number is in
`VERSION`, in the plugin manifest, at the foot of the settings and on a `v` tag
in this repository. `./release.sh "summary"` cuts the next one.

### Notifications

A macOS notification always shows its sender's icon and name, so the panel
posts through a small app of its own. `install.sh` compiles
`assets/notifier.swift` with `swiftc` into
`~/.local/share/agents-sidebar/Agents.app`, with the icon from `assets/`, its
own bundle id and an ad-hoc signature. `swiftc` comes with the Xcode Command
Line Tools (`xcode-select --install`, then run the script again).

macOS asks once to allow notifications from Agents. After that the app has its
entry in System Settings, Notifications, where you set its sound and banner
style. The bundle is rebuilt only when the source or the icon changes, because
signing it again can bring the permission prompt back. Without `swiftc` the
panel works as usual and posts nothing.

### The context percentage (opt-in)

```sh
./install.sh --statusline
```

Without this, rows show a branch, a model and a state, but no context figure.

Claude Code publishes the size of the context window in one place only: the
JSON it hands its statusline command on stdin. Claude Code strips the `[1m]` suffix from the model id before a request goes out, so 143k tokens can be 14% of one
window or 71% of another, and nothing in the transcript says which. Reading
that payload is the only way to show the same percentage Claude Code shows.

`--statusline` points `statusLine.command` in `~/.claude/settings.json` at
`plugin/statusline-bridge.sh`. The bridge publishes the payload to
`~/.claude/agents-sidebar-status/<claude pid>.json`, then renders the
statusline that was there before. It sets `CS_STATUSLINE_PARENT` to the claude
pid, so a statusline that caches by its parent pid (cs's does) still finds its
cache.

It leaves `refreshInterval` alone. The tick rate is cs's to set, because its
logo's attention pulse runs on that timer. At one second, the bridge costs two
execs on a tick that finds a render still running. The daemon deletes files a
session leaves behind once they are a day old.

The install saves the replaced command to
`~/.claude/agents-sidebar-status/original-statusline` and backs up the whole
settings file to `settings.json.before-agents-sidebar`.

It's opt-in because it's the one part that edits a file other tools own. `cs`
rewrites `settings.json` from a template, so `cs -statusline enable` replaces
the bridge. The statusline keeps working, but the context figure stops
updating. Run `./install.sh --statusline` again to put it back.

To undo:

```sh
cp ~/.claude/settings.json.before-agents-sidebar ~/.claude/settings.json
```

### Codex sessions (opt-in)

```sh
./install.sh --codex
```

This registers the same state hook, run with `--codex`, in
`~/.codex/hooks.json` for seven Codex events, so a Codex CLI session gets a
card in AGENTS too. Codex asks once to trust the new hooks, and sessions
started after that report.

A `codex exec` that a Claude session runs as a tool reports nothing. It shares
the Claude pane, and the card stays the Claude session's.

Entries other tools put in that file (herdr registers its own) stay where they
are, and the install first copies the file to
`hooks.json.before-agents-sidebar`. A herdr update can rewrite the file, so run
`./install.sh --codex` again if Codex cards stop showing up.

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

Arrow keys only. iTerm2 sends printable characters to the terminal and keeps
Shift+Enter for itself, so a `j` and `k` binding or a Shift+Enter one would
never fire. Enter, Space, and Enter with Cmd, Ctrl or Option all reach the
panel. Click an empty part of the panel first to give it keyboard focus,
because clicking a row activates that terminal and takes the focus with it.

Cmd+Enter is there to unblock an agent sitting at a prompt without leaving the
panel. Focus, send and close are the only three things the panel can do to a
session. No endpoint runs arbitrary code.

### Cards

Each session is a card. A session doing something has a dark name and the
working dots. A resting one goes grey, with a grey IDLE outline and a faint
light sweeping through the word every two seconds (none when macOS reduces
motion).

A session waiting on you turns its whole card amber with a WAITING badge.
Nothing else on the panel uses that colour.

A turn that has been working for 20 minutes or more gets a warm `long 25m`
outline, since it may have stalled. The hook stamps the time your prompt
started the turn.

A session whose turn has ended stays working while a background shell,
subagent, workflow or monitor it started is still running, because that task's
end wakes it up. A background command that never ends keeps it working until
your next prompt.

Rows read `t3` for the third tab, `t3.2` for the second pane of a split tab,
and `w2.t3` once there is a second window. The number is a position you can
count to, not iTerm2's internal tab id.

### Order

Cards sit in the order iTerm2 lists windows, tabs and panes, so a card is where
its terminal is, and nothing a session does moves it. Sort cards by name, under
Rows in settings and off by default, puts the top-level cards in alphabetical
order instead. Teammates stay under their lead and a worktree card stays
docked to its session either way.

### Model, effort and Codex

After the model, a letter in brackets gives the session's effort level: `[l]`,
`[m]`, `[h]`, `[xh]` or `[mx]`, in the colours of Claude Code's `/effort`
picker.

A Codex card has the OpenAI mark before its model, where a Claude card has the
Claude mark. It shows the same working, waiting, idle and long badges. The
model comes from the hook. Effort and context come from the end of its session
log, and context is the figure Codex's own `/status` shows, as percent used. A
Codex card has no teammates and no background-shell line.

### CPU and memory

A session using a lot of the machine gets a `CPU` or `Mem` chip at the end of
its facts line. The figure covers the session's whole process tree: claude or
codex, its MCP servers, shells, builds and subagent processes. The panel finds
them by parent pid in the one `ps` listing it already takes on each refresh. A
teammate or another session further down the tree counts only on its own card.

CPU is `ps %cpu` summed, where 100% is one full core. Memory is resident size.
The chips show at 100% CPU and 2 GB by default, and you set both under Rows in
settings, as CPU heavy at and Memory heavy at.

Only the on or off result reaches the panel, not the figures, so usage moving
around below the threshold repaints nothing. A chip stays for 15 seconds after
its last high reading. Under load, a busy process reads anywhere from a quarter
to most of a core from one refresh to the next, and a session near the line
would flicker without that.

### Notifications and answering from a banner

Show macOS notifications, in settings, posts a banner when a session asks a
question and when one finishes a turn. Each has its own switch, and all are on
by default.

The banner uses the session's name as the card shows it, so a teammate's
banner has its agent name and a plain shell's has its path. The panel posts nothing for the session you are looking at, meaning the session in front of its window
while iTerm2 is the frontmost app. A session in another tab of the same window
still gets one, since that is exactly when you can't see it.

A session has one banner at most, and going back to work takes it down. Like
the sounds, banners only post while the panel is open, and they need the app
that `install.sh` builds (see Install). A banner plays no sound of its own. The
sound switches are separate, so a banner and a chime are two choices.

The banner can answer for you:

- **A click** brings that session forward, tab and all.
- **A question** from Claude Code shows with its options as buttons (four at
  most) and Other as a text field. A button sends the option's number into the
  prompt. Other picks that option and types your text. macOS shows a single
  action inline and folds two or more into an Options menu, so a question is
  always a menu.
- **Any other permission gate** shows what the tool wants to run and one Allow
  button, which answers Yes. The banner shows only the command's first line,
  while Allow approves the whole command, so No stays in the terminal.
- **A finished turn** offers a Reply field, and its text becomes the session's
  next prompt.

The banner sends keystrokes only while its question is still open. If you already answered it in the terminal, the banner sends nothing.
Codex sessions get a plain banner without these.

### Focus

Bring a blocked session forward, in settings, focuses a session as soon as it
starts waiting on you. It's off by default, and like the sounds it only acts
while the panel is open.

Under it, Go back once it resumes (on by default) takes you back to the pane
you were in once that session stops waiting. It only goes back if you are
still on the session it brought you to. If you moved somewhere yourself, you
stay there. Blocks in a row unwind in order.

### Row menu

Right-click an agent row, or press Shift+F10 on a selected one, for `/compact`,
`/rotate`, `/clear` and Close. Other rows offer Close only. Close shuts the
iTerm2 pane, and both Close and `/clear` ask for a second click.
Option-right-click opens the web view's own menu instead, with Reload and
Inspect Element.

### Teammates and worktrees

A teammate sits under the lead that spawned it, wherever it runs. Its process
names the lead's session in its `--parent-session-id` argument, and the lead's
own session id comes from its statusline payload, so this match needs the
statusline bridge. The teammate wears the badge colour Claude Code gave it,
read from `--agent-color` on the same command line (the only place that colour lives), and takes the name Claude Code calls it by.

A session in a linked git worktree of another open session's repo (a cs
feature session in `<repo>@worktree`, for example) keeps its own card. The card
sits right after that session's card, tied to it by a short line across the
gap. Its name is the feature, the part after the `@`, since the branch has its own
chip. A worktree directory without an `@` takes its branch as its name. When
the main session isn't open, the card stays put, under its own name.

### The task line

Under its name, an agent shows what it says it's doing: a task title, then
`Reading code · 40s`, then a row of ticks, green for the part it says is finished. The session writes the whole line itself. The name is in the main text colour,
the task is grey, and what the session is doing right now uses the same green
as the ticks, so one colour marks the live part of the report.

The state hook asks the session to report, at every prompt and at most once a
minute after a tool. It names the current request and reports a rough
percentage and a two to four word activity through `hooks-handlers/task.py`.
The note goes to `~/.claude/agents-sidebar-tasks/<session id>.json`. Codex
writes only inside its workspace, so `install.sh --codex` also adds that
directory to `[sandbox_workspace_write] writable_roots` in
`~/.codex/config.toml`.

The percentage is the model's own estimate, not a measurement, so the report's
age is part of the line. A report older than five minutes turns grey and reads
`stale`. A hundred percent shows `Done` and stays until a new request starts a
new task.

The ticks show the estimate as a count you can glance at. They are not the
solid bars of the limit meters in the foot, on purpose: those go green, amber
and red, and that would make being nearly done look like a warning.

Show task, in settings, turns the line off. Under it, the activity, the
report's age and the progress ticks each turn off separately. The design
follows herdr-agent-progress.

### Plain terminals

A plain terminal takes its path as its name, as its prompt writes it
(`~/src/acme`). Its tab's title sits on the line below, before the branch. The
panel leaves out a default title: the shell's name or `user@host:path`.

At its prompt, it shows a shell mark in its session colour where an agent
shows its square. While it runs a command it shows the working dots and the
command's name, and it goes quiet when it's back at its prompt.

Inside tmux, iTerm2 doesn't reliably report a pane's command or directory, so
the panel asks tmux for the pane's tty and directory and names the tty's
foreground process. A script run by an interpreter shows under the script's
name: `node .../bin/codex` shows as `codex`.

### The foot and the bar

While any session is waiting on you, the foot lists them oldest first with how
long each has waited (`12m`, `<1m`). Click one to focus it. With nothing
waiting, there is no list. The account limits sit under it.

The bar under the foot, behind its own rule, starts with a coin mark and what
the running Claude Code sessions report having spent at API prices. Next is a
terminal mark with how many sessions report it. Hover either one to see what
it counts. On the right are two buttons: reload, which reads `page.html` again
without closing the panel, and the gear, which opens the settings. In settings,
each topic is a card. The switch in its title turns the topic on or off, and
its options sit under a guide line and fold away while it's off.

### Account limits

Until you store an account, the limits come from the sessions' status lines:
5-hour and weekly, as thin bars with the percentage used and the time left
until the reset. If no session sends statusline data, those lines disappear instead of showing zero.

Click **Add this account** to store the login Claude Code is using right now.
The panel copies its credential into its own Keychain item
(`agents-sidebar-accounts`) and lists the account in
`~/.config/agents-sidebar/accounts.json`. The email stays in the Keychain next
to the credential and never goes into that file. To add a second account,
`/login` as it in Claude Code and click Add again.

With accounts stored, the foot lists every account behind the Claude mark. The
one your sessions run on comes first, with a green check. The others stay dim until you point at one. Each shows its 5-hour limit, its weekly limit,
and every per-model weekly limit the account has (Fable, for example), with
the time left until each resets (`2h`, `3d`, `14m`).

Bars are green, amber from 70%, and red with a red percentage from 90%, the
same bands cswap uses. A tick on a weekly line marks where an even spend
across the week would be, and a percentage 15 points or more past its tick
turns warm.

The foot shows an account's nickname, or its email if it has none. Click a
name to set a nickname: Enter saves, Esc cancels, and an empty name goes back
to the email. A failed reading keeps showing its last figures with
`as of 14:02`. An account whose login stopped working says
`log in to <name> again`.

The panel reads usage at most every 3 minutes per account, which is how often
cswap measured the endpoint allows. When an account's usage moved since the last reading, the panel reads it twice
as often, down to that 3-minute floor. When it stays still, the panel reads it
less often, up to 5 minutes for the active account and 10 for the others, and
never later than a window's reset. A failed reading backs
off to 30 minutes, and a 429 waits an hour. The reload button asks for fresh
readings first, except for an account read in the last 3 minutes.

The panel refreshes the tokens of the accounts you are not using. It never
touches the active one, because that one belongs to Claude Code.

To switch, point at an account and click the **Switch** button over its bars,
then click **Confirm switch** within 4 seconds. The panel first refreshes that
account's token, which proves its login still works. Then it swaps Claude
Code's credential and the account in `~/.claude.json` while holding Claude
Code's own locks. If a step fails after a write, the panel puts the old login back and says so. Running sessions pick up the new account within about 30
seconds.

Under the accounts, behind the OpenAI mark, the foot shows Codex's own limits
if you have Codex CLI: a bar for each window Codex reports, 5-hour and weekly,
or weekly alone, depending on the plan. The panel reads them from the end of
Codex's newest session log in `~/.codex/sessions`, which Codex updates on every
turn, so it makes no request and never touches Codex's login. A window whose
reset time has passed reads 0% until Codex reports again.

If cswap (claude-swap) runs on the same machine, both tools hold copies of the
same refresh tokens, and a refresh token works only once. Every refresh the
panel does spends cswap's copy, so cswap then shows those accounts as needing
a login.

### Subagents

Inside a card, under its teammates, each running subagent gets its own row: its name (a workflow agent's label, like `read:theirs-features`), the
model it replies with, and how long it has been running. Claude Code writes the
name to the subagent's meta file and the model to its transcript, next to the
session's own. Until those exist, the row shows the subagent's type.

A subagent that finishes keeps its row, dimmed, with a check and how long it
ran, until you send the next prompt. That way a busy workflow doesn't shift the
list every time one of its agents ends. Click a row to focus its session. Show
subagents, in settings, hides them.

### Background shells

A session's background shells fold into one line at the bottom of its card,
like "2 commands running", with the same light sweep as the IDLE badge. Click
it to open or close the list. Each shell then has its own row, labelled with
its command.

When the last shell ends, the line stays for a few seconds, dimmed, as
"1 command finished", so a run of short commands doesn't grow and shrink the
card each time. The panel's own task report (task.py, run when the prompt hook
asks) is never counted, and a home directory in a command reads as `~`.

Start expanded, under Show background shells in settings, opens every card's
list by default. Click a shell row to see the whole command with a Copy button.
The popover stays in place while the list refreshes behind it.

The panel finds shells in the process tree, because Claude Code doesn't publish
them anywhere. A shell whose command the panel can't parse shows `?`. Show
background shells, in settings, hides them.

## When the panel says `STALE`

Every row dims and a banner shows up when the list on screen is no longer known
to be true. Two causes lead to the one banner: either the daemon missed two
heartbeats, or a heartbeat arrived saying the daemon itself hasn't managed to
read iTerm2 recently. A heartbeat only proves the daemon is answering, so it
carries that result too. Without it, a stuck refresh would leave every row and
every permission badge looking current forever. Restart the script from the
Scripts menu.

The panel would rather show nothing than a believable wrong answer. A session
whose working directory or job iTerm2 can't report shows `?` instead of a
guess, and one such session costs its own row, not the whole list.

The permission badge follows the same rule. The hook keeps a record per
session of which subagents are alive and which tools are waiting on you, and a
session's state comes from that record, not from the last event that fired. It
has to, because a parent and all its subagents write to the same terminal. Only the tool that opened a gate closes it, or your next prompt does. Nothing
else gets to decide that you are no longer needed.

## Tests

```sh
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

The daemon needs neither of these. Both are for tests only, and
`tests/test_integration.py` runs a real listener over real sockets.

`Bridge` is the only part that talks to iTerm2, and mocking that API would only
test the mock. Its tests pin how it takes its readings
(`tests/test_rebuild.py`: one process listing per rebuild, read in a thread, a
burst of layout events folded into one more rebuild, a session's variables
fetched together), and the rest gets a manual check against a live iTerm2.

### Measuring what the machine executes

On a managed Mac, endpoint agents inspect every exec, so the exec rate decides
whether the panel's helpers weigh on the machine, more than CPU time does.
`sudo ./measure-load.sh 10` watches ten seconds with `fs_usage` and reports
execs per second, what ran, who ran it, PATH misses kept apart, and the load
average before and after. The raw lines stay under `$TMPDIR` for a closer
look. The daemon execs `ps` and `tmux` once per rebuild, in a thread. The
statusline bridge execs four times per render.

## Notes

The tool identifier `com.hexul.agents-sidebar` is permanent. `iterm2.tool` has
only `async_register_web_view_tool` and no way to unregister, so an identifier
stays in the Toolbelt once anything registers it. Registering it again with a
new URL does work, which is why the daemon can take a random port and still
find its panel after a restart.

iTerm2 keeps every identifier it has seen in its `NoSyncDynamicTools`
preference, and the Toolbelt menu picks a tool by its display name. Two
identifiers both named "Agents" open whichever one iTerm2 finds first, which
can be a dead port and a white panel. Rename the stale entry to bring the live
one back:

```sh
defaults write com.googlecode.iterm2 NoSyncDynamicTools -dict-add <old id> \
  '{ URL = "http://127.0.0.1:1/"; name = "OLD-Agents"; }'
```

The daemon binds `127.0.0.1` on a port the OS picks and checks a random 32-byte
token on every request, including the event stream.

`python3 assets/make-banner.py` redraws `assets/banner.svg`, the image at the
top of this file. It reads the marks and colours from `page.html`, so the
drawing can't drift from the real panel. I made up the session names in it.
GitHub plays the animation only from the raw file URL, which is what that image
points at.
