# Finished marks: a session that finished unseen says so where the eyes are

Designed 2026-10-18 on `feature/finished-marks`.

A session that ends its turn while another pane has the eyes gets a small
green Done badge on its card. Across five to fifteen sessions that badge is
missed: it is twelve pixels of type in a panel that is not being looked at,
and a card below the fold has no discoverability at all. The finish sound
and the finish notification are off in the install this was designed for,
so a finish today produces nothing outside the panel.

The request (2026-10-18): "I don't really notice idle/done sessions". Then,
of the panel: "it doesn't draw my attention and I completely ignore the
sidebar, it looks nice, but it's not really doing its job". The eyes are
inside iTerm2, across several tabs that each hold split panes.

A council of eleven external models ranked the options (transcript in
`.claude/council-cache/council-1792299934.md`). Eight rendered variants were
compared side by side; the pick was E (grouped order plus a card wash) and H
(marks outside the panel), each piece its own setting.

Decided:

- **Marks go where the eyes are: into the iTerm2 pane itself** (picked over
  panel-only changes). The panel is improved too, but a greener card in a
  panel nobody looks at fixes nothing on its own.
- **The pane badge carries the mark** (picked over tab colour and over the
  pane title bar). Measured 2026-10-18 in a throwaway window
  (`tests/live/pane_marks_check.py`): a tab's colour follows its active pane
  only, so a finished pane behind the one being typed in cannot colour its
  tab; a profile subtitle shows nowhere, neither in the tab nor in a split
  pane's title bar; the only text that reaches a pane's title bar is the
  session name, which agents set and the daemon reads, so it is never
  written. The badge shows in the pane, large and faded, in the profile's
  own badge colour.
- **Tab colour, menu bar count and Dock badge exist as switches, off by
  default.** Tab colour helps a one-pane tab; the other two help only when
  iTerm2 is behind another app, which is not where the misses happen.
- **In the panel, an unseen finish lifts the card and washes it green**
  (variant E). Blocked cards are lifted too and sit above it; the wash sits
  below amber in weight. Idle keeps its grey name and Idle outline: idle asks nothing.
- **A mark clears when the pane is focused**, and only then. Hover, the
  panel being visible, or another pane in the same tab coming forward do
  not clear it. This is the existing `Unseen` rule; nothing new is added to
  it.
- **No auto-focus on a finish, no repeated sounds, no escalation.** Those
  were rejected by the council unanimously and are not wanted here.

Settled earlier and kept: no left accent bars, plain tint hovers, no motion
that pops or rotates, the small rounded-square identity, no emojis, a status
line only while it is actionable. The finish sound and finish notification
settings are untouched.

## 1. One bit drives everything

The daemon already keeps the set of sessions whose turn ended while they
were not in front: `alerts.Unseen.sids`, stepped once per rebuild, cleared
when the session comes to the front, starts a turn, blocks, exits or goes.
Every mark in this design is a view of that set. There is no second clock,
no acknowledgement state, no per-mark bookkeeping of when a finish happened.

A rebuild computes `want = Unseen.sids` filtered to top-level cards (the
rows whose card can show Done) that still have an iTerm2 session object. The marker holds `have`, the sessions it has
marked. `want - have` get marked; `have - want` get cleared. Both happen in
the same rebuild that renders the card, so the panel and the pane never
disagree for longer than one poll.

## 2. In the panel

