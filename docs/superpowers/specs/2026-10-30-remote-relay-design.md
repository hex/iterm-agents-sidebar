# Remote relay: the daemon reads another machine's state over ssh

Designed 2026-10-30 on `spec/remote-relay`. Slice 2 of remote panes; slice 1
is [state over the pane](2026-10-11-remote-panes-design.md).

Slice 1 shows a card for an agent on another machine from what its pane's
byte stream carries: a state, a question, a host name. The card cannot show
the session's tasks, subagents, model or context, cannot take a reply, and a
session over there with no pane here shows nothing at all. This design gives
the daemon a reading of the other machine's state files, taken over an
outbound ssh, and a way to type a reply there.

Decided (2026-10-30):

- **The daemon polls over ssh** (picked: "Poll over ssh" over one long-lived
  ssh stream per host and over the remote hook pushing here). One ssh
  command per host every few seconds, through the user's own ssh
  configuration and keys. No listener on either machine, no tunnel.
- **A reply goes through tmux on the other machine** (picked: "tmux on the
  remote, over ssh" over typing into the local pane and over a helper the
  hook installs there). A remote session not under tmux gets the refusal it
  gets today.
- **Hosts are the ones local panes reach** (picked: "Hosts seen in panes"
  over a list in settings and over both). A host counts while a pane here
  runs `ssh` or `et` to it. Nothing to configure.
- **The first cut is everything slice 1 deferred**: Reply, tasks,
  subagents, model and context on remote cards, Codex rows from the other
  machine, and sessions there with no pane here.

Kept from slice 1: the daemon stays on 127.0.0.1 with its token; text from
the other machine is clipped, shown as text and never part of a command;
the hooks reach the other machine through the dotfiles manager, pinned to a
release tag.

## 1. What is known before the build

- The hook on any machine files the whole state under
  `~/.claude/agents-sidebar-subagents/<session>.published` whenever the
  variable would not carry it, and the folded document beside it. The
  status line bridge files `~/.claude/agents-sidebar-status/<pid>.json` with
  the model, the context figure and the cost. The task line files
  `~/.claude/agents-sidebar-tasks/<session>.json`. A Codex hook with no
  terminal files its state in the subagents folder too. These are the files
  the daemon reads locally today; the relay reads the same ones over there.
- The envelope names `host`, `pid`, `front` and `cwd`, not the terminal the
  session runs in. tmux names a pane by its tty (`#{pane_tty}`), so the tty
  is the join between a session's state and a pane keys can go to.
- Locally the daemon runs `git`, `ps` and `tmux` as subprocesses with
  argument lists; it has never run `ssh`.
- Section 7 measures what is not known: whether the daemon's process, which
  iTerm2 starts, reaches the ssh agent; what a poll costs; whether a buffer
  paste through ssh carries text whole.

## 2. The hook (`plugin/hooks-handlers/emit-state.py`)

### What it adds

- `tty`: the controlling terminal the hook writes its variable to, as a path
  (`/dev/ttys004`), in the published value. Under tmux that is the pane's
  pts, which is what tmux lists. A hook that found no terminal publishes no
  `tty`.
- Nothing else. The relay reads files the hook already writes.

A hook older than this release publishes no `tty`; its session's card fills
in from the files but refuses a reply: "the session's terminal is not
known".

## 3. The daemon (`sidebar.py`)

### Hosts and destinations

A pane whose foreground job is `ssh` or `et` names a destination in that
job's arguments: the first argument that is not an option, of the shape
`[A-Za-z0-9._-]+(@[A-Za-z0-9._-]+)?` (a host, an alias from the ssh
configuration, or `user@host`), at most 64 characters. Anything else in the
command line is ignored; no option from a pane's command is ever passed on.
A pane that names no destination of that shape relays nothing.

The daemon learns the destination's short host name once, by running
`hostname -s` over it, and keeps the pair. The envelope's `host` is the
short name; that is how a reading pairs with the rows slice 1 already
shows. Two destinations with one short name are one host.

A host is polled while at least one pane reaches it. When the last such
pane closes, the host's reading is kept for 60 seconds, so a card survives
an `et` reconnect, then dropped with its rows.

### The poll

Every 5 seconds per host, one command:

```
ssh -o BatchMode=yes -o ConnectTimeout=5 -o ControlMaster=auto
    -o ControlPath=<daemon's own socket dir>/%C -o ControlPersist=60
    -- <destination> sh -c '<reader>'
```

