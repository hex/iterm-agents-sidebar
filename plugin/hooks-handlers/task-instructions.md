# Task line

The Agents sidebar shows, under this session's name, what you say you are working on. Report the progress of the user's whole current request through the task script named below. This is your estimate, not a timer or a count of tools. A reporting failure must never stop the actual work: give one short diagnostic and continue, without retry loops.

Only the top-level agent of this session reports. Subagents and teammates never run it.

At genuinely new work, run `begin` with a short title before task tools or a blocking clarification question, so a finished task never describes new work. A clarification, a continuation, or continuing after compaction reuses the existing task. Ordinary questions about finished results need no task.

Report a rough percentage in five-point steps and a two-to-four-word activity, such as `Reading code`, `Testing changes`, or `Waiting for you`. Revise the estimate downward when you discover more work. Use `--unknown` while the scope is unclear. The activity can change while the percentage stays the same.

Report after meaningful milestones, changes of activity, blockers, and before a substantive reply. During active work, aim for one check-in per minute at a natural tool boundary. Never invent progress because a timer says so.

Use 100 only once the entire requested outcome and its checks have finished. A tool finishing or a clarification question is not completion. Reported 100 shows `Done` and stays complete; more work needs a new `begin`.
