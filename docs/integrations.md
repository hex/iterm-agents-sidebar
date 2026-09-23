# Integrations

What `./install.sh` changes outside its own files, the statusline bridge and
the Codex hooks, and how to undo them. `./uninstall.sh` undoes most of it at
once, the panel's own data included; below says what it leaves. The bridge
and the hooks each have an opt-out, `--no-statusline` and `--no-codex`. The
README has the short version.

## What the install writes

| Where | What |
| --- | --- |
| `~/Library/Application Support/iTerm2/Scripts/AutoLaunch/agents_sidebar.py` | A stub that loads `sidebar.py` from the checkout, so iTerm2 starts the panel |
| `~/.claude/skills/agents-sidebar` | A copy of `plugin/`, the state hook. Claude Code runs this copy, not the checkout, so after editing `plugin/` run `./install.sh` again |
| `~/.local/share/agents-sidebar/Agents.app` | The app that posts the macOS notices. It needs `swiftc`; without it the install warns and builds nothing. macOS asks once to allow its notifications |
| `~/.claude/settings.json` | The statusline bridge, below |
| `~/.codex/hooks.json` and `~/.codex/config.toml` | The Codex hooks, below |

`--statusline` also exists. The bridge goes in by default, so the flag only
cancels an earlier `--no-statusline` on the same command line.

## The statusline bridge

Claude Code publishes the size of the context window in one place only: the
JSON it hands its statusline command on stdin. It strips the `[1m]` suffix
from the model id before a request goes out, so 143k tokens can be 14% of one
window or 71% of another, and nothing in the transcript says which. Reading
that payload is the only way to show the same percentage Claude Code shows.

The install points `statusLine.command` in `~/.claude/settings.json` at
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
settings file to `settings.json.before-agents-sidebar`. Every install of the
bridge writes that backup again, the panel's Install button included, so it
holds the file from just before the latest install, not the first.

`cs` rewrites `settings.json` from a template, so `cs -statusline enable`
replaces the bridge. The statusline keeps working, but the context figure
stops updating. Run `./install.sh` again to put it back.

While `settings.json` lacks the bridge, the panel's foot offers it. **Install**
puts it in, and **Not now** hides the offer. The Settings row **Offer the
statusline bridge** brings the offer back. A `settings.json` that is not valid
JSON gets no offer; fix the file first.

To undo, run `./uninstall.sh`. It puts back only the `statusLine` key and
leaves the rest of `settings.json` alone, later edits included. Copying the
backup over `settings.json` also works, but it throws away every edit made
since the latest install.

## Codex hooks

When `~/.codex` or a `codex` binary exists, the install registers the state
hook, run with `--codex`, in `~/.codex/hooks.json` for seven Codex events.
Codex asks once to trust the new hooks, and sessions started after that
report. It also adds `~/.claude/agents-sidebar-tasks` to
`[sandbox_workspace_write] writable_roots` in `~/.codex/config.toml`, because
Codex writes only inside its workspace and the task line lives in that
directory. `codex-sandbox.py` makes that edit: it creates the table or the key
when absent and appends to a one-line array. Any other layout (an array over
several lines, or one with a comment after it) it leaves alone with a message,
so add the directory by hand then.
`--codex` installs even when Codex is missing, and creates `~/.codex` for it;
`--no-codex` skips both files.

Before its first prompt, a Codex session has published nothing. The panel
still shows a Codex card for a pane whose foreground job is `codex`.

A `codex exec` that a Claude session runs as a tool reports nothing. It shares
the Claude pane, and the card stays the Claude session's.

Entries other tools put in `hooks.json` (herdr registers its own) stay where
they are, and the first install copies each file to
`hooks.json.before-agents-sidebar` and `config.toml.before-agents-sidebar`; a
re-run keeps those first copies. A file that did not exist gets no copy. A
herdr update can rewrite the hooks file, so run `./install.sh` again if Codex
cards stop showing up.

To undo, run `./uninstall.sh`. It takes only our entries out of `hooks.json`
and leaves the rest. Copying the backups back would also drop what other
tools added since the first install. To take our entries out and keep
everything else installed, run this in the checkout:

```sh
bash codex-hooks.sh --remove ~/.codex/hooks.json \
  ~/.claude/skills/agents-sidebar/hooks-handlers/emit-state.py
```

The `writable_roots` entry in `config.toml` stays either way; remove it by
hand if you like.

See `docs/codex-rows-design.md` for what a Codex card reads and from where.

## Uninstall

`./uninstall.sh` takes no flags. It stops the daemon and removes:

- the AutoLaunch stub, the plugin copy and `Agents.app`
- the bridge from `settings.json`, putting back only the `statusLine` key
- our entries from `~/.codex/hooks.json`, through `codex-hooks.sh --remove`
- the panel's settings, state and account store, and the Keychain items of
  every stored login

It leaves the `writable_roots` entry in `~/.codex/config.toml`, the
`.before-agents-sidebar` backups, and the checkout itself.

## omp

Nothing to install, and nothing to undo. omp has no shell hooks to register. It
does write its state into the tab title, and the panel reads that title from
iTerm2's `autoName`, the same variable that carries Claude Code's marker.

| Title | The card says |
|---|---|
| `π > label` | idle |
| `π ! label` | blocked: an approval or a question waits |
| `π ⠋ label`, or any other mark | working |
| `π: label`, or `π` alone | omp, state unknown (title states are off) |

The format is omp's own (`src/utils/title-generator.ts` in omp 18.2.5), and a
later omp can change it. If omp rows stop showing a state, check the title
first. An extension that calls `setTitle()` replaces the title whole, and the
row then reads as a plain terminal.

The title carries the state and the session's name. The rest of the card comes
from files omp already writes, read and never written:

| On the card | Read from |
|---|---|
| Uptime, CPU and memory | the pane's foreground job, iTerm2's `jobPid`. `ps` calls omp `bun`, so no name match finds it |
| Model and effort | the session log. `~/.omp/agent/terminal-sessions/<tty>` names the log the omp on that terminal is writing |
| Context % | the last answer's `contextSnapshot.promptTokens` against the model's `contextWindow` in `~/.omp/agent/models.db`. A model with a dearer long-context tier counts against that tier's `inputThreshold`, as omp does. With omp's `extendedContext` on, omp's own window is larger and the card reads high |
| The line under the topic | the `intent` of the tool omp last started, the line omp shows above its own status bar. Shown while omp is working or blocked |
| Cost | every answer's `usage.cost.total`, added up. omp prices each answer itself |
| Commands running | a bash result whose `details.async` says a job started, under the command its call gave; the `hub` tool's `jobs` list for each job's status; an `async-result` message for the ones that ended |
| Subagents | a `task` result's `details.progress`, one entry per subagent with its `id` and `agent` kind (its `details.async` names only the first); the `hub` tool's `jobs` of type `task` for the model, the effort and the status (`completed`, `failed` and `cancelled` end a row; only `running` and `completed` were seen on a subagent); an `async-result` message for the ones whose result omp delivered |

The log runs to megabytes, so the panel reads it from where the last reading
stopped. omp never deletes a `terminal-sessions` file, so the panel trusts one
only for a pane whose title says omp is running there.

omp also files each subagent its own log, `<subagent id>.jsonl` in a folder
named after the session log, in the session log's own shapes. A subagent row
reads its context, cost and intent line from that log the way the card reads
its own; the hub's word on the model stands until the log names one.

Not on the card: the task line and the text of a waiting question. Both need
an extension inside omp.

A pane that has published state through a hook speaks for itself, so a Claude
Code or Codex session whose title happens to start with `π` keeps its own row.
