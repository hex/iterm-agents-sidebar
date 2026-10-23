# Task line as two mod tools: design

Written 2026-10-23. Status: proposed, awaiting sign-off before implementation.

## Problem

A Claude session reports its task line by running `task.py` through Bash:
144 ms a report (107 ms of it interpreter startup), about one a minute per
session, and a long command the model copies with its own session id. The
link mod already registers tools (`partner_read`, `partner_delegate`) and
serves them in its one `tool.call` hook. This moves Claude's reporting onto
two tools that mod registers, writing the same note with the same rules, so
`sidebar.py` and the hook's reader stay as they are.

Constraints the shape honours:

- The note `~/.claude/agents-sidebar-tasks/<id>.json` is a contract with two
  readers: `{task, title, activity, percent, done, ts}`, `ts` in epoch seconds,
  widths 80 and 40, percent 100 means `Complete` and the task is locked.
- `task.py` stays: Codex has no mod engine. SessionEnd removal stays in the
  hook (`clear_note`, under the flock `task.py` takes).
- One hooks module per plugin, one hook per event, `$` never crosses an
  import, so every I/O call lives in `link.tsx` and only pure code splits out.
- The session id changes on `/clear` and on a resume with no new
  `session.start`.
- Registration can be refused (a managed `allowedMcpServers`), and the hook
  that teaches the model runs in another process and cannot see that.
- On an organization account the security default plugin skips
  `prompt.compose` and every `classic.*` event, so the rules reach the model
  only through the hook's `UserPromptSubmit` context, as today.
- Plugin-registered tools are listed as deferred: the model sees the name and
  loads the schema through ToolSearch before it can call the tool. A tool
  description is not reliably in front of the model, so the rules cannot
  live only there.
- The engine has no file lock. `$.fs.write` is not atomic; `mv` is.
- A plugin's own tool raises no permission dialog in an interactive session,
  in any mode (measured 2026-10-22 with a probe mod). In a headless `-p`
  session outside bypass mode the engine's own verdict is `ask`, which no one
  answers; the call fails and the rules already say to carry on.

## Usage (caller's view)

What a Claude session with the tools reads on every prompt, from the hook:

```
# Task line
<task-instructions.md, worded for both tools and commands>

Current task: {"task":"m3x9k2a1","title":"Fix the login bug","activity":"Reading code","percent":35,"done":false,"ts":1792732800}

Tools (deferred: load them once with ToolSearch "select:mcp__agents-sidebar__task_begin,mcp__agents-sidebar__task_report"):
mcp__agents-sidebar__task_begin {"title": "Task title"}
mcp__agents-sidebar__task_report {"activity": "Reading code", "percent": 25}
mcp__agents-sidebar__task_report {"activity": "Assessing task", "percent": null}
```

A Codex session, or a Claude session whose tools are not registered, reads
the same rules and today's three `task.py` commands. That is a working
protocol, not a diagnostic.

Calls and what comes back:

```
task_begin {"title": "Fix the login bug"}
  -> Task line: Fix the login bug
task_report {"activity": "Assessing task", "percent": null}
  -> Task line: Fix the login bug · Assessing task · ?%
task_report {"activity": "Testing changes", "percent": 70}
  -> Task line: Fix the login bug · Testing changes · 70%
task_report {"activity": "All checks pass", "percent": 100}
  -> Task line: Fix the login bug · Complete
task_report {"activity": "One more fix", "percent": 40}
  -> Not recorded: task is done: begin a new one for more work
(from a subagent) task_report {...}
  -> Not recorded: only the main conversation reports the task line
```

A refusal is a result, never `{deny}` and never a thrown error: the model
reads one line and the work goes on.

The PostToolUse nudge, in tool mode:

```
Progress check-in is due if this is a natural boundary. Reassess the current task; do not invent progress. mcp__agents-sidebar__task_report {"activity": "...", "percent": N}
```

## Shape

### The marker: how the hook learns the tools exist

`~/.claude/agents-sidebar-links/<id>/task-tools.json`, written by the mod
beside `ready`:

```json
{"session": "<id>", "begin": "mcp__agents-sidebar__task_begin", "report": "mcp__agents-sidebar__task_report"}
```

or, after a refused registration, `{"session": "<id>", "refused": "<reason>"}`.

The tick rewrites it each second (the same plain `$.fs.write` as `ready`), and
`turn.start` writes it too, so a prompt right after `/clear` already finds it
under the new id. The hook trusts it only when it is a regular file, at most
60 s old, names the payload's session, and both names match
`^mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$`. Anything else means no tools, and
the session gets the commands. That one rule covers Codex, a Claude Code
without the engine, a refused registration, a mod that died, and a torn read
(one prompt gets the commands).

What the marker buys: the registration result is the only source of the tool
names, so no TypeScript literal and Python literal must agree; a dead mod goes
stale on its own; a refusal can be read with `cat`; and the hook's self-nudge
check reads the names it must skip from the same file.

### Pure module: `plugin/hooks/task-line.ts`

