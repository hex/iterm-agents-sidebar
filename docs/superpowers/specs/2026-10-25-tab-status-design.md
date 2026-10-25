# The status under a tab, written by the panel: design

Written 2026-10-25. Status: agreed 2026-10-25; implemented 2026-10-25 (see Implementation reconciliation).

## Problem

iTerm2 3.7.6 gives every session a status indicator under its tab title: a
word, a coloured dot, a detail line and a background-task count. It is set and
read by two RPC functions, `iterm2.set_session_status` and
`iterm2.get_session_status`, callable over the daemon's existing connection
with no subprocess. iTerm2's own Claude Code integration writes the same
indicator from a `cc-status` hook on ten Claude Code events in
`~/.claude/settings.json`: Claude sessions only, about 0.37 s per hook run,
synchronous on every tool call. A probe showed the next `cc-status` run
overwrites whatever the daemon set, so two writers on one session fight.

The daemon already knows every agent session's state, question, intent and
background work, for Claude, Codex and omp, local and remote. This makes it
the one writer of the indicator, in the panel's own words and colours, and
takes `cc-status` out with consent.

Verified by probe (2026-10-24):

- The status word is free text: "needs you" is accepted and shown as given.
- Argument names: `session_id`, `status`, `detail`, `dot_color`,
  `text_color`, `background_tasks` (int). `expires_on`, `then_*`,
  `turn_open`, `if_turn_open`, `if_background_tasks` exist in the CLI and are
  accepted; unused here.
- Clearing: `status: "", detail: "", dot_color: "", text_color: "",
  background_tasks: 0` in one call resets every field to null or zero. A
  colour survives a status change unless rewritten.
- `iterm2.util.invocation_string(name, args)` in the bundled Python package
  builds the call and escapes `\` and `"`; `\(` arrives inert.
- `cc-status`'s palette, from the binary: `#ff9500` (seen live as working),
  `#00d75f`, `#888888`, `#ff3b30`, `#5f87ff`. Which word takes which of the
  other four is unverified; only the set matters.
- The `iterm2` package (2.30) has no wrapper for these functions.

Constraints the shape honours:

- The rebuild owns all per-poll work. `marks.Marker` is the house pattern:
  pure `wanted` and `plan`, a `have` dict, a `step` that logs and never
  raises, a startup sweep, fakes in tests with no `iterm2` import.
- Fail loud. A tab that still says working after the daemon or the agent
  has gone is plausible old data.
- Status only while it would change what the reader does; no decoration.
- `statusline.py` is the one reader, backup and atomic writer of
  `~/.claude/settings.json`; `install.sh` runs it by name.
- A new settings key takes its default on every install (`_clean` fills
  missing keys from the defaults).

## Usage (what the person sees)

docs/usage.md gains a section, "The status under a tab":

> An agent's tab shows what its session is doing under the title, in the
> panel's words:
>
> | The card says | Under the tab | Dot and text | Detail |
> |---|---|---|---|
> | Working | `working` | iTerm2's own working orange | what the agent says it is doing, when it says |
> | Needs you | `needs you` | the panel's amber | the question, or the tool asking for permission, else what it was doing |
> | Done (finished while you looked elsewhere) | `done` | the panel's done green | nothing |
> | Idle, exited, no report | nothing | nothing | nothing |
>
> Running subagents and background shells are counted beside the word.
> Teammates' and worktrees' panes show working and needs you; only a card
> shows done, as on the panel. Remote sessions' tabs are written like local
> ones.
>
> Settings > Terminal > **Status under the tab title** turns this on and off
> (default on). With it off, or when the panel stops, the words are taken
> back.
>
> iTerm2's Claude Code integration writes the same line from hooks of its
> own. While those hooks are in `~/.claude/settings.json`, the panel leaves
> Claude tabs to them and writes only Codex, omp and remote tabs. The foot
> then offers **Hand over**, which removes iTerm2's hook entries (a copy of
> the file is kept beside it as `settings.json.before-tab-status`), or **Not
> now**. Settings > Rows > **Offer to take the tab status from iTerm2**
> brings the offer back. To put iTerm2's hooks back, restore the copy or run
> iTerm2's Claude Code integration setup again.
>
> The line needs iTerm2 3.7.6 or later. On an older iTerm2 the setting says
> so and nothing is written.

