# Card styles: design

Written 2026-10-25. Status: built.

## Problem

Every session in the list sits on a card: a face a step off the canvas, an
edge, rounded corners and a gap. Some panels read better with less
container. A rendered round put four containerless looks beside today's
cards, at 380px in both themes, and all four stay as choices.

## Decisions

- **Setting.** `card_style`, one of `cards`, `hairlines`, `air`, `inset`,
  `outlines`, default `cards`. The sheet names them Cards, Hairlines, Air,
  Inset rules and Outlines.
- **Looks.** Variants B to E of the round's mock, as rendered:
  - Hairlines (B): no card; a rule the panel's full width between sessions,
    the list's side padding gone; a waiting or finished session is a band
    across that width.
  - Air (C): no card and no rules; 14px between sessions; a waiting or
    finished session gets a rounded face with its ring.
  - Inset rules (D): no card; the rule between sessions starts at the text
    column; a waiting or finished session is a rounded wash with no ring and
    no rule against it.
  - Outlines (E): the card as a hairline in `--rule` over the canvas.
- **Cards.** No rule names `cards`, so Cards draws the stylesheet unchanged.
- **Scope.** Only session rows in the list change, agent and shell cards
  both. Details, the settings drawer and the link tether keep `--card`.
- **Settings head.** A Style card after Finished: Card style, Follow the
  terminal's background, Text size, Shell names, Provider badge, Green wash
  (from Finished), then every `show_*` switch with its sub-switches. Rows
  keeps the three thresholds, Order and the statusline offer.

## Where each look must hold

- **Compact.** The compact padding rules apply as in cards. Inset rules
  start at the compact row's 9px padding, as the worktree hairline does.
- **Tiny.** Already a row, not a card. Every style rule is under
  `:root:not(.tiny)`, so tiny is the same in every style.
- **Worktree cluster.** The fork and the stem stay in every style. The
  cluster outline (each card's `::after`) exists in Cards and Outlines only;
  elsewhere the hairline after the mark column is the join. In Outlines the
  outline is the same hairline, and a cluster card draws no ring of its own.
- **Partners.** The pair stays docked in every style. The badge's face fills
  with `--bg`, the ground it sits on, in every style but Cards. In Outlines
  the lower card stands a hairline off the upper, so the two rings meet as
  one line instead of two a pixel apart.
- **Drag ghost.** Every rule sits under `#groups`; the ghost is a list
  outside it, so it stays a lifted card.
- **Rested and neglected.** Without a face to wash, the card fades to
  opacity .72, as the mock did. A placeholder keeps its own .35.
- **Hover.** A plain tint: `--fg` at 5% over the canvas, 4% in Outlines.
- **Terminal background.** Every token the styles use (`--rule`, `--bg`,
  the washes) is derived from the terminal colour when the panel follows
  one, so each style follows without rules of its own.

## Departures from the mock

The mock was a quick variant sheet; its CSS had specificity gaps the round's
shots did not show.

- **Outlines keeps the waiting and finished cards.** The mock's transparent
  fill outranked the amber and green, so its waiting and finished cards were
  outlines with only the badge and ink to show their state, and Green wash
  did nothing. The build keeps the full card for those two states, fill and
  ring.
- **Hover over a waiting or finished session keeps its fill.** The mock's
  plain tint outranked the amber and the green; the build restates both.
- **Air keeps a partner docked.** The mock's 14px gap also opened under a
  card with a partner below it; the build closes it, as for a worktree.
- **A rounded face in a cluster or a pair is square where it meets the
  next card,** as in Cards.

## The page

`applyCardStyle` runs in `paintAll` beside `applyShellFont` and sets
`data-card-style` on the root from `SETTINGS.card_style`, `cards` before
settings arrive. A pick in the sheet goes through `push`, which renders at
once, so the list changes before the daemon answers.

## Settings default

`load_settings` starts from `DEFAULT_SETTINGS` and copies only the keys the
file has, so an install whose saved file predates `card_style` reads Cards.
`save_settings` writes every key, so the next save pins it in the file.

## Verification

Headless Chrome over one captured frame with seeded cards (finished unseen,
blocked on a Bash gate, working with a subagent and a task list, a worktree,
stale, a partner pair, rested, exited, a shell) and a frozen clock.

- Cards against the page before this work, over four runs in each theme:
  0 differing pixels in five of the eight shots. The other three differ by
  one fixed pattern of about 260 pixels, none more than 32 of 255 off, and
  two shots of the page before this work differ by the same pattern in
  three of six runs. A style other than Cards differs by 107,229 pixels.
- Each style in both themes at 380px, with hover on a plain and on a
  waiting card; each at 180px (compact) and 110px (tiny); each over Dracula
  #282a36 and Solarized light #fdf6e3; the drag ghost of a worktree cluster
  in each.
- Tiny is the same in every style: each style against Cards differs by 0
  pixels or by the same run-to-run pattern that two paints of Cards show.
- The sheet's Style card lists its rows in order, and picking a style there
  sets the root attribute at once.

Not verified: the page in iTerm2's WKWebView, and the hover and the drag
ghost under a real pointer.
