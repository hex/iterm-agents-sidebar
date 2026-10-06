# An unseen finish, omp's own events, a guarded prompt and a wait command

Four features, designed 2026-10-05. Each is its own branch off `main`, and
Fable and Codex validate the built work before it is merged.

Decided before the build:

- The omp extension is installed by default when omp is on the machine.
  `--no-omp` skips it, `uninstall.sh` removes it, and the title-derived state
  stays as the fallback for a session without it.
- The look of the unseen-finish mark is chosen in a rendered variant round
  before the branch merges.

## 1. A finish nobody has seen (`feat/unseen-finish`)

A card whose turn ended while you were not looking at that session keeps a
mark until you look at it. The macOS banner says so for 5 s; the card says so
until it matters no more.

**Looking at it** is the rule `notify_wanted` already uses: the session is
`active_session_id()` and `app.app_active is True`. Anything else, `None`
included, is not looking.

**The rule**, a pure class beside `Watch` in `alerts.py`:

- `Watch.step` records every turn end it sees in `self.ended` (the sids whose
  `turn_done` was true this reading), whatever the alert settings say. Its
  return value does not change.
- `Unseen.step(ended, looking_at, states)` keeps a set of session ids:
  - a sid in `ended` joins the set unless it is `looking_at`;
  - `looking_at` leaves the set;
  - a sid leaves the set on a new turn (`Watch`'s `new_turn`: working with a
    turn that differs from the one it finished), on `blocked`, on `exited`,
    and when it has gone. Not on any other change: a Stop hook that runs a
    command flips the session to working for a few seconds without a new
    prompt, and a Stop hook like that runs on every turn on the machine this was built on. Clearing on
    that flip would erase every mark, and the flip back to idle is not a new
    turn end, so nothing would set it again. The first test is that
    sequence: working, idle (marked), working with the same turn, idle -- the
    mark is still there.
- `Unseen.seen(sid)` takes one out at once.

**The daemon.** `_rebuild_once` reads `looking_at` in the same rebuild that
ran `Watch.step`, steps `Unseen`, and sets `row["unseen"] = True` on the
matching rows of `self.latest` before the frame is built. `snapshot()` stays
as it is. `act` with `focus` or `bring` calls `Unseen.seen` before it
activates, then rebuilds, so the mark goes with the click and not two seconds
later. A focus made inside iTerm2 is seen by the next poll.

**Not covered, on purpose.** A daemon restart forgets the marks (they are
memory, like `ReturnTrips`). A working turn that went `unknown` before it
ended never counts as finished, as today. The second pane of one conversation
in two panes keeps its own mark.

**The page.** An idle top-level card with `unseen` wears the mark in place of
the `IDLE` outline. It needs a `--badge-room` rule (`test_page_badge_room`).
"Done" already names a finished task and an alert kind, so the word is
decided in the variant round with the look; the code calls it `unseen`.

## 2. omp state from omp's own events (`feat/omp-events`)

The extension plan in `2026-09-21-agent-providers-design.md` ("omp, the first
new agent") stands, with these corrections for omp 18.2.11 (installed here):

- omp sets `OMPCODE=1` (and `CLAUDECODE=1`) in every shell it spawns. The
  extension does nothing when `process.env.OMPCODE === "1"`.
- The guard is `ctx.hasUI === true && ctx.mode === "tui"`, applied before any
  identity is recorded.
- omp already has model, effort, context, cost, jobs and subagents on its card
  from `omp.py`. The extension adds state only: turn start, turn end, a
  waiting approval or `ask`, and the session's end. The title stays the
  fallback, and `omp.read_session` stays the status source either way.
- The extension directory follows omp's own rule: with `OMP_PROFILE` (then
  `PI_PROFILE`) set, `~/<PI_CONFIG_DIR or .omp>/profiles/<profile>/agent`;
  else `PI_CODING_AGENT_DIR` when set; else `~/<PI_CONFIG_DIR or .omp>/agent`.
  The file is `extensions/agents-sidebar.ts`.