### Call sites

The rebuild, one line after `marks.step`:

```python
hooks = statusline.cc_status(CLAUDE_SETTINGS)          # "present" | "absent" | "unreadable"
await self.status.step(self.app, agent_rows, self.unseen.sids, settings, hooks, self.log)
if (note := tabstatus.notice(settings, hooks, self.status.available)):
    self.latest["tab_status"] = note                   # "contested" | "unavailable"
```

Wiring and stop, in `main`:

```python
bridge.status = tabstatus.Writer(
    invoke=lambda name, args: iterm2.async_invoke_function(
        connection, iterm2.util.invocation_string(name, args)))
hand_over_fn=lambda: statusline.drop_cc_status(CLAUDE_SETTINGS)       # POST /tab-status
loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(bridge.stop()))
```

`Bridge.stop` awaits `self.status.clear_all(self.log)` under a two-second
bound, then stops the loop.

A test:

```python
def test_a_card_that_needs_you_shows_its_question_and_idle_takes_it_back():
    app, calls, logged = App(Session("a")), [], []
    w = tabstatus.Writer(invoke=recorder(calls))
    row = dict(card("a", "blocked"), question={"question": "Ship it?", "options": ["Yes", "No"]})
    run(w, app, [row], set(), ON, "absent", logged.append)
    run(w, app, [card("a", "idle")], set(), ON, "absent", logged.append)
    assert calls[1:] == [
        ("iterm2.set_session_status", {"session_id": "a", "status": "needs you", "detail": "Ship it?",
                                       "dot_color": "#ff9f0a", "text_color": "#ff9f0a", "background_tasks": 0}),
        ("iterm2.set_session_status", {"session_id": "a", "status": "", "detail": "",
                                       "dot_color": "", "text_color": "", "background_tasks": 0}),
    ]   # calls[0] is the startup adopt read
    assert logged == []
```

The fake `invoke` takes `(name, args)` and returns the dict
`get_session_status` would. Tests never build or parse an invocation string.

## Shape

### Module map

| File | Change |
|---|---|
| `tabstatus.py` (new) | `Status`, `FACES`, `status_of`, `one_line`, `wanted`, `plan`, `notice`, `Writer`. Owns what the indicator says and when it is written. |
| `statusline.py` | `cc_status(path)` and `drop_cc_status(path)` beside `state` and `install`, reusing `_read` and the atomic replace. ABOUTME widened to Claude Code's settings.json for the panel. |
| `sidebar.py` | `DEFAULT_SETTINGS` gains `tab_status: True`, `offer_tab_status: True`. The rebuild's three lines. `main` wires the writer, `POST /tab-status`, SIGTERM. `Bridge.stop`. |
| `page.html` | `SETTING_ROWS`: new `{head: "Terminal"}` after Finished with `{k: "tab_status", label: "Status under the tab title"}`; its note reads "Needs iTerm2 3.7.6" while `LATEST.tab_status === "unavailable"`. `offer_tab_status` beside `offer_statusline`. The foot offer reuses the statusline offer's component: text, Hand over, Not now. |
| `docs/usage.md`, `README.md` | The section above; one feature line. |
| `tests/test_tabstatus.py` (new), `tests/test_statusline.py` | Mapping, plan, writer with fakes, adopt, yield, release, hand-over sweep, unavailable; `cc_status` and `drop_cc_status` cases incl. non-JSON refusal and the backup. |

### Types

