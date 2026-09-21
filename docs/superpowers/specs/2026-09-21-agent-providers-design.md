# Agent providers design

Status: proposal, 2026-09-21. Nothing here is built. Written from research
workflow `wf_a827cd6a-25e`; the raw survey with its source URLs, and the
verified/inferred mark on every claim, is in
`.cs/research/2026-09-21-agent-cli-survey.md`. The survey of other agents is a
snapshot of that date and will age; re-check an agent's row before building
for it.

## Review outcome (read this first)

Two independent reviews ran on the first draft: Codex, asked to refute it
(`.cs/research/2026-09-21-agent-providers-codex-review.md`, 170 citations
checked, 10 wrong), then a second reviewer that re-ran Codex's probes and ruled
on each finding (`.cs/research/2026-09-21-agent-providers-fable-review.md`).
The research, the non-goals, the tier table and translating event names at the
door all survived. **The "behaviour unchanged, tests green unedited" claim for
the daemon half did not**, and the sections below are corrected where they were
wrong. What changed:

- **`providers.py` cannot be built as a sibling module.** Claude's reader needs
  `sidebar.read_status` and `parse_status`. `sidebar.py` runs as `__main__`
  under `runpy`, and the tests load it with `module_from_spec` without
  registering it in `sys.modules` (`tests/test_rebuild.py:10-13`), so
  `import sidebar` from a sibling executes a second copy that the tests'
  monkeypatches of `sidebar.STATUS_DIR` and `TASKS_DIR` never reach. `codex.py`
  works as a sibling only because it imports nothing from `sidebar`. Provider
  records live in `sidebar.py`, or they do not exist yet.
- **Slice 4 would have broken collection of `tests/test_state.py`.** Line 15 is
  `from sidebar import parse_context, parse_state`, and `parse_model` is
  imported at `:99,107,135`. The parsers have no callers in `sidebar.py`; they
  have about six tests. Deleting them deletes tests, which is the owner's
  decision, not housekeeping. The fetch of `user.claudeStatus` may still be
  dead (nothing in the repo writes it; `sidebar.py:777` says iTerm2 renders it).
- **`nested_agent` keeps its bool signature.** `tests/test_emit_state.py:282-284,290`
  call it with `codex=True/False`.
- **`--codex` stays the only spelling.** `tests/test_codex_hooks.py:33,42,52`
  assert it, `codex-hooks.sh:33` writes it, and Codex keys hook trust by
  position and command, so a respelled command probably re-prompts trust for
  all seven hooks (inferred, not measured). New agents get `--agent <id>`;
  Codex is not migrated. This removes former decision 3 and with it the only
  backward-compatibility question.
- **The loader fallback cannot be a Claude row alone.** `emit-state.py:796-797`
  picks binary and variable together, so a `--codex` hook under a Claude
  fallback would write `claudeState`. With the table inside `emit-state.py`
  (plan B below) there is no loader and no fallback.
- **A pid is required for a truthful state, not only for resources.**
  `sidebar.py:804-806`: `int(payload["pid"])` on `None` raises and the state
  reads `"unknown"`. An agent whose process shows as `node` gets a card that
  says "?" forever until the `match` field exists. That field is a precondition
  for Qwen, Copilot, Gemini and Cursor, not an add-on.
- **Isolation is wider than the readers.** `parse_state` raises `OverflowError`
  on a huge pid (`sidebar.py:815-817` catches `ProcessLookupError, ValueError`),
  `parse_subagents` raises on a NaN or infinite `since` (`round` at `:1323`),
  and `codex.read_session` raises `TypeError` on a non-string path
  (`codex.py:178` catches `OSError`). All run outside any per-provider guard,
  and the rollout read at `sidebar.py:2257` is on the event loop. The unit to
  isolate is one pane's whole decode and enrichment.
- **Two unvalidated paths come from published state.** `read_task` joins the
  session id into a path (`sidebar.py:1559`), and `../x` or an absolute path
  escapes `TASKS_DIR` (reproduced); `with_detail` already validates with
  `_SESSION_FILE` (`:1247`). `transcript_path` goes unchecked to `open()`
  (`codex.py:109`).
- **Translating an event name must not change the reply.** `main()` uses one
  `event` for `state_for` and for `hook_output(event, …)` (`emit-state.py:537`,
  `:849-855`). Identity for Codex; wrong for Gemini. Keep the native name for
  stdout.
- **Shared code that is Claude-only and harmless at N=2:** `short_model`
  (`sidebar.py:1384-1386`) returns `None` for any non-`claude-` model, and
  `tests/test_state.py:276` asserts that; `describe_subagents`
  (`emit-state.py:443`) reads Claude's transcript layout. Both matter for the
  first third agent that has subagents, not before.
- Dropped as having no consumer: the null provider (a `dict.get` default does
  it), `config_path`, and `vendor`/`marker` before the page descriptors exist.
  "Present only when truthy" was wrong wording: `context`, `blocked_since`,
  `working_since` and `started_at` are kept when `is not None`
  (`sidebar.py:658,670,674,678`), and `tests/test_snapshot.py:395` needs
  `started_at=0` to survive. `tests/test_rebuild.py:1-6` covers the process
  listing only, so limits threading needs a new test.
- Not confirmed as stated: the 4096-byte ceiling. Adding `v` and `provider`
  does push a value of exactly 4096 to 4136 and the spilled envelope to 4108,
  but only with a `transcript_path` padded to about 3.7 KB, and the ceiling is
  a cost budget (`emit-state.py:714-717`), not a transport limit. A boundary
  test is reasonable.

### Two plans

**Plan A, the contract as drafted below** (corrected): `agents.py` loaded by
path, provider records, `snapshot.providers`, a versioned protocol doc. Eight
slices. Its daemon half is speculative: `limits` and `side_jobs` have one
implementer each and the draft itself says new providers implement neither,
and the row's shape (`match`, `keys`, `values`) is unknown until a third agent
is measured.

**Plan B, the table without the framework** (recommended):

1. Live bugs first, independent of providers: isolate a pane's decode and
   enrichment, move the rollout read off the loop, validate `session` and
   `transcript_path` at the parse edge, wrap the startup `rebuild()`, gate
   `HOUSEKEEPING` on `row.provider`, carry `background` through `read_state`.
2. Hook side: a dict inside `emit-state.py`, `{id: (binary, variable,
   extra_fields, events)}`, and `--agent <id>` beside the untouched `--codex`.
   One `<name>-hooks.sh` per agent.
3. Daemon side: the same ids and variable names in `sidebar.py`,
   `agent_variable` made N-way, the foreground-name rule read from the dict. A
   test loads both files and asserts the variable names agree, which is what
   stops the two drifting in the repo. Drift between the checkout and the
   installed copy already exists for every `emit-state.py` edit and is handled
   by re-running `install.sh`, so no loader, no fallback row, no mismatch log.
4. Page side: the icon fallback and one `PROVIDER_ICONS` entry per agent.
5. The `match` field, with the first agent whose process is `node`.
6. A provider record, in `sidebar.py`, when a second agent needs its own
   status reader. Cost of waiting: one more `if provider ==` branch to fold
   then, which is cheaper than unwinding a record shaped by a guess.

