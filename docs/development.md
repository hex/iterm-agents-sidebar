# Development

How the panel works, and the parts that only matter when you change
it.

## The install and the port

`get.sh` is the one-liner's script: it clones to `~/.local/share/agents-sidebar/src`,
or pulls there, and runs `install.sh` with its arguments. `./install.sh` writes a stub into
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/`, and the stub loads
`sidebar.py` from the checkout. The daemon reads `page.html` from disk on every
request, so a change to the page alone needs only a reload of the panel
(Option-right-click, Reload). A change to `sidebar.py` needs the daemon
restarted. The new run takes a port the OS picks, so reopen the panel after
it from View > Toolbelt > Agents.

To restart the daemon without restarting iTerm2, kill its
`venvs/3.10/bin/python` process, not the `it2_api_wrapper.sh` parent
(`pgrep -f AutoLaunch/agents_sidebar.py` matches both). Nothing starts it
again by itself, so launch it:

```sh
osascript -e 'tell application "iTerm2" to launch API script named "agents_sidebar"'
```

Check that `ps` shows exactly one daemon, then reopen the panel.

The hook runs from a copy, not from the checkout. `install.sh` copies
`plugin/` to `~/.claude/skills/agents-sidebar`, and that copy is what Claude
Code and Codex run. An edit to the hook needs `./install.sh` again. Each
event runs the hook's scripts fresh from disk, so they are live once copied;
only a change to `hooks.json` also needs `/reload-plugins` in a running
session.

The daemon binds `127.0.0.1` and checks a token of 24 random bytes on every
request, including the event stream. The panel can do eight things to a
session: focus, send, close, bring, return, notify, resume and answer. The
server also takes `POST /accounts` (switch, add, rename, read), `/update` and
`/statusline`. No endpoint runs arbitrary code.

## Releases

The version sits in `VERSION`, in the plugin manifest, at the left of the bar
and on a `v` tag. `update.py` compares that file with the mirror's tags once
a day and, on request, fast-forwards the checkout and re-execs the daemon.

To see an update take without touching your own install, clone the mirror
at the previous tag and run it under a spare `HOME`; `install.sh` writes only
there, and the clone's `VERSION` moves to the newest tag:

```sh
git clone -q https://github.com/hex/iterm-agents-sidebar.git /tmp/clone
git -C /tmp/clone reset -q --hard v2026.09.18
HOME=/tmp/fakehome python3 -c 'import sys; sys.path.insert(0, "."); import update
print(update.take("/tmp/clone"))'
```

A checkout whose `main` is not the mirror's, this one included, refuses the
pull, and that refusal is what the bar shows: pressing Update here tests the
failure path only. `./release.sh "summary"` bumps it, runs the tests
on main and again on the public tree, pushes one squashed commit to the
mirror, and makes a GitHub release page with the summary and a compare link
to the release before. It needs a local branch `public`, a remote named
`github` and `gh` logged in. It always fails the release if the public tree
carries an email address. `RELEASE_SCRUB="word word"` adds words that fail it
too.

Before each release, check the docs against what changed since the last tag:

```sh
git diff "$(git describe --tags --abbrev=0 public)" main --stat -- . ':!.cs'
```

For every change a user or a developer can see, the README, `docs/` and the
figures must say it, and nothing in them may still describe the old way.
Redraw the figures whose page parts changed (`python3 assets/make-<name>.py`).
The suite catches what a script can see (`tests/test_docs.py`: links, headings,
unlinked docs, actions, install flags, settings; `tests/test_figures.py`: each
figure is what its script draws); whether a sentence is still true takes a
read against the source.

## The files

- `sidebar.py`: the daemon, run by iTerm2; the rows, the server and the notices.
- `page.html`: the panel itself, one page with its own script and styles.
- `accounts.py`: account usage meters, switching and the Keychain logins.
- `codex.py`: Codex rate limits, read from Codex's own session logs.
- `omp.py`: what an omp session says about itself, read from its own files.
- `context_usage.py`: a Claude session's `/context`, read from a fork of it.
- `statusline.py`: puts the statusline bridge into Claude Code's settings.
- `update.py`: checks the mirror for a newer release and takes it.
- `plugin/`: the state hook (`hooks/hooks.json`, `hooks-handlers/`) and
  `statusline-bridge.sh`.
- `install.sh`, `uninstall.sh`: put everything in place, and take it out.
- `get.sh`: the one-line installer.
- `codex-hooks.sh`: adds the state hook to Codex's `hooks.json`.
- `codex-sandbox.py`: lets Codex write the task note, in its `config.toml`.
- `release.sh`: cuts a release to the public mirror.
- `assets/`: the README figures and their scripts, and the notifier's source
  (`notifier.swift`) and icon.
- `tests/`: the test suite.

## The tool identifier

`com.hexul.agents-sidebar` is permanent. `iterm2.tool` has only
`async_register_web_view_tool` and no way to unregister, so an identifier stays
in the Toolbelt once anything registers it. Registering it again with a new URL
does work, which is why an ephemeral port is fine. See
`docs/troubleshooting.md` for what happens when two identifiers share a
display name.

## Keys

iTerm2 sends printable characters to the terminal and keeps Shift+Enter for
itself, so a `j` and `k` binding or a Shift+Enter one would never fire. Enter,
Space, and Enter with Cmd, Ctrl or Option all reach the panel. Clicking a row
activates that terminal and takes the focus with it, which is why the panel
needs a click on an empty part of itself first.

Option-right-click on a row opens the web view's own menu, with Reload and
Inspect Element.

## Where each fact comes from

- **Shells:** the process tree, because Claude Code publishes them nowhere. The
  panel's own task report (`task.py`, run when the prompt hook asks) is
  filtered out, and a home directory in a command reads as `~`.
- **Teammates:** the lead's session id in the teammate's
  `--parent-session-id`, matched against the lead's own id from its statusline
  payload, so nesting needs the statusline bridge. The badge colour comes from
  `--agent-color` on the same command line, the only place it lives.
- **Subagents:** the name from the subagent's meta file, the model from its
  transcript. Until those exist, the row shows the subagent's type.
- **Plain terminals inside tmux:** iTerm2 doesn't reliably report a pane's
  command or directory, so the panel asks tmux for the pane's tty and
  directory and names the tty's foreground process. A script run by an
  interpreter shows under the script's name: `node .../bin/codex` shows as
  `codex`.
- **CPU and memory:** one `ps` listing per rebuild, summed over each session's
  process tree by parent pid, stopping at any pid that is another card so a
  teammate is not counted twice. CPU is `ps %cpu` summed. Only the verdict
  reaches the page, not the figures, so usage moving below the threshold
  repaints nothing. A chip holds for 15 seconds after its last high reading,
  because a busy process reads anywhere from a quarter to most of a core from
  one refresh to the next.

## State and the permission badge

The hook keeps a record per session of which subagents are alive and which
tools are waiting on you, and a session's state comes from that record, not
from the last event that fired. It has to, because a parent and all its
subagents write to the same terminal. A gate closes when the tool that
opened it runs, fails or is denied, when your next prompt comes, or when the
turn ends: a `Stop`, an `idle_prompt` notification or a `SessionStart` clears
every open gate.

A subagent leaves the record at its own `SubagentStop`. A prompt clears the
finished ones and keeps the running ones, because a subagent sent to the
background runs on through it. One whose stop never arrives would hold the
session at working, so a turn's `Stop` that lists neither a subagent nor a
workflow among its `background_tasks` ends every subagent still marked
running. A Workflow's agents are listed only as the one workflow task that
runs them. A launch starts from none.

The state reaches the daemon as an iTerm2 user variable, written to the pane on
every hook event, in one unbuffered write. The hook keeps it under 512 bytes
of base64: the pane's tty is the one Claude Code draws its status line on, and
a write the tty takes in pieces is cut mid-escape, with the rest of the base64
printed after the status line. A bare state is about 260 bytes and one
subagent fits; a state past the line goes whole into
`~/.claude/agents-sidebar-subagents/<session id>.published`, and the variable
carries the state, the ids and the times with `detail: true`. The daemon reads
the file back on each rebuild. If the hook can't write the file, the variable says
`detail: false` and the card shows its state without its subagents.

A session whose working directory or job iTerm2 can't report shows `?` instead
of a guess.

## What the panel keeps on disk

- `~/.claude/agents-sidebar-events.jsonl`: the hook's event log.
- `~/.claude/agents-sidebar-subagents/<session id>`: the hook's record for
  each session, with its `.lock` and, for a large state, its `.published` file.
- `~/.claude/agents-sidebar-tasks/`: each session's task note.
- `~/.claude/agents-sidebar-status/`: the statusline payloads and lines, and
  `daemon.log`.
- `~/.claude/agents-sidebar-settings.json`: the panel's settings.
- `~/.config/agents-sidebar/accounts.json`: the accounts the panel knows.

## Tests

```sh
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

