# Teleport: move a cs session to another machine

Designed 2026-10-31 on `spec/teleport`. It builds on
[remote panes](2026-10-11-remote-panes-design.md) (slice 1, built) and
[the remote relay](2026-10-30-remote-relay-design.md) (slice 2, not built).
Nothing here exists yet, and the build waits for the relay.

A session card gains **Move to <host>** in its menu. A move starts the
session on the other Mac through cs, waits until the relay's reading shows
it there, and then ends it here with a typed `/exit`. The order matters. A
start that fails, or never reports, leaves the session running here.

Decided (2026-10-31):

- **Only cs sessions move** (picked: "a cs session, by its name" over
  `claude --resume <id>` over ssh). cs brings a session back by name on any
  machine that has its folder. A conversation id does not travel. Claude
  Code keeps the transcript at `~/.claude/projects/<folder>/<id>.jsonl` on
  the machine that ran it, and `<folder>` is the working directory's
  absolute path with each `/` and `.` written as `-`. The other machine has
  no such file, and a different home path there names a different folder.
- **Start there, confirm, then stop here** (picked: "start, confirm, stop"
  over "stop, then start" and over both at once). Until the other machine
  reports the session, the daemon types nothing here.
- **The session here ends with a typed `/exit`** (picked: "typed `/exit`
  under the prompt guards" over a signal to its process). The text goes
  through the path a card's reply takes, under its refusals. A kill skips
  the session's end hooks, which cs uses to mark its lead as ended and to
  start the waiter that unmounts an encrypted session's vault. The daemon
  never kills the session.
- **The menu holds the item** (picked: "an item in the card's menu" over a
  button on the card's face). Resume is a button on an Exited card's face.
  A live card's actions sit in its right-click menu (`menuFor` in
  `page.html`), so Move goes there, beside `/rotate`.
- **The check before a move runs over the relay's control connection**
  (picked: "a one-shot check over ssh" over a field in the relay's
  reading). The reading carries the three `agents-sidebar-*` folders and the
  tmux pane list, never a session folder, so it cannot say whether the
  folder exists there.

Kept from slices 1 and 2: the daemon stays on 127.0.0.1 with its token.
The daemon clips text from the other machine, shows it as text and never
builds a command from it. Hosts are the ones local panes reach. The hooks
reach the other machine through the dotfiles manager.

## Open, for a decision

Each item names the choices and a recommended default. The build takes the
default unless a decision replaces it.

1. **Where the session runs over there.** Detached: a window of cs's own
   tmux session, started with `cs -spawn <name>`, and the card becomes the
   relay's paneless row, with Reply. A tab here: `ssh -t <destination>` and
   cs there, so the session has a pane here and ends with the connection.
   Both: the detached window, then a tab here attached to it. Recommended
   default: detached. Only that one survives this Mac going to sleep, which
   is the usual reason to move a session.
2. **Which conversation it continues there.** cs keeps one recorded
   conversation per machine. The start takes cs's default answer at its
   resume question, so a session that ran there before resumes the
   conversation that machine recorded, which can be older than this one,
   and a session that never ran there starts fresh. The other choice is a
   fresh start every time. Recommended default: cs's default answer, the
   same thing `cs <name>` typed by hand there does.
3. **Uncommitted changes here.** Refuse a move while `git status` here
   lists any changed path, `.cs/` included, or refuse only for paths outside
   `.cs/` and name the `.cs/` count in the card's line. Measured
   2026-10-31 on this machine: of 100 cs sessions with git, 82 had changed
   paths and 56 had changed paths outside `.cs/`. Recommended default:
   refuse on any changed path, with the count and the first path in the
   card's line. The narrative and a handoff are `.cs/` files, and they are
   the only records that tell the other machine what happened here.
4. **Commits that differ.** Refuse a move unless `HEAD` there equals
   `HEAD` here, or refuse only when this checkout is ahead of its upstream.
   Measured the same day: 27 of the 100 have an upstream, and 6 of those
   are ahead of it. An upstream check says nothing about the 73 with none.
   Recommended default: require equal `HEAD`s. It covers every route a
   folder takes to the other machine, and a different repository there
   fails it too.
5. **Carrying the conversation.** cs keeps handoffs in shared files, and
   it says a handoff from another checkout stays usable. A move could run
   `/rotate` here, commit and push the handoff, pull there and answer `r` at
   cs's question. That is two git writes and a pull on the user's behalf.
   Recommended default: a move carries nothing but the name. The docs give
   the path by hand: `/rotate`, commit, push, then `cs <name>` on the other
   Mac, answering `r`.
6. **A start that never reports.** The window cs opened over there may sit
   at a question. Leave it, or close it. Closing it means typing into it or
   killing what runs in it. Recommended default: leave it, and say on the
   card where it waits.

## 1. What is known before the build

Read in the cs repository, not run:

- `cs <name>` creates a session the first time and resumes it after
  (`README.md`, `docs/commands.md` "Open and resume"). Run on a machine
  that has no session of that name, it creates an empty one. That is why
  the folder check in section 3 comes before any start.
- cs resumes the conversation id in `.cs/local/state`
  (`claude_session_id`). `docs/session-layout.md` says that file is
  machine-local and gitignored: "Each machine binds its own conversation,
  so this must not sync." cs on the other machine never resumes the
  conversation that ran here.
- Shared session files travel through the session's own git repository.
  A folder copied by a file sync carries `.cs/local` too, with that
  machine's conversation id and any `pre-open` script, and cs runs that
  script at open (`docs/session-layout.md`, "Machine-local files").
- A pending handoff is a shared file under `.cs/handoffs/`, and the
  launch answer `r` starts from it (`docs/commands.md`, "Conversation
  rotation and wrap"). cs commits nothing on its own.
- Session names follow `validate_session_name` (`lib/25-deps.sh`): letters,
  digits, `.`, `_` and `-`, with no leading `.` or `-`. A feature worktree
  is `<base>@<task>` (`lib/30-worktree.sh`). Sessions live under
  `~/.claude-sessions/` unless `CS_SESSIONS_ROOT` says otherwise, and an
  adopted session is a link there to the project's own folder.
- `cs -spawn <name>` (`lib/52-spawn.sh`) checks the name, refuses when the
  session is live on that machine or a window of that name exists, needs
  tmux, and opens a window in cs's own tmux session `cs` running
  `cs <name>`. It returns once the window exists. It passes no other flag
  to that `cs`, and it does not check that the session exists.
- cs asks "Continue previous conversation? [Y/n]" when a conversation is
  recorded, shows a menu of answers when a handoff is pending, and asks
  nothing when there is nothing to resume (`lib/75-launch.sh`). With no
  recorded conversation, cs first binds the newest transcript that
  machine holds for the folder, if it has one. A launch on a terminal can
  also ask about a newer cs release, and an encrypted session asks for its
  password.
  A flag that takes the resume question's default without a key is
  approved for a later cs branch and has no name yet. This spec writes it
  as `<resume flag>`.

Read in this repository:

- Resume types `cs .` for a cs session (`sidebar.py`, `resume_command` and
  `Bridge.reopen`), and cs's question then waits for a key.
- Every write into a pane goes through `type_keys`, and a prompt through
  `prompt_refusal` (`sidebar_rules.py`): refused while the session waits on
  you, after it exited, with something in front of it, or for a
  remote row. Mid-turn the agent queues the text.
- An agent that ends with `/exit` leaves no card (`docs/usage.md`,
  "Resuming an exited agent").
- The card's menu holds Details, Untie, `/compact`, `/rotate`, `/clear` and
  Close. `/clear` and Close sit after a hairline and arm on the first click.
- The relay (not built) brings the hosts, the destination's shape check,
  the control connection, the reading every 5 seconds, paneless rows, the
  `tty` in the envelope and Reply over tmux. Its check 1 (does the daemon
  reach the ssh agent) is still open, and every move depends on it.
- The relay spec says `tmux` and `tar` are both present on macOS. `tar` is.
  `tmux` is not part of macOS, so it lives wherever its installer put it,
  and a command run over ssh may not find it. Check 1 in section 7
  measures that for cs and tmux together.

## 2. The hook

Nothing changes in the hook. A move needs `host` and `cwd` (slice 1) and
`tty` (the relay) from the hook on the other machine, at the relay's
release or later.

## 3. The daemon (`sidebar.py`)

### The cs name of a card

A row's cs name comes from its own path on this machine, never from the
page or the other machine. The name is the last part of the path when
the path's parent is the sessions root, or the name of the link there
that resolves to the path (an adopted session). A path anywhere else has
no cs name, even with a `.cs/` folder, because cs's hooks do not treat it
as a session either.

The name must pass cs's own rule and be at most 64 characters. The rule
admits no `@`, so a feature worktree has no cs name here.

### When the item shows

A row carries `move_to`, the short names of the hosts it can move to, when
these hold:

- the row is local, its agent is Claude Code, and it has a cs name;
- at least one host has a reading fresher than 30 seconds.

Nothing else hides the item. The page once hid the housekeeping commands
until a session was idle, and the control was missing at the moment
someone looked for it. A click runs the rest of the checks and says which
one failed.

### The checks, on a click

The page sends the verb `move` with the session id and one short host
name. The daemon looks the host up in its own table and takes the
destination from there. The daemon refuses a host its table does not
hold. The checks run in this order, and the first that fails is the
refusal:

1. The row is still local, Claude Code, with a cs name.
2. Its state is idle. Working: "a turn is under way; move it after the
   turn". Waiting: "it is waiting on you".
3. `prompt_refusal` finds nothing, so `/exit` could land.
4. No subagents and no background shells run: "2 subagents are running
   here". `/exit` ends them.
5. Not linked, not a partner, no Remote Control: "untie it first", "Remote
   Control serves it here". Neither earlier slice carries these across
   machines.
6. No other agent card works in the same folder: "another agent works in
   <name> here".
7. No changed paths here (open decision 3): "3 changed files here, first
   `src/a.py`; commit them first".
8. The host's reading is fresher than 30 seconds: "no reading from <host>
   for 40 s".
9. The one-shot check over there (below) finds the folder: "<host> has no
   session named <name>".
10. `HEAD` there equals `HEAD` here (open decision 4): "<host> is at
    another commit; push here and pull there".

When the reading already shows the session live over there, the move skips
the start and goes to the stop. A second click on a move that started
there finishes it rather than starting it twice.

### The one-shot check

One command over the relay's control connection, with the relay's options
(`BatchMode`, `ConnectTimeout` 5, the daemon's own `ControlPath`) and `--`
before the destination, bounded at 10 seconds. The script is a fixed
string in the daemon, and the cs name is its one argument:

```
sh -c '<check>' teleport <name>
```

`<check>` moves into `${CS_SESSIONS_ROOT:-$HOME/.claude-sessions}/$1`.
When that fails or the folder has no `.cs/`, it prints `missing` and stops.
Otherwise it prints three lines: `pwd -P`, `git rev-parse HEAD` and the
number of lines `git status --porcelain` prints there.

The daemon parses the answer and executes none of it. The first line is
`missing` or an absolute path of at most 1024 characters. The second is 40
or 64 hex digits. The third is a count. The daemon refuses anything else:
"<host> answered the check with something unexpected". It keeps the path
only to compare with the `cwd` the other machine's hook reports. The
`HEAD` is only compared. A count above zero there goes into the card's
line after a move, since that session starts on top of those changes.

### The start

The same connection runs a second fixed script with the same one argument.
It runs `cs -spawn <name> <resume flag>` (open decision 1's default),
through the path to cs that check 1 in section 7 settles. `cs -spawn`
takes no such flag today, so cs owes two things here: the flag, and
`-spawn` handing it to the `cs` its window runs, as an argument or as an
environment value the window carries. Without both, the spawned `cs`
stops at its resume question (failure mode 5). A non-zero
exit is a refusal that quotes cs's first line of error, clipped and shown
as text: "cs on <host> refused: Session <name> is already live".

Before the start, the daemon notes the host's last reading. It then waits,
for at most 60 seconds, for a later reading that holds a `.published`
filing whose `cwd` equals the check's path, that differs from the one in
the noted reading or that the noted reading lacks, and whose state is not
"exited". The relay's own rule then pairs it with a tmux pane. The
comparison is between two readings of the same machine, so the two Macs'
clocks never meet.

A start whose ssh call fails after the window may already exist (the
connection drops) is not taken as failed. The daemon goes on waiting for
the report, and never runs the start again on its own.

### The stop

Once the other machine reports, the daemon types `/exit` and Enter into the
pane here, through `act`'s prompt path, after the same `prompt_refusal` and
the idle check again. If either refuses now, the daemon types nothing,
and the card says that the session runs in both places. The daemon then
waits up to 15 seconds for the session here to end, which takes its card
away.

### The move's state

A move is one of these steps, held per session in the daemon's memory:

| Step | The card's line |
|---|---|
| checking | Moving to <host>: checking |
| starting | Moving to <host>: starting cs there |
| waiting | Moving to <host>: waiting for it to report (12 s) |
| ending | Moving to <host>: ending it here |
| refused | Not moved to <host>: <reason> |
| both | <name> runs on <host> and here: <reason> |

The step travels in the row as `move`. A finished move leaves no state: the
card here leaves, and the relay shows the session under the host's rows.
`refused` and `both` stay on the card for 30 seconds. While a move is under
way, another `move` for the same session does nothing.

### Security

- Two values reach an ssh argument list: the destination, from the daemon's
  own host table after the relay's shape check, and the cs name, from the
  row's local path after cs's rule. The scripts are constants. `/exit` is a
  constant.
- ssh sends the remote command as one string, its parts joined by spaces,
  and the login shell over there parses that string again. That makes the
  cs name a word in a shell command on the other machine. cs's rule
  admits letters, digits, `.`, `_` and `-`, with no leading `.` or `-`. A
  word of those has nothing a shell expands, splits on or reads as an
  option. The name comes after the script as its own word, never inside it.
- The daemon executes nothing from the other machine. It parses the
  check's three lines by shape and compares them. It clips cs's error line
  and shows it as text. The reading stays the relay's data.
- The page sends a host's short name and a session id, never a destination
  or a command.

What remains open, each with its fix, for a decision:

1. **The daemon's ssh can do whatever the key can do there.** The shape
   check in the daemon is the one guard between data and a shell on the
   other machine. Fix: a key of the daemon's own, limited over there to a
   fixed command that takes only `check <name>` and `start <name>`, with no
   terminal and no forwarding. That puts a file on the other machine, which
   slice 1 kept from doing.
2. **The other machine decides when the session here ends.** A process
   there that writes a changed `.published` with the right `cwd` makes the
   daemon type `/exit` here. The session ends with its conversation saved,
   and Past sessions or `cs <name>` brings it back. Fix: a second witness.
   The report must come from a pane of the window cs opened, matched by the
   window id cs prints and a `#{window_id}` field the relay's reader would
   add to its pane list.
3. **A folder that arrived by a file sync runs its `pre-open` at the
   start.** A move then runs that script over there. Fix: the check also
   reports whether `.cs/local/pre-open` exists there, and the move refuses
   it, or names it in the card's line.
4. **Two machines with one short name.** The relay counts them as one host,
   so a move can land on the other one. Fix: the item's hint names the
   destination as the pane gave it (`user@host`).

## 4. The page (`page.html`)

- One item per host in `move_to`, labelled **Move to <host>**, in the card's
  menu after `/rotate`, in the group after the hairline with `/clear` and
  Close. It arms on the first click, as they do. Its hint: "start <name>
  on <host> through cs, then type /exit here; this conversation stays on
  this Mac".
- During a move, the card shows its step's line (section 3) under the card,
  where a refused command's line sits today.
- On a refusal, the line is in the warning colour and stays 30 seconds.
- After a move, the card here leaves as after any `/exit`, and the session
  shows under the host's rows as a paneless row with the host mark.
- The card's face gains no mark, colour or row.

## 5. The other machine

It needs, beyond what the relay needs:

- cs, at a release whose `cs -spawn` carries `<resume flag>` to the `cs`
  it starts, found by a command run over ssh;
- the session's folder, from a git clone of the session's repository, not a
  file sync;
- tmux, which `cs -spawn` needs.

This repository installs nothing there beyond the hooks.

### Before the build

- The relay (slice 2), built and live, with its check 1 settled: the
  daemon reaches the ssh agent.
- The cs resume flag, named and released, and honoured by `cs -spawn`.
  The request to cs so far covers the flag for Resume here, not `-spawn`.
- The hooks on the other machine through the dotfiles manager, at the
  relay's release or later.
- cs and tmux on the other machine, found by a command run over ssh
  (section 7, check 1).

## 6. Failure modes, written before the code

1. **ssh refuses the connection.** The daemon has no agent (relay failure
   mode 1). The check fails, nothing starts: "ssh to <host> was refused:
   no key".
2. **cs or tmux is not found over ssh.** A command run over ssh reads fewer
   startup files than a terminal does. The check or the start fails with
   the shell's line: "cs on <host> refused: cs: not found". Check 1.
3. **No folder there, or a different sessions root.** "<host> has no
   session named <name>". The start never runs, so `cs -spawn` never
   creates an empty session over there. A root set only in an interactive
   startup file reads as missing.
4. **Another commit, or another repository.** `HEAD`s differ: "<host> is
   at another commit; push here and pull there".
5. **cs waits on a question there.** The resume question (before cs has
   the flag), its offer of a newer release, an encrypted session's
   password, a first-run trust question. Nothing reports within 60
   seconds: "Not moved to <host>: it did not report in 60 s; cs may be
   waiting in tmux session cs there". The session stays here.
6. **Already live there.** Seen in the reading: the move skips the start and
   ends the session here. Live by cs's lock but not in the reading (no
   hook there): `cs -spawn` refuses and the card quotes it.
7. **A stale filing reads as up.** A `.published` from an earlier run there
   names the same folder. The noted reading holds it unchanged, so it does
   not count.
8. **The session here moves on between the start and the stop.** A prompt
   arrives, a question stands, an editor comes to the front. The daemon
   refuses `/exit` and types nothing: "<name> runs on <host> and here: a
   turn is under way". Ending one of them is the user's call.
9. **`/exit` lands and the session does not end.** After 15 seconds: "<name>
   runs on <host> and here: /exit did not end it". No retry, no kill.
10. **The connection drops after the start.** ssh reports a failure that
    does not prove one. The daemon keeps waiting for the report and never
    starts again on its own.
11. **A second click during a move.** Nothing happens. A click after a move
    stopped between its start and its stop finds the session live there
    and goes straight to the stop.
12. **The daemon restarts mid-move.** The daemon forgets the move. If the
    start had run, both sessions run, and the panel shows both, each with
    its own card. The daemon types nothing here.
13. **The hook there is older than the relay.** No `cwd` or `tty` arrives,
    nothing reports: failure mode 5's line.
14. **A move refused here leaves nothing there.** Every local check and the
    one-shot check run before the start, and the check writes nothing.

## 7. Checks before the build

On the second Mac, with the relay built:

1. **What a command over ssh finds.** `ssh -o BatchMode=yes <second Mac>
   'command -v cs tmux git'`. Decides whether the scripts name cs and tmux
   by their install paths. It bears on the relay's reader, which calls
   tmux, as well.
2. **`cs -spawn` over ssh.** With no terminal on the ssh side, it returns
   once the window exists, and it exits non-zero with its reason when the
   session is live there. Whether the resume question and the release offer
   appear in that window.
3. **Time to report.** 20 starts of a session that ran there before, timed
   from the start's return to the first reading that shows it. The slowest
   sets the 60-second bound.
4. **The `cwd` there.** The hook's `cwd` for a cs session there equals `pwd
   -P` of its folder, for an ordinary session and for an adopted one.
5. **The name through ssh.** A session named `a.b_c-1` reaches cs over there
   unchanged.
6. **`/exit` through the prompt path.** Typed by the daemon into an idle cs
   session here: the session ends, cs's end hook runs, and the card leaves
   within 15 seconds.
7. **Reply after a move.** The paneless row of a moved session takes a
   reply through the relay's tmux path.

## 8. Tests

Tests cover the pure rules, written one at a time, each before the code it
covers. None of them mocks ssh.

- The cs name of a row: a folder under the sessions root, a link there, a
  folder elsewhere with `.cs/`, a feature worktree.
- The name's shape: names cs takes, and names refused for a leading `.` or
  `-`, `@`, a space, `$`, a quote, a backtick, `~`, `*`, 65 characters,
  empty.
- `move_to`: local and remote rows, Claude Code and other agents, no host,
  a host whose reading is 31 seconds old, two hosts.
- Each local refusal, one test each, with its wording.
- The one-shot check's answer: `missing`, three good lines, a short `HEAD`,
  a word for the count, a fourth line, an answer past its limit.
- The report rule: a changed filing for the path, an unchanged one, one
  the earlier reading lacks, one for another path, one that says "exited".
- The steps: each failure leads to its line, and a move whose session is
  already live there skips the start.
- The command lists the daemon builds: the script constant, the name as the
  last word and only there, `--` before the destination.

A live run on the second Mac ends with a recorded result anyone can re-run:
one move that lands, one refused for changed files, one start that waits on
cs's question and leaves the session here.

## 9. Docs

- README, "Sessions on another machine": the item, that it moves a cs
  session by its name, and that the conversation stays here.
- docs/usage.md, "Sessions on another machine": what a move checks, each
  refusal's wording, the card's lines, and the path by hand that carries a
  handoff. "Past sessions" names `<resume flag>` once it exists.
- docs/integrations.md, "Hooks on a second machine": cs on the other Mac,
  and session folders by git clone, not by file sync.
- docs/troubleshooting.md: a start that did not report, and where cs then
  waits; cs not found over ssh.
- docs/development.md: the `move` verb, which `tests/test_docs.py` requires
  of every verb.

## Defaults set in this spec

- A move waits 60 seconds for the report and 15 seconds for the session
  here to end.
- The one-shot check stops after 10 seconds, as a poll does.
- A host counts for `move_to` while its reading is fresher than 30 seconds.
- A cs name is at most 64 characters.
- A refusal's line stays 30 seconds.

## Not in this design

- Moving a session from another machine to this one, or between two other
  machines.
- Claude Code outside cs, Codex and omp: none of them comes back by name on
  another machine.
- Feature worktrees (`<base>@<task>`).
- Any commit, push or pull on either machine.
- Moving a linked session, a partner, or a session Remote Control serves.
- A setting that names hosts. A host with no pane here has no reading, so
  no session moves to it.