```python
# tabstatus.py
Word = Literal["working", "needs you", "done"]

#: The one table of words and colours. Dark-theme panel values, as the tab
#: colour already is (the tab bar cannot follow the panel's theme):
#: working = iTerm2's own working orange, one unit off cc-status's #ff9500 so the
#: signature still tells our dot from its; needs you = --blocked-border;
#: done = --sev-ok via marks.TAB_RGB.
FACES: dict[Word, str] = {"working": "#ff9501", "needs you": "#ff9f0a", "done": "#30d158"}
#: A dot in one of these colours was written by this daemon: cc-status uses none of them.
SIGNATURE = frozenset(FACES.values())
#: cc-status's own palette, for the hand-over sweep.
CC_PALETTE = frozenset({"#ff9500", "#00d75f", "#888888", "#ff3b30", "#5f87ff"})
DETAIL_MOST = 60

@dataclass(frozen=True)
class Status:
    word: Word
    detail: str          # one clean clipped line, only via one_line
    background: int      # running subagents + background shells
    def args(self, session_id) -> dict: ...   # dot and text share FACES[word]

def clear_args(session_id) -> dict: ...       # every field set, as probed
def one_line(text) -> str: ...                # whitespace runs to one space, controls dropped, clipped with an ellipsis

def status_of(row, unseen) -> Status | None:
    """working -> "working", detail row["doing"]
    blocked -> "needs you", detail the AskUserQuestion's question, else a
               permission gate's "tool: summary", else row["doing"], else ""
    idle, in unseen, depth 0 -> "done", no detail
    anything else -> None
    background = row.get("agents", 0) + len(row.get("shells", []))"""

def wanted(rows, unseen, settings, hooks) -> tuple[dict[str, Status], set[str]]:
    """(sid -> Status for every owned row with something to show, the sids yielded).
    Off -> ({}, set()). A local Claude row (provider claude, no host) is yielded
    while hooks is "present" or "unreadable". Codex, omp and remote rows are owned."""

@dataclass(frozen=True)
class Plan:
    writes: dict[str, Status]; clears: set[str]; releases: set[str]

def plan(want, have, yielded) -> Plan: ...
def notice(settings, hooks, available) -> Literal["contested", "unavailable"] | None: ...

class Writer:
    def __init__(self, invoke): ...   # have: dict[str, Status | None]; available; adopted; failing; last_hooks
    async def step(self, app, rows, unseen, settings, hooks, log): ...
    async def adopt(self, app, yielded, log): ...
    async def sweep_handed_over(self, app, sids, log): ...
    async def clear_all(self, log): ...
```

```python
# statusline.py
def cc_status(settings_path) -> Literal["present", "absent", "unreadable"]:
    """Any hook entry whose command's basename is cc-status (the path is a per-machine symlink)."""
def drop_cc_status(settings_path) -> int:
    """Remove those entries, drop groups and events left empty, back up as
    settings.json.before-tab-status, replace atomically. -> entries removed.
    ValueError, nothing written, when the file is not a JSON object."""
```

### Data flow

Agent rows, Unseen, settings and the hook state go into `wanted`; `plan`
compares the result with `have` and yields writes, clears and releases; the
writer sends one `invoke` per change. A steady panel sends nothing. Startup
costs one `get_session_status` per session (adopt). A hand-over costs one
read per formerly yielded Claude session, once.

### Load-bearing decision: no tab carries the daemon's colours unless the daemon owns that session now

Diffing against `have` is correct only if nobody else writes those
sessions. The dot colour says who wrote last, and enforces all of it:

1. **Yield.** While `cc-status` is present, or the file cannot be read, local
   Claude rows are never written. Codex, omp and remote rows are always
   owned: `cc-status` cannot reach them.
2. **Release only what is still ours.** When a row becomes yielded the
   writer reads it once and clears it only if the dot is in `SIGNATURE`;
   either way it leaves `have`.
3. **Adopt by signature.** At start, a `SIGNATURE` dot on an owned session
   enters `have` and the first plan corrects or clears it; on a yielded
   session it is cleared. A dot in any other palette is never touched.
4. **Hand-over sweep.** On the present-to-absent transition of the hooks,
   the writer reads each local Claude session once and clears a status whose
   dot is in `CC_PALETTE`, so the leftover `idle` and `done` words do not
   stay for good. (Graft from the fable and sonnet candidates; the opus base
   left those words standing.)
5. **Hand-over is explicit.** The writer never removes `cc-status` itself.
   The foot offers it; detection flips the yield on the next poll. If iTerm2
   puts the hooks back, the yield and the offer return and nothing fights.

