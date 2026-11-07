# Development

How the panel works, and the parts that only matter when you change
it.

## The install and the port

`get.sh` is the one-liner's script: it clones to `~/.local/share/agents-sidebar/src`
and runs `install.sh` with its arguments. On an existing install it stops:
it is fetched unsigned, so it never updates one. `./install.sh` writes a stub into
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/`, and the stub loads
`sidebar.py` from the checkout. The daemon reads `page.html` from disk on every
request, so a change to the page alone needs only a reload of the panel
(Option-right-click, Reload). A change to `sidebar.py` needs the daemon
restarted. The new run takes a port the OS picks, so reopen the panel after
it from View > Toolbelt > Agents.

The install starts the daemon at the end when iTerm2 is running and no
Python process runs `AutoLaunch/agents_sidebar.py`. The check excludes
`it2_api_wrapper`. It never restarts an existing daemon; it prints that
daemon's process ID and the kill-and-launch command instead. A launch error prints
a warning without failing the install. With iTerm2 closed, the install
prints the manual start instructions.

To restart the daemon without restarting iTerm2, kill its
`venvs/3.10/bin/python` process, not the `it2_api_wrapper.sh` parent
(`pgrep -f AutoLaunch/agents_sidebar.py` matches both). Nothing starts it
again by itself, so launch it:

```sh
osascript -e 'tell application "iTerm2" to launch API script named "agents_sidebar"'
```

Check that `ps` shows exactly one daemon, then reopen the panel. The kill
(`SIGTERM`) first takes the daemon's words off the tabs, waiting at most two
seconds for iTerm2.

The hook runs from a copy, not from the checkout. `install.sh` copies
`plugin/` to `~/.claude/skills/agents-sidebar`, and that copy is what Claude
Code and Codex run. An edit to the hook needs `./install.sh` again. Each
event runs the hook's scripts fresh from disk, so they are live once copied;
only a change to `hooks.json` also needs `/reload-plugins` in a running
session.

The daemon binds `127.0.0.1` and checks a token of 24 random bytes on every
request, including the event stream. The panel itself reads the live frames
over a WebSocket at `/live`, with the same token, because WebKit allows six
HTTP connections to a host and a stream held open in every window's panel
would leave a sixth window none for its requests.
The panel can ask six things about a
session: focus, send, prompt, close, resume and answer. Alerts are not among
them: the daemon decides sounds, banners and the focus move from its own
reading (`alerts.py`), so a page that fell behind cannot replay old ones.

`send` types raw keys. `prompt` types the agent's next input, and the daemon
refuses it, with a 409 and the reason, while the session waits on you, after
its agent has exited, for a pane listed under SESSIONS (a plain shell, where an
agent that quit cleanly leaves its pane), or while another program is in front of the agent: the
agent's process group is not its terminal's foreground process group, and the
reason names that group's leader ("nvim is in front"). Membership is the test,
not leadership: under a `cs` wrapper bash leads the group, and for Codex its
node launcher does. Both come off the rebuild's one process listing. For a row
with no agent pid, such as a Codex that has published nothing yet, the daemon
asks only whether it waits or has exited.

The server also takes `POST /accounts` (switch, add, rename, read), `/update`,
`/statusline`, `/tab-status` (takes iTerm2's `cc-status` hook out of Claude Code's settings), `/context`, `/link`, `/untie`, `/github` (opens the repository
or releases page the daemon builds), `/rebuild` (registers the panel again under a fresh URL, so iTerm2 builds its web view anew in every window: the reload button's right-click menu), `/stop-port` (`SIGTERM` to the holder of a port a card showed in the daemon's last reading, once a fresh `lsof` and `ps` show the same process still holds it), `/open-port` (opens `http://localhost:<port>` for a port a card showed in that reading) and `/page-error`. No endpoint runs arbitrary code.
`POST /uninstall` checks the token, then accepts an object containing only
the optional boolean `keep_accounts`. An empty body or `{}` defaults to false.
Malformed JSON, unknown keys and other value types return 400 before a job or
log exists. When true, it passes `--keep-accounts` as a separate script argument.
Otherwise, the script deletes saved logins. The route prepares a private log in `$TMPDIR`.
It sends 202 with the log path before starting this checkout's `uninstall.sh`
in its own process session. A pending job holds the open log through the
response, so launching does not reopen a path. A failed response closes it
without launching; a failed launch writes its error into the log. Repeated
requests return 409. The route works in development checkouts too.
`POST /review` takes `{"pane": "<pane id>"}` and asks that pane's partner to
review its change. A refusal returns HTTP 409 with the reason in `error`.
`/live` also refuses a request whose `Origin` header is not `http://` plus its `Host`: a WebSocket skips the browser's cross-origin rules, so that header is what keeps a page on another origin from reading the frames. A request with no `Origin`, such as a script's, passes on the token alone.

