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
