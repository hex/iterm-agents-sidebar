# Linked cards: one session hands its result to another

Designed 2026-10-07 on `feat/link-cards`, Claude's route reworked 2026-10-08
around a mod. Builds on the drag order and the drag ghost
(`2026-10-07-drag-order-design.md`).

Hold a dragged card over another card and a link draws between them; let go
and the first session (A) writes up its latest result and sends it to the
second (B), which starts working on it. One message, once. Nothing relays
back on its own.

Decided before the build:

- **A's agent writes the message**, not the panel and not you. The panel only
  tells A to send its latest result to B.
- **B starts working on it** when it arrives, where B's agent allows that.
- **The gesture is a hover during a drag**: the ghost held over a card links;
  moving on reorders as before. The link's look is picked in a rendered
  variant round.
- **Claude, Codex and omp** all take part, each by its own route (below).
- **Nothing is typed into a terminal.** A typed line would join whatever you
  had half-typed there, and nothing can see a draft (memory
  `project_question-sets-and-pane-input`). Every route below is a mod's
  prompt or hook context.
- **Claude sessions take part through a mod**: a module in the agents-sidebar
  plugin, running inside each Claude session. It starts the turn in A and in
  B itself, so nothing goes through Claude Code's cross-session inbox and no
  setting changes. `crossSessionInbound: "accept"` was rejected: it lets every
  local session and process start work in a bypass session, with no way to
  accept only some (Claude Code docs, cross-session messaging).
- **Both linked Claude sessions show the link** in a band on the right above
  the prompt (variant C of a live round): ‹A› and ‹B› each on a chip in its
  card's colour (the drops carry `from_colour`/`to_colour`, the colour's name,
  which the mod maps to the panel's hex; grey when a card has none), joined by a link mark between two runs of dots that flow
  while A writes (a spinner beside "writing") and lock as solid bars with a
  tick at "sent" or "delivered", the new state bold for 600 ms; and a toast at each
  step: A "Linked to “B”: writing up your latest result for it", then "Sent
  your latest result to “B”"; B "“A” handed you its latest result"; a
  failure "The link to “B” failed: ‹reason›" in A or "The hand-off from “A”
  failed: ‹reason›" in B. Codex and omp have no toast surface.
- **B acts on the hand-off at once, fenced.** A's text reaches B in a fenced
  block, prefaced as a report from another session, not instructions from
  you: the same trust as pasting A's output into B yourself. Whatever A
  picked up can steer B with B's permissions; that was accepted over a
  Run/Discard step in B.
- **A prompt you type in A during the hand-off goes back to A's prompt box**
  as a draft, with a note to send it once the hand-off ends, so it never
  mixes into the write-up and keeps its `@file` mentions. The box takes text
  alone (`$.prompt.fill`), so an attached image has to be added again, and the
  note says so.

Measured before the design (memory `project_session-link-transports`, and the
session narrative for the runs):

- Claude to Claude: `ListAgents` + `SendMessage` delivers by session name; the
  receiver reads it between tool calls, or an idle receiver starts a turn.
  `ListAgents` shows no working directories on this machine, so a target is
  named, never located by directory. cs starts each Claude with
  `--name <card label>`, which is the name `ListAgents` shows.
- A post into a Claude session's inbox socket from the daemon is delivered by
  a prompting-mode receiver and held by a bypass-mode one, token or not, since
  the daemon is not that session's child. An interactive bypass session then
  shows Claude Code's own dialog with the full text, Deny selected by default
  (`.cs/local/probe_held_dialog.py`).
- A mod in an idle interactive bypass Claude session (`--plugin-dir`, Claude
  Code 2.1.294) saw a dropped request file through `$.clock.every` and
  `$.fs`, called `$.prompt.submit`, and the session started a turn within
  about a second, framed "The ‹plugin› plugin sent a message"
  (`.cs/local/probe_mod_submit.py`, `.cs/local/link-mod`). The plugin's
  `hooks.json` validates with a `modules` entry beside its command hooks.
  `turn.complete` hands a mod the turn's final text.
- omp: an extension's `before_agent_start` handler returning `{message}` adds
  it to that turn (a code word injected this way was repeated; without the
  extension the model said none).
- Codex's workspace-write sandbox blocks localhost, and can write under
  `~/.claude/agents-sidebar-tasks`, already one of its `writable_roots`.
