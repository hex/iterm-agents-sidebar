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

Order, under Rows in settings, picks how the cards are arranged, inside each
agent's group while cards are grouped by provider (the default):

| Choice | What you get |
|---|---|
| Follow the terminals | iTerm2's own order of windows, tabs and panes. A card sits where its tab does and nothing a session does moves it. The default |
| By name | Alphabetical |
| By attention | The working cards first, the longest turn at the top, under a `Working` head; then every other card (at rest, exited, or not yet heard from), the longest rest at the top and the ones without a time last, under `Idle`. A card at rest for ten minutes is washed toward the background, and more after thirty: the sessions that slipped your mind. The heads appear only while a group holds both kinds |

By attention moves a card only once its new state has held for thirty
seconds: a tool pause that reads as idle, or a turn that just ended, leaves it
where it was, and a turn or a rest shorter than that never moves it at all. A
card waiting on a prompt counts as working and goes there at once, without the
wait; the foot's Waiting on you is where the ask itself shows. omp without its extension publishes no times, so the panel times those cards from when it
saw each state begin. Whatever the order, a teammate stays under its
lead and a worktree card stays docked to its session, because each card
travels with the rows under it.

## Which agent a card runs

Provider badge, under Rows in settings, picks how a card says whether it runs
Claude Code, Codex or omp:

| Choice | What you get |
|---|---|
| Tag by the name | A small pill after the session name, tinted in the agent's colour, with its glyph and its name |
| Icon in the corner | The glyph alone in the card's top corner. The state badge moves over for it |
| Group by provider | Cards gathered under a head for each agent, Claude first. The Order choice applies inside each group. With one agent running there are no heads. The default |
| Off | The glyph stays before the model name, as the only sign of the agent |

With a tag or a corner mark the glyph leaves the facts line, so a card says it
once. The Order choice still applies inside each group.

## Shell names

Shell names, under Rows in settings, picks the face of a shell card's name
in the Sessions group, which is a path or a command:

| Choice | What you get |
|---|---|
| System | The panel's own face, as agent names have. The default |
| SF Mono | SF Mono, a size smaller, since its letters run wider |
| Terminal font | The font of your default iTerm2 profile, at the panel's size. The daemon reads it when it starts, so a profile font you change later shows after the next iTerm2 start, or a [daemon restart](development.md#the-install-and-the-port). When the panel could not read it, the choice reads `Terminal font (not read)` and the names use SF Mono |

Agent names and the rows under a card keep their face whichever you pick.

## A long name

A card name too long for its row fades out at the edge. Every few seconds it
slides left to show its end, and its start comes back in from the right. It
stays still when Reduce motion is on in macOS accessibility settings.

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
while it sits past the top or bottom edge of the list scrolls into view,
whole, with its answer buttons. A card taller than the list shows from its top.
One already fully in view stays put.