`<reader>` is a fixed string in the daemon, never built from data. It
writes `tmux list-panes -a -F '#{pane_id} #{pane_tty} #{pane_current_command} #{pane_pid}'`
to a file in a temporary folder, then emits one tar stream of the three
state folders under `~/.claude` and that file, and removes the folder. The
daemon reads the stream with `tarfile`, keeps entries whose names are under
those four paths, under 1 MiB each, and ignores the rest. Nothing is
executed from the stream.

The control socket lives under the daemon's own state folder, mode 700, so
the first connection per host pays for the key exchange and the next
polls reuse it. `BatchMode` means a host that asks for a password or a
passphrase the agent does not hold is a refused host, not a prompt nobody
sees. A failed poll leaves the last reading in place and stamps it; after
30 seconds without a reading the host's rows read "unknown", with "no
reading from <host> for 40 s" in the card's facts line.

### Pairing a reading with rows

- A remote row slice 1 already shows (a local pane whose state names that
  host) takes its session's `.published`, task and status files by the
  envelope's `pid` and session id. The card fills in: tasks, subagents,
  model, context and cost, as a local card does.
- A session in the reading that no local pane shows is a **paneless row**:
  its own card, under the host's rows, with the host mark, the state the
  files say (aged as a local claim is: a working claim with no event for
  five minutes reads "unknown"), and its folder. It has no pane to focus.
  A session whose files say "exited" or whose pid the reading does not list
  among tmux's pane pids and whose last event is older than a day is not
  shown.
- A Codex filing in the reading pairs the way a local one does, by folder
  and start time, against the remote tmux panes the reading lists; one that
  pairs with nothing is a paneless Codex row.

### Reply, over tmux

A reply to a remote row, from the card's field or a notice's reply, goes:

1. The row's `tty` (from the envelope) is looked up in the reading's pane
   list; the pane id (`%12`) and its current command come from there.
   No pane with that tty: refused, "the session on <host> is not in tmux".
2. The pane's current command must be the agent's process name (`claude`,
   `codex`, `node` for a Claude started through a wrapper is accepted when
   the published state is fresher than 30 seconds): otherwise refused,
   "something else is in front of the session on <host>".
3. The published state must be fresher than its own stale bound and not
   "exited": otherwise refused, "the session on <host> has not reported for
   <age>".
4. The daemon runs, over the same control connection:
   `tmux load-buffer -b agents-sidebar -` with the reply text on stdin, then
   `tmux paste-buffer -d -b agents-sidebar -t <pane id>`, then
   `tmux send-keys -t <pane id> Enter`. The text travels on stdin and is
   never a shell argument; the pane id is matched against `%[0-9]+` before
   use.

Answers to a standing question keep slice 1's path (one key into the local
pane under the title check) when the row has a local pane, and take the
tmux path when it has none.

What stays refused: Resume, Link and partner, the context breakdown, and
Remote Control keeping, for the reasons in slice 1.

### Security

- The destination is the only thing from a pane's command that reaches an
  ssh argument list, after the shape check. The reader string is constant.
  Reply text goes on stdin. Pane ids pass a shape check. Nothing in the
  reading is executed or used as a path outside `tarfile`'s member names,
  which are kept only when they start with one of the four expected
  folders and contain no `..`.
- The daemon reads only the three `agents-sidebar-*` folders over there,
  never transcripts, settings or keys.
- A host's text (host name, folders, task titles, question text) goes
  through `plain()` and the limits slice 1 set.
- `BatchMode` keeps every ssh non-interactive. The control socket is in a
  folder only the user can read.

## 4. The page (`page.html`)

- A remote card with a reading shows what a local card shows: tasks,
  subagents, model, context, cost, the task line. The host mark stays.
- A paneless row draws as a card with the host mark and no focus action;
  clicking its name does nothing, and the row says so in its tooltip: "no
  pane here".
- The Reply field appears on a remote card once the daemon can reach the
  session's tmux pane; a refusal shows inline as today.
- A host without a reading for 30 seconds shows the reason in each of its
  cards' facts line.

## 5. The other machine

Nothing new is installed there. The hooks arrive through the dotfiles
manager (slice 1, section 5); `tmux` and `tar` are what the relay needs,
both present on macOS. A session not under tmux shows and fills in but
takes no reply.