### Other decisions

- Own owner beside `Marker`, not a third channel: a channel is a set of sids
  over profile fields with a restore; this is a value per sid over an RPC
  with nothing to restore, covering every state. Same pattern, so one reader
  reads both.
- Nothing at rest: idle, exited and unknown clear the line (status only when
  actionable; a tab never asserts what nobody vouches for). Done is the one
  resting word and lasts until the pane is looked at, as Unseen decides.
- Working wears iTerm2's own orange, as cc-status paints it, written as
  `#ff9501`: indistinguishable on screen, and one unit off `#ff9500` so the
  signature still tells the daemon's dot from `cc-status`'s.
- Detail goes through `one_line` only; the wire string is built in one place
  by the library that defines its grammar.
- Idempotent: a second `step` on one reading sends nothing; a crash between
  a write and `have` is repaired by adopt at the next start.
- Failures: a failed call leaves `have` as it was, logs once per session
  until it succeeds, and retries next reading. Only an unknown-function
  answer, or a start where every read failed, turns the writer off; the
  setting row then says why.
- Stop: SIGTERM runs `clear_all`; execv restart, SIGKILL and crash are
  covered by adopt at the next start.
- `tab_status` defaults on: a new key, so every install gets it, including
  machines without `cc-status` where Codex and omp tabs gain the line at once.

## Synthesis decision

Four candidates (opus, fable, sonnet, haiku) and an opus judge. Base: opus
(17/18): its clear sends all five fields as the probe requires, encodes
through the library, has the row shapes right, keeps the yield policy inside
the writer, covers stop, crash and old iTerm2. Grafted: the hand-over sweep
of `cc-status`'s leftover words (fable, sonnet); a test that `FACES` matches
page.html's tokens and a detail-injection test asserted on the args dict
(sonnet); log-once for two rows on one session (fable). Rejected: fable's
enum-word premise and hand-built wire string; haiku's absent yield rule and
default-off on a misread of the settings trap; sonnet's leaving a dead
daemon's status until the next start without a stop handler. Changed from
the base by the orchestrator: the blocked word is the panel's "needs you"
(free text is verified), and working wears iTerm2's orange.

## Tradeoffs accepted

- Three hex values and three words are hand-synced with page.html; a test
  pins them. Done derives from `marks.TAB_RGB`.
- Dark-theme colours on a light tab bar, as `marks.TAB_RGB` already is: the
  RPC takes one colour.
- `statusline.py` edits two things under a name that says one, for one
  reader, one backup and one atomic replace.
- A status overwritten by an unknown writer stays wrong until the session's
  next state change; the alternative is N reads per poll.
- While `cc-status` is installed, Claude tabs keep iTerm2's words and
  palette and the others show the panel's, until the hand-over.
- A two-second bound on SIGTERM for the clear.

## Alternatives considered

- A third `Marker` channel: same surface, hides nothing new, and makes
  `CHANNELS` lie about what a channel is.
- The sidebar's own Claude hooks writing the line: keeps the per-hook cost
  on every tool call, covers Claude only, duplicates the state model.
- Read back and repair every session every poll: N RPCs per poll and an
  active fight with `cc-status` that never converges.
- Leave Claude tabs to `cc-status` for good: no question text, no panel
  colours, no done-only-when-unseen on Claude tabs; not one writer.

## Open questions and risks

- Does a running Claude Code session drop a hook removed from settings.json
  at once, or only at its next start? Claude Code snapshots hook config at
  startup, so the expectation is: after Hand over, already-running Claude
  sessions keep writing until restarted, and their tabs fight with the daemon
  for that long. Measure live before the button ships; if confirmed, the
  offer's text says to restart open Claude sessions.
- Does iTerm2 re-add the hooks after they are removed while
  `NoSyncClaudeCodeHooksInstalled` stays 1? Detection covers it either way;
  verify live after the first removal.
- Can a remote host's `cc-status` reach the local iTerm2 (through the ssh
  integration)? If it can, remote Claude rows need the yield too.