**Shape**, from the spec: handlers enqueue a small Claude-shaped payload and
return at once; one worker per root session spawns
`python3 -B <handler> <Event> --agent omp` with the JSON on stdin, one child
at a time (`Bun.spawn`, stdin bytes, stdout/stderr ignored, 500 ms timeout,
SIGKILL, every await caught); the queue is bounded; the last working payload
is resent every 120 s while a turn is open. The event mapping table in the
spec applies unchanged.

The child's environment is minimal but must carry what the handler reads:
`TMUX` (`emit()` wraps the escape for tmux, emit-state.py:809, and every
pane on the machine this was built on is tmux -CC), `TTY` (emit-state.py:777), `HOME` and
`PATH`. Whether a Bun child finds the pane's tty, inside tmux and outside,
is measured, not assumed.

**`emit-state.py --agent omp`**: the pid comes from the payload and must be a
positive integer; the variable is `ompState`; no `describe_subagents`, no
`whisper` and no hook stdout. A waiting approval or `ask` publishes what the
existing fold can carry from the payload (tool name and command summary for
an approval, the question for an `ask`) when the payload maps onto it without
new fold code; otherwise blocked without text, as today. Answer buttons are
not offered on omp cards (the daemon refuses `answer` for omp rows): those
keystrokes were built for Claude Code's and Codex's prompts.

**`sidebar.py`**: watches `user.ompState`; `agent_variable` takes any number
of variables and the newest report wins; a pane with a fresh `ompState` is an
omp row whose state comes from `parse_state` (pid liveness, the 300 s
staleness rule); without it, the title rule as today. `omp.read_session`
keeps filling the status in both cases.

**Install.** `install.sh` writes the extension when `omp` is on PATH or the
omp agent directory exists; `--no-omp` skips, `--omp` insists and fails
without omp. Line 1 is a marker comment; the installer refuses to overwrite
a file without it, writes by rename, and fills in the absolute handler path
(`~/.claude/skills/agents-sidebar/hooks-handlers/emit-state.py`).
`uninstall.sh` removes the file only when it carries the marker.

**Tests.** The extension's pure parts (event to payload, the guard, the
queue's order and overflow) are exported and tested with `bun test` under
`plugin/omp/`. The installer is tested like `codex-hooks.sh`, under a temp
HOME. The `bun test` run is wrapped in a pytest test so `release.sh` runs it;
it skips only when bun is not installed. The live check (a turn, an
approval, an `ask`, an exit, watched on the card) needs a real omp session:
the branch ships a repeatable script for it under `.cs/local/`, shaped like
`.cs/local/e2e_resume.py` (a scratch `/bin/zsh -l` window, omp started with a
short prompt that asks for an approval, `/events` watched for the states),
run by hand before the merge.

## 3. A prompt is refused where it cannot land (`feat/prompt-guard`)

Today the daemon types a prompt into a pane whatever the agent there is
doing: waiting on a question, exited, or no longer the program in front.

**A new verb, `prompt`**: text meant as the agent's next input. The page's
row commands (`/compact`, `/clear`, `/rotate`) and the Reply on a finished
turn's notice use it. `send` stays as raw keys: Cmd+Enter's newline and the
digits a notice's buttons type into a waiting prompt keep working.

**The rule**, pure, `prompt_refusal(row, foreground_pid)` → `None` or a
reason:

- no row: "the session has gone";
- `state == "blocked"`: "it is waiting on you" (answer it first);
- `state == "exited"`: "the agent has exited";
- the agent's pid is known and is not the pane's foreground process-group
  leader: "<program> is in front".

The foreground leader is the process whose pid equals its own pgid and its
tty's foreground pgid, the reading `parse_foreground` already makes. The row
carries the agent pid and tty for this. Measured 2026-10-05 on one working
Claude pane: `ps -o pid,pgid,tpgid` gives claude pid = pgid = tpgid, and its
MCP servers share claude's pgid, so the leader is claude even when iTerm2's
`jobName` names an MCP child. The clause ships only after the same reading
holds for a Codex pane and an omp pane (and a plain-tab pane if one exists);
for any provider where it does not hold, that provider gets the blocked and
exited clauses alone.

