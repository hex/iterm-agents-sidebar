# Past sessions and window snapshots: a plan

Drafted 2026-10-30 on `feat/mask-and-keepalive`, after a look at another
Toolbelt panel for AI agents that ships both. This is a plan with its
questions open, not a design that was decided. Nothing here is built.

## Problem

The panel shows live sessions only. A conversation that is over is gone
from it: the card leaves when the process ends with `/exit`, and an Exited
card stays only while its pane sits at a shell prompt. Two things follow:

- A conversation closed yesterday has to be found with `claude --resume`
  and a picker, or `cs` and its manager, or `codex resume` and a list.
  Three tools, three lists, none of them in the panel.
- A window layout with four agents in it is rebuilt by hand after a
  restart of iTerm2 or the Mac: the panes, their directories, and which
  conversation each one continues.

The other panel answers both with a Sessions tab (every past conversation
of every agent, by project, with Resume) and window snapshots (every
window's panes with their directory and conversation, saved every five
minutes and restored as new windows with the agents resumed).

## What exists already

- **Resume on an Exited card** (`docs/usage.md`, "Resuming an exited
  agent"): the card types `cs .`, `claude --resume <id>` or `codex resume
  <id>` into the pane. The conversation id, the directory and the safety
  checks (pane at a prompt, directory exists, a transcript was written,
  not open elsewhere) are all in the daemon.
- **cs owns session layout** for cs sessions: `cs <name>` creates or
  resumes a session in its own window, `cs -checkpoint` snapshots state,
  and the session manager lists every session. The panel never duplicated
  that and should not start.
- **The stores a list would read**: `~/.claude/projects/<dir>/<id>.jsonl`
  (2,671 project folders on this machine), `~/.codex/sessions/<y>/<m>/<d>/`
  with `~/.codex/session_index.jsonl` beside it (id, thread name, updated
  time), and omp's own session folders. Codex titles its conversations;
  Claude's title is the first prompt or the summary line in the transcript.
- **Live facts, not documents**: a line on a card shows derived state or a
  self-report with its age, never a maintained document. A past-session
  list is a reading of files, which passes; the titles are the agents'
  own.

## Feature 1: past sessions

### What it would be

A list behind the limits foot or a fold of its own: the conversations that
ended, newest first, each with the agent's mark, the title the agent gave
it, the directory as the card would show it, and when it last wrote. One
button, Resume, which opens it where it belongs:

| Conversation | Resume does |
| --- | --- |
| A cs session | `cs <name>` in a new window, as cs opens one |
| Claude Code outside cs | a new tab in the directory, `claude --resume <id>` |
| Codex | a new tab in the directory, `codex resume <id>` |

The live cards stay as they are. A resumed conversation gets its card the
way a new session does, through the hooks.

### What it costs

- Reading the stores. 2,671 project folders is a first scan of seconds and
  a cache after it; the other panel caches to disk and reads only appended
  bytes. The daemon rebuilds every few seconds today and must not grow a
  scan in that loop; the list is read on open, off the loop, like a
  Keychain read.
- A second kind of row on the page, with its own fold, search when the
  list is long, and the empty state.
- Two ways to open a tab: the daemon opens tabs for notices already
  (`Focus`), so the iTerm2 call exists; what is new is a tab with a
  directory and a typed command, which is the Resume path with a new pane
  instead of the exited one.

### What it should not do

- Not list cs sessions beside the cs manager as a second manager. A cs
  session appears once, as a session, and Resume hands it to `cs`.
- Not show a conversation that is open now: the live card is the row.
- Not read transcripts for anything but the title and the time.

### Questions for the decision

1. Is the panel the place for this at all, or is the Exited card's Resume
   plus `cs` enough? The case for it is Codex, which has no manager and
   whose `codex resume` list is a TUI picker; the case against is that cs
   already answers it for the sessions that matter most here.
2. How far back: a day, a week, or everything with a search box. The
   other panel lists everything, by project.
3. Where it lives: a fold under the limits foot, or a third mode of the
   list beside Cards and Outlines.

## Feature 2: window snapshots

### What it would be

A saved picture of every window: for each tab, its panes, each pane's
directory and the conversation running in it. Restore opens the windows
again, splits the panes, `cd`s each one and resumes its agent.

### Why it is weaker here than there

- cs sessions already come back by name, in their own window, with their
  conversation. For a Mac of cs sessions the snapshot adds the arrangement
  of panes, not the sessions.
- The daemon already knows every pane's directory, tty and agent: the
  capture is a serialisation of the layout it reads every tick. The
  restore is the new part: iTerm2 window and split creation, waiting for
  each shell, typing a `cd` and a resume command into each pane. The other
  panel's restore is 50 lines with a wait-for-shell loop; its correctness
  depends on the shell being at a prompt when the text lands, which is the
  same race the Resume button already guards against.
- Typing into panes is the daemon's most guarded path (the prompt guard,
  the token, the refusals). A restore types into many panes at once, each
  a fresh shell, so the guard is simpler there, but the surface grows.

### Questions for the decision

1. Does anyone here lose a layout often enough to want this? An iTerm2
   restart is rare and `cs` brings sessions back by name. Without a yes,
   this stays unbuilt.
2. If yes: autosave every few minutes like the other panel, or save on
   demand only. Autosave writes a file the user never asked for; on demand
   is a button that is forgotten until after the restart.
3. Format: the other panel writes TermDeck's JSON so that tool restores
   the same files. Sharing a format with a tool that is not installed here
   is no reason to pick it; a format of its own is one file.

## Recommendation

Build neither until a question above gets a yes. Of the two, past sessions
has the stronger case and the smaller build, through Codex, whose
conversations have no manager; the first cut would be Codex only, read
from `session_index.jsonl`, with Resume in a new tab, and Claude outside
cs after it if the list earns its place. Window snapshots wait for a
layout actually lost.

## Measured before the build (2026-10-30)

The Codex-only first cut was measured against the machine it was for
before any code, and stopped on the numbers.

| Codex rollouts in the last 7 day folders | 2,431 |
| --- | --- |
| Non-interactive runs (`codex_exec`, from claude-errands and plugins) | 2,337 |
| Interactive terminal sessions (`thread_source: user`, `originator: codex-tui`) | 5, of which 4 opened and left with no prompt |
| Threads in `session_index.jsonl` | 11, mostly Companion tasks that Claude Code ran |
| Claude Code conversations outside cs sessions, same week | 78 |

Two premises of the plan did not hold:

- `session_index.jsonl` is not a list of conversations. It holds the
  threads that got a name, 11 of 2,431; the rollouts' own `session_meta`
  line (`thread_source`, `originator`, `cwd`) is the only authority.
- Codex is used here almost entirely non-interactively, through other
  agents. A list of interactive Codex sessions to resume would show about
  one row a week.

Decision: not built. Past sessions stays an open question, and the next
look at it starts from Claude Code outside cs, where the conversations
are, not from Codex. Window snapshots keep the questions above.