Under plan B adding a hook-shaped agent is: one row on each side, one hooks
script, one icon. That is the plugin system for tier 1. Plan A's extra
machinery buys nothing until an agent needs a reader, limits, or a card from a
tool this repo has never heard of.

## omp, the first new agent

**Built, 2026-09-21: the title, not the extension.** Both surveys missed that
omp writes its state into the terminal title (`π > label` idle, `π ! label`
waiting on an approval or a question, a spinner frame while working;
`src/utils/title-generator.ts:727-760`, set from `event-controller.ts`). The
daemon already reads that title for Claude's marker, so an omp row needed no
code inside omp: `omp_title_state()` in `sidebar.py`, a `π` mark and a program
name on the page, its own row commands, and no panel notices for an agent that
posts its own. Checked against the live pane: `autoName` was
`π ⠋ <label>`, and the real session read produced an AGENTS row with provider
`omp` and state `working`. `docs/integrations.md` has the format and its
limits.

The extension plan below stays as the route to a model, a context figure and a
pid on the card. Nothing in it is built. The probe in slice 1 was written and
removed unused.

Decided 2026-09-21: plan B, and omp goes first. omp is oh-my-pi
(`@oh-my-pi/pi-coding-agent` 18.2.5), a fork of pi. The survey of its installed
source is in `.cs/research/2026-09-21-omp-survey.md`, and Codex's check of this
plan is in `.cs/research/2026-09-21-omp-codex-check.md`. Every claim below comes from
reading the installed source. Nobody has measured any of it in a live omp
session yet, and slice 1 exists to change that.

### What omp gives us

omp has no shell hooks. Its hooks and extensions are TypeScript or JavaScript
modules that it imports into its own process. It finds `.sh` hooks and filters
them out before loading (`extensions/loader.ts:511-512,612-615`). Plan B's
"one hooks script per agent" does not fit omp. The integration is an extension
file at `~/.omp/agent/extensions/agents-sidebar.ts`, or under
`~/.omp/profiles/<name>/agent/extensions/` when `OMP_PROFILE` is set.

The process is `bun`. `ps -o comm=` prints `bun` and the args are
`bun /Users/x/.bun/bin/omp`, so `agent_pid` cannot find it by name. The
extension knows `process.pid` and sends it.

The extension API has what a card needs:

| Card fact | Source |
|---|---|
| turn started | `agent_start` |
| turn ended | `agent_end` with `willContinue` not true |
| blocked on an approval | `tool_approval_requested`, cleared by `tool_approval_resolved` |
| blocked on a question | `tool_execution_start` with `toolName === "ask"`, cleared by its `tool_execution_end` |
| tool activity | `tool_execution_start` and `tool_execution_end` |
| session gone | `session_shutdown`, which fires on session disposal and not only at exit |
| session id, transcript | `ctx.sessionManager.getSessionId()`, `getSessionFile()` (undefined until the file exists) |
| model | `ctx.model?.id` |
| context | `ctx.getContextUsage()`, `{tokens, contextWindow, percent}` or undefined |

`input` is not a turn start. omp returns early when a handler consumed the
input (`input-controller.ts:914-917`), so no turn runs. `agent_start` alone
starts the turn.

### What the card cannot have

- Waits that are not tool approvals. A dialog raised by another extension, and
  some plan approvals, emit no event. The card reads working while omp waits.
- A subagent list. omp runs subagents in its own process and has no event for
  them. The card shows the main turn only.
- Nested-run detection. omp sets no marker like `CLAUDECODE` for its children.
- A reliable end. A SIGKILL publishes nothing, so pid liveness stays the
  authority, as it is for Claude.

### The shape

The extension translates and hands off. The fold stays in Python.

1. A handler in the extension builds a small Claude-shaped payload and puts it
   on a queue. It returns at once and never awaits Python. omp awaits approval
   handlers before it shows the approval, so a slow handler delays the prompt.
2. One worker per root session takes payloads off the queue in order. For each
   it runs `python3 -B <handler> <Event> --agent omp` with the JSON on stdin,
   and waits for the child to exit before it starts the next.
3. `emit-state.py` folds the event, exactly as it does for Claude, and
   publishes `user.ompState`.

The queue is there for ordering as much as for safety. omp calls subscribers
without waiting for them (`agent-session.ts:2624-2628`), and our terminal write
happens after the fold lock is released (`emit-state.py:441-450`, `:847`). Two
children running at once could publish the older state last.

The worker follows these rules, because an extension bug can end the user's
omp session:

- Every handler body sits in try/catch. An unhandled rejection from a detached
  promise reaches omp's `exitAfterFatal`.
- `Bun.spawn` with `stdin` as bytes, `stdout` and `stderr` ignored, `timeout:
  500` and `killSignal: "SIGKILL"`. Both the spawn and `await child.exited` are
  caught. No shell, no `spawnSync`, no detached child.
- The queue is bounded. When it overflows, the extension stops publishing
  rather than drop a gate transition and leave a stale badge.
- The child gets a minimal environment and fixed absolute paths. The payload
  carries ids, names and numbers. It never carries prompts, tool results,
  credentials or the model object.

Subagents get their own copy of the extension and their own `session_start`
(`extensions/loader.ts:550-552`, `task/executor.ts:4036`). The guard
`ctx.hasUI && ctx.mode === "tui"` therefore runs before the extension records any
identity. Task children have `hasUI: false` (`task/executor.ts:3784`). The
extension refreshes the accepted session id on `session_switch` and
`session_branch`, and
a generation counter drops queued payloads that belong to the previous one.

Cost, measured by Codex on this machine: python3 starts in 32 ms (median of
20) and the handler's imports take 41 ms. A tool call is two events. A hundred
tool calls is about 8 s of child time spread over the turn, off omp's own
path.

### Event mapping

| omp event | Sent as | Payload beyond the common fields |
|---|---|---|
| `session_start`, `session_switch`, `session_branch` (root, TUI) | `SessionStart` | |
| `agent_start` | `UserPromptSubmit` | |
| `tool_execution_start` | `PreToolUse` | `tool_use_id`, `tool_name` |
| `tool_execution_start`, `toolName === "ask"` | `Notification` | `notification_type: "permission_prompt"`, `tool_use_id`. `state_for` ignores it without both (`emit-state.py:561-567`) |
| `tool_approval_requested` | `PermissionRequest` | `tool_use_id`, `tool_name` |
| `tool_approval_resolved`, approved | `PostToolUse` | `tool_use_id` |
| `tool_approval_resolved`, refused | `PermissionDenied` | `tool_use_id` |
| `tool_execution_end` | `PostToolUse`, or `PostToolUseFailure` when `isError` | `tool_use_id` |
| `agent_end`, `willContinue` not true | `Stop` | |
| `session_shutdown` of the accepted session | `SessionEnd` | |

Common fields on every payload: `session_id`, `pid`, `model`, `context`
(percent, or absent), `transcript_path` (or absent), `cwd`.