**Order.** A setting `finished_first` (on). While on, a two-tier band
sits at the top of each provider group in every base order (`terminal`,
`name`, `attention`, `hand`): blocked cards first, then unseen finished
cards, then the rest. Inside each tier the base order holds. A card moves
into the band when it blocks or its mark appears and leaves when the
question is answered or the mark clears; nothing else reorders it. This is
a deliberate exception to the terminal order's promise that nothing a
session does moves a card (decided 2026-10-18: "Blocked then finished, both
on top" over finished alone and over a band in the attention order only);
turning the setting off restores that promise in full, and the usage docs
say so beside the promise. The existing
`ATTENTION_DWELL_SECONDS` rule does not apply here: the mark itself already
needs the turn to have ended, and a turn that ends and restarts within one
poll never marks.

A move is a re-render, not an animation. The page holds a frame back only
for an open question under the pointer, so a band move can re-sort the list
under a resting pointer (corrected 2026-10-18 after review: the pin the
earlier text named is the hover card, not the list). A hold for band moves
is a separate decision, not taken here.

The band is made of blocks (a lead with its teammates indented under it
and its worktrees and partners docked to it), each moving as one, lifted
when any card in it (the lead, a docked worktree, a linked partner) is
blocked or carries the mark: each of those has a pane of its own that
wants the eyes. A teammate's row is nested and never shows Done, so the
marker (section 3) never marks its pane, and the two agree in saying
nothing. Unseen membership alone says finished, for the band, the wash and
the pane marks alike: Unseen drops a sid that began a turn, blocked or
exited, and keeps one through the seconds a Stop hook's command reads as
working, which the marks ride out instead of flickering (decided
2026-10-18 after review). Banded
rows carry no attention bucket, so the `Working`/`Idle` heads of the
attention order open below the band and their counts leave banded cards
out. A drag while a card is banded does not write the band position into
the saved hand order: banded cards are left out of the drop's reading of
the list and keep their remembered index.

**Wash.** A setting `finished_wash` (on). A card with the mark gets a class
`finished` beside `rested`/`neglected`; its background is a new token pair
`--finished-bg`, dark `#1f2e22`, light `#e8f5ec`, with the card border mixed
toward `--sev-ok`. No inset ring: the blocked card keeps its two-pixel ring
as the louder of the two. The name stays `--fg`, not dimmed. The Done badge
stays as it is. The wash outranks `rested` and `neglected` while present.

Hover on a washed card is the plain tint hover the other cards have, at the
same weight over the wash.

**Idle** is unchanged.

## 3. In the pane

All pane marks are written through the session's own profile with
`Session.async_set_profile_properties(LocalWriteOnlyProfile)`, which changes
that session alone and not the saved profile. Before the first write to a
session the marker reads the fields it will touch with
`Session.async_get_profile()` and keeps them; a clear writes them back. A
session that goes away before its clear is dropped from `have` with nothing
to restore.

**Badge** (`mark_badge`, on). `badge_text` becomes `Done`. The badge colour,
font and margins are left at the profile's values: the mark is the word, in
the user's own badge style. A profile whose badge text is already non-empty
is not marked, and the row logs `badge busy` once; a badge in use is the
user's.

**Title bar.** Dropped 2026-10-18 after the live check: the subtitle does
not render in this iTerm2, and the session name is not the daemon's to
write. No setting.

**Tab colour** (`mark_tab`, off). `use_tab_color` true and `tab_color`
`--sev-ok`'s dark value. Not written when the profile already has
`use_tab_color` on: a coloured tab is the user's. Documented limit: the tab
shows the colour only while the marked pane is the active one in its tab.

**Clearing** writes the kept values back, each field only if the marker
wrote it.

**Startup.** The marker starts with `have` empty. A mark left by a daemon
that died is recognised by its exact text: on the first rebuild, any session
whose `badge_text` is exactly `Done` is cleared, since the
marker never writes anything else there and a user would not. Tab colour is
not recognisable this way and is left alone; this is the second reason it
defaults off.

**Under tmux.** With iTerm2's tmux integration (`tmux -CC`) each tmux pane is
its own iTerm2 session and marks land on the right pane. Inside plain tmux
one iTerm2 session hosts several tmux panes; a mark there covers the whole
pane. The usage docs say so; nothing tries to be cleverer.

**Remote cards.** A row whose state came from another machine has an iTerm2
session here (the ssh or et pane), and that pane is where the eyes would
look, so it is marked like any other.

## 4. Outside iTerm2

**Menu bar count** (`mark_menubar`, off) and **Dock badge** (`mark_dock`,
off). Both show `len(Unseen.sids) + blocked count`, hidden at zero. The Dock
badge is iTerm2's own (`NSApp.dockTile.badgeLabel` on the iTerm2 process is
not reachable from the API, so this is the notifier's badge: the notifier
app in `assets/notifier.swift` already has a Dock presence through its
bundle, and gains a `badge <n>` verb). The menu bar item is an
`NSStatusItem` in the same notifier, a small rounded square in `--sev-ok`
with the count beside it; a click brings iTerm2 forward and focuses the
oldest marked session through the daemon's existing `focus` verb. Neither
is built until the notifier is already running for notifications; with
notifications off the switches are present and do nothing, and their rows
say so.

The notifier today is one-shot: it exits moments after an action or its
lifetime. A status item and a Dock badge need a resident process with its
own launch and shutdown, which this design does not provide. These two are
therefore a later slice with its own design; this slice ships the settings
card without their rows, and the band of washed cards is the count.

## 5. Settings

A new card between Focus and Rows:

| Card | Settings |
| --- | --- |
| Finished | In the panel: Finished first, Green wash. In the pane: Badge, Tab colour |

Defaults: `finished_first` on, `finished_wash` on, `mark_badge` on,
`mark_tab` off. Each
is a plain switch; none nests under another. `save_settings` writes every
key, so an install that has saved before gets the new defaults only through
`load_settings` filling the missing keys, which it does today.

The README settings table and the card-states figure gain the washed card;
`docs/usage.md` gains a Finished section with the tmux limit, the
tab-colour limit, the `busy` rule and the startup sweep.

## 6. What is not in this design

- A summary strip or count at the top of the panel. Ranked high by the
  council for people who look at the panel; this design is for someone who
  does not, and the band of washed cards at the top already aggregates.
- Escalation by age, reminder sounds, auto-focus on finish.
- Any change to what `Unseen` counts as a finish or a view.
- A mark for idle. A card is idle a long time without anyone needing it.

## 7. Tests

End to end, against a real iTerm2, since the marks are iTerm2 state:

1. A throwaway window with two splits; a fake session row whose state goes
   working then idle while the other split is active. Expected: the badge
   `Done` appears on the finished pane, `have` holds its
   id, the card carries `finished` and sits in the band. Activating the pane
   clears both within one poll and the profile fields read back as
   they were.
2. The same, with the profile's badge text set beforehand to `mine`.
   Expected: no badge write, one `badge busy` log line, card still washed
   and banded.
3. Daemon restart with a `Done` badge left on a pane. Expected: cleared on
   the first rebuild.
4. Page: with `finished_first` off and `finished_wash` on, the order is the
   base order and the wash is present; with both off the card looks as it
   does today. With `finished_first` on in the terminal order, a blocked
   card and a finished card from the middle of the list render first, in
   that order, and return to their places when answered and focused.

The page tests in `tests/` already render rows through the real page; the
wash and band get rows there. The marker is a pure diff over two sets plus
an iTerm2 writer, so its diff is tested without iTerm2 and the writer only
in the live run.

Run 2026-10-18 with `tests/live/finished_marks.py` against the daemon from
this checkout: row working, card finished, card banded, marked badge, card
plain, cleared badge, all PASS (screens `marked.png`, `cleared.png`). The
suite: 1717 passed.

## 8. Left to the builder

- The exact light-theme wash value, checked against white cards in both
  the Chrome harness and WKWebView.
- Whether the band move under a resting pointer reuses the pin or needs its
  own hold.
- Where the marker lives: a small class beside `alerts.Unseen`, fed from
  the same rebuild step.