```ts
export const TITLE_WIDTH = 80
export const ACTIVITY_WIDTH = 40

/** The note as both readers take it. percent null with done false is unknown or not yet reported. */
export type TaskNote = { task: string; title: string; activity: string | null; percent: number | null; done: boolean; ts: number }

/** One call's outcome: the note to write, or why nothing is written, in task.py's words. */
export type TaskCall = { kind: 'write'; note: TaskNote } | { kind: 'refused'; reason: string }

/** Control characters and bidi overrides removed, cut to width in code points (Python slices code points), trimmed. */
export function clean(text: string, width: number): string

/** The file's JSON as a note, or null (task.py's read_note: an object with a "task" key). */
export function parseNote(value: unknown): TaskNote | null

/** begin: title a string, cleaned, empty refused "title is empty"; the current note is ignored (begin starts over).
 *  report: no note -> "no task yet: run begin first"; done -> "task is done: begin a new one for more work";
 *  activity cleaned, empty refused; percent an integer 0..100 or null (unknown), else "percent must be 0 to 100";
 *  100 -> activity "Complete", done true. Checks in task.py's order, so the same bad input gets the same refusal. */
export function taskCall(kind: 'begin' | 'report', input: Record<string, unknown>, current: TaskNote | null, nowSeconds: number, taskId: string): TaskCall

/** One line for the model: "Task line: <title> · <activity> · <percent|?>%", or "Task line: <title> · Complete". */
export function summary(note: TaskNote): string

/** The two tools as registered. Descriptions carry the call contract only; the rules live in task-instructions.md. */
export const TASK_TOOLS: { begin: ToolSpec; report: ToolSpec }
// task_begin: { title: string (required) }
// task_report: { activity: string (required), percent: integer 0..100 | null (required; null = unknown) }
```

`percent` is required with `null` for unknown, so a forgotten field is refused
rather than shown as unknown, and the schema needs no `anyOf`/`const`. The
five-point rule stays in the prose, not in a `multipleOf` the engine may or
may not enforce.

### The I/O shell, in `link.tsx`

```ts
let taskTools: { begin: string; report: string } | { refused: string } | null = null
let noteChain: Promise<unknown> = Promise.resolve()   // in-process stand-in for the flock: two calls in one message

async function registerTaskTools($): Promise<void>      // both or neither; a refusal lands in taskTools, never throws
function taskToolOf(tool: string): 'begin' | 'report' | null
async function serveTask($, kind, input, signal): Promise<string>
//   agentId -> "Not recorded: only the main conversation reports the task line"
//   id = $.session.id() now (after any /clear); plain token or refused
//   serialized: read the note from disk (never cached: the hook may have removed it), taskCall(...),
//   refused -> "Not recorded: <reason>"; signal.aborted -> nothing written; replaceFile; summary(note)
function serialized<T>(work: () => Promise<T>): Promise<T>
async function replaceFile($, path, text): Promise<{ok: true} | {ok: false; error: string}>
//   $.fs.write to `<dir>/.<base>`, then mv over path; no chmod (task.py sets none; the directory is the guard)
//   writeWhole() delegates to it, so there is one writer of whole files
```

`session.start` registers the task tools first, in their own `try`, then the
partner tools (today a refused partner registration throws out of
`session.start`; it gets the same `try` in this change). The one `tool.call`
hook gains a first branch: `taskToolOf(e.tool)` routes to `serveTask`.

Task ids: clock in base 36 plus a per-process counter. No reader compares ids
across sessions; `sidebar.py` only checks the key is present.

### The hook side, `emit-state.py`

```python
TOOLS_FRESH = 60
def task_tools(session_id, now, root=None) -> TaskTools | None   # the marker, parsed at the boundary
def whisper(event, payload, note, now, reminded, script, tools)    # tools: names or None
#   UserPromptSubmit: instructions + Current task + (tool_calls(tools) | command_calls(bound))
#   PostToolUse skip: "task.py" in tool_input, or tool_name in tools
#   nudge: the report call in the active shape
```

`main()` passes `task_tools(...)` for Claude and `None` for Codex. Everything
else in `whisper` is unchanged.

### Shared rules and shared cases

`task-instructions.md` stays the single statement of the rules for both
agents, reworded transport-neutral: "the begin and report calls named below",
"report unknown" for `--unknown`. The descriptions carry only the call
contract (what each field is, what comes back, that 100 locks).

`plugin/hooks-handlers/task-cases.json` is one list of begin/report cases
(widths, the unprintable class, trimming, an astral character at the cut, the
order of refusals, 100 to Complete, unknown to null, begin over a done task).
`tests/test_task.py` runs them through `task.py`; the kit test runs them
through `taskCall`. A rule changed on one side fails the other's run.

### What the design deliberately does not do

- No prose from the mod through `prompt.submit` context: the hook owns all
  task-line prose for both agents, and a second owner would need the same
  "is the mod serving?" signal.