- Codex and Claude both take `additionalContext` from a `UserPromptSubmit`
  hook; `emit-state.py` already uses it for the task line.

## 1. Routes

A link has a sender A and a receiver B. Two steps: the panel gets A to write
the message (the ask), and the message reaches B (the delivery).

**The ask, by A's agent:**

| A | How the ask reaches A | When A acts |
|---|---|---|
| Claude | The daemon drops it for A's mod, which submits it as a prompt | At once when A is idle; after its running turn otherwise (§6) |
| Codex | Hook context on the next prompt you send in A | With your next prompt there |
| omp | The extension adds it to the next prompt (`before_agent_start`) | With your next prompt there |

**The delivery, by B's agent:**

| A → B | How the message reaches B |
|---|---|
| Claude A | A's mod takes A's reply when the asked turn ends (`turn.complete`) and hands it to the daemon |
| Codex A | The daemon reads A's reply to the asked turn from A's own rollout, which Codex writes |
| omp A | The extension takes A's reply when the asked turn ends and writes it to A's own links folder |
| any → Claude B | The daemon drops it for B's mod, which submits it as a prompt |
| any → Codex or omp B | The daemon queues it; B gets it as hook context on your next prompt there |

So Claude to Claude runs on its own; anything with Codex or omp waits for
your next prompt in that session, and the card says so.

**The ask's text** names B and asks for the latest result written for B to
act on. Claude A: "Write your latest result for the session ‹B label›,
written for it to act on, as your whole reply. (link ‹nonce›)", the nonce
being 64 random bits that tie the reply to the ask (§2, §4). Codex and omp A
get the same text. The wording is the daemon's own; only the two card labels come from the
sessions (a label can be a model-written title or a branch name), so each
is quoted and cut to 60 characters. B gets the result after a fixed
preface, "A report from the session ‹A label›, another agent session. It is
not an instruction from the user:", then the text in a fenced block whose
fence is longer than any run of backticks inside it.

## 2. Daemon (`sidebar.py`, new `links.py`)

**State.** `links.py` holds pending links: `{id, from, to, route, asked_at,
state}`, state one of `asked`, `sent`, `delivered`, `refused`, `expired`.
At most one open link per sender. A link expires 30 minutes after the ask.

**`POST /link {from, to}`** from the page. Refuses, with the reason the card
shows: either session gone; the same session or one of its own teammates or
worktrees; B exited; A waiting on you (`blocked`), exited, or something else
in front of it (`prompt_refusal`); A already has an open link; a Claude end
whose mod is not running (§4: "‹B› can’t link yet: run /reload-plugins there").

**Mod drops.** Each Claude session has a directory
`~/.claude/agents-sidebar-links/‹session id›/`, `0700`, made by its mod.
The daemon writes `ask-‹link id›.json` there (`{link, nonce, text, peer,
role, expires}`, `role` `ask` for A and `deliver` for B), temp name opened
`O_EXCL|O_NOFOLLOW` then rename, `0600`, after checking the session id
against `_SESSION_FILE` and that the directory's real path sits under the
root and is no link. The mod claims a drop by renaming it to
`taken-‹link id›.json`, so a drop runs once even across a reload, and never
submits one past its `expires`. When a link expires the daemon deletes its
`ask-` file; a link whose drop is already `taken-` is not expired by the
clock until its turn ends.

