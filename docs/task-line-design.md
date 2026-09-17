# Task line: a session's own account of its work

Approved 2026-09-16, after reading herdr-agent-progress
(github.com/eliasstravik/herdr-agent-progress), whose shape this follows.

## The line

Under each agent card's name, the session's own account of its work: a task
title, a rough percentage, a two-to-four-word activity, and how old that
report is. Self-reported by the model running in the pane, not measured. The
age and the rule that every new request starts a new task are what keep it
honest.

Replaces the README objective line (`session_objective`, `show_objective`),
which depended on a document nobody kept current.

## The note

One JSON file per session, `~/.claude/agents-sidebar-tasks/<session_id>.json`:

```json
{"task": "<uuid>", "title": "Fix the login bug", "activity": "Reading code",
 "percent": 35, "done": false, "ts": 1789552045}
```

- `title` up to 80 characters, `activity` up to 40; control characters and
  bidi marks stripped; the script rejects an empty value.
- `percent` is an integer 0 to 100 or null (unknown). No rounding on our
  side; the instructions ask for five-point steps.
- `percent 100` sets `done`; a done task rejects further reports.
- `ts` is the time of the last `begin` or `report`.

Written by `plugin/hooks-handlers/task.py`, which the model runs:

```
task.py --session <id> begin --title "Fix the login bug"
task.py --session <id> report --activity "Reading code" --percent 35
task.py --session <id> report --activity "Assessing task" --unknown
task.py --session <id> report --activity "All checks pass" --percent 100
```

`begin` replaces any task, done or not. `report` needs a task. Every write
is atomic (temp file then rename). Errors go to stderr with exit 1 and one
line; the instructions tell the model never to retry in a loop. SessionEnd
deletes the note (emit-state already clears its own state there).

## The whisper

`emit-state.py` already runs on UserPromptSubmit and PostToolUse for Claude
and for Codex. It gains one output: `{"hookSpecificOutput":
{"hookEventName": <event>, "additionalContext": <text>}}` on stdout instead
of the current `{}`, when there is something to say.

- UserPromptSubmit: the instructions (below), the current note as JSON or
  `none`, and the exact commands with the session id and the script path
  filled in. Always.
- PostToolUse: one line, "Progress check-in is due if this is a natural
  boundary. Reassess; do not invent progress." plus the command, only when
  the note's `ts` is over 60 s old and the task is not done, or there is no
  note and the last reminder was over 60 s ago. The note keeps the reminder time
  (`reminded`); with no note, the emit-state state document keeps it.
- Never when the payload carries `agent_id` or its transcript path contains
  `/subagents/` (a subagent), never when `tool_input` mentions `task.py`
  (the report itself), never on other events.

Instructions text (kept in `plugin/hooks-handlers/task-instructions.md`,
read by emit-state): report the whole current request's progress; new work
means `begin`, a continuation or clarification reuses the task; a
percentage in five-point steps that may go down, `--unknown` while scope is
unclear; activity two to four words such as `Reading code`, `Testing
changes`, `Waiting for you`; report at milestones, activity changes,
blockers, and before a substantive reply, about once a minute during work;
100 only once the whole request and its checks have finished; a reporting
failure never stops the work and is never retried in a loop.

## The daemon

`published()` in emit-state adds `"session": session_id` to the
`claudeState` and `codexState` payloads, so every agent row carries its
session id without the statusline bridge. `parse_state` keeps returning the
state word; a new `parse_session(raw)` returns the id.

On each rebuild the daemon reads the note for that id and puts `task` on
the row when a note exists:

```json
"task": {"title": "...", "activity": "...", "percent": 35, "done": false,
         "reported_at": 1789000000}
```

`reported_at` is the note's `ts`; the page works the age out on its own clock
and ticks it, so the snapshot does not change every rebuild. No note, no key. The
daemon ignores a note it cannot parse. The existing sweep loop
(`sweep_status_dir` gains the tasks directory) removes day-old notes.

## The card

Under the name, before the branch and model line:

```
Fix the login bug
~35% · Reading code · 40s
```

- Percent shows as `~35%`; `100%` shows as `Done` in green with nothing
  after it; unknown shows no percent.
- Age is `40s`, `3m`, `2h`.
- Over 300 s and not done: the whole line greys and ends with `· stale`.
- Setting `show_task`, default on, in the Rows group. This removes
  `show_objective` and the `.objective` line.

## Codex

Same hooks, same output; herdr returns the same JSON to Codex. Verified
live as part of the proof; if Codex ignores it, Codex rows show nothing.

## Tests

Pure functions with fixtures, no mocks:

- task.py: begin/report/done rules, limits, cleaning, atomic write, rejects.
- emit-state: whisper decision (event, age, subagent, self-report, done);
  published payload carries the session.
- sidebar: `parse_session`, `read_task`, row shape, age; sweep covers the
  tasks dir.
- Page: `node --check` on the script, one harness shot.

Live: a Claude session shows a title and activity within a minute of a
prompt; a Codex session too, or the notebook records the Codex gap.