A working card goes unknown after 300 s without a report (`sidebar.py:44`).
Claude refreshes it on every tool call. One long omp tool call would not, so
the worker resends the last working payload every 120 s while a turn is open.

### What changes in the repo

`emit-state.py`:

- `--agent <id>` beside `--codex`, which stays as it is. An id that is not in
  the table publishes nothing.
- A table inside the file, one row per agent: variable name, how the pid is
  found (by process name, or from the payload), and which payload fields are
  published. Claude and Codex keep today's behaviour.
- For omp the pid comes from the payload, and must be a positive integer.
  It publishes `model`, `context` and `transcript_path`.
- omp skips `describe_subagents` and the task-line `whisper` output.
  The first reads Claude's transcript layout. The second writes Claude hook
  JSON to stdout, and nothing reads it.

`sidebar.py`:

- The same ids and variable names, and a test that loads both files and fails
  when they disagree.
- `agent_variable` takes any number of variables. The newest report wins.
- An omp status reader: model and context percent from the published value.
  No file is read.
- The foreground rule matches `omp` in the args, for a pane that has not
  reported yet.

`page.html`: an omp entry in `PROVIDER_ICONS`, a fallback mark for an id that
has none, `"Codex"` and `"OpenAI"` literals read from a small label map, and
`agents: [...]` on the row commands once omp's own commands are known.

`install.sh --agent omp`: writes only `agents-sidebar.ts`, by rename. It
refuses to overwrite a file of that name that it did not write (a marker
comment on line 1 says which). It honours `OMP_PROFILE` and `PI_PROFILE`. It
checks that `omp` and `python3` exist, and it fills in the absolute handler
path. `docs/integrations.md` gets the section, with the undo (`rm` the file).

### Slices

Each slice is one failing test, then the code.

1. **Probe.** A throwaway extension that logs event names, `ctx.hasUI`,
   `ctx.mode` and the session id to a file, run once in a real omp session
   with a tool call, an approval, an `ask` and a subagent. This is not a test
   and is not committed. It replaces "read from source" with "measured" for
   the mapping table, and slice 2 waits until the table matches what it saw.
2. **The handler accepts `--agent omp`.** `published` for omp carries the
   payload's pid, model, context and transcript path. Test in
   `tests/test_emit_state.py`, beside the Codex cases.
3. **An id that is not in the table publishes nothing**, and `--codex` still
   does what it did. `tests/test_codex_hooks.py` stays unedited.
4. **The `ask` wait reads blocked and clears.** A fold test in
   `tests/test_session_state.py` over the mapped sequence: `PreToolUse`,
   `Notification` with both keys, `PostToolUse`.
5. **The daemon reads `user.ompState`.** N-way `agent_variable`, with the
   two-variable cases in `tests/test_state.py:297-319` re-spelled and their
   outcomes unchanged. The agreement test between the two tables.
6. **An omp row has a model and a context figure.** `tests/test_snapshot.py`.
7. **The page draws an omp row**, and an unknown id draws the fallback mark.
   Source tests only, as for the rest of the page. Checked by eye in the panel.
8. **The extension.** Its pure parts (event to payload, the guard, the queue's
   ordering and overflow) are exported functions with `bun test` cases under
   `plugin/omp/`. This adds bun as a test dependency, for this directory only.
9. **The installer**, tested the way `tests/test_codex_hooks.py` tests
   `codex-hooks.sh`: a temp home, run it, read what it wrote, run it again.
10. **Live check.** Install it, run omp, and watch a turn, an approval, an
    `ask` and an exit on the card. README and `docs/usage.md` updated.

### Open questions

1. **Who writes the escape.** A child writing the tty can land inside a TUI
   frame that omp split across writes (`pi-tui/src/terminal.ts:277-283`
   documents the hazard). The alternative is that Python prints the finished
   sequence and the extension writes it through `writeThroughActiveTerminal`.
   That needs a second output mode in `emit()`. Claude Code has lived with the
   child write without a reported problem. Recommendation: start with the
   child write, look for torn output during slice 10, and switch only if it
   shows.
2. **The icon.** omp needs a mark in the row's small rounded square.
3. **bun tests.** Slice 8 adds `bun test` next to pytest. The alternative is an
   extension with no tests of its own, covered only by slice 10.
4. **Background work.** `ctx.getAsyncJobSnapshot()` could hold the card at
   working while an async job runs after `agent_end`. Left out until the probe
   shows whether that happens in practice.

## The first draft, corrected in place

Everything from here down is plan A. Where the reviews proved a claim wrong it has been fixed; the slice list still describes plan A's order.

## Goal and non-goals

**Goal.** Make the per-agent facts a table instead of `if codex:`, so a new agent CLI is one table row plus (only if it has enrichable state) one sibling reader module. Two agents exist today and the branch count is already 27 (`sidebar.py` 14, `emit-state.py` 6, `page.html` 7); a third agent multiplies the places to edit, not the code.

**Non-goals.**
- No screen scraping, no OSC-title rules, no pane-capture ruleset. herdr's and AoE's open issues are the argument: #3029 (idle Claude read as codex from overlapping title rules), #3871/#4429 (permission menus read as idle), #3530 (still generating, read as done), AoE #2606 (fixtures 16 minor versions stale). That is a different product with a maintenance treadmill; the panel's state comes from the agent reporting it.
- No plugin loading from outside the checkout. The daemon holds the iTerm2 connection and can `async_send_text` into any pane (`sidebar.py:2386-2389`) and `async_close(force=True)` (`:2394`); `docs/development.md:15-17` says no endpoint runs arbitrary code.
- No generic limits/budget rewrite. `page.html:2105-2330` (account chrome, auto-switch, add/rename/switch) is working code for N=1.
- Not the Codex *job* store. `CODEX_JOBS_DIR` (`sidebar.py:1417`), `merge_codex_rows` (`:1485`), `sub.provider === "codex"` (`page.html:2793`) are a subagent kind — a Codex job a Claude session spawned through the codex Claude Code plugin — not a second agent in a pane. It stays where it is, reached through one provider method.
- No "supported agents" list rendered anywhere. Icons and labels drive rows that exist; a static roster is a maintained document, and the panel does not show those.

## What varies per agent

Tiers are by *what can be registered*, because that decides whether the existing handler works at all.

### Tier 1 — Claude-shaped shell hooks (stdin JSON, exit 2 blocks)

The existing `emit-state.py` runs for these, modulo an event-name map. This is the whole reason Codex works: "its hook events and payloads have the shape Claude Code's do, measured by a probe hook on 2026-09-15" (`emit-state.py:770-771`).