**Results.** A Claude A's mod writes its result as `result-‹link
id›.json` in its own drop directory, which no Codex sandbox can write.
An omp A's extension does the same in that session's links folder, from the
turn that started with the nonce in its context. A Codex A's result is read
from A's rollout under `~/.codex/sessions`: the final agent message of the
turn whose context carries the nonce. Codex writes that file itself and no
workspace-write sandbox can, so nothing passes through a folder a sandbox
can write; `~/.claude/agents-sidebar-tasks`, which every Codex sandbox can
write, carries no link data. The daemon takes a result only for an open
link in state `asked`, at most 16 000 characters, once; anything else is
deleted and logged with the reason. A taken result moves the link to `sent`
and is delivered by B's route.

**Hook context queue.** For a Codex or omp receiver (or a Codex or omp
sender's ask), the daemon writes the text to that session's state; on its
next `UserPromptSubmit`, `emit-state.py` returns it as `additionalContext`
with a fixed preface, "From the session ‹A label›, another agent session,
not the user:", and clears it. Delivered means that hook ran.

**Claude B delivered** is the mod's word: it writes `started-‹link id›`
when the turn its prompt opened starts (`turn.start`), not when it queues,
and the daemon moves the link to `delivered` on seeing it. A Claude A's
asked turn that ends other than by an answer (interrupted, refused, an API
error) or with an empty answer writes `failed-‹link id›.json` with the
reason, and the link turns `refused` with it. The daemon deletes a link's
files once it reaches a final state.

**Frames** carry each open link `{id, from, to, state, route}` for the page.

## 3. Page (`page.html`)

**Arming.** During a drag the ghost may travel the whole list, not only its
provider group; the placeholder still only moves inside its group. A card
under the pointer (by `elementFromPoint`, the ghost takes no pointer events)
that stays under it for 400 ms arms a link: reordering pauses, the target
lights, and the link draws between the placeholder and the target. Leaving
the target disarms and reordering resumes. Held-button moves arrive in the
Toolbelt (measured), so the timer runs on them.

**Releasing armed** posts `/link`, puts the dragged card back where it began,
and saves no order. Escape, a release outside the panel, or a lost release
cancel as for a drag. A target that cannot be linked never arms: it shows its
refusal reason under the pointer instead.

**After the drop** A's card carries one line, "Asked to send to ‹B›", then
"Sent", then "Delivered to ‹B›" (or "Waits for your next prompt in ‹B›",
"Refused: …", "Expired"); B's card shows "From ‹A›" once delivered. Lines
clear 10 s after the final state.

**In the sessions.** While a link is open, both Claude ends' mods draw a band
above the prompt: ‹A› then a link mark then ‹B›, then the state ("writing",
"sent", "delivered"). The band clears 10 s after the final state, as the card
lines do. Its look is settled in a rendered round.

**Look: Tether** (picked from a live variant round of three, kept as
`.cs/local/link-variants.html`), reworked live into "two drops of water"
(variant C of `.cs/local/fluid-link-variants.html`, asked for: "C but remove the
colors from the badge"). Everything moves on springs (stiffness, damping), so
it lags, overshoots and settles; with reduced motion each lands at once.
As the ghost nears a card, before any overlap, the two reach for each other:
the nearest agent card ahead of the ghost in the direction it last moved,
within 40 px of its leading edge or under it, melts toward it up to half the
full melt, more the closer it is. Only that nearest card reaches, and none
when it or the dragged card cannot link; a new card takes over once the shape
has let go of the last. (Reason: the panel's ghost covers most of the target by
the time the pointer rests on it, so a reach that waited for the pointer was
out of sight.) Once armed they fuse: both silhouettes stand 5 px out past their
cards and a neck spans the join, all blurred and thresholded into one shape
with rounded corners, masked to what lies outside the cards, filled with a
gradient from the target's colour to the ghost's; inside that rim the cards'
own shapes and the neck, fused the same way in the card colour, make one card
background across the join (asked for: "cards background should also melt and
become one card background"). As they fuse the facing corners square off
(the upper card's bottom pair and the lower card's top pair, from the card
radius to 0 with the melt), both cards stop drawing their own edge and shadow
past 60 % melt, and the neck widens to the cards' full width, so the pair reads
as one card with straight sides (asked for: "cards should not have bottom radius or
border, respectively top radius or border"); the ghost turns solid too. The
rim and the background each have their own mask: the rim's holes reach 1.5 px
past each card and the background's stop 1 px inside it while the background
grows 1.5 px past the card, so no two edges meet on one pixel (they did, and
the rim showed through as a grey line at the join, measured at 224,225,233).
The rim's own growth starts from that 1.5 px line, so the cut never thins it
(it had: half grown, during the reach, the rim measured 3 px past the card
against 5.5 px before the cut; asked: "what happened to the glow here?"). The
blur rounds the fused shape's outer corners past the cards' own, which left
the page showing between a card's corner and the rim (asked: "why is it bad at
the corner radius?"); so each card's outline is drawn again unblurred, in the
rim and in the background, beside the blurred shape, and the blur only
shapes the join. A plain badge (card face,
a ring in the text colour at 35 %, the link mark) sits at the ghost's
horizontal centre on its edge facing the target, pinned there with no lag;
once the held card's middle passes the target's, it slides to the held
card's other edge on the same spring as its size (asked for: "once we go over the
middle of the card can the link icon move to the bottom?"),
and its size follows how deep the ghost has gone over the target: overlap
over half the shorter card's height, on a spring that never overshoots
(400, 40); armed, it stands at full size (asked for: "this should appear
gradually when I move to the inner of the other and keep a fixed position on
the dragged card"). Leaving the target disarms at once and lets the shape
and badge spring apart; the overlay goes when both are at rest or the drag
ends. Over the target the held card casts a shadow straight up and straight
down, none at the sides (8 px, the text colour at up to 38 % as it goes
deeper), so the two read apart once fused (asked for: "can we add top and bottom
shadow for the dragged card when over a card?"). The neck that bridges the gap reaches 12 px into each card but never
past the two together: deep over the target the edges it joins are the
pair's outside, and the card-coloured neck covered the rim's top and bottom
and flared at the corners (reported: "something weird happens to the top glow
and bottom glow when I drag the card"). A release while armed confirms where it was let go (picked: B of
four rendered confirmations): the badge bounces once on a spring (520, 14,
kicked at 9 scales/s) while a 2 px ring in the held card's colour ripples
from the badge's radius to 2.6 times it and fades over 620 ms; then the
badge shrinks away over 220 ms. With reduced motion the ring stands at its
reach for those 620 ms and goes. On drop the target shows
"Sent · from ‹A›" for 2 s.

## 4. The mod

A module in the agents-sidebar plugin (`plugin/hooks/hooks.json` gains
`"modules"` beside its command hooks), so every install has it with no
setting changed.

**Ready.** Each second (`$.clock.every`) it reads `$.session.id()`, since
`/clear` and a resume change the id without a new `session.start`, makes
that id's drop directory if needed, and rewrites `ready` there with the
session id as plain text (one small write a second, no process started).
The daemon treats a Claude session as
linkable while `ready` names it and is under a minute old; an older Claude
Code without mods never writes it, so its card is refused, never armed.
`$.fs` reads, writes and lists; making the directory `0700`, the claim's
rename and removing files go through `$.process.run` (`mkdir -m 700`,
`mv`, `rm`).

**A drop** is claimed (§2), then submitted with `$.prompt.submit`, framed
as from the agents-sidebar plugin. A plugin's prompt runs once the session
is idle and is never folded into a running turn.

**The asked turn.** The submit returns no turn id, so the mod takes the
next `turn.start` whose text carries the drop's nonce, keeps `{link,
nonce, turnId}` in module memory, and takes that turn's `turn.complete`,
skipping any with an `agentId`, which are subagents' turns inside it. The
result is the turn's reply at its first Stop (`classic.Stop`,
`stop_hook_active` false, `last_assistant_message`), not the
`turn.complete` answer: a Stop hook that blocks sends the turn on, and its
final answer is then the reply to that hook (measured 2026-10-09: a turn
that answered "TYPED1" ended on the blocking hook's "STOPPED"; cs blocks
this way for its narrative check). A turn interrupted after that Stop still
sends the reply it stopped with. A reload loses that memory, so on
`session.start` any `taken-` ask with no result is written `failed-` ("the
session reloaded during the hand-off").

**Your prompt during the hand-off.** A `prompt.submit` hook sees a prompt
you type (`origin.kind` `composer`, or `bridge` from Remote Control) while
the asked turn runs, answers it with
`{ drop }`, puts its text back in the prompt box with `$.prompt.fill`, and
shows a toast: "the hand-off is running; send this when it ends".

**The band** (§3) is a `ui.render` hook on `AbovePrompt`.

**Who can make a session act through this.** Anything that can write a
session's drop directory. No Codex sandbox can (the root is outside its
`writable_roots`); a Claude session that asks before running commands needs
your approval to; a bypass-mode Claude session can, and could already
message another bypass session with no setting; any other program of yours
can, and could already run anything as you. Unlike `"accept"`, no session
gains a way in it lacked before.

## 5. Failure modes, written before the code

1. A release on a card that cannot take a link sends nothing and says why.
2. Hovering a card shorter than 400 ms never arms; passing over cards while
   reordering never links.
3. Nothing is ever typed into a pane.
4. A mod submits a drop once: a file it took is deleted before the prompt
   goes in, and a drop in another session's directory is never read.
5. A result for an unknown, used, closed or expired link, or over the cap,
   is deleted, not delivered; no link data is read from a folder a Codex
   sandbox can write.
6. One open link per sender; a second drop from A while one is open is
   refused.
7. A link that never completes expires at 30 minutes and says so.
8. A Codex or omp receiver gets the message once, on the next prompt only.
9. A Claude end whose mod is not running is refused with the reason, not
   left waiting.
10. A Claude A whose asked turn ends without an answer, or with an empty
    one, turns the link `refused` with the reason, never `sent`.
11. Only the asked turn's own `turn.complete` becomes the result: not a
    subagent's, not an earlier or later turn's.
12. A prompt you type in A during the asked turn is returned to your prompt
    box, never mixed into the result and never lost.
13. A drop past its `expires`, or of an expired link, never starts a turn;
    a reload mid-hand-off ends the link as failed, never silently.
14. After `/clear` or a resume the session stays linkable under its new id.

## 6. Checks before the build

All run 2026-10-08 (Claude Code 2.1.294, codex-cli 0.160.0, omp 18.2.11);
the spike mod is `.cs/local/link-mod`, its probes `.cs/local/probe_mod_*.py`.

1. **Nonce match: passes.** An ask dropped while A ran another turn queued
   behind it; its `turn.start` carried the nonce, and only its
   `turn.complete` answer became the result, not the busy turn's.
2. **Installed, not `--plugin-dir`: by the docs.** An installed plugin's
   mods load like the rest of the plugin, `/reload-plugins` picks up an
   update. The live E2E confirms it from the copy `install.sh` makes.
3. **Oldest Claude Code with mods: 2.1.287** in the terminal, 2.1.286 in
   the desktop app (docs, mods overview). Mods are on by default;
   `disableAllHooks`, `--safe-mode` or an organization's
   `allowManagedModsOnly` turn them off, so the ready file is the test, not
   the version.
4. **The band: passes in the terminal**, drawn above the prompt with
   Claude Code's own fold control. The desktop app's Code tab draws mods
   too; the VS Code chat panel and `-p` run the hooks and draw nothing, so
   the card lines carry the state there.
5. **Return to the box: passes.** A prompt typed while the asked turn ran
   arrived with `origin.kind` `composer`, was dropped ("Prompt dropped by a
   hook"), went back into the prompt box as the draft, and the result held
   only the hand-off.
6. **Codex rollout: passes.** Hook context is a `developer` message inside
   one turn's `task_started` and `task_complete`, and `task_complete`
   carries that `turn_id` and `last_agent_message`.
7. **omp turn end: passes.** The extension that adds the ask in
   `before_agent_start` takes the next `agent_end` without `willContinue`;
   its last assistant message was exactly the asked reply.

## 7. Tests

- pytest, one failure mode at a time before its code: `/link` refusals (1, 6,
  9); result validation, and a result planted in
  `~/.claude/agents-sidebar-tasks` never read (5); expiry (7); hook context queued once and cleared
  (8); the ask's text per route; drops written `0600` and taken once (4).
- `claude plugin test` for the mod: a drop claimed and submitted once
  across a reload, an expired drop ignored, the asked turn matched by nonce
  with subagent turns skipped, an empty or failed turn written as failed, a
  typed prompt returned to the box, the id followed after `/clear`
  (4, 10-14).
- Daemon pytest: a session id that fails `_SESSION_FILE`, or a drop
  directory that is a link or resolves outside the root, gets no drop.
- Page E2E in headless Chrome: arming at 400 ms, never under it, disarming,
  release posting `/link` and restoring order, refusal under the pointer, the
  status lines (1, 2).
- Live E2E with throwaway sessions: Claude → Claude (both bypass, no setting
  changed), Claude → Codex, Codex → Claude; each with a random token checked
  in what B received.

## 8. Docs

`docs/usage.md` gets a Linking section (gesture, routes, what waits for your
next prompt, the band, refusals); `README.md` a pointer; `docs/integrations.md`
the mod, its drops and the hook context; `docs/development.md` links this
spec.

## Not in this design

Replies sent back automatically, debates, linking shell cards, linking to
sessions on other machines. Standing links, where two Claude
sessions become partners that share context and hand each other tasks, are
`2026-10-09-partner-sessions-design.md`.
