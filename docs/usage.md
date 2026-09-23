# Using the panel

The reference for what each part of a card means. The README covers the parts
you need on day one.

## Which group a session lands in

A session running Claude Code, Codex or omp goes in `AGENTS`. The panel
knows one by the agent's mark in the tab title, the state it reports, or its
process. A terminal that only sits in a `cs` session directory is not enough.
Everything else goes in `SESSIONS`. A Codex
terminal counts from the moment it opens, which the panel reads from the
foreground process, since Codex itself says nothing until the first prompt.

A screen reader reads a row's position out with its name: `t3` for the third
tab, `t3·2` for the second pane of a split tab, and `w2·t3` once there is a
second window. The row itself does not show it. The number is a position you
can count to, not iTerm2's internal tab id.

## What keeps a session working

A session whose turn has ended stays working while a background shell,
subagent or workflow it started is still running, because that task's end wakes it. A background command that never ends keeps it working until
your next prompt. A monitor does not: it only waits for something outside to
happen, and the watcher Claude Code arms when a session publishes an Artifact
stays open for as long as the session does.

The hook stamps the time your prompt started the turn, which is what the
`long 25m` outline counts from.

## Order

Cards follow iTerm2's own order of windows, tabs and panes. Sort cards by name,
under Rows in settings, switches to alphabetical order. Either way a teammate
stays under its lead and a worktree card stays docked to its session, because
each card travels with the rows under it.

## Which agent a card runs

Provider badge, under Rows in settings, picks how a card says whether it runs
Claude Code, Codex or omp:

| Choice | What you get |
|---|---|
| Tag by the name | A small pill after the session name, tinted in the agent's colour, with its glyph and its name. The default |
| Icon in the corner | The glyph alone in the card's top corner. The state badge moves over for it |
| Group by provider | Cards gathered under a head for each agent, Claude first. The list no longer follows your tabs. With one agent running there are no heads |
| Off | The glyph stays before the model name, as the only sign of the agent |

With a tag or a corner mark the glyph leaves the facts line, so a card says it
once. Sorting by name still applies inside each group.

## Teammates and worktrees

A teammate sits under the lead that spawned it, wherever it runs, and takes the
name and badge colour Claude Code gave it.

A session in a linked git worktree of another open session's repo (a cs feature
session in `<repo>@worktree`, for example) keeps its own card, right after that
session's card and tied to it by a short line across the gap. Its name is the
feature, the part after the `@`, since the branch has its own chip. A worktree
directory without an `@` takes its branch as its name. A directory named
`<base>@<feature>` beside a session directory `<base>` docks there by name
alone, when git cannot tie the two (a symlinked home, a main shell parked in a
subdirectory). When the main session is not open, the card stays put, under
its own name.

## A waiting card

A card that starts waiting on you, for a question or a permission prompt,
while it sits past the top or bottom edge of the list scrolls into view. One
already on screen stays put.

A waiting card says what it waits on, under the name: the first question of an
AskUserQuestion (two lines at most, with "+1 more" when it asked several), or
the tool a permission prompt is for and the first line of what it would run.
The line goes when the prompt is answered. An omp session reports only that it is
blocked, so its card shows no question.

Under a question the card lists its options, a button each. The one the agent
suggests, whose label ends in "(Recommended)", is tinted green. Clicking one types
that option's number into the prompt, as if you had pressed it there. The
daemon types it only while that same question still stands, and only once.

When the agent asks more than one question at once, each click moves the card to
the next question, and after the last it shows Submit answers; Cancel stays
in the terminal. The daemon types each step once, in order. Claude Code says
nothing as it moves from one question to the next, so the card counts only
its own clicks: answer a question in the terminal and the card's next click
answers the question after it. Answer a set in one place.

A question that takes more than one answer shows its options without
buttons; answer it in the terminal. While a card asks, it
drops its task line, model line and folds, so its height barely moves; they
come back once you answer.

## What fills the context

Rest the pointer on a Claude card for about a second and its hover card holds
still and takes clicks. Context breakdown then runs Claude Code's own
`/context` on a throwaway fork of that conversation: hooks off, nothing saved,
no model call. It takes a few seconds, and the result stays in the card until
you read it again.