| | Register at | Event names | Blocked signal | session id | model | context % | subagents | `ps -o comm=` |
|---|---|---|---|---|---|---|---|---|
| **Claude Code** | `plugin/hooks/hooks.json` (13 events) | native | `PermissionRequest`, `Notification.permission_prompt` | `session_id` | statusline bridge | statusline bridge | `SubagentStart/Stop` | `claude` |
| **Codex** | `~/.codex/hooks.json`, jq merge | identical (7 used) | `PermissionRequest` | `session_id` | payload `model` | rollout `token_count` | none | `codex` (vendor binary) |
| **Qwen Code** | `~/.qwen/settings.json` → `hooks` | identical (22) | `PermissionRequest` + `Notification.permission_prompt`/`idle_prompt` | `session_id` | statusline `model.display_name` | statusline `context_window.used_percentage` | `SubagentStart/Stop` | `node` — argv only |
| **Copilot CLI** | `~/.copilot/hooks/`, or reads `.claude/settings.json` outright | PascalCase form gives snake_case fields | `permissionRequest` + `notification` | `sessionId`/`session_id` | statusline (community-documented, unstable) | same | `subagentStart/Stop` | `node` — argv only |
| **Factory Droid** | `~/.factory/hooks.json` | identical (9), accepts `${CLAUDE_PLUGIN_ROOT}` | `Notification` (type enum undocumented) | `session_id` | `~/.factory/settings.json` only | none (`estimated_tokens` on PreCompact) | `SubagentStop` | `droid`/`node` |
| **Gemini CLI** | `~/.gemini/settings.json` → `hooks`, or extension `hooks/hooks.json` | **renamed** — `BeforeTool`, `AfterTool`, `BeforeAgent`, `AfterAgent`, `PreCompress` | `Notification` with `notification_type: "ToolPermission"` | `session_id` | `AfterModel.llm_request.model` | OTEL only | none | `node` — argv only |
| **Goose** | `~/.agents/plugins/<n>/hooks/hooks.json` | 6 overlap, no Notification/Permission | **none** — infer from unresolved `PreToolUse` | `session_id` | none | none | none | `goose`/`goosed` |
| **Cursor CLI** | `~/.cursor/hooks.json` | camelCase, **`conversation_id` not `session_id`** | **none observe-only** — `permission:"ask"` only if you decide | `conversation_id` | **every payload** | none | `subagentStart/Stop` | `node` (argv `cursor-agent`) |
| **Crush** | `crush.json` | **`PreToolUse` only** | none | `session_id` | none | none | none | `crush` |
| **Kiro CLI** | `.kiro/hooks/<id>.json` | own v1 schema, `action.type: "agent"` | none | unverified — stdin fields undocumented | none | none | none | `kiro-cli`/`q` |

**Two things in this table the v1 contract does not fit, and the contract says so rather than pretending.**

*Pid.* `pid_named` (`emit-state.py:611-626`) matches the executable path from `ps -t <tty> -o pid=,comm=` (`:629-648`), and `comm` is the kernel's. **The `ps` column above is inferred for every row but Codex (a test fixture, `tests/test_emit_state.py:86-91`) and Cursor (its wrapper was read: it `exec -a`s the name over a bundled node, so `cursor-agent` exists only in argv).** The rest were not installed on the research machine; Qwen, Copilot and Gemini reading `node` is likely and unmeasured. Without a pid there is no resource tree, no shells list and no `started_at`. The fix is a row field naming the matcher, `"match": "comm" | "args-token" | "args-argv0"`, added with the first agent that needs it. It cannot be today's bare substring test pointed at `-o args=`: against a full command line a short name matches almost anything (agent-deck token-matches `pi` to avoid epic/tapioca; tmux-handlr excludes `pi` and `amp` by default).

*Payload vocabulary.* v1 of the contract serves agents whose payloads use `session_id`, `transcript_path` and Claude's notification values. Gemini fails on the value (`state_for:562-565` compares to the literal `permission_prompt`, so a Gemini pane would never read blocked) and Cursor on the key (`session_id` is the state-file name, `_state_path:387`). Both are one more row field of the same shape as `events` — `"keys": {"conversation_id": "session_id"}`, `"values": {"notification_type": {"ToolPermission": "permission_prompt"}}`, applied at the same door — and both are added with the first agent that needs one. Until then the table advertises ten agents the contract half-fits, which is the honest state of it.

*Idle.* `state_for` (`emit-state.py:554-595`) reaches `idle` only from `Stop`, `SessionStart` and `Notification.idle_prompt`. Crush has `PreToolUse` alone and Goose has no Notification or Permission event, so both would publish `working` and never retract it; the daemon degrades a stale `working` to unknown after 300 s (`sidebar.py:43`, `:821-829`). Their cards would alternate working and "?" and never read idle. Tier 1 means the handler registers, not that the card is right.

### Tier 2 — other hooks, plugin API or RPC (the shell handler cannot be registered)

| | Surface | State | Blocked | model / context |
|---|---|---|---|---|
| **opencode** | in-process JS plugin, **or** HTTP + SSE server | `session.status` = `idle`\|`busy`\|`retry` — the only literal enum anywhere | `permission.asked`, `GET /api/permission/request` | `session.model`; `tokens_*`+`cost` in `opencode.db` |
| **pi** | `.ts` extensions, **or** `--mode rpc` JSONL over stdio | `agent_start`/`agent_end`/`agent_settled` | `extension_ui_request` blocks for a reply | `ctx.getContextUsage()`, full Model object over RPC |
| **Amp** | declarative hook actions (no command type), Bun plugins, `--stream-json` | `agent.start`/`agent.end` | nothing live — `permission_denials` after the fact | tokens yes, **model never** |

These need a *bridge process* the sidebar owns, not a hook adapter. The pane problem is the blocker, not the protocol: `docs/codex-rows-design.md:40-42` records why polling alone cannot give a row identity — a row needs a pane, and only something running in the pane knows which. opencode makes it worse: the TUI's server port is random and recorded nowhere.

### Tier 3 — files only

**aider.** `--notifications-command` fires on the working→idle edge with no payload; `.aider.chat.history.md` is written into the cwd, not a central store; **no session id at all**, so identity is pid + cwd. A wrapper script can publish the variable itself — which is exactly the third-party path the protocol below documents.

### Tier 4 — nothing but a process name

The ceiling is already in the tree: `codex_tui` at `sidebar.py:2247-2250` gives a pane a card, a provider and a label with no state, from the foreground job name alone. Generalised to a per-provider `foreground_names`, that is tier 4's whole support: **a card, a label, no state, no model, no context.** Say it out loud in `docs/` rather than let it look like a bug.

## The provider contract

### One table, two path-based loads

The static per-agent fields live in **one** file in the repo, `plugin/hooks-handlers/agents.py`, and both sides load it by explicit path. One file in the repo is still two at runtime: the daemon runs from the checkout (`install.sh:25-27`) and the hook runs from the copy `install.sh:56` tars into `~/.claude/skills/agents-sidebar`. A `git pull` plus a daemon restart updates the first and not the second, and the failure is silent: a variable fetched that nobody writes, or written that nobody fetches. So **adding an agent means re-running `install.sh`**, `docs/` says so, and the daemon compares the agent ids in its own table with the installed copy's at startup and logs a mismatch. No version subsystem; one log line. What one file does buy is that the two never drift *in the repo*, which is agent-deck's #1258 ("the built-in list lived in two hand-synced functions that drifted").