A waiting card says what it waits on, under the name: the first question of an
AskUserQuestion (three lines at most, with "+1 more" when it asked several), or
the tool a permission prompt is for and the first line of what it would run,
under the reason the agent gave for it when it gave one (Codex's escalation
reason, Claude's command description). The line goes when the prompt is answered. An omp card shows its
question, or the tool and the command, the same way, through omp's extension,
but no buttons under them: omp draws its own prompts, so you answer in omp.
An omp session without the extension reports only that it waits, so its card
shows no question.

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

Under a permission prompt the card shows Yes and No, each marked with the key
it types: Yes is `y` on Codex and `1` on Claude Code, No is Esc on both. Neither
agent tells the panel which options its prompt lists, and Codex's vary from one
prompt to the next, so the rest, such as "don't ask again", stay in the
terminal. The daemon types the key only while that same command still waits,
and only once.

A question that takes more than one answer shows its options without
buttons; answer it in the terminal. While a card asks, it
drops its task line, model line and folds, so its height barely moves; they
come back once you answer.

A card that asks holds still under the pointer. An update that would move it,
a card above it growing or the order changing, waits until the pointer leaves
the card, you answer the question, on the card or in the terminal, another
question replaces it, or the panel goes out of sight. The card ignores a click on an
answer, Yes or No in the 0.7 seconds after it moved, so the option that slid
under the pointer is never the one that counts.

## What fills the context

Pick Details from a Claude card's right-click menu: its details card opens
and stays until Escape or a click elsewhere. Context breakdown then runs Claude Code's own
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

## Sounds

The daemon notices each change as it reads the sessions and plays the sound
itself, so sounds, banners and the focus move come whether or not the panel is
open in any window, and each moment plays once, even for a session shown in
two panes (two tmux clients on it). A setting takes effect on the
next change, in every window. At most two sounds play at a time. Each alert,
and any problem playing one, is written to `daemon.log` in
`~/.claude/agents-sidebar-status`.

## Banners

The banner uses the session's name as the card shows it. The panel posts nothing for the session you are looking at, meaning the session in front of its window
while iTerm2 is the frontmost app. A session in another tab of the same window
still gets one, since that is exactly when you can't see it.

A session has one banner at most, and going back to work takes it down, as
does closing the session. Banners need the app that `install.sh` builds. A
banner plays no sound of its own; the sound switches are separate. A session
waiting on something other than a question or a tool it wants to run says it
"needs you".

macOS shows a single action inline and folds two or more into an Options menu,
so a question is always a menu. The banner sends keystrokes only while its question is still open, so a prompt you already answered in the
terminal gets nothing. A Reply to a finished turn types nothing once the
session waits on you, its agent has exited, or another program is in front of
its agent. omp sessions get
no banner from the panel, since omp posts its own.

## A finish you have not seen

A banner lasts five seconds. A card whose turn ended while you were not
looking at that session wears a green DONE badge in place of IDLE until you do.
Looking means the same as for banners: the session is in front of its window
while iTerm2 is the frontmost app. The sound and banner switches don't change
it, and omp cards get it too.

Going to the session from its card, or a banner or a block bringing it
forward, takes the mark off at once. Moving to the session inside iTerm2 takes it off at the next
reading, within two seconds. A new prompt takes it off, and so do a block, an
exit and closing the session. A Stop hook that runs a command and briefly
flips the session back to working does not, since that is not a new turn.

The marks live in the daemon's memory, so a daemon restart clears them. A
turn that went unknown before it ended is not counted as finished. Two panes
showing one conversation each keep their own mark.

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
`stale`. A hundred percent shows `Complete` with a green tick and stays until a new
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
what the panel got sits in the row's tooltip.

Codex keeps its plan in its `update_plan` tool instead. Each call carries the
whole plan, so the hook keeps the pending and running steps of the latest one
and shows them in the same fold until the next call replaces them; a plan
with every step completed leaves no fold. Codex 0.160 ships the tool off, so
its sessions make no plan until `~/.codex/config.toml` has:

```toml
[tools.update_plan]
enabled = true
```

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
the repository the checkout was cloned from; when one is newer, the
line adds an Update button, which names the new release in its tooltip. Pressing it fetches that
release into the checkout the daemon runs from, checks it, runs `install.sh`
again and restarts the daemon. The port changes with the restart, so the bar reads
`restarting, reopen the panel` and the panel goes blank: reopen it from
View > Toolbelt > Agents.

Update takes a release only when all of these hold, and otherwise refuses
with the reason beside the button, leaving the checkout and the daemon as
they were:

- git is 2.34 or newer, the first that checks SSH signatures
- no tracked file in the checkout has local edits, which would run unsigned
- the new commits continue the checkout's history in a straight line, with
  no merge commits, and every one carries an SSH signature by a key the
  commit before it lists in `release-signers` and does not list in
  `release-revoked`
- or, when the mirror's history was rewritten and continues nothing in the
  checkout, its newest commit carries an SSH signature by a key the
  installed release lists and does not revoke, it revokes every key the
  installed release revoked, and it adds no file that sits untracked in the
  checkout. The checkout must itself be a signed release, so commits of
  your own are never dropped. The checkout then moves to that commit
  instead of fast-forwarding
- the new `VERSION` is newer than the installed one. It is read from the
  signed commit, not from the tag that offered it, so a stray tag cannot hold
  a release back

An install that fails after that also puts its last line beside the button,
and puts the checkout back on the release that runs, so the offer stays and
the next press tries again.
The whole message is in the daemon's log under Scripts > Manage > Console.

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

## From a script

`install.sh` links the `agents-sidebar` command into `~/.local/bin`. It reads
what the panel reads, from the running daemon, so the panel has to be running.

```sh
agents-sidebar status                 # one line per agent
agents-sidebar status --json          # the rows as the panel has them
agents-sidebar wait atlas             # until atlas waits on you or is idle
agents-sidebar wait current --until done --timeout 600
```

`status` prints each agent as its session id, label, provider and state,
separated by tabs. A Claude agent's provider is `claude`, and an agent whose
state the panel cannot read shows `unknown`. When the daemon says its reading
is stale (the panel's `STALE` banner), `status` still prints the rows, says on
stderr that they may be out of date, and exits 1.

`wait` returns once the session is in one of the states you ask for and prints
its row as JSON. `--until` takes `working`, `blocked`, `idle`, `done`,
`unknown` or `exited`, once or more; without it the wait is for `blocked` or
`idle`. `done` is a turn that ended while you were not looking at that
session, the card's unseen mark. `idle` matches it too.

The target says which session:

| Target | Which session |
| --- | --- |
| An iTerm2 session id | That one, as `status` prints it |
| A label | The one agent with that label. Two tabs on the same repo share one, so when two agents carry it the command lists both and stops |
| `current` | The pane the command runs in, found by its terminal |

`current` goes by the terminal, not by `$ITERM_SESSION_ID`. Inside tmux that
variable comes from whichever pane started the tmux server. Codex runs its
hooks in one process shared by every Codex pane, and there it names the pane
that started that process. Either way it can name another pane that is still
open, so a command with no terminal anywhere above it stops with exit 1
rather than wait on the wrong agent. A command an agent runs has no terminal
of its own, so the terminal of the nearest process above it counts, which is
the agent's pane. Two agents on that one terminal stop it the way a shared
label does.

A state that already holds returns at once. While the daemon says its reading
is stale (the panel's `STALE` banner), nothing matches until the reading is
fresh again, and that holds from the moment the wait connects. If the daemon restarts, for an update say, the wait connects to
the new one when it answers within 10 s and carries on. The wait settles on a
session at the start, so a label that later moves to another pane does not
move the wait.

| Exit | When |
| --- | --- |
| 0 | The session is in a state asked for |
| 1 | The timeout passed, the session closed, nothing answers to the target, the daemon is not running, or `status` printed a stale reading; stderr says which |
| 2 | An argument it cannot use, a label more than one agent carries, or two agents on the terminal `current` names |