The bar is the whole window: the conversation, system and tools, memory, and
agents and skills in their own colours, then the reserve kept free for
compaction, hatched. Under it every category has a row with its own bar. The
deferred tool rows sit apart, since Claude Code loads them only when a tool
runs and does not count them. Only the conversation's rows are this
session's own; the rest are what a new session in the same directory would
load now. The figures are `/context`'s estimate, so they can differ from the
Context percentage above them, which Claude Code measures on each turn.

## Banners

The banner uses the session's name as the card shows it. The panel posts nothing for the session you are looking at, meaning the session in front of its window
while iTerm2 is the frontmost app. A session in another tab of the same window
still gets one, since that is exactly when you can't see it.

A session has one banner at most, and going back to work takes it down. Like
the sounds, banners only post while the panel is open, and they need the app
that `install.sh` builds. A banner plays no sound of its own; the sound
switches are separate.

macOS shows a single action inline and folds two or more into an Options menu,
so a question is always a menu. The banner sends keystrokes only while its question is still open, so a prompt you already answered in the
terminal gets nothing. omp sessions get no banner from the panel, since omp
posts its own.

## Focus

Bring a blocked session forward only goes back if you are still on the session
it brought you to. If you moved somewhere yourself, you stay there. Blocks in a row unwind in order.

## Plain terminals

A plain terminal takes its path as its name, as its prompt writes it. Its tab's
title sits on the line below, before the branch, and the panel leaves out a
default title: the shell's name or `user@host:path`.

At its prompt it shows a shell mark in its session colour where an agent shows
its square. While it runs a command it shows the working dots and the command's
name, and it goes quiet when it's back at its prompt.

## The task line

The session writes its own report: a task title, what it's doing now, and a rough percentage. A report older than five minutes turns grey and reads
`stale`. A hundred percent shows `Done` with a green tick and stays until a new
request starts a new task.

The ticks show the estimate as a count you can glance at. They are not the
solid bars of the limit meters in the foot, on purpose: those go green, amber
and red, and that would make being nearly done look like a warning.

`docs/task-line-design.md` has the hook cadence and the note format.

## Tasks

Claude Code keeps a session's task list under `~/.claude/tasks/<list>/`, one
file per task, named by `CLAUDE_CODE_TASK_LIST_ID` or `session-` plus the
first eight characters of the session id. The hook reads the list on every
event, since the tool calls that change it are the events, and hands the
panel the pending and running items; a list is never pruned, so completed
ones never show. A subject is clipped to 240 characters and the whole of
what the panel got sits in the row's tooltip. Codex keeps no task list.
Settings > Rows > Task > Task list turns the fold off; that switch hides while
Task is off.

## Background shells

When the last shell ends, the line stays for a few seconds, dimmed, as
"1 command finished", so a run of short commands doesn't grow and shrink the
card each time. A shell whose command the panel can't parse shows `?`.

## Updating

The bar's left end names the release the panel runs, or reads
`unreleased checkout` in a checkout with no `VERSION` file. Once a day, once at
start, and on every press of the reload button, the daemon lists the tags on
the public mirror; when one is newer, the
line adds `2026.09.20 available` and an Update button. Pressing it pulls that
release into the checkout the daemon runs from, runs `install.sh` again and
restarts the daemon. The port changes with the restart, so the bar reads
`restarting, reopen the panel` and the panel goes blank: reopen it from
View > Toolbelt > Agents. A pull the checkout cannot
fast-forward, or an install that fails, leaves the daemon as it was and puts
the tool's last line beside the button; the whole message is in the daemon's
log under Scripts > Manage > Console.

## Resuming an exited agent

When an agent's process dies (killed, or crashed) and its pane drops back to a
shell prompt, the card stays, faded, with an EXITED outline. Resume types the
command that reopens the same conversation at that prompt and brings the pane
forward:

| Session | What Resume types |
| --- | --- |
| A cs session (the directory has `.cs/`) | `cs .`, which asks whether to continue; Enter resumes |
| Claude Code | `claude --resume <conversation id>` |
| Codex | `codex resume <conversation id>` |

The button shows only while that is safe: the pane is at a shell prompt, its
directory still exists, the conversation saved a transcript (an agent killed
before its first reply has nothing to resume), and it is not open in another pane. After
a click it stays away until the agent reports again, or for a minute if the
pane comes back to its prompt without one. An agent
that ends with `/exit` leaves no card behind, and omp sessions have no Resume.