Once a reading of iTerm2 has worked, the first or a later one, the daemon writes its port, token and
pid to `~/.local/share/agents-sidebar/endpoint.json`, readable by your user
alone, so `agents-sidebar` can reach `/events`. That puts the token on disk
where before it lived only in the Toolbelt URL. Anything running as you can
read it, and anything running as you can already drive iTerm2 through its
own API, so the file grants nothing new. The command's `status` and `wait`
read `/events` and send no action. `agents-sidebar uninstall` resolves the
command's symlink, runs its checkout's script and returns the script's exit
status. Its `--keep-accounts` flag keeps `~/.config/agents-sidebar/accounts.json`
and its Keychain items while the other panel data goes. It leaves the checkout
and prints a quoted command to delete it.

Settings offers the same uninstall behind an inline confirmation. Its page
state moves from idle to confirmation, submission and acceptance. The confirmation
counts all records in the latest account snapshot, including failed readings.
An unavailable store gets a warning without a count; a known empty store gets
no account warning. **Keep my account logins** is a switch that starts off and sends
`keep_accounts`. A refused or failed `POST` returns to confirmation with the
reason and keeps the choice and count. Cancel, Escape and outside clicks cancel
only before submission; reopening resets the choice.

The statusline bridge treats exit 127 as a missing command and writes
`status line: <command or script> not found`; other failures keep the
cached line. Uninstall removes `statusLine` when the saved command names a
missing absolute script path. It preserves relative paths, whose working
directory belongs to Claude, and restores existing script paths.

## Releases

The version sits in `VERSION`, in the plugin manifest, at the left of the bar
and on a `v` tag. `update.py` compares that file with the tags on the
checkout's `origin` once a day and, on request, fetches, verifies and
fast-forwards the checkout and re-execs the daemon. It follows a mirror whose
history was rewritten with a hard reset instead, when a key the installed
release lists signed the mirror's newest commit.

Every commit on the mirror is signed with the release key. `release-signers`
lists the keys a release may be signed with, in git's allowed-signers format
(`release namespaces="git" ssh-ed25519 …`), and `release-revoked` the public
keys no longer trusted. Update judges each new commit by the lists in the
commit before it, so a commit cannot vouch for itself; the installed
release's lists judge the head of a rewritten history, which has no
installed commit before it. That head must also revoke every key the installed
release revoked. Do not rotate or revoke a key on a rewritten history until
installs have crossed it: an install that skipped the rotating release gets
only a head signed by a key it never learned, and refuses it. To rotate, release
once with the old key a commit that adds the new key (and, to retire the old
one, lists it in `release-revoked`); the release after that is signed with
the new key.

To see an update take without touching your own install, clone the mirror
at the previous signed release and run it under a spare `HOME`; `install.sh`
writes only there, and the clone's `VERSION` moves to the newest release:

```sh
git clone -q https://github.com/hex/iterm-agents-sidebar.git /tmp/clone
git -C /tmp/clone reset -q --hard v<previous>
HOME=/tmp/fakehome python3 -c 'import sys; sys.path.insert(0, "/tmp/clone"); import update
print(update.take("/tmp/clone", "<newest>"))'
```

