# Task line over MCP: a proposal

Rejected, not built. Written 2026-09-17 to decide whether the task line
should stop spawning a process for every report.

Two reviews said no. An MCP tool call still blocks the model. It saves the
interpreter startup, but the reports still wait. Over HTTP, the MCP session id
does not tell which Claude process is calling, so the session id would still be
a tool argument. A user-level entry also makes every Claude session log a failed
connection when iTerm2 is not running. We fixed the race below with a lock
instead: `task.py` and `clear_note` hold `<session>.lock` around the note.

## What it costs today

Every report is `python3 plugin/hooks-handlers/task.py --session <id> report
--activity '...' --percent N`, and the model waits for it. Measured on this
machine under load: 144 ms a call, of which 107 ms is bare interpreter startup
(`python3 -c pass`) and about 37 ms is the script. At roughly one report a
minute that is 8.6 seconds an hour per reporting session.

A second cost is quieter. `task.py` reads the note and writes it back
with nothing between the two, and only the publish is atomic (`<path>.<pid>`
then `os.replace`). One writer per session makes that safe in practice, but that is a convention the code does not enforce, and it rules out detaching the call: a late report could undo a newer one, or write a note back after
`clear_note` deleted it at SessionEnd.

## The proposal

The daemon already runs, already owns an HTTP server on loopback, and already
reads every note on a timer. Let it accept the reports directly, as an MCP
server, and let the agents call a tool instead of spawning Python.

- `task_begin(title)` and `task_report(activity, percent | unknown)`, matching
  what `task.py` takes today.
- The session id comes from the MCP session, not from the model. The model
  cannot report for another session by mistake, which the current command
  allows.
- The daemon holds the note in memory and writes it. One process writes each
  note, so the read-then-write race disappears without a lock, and the panel
  can paint the report on the next rebuild without waiting for a file read.

The hook does not change. It still injects the instructions that say when to
report and in what shape; only the command they name becomes a tool call.

## Transports

Both agents take both MCP transports.

| Agent | stdio | streamable HTTP |
| --- | --- | --- |
| Claude Code | yes | yes |
| Codex CLI 0.154 | `codex mcp add <name> -- <command>` | `codex mcp add <name> --url <URL>` |

HTTP is the one that fits: the daemon is already an HTTP server, so it costs
one more route rather than one more process per session.

## The port problem

The daemon takes an OS-assigned port on every start
(`asyncio.start_server(..., "127.0.0.1", 0)`), because re-registering the Toolbelt URL follows it, which a spike showed on 2026-09-07. An MCP entry in a config file cannot
follow a port that changes on every restart. Three ways out:

1. **A fixed port for MCP alone.** The daemon binds a second listener on a
   known port (say 51737) for MCP, keeping the ephemeral one for the panel. A
   port in use by something else means no reporting until it frees up.
2. **A stdio shim.** A small script reads the live port from the same
   `defaults` entry the panel registers, connects, and speaks MCP over stdio.
   That reintroduces a process per session, though a long-lived one rather
   than one per report.
3. **A port file.** The daemon writes its port to
   `~/.claude/agents-sidebar-status/port`, and the shim or the config reads
   it. Same shim cost as 2, with less coupling to iTerm2's preferences.

Option 1 is the only one that spawns nothing. It trades an ephemeral port's
safety for a fixed one, on loopback, still behind the daemon's token.

## Authentication

The panel's token is 24 random bytes, checked on every request,
including the event stream. An MCP client sends headers, so the same token can
travel as a header, but the daemon makes a new one on every start, which puts it
in the same bind as the port. A token written beside the port file, and read by
whatever launches the client, is the shape that works for both.

## What this does not fix

- **Codex parity.** Codex's config is its own, so `install.sh --codex` grows
  an MCP entry beside the hook entry it already writes.
- **A dead daemon.** Today `task.py` writes the note without the daemon, so a
  stopped daemon does not make a report fail. Through MCP a stopped daemon
  means the tool is absent, and the model has nothing to run.
- **`task.py` itself.** It stays. It stays the fallback when the daemon is down, and Codex sandboxes that cannot reach the port still need it.

## What it is worth

It removes about 8.6 seconds an hour per session and one race nobody has hit yet. It adds a second listener, a fixed port, a token file, two
config entries, and a second path to the same note. That is the trade to judge, and the measurements above are the honest size of the win.
