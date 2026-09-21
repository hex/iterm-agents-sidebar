# Integrations

What `./install.sh --statusline` and `./install.sh --codex` change, and how to
undo them. The README has the short version.

## The statusline bridge

Claude Code publishes the size of the context window in one place only: the
JSON it hands its statusline command on stdin. It strips the `[1m]` suffix
from the model id before a request goes out, so 143k tokens can be 14% of one
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

`cs` rewrites `settings.json` from a template, so `cs -statusline enable`
replaces the bridge. The statusline keeps working, but the context figure
stops updating. Run `./install.sh --statusline` again to put it back.

To undo:

```sh
cp ~/.claude/settings.json.before-agents-sidebar ~/.claude/settings.json
```

## Codex hooks

`--codex` registers the state hook, run with `--codex`, in
`~/.codex/hooks.json` for seven Codex events. Codex asks once to trust the new
hooks, and sessions started after that report. It also adds
`~/.claude/agents-sidebar-tasks` to `[sandbox_workspace_write] writable_roots`
in `~/.codex/config.toml`, because Codex writes only inside its workspace and
the task line lives in that directory.

A `codex exec` that a Claude session runs as a tool reports nothing. It shares
the Claude pane, and the card stays the Claude session's.

Entries other tools put in `hooks.json` (herdr registers its own) stay where
they are, and the install first copies the file to
`hooks.json.before-agents-sidebar`. A herdr update can rewrite the file, so run
`./install.sh --codex` again if Codex cards stop showing up.

To undo:

```sh
cp ~/.codex/hooks.json.before-agents-sidebar ~/.codex/hooks.json
```

See `docs/codex-rows-design.md` for what a Codex card reads and from where.

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