The daemon needs neither; both are for tests only. `tests/test_integration.py`
runs a real listener over real sockets.

`Bridge` is the only part that talks to iTerm2, and its tests pin how it takes
its readings (`tests/test_rebuild.py`: one process listing per rebuild, read in
a thread, a burst of layout events folded into one more rebuild, a session's
variables fetched together). The rest of `Bridge` gets a manual check against a
live iTerm2.

## Measuring what the machine executes

```sh
sudo ./measure-load.sh 10
```

It watches ten seconds with `fs_usage` and reports execs per second, what ran,
who ran it, PATH misses kept apart, and the load average before and after. The
raw lines stay under `$TMPDIR`.

On a managed Mac, endpoint agents inspect every exec, so the exec rate decides
whether the panel's helpers weigh on the machine, more than CPU time does. The
daemon execs `ps` and `tmux` once per rebuild, in a thread. It also runs the
notifier in `~/.local/share/agents-sidebar/Agents.app` once per notice and once
at start to sweep old notices, and `git ls-remote` once a day for updates.
`accounts.py` runs `/usr/bin/security` each time it reads or writes a login
in the Keychain. The statusline bridge execs `mv` and `mkdir` on every tick,
and on a tick that renders also `sh` for your own statusline, a second `mv`
and `rmdir`: five, plus whatever your statusline runs.

