# Agents sidebar — interface system

A 250px iTerm2 Toolbelt panel listing every terminal session, agents first.

## Who and what

The user, mid-work, glancing sideways to answer **which session needs me, and what
is it costing me**. The verb is triage, not reading. They are not in this panel; they
are in a terminal next to it.

## Feel

An instrument panel. Quiet until something is wrong. Nothing animates, colours
or bolds itself unless it is asking to be acted on.

## Domain

Annunciator lamps, fuel gauges, a budget being spent, a shift log, processes at
work. Not "dashboard", not "cards".

## Colour

Tokens are named for what they are on the board, never for a generic scale.
Someone reading only the token names should be able to guess this is a panel of
running things.

    --bg #e3e2e6   --fg #1d1f21   --dim #64666c   --rule #cfcdd3
    --lit #2f8f4e      a lamp that is on and fine
    --alert #c2410c    a lamp demanding attention
    --warn #a8420a     caution, not yet alarm
    --hot #2a6fd6      the one actionable accent

Dark mode redefines the same names, never adds new ones. Colour means
something or it is absent: a row at 30% context is grey, the same row at 93% is
ember. There is no decorative colour anywhere in this panel.

## Depth

Borders and one vibrancy treatment, never shadows on flat elements. Anything
floating above the list — the housekeeping menu, the hover card — uses the same
slab: 82-86% background, `backdrop-filter: saturate(180%) blur(20px)`, a .5px
hairline border, and a three-layer shadow. One vocabulary for "above".

## Spacing and type

Base 2px. Row padding 5px 10px, min-height 30px. Type is small and deliberate:
12px sans for a name, 10px mono for metadata, 9.5px for measurements, 9px for
chips. Monospace and `font-variant-numeric: tabular-nums` for every number, so
columns of figures line up and do not shimmer as they change.

## Patterns

**Gauge.** Anything that is a budget being consumed — context, the five-hour
window, the week — gets a hairline track with a fill: 42px track, 1.5px high,
anchored to the track's LEFT edge so a long bar means a lot spent. Green under
60, amber to 90, ember past it. Facts that are not budgets (cost, line counts,
shell counts) stay plain. A bar behind a dollar figure measures nothing.

**Chips.** A mode the session is in — effort, thinking, output style, past 200k
— is a chip, not a table row. Grey by default; `--warn-bg` when it carries a
cost; `--hot` when it is a mode the user chose.

**Icons.** Phosphor regular, path data read out of the local package, never
transcribed. An icon appears only where it replaces a word. If removing it
loses no meaning, it does not belong: the line-count row has no icon because
`+40 −13` already says it.

**Absent, not zero.** A signal that cannot be read is omitted. No placeholder,
no "0", no "unknown" — the panel would rather show less than show something
plausible and wrong. This is the rule everything else defers to.

**Cursor.** The arrow, never the pointing hand. macOS reserves the hand for
links, and this is a native list.

**Tooltips.** `aria-label` only, never `title`. The window server draws OS
tooltips above any z-index this page can reach, so a `title` and the hover card
end up stacked on each other.