**Reporting.** `/action` checks a `prompt` synchronously against the last
rebuild and answers 409 `{"error": reason}`, the shape account switches use.
The page shows the reason on that card for a few seconds. A refused notice
Reply is logged, as a refused notice answer is today.

## 4. Wait on a session from a script (`feat/wait-cli`)

**Discovery.** After `server.start()` the daemon writes
`~/.local/share/agents-sidebar/endpoint.json` = `{"port", "token", "pid"}`,
mode 0600, by rename. The token was only in the Toolbelt URL; on disk it is
readable by the same user, who can already drive iTerm2. That trade is named
in `docs/development.md`.

**The CLI**, `agents-sidebar` at the repo root, stdlib only. `install.sh`
links it into `~/.local/bin` (creating the directory, saying so when it is
not on PATH); `uninstall.sh` removes the link when it points at us.

- `agents-sidebar status [--json]`: one line per agent row (session id, label,
  provider, state).
- `agents-sidebar wait <target> [--until STATE]... [--timeout SECONDS]`:
  returns when the session's state is one of the states asked for, printing
  the row as JSON. STATE is `working`, `blocked`, `idle`, `done`, `unknown` or
  `exited`; `done` is an idle row with `unseen`, and `idle` matches it too.
  The default is `--until blocked --until idle`.
- `<target>`: an iTerm2 session id, `current`, or a label that matches
  exactly one row (more than one is an error that lists them). `current` is
  the part of `$ITERM_SESSION_ID` after the colon only once it is checked
  against the snapshot's `session_id` inside a tmux -CC pane: tmux panes can
  inherit the variable from whoever started the tmux server. If it does not
  hold there, `current` resolves by the caller's tty instead, and the
  snapshot carries each row's tty for that.
- It reads `/events`: the first frame is the current state, so a state that
  already holds returns at once. A heartbeat with `fresh: false` means the
  data is stale, and nothing matches until it is fresh again. A dropped
  stream re-reads `endpoint.json` and reconnects for up to 10 s.
- Exit 0 on a match; 1 with a message on stderr for a timeout, a session that
  closed, or a daemon that is not running; 2 for bad arguments.

Tests reuse `tests/test_integration.py`'s real `Server` on an ephemeral port.

## Order and checks

Each branch is built test first, one behaviour at a time, and passes the
whole suite under the mise Python 3.11. README and the docs are updated in the
branch that changes the behaviour, through the voice profile and Vale. Then
Fable and Codex review each branch; then the unseen mark's variant round; then
the merges, one at a time, with the suite run on each merged tree,
in the order 1, 3, 4, 2 (3 and 4 both touch `VERBS`, `_action` and
`docs/development.md`; 2 and 4 both touch the installers; 2 waits on its live
check).

## Decided after the build (2026-10-05)

- **The unseen mark** is the word NEW on a filled badge in the panel's calm
  green (`--sev-ok`), with the IDLE badge's border and padding. WAITING is no
  longer the panel's only filled badge; it stays the only amber one.
  `Unseen.step` takes `(ended, began, looking_at, states)`: `began` is the set
  where `Watch`'s own `new_turn` held, since a map of states alone cannot tell
  a Stop hook's flip from a new prompt.
- **The prompt guard** refuses on `blocked`, on `exited`, and when the
  agent's process group is not the tty's foreground process group. The
  leader test above failed on real panes (Claude under `cs`, and Codex, are
  not the leader); the group test held on every pane measured.
- **`current`** in the wait command resolves by the caller's terminal, walking
  up its processes to a tty, and never reads `$ITERM_SESSION_ID`: a tmux pane
  can inherit that variable from whoever started the tmux server, and no rule
  tells an inherited id from a true one.
- **The omp hook child** gets 10 s before SIGKILL, not 500 ms: python3 alone
  took 250-464 ms to start under load. Children run one at a time off omp's
  own path, so a slow one delays later state, never omp.
- **The extension's marker** is a line of its own, line 3, below the two
  ABOUTME lines, and the installer compares it whole. A marker inside line 1
  tied the file's ownership to its description, so rewording the description
  would have left every installed file stranded.
