# Cards in an order you drag

Designed 2026-10-07 on `feat/drag-order`.

Dragging an agent card up or down puts it where it is dropped, and the panel
keeps that order. It is a fourth Order choice, **By hand**, beside Follow the
terminals, By name and By attention.

Decided before the build:

- A drop changes the panel's own order only. iTerm2's tabs and windows do not
  move.
- A card is remembered by its name (its label), so the order survives an
  iTerm2 restart and a `tmux -CC` reattach. Two cards with the same name share
  one place.
- Dragging works whatever the Order is. The first drop switches Order to By
  hand, starting from the order on screen, so nothing else moves.
- Only agent cards drag. Shell cards in Sessions keep their order: they come
  and go, and their names (paths, commands) repeat.
- A card stays inside its provider group. A lead card carries its teammates
  and docked worktree cards; those never drag on their own.
- A card with no remembered place goes to the bottom of its group, in the
  order it arrived.

## 0. Step one: do held-button moves reach the Toolbelt?

The Toolbelt web view has been measured getting almost no `mousemove` at
times (memory `project_toolbelt-pointer-events`). A drag runs on moves while
the button is held, which AppKit delivers as `mouseDragged:`, a different
event, never measured there.

Before any build, a throwaway probe in the live page counts `pointermove`
with `buttons & 1` and `pointerup` while a person presses and drags on a card in
the hotkey window. If held moves arrive, build as below. If they do not, stop
and redesign (for example Move up / Move down in the right-click
menu). The probe is never committed.

## 1. Daemon (`sidebar.py`)

**Settings.**

- `SETTING_CHOICES["order"]` gains `"hand"`.
- `DEFAULT_SETTINGS["hand_order"] = []`: card names, first is top.
- `_clean` gets a list branch for `hand_order`: keep `str` items only, drop
  empty strings and later duplicates, keep the first 200. A value that is not
  a list leaves the default.

**Ordering.** `by_hand(rows, names)` beside `by_name`:

- sorts `_blocks(rows)` by the index of the block head's `label` in `names`;
- a block whose name is not in `names` sorts after every known one, keeping
  its incoming (terminal) order; `sorted` is stable, so the key is
  `(index if known else len(names),)`;
- applies to `rows["agent"]` only.

`snapshot` calls it where it calls `by_name` and `by_attention`, so
`by_provider` still groups afterwards and keeps each group's order.
`snapshot` takes the names as a new keyword argument, passed from settings
where `order` is passed today.

## 2. Page (`page.html`)

**Starting a drag.** `pointerdown` with the primary button on an agent
card's `button.row` records the start. Nothing happens until the pointer has
moved more than 5 px vertically; a shorter press stays the click that focuses
the session. The right-click menu is unchanged. The page takes pointer
capture on the row so the moves keep coming outside it.

**During a drag.**

- The card's block (the card plus its nested rows) follows the pointer on the
  Y axis only, by `transform: translateY`, clamped to its provider group.
- The other blocks in the group slide to make room, through the row-move
  animation the page already runs (`measureRows`).
- Arriving frames are held, as the question-card hold does, and the latest
  one is painted after the drop.
- Escape, or losing pointer capture, cancels: the block slides back and
  nothing is saved.

**Dropping.**

- The click that follows the `pointerup` is swallowed.
- The page builds the new list: the agent card names as now shown, top to
  bottom, with the dropped block at its new place, followed by any names in
  the old `hand_order` that are not on screen (so a closed session keeps its
  place for when it returns, up to the 200 cap).
- It sends `{order: "hand", hand_order: [...]}` through the settings call the
  page already uses, and paints the new order at once rather than waiting for
  the daemon's next frame.

**Settings.** The Order control gains a fourth choice, By hand. Picking it
with an empty `hand_order` shows the terminal order until the first drop.

**Look.** While dragged the card rises one step (the shadow the panel uses
for raised surfaces) and nothing else changes. No accent bar, no handle
(memory `feedback_panel-visual-taste`).

## 3. Failure modes, written before the code

1. A press without a move must still focus the session (threshold).
2. A drag must not focus the session on release (click swallowed).
3. A redraw mid-drag must not snap the card back or lose it (frames held).
4. A drag must not leave its provider group or split a block from its
   teammates and worktrees.
5. Escape mid-drag restores the old order and saves nothing.
6. The first drop under By name or By attention must not reorder any card
   other than the dragged one.
7. A remembered name that is not on screen keeps its place in the list.
8. `hand_order` from settings.json that is not a list, holds non-strings,
   duplicates, or more than 200 names is cleaned, never trusted.
9. A new session with an unknown name lands at the bottom of its group.

## 4. Tests

- pytest, written one at a time before the code each covers: `_clean` cases
  for `hand_order` (8); `by_hand` placing known names, unknown names last in
  arrival order, blocks kept whole (9); `snapshot` with `order="hand"` and
  provider groups (4).
- Headless Chrome E2E in `.cs/local/e2e_drag_order.mjs` on the live page with
  real `Input.dispatchMouseEvent` presses and moves: modes 1-7. Run against
  the unbuilt page first and seen to fail.
- Live check in the hotkey window: drag, drop, reload, order kept.

## 5. Docs

- `docs/usage.md` Order table: a By hand row, and that a drop switches to it.
- `README.md` settings row and any sentence listing the orders.
- The settings figure, if it draws the Order choices.