## The figures

```sh
python3 assets/make-banner.py
BANNER_H=864 python3 assets/make-banner.py /tmp/banner-16x9.svg   # a taller cut, for a post
for f in card-states card-anatomy foot settings menu; do python3 assets/make-$f.py; done
```

Each script redraws one SVG the README shows. The marks come from `page.html`
through `assets/panel_draw.py`; the colours are the page's dark-theme tokens,
copied into that module, so a token change there needs a change here. `make-settings.py` reads its rows out of `SETTING_ROWS` and its
defaults out of `sidebar.py`; `make-menu.py` reads its items out of
`HOUSEKEEPING`. I made the session names up.

`tests/test_figures.py` holds each committed SVG to what its script draws, and
the settings and menu figures to the page's own lists. A changed page fails
the test until you redraw the figure.

A new label on a middot line needs its width measured in Chrome
(`canvas.measureText`, 12.5px in the system face) and added to `MEASURED` in
`panel_draw.py`, because that table places the middots. A new session name
needs its width in `NAME_W` (600 15px), and a new agent tag word in
`TAG_TEXT` (600 11px), measured the same way. The mono face needs no table. GitHub plays the banner's animation only from the raw file URL.

To see a figure as GitHub will, render it with headless Chrome rather than
`qlmanage`, which scales the viewBox wrong:

```sh
printf '<img src="file://%s" width=880>' "$PWD/assets/foot.svg" > /tmp/f.html
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --force-device-scale-factor=2 --window-size=880,484 --screenshot=/tmp/foot.png file:///tmp/f.html
```

## Design records

Each of these records a design as it stood on its own date. The code has moved
on since, so read the source for what runs now.

- [accounts-design.md](accounts-design.md): usage meters and switching accounts in the panel.
- [codex-rows-design.md](codex-rows-design.md): Codex sessions as panel rows.
- [iterm2-integration-comparison.md](iterm2-integration-comparison.md): iTerm2's own Claude Code
  integration, measured against this panel.
- [notification-actions-design.md](notification-actions-design.md): our own notice sender, with buttons
  and a reply field.
- [task-line-design.md](task-line-design.md): the task line, a session's own account of its
  work.
- [task-line-mcp-design.md](task-line-mcp-design.md): the task line over MCP, rejected.
- [superpowers/specs/2026-09-18-account-autoswitch-design.md](superpowers/specs/2026-09-18-account-autoswitch-design.md): switching
  accounts on their own before a limit stalls a session.
- [superpowers/specs/2026-09-21-agent-providers-design.md](superpowers/specs/2026-09-21-agent-providers-design.md): how more
  agents could get cards, and how omp got one.
- [superpowers/plans/2026-09-18-account-autoswitch.md](superpowers/plans/2026-09-18-account-autoswitch.md): the step-by-step
  plan that built the automatic switch.