- `#ff9f0a` and `cc-status`'s `#ff9500` differ by a few units; the signature
  is exact-match, so it holds, but it is fragile if either palette moves.

## Implementation reconciliation

Decided at the checkpoint (2026-10-25): the waiting word is "needs you";
working wears iTerm2's orange (`#ff9501`, see Other decisions); `mark_tab`
(the green tab colour while unseen) is retired, its setting and channel
removed, since the done dot says the same per session; the badge mark
stays. `cc-status` was removed from this machine's settings.json by hand
the same day (backup `settings.json.before-tab-status`); the foot's Hand
over offer still ships for other machines.

Where the build departed from the text above, and why:

- **cc-status words are taken over at start too, not only on the
  transition.** On this machine the hooks were gone before the daemon
  started, so the present-to-absent transition never happens and the
  `idle` and `done` words cc-status left would stay for good. `adopt` now
  also puts a `CC_PALETTE` dot on an owned session into `have` (as None)
  while the setting is on and the hooks are absent; the first plan clears
  or overwrites it. The hand-over sweep runs whenever local Claude tabs
  become the daemon's (hooks gone, or the setting turned on with them
  gone), and it takes those words into `have` the same way rather than
  clearing them itself, so a working tab is overwritten and an idle one
  cleared through one path. A cc-status dot on a yielded tab, or with the
  setting off, is never touched.
- **Done is a literal, not derived from `marks.TAB_RGB`.** Retiring
  `mark_tab` left `TAB_RGB` with no use in marks.py, so it went with the
  tab channel. `FACES["done"]` is `#30d158`, and a test pins it, with
  needs you, to page.html's dark `--sev-ok` and `--blocked-border`, and
  checks `SIGNATURE` and `CC_PALETTE` are disjoint.
- **Two rows on one session: the word that most needs the reader wins**
  (needs you, then working, then done), and no collision is logged. Two
  rows share a session in every plain tmux pane holding several agents,
  so a log line would be noise, and the first row could hide a question.
  The log-once rule stays for failing calls, per session.
- **The yield test reads the row as it is:** a local Claude row has no
  `provider` key and no `host` (snapshot rows name only non-Claude
  providers, and Codex is `openai`).
- **The writer is built in `Bridge.__init__`**, calling
  `Bridge.invoke_function`, which imports iterm2 on first use and encodes
  through `iterm2.util.invocation_string`, rather than a lambda in `main`:
  every test bridge then carries a writer, as it carries a `Marker`.
- **The stop exits through `loop.call_soon(sys.exit, 0)`.** Raising
  SystemExit inside the stop task did end `iterm2.run_forever` with exit
  code 0, but printed "Task exception was never retrieved" with a
  traceback; from a plain callback it exits 0 cleanly. Both measured with
  a throwaway `run_forever` script that sent itself SIGTERM.
- **"Unavailable" is iTerm2's own answer text.** An unknown function
  answers `FAILED: No function registered for invocation ...` (probed
  live); `No such session` and timeouts are per-session failures.
- **Worktrees show done.** The usage text grouped worktrees with
  teammates as never showing done, but a docked worktree is a card of its
  own (depth 0), as for the badge; only a teammate's pane never says done.
- **The two foot offers share one component**: a table of offers and one
  painter, the statusline offer moved onto it unchanged in behaviour.
- **The settings figure** picks its right column by the Rows card's title,
  not by position, since the Terminal card moved it.
- **The restart note is from Claude Code's documentation, not measured.**
  Claude Code takes its hooks at session start, so the hand-over's done
  text and troubleshooting say an open Claude session keeps running
  cc-status until it restarts. Not checked against a live session.

Verified live on iTerm2 3.7.6 (`tests/live/tab_status_check.py`, a
throwaway window, the writer shown only its own sessions and calling
through the daemon's own `Bridge.invoke_function`): working with
its count, needs you with a detail holding `"`, `\` and `\(session.name)`
read back literally, done, idle clearing all five fields, `clear_all`, and
a second writer's start clearing the first one's word. The tab bar shows
the word and the dot; the detail line was not visible in the tab bar in
the screenshot.