Why by path and not `import agents`: `install.sh:56` tars all of `plugin/` to `~/.claude/skills/agents-sidebar`, so the file ships beside the handler — but `tests/test_emit_state.py:10-14` loads the handler with `importlib.util.spec_from_file_location`, which does **not** put its directory on `sys.path`, so a bare sibling import fails under the existing test. `sidebar.py` has the same problem from the other end: `runpy.run_path` from the AutoLaunch stub, worked around at `sidebar.py:22-24` for the checkout root only, and `plugin/hooks-handlers/` is not on that path.

So each side gets a four-line stdlib loader against `Path(__file__)`. In `emit-state.py` that load is a new import-time side effect in a file whose rule is never to raise (`emit-state.py:391-397`: "a hook that raises writes no state at all"). A missing or half-copied `agents.py` would silence every event for every agent. A Claude-only fallback is not safe (a `--codex` hook would then write `claudeState`, `emit-state.py:796-797`), so the fallback carries both existing rows or publishes nothing. Plan B avoids the loader altogether.

```python
# plugin/hooks-handlers/agents.py — data only, stdlib only, no imports
AGENTS = {
    "claude": {
        "provider": "claude",          # the id row["provider"] carries; page keys icons on it
        "label": "Claude",             # the product name the page prints
        "vendor": "Anthropic",         # the icon's aria-label
        "variable": "claudeState",     # emit-state.py:797, sidebar.py:2085
        "binary": "claude",            # emit-state.py:796 -> agent_pid(tty, name)
        "extra_fields": (),            # emit-state.py:709-711
        "marker": "CLAUDECODE",        # env var this agent's own hooks always carry
        "events": dict.fromkeys((      # the 13 in plugin/hooks/hooks.json, verbatim
            "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
            "PostToolUseFailure", "PermissionRequest", "PermissionDenied",
            "Notification", "SubagentStart", "SubagentStop", "PreCompact",
            "Stop", "SessionEnd")),
        "foreground_names": (),
    },
    "codex": {
        "provider": "openai",          # NB: pane says openai, job rows say codex (decision 2)
        "label": "Codex", "vendor": "OpenAI",
        "variable": "codexState",
        "binary": "codex",
        "extra_fields": ("model", "transcript_path"),
        "marker": None,                # Codex sets no marker we have measured
        "events": dict.fromkeys((      # codex-hooks.sh:28-29, verbatim
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "PermissionRequest", "PostToolUse", "Stop", "SessionEnd")),
        "foreground_names": ("codex",),
    },
}
```

`events` does two jobs, which is why it is one field: its **keys** are what a registration script writes (replacing the jq literal at `codex-hooks.sh:28-29`; for Claude nothing writes `plugin/hooks/hooks.json`, it is a hand-maintained plugin manifest, so there the keys are only asserted against it by a test), and its **values** are the Claude event name the fold already understands — `None` meaning "same name". Gemini would ship `{"BeforeTool": "PreToolUse", "AfterTool": "PostToolUse", "AfterAgent": "Stop", ...}` and `state_for` (`emit-state.py:554-596`), `is_fresh_start` (`:599-608`), `GATE_CLOSING` (`:74`) and `apply_event` are **not touched**. Translating at the door is the adaptation; inventing a semantic event vocabulary (`turn_start`, `gate_open`, …) is a rewrite of the one part of this codebase that was derived from 2745 logged real events.

### Hook side

Everything in `emit-state.py` except these lines is already agent-neutral and stays shared — `apply_event`, `aggregate`, `blocked_since`, `working_since`, `subagents`, `carried`, `emit`, `update` and its locking.

```python
agent_id(argv)         -> "claude" | "codex"     # replaces emit-state.py:772
                                                  # slice 1 keeps the --codex spelling
translate(event, row)  -> str                     # row["events"].get(event) or event
published(doc, pid, payload, row, now) -> dict    # emit-state.py:696-711
    # the common nine fields unchanged, plus "v": 1 and "provider": row["provider"];
    # then for key in row["extra_fields"]: value[key] = payload.get(key)
nested_agent(environ, codex) -> bool              # emit-state.py:756-765, untouched:
    # signature and behaviour. tests/test_emit_state.py:282-290 call it with codex=.
```

`agent_pid(tty, name)` and `pid_named(ps_output, name)` keep their signatures — `main()` passes `row["binary"]` into them. `tests/test_emit_state.py:82,97` call them with the bare name, and the `"claude-status" not in comm` exclusion inside `pid_named` (`:611-626`) is Claude-only but harmless at N=2; moving it into the row changes a tested signature for no consumer.

`main()` reads `row["variable"]` at `:797` and passes `row` at `:846`.

Registration cannot be data alone — Claude wants `${CLAUDE_PLUGIN_ROOT}` in `hooks.json`, Codex wants a jq merge that preserves herdr's entries (`codex-hooks.sh:26-27`). `codex-hooks.sh` keeps its name and gains the event list as arguments; a second agent gets its own `<name>-hooks.sh` of the same shape, with `install.sh` dispatching on `--agent <id>` rather than growing the branch at `install.sh:109-127` per agent.

### Daemon side

New `providers.py`, a sibling module beside `codex.py` — the mechanism already in use at `sidebar.py:25-26`.

```python
class Provider:                     # a record, not an ABC
    id: str                         # == AGENTS[x]["provider"]
    label: str; vendor: str
    variable: str                   # "user.claudeState"
    foreground_names: frozenset     # a TUI that has not reported yet
    subcommand_jobs: bool           # sidebar.py:1113-1117, today `if name == "codex"`

    def read_status(self, raw, pid) -> dict
    def limits(self, now) -> dict | None      # blocking; the caller threads it
    def side_jobs(self, cache, session, turn_started, resources) -> list[dict]
```