## 6. Failure modes, written before the code

1. **The daemon has no agent.** iTerm2 starts the daemon without the
   shell's `SSH_AUTH_SOCK`; every poll is refused. The card says "ssh to
   <host> was refused: no key" and the daemon log carries ssh's stderr.
   Section 7, check 1 measures what the daemon's environment holds; the
   fix, if needed, is reading the socket path from launchd's environment
   or from the user's login shell once at start.
2. **A host is slow or gone.** `ConnectTimeout` bounds the connect;
   the poll's whole run is bounded at 10 seconds by the daemon. A poll
   past its bound is killed and counted as failed. Rows age as described.
3. **Two sessions share a tty.** A shell started claude twice in one pane
   over time: both file states with the same tty; only the one whose pid
   the reading lists among tmux's pane pids is alive, the other is not shown.
4. **The pane list and the files disagree.** A session's tty names a pane
   whose current command is a shell: the agent ended between events. Reply
   refused by step 2.
5. **The reply lands twice.** A paste that succeeded while the ssh
   connection reported a failure: the daemon reads back nothing, so it
   reports the error and does not retry on its own; a retry is the user's
   click. The buffer name is fixed, so a second paste overwrites, never
   appends.
6. **A reading grows.** A machine with many old `.published` files: each
   entry is bounded at 1 MiB and the stream at 16 MiB; past that the
   reading is dropped and the host reads "reading too large".
7. **The same host over two transports.** An `ssh` pane and an `et` pane to
   one host share one poll; the destination of the first pane is used.
8. **A destination that is an alias with a ProxyJump.** ssh resolves it; the
   daemon sees only the short host name. Nothing to do.
9. **A hook older than this release.** No `tty` in the envelope: cards fill
   in, Reply refused with the wording in section 2.

## 7. Checks before the build

1. **The daemon's environment.** From the running daemon, print
   `SSH_AUTH_SOCK` and run `ssh -o BatchMode=yes <second Mac> true`. Decides
   failure mode 1's fix.
2. **Paste through ssh.** Over ssh to the second Mac, `tmux load-buffer -b
   agents-sidebar -` with a three-line text on stdin containing quotes, a
   dollar sign and a backtick, then `paste-buffer` into a pane running
   `cat`: the pane must show the text verbatim.
3. **Poll cost.** 60 polls at 5 seconds with `ControlMaster`: wall time per
   poll and the second Mac's `ssh` process count must stay flat.
4. **The tty under tmux.** On the second Mac, a claude under tmux: the hook's
   published `tty` equals the pane's `#{pane_tty}`.
5. **et and ssh together.** With an `et` pane open to the second Mac, an
   ssh poll to the same host works independently of it.

## 8. Tests

- Destination parsing from a pane's command line: aliases, `user@host`,
  options before the destination, `-J`, a command after the destination, a
  destination of the wrong shape.
- The reader's output through `tarfile`: entries outside the four folders,
  `..` members, oversize members, a tmux list with and without panes.
- Pairing: a local remote row takes its files; a paneless session becomes a
  row; a Codex filing pairs by folder and start.
- Reply refusals, one each, with their wording; the command lists the
  daemon builds for a reply, with the text on stdin and never in argv.
- Ageing: a failed poll keeps the reading; 30 seconds without one reads
  "unknown".
- Live, on the second Mac (the tasks already open): a question raised by
  Claude there answered from here; `front` under a cs wrapper; an `et` pane
  through a network break.

## 9. Docs

- README "Sessions on another machine": what fills in, that a reply needs
  tmux over there, that hosts come from panes, and what a paneless row is.
- docs/usage.md: the poll, its cadence, the "no reading" line, and every
  refusal's wording.
- docs/troubleshooting.md: "ssh was refused: no key", with check 1's fix.

## Defaults set in this spec

- Poll every 5 seconds per host; a reading older than 30 seconds reads
  "unknown"; a host with no pane keeps its reading 60 seconds.
- `ConnectTimeout` 5, whole poll bounded at 10 seconds.
- Entry limit 1 MiB, stream limit 16 MiB.
- Reply accepted only into a pane whose current command is the agent's.

## Not in this design

- A daemon on the other machine, or a panel that lists machines.
- Focusing a paneless row: it would open a connection on the user's behalf.
- Account switching, Remote Control keeping, links and partners across
  machines.
- Hosts named in settings; a host with no pane here is not polled.
