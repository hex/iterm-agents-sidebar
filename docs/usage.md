# Using the panel

The reference for what each part of a card means. The README covers the parts
you need on day one.

## Which group a session lands in

A session running Claude Code or Codex, or sitting in a `cs` session
directory, goes in `AGENTS`. Everything else goes in `SESSIONS`. A Codex
terminal counts from the moment it opens, which the panel reads from the
foreground process, since Codex itself says nothing until the first prompt.

Rows read `t3` for the third tab, `t3.2` for the second pane of a split tab,
and `w2.t3` once there is a second window. The number is a position you can
count to, not iTerm2's internal tab id.

## What keeps a session working

A session whose turn has ended stays working while a background shell,
subagent, workflow or monitor it started is still running, because that task's end wakes it. A background command that never ends keeps it working until
your next prompt.

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
directory without an `@` takes its branch as its name. When the main session is
not open, the card stays put, under its own name.

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
terminal gets nothing. Codex sessions get a plain banner with no actions.

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
`stale`. A hundred percent shows `Done` and stays until a new request starts a
new task.

The ticks show the estimate as a count you can glance at. They are not the
solid bars of the limit meters in the foot, on purpose: those go green, amber
and red, and that would make being nearly done look like a warning.

`docs/task-line-design.md` has the hook cadence and the note format.

## Background shells

When the last shell ends, the line stays for a few seconds, dimmed, as
"1 command finished", so a run of short commands doesn't grow and shrink the
card each time. A shell whose command the panel can't parse shows `?`.

## The cost figure

The coin in the bar adds up what the running Claude Code sessions report having
spent, at API prices. That figure is what those sessions report, not a bill. The
terminal mark beside it counts how many sessions report anything at all.