A pane that published nothing has no provider (`provider is None` for every plain shell, and today's `else` at `sidebar.py:2258` runs for all of them). Dispatch is a `dict.get` with today's `read_status(pid)` as the default; `read_status(None)` already returns the blank status (`sidebar.py:1795-1796`), so no null-provider object is needed.

`read_status` returns **exactly** today's `parse_status` contract (`sidebar.py:1653-1654`), so nothing downstream moves:

```
{"context": int|None, "model": str|None, "effort": str|None,
 "details": dict, "transcript": str|None, "session": str|None}
```

Claude's is `read_status(pid)` → `parse_status` (`sidebar.py:1788`, `:1641`). Codex's is `dict(parse_status(None), model=parse_codex(raw)["model"], **codex.read_session(...))` — verbatim from `sidebar.py:2252-2258`. A tier-4 provider returns `parse_status(None)` and the row renders nothing, per the absent-not-zero rule.

`limits(now)` returns `codex.read_limits`'s `{"windows": [...]}` (`codex.py:115`), `None` by default. It reads disk, so `_rebuild_once` keeps it off the loop exactly as `sidebar.py:2351-2352` does now: one `await asyncio.to_thread(p.limits, now)` per provider, called once. `tests/test_rebuild.py` covers only the process listing (`:52` stubs limits away), so threading and call count need a new test, and the provider must call `codex.read_limits` through the module or the existing stubs stop applying and the tests read the real `~/.codex/sessions`. Claude's limits are **not** behind this method: they come from `self.meters`, an `accounts.AccountMeters` built in `main()` and held on the Bridge (`sidebar.py:2349-2350`, `:2609-2611`), which a module-level record cannot reach. They stay on the Bridge. `side_jobs` returns today's `codex_job_rows` shape (`sidebar.py:1461-1482`), `[]` by default. Both default to nothing, so a new provider implements neither.

Module-level and shared, because every provider's hook publishes the same envelope: `parse_state`, `parse_session`, `parse_pid`, `parse_agents`, `parse_subagents`, `_subagent_tree`, `parse_blocked_since`, `parse_question`, `parse_working_since`, `parse_turn_started`, `with_detail`, `_reported_at`, `merge_codex_rows`.

Replaced call sites: `SESSION_VARIABLES` (`sidebar.py:2083-2085`) becomes `BASE + tuple(p.variable for p in PROVIDERS)`; `agent_variable(claude_raw, codex_raw)` (`:1263-1279`) becomes `pick_agent(values) -> (raw, provider_id)`, newest `_reported_at` wins with ties to later registry order; the TUI fallback (`:2247-2250`); the status fork (`:2252-2259`); `side_jobs` at `:2281-2283`; `limits` at `:2352`; `foreground_command`'s codex rule (`:1116`); `classify`'s `AGENT_TITLE_MARKER` (`:36`, `:430`, `:483`, `:494`).

`SESSION_VARIABLES` also carries `user.claudeStatus`, which `read_sessions` never reads. Its parsers `parse_model` (`sidebar.py:1521`) and `parse_context` (`:1807`) have no callers in `sidebar.py` but are imported and tested by `tests/test_state.py:15,99,107,135`. The fetch looks like a dead round trip per pane per poll; dropping it, and the parsers with their tests, is a separate decision for the owner and is **not** part of slice 4.

That N-way pick reproduces today's behaviour on every case `tests/test_state.py:297-319` covers. One untested edge differs: both variables set and both torn returns Claude today (`codex_ts is not None` fails first, `:1276`) and Codex under tie-to-later-registry-order. Match it or accept it, but it is a real difference.

### Snapshot fields the page reads

Per row, from `snapshot()` (`sidebar.py:531-754`). Always present: `depth`, `session_id`, `window_id`, `tab_id`, `label`, `position`. Present only when set (`is not None` for `context`, `blocked_since`, `working_since`, `started_at`, so a zero survives; truthy for the rest): `provider` (today omitted for Claude, `:654-655`), `state`, `context`, `model`, `effort`, `agents`, `subagents`, `blocked_since`, `question`, `working_since`, `shells`, `started_at`, `details`, `heavy`, `usage`, plus derived `busy_kids` (`:757`) and `worktree_of` (`:734`).

A provider must produce `provider`. Everything else is optional and absent renders nothing — `tests/test_snapshot.py:643` is exactly that case, a Codex terminal with a provider and no state. Top level: `groups`, `version`, `accounts`, `codex` (`:2344-2359`).

## Discovery and loading

**Recommended: one explicit table in the checkout, loaded by path from both sides; behaviour in sibling modules imported explicitly.**

It is how `codex.py` already loads (`sidebar.py:26`). No install change — `install.sh:56` already tars the whole of `plugin/`. `release.sh:36` and `:86-90` run pytest twice, once on main and once on the released tree, so an import-time error in any provider fails the release. And it is the list a reader wants: one grep shows every agent the panel knows.

Rejected:

- **`importlib.metadata` entry points.** Dead on arrival. The runtime is iterm2env 3.10.19 (`install.sh:34`), `install.sh` installs nothing with pip — it only checks the env exists — so no dist-info is ever on that `sys.path`. It would also break `release.sh`'s worktree pytest, which runs against a bare tree.
- **Directory scan of `~/.config/agents-sidebar/providers/*.py`.** Two independent disqualifiers. Security: executing arbitrary user-directory Python inside the process that holds the iTerm2 connection inverts `docs/development.md:15-17`. And it does not work end to end anyway — a third-party file there extends only the daemon's *reader*, while the publisher is the copied `emit-state.py` pointed at by the agent's own hooks config; a user-dir provider gets a reader for a variable nobody writes.
- **In-repo `providers/*.py` directory scan** (no user dir). Same code, implicit ordering, no grep-able list, and discovery becomes a thing to test for zero gain over a dict.
- **Declarative JSON/TOML manifests.** `tomllib` does not exist on 3.10, so JSON. It handles the static fields — which the table above already does in one file — and nothing of the behaviour, where the actual work is: `codex.py` is 179 lines of rollout-tail parsing whose `BASELINE_TOKENS = 12000` was *fitted* to `/status` output (`codex.py:135-137`). A schema plus a loader to externalise ten string constants is indirection for N=2. Revisit only for the page-side presentation fields, and only when a fourth provider makes `page.html`'s ternaries tiresome.

## The state protocol

The variable format becomes documented and versioned, because it is the only path by which a tool the panel has never heard of gets a card. Today it is undocumented, which is the sole reason this is a repo change rather than a wrapper script.

`published()` (`emit-state.py:696-711`) gains `v` and `provider`; `docs/state-protocol.md` pins the rest:

```
v              1                                   protocol version
state          "working" | "idle" | "blocked"       required
provider       "claude" | "openai" | <yours>        required; keys the icon and label
ts             epoch seconds                        required; arbitrates a stale sibling
pid            int | None                           resource tree, shells, statusline files
session        str | None                           names the state file and the task note
agents         int                                  live subagent count
subagents      [{id, parent, type, since, ended, name, model}]
blocked_since  epoch s | None
working_since  epoch s | None
turn_started   epoch s | None
question       {header, question, options[], multi, more} | {tool, summary} | None
detail         true | false                         set only when over the ceiling
model          str | None                           optional, per extra_fields
transcript_path str | None                          optional, per extra_fields
```

Written as OSC 1337 `SetUserVar=<variable>=<base64>` (`emit-state.py:677-693`). Over `VARIABLE_CEILING = 4096` base64 bytes, `subagents` and `question` (`DETAIL_FIELDS`, `:721`) move to `~/.claude/agents-sidebar-subagents/<session>.published` and the variable says `detail: true` (`:728-753`). The empty string clears (`:843-844`).

Reading this is already forgiving — `parse_state`, `parse_codex`, `parse_subagents`, `with_detail` all tolerate absent or torn JSON, and `tests/test_state.py`, `test_state_detail.py`, `test_session_state.py`, `test_snapshot.py` are the best-covered part of the tree. An unknown `v` is read on a best-effort basis rather than dropped. **Trust.** Any process that can write a pane's variable can name any `pid` and `session`, and the daemon uses both verbatim: statusline files (`read_status`, `sidebar.py:1788-1804`), the process tree, the shells list, `started_at` and the task note (`read_task`, `:1548-1569`). A pane can therefore claim another session's pid and wear its model, context, cost and limits. That is true today; documenting the protocol does not widen it, but the protocol doc must say it.

The in-payload `provider` is written from slice 2 but nothing reads it until decision 1: until then the variable *name* still says which agent published.

**The honest limit.** iTerm2 has no variable-enumeration API — `iterm2/session.py:665` `async_get_variable(name)` fetches one name, there is no list call, and `sidebar.py:2231-2235` issues one round trip per name per pane. So a third party publishing `user.myAgentState` still needs its **name** registered in `PROVIDERS`, and the protocol alone does not make it zero-change. The one escape is decision 1.

And the protocol is deliberately unenriched: a provider gets exactly what it published. No context percentage, no limits strip, no details panel, no shells list, no teammate nesting — those need in-repo readers, and they stay Claude-shaped whatever the table looks like.

## Page changes

Only what a third provider forces. Each is small and each has a test that fails first.

1. **`providerIcon` fallback.** `page.html:2364` does `svg.innerHTML = PROVIDER_ICONS[kind]`, unguarded — an unknown id writes the literal string `undefined` into the SVG. A generic mark for anything not in the map. This is a present bug, not a new requirement. (`tests/test_page_icons.py`.)
2. **`snapshot.providers = {<id>: {label, vendor, icon, colour, commands, effort_labels}}`**, and the seven `providerIcon(kind, label)` call sites stop carrying the vendor label as an argument. This is what stops every new agent being a page edit.
3. **`HOUSEKEEPING` becomes per-provider data.** `page.html:1335-1339` types `/compact`, `/rotate`, `/clear` into any AGENTS row (gated only on `group.name === "AGENTS"`, `:1626`), so a Codex row already gets Claude's commands typed at it, and two of the three do not exist there. A `commands` list in the descriptor, empty meaning Close only. The clearest existing bug the descriptor fixes.
4. **`EFFORT_LETTERS`** (`:1265`, appended at `:2640-2649`) is Claude's `low/medium/high/xhigh/max`; it comes from the descriptor, `null` meaning the provider has no effort concept.
5. **The Codex-shaped no-model chip** (`:2666-2675`), the row `aria-label` literal (`:2741`) and `dataset.spoken` (`:2673`) read the descriptor's label.
6. **Subagent model chip** (`:2822-2826`) is unconditionally `providerIcon("claude", "Claude")` even under a Codex parent; it takes the parent row's provider.
7. **CSS**: `.provider.claude` raw hex at `:461` and `#budget .provider.*` at `:1092-1098` become one rule plus a `colour` token from the descriptor, `null` meaning `currentColor`. `#budget .codex` (`:1097`) — a provider-named class as the only separator between limit blocks — becomes `.provider-block + .provider-block`. Note `tests/test_page_contrast.py` only parses the first two `:root` blocks and only checks pairs in `PAIRS`, so a brand colour added as a token is unchecked unless added there; an SVG fill needs no ratio, provider *text* on the strip ground does.

Deferred: the budget strip stays two painters (`accountMeters` `:2080-2094` and `paintCodex` `:2368-2381`) until a third provider actually reports limits. They already converge on `meterRow` (`:2049-2078`), so the merge is available when it is worth doing; folding Claude's account chrome (`:2105-2330`) into a template now is a rewrite of working code. `paintCost` (`:2427-2437`) says "Claude Code sessions" while summing whatever carries `details.cost` — either scope it or relabel it, one line, independent of this work.

## Migration plan

Codex moves behind the contract first, behaviour unchanged: slices 1-3 hook side, 4-6 daemon side, 7 isolation, 8 the first new agent. Nothing before slice 8 adds agent behaviour. Where a slice changes a tested call's spelling it is named, and every existing assertion stands as written.

**Slice 1 — the table, and `main()` reads two fields from it.**
Add `plugin/hooks-handlers/agents.py` and the path loader. `main()` takes `variable` (`emit-state.py:797`) and the pid binary (`:796`) from the row. `--codex` stays the only spelling — `tests/test_codex_hooks.py:28-33,45,52` assert that literal and every installed `~/.codex/hooks.json` carries it.
*Drives it (new):* `tests/test_agents_table.py::test_each_agent_row_names_its_variable_and_binary`, and `::test_the_claude_row_names_the_events_hooks_json_registers` reading `plugin/hooks/hooks.json`.
*Green unedited:* the whole of `tests/test_emit_state.py` — `main()` has no test, and `agent_pid`/`pid_named` keep their signatures.

**Slice 2 — `published` reads the row: `extra_fields`, `v`, `provider`.**
`published(doc, pid, payload, row, now)` replaces the `codex` bool (`:696`, `:709-711`).
*Drives it (new):* `test_emit_state.py::test_an_agent_whose_row_names_no_extra_fields_publishes_none` and `::test_every_published_value_names_its_protocol_version_and_provider`.
*Green, assertions untouched:* `test_emit_state.py:119-133,198,210,215` — the call sites get `codex=True/False` → the row; every assertion stands as written.

**Slice 3 — event names translate at the door; registration reads the table.**
`translate()` before `state_for`; `codex-hooks.sh` takes the event list as arguments instead of the jq literal at `:29-33`; `install.sh:109-127` dispatches `--agent <id>`, which needs real argument parsing: today it is an exact positional test, `"${1:-}" = "--codex"` (`:109`) beside `"${1:-}" = "--statusline"` (`:73`).
*Drives it (new):* `test_codex_hooks.py::test_the_script_registers_exactly_the_events_it_is_given`, plus a translation case for a renamed event in `test_emit_state.py`.
*Green, assertions untouched:* `test_codex_hooks.py:27-60` — the `register()` helper at `:17-18` passes the seven events; the same commands, the same `--codex`, every assertion as written.

**Slice 4 — `providers.py`, and the pick goes N-way.**
`agent_variable(claude_raw, codex_raw)` (`sidebar.py:1263-1279`) → `pick_agent(values)`; `SESSION_VARIABLES` (`:2083-2085`) built from the registry.
*Drives it (new):* `test_state.py::test_the_newest_report_speaks_for_the_pane` over three registered variables.
*Edited, outcomes unchanged:* `test_state.py:290,297-319`. Every line there is `agent_variable(a, b) == (raw, "openai")`, so the import and each call change shape; the expected results stay, unless decision 2 renames the id.

**Slice 5 — the status fork moves behind `read_status`.**
`sidebar.py:2252-2259` becomes `provider.read_status(raw, pid)`. Nothing inside `parse_status`, `read_status`, `parse_codex` or `codex.read_session` changes.
*Drives it (new):* `test_status.py::test_a_provider_with_no_reader_yields_a_blank_status`.
*Green unedited:* `tests/test_status.py`, `tests/test_codex.py`, `tests/test_integration.py`.

**Slice 6 — `limits` and `side_jobs` move behind the record.**
`sidebar.py:2352` and `:2281-2283`. `limits` stays threaded, one call per provider; `snapshot["codex"]` keeps its name and `snapshot["accounts"]` stays on the Bridge, outside the record.
*Drives it (new):* `test_rebuild.py::test_limits_are_read_off_the_loop_once_per_provider`. `latest["codex"]` is written unconditionally today (`sidebar.py:2352`) and stays that way; a third provider's limits have no page consumer yet, so no new key is added.
*Green unedited:* `tests/test_codex_jobs.py`, `tests/test_meters.py`, `tests/test_meter_loop.py`.

**Slice 7 — isolation. Independent of the contract, required before a third provider.**
Two present defects that can blank or stale the panel, and one cosmetic:
- `sidebar.py:2625` — the startup `await bridge.rebuild()` is unwrapped and runs *before* `async_register_web_view_tool` at `:2628`. `rebuild()` does not catch (`:2323-2341`, only `finally: self._rebuilding = False`) and `poll()` catches (`:2594-2600`) and `watch_layout` catches at `:2535` but then ends its monitor, so one provider reader raising at startup means no panel registers at all.
- `sidebar.py:2257`, `:2352` — provider readers run inline, catching `OSError` only; a `TypeError` or `ValueError` on a malformed rollout propagates. `self.last_ok` is stamped after everything (`:2355`), so the raise costs freshness and the panel wears STALE (`:1952-1963`) when one card's enrichment failed.
- `page.html:2364` — the `innerHTML = undefined` above. It prints the text "undefined" in the SVG and does not throw, so it is cosmetic, not isolation.
*Drives it (new):* `test_rebuild.py::test_a_reader_that_raises_still_stamps_the_frame`, `test_page_icons.py::test_an_unknown_provider_draws_a_generic_mark`. That one can only assert the source shape (that `PROVIDER_ICONS[kind]` is guarded): no test in the tree runs JavaScript, `test_page_icons.py` is regexes over the source, and the WKWebView harness paints only the first frame. The page changes in slice 8 ship checked by eye in the panel, not by test.

**Slice 8 — the first new agent, and the page descriptors it forces.**
One row in `AGENTS`, one `<name>-hooks.sh`, `--agent <id>`, `snapshot.providers`, and the seven page edits above. A tier-1 agent whose hooks already register cleanly is the right first pick; a tier-4 entry (`foreground_names` only) is the cheapest possible proof the table works end to end. Whichever it is, it is also what decides whether the `match` field and the `keys`/`values` maps get added now.

The nesting guard (`nested_agent`, `emit-state.py:756-765`) stays one-way until then. It sees codex-inside-claude only, so a Claude started inside a Codex tool publishes over the pane. Generalising it to "any other row's marker present, mine absent" needs a second measured marker, and the table has one (`CLAUDECODE`; Codex sets none we have measured). The survey found only compatibility aliases (`CLAUDE_PROJECT_DIR` on Gemini and Qwen), and an agent that ever ships `CLAUDECODE` for compatibility would make the general guard silence a real pane. It is built with the first agent whose marker is measured on a live run.

## Present bugs found on the way

None is fixed by this proposal's first slices, and none was touched during the research.

- `read_state` (`emit-state.py:408-422`) does not carry `background` through, while `aggregate` reads `doc.get("background")` (`:279`) and `apply_event` carries it (`:302`) and `published`/`aggregate` depend on it — so background tasks recorded by one `Stop` are dropped on the next event's read and a session parked on one can read `idle`. `blank_state` (`:93-95`) omits it too. Confirmed by the critique.
- The startup `await bridge.rebuild()` at `sidebar.py:2625` is unwrapped and runs before the panel registers (slice 7).
- Provider readers catch `OSError` only, so a malformed rollout stales the whole panel (slice 7).
- `user.claudeStatus` is fetched per pane per poll and never read (slice 4).
- `HOUSEKEEPING` types Claude's commands at Codex rows (slice 8, or sooner).
- `providerIcon` prints "undefined" for an unknown id (slice 7, cosmetic).

## Risks and open questions

**1. One shared `user.agentState`, or a registered variable name per provider?**
No enumeration API means the daemon must know the names up front, so a third-party tool cannot get a card without a repo change — unless every agent writes one variable carrying `provider` inside it, where newest-write-wins needs no `ts` arbitration at all and `pick_agent` disappears. *Recommendation:* add `user.agentState` as the v1 protocol variable and keep reading `claudeState`/`codexState` alongside it — additive, no install breaks, and the transition costs one more `async_get_variable` round trip per pane per 2s poll (`sidebar.py:2231-2235`). A cutover instead of an overlap is cheaper at runtime and breaks every install until `install.sh` is re-run, which is yours to call. Slices 1-7 do not depend on this either way. The critique's note: with one variable, physical last-write-wins replaces the `ts` arbitration for the dead-Claude-then-Codex case, and `parse_state`'s pid-liveness check (`sidebar.py:815-817`) still covers the window before the new agent's first event.

**2. `openai` or `codex` as the id — and is `row.provider` always set?**
The tree has both vocabularies for one agent: a pane says `openai` (`sidebar.py:2250`), a job row says `codex` (`:1481`), and the page branches on each (`page.html:2636` vs `:2793`). Claude's id is unnameable because `snapshot()` omits it (`:654-655`) and the page defaults (`:2636`). *Recommendation:* unify on `codex` — the card already prints "Codex" beside the OpenAI mark, and the descriptor carries `vendor: "OpenAI"` for the icon's `aria-label` — and always set `row.provider`. Cost: `page.html:2636,2669,2741,2793` plus `tests/test_snapshot.py:168-171` and the deletion of the assertion at `:177` (test defined at `:174`), which is a test deletion and needs the owner's word that Claude rows carry none. Ids are not persisted anywhere, so there is no data migration.

**3. Withdrawn after review: `--codex` stays as it is, see Review outcome. The original text:**
Slice 3 introduces `--agent <id>`. Old installs' `~/.codex/hooks.json` carries `--codex` until `install.sh --codex` is re-run. *Recommendation:* accept both — `--codex` as codex's alias — and register only `--agent codex` for new installs. That is backward compatibility, which needs your explicit say-so; the alternative is a silent breakage where a Codex pane stops reporting until someone re-runs the installer, with no error anywhere.

**4. Does every agent's state stay under `~/.claude`?**
`LOG` (`emit-state.py:57`), `STATE_DIR` (`:63`), `TASKS_DIR` (`:77`), `sidebar.py:1225,1417,1542,1545` are all `~/.claude/…`, including Codex's state — which is why `install.sh:118-124` has to punch a `writable_roots` hole in Codex's sandbox, and every future sandboxed agent needs the same hole at a path named after a different vendor. *Recommendation:* leave it and name the cost in `docs/`. Moving to `~/.agents-sidebar` orphans in-flight `.published` detail files (self-healing, they are per-session) and rewrites four path constants plus the sandbox stanza — cheap, but churn with no user-visible gain until a third sandboxed agent arrives.

**5. How much of the page becomes data-driven in slice 8?**
The descriptor map is 7 edits (icons, labels, commands, effort, chips, subagent mark, CSS). The budget strip and account chrome are another ~250 lines and I have excluded them. *Recommendation:* ship the 7, defer the strip until a third provider actually reports limits. The one I would not defer is `HOUSEKEEPING` (`page.html:1335-1339`): it types `/compact`, `/rotate` and `/clear` into any agent row today, so a Codex row is already offered two commands it does not have (Codex has `/compact`; it has no `/rotate`, a Claude Code skill, and uses `/new` where Claude has `/clear`). That is a live bug, not a future one.