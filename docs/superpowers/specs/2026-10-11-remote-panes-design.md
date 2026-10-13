# Remote panes: cards for agents on another machine

Designed 2026-10-11 on `spec/remote-panes`.

A pane here that runs `ssh host` or `et host` (Eternal Terminal) can hold a
Claude Code session running on another Mac. Today its card is wrong: the
state reads "exited", a remote tmux pane can wear a local session's name and
branch, and the folder is the local one. This design makes that card honest
and lets it answer a standing question. This is the first of two slices; the
second (a relay the daemon runs over an outbound ssh) gets its own spec.

The request (2026-10-11): "I want to make the sidebar work with remote
sessions, I plan to run claude and codex on another computer". Then: "Both,
but mostly ssh panes in iterm2", and, during the probes, "We need to also
support eternal terminal".

Decided:

- **Slice 1 is state over the pane** (picked: "State over the pane" over
  "Relay from the start" and "Bug fix only first"). Everything in this spec
  travels in the pane's own byte stream, through user variables the hook
  writes on the pane. No connection of the daemon's own to the other machine.
- **A remote card focuses its pane and answers a standing question**
  (picked: "Focus plus answer buttons" over "Focus only" and "Reply too, via
  a helper"). Reply waits for the relay.
- **The question travels in a variable of its own** (picked: "Second
  variable" over labels only in the one variable, and over dropping the
  buttons). It does not fit beside the state.
- **An answer also needs the agent's title on the pane** (picked: "Add the
  title check if it works" over shipping without it and over no typing at
  all). Section 7, check 2 measured it: it works where the remote prompt
  sets a title.
- **The hooks reach another machine through the dotfiles manager** (picked:
  "chezmoi carries it" over an `install.sh --hooks-only` run there and a
  push from this machine).
- **ssh and Eternal Terminal are both supported**, with or without tmux on
  the remote, plain or `tmux -CC`.

Settled earlier and kept: the daemon stays on 127.0.0.1 with its token; no
network listener and no reverse tunnel; no account credentials go to the
other machine; whatever the other machine says is untrusted input; no
screen is ever parsed for state.

## 1. What was measured

Probes ran against a second Mac over ssh and over Eternal Terminal (et 7.0.0
here, etserver 6.2.11 there), each result read back from iTerm2 variables.

| Question | Result |
|---|---|
| Does `OSC 1337 SetUserVar` set on the remote reach the pane's variable? | Yes in every topology: plain pane (bare, wrapped once), local `tmux -CC` pane (bare, once, twice), remote `tmux -CC` pane (bare, once), plain remote tmux inside a local `tmux -CC` pane (once, twice; bare is swallowed by the remote tmux). ssh and et alike. |
| Does the hook's wrap rule need to change? | No. "Wrap once when `TMUX` is set" is right in each case, and an extra wrap is harmless. |
| Does a terminal title set on the remote arrive? | Yes when bare and held, in `name`, `autoName`, `terminalWindowName`, `terminalIconName` (and `tmuxPaneTitle` under tmux). A wrapped title does not arrive under tmux. The remote shell's prompt repainted the title within 2 s of a command ending. |
| Does iTerm2 say the pane is remote? | `hostname` and `username` stay local without remote shell integration. `jobName` is `ssh` or `et` for a plain pane, a local tmux pane and a remote `tmux -CC` pane. |
| What path does iTerm2 report? | The local folder the transport was started in, for a plain pane. The remote folder for a remote `tmux -CC` pane, whose `tty` is empty. |
| Do tmux pane numbers collide? | Yes. Remote pane `%4` took local pane `%4`'s row: its label, tty and branch. `tmux_panes` is keyed by number alone. |
| Does the question cross? | No. All four live local Claude panes carried the envelope with `detail: true` (231 to 238 raw bytes, 308 to 320 of base64): `question`, `subagents` and `tasks` were in the local file only. |
| What does a force-closed et pane leave? | The `etterminal` process and its shell stay alive on the remote. A clean `exit` leaves nothing. |
| Can the daemon tell tmux servers apart? | Yes, measured on the local connection: every iTerm2 tab has `tmux_connection_id`, and `TmuxConnection.async_send_command` answers `display-message -p '#{host}'` and `list-panes` for its own server. |

Read in the code, not run: `parse_state` calls `os.kill(pid, 0)` on the
payload's pid, so a remote pid reads "exited" unless a local process happens
to share the number, and `program_in_front` returns nothing when the pid is
not in the local listing, so the guard that keeps typed text out of a shell
is silently off for a remote pane.

## 2. The hook (`plugin/hooks-handlers/emit-state.py`)

### What it adds

`published()` gains three fields, on every machine, because a hook cannot
know which machine is watching:

- `host`: the machine's short name, `socket.gethostname()` up to its first
  dot.
- `front`: true when the agent's process group is the foreground group of
  its terminal at this event (`ps -o tpgid=,pgid=` on the agent's pid, equal
  values). The same question `program_in_front` asks locally, answered where
  the facts are. The value describes the moment of the event and nothing
  later.
- `cwd`: the session's working folder, for a Claude session too (Codex
  carries it already).

### What the variable carries

`VARIABLE_CEILING` stays at 512 bytes of base64 (384 of JSON): a longer
write can be cut by the terminal, and that is the reason the ceiling exists.
`carried()` keeps its rule: the whole value when it fits, otherwise the
envelope with `detail` and the whole value filed locally.

The envelope is written without spaces between its parts. Measured on a
live blocked session: 238 bytes of JSON today, 219 without the spaces. With
`host` and `front` it is about 257, which leaves room for `cwd` up to about
118 characters; a longer path is cut to its last two components. So the
envelope always carries `host`, `front` and `cwd`.

### The question, in a variable of its own

The question does not fit beside the envelope. After `host` and `front`
about 145 bytes are left, the question's own shape takes about 83 of them
for three options, and that leaves some 60 characters for the question and
every label together. A real three-option question measured 102 characters
of text.

So a standing question travels in a second variable, `user.claudeQuestion`,
under the same ceiling, written as a separate escape sequence:

- It holds the question in its own shape, so the answer checks read it
  unchanged, plus `since`: the envelope's `blocked_since` at the time of
  writing.
- A single AskUserQuestion: every option kept in its place, labels clipped
  evenly, the question text given what remains. If the options cannot all
  be carried, nothing is written: an answer is a number, and a missing
  option would renumber the rest.
- A tool approval: `tool` and a clipped `summary`; `reason` is dropped.
- A set of several questions, or a multi-select: nothing is written. The
  card says a question is standing and focuses the pane.
- When no question stands the hook writes the variable empty.
- The variable is written only when what it would carry differs from what
  stands in it, and before the state that names it, so the panel finds it
  there when the state arrives. A second gate opened while the first stands
  changes the question and not `blocked_since`, so the comparison is on the
  text, never on the time.

The daemon reads it for a remote row only, and only while the envelope's
state is "blocked" and its `blocked_since` equals the question's `since`. A
question left behind by a lost clearing write therefore never shows.

A local daemon still reads the filed value when `detail` is true, so a local
card changes in nothing.

## 3. The daemon (`sidebar.py`)

### Recognising a remote row

A row is remote when its state carries a `host` that is not the daemon's own
short name. The row then carries `host` in the frame. A state without
`host` (an older hook) is handled as today.

For a remote row:

- `parse_state` does not ask the local process table. The state is the
  envelope's, with the existing rule that a "working" claim gone quiet reads
  "unknown".
- The row is live only while the pane's transport is in front here: the
  pane's foreground job (`jobName`, or the local tmux pane's job from the
  process listing) is one of `TRANSPORTS = {"ssh", "et"}`. When it is not
  (the link dropped and a local shell is back, or ssh is suspended), the
  state reads "unknown" and the card offers no action. The variable outlives
  the link, so nothing else says the session is out of reach.
- `path` is the envelope's `cwd`, else the folder its own tmux connection
  reports (next section), else empty. iTerm2's path for a plain remote pane
  is a local folder and is not shown.
- The fields the daemon reads from this machine are empty: model, context,
  cost, tasks, subagent list, branch, processor and memory readings, status
  line payload, transcript, Remote Control, links and partners. The count
  of subagents (`agents`) is in the envelope and is shown.

### tmux panes, per connection

`read_tmux_panes` asks the local tmux binary and returns one table keyed by
pane number. A second tmux server (a remote `tmux -CC`) numbers its panes
from zero as well, so its pane takes a local pane's tty and folder.

Each tab names its tmux connection (`tmux_connection_id`), and each
connection is asked through iTerm2 for its host and its panes (`list-panes
-a -F ...` through `TmuxConnection.async_send_command`):

- A connection whose host is the daemon's own: its panes are the local
  table's, paired with local terminals and the process listing as today.
- A connection on another host: its panes give the folder and the host and
  nothing else. No local tty, no local job, no local process is ever paired
  to them.
- A connection that could not be read: its panes are left to what iTerm2
  reports, never to the local table.

Two tmux servers on this machine still share the local table by number;
that is as today and outside this design.

This fix stands on its own. It gets built first, and it ships even
if the rest waits.

### Actions on a remote row

Every write the daemon makes into a pane goes through one place, and that
place holds the remote rule: into a remote pane it types one key that is
not Enter, and only when each of these holds:

- the transport is in front here;
- the envelope's `front` is true;
- the pane's `autoName` starts with the agent's title marker;
- the row's state is "blocked".

That covers every path that types, not only the card's buttons:

- **Focus**: always.
- **Answer** from the card: the digit, `y` or Escape it types today, under
  the rule, and only onto the question that stands, by the existing check.
- **A notice's buttons** (a macOS notification): the same one key under the
  same rule. A remote row's notice has no reply field.
- **Reply**, a notice's reply, and any raw text: refused: "replies do not
  reach a remote session yet".
- **Resume**: never offered. A conversation id from another machine is not
  typed into a shell here.
- **Link and partner**: refused: "a remote session cannot be linked yet".
- **The context breakdown**: refused; it would start a local fork of a
  conversation this machine does not have.
- **Remote Control keeping**: a remote row is never owed; the daemon reads
  that state from local files only.

Refusal wording for a key: "the connection to <host> is not in front
here", "something is in front of the agent on <host>", "the agent's title
has gone from the pane", "it is not waiting on you".

The host named in a refusal or on the card is text from the other machine.
The daemon clips it, renders it as text, and never builds a command from it.

## 4. The page (`page.html`)

A remote card carries a small mark with the host's name, in the facts
line's grey like other small marks. Its look is picked from a rendered
variant round before the build, as other marks were.

A remote card has no Reply field and no Resume. With a question in its
variable it shows the same buttons a local card shows. With a question the
hook wrote none for, it shows that a question is standing, and a click focuses the pane.

## 5. Hooks on another machine

The hooks are a Claude Code plugin: the `plugin/` folder, copied to
`~/.claude/skills/agents-sidebar`. On the machine with the panel,
`install.sh` makes that copy from the checkout. On any other machine the
dotfiles manager makes it: it pulls `plugin/` from a tagged public release
into the same place, pinned to the tag, on every machine except the one
that runs `install.sh`.

That change lives in the dotfiles repository, with one more: the status
line setting names a path inside this checkout, which exists on one machine
only, so it becomes a per-machine value there.

What this repository owes that route:

- `plugin/` stays whole on its own: nothing in it reads a file outside it
  at run time.
- The README says how a second machine gets the hooks, and that a hook
  older than this release shows remote cards as before.
- The task-line instructions are added to a prompt only where the
  daemon's endpoint file exists, so a machine with hooks alone stays quiet.
- No daemon, no AutoLaunch script and no Codex hook file is installed
  there. A Codex on the other machine usually runs its hooks with no
  terminal, files its state locally, and so shows nothing here until the
  relay.

## 6. Failure modes, written before the code

1. **Two machines share a short host name.** The remote row is taken for
   local: its pid is asked of the local table and it reads "exited", as
   today. Nothing is typed into it under remote rules.
2. **The agent dies after its last event while a question stands.** No
   event fires, `front` stays true, and an answer's key lands on the remote
   shell's prompt line. The key is a digit, `y` or Escape with no Enter, so
   nothing runs; the key sits on the line. Section 7, check 2 looks for a
   second witness that would refuse this. Decided at review: the title
   check is added if check 2 passes. It passed, so the marker is required.
   A remote shell that sets no title is the case it does not cover; answers
   ship with that limit, stated in the README (picked: "Ship, document it"
   over an opt-in per host and over no typing at all).
3. **The link drops.** The local shell is in front; the transport check
   fails; the card reads "unknown" and types nothing. An et client is
   expected to stay in front and reconnect on its own, which would keep the
   card's last state through a network break (section 7, check 7).
4. **ssh is suspended (`~^Z`) or another program is in front here.** The
   foreground job is not the transport: no answer is typed.
5. **An editor or pager is in front of the agent on the remote at its last
   event.** `front` is false: no answer is typed.
6. **The envelope claims a host, a folder or a question meant to mislead.**
   All three are display text. No path from the envelope is opened, no host
   from it is contacted, and an answer is still only one of the keys above.
7. **The remote hook is older and sends no `host`.** Handled as today.
8. **The remote hook is newer than the daemon.** The daemon ignores fields
   it does not know.
9. **A remote tmux connection closes while its tabs still list.** Its pane
   table is empty; rows fall back to what iTerm2 reports, never to another
   connection's table.
10. **The question does not fit its variable, or is a set.** The hook
    writes none; the card says a question is standing and offers focus.
11. **A question variable outlives its question.** Its `since` no longer
    equals the envelope's `blocked_since`, or the state is not "blocked":
    the daemon shows no question and types nothing.
12. **This machine's host name changes** (a network or VPN can rename a
    Mac). Hook and daemon derive the name the same way, and the daemon
    reads its own at every rebuild, not once at start. A local row whose
    envelope still carries the earlier name reads as remote until its next
    hook event: "unknown", no action, nothing typed.
13. **mosh.** Not supported: it redraws the screen itself and is not
    expected to pass the variable. A pane running it shows as a shell.

## 7. Checks before the build

Run 2026-10-11 against the second Mac, each read back from iTerm2 or from
`ps` there.

1. **The pane table per connection.** Passed. With a remote `tmux -CC`
   attached over et, iTerm2 listed two connections; the remote one answered
   `#{host}` with the remote name and `list-panes` with its own five panes.
   Remote pane `%4` paired with the remote folder and local `%4` with the
   local session, each through its own tab's `tmux_connection_id`. Two
   remote servers at once (one over ssh, one over et) got distinct ids,
   the second suffixed " (2)". The id is an opaque key: iTerm2 names it
   after the gateway's local user and host, not the remote.
2. **The title as a witness.** Passed on this host. A real Claude session
   over ssh read `autoName` "✳ Claude Code" while running; after `/exit`
   and after `kill -9` the remote prompt had repainted it and the marker
   was gone. A local session under a `cs` wrapper and tmux keeps the marker
   in `autoName` too. So an answer also requires `autoName` to start with
   the agent's marker. What is left: a remote shell whose prompt sets no
   title leaves the marker standing after the agent dies, and there the
   key of failure mode 2 can still land, with no Enter.
3. **Two writes back to back.** Passed as an approximation. A process on
   the remote wrote two variables (320 and 508 bytes of base64) in two
   writes to the tty of a real, idle Claude session: 50 of 50 pairs arrived
   whole, and 50 of 50 with a second process redrawing a status row on the
   same tty fifty times a second. Then with the built hook installed on
   the remote and fed the payloads Claude Code sends it, on the tty of a
   real idle session: 50 of 50 questions arrived whole over ssh and 50 of
   50 over et, each paired with its state. A question raised by Claude
   itself there is still unmeasured: over ssh the session was not logged
   in, its login keychain being locked in an ssh session.
4. **`ps -o tpgid=,pgid=`.** Passed. On the remote the agent's two values
   were equal while it held the terminal, and the call took 4 ms; the
   built hook published `front` true for the same session. Not measured
   under a `cs` wrapper there.
5. **The hook's interpreter.** Passed. `python3` is on the remote's path
   (3.14) and `/usr/bin/python3` (3.9) runs without asking to install
   anything.
6. **What rides along.** Read in the code. Every hook event runs
   `emit-state.py`, which on each prompt adds the task-line instructions
   with no condition, so sessions on a machine with no daemon would be told
   to report progress nothing reads. Decided here: the hook adds them only
   where the daemon's endpoint file exists. The mod in `plugin/hooks/`
   finds no link files there and does nothing.
7. **An et pane through a network break.** Not run: the et server there
   runs as root and could not be paused from a user shell. It needs the
   network broken by hand, and is part of the live script's run.

The live run with the built hook (2026-10-11, ssh and et, 19 checks each,
all passing): the card names the remote host and carries nothing read here;
a reply answers 409 with its reason; a carried question shows both labels
and an answer types its one key; with the transport stopped the card reads
"unknown" and an answer is refused with "the connection to <host> is not in
front here"; with the agent killed the prompt repaints the title and an
answer is refused with "the agent's title has gone from the pane". The card
takes its name from the session's title, as a local card does.

## 8. Tests

The failure list in section 6 is the specification. Tests are written one
at a time, each before the code it covers, for the pure rules: the
envelope's fields and the question variable's clipping and pairing; a remote row's state with
and without its transport in front; the answer refusals; the pane table
per connection.

A live script against a second Mac, over ssh and over et, ends with a
recorded result anyone can re-run: a state published there reads on the
card here with its host and folder; the pane collision does not reproduce;
one real question is answered from the card; an answer is refused with the
link suspended.

## 9. Docs

README: remote panes (what a remote card shows and what it cannot do yet),
how a second machine gets the hooks, ssh and Eternal Terminal named as
supported, mosh as not, and that the title check behind an answer depends
on the remote prompt setting a title. The card anatomy figure stays as it is: it draws one local card with a branch, a model and a context figure, which a remote card never has.

## Defaults set in this spec

- `TRANSPORTS`: `ssh`, `et`.
- The variable ceiling stays 512 bytes of base64.
- `cwd` falls back to its last two components.
- The question variable is `user.claudeQuestion`.

## Not in this design

- The relay: an outbound ssh the daemon runs to read the other machine's
  state files. It brings Reply, tasks, subagents, model and context, Codex,
  and sessions with no pane here (an et session whose pane was closed is
  one). Its own spec.
- A daemon on the other machine, or a panel that lists machines.
- Account switching, Remote Control keeping, links and partners across
  machines.