- No flock from the mod and no mod-side removal at `session.end`:
  `clear_note` stays the one remover, and a tool call cannot follow
  `session.end` in-process. Against the mod the flock would guard only a
  call the engine is aborting, and `serveTask` checks the signal before the
  rename.
- No `tool.check` hook: no dialog to suppress (measured).
- Registration is not gated on the panel endpoint: the endpoint check already
  decides, in one place, whether the model hears of the task line at all.

### Interface depth

The model sees two tools with one and two fields, no session id, script path
or flag group. Behind them: session binding across `/clear`, parsing,
cleaning, the done lock, unit conversion, serialized read-then-write and
atomic replace. The hook grows by one function and one parameter. The marker
is the only new cross-process format: four keys, one writer, one reader.

## Synthesis decision

Four candidate designs were drawn (2026-10-23). Three converged on this
shape: rules in TypeScript, two tools, an in-process chain plus stage-and-mv,
a marker for the hook, shared cases. The fourth kept one implementation by
shelling to `task.py` from the handler; rejected, since it keeps the 107 ms
the change exists to remove and makes the tool a wrapper. The base is the
candidate with the freshness-checked marker (a dead mod falls back on its
own) and the explicit write-safety argument. Grafts: the marker stamped at
`turn.start` so `/clear` never waits a tick; the one-line summary as the
tool's result; the "Not recorded:" prefix on refusals; no chmod on the note
(parity with `task.py`); `percent` as integer-or-null rather than a sentinel
string. Rejected from the losers: `multipleOf: 5` in the schema (the engine's
validation is unverified and a 33 would surprise the model), a never-expiring
marker, and "unavailable, do not report" in place of the commands fallback.

## Tradeoffs accepted

- Two implementations of the begin/report rules, in exchange for no
  interpreter start per report; the shared cases make drift a test failure.
- A marker rewritten each second, in exchange for one source of tool names
  and a fallback that follows the mod's life.
- A torn marker read sends the commands for one prompt, in exchange for
  writing it the way `ready` is written.
- No cross-process lock between the mod and `task.py`, in exchange for no
  primitive the engine lacks: per-session ownership and atomic writes. A model
  that runs `task.py` by hand beside the tool loses only to last-writer-wins
  on a self-estimate.
- The 13-line prose still rides every prompt, in exchange for rules that reach
  the model under tool search and that Codex shares.
- One ToolSearch call per conversation to load the tools, in exchange for no
  Bash call and no session id in the command.

## Alternatives considered

- The handler shells to `task.py` via `$.process.run`: one implementation and
  the flock for free, but every report keeps the startup cost and the tool
  hides none of the rules.
- One `sidebar_task` tool with an `action` field: one registration, but the
  schema can no longer say which fields each verb needs; `title`, `activity`
  and `percent` all go optional and the pairing moves into runtime refusals.
- The mod owns Claude's prose through `prompt.submit` context: a Claude
  session with hooks and no mod would lose the task line unless the hook still
  spoke, and the hook would then need the same signal to stay quiet.
- Rules carried only by the tool descriptions: lost under tool search, where
  descriptions are not in context until loaded, and forks the rules from
  Codex.
- Reports through the daemon as an MCP server: rejected 2026-09-17
  (`docs/task-line-mcp-design.md`), reasons stand.

## Implementation reconciliation

(none yet)

## Open questions and risks

- Can a kit test load `task-cases.json` (a JSON import, or a read through an
  unmocked `$.fs`)? If neither works, the cases live as a `.ts` export the
  Python test parses with a narrow reader. Probe before writing tests.
- Does the engine validate `inputSchema` before the hook runs, and does
  `type: ["integer", "null"]` register? `taskCall` re-validates either way.
- A tmux teammate is its own Claude process and session: it hears the prose
  and reports onto its own card. Out of scope here; worth a decision later.
- `partner.test.tsx` and `link.test.tsx` each carry a `world()` harness; the
  task tests would be the third copy. Rule of Three says extract
  `test-world.ts` in this change.

## Tests

- Kit (`plugin/hooks/task.test.tsx`): begin; report; unknown; 100 locks and
  the next report is refused with the exact text; no task; empty title or
  activity; percent 101, 35.5 and "35"; a subagent call refused with nothing
  written; two concurrent reports both applied in order; a rejected
  `tool.register` leaves a `{refused}` marker and routes nothing; the marker
  follows a `/clear`'s new id; the shared cases.
- Python: `test_task.py` runs the shared cases; `test_emit_state.py` covers a
  fresh marker (tool calls in the prompt and the nudge), a stale, foreign,
  refused or malformed marker (commands), a PostToolUse whose `tool_name` is
  a marker name (no nudge), and Codex ignoring any marker.
- One live check in a real session: begin and report through the tools, the
  note on disk, the card's line and age, a `/clear` followed by a report
  under the new id, and no Bash `task.py` call in the transcript.

## Next implementation step

Write `task-cases.json` and make `tests/test_task.py` run it against the
current `task.py`: the cases are the spec both implementations answer to, and
they must pass on the Python side before any TypeScript exists.