A checkout with no `origin`, this one included, is offered nothing, and
Update there refuses with `no release is on offer`: it tests the failure
path only. `./release.sh "summary" [notes.md]` bumps it, runs the tests
on main and again on the public tree, pushes one squashed commit to the
mirror, and makes a GitHub release page with the summary, the notes file's
Markdown when one is given, and a compare link to the release before. The
notes go through the same check for addresses and scrub words as the public
tree, before anything is pushed. It needs a local branch `public`, a remote named
`github`, `gh` logged in, and the release key: `RELEASE_SIGNING_KEY` names
it, `~/.ssh/release-signing.pub` by default. That is the public half of a key
an ssh-agent holds (Bitwarden's, run with `SSH_AUTH_SOCK` pointing at it), so
git signs through the agent; a private key file works too. The key is not
this project's own: other projects can list the same one. It signs the public
commit and checks it against the previous release's lists before pushing. It always fails the release if the public tree
carries an email address. `RELEASE_SCRUB="word word"` adds words that fail it
too, and so does `.cs/local/release-scrub`, one word per line, which stays
out of git and so out of every release.

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
- `codex.py`: Codex rate limits, read from Codex's own session logs, and a linked
  Codex session's reply, read from its rollout.
- `omp.py`: what an omp session says about itself, read from its own files.
- `context_usage.py`: a Claude session's `/context`, read from a fork of it.
- `past.py`: the rows of the History fold's Sessions tab, read from Claude Code's transcripts.
- `ports.py`: the ports on each agent's card: `lsof`'s listening TCP sockets, each under the card whose agent's process tree holds it, or whose agent its environment's `CLAUDE_PID` names, with the language its process runs, read off the kernel's name for it.
- `statusline.py`: puts the statusline bridge into Claude Code's settings, and takes iTerm2's `cc-status` hook out.
- `tabstatus.py`: the status under each agent's tab title, written through iTerm2's `set_session_status` and
  taken back when the session exits or goes unreported, the setting goes off or the daemon stops.
- `tabcolour.py`: each card's tab in its cs session colour, mixed over the pane's own backgrounds, written
  through the session's own profile, put back when it no longer applies, and known by its colours after a restart.
- `tabunderline.py`: at the daemon's start, puts back iTerm2's line under the selected tab through `defaults`
  where `tab-underline.json` says the panel set it to 0, unless the user changed it since, and removes the record.
- `update.py`: checks the mirror for a newer release and takes it.
- `links.py`: links between two cards, the one-shot hand-off, through each session's links folder.
- `partners.py`: partner sessions: the record, each end's `partner.json`, and the tasks between them.
- `remote.py`: Remote Control on each Claude card, from its state file, and turned back on after a panel switch.
- `schedules.py`: when a scheduled prompt's cron expression next runs, and the words its row says that in.
- `marks.py`: the word Done as iTerm2's badge in the pane of a session that finished unseen, written through the session's own profile and restored when the pane is seen.
- `activity.py`: the activity report, per day, project and provider, from Claude Code's transcripts and Codex's rollouts.
- `agents-sidebar`: the command scripts use to list agents and wait on one;
  standard library only, and it runs on the Python 3.9 macOS ships.
- `plugin/`: the state hook (`hooks/hooks.json`, `hooks-handlers/`) and
  `statusline-bridge.sh`; `plugin/omp/` holds omp's extension, which runs the
  same hook with `--agent omp`, and its `bun test` cases. `hooks/link.tsx` is
  the mod for linked cards, partners and the task line's two tools, with its
  helpers `partner-text.ts`, `task-line.ts` and `task-cases.ts`, the test world
  `test-world.tsx`, and its `*.test.tsx` kit tests.
- `install.sh`, `uninstall.sh`: put everything in place, and take it out.
- `get.sh`: the one-line installer.
- `codex-hooks.sh`: adds the state hook to Codex's `hooks.json`.
- `codex-sandbox.py`: lets Codex write the task note, in its `config.toml`.
- `omp-extension.sh`: writes omp's extension into omp's agent directory, and
  takes it out.
- `release.sh`: cuts a release to the public mirror.
- `assets/`: the README figures and their scripts, and the notifier's source
  (`notifier.swift`) and icon.
- `tests/`: the test suite; `tests/live/` holds manual scripts that drive a
  real iTerm2 and are not collected.

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
  panel's own task report (`task.py`, run by a Codex session when the prompt hook asks) is
  filtered out, and a home directory in a command reads as `~`.
- **Teammates:** the lead's session id in the teammate's
  `--parent-session-id`, matched against the lead's own id from its statusline
  payload, so nesting needs the statusline bridge. The badge colour comes from
  `--agent-color` on the same command line, the only place it lives.
- **Subagents:** the name from the subagent's meta file, the model from its
  transcript's first reply, and until that reply the model the meta file says
  the Agent call asked for. Until those exist, the row shows the subagent's type.
- **A Claude card's directory** (its name and branch): `workspace.project_dir`
  from the statusline payload. iTerm2's `path` is only the last directory
  pushed to the pane, and after a push iTerm2 stops polling, so a stray push
  sticks; without the statusline bridge the card falls back to it (or to
  tmux's, inside tmux).
- **Plain terminals inside tmux:** iTerm2 doesn't reliably report a pane's
  command or directory, so the panel asks tmux for the pane's tty and
  directory and names the tty's foreground process. A script run by an
  interpreter shows under the script's name: `node .../bin/codex` shows as
  `codex`.
- **Activity** (`GET /activity?days=N`): Claude Code's transcripts and its
  subagents' (under `<conversation>/subagents/`, a workflow's one level
  deeper), and Codex's rollouts, each line counted on the day its own
  timestamp falls on in this machine's time, never by the file's mtime. Claude
  writes a reply once per content block with the whole reply's usage on every
  line, so usage counts once per message id. A prompt is a line whose
  `turnOrigin` is `human`; a transcript with no `turnOrigin` anywhere predates
  the flag, and its prompts go by their text. A subagent's lines can carry a
  session id of their own, so a conversation is its transcript's id, and a
  subagent's the folder it sits in. A worktree under `.claude/worktrees/`
  counts to its checkout, and each row's `scratch` says whether that project
  is `/tmp`, `/private/tmp`, `/var/folders` or `/private/var/folders`, or a
  folder under one; the page lists those apart. Codex's `token_count` totals
  are running sums, so a day gets how far they rose that day. Cost is a
  conversation's only, from its last `cost-state` line, which has no time.
  The page counts neither program's cache reads. The daemon keeps each file's
  figures against its size and mtime and runs one report at a time: on one
  machine a cold week read 641 files in about 9 s of CPU and a warm one in
  about half a second, since it reads again only a file written since the last
  read. After a read that changed them it writes the figures to
  `activity.json` in the status directory, owner-only and renamed over the
  last copy, and it loads that file at the first read of its life, never at
  start. Figures another `activity.py` made (the file's SHA-256), or made in
  another time zone, or not wholly in the shape it writes, are not used: that
  read starts cold and `daemon.log` says why.
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
every open gate. Claude Code can also end a gated tool with no hook at all: a
prompt it times out itself, as for a teammate that cannot prompt, leaves only
the tool's error result in the transcript. While a gate is open, each event
looks for that result in the last megabyte of the transcript (a subagent's
own, for a subagent's tool) and closes the gate when it is there. A Codex state reaches its pane another way when it has to:
Codex runs hooks in an app-server daemon that outlives the Codex that started
it and serves the next, and from there the hook finds no terminal. It files
the state with its directory instead, and the panel gives it to the pane
running Codex in that directory, if exactly one state newer than that Codex
is filed there. In a Codex session any tool starting closes every gate too:
Codex issues no tool while its prompt is up, and waiting for the approved
command to finish kept the card waiting through whole test runs.

Codex fires `PermissionRequest` for every approval request, whoever rules on
it. For a shell command the hook reads the turn's `turn_context` from the end
of the rollout, at most 32 MB back, and opens no gate when its
`approvals_reviewer` is `auto_review`: Auto-review rules on the command. Any
other tool, any other reviewer and a turn it cannot read open the gate. Under
`approval_policy = "never"` an MCP tool's request still opens one for the
moment before the tool runs.

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

The daemon rebuilds the list every two seconds, and at once on three changes:
a window or tab opening or closing, a hook writing `claudeState`,
`codexState` or `ompState` into any pane, and a `.published` file being created, replaced or removed.
The last one is the only word from a Codex whose hooks find no terminal, since
it writes no variable. A rebuild asked for while one runs folds into one more.
If a watch stops, the daemon says so in the Script Console and the two-second
rebuild carries on alone.

A session whose working directory or job iTerm2 can't report shows `?` instead
of a guess.

## What the panel keeps on disk

- `~/.claude/agents-sidebar-subagents/<session id>`: the hook's record for
  each session, with its `.lock` and, for a large state, its `.published` file.
- `~/.claude/agents-sidebar-tasks/`: each session's task note.
- `~/.claude/agents-sidebar-status/`: the statusline payloads and lines,
  `original-statusline`, `daemon.log`, `partners.json`, `activity.json`, the
  `tones/` folder and `tab-underline.json`, kept until the daemon has put back
  iTerm2's line under the selected tab or found it changed.
- `~/.claude/agents-sidebar-links/<session id>/`: each session's link,
  partner and remote control files.
- `~/.claude/agents-sidebar-settings.json`: the panel's settings.
- `~/.config/agents-sidebar/accounts.json`: the accounts the panel knows.
- `~/.local/share/agents-sidebar/endpoint.json`: the running daemon's port,
  token and pid, for `agents-sidebar`.

## Tests

```sh
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

The daemon needs neither; both are for tests only. `tests/test_integration.py`
runs a real listener over real sockets. The omp extension's own tests run with
`bun test` in `plugin/omp/`; `tests/test_omp_extension.py` runs them as part
of the suite, and skips only on a machine without bun.
`tests/test_link_mod.py` runs the mod's kit tests with `claude plugin test`
on `plugin/` as the install ships it, and skips only on a machine without
`claude`.

`defaults` ignores `HOME`, so a spare home still reaches this Mac's iTerm2
settings. An autouse fixture in `tests/conftest.py` points
`tabunderline.DOMAIN` at a plist in each test's own folder, and sets
`AGENTS_SIDEBAR_ITERM_PREFS`, which `uninstall.sh` reads, to the same path.

`Bridge` is the only part that talks to iTerm2, and its tests pin how it takes
its readings (`tests/test_rebuild.py`: one process listing per rebuild, read in
a thread, a burst of layout events folded into one more rebuild, a session's
variables fetched together, a filed state read at once). The rest of `Bridge` gets a manual check against a
live iTerm2. `tests/live/` holds the scripts for that: each opens a throwaway
window on a bare shell, drives the daemon or the iTerm2 API, prints a PASS or
FAIL line per expectation and closes the window. Run them with iTerm2's own
python and its cookie, as their docstrings say; they are not collected by
pytest.

## Measuring what the machine executes

```sh
sudo ./measure-load.sh 10
```

It watches ten seconds with `fs_usage` and reports execs per second, what ran,
who ran it, PATH misses kept apart, and the load average before and after. The
raw lines stay under `$TMPDIR`.

On a managed Mac, endpoint agents inspect every exec, so the exec rate decides
whether the panel's helpers weigh on the machine, more than CPU time does. The
daemon execs `ps` and `tmux` once per rebuild, in a thread, so each hook
event that changes a pane's state costs one more of each. It also runs the
notifier in `~/.local/share/agents-sidebar/Agents.app` once per notice and once
at start to sweep old notices, and `git ls-remote` once a day for updates.
`accounts.py` runs `/usr/bin/security` each time it reads or writes a login
in the Keychain. The statusline bridge execs `mv` and `mkdir` on every tick,
and on a tick that renders also `sh` for your own statusline, a second `mv`
and `rmdir`: five, plus whatever your statusline runs. While a partner task
is out, the mod execs `sleep` every two seconds, for up to ten minutes.

## What the panel costs the GPU

The panel stays open all day, so whatever in it moves without end sets its
GPU cost. `tests/test_page_motion_cost.py`, part of the suite `release.sh`
runs, holds `page.html` to three rules:

- every endless animation, in CSS or started from script, changes only
  `transform` or `opacity`
- every one pauses when the panel hides and when its row leaves the list's
  view
- every blur and filter is on the test's list, and each one got a
  measurement before joining it

The test reads source, not the GPU. When it fails on a new blur, filter or
endless animation, measure the panel with that change on screen, and while
it moves if it does:

```sh
sudo powermetrics --samplers gpu_power,tasks --show-process-gpu -i 1000 -n 10
```

Watch the GPU's active residency and the `com.apple.WebKit.GPU` and
`WindowServer` rows, then add the change to the list. Other apps use the same
GPU, so compare against a reading with the panel closed.

## What the panel costs in memory

WebKit keeps the memory of an element that was styled, drawn and dropped, so
a page that rebuilt its rows on every frame grew without bound. The card list,
the queue and the foot are instead built detached each frame and morphed onto
the live ones: a row's node lives until the row leaves, and a frame changes
text and attributes on it. `tests/test_page_in_place.py` holds the builders
that run per frame to two rules, each an allowlist of the functions that may
break it:

- a builder writes no inline `style`; every value a node can wear is a data
  attribute, and one generated stylesheet carries the rules
- a builder calls no `addEventListener`; a handler goes through `on()`, so
  the kept node runs this frame's closure

The test reads source. The behaviour is measured by
`.cs/local/e2e_in_place.mjs` in a session's local checks: a frame painted
again adds and removes no element, and over a replayed minute of the stream
an unchanged card keeps every element it had. A ten-minute footprint of the
page in a WKWebView is the acceptance figure, and it must run on an
unlocked screen: WebKit stops rendering a hidden page, so a locked Mac
reads flat whatever the page does.

## The figures

```sh
python3 assets/make-banner.py
BANNER_H=864 python3 assets/make-banner.py /tmp/banner-16x9.svg   # a taller cut, for a post
for f in card-states card-anatomy foot settings menu; do python3 assets/make-$f.py; done
```

Each script redraws one SVG the README shows. The marks come from `page.html`
through `assets/panel_draw.py`; the colours are the page's dark-theme tokens,
copied into that module, so a token change there needs a change here. `make-settings.py` reads its rows out of `SETTING_ROWS` and its
defaults out of `sidebar.py` and the repository row out of `update.py`;
`make-menu.py` reads its items out of
`HOUSEKEEPING`. I made the session names up.

`tests/test_figures.py` holds each committed SVG to what its script draws, and
the settings and menu figures to the page's own lists. A changed page fails
the test until you redraw the figure.

A new label on a middot line needs its width measured in Chrome
(`canvas.measureText`, 12.5px in the system face) and added to `MEASURED` in
`panel_draw.py`, because that table places the middots. A new session name
needs its width in `NAME_W` (600 15px), and a new agent tag word in
`TAG_TEXT` (600 11px), measured the same way. So does a word in the other tables: `MEASURED_AT` for Task first's folder name (400 11px), title (600 17px) and small lines (400 10px), `PILL_W` for the state pills and `SOLID_W` for the solid Done badge (both 600 10px), and `BADGE_W` for the corner badges (600 11px). A word missing from `MEASURED` or `MEASURED_AT` falls back to an estimate; the other tables have no fallback, so a missing word stops the script. The mono face needs no table. GitHub plays the banner's animation only from the raw file URL.

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
- [superpowers/specs/2026-10-23-task-line-tools-design.md](superpowers/specs/2026-10-23-task-line-tools-design.md): the
  task line as two tools the link mod registers.
- [superpowers/specs/2026-09-18-account-autoswitch-design.md](superpowers/specs/2026-09-18-account-autoswitch-design.md): switching
  accounts on their own before a limit stalls a session.
- [superpowers/specs/2026-09-21-agent-providers-design.md](superpowers/specs/2026-09-21-agent-providers-design.md): how more
  agents could get cards, and how omp got one.
- [superpowers/specs/2026-10-05-unseen-guard-wait-omp-design.md](superpowers/specs/2026-10-05-unseen-guard-wait-omp-design.md): an
  unseen finish, omp's own events, a guarded prompt and a wait command.
- [superpowers/specs/2026-10-07-drag-order-design.md](superpowers/specs/2026-10-07-drag-order-design.md): dragging
  a card to set an order the panel keeps.
- [superpowers/specs/2026-10-07-linked-cards-design.md](superpowers/specs/2026-10-07-linked-cards-design.md): linking
  two cards so one session hands its result to another.
- [superpowers/specs/2026-10-09-partner-sessions-design.md](superpowers/specs/2026-10-09-partner-sessions-design.md):
  two linked Claude sessions as partners that read each other and hand each other tasks.
- [superpowers/specs/2026-10-10-remote-control-design.md](superpowers/specs/2026-10-10-remote-control-design.md):
  Remote Control turned back on after an account switch, and the mark on a card that has it.
- [superpowers/specs/2026-10-11-remote-panes-design.md](superpowers/specs/2026-10-11-remote-panes-design.md):
  cards for agents on another machine, reached through an ssh or Eternal Terminal pane.
- [superpowers/specs/2026-10-18-finished-marks-design.md](superpowers/specs/2026-10-18-finished-marks-design.md):
  a session that finished unseen lifted and washed in the panel, and the word Done as iTerm2's badge in its pane.
- [superpowers/specs/2026-10-25-terminal-background-design.md](superpowers/specs/2026-10-25-terminal-background-design.md):
  the panel in the colour of the terminal in front, every surface derived from it.
- [superpowers/specs/2026-10-25-tab-status-design.md](superpowers/specs/2026-10-25-tab-status-design.md):
  the status under each agent's tab title, written by the panel, and taking it over from iTerm2's own hooks.
- [superpowers/specs/2026-10-25-card-styles-design.md](superpowers/specs/2026-10-25-card-styles-design.md):
  four ways of drawing session rows without the card, beside the card itself.
- [superpowers/specs/2026-10-30-resume-and-snapshots-plan.md](superpowers/specs/2026-10-30-resume-and-snapshots-plan.md):
  a list of past conversations with Resume, and window snapshots; a plan with
  its questions open, nothing built.
- [superpowers/specs/2026-10-31-teleport-design.md](superpowers/specs/2026-10-31-teleport-design.md):
  moving a cs session to another machine from its card, after the remote relay; nothing built.
- [superpowers/specs/2026-10-31-refined-cards-design.md](superpowers/specs/2026-10-31-refined-cards-design.md):
  the task-first card with a folder line, a state pill and a recency line, picked from real-page renders, with its decisions; built behind Card anatomy.
- [superpowers/plans/2026-09-18-account-autoswitch.md](superpowers/plans/2026-09-18-account-autoswitch.md): the step-by-step
  plan that built the automatic switch.
- [superpowers/plans/2026-10-07-drag-order.md](superpowers/plans/2026-10-07-drag-order.md): the step-by-step
  plan that built the drag order.
- [superpowers/plans/2026-10-08-linked-cards.md](superpowers/plans/2026-10-08-linked-cards.md): the step-by-step
  plan for linking two cards.
- [superpowers/plans/2026-10-09-partner-sessions.md](superpowers/plans/2026-10-09-partner-sessions.md): the step-by-step
  plan for partner sessions.
- [superpowers/plans/2026-10-10-remote-control.md](superpowers/plans/2026-10-10-remote-control.md): the step-by-step
  plan for keeping Remote Control across switches.
- [superpowers/plans/2026-10-11-remote-panes.md](superpowers/plans/2026-10-11-remote-panes.md): the step-by-step
  plan for cards of agents on another machine.
- [superpowers/plans/2026-10-18-finished-marks.md](superpowers/plans/2026-10-18-finished-marks.md): the step-by-step
  plan for the finished marks.
