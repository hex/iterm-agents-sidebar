# Drag Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drag an agent card up or down in the panel; the drop sets a fourth Order, By hand, that the daemon keeps by card name.

**Architecture:** The daemon owns the order, as it does for the other three: a `hand_order` setting (names, top first) and a `by_hand` sort beside `by_name`. The page only collects the gesture, paints the drop at once and posts `{order: "hand", hand_order}` through the existing `/settings` call. Each snapshot carries the `hand_order` it was sorted by, so the page can skip a frame built before the drop.

**Tech Stack:** Python 3.10 daemon (`sidebar.py`), one-file page (`page.html`, plain JS in WKWebView), pytest, headless Chrome over CDP for page E2E.

**Spec:** `docs/superpowers/specs/2026-10-07-drag-order-design.md`

## Global Constraints

- Order choices: `terminal`, `name`, `attention`, `hand`; label "By hand".
- `hand_order`: list of `str`, empty strings and later duplicates dropped, at most 200 kept; default `[]`.
- Only agent cards drag; shell cards never. A card stays inside its provider group; a block (card + teammates + docked worktrees) moves whole.
- Drag starts after more than 5 px vertical movement; Y axis only; Escape cancels and saves nothing.
- Unknown names go to the bottom of their group in arrival (terminal) order.
- No accent bar, no handle; a dragged card rises one step and nothing else changes.
- Run pytest with the mise 3.11 python first on PATH (memory `project_test-python`); judge mutants by exit code with `--color=no` and `PYTHONDONTWRITEBYTECODE=1`.
- Never commit a PROBE in `page.html`.
- Never name Herdr anywhere in the repo.

## Review Focus

1. A frame the daemon built before the drop arrives after it: the card must not jump back and forth. Pinned by Task 3 check 6 (stale frame skipped) and Task 2 test `snapshot_carries_the_hand_order`.
2. The `/settings` POST fails: the panel must not freeze waiting for a matching frame. Pinned by Task 3 check 7 (skip lasts at most 5 s).
3. A drag released outside the panel, or capture lost (the Toolbelt drops events): the card must slide back, nothing saved. Pinned by Task 3 check 5 (`lostpointercapture` cancels).
4. Two cards with the same name: they share one slot and keep their arrival order relative to each other, never swap. Pinned by Task 2 test `same_name_cards_keep_their_arrival_order`.
5. A drop while a question card is held under the pointer: the drag wins only on the dragged card; a held question frame is still released by the existing rules. Pinned by Task 3 check 8 (drag does not start on `.answers` buttons).

---

### Task 0: Gate — held-button moves reach the Toolbelt

**Files:** `page.html` (PROBE-DRAG, uncommitted, already in the working tree).

- [ ] **Step 1:** Reload the panel and drag a card 3 times in the hotkey window.
- [ ] **Step 2:** Read `grep PROBE-DRAG ~/.claude/agents-sidebar-status/daemon.log | tail`.
  Pass: `held` grows by tens per drag, `up` equals `down`, `maxdy` near the drag distance, `lost` 0.
  Fail (`held` near 0): stop, report back, redesign (spec §0).
- [ ] **Step 3:** `git checkout page.html` to drop the probe; log the counts in the narrative.

### Task 1: The `hand_order` setting and the `hand` choice

**Files:**
- Modify: `sidebar.py` (`DEFAULT_SETTINGS` ~line 165, `SETTING_CHOICES` ~line 170, `_clean` ~line 175)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `load_settings()["hand_order"] -> list[str]`; `"hand"` accepted for `order`; `HAND_ORDER_MAX = 200`.

Write each test, run it, see it fail, then add only the code it needs. One at a time.

- [ ] **Step 1: failing test — order accepts hand**

```python
def test_order_can_be_by_hand(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"order": "hand"}, store)
    assert load_settings(store)["order"] == "hand"
```

Run: `python -m pytest tests/test_settings.py::test_order_can_be_by_hand -q --color=no` — expect FAIL (`'terminal' == 'hand'`).
Implement: `"order": ("terminal", "name", "attention", "hand")`. Re-run: PASS.

- [ ] **Step 2: failing test — a saved hand order survives, cleaned**

```python
def test_a_hand_order_keeps_names_once_in_their_order(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"hand_order": ["beacon", "atlas", "beacon", "", 7, None, "cobalt"]}, store)
    assert load_settings(store)["hand_order"] == ["beacon", "atlas", "cobalt"]


def test_a_hand_order_that_is_not_a_list_is_ignored(tmp_path):
    store = tmp_path / "settings.json"
    save_settings({"hand_order": "atlas"}, store)
    assert load_settings(store)["hand_order"] == []


def test_a_hand_order_keeps_at_most_two_hundred_names(tmp_path):
    store = tmp_path / "settings.json"
    names = [f"s{i:03}" for i in range(250)]
    save_settings({"hand_order": names}, store)
    assert load_settings(store)["hand_order"] == names[:200]
```

Run each — expect FAIL (KeyError `hand_order` first, then the cleaning cases).
Implement in `DEFAULT_SETTINGS` (with a comment in the file's voice):

```python
    # The order the cards were dragged into, by name, top first. Used while
    # "order" is "hand"; a name not on screen keeps its place for its return.
    "hand_order": [],
```

and in `_clean`, before the `isinstance(default, bool)` branch:

```python
        if isinstance(default, list):
            if isinstance(value, list):
                names = [name for name in value if isinstance(name, str) and name]
                out[key] = list(dict.fromkeys(names))[:HAND_ORDER_MAX]
            continue
```

with `HAND_ORDER_MAX = 200` and its one-line comment next to `SETTING_RANGES`.
Note: `save_settings` returns `_clean(...)` of the merge; also check `DEFAULT_SETTINGS` is copied, not shared — `dict(DEFAULT_SETTINGS)` shares the list, so `_clean` must assign a new list, never mutate `out[key]` in place.

- [ ] **Step 3:** `python -m pytest tests/test_settings.py -q --color=no` — all pass.
- [ ] **Step 4: Commit** `git add sidebar.py tests/test_settings.py && git commit -m "Settings keep a hand order: card names, once each, at most 200"`

### Task 2: The daemon sorts By hand

**Files:**
- Modify: `sidebar.py` (`by_hand` after `by_name` ~line 817; `snapshot` signature ~line 922 and its order branch ~line 1167; `_rebuild_once` ~line 3318)
- Test: `tests/test_snapshot.py` (beside the `by_name` tests ~line 621)

**Interfaces:**
- Consumes: `settings["hand_order"]` from Task 1.
- Produces: `by_hand(rows: list[dict], names: list[str]) -> list[dict]`; `snapshot(sessions, order="terminal", group_by_provider=False, now=None, hand_order=())`; every published frame has `frame["hand_order"]` (the list it was sorted by, `[]` unless order is hand).

- [ ] **Step 1: failing tests** (fixtures `OTHER`, `MAIN`, `LINKED`, `TEAM` already in the file):

```python
def test_by_hand_puts_the_named_cards_where_they_were_dropped():
    rows = snapshot([MAIN, OTHER], order="hand", hand_order=["beacon", "atlas"])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["beacon", "atlas"]


def test_by_hand_puts_a_card_it_does_not_know_last_in_terminal_order():
    rows = snapshot([MAIN, OTHER, TEAM[0]], order="hand", hand_order=["atlas"])["groups"][0]["rows"]
    assert [r["label"] for r in rows] == ["atlas", "beacon", "fignity"]


def test_by_hand_moves_a_card_with_its_teammates_and_worktrees():
    rows = snapshot([MAIN, LINKED, TEAM[0], TEAM[1]], order="hand",
                    hand_order=["fignity", "atlas"])["groups"][0]["rows"]
    assert [(r["label"], r["depth"]) for r in rows] == [
        ("fignity", 0), ("review-351", 1), ("atlas", 0), ("worktree", 0)]


def test_same_name_cards_keep_their_arrival_order():
    twin = dict(MAIN, session_id="Twin")
    rows = snapshot([MAIN, OTHER, twin], order="hand", hand_order=["atlas", "beacon"])["groups"][0]["rows"]
    assert [(r["label"], r["session_id"]) for r in rows] == [
        ("atlas", MAIN["session_id"]), ("atlas", "Twin"), ("beacon", OTHER["session_id"])]


def test_by_hand_leaves_the_sessions_group_in_terminal_order():
    """Only agent cards drag; a shell card's name is a path or a command."""
    code = dict(LIVE[0], session_id="5E11C0DE", tab_index=7, path="/Users/x/Code")
    groups = snapshot([LIVE[0], code], order="hand",
                      hand_order=["/Users/x/Code", "/Users/x/Downloads"])["groups"]
    assert [r["label"] for r in groups[-1]["rows"]] == ["/Users/x/Downloads", "/Users/x/Code"]
```

Check the label of `code` first with a one-off `snapshot([code])`; if the label is not `/Users/x/Code`, use what it prints in both places.

```python
def test_snapshot_carries_the_hand_order_it_was_sorted_by():
    assert snapshot([MAIN], order="hand", hand_order=["atlas"])["hand_order"] == ["atlas"]
    assert snapshot([MAIN], order="name", hand_order=["atlas"])["hand_order"] == []
```

Run: `python -m pytest tests/test_snapshot.py -k "hand" -q --color=no` — expect FAIL (unexpected keyword `hand_order`).

- [ ] **Step 2: implement**

```python
def by_hand(rows, names):
    """Top-level cards in the order they were dragged into, each with
    everything nested in it. A card whose name was never placed goes after
    every placed one, in the order it came."""
    place = {name: at for at, name in enumerate(names)}
    blocks = sorted(_blocks(rows), key=lambda block: place.get(block[0]["label"], len(place)))
    return [row for block in blocks for row in block]
```

In `snapshot`: add `hand_order=()` to the signature and its docstring line; add

```python
    elif order == "hand":
        rows["agent"] = by_hand(rows["agent"], hand_order)
```

and set `"hand_order": list(hand_order) if order == "hand" else []` in the returned dict.
In `_rebuild_once`: pass `hand_order=settings["hand_order"]`.

- [ ] **Step 3:** `python -m pytest tests/test_snapshot.py tests/test_settings.py -q --color=no` — all pass.
- [ ] **Step 4: sensitivity** — mutate `len(place)` to `-1` and `rows["agent"]` to every kind; each must fail a test. Revert.
- [ ] **Step 5: Commit** `git commit -am "The daemon sorts agent cards by hand, and each frame says which hand order it used"`

### Task 3: The page drags a card

**Files:**
- Modify: `page.html` (Order choices ~line 4209; the row button setup ~line 3839; render ~line 2502; a new drag section after the hold code ~line 2490)
- Create: `.cs/local/e2e_drag_order.mjs` (session-local, not committed; same harness shape as `.cs/local/e2e_card_hold.mjs`)
- Test: `tests/test_page_*.py` only if a pure source assertion is the honest test (e.g. the Order choice list); behaviour is tested by the E2E.

**Interfaces:**
- Consumes: frames with `hand_order` (Task 2); `push(change)` (page.html ~4546); `measureRows()` / `animateRows(before)`; `act(sessionId, "focus")`; `agentKindOf(row)`; `button._row` (each row button carries its row).
- Produces: `dragging` (null or state object), `dropOrder() -> string[]`, `frameIsStale(frame) -> bool`, `rowBlocks(rows) -> row[][]` (the page's copy of the daemon's `_blocks`: a row starts a new block unless `row.depth` or `row.worktree_of`).

**The DOM as `paint()` builds it (page.html ~3594-3900), which the drag must follow:**
- A top-level card is `li.line.card[data-key]` without `.worktree`. Its teammates are NOT separate `li`s: they are `button.row.child` inside the lead's `li`. A docked worktree is the next sibling `li.line.card.worktree`.
- So a block on screen = one `li.line.card:not(.worktree)` plus the `li.line.card.worktree` siblings that directly follow it.
- A drag starts only from `button.row.agent:not(.child)` whose `li` is not `.worktree` (check 10 presses a `button.row.child`; a worktree card's own button also starts nothing).
- Provider heads are `li.phead`; By attention also paints bucket heads. The drag's group is the run of top-level cards whose `agentKindOf(button._row)` equals the dragged card's; clamp to the first and last block of that run, and never move a block across an `li.phead`.

E2E first. Run it against the current page and see each behaviour check fail.

- [ ] **Step 1: write `.cs/local/e2e_drag_order.mjs`.** Same CDP setup as `e2e_card_hold.mjs` (380 px wide, `events.onmessage = () => {}`, `act` and `fetch('/settings')` stubbed into `window.__acts` / `window.__posts`). A frozen BASE with at least three top-level Claude cards A, B, C (from `LATEST`). Press/move/release via `Input.dispatchMouseEvent` (`mousePressed`, `mouseMoved` with `buttons: 1`, `mouseReleased`). Checks:
  1. Press and release on A with a 3 px move: `__acts` has `["<A>", "focus"]`, order unchanged.
  2. Drag A down past C and release: on screen order is B, C, A; `__acts` has no focus; `__posts` has one `{order: "hand", hand_order: [B, C, A, ...]}`.
  3. During the drag, `render(BASE, true)` does not move A off the pointer (A's top within 2 px of the pointer offset) and the frame paints after release.
  4. A drag cannot leave A's provider group: dragging an omp/Codex card above the Claude head clamps it to its group's top (skip with a printed SKIP if BASE has one provider only; never a PASS).
  5. Escape mid-drag, and separately a synthetic `lostpointercapture`, restore B, C, A's old order and post nothing.
  6. After a drop, a stale frame (BASE in the old order, `hand_order: []`) delivered the way frames arrive (save the real `events.onmessage` before stubbing it, then call it with `{data: JSON.stringify(stale)}`) leaves the order as dropped AND `LATEST` in the dropped order; a following `render(LATEST)` without `arrived` (what `push()`'s `.then` does) still shows the dropped order; a frame in the dropped order with `hand_order: <posted>` paints and becomes `LATEST`.
  7. After a drop, a stale frame arriving 5.5 s later paints (no freeze if the save failed).
  8. Pressing an answer button inside `.answers` of an asking card and moving 20 px starts no drag.
  9. Under `SETTINGS.order = "name"`, the first drop's `hand_order` starts from the order on screen: only the dragged card changes place.
  10. A teammate row (`depth > 0`) cannot start a drag.
- [ ] **Step 2: run against the unbuilt page.** Get the URL as the other E2Es do (port from `~/.local/share/agents-sidebar/endpoint.json`, token from the running panel URL), Chrome headless on a dedicated port (`pgrep -fl remote-debugging-port` first; use 9444), `timeout 900`. Expect checks 2, 3, 5, 6, 7, 9 to FAIL; 1, 8, 10 may pass (they are guards). Record the output in the narrative.
- [ ] **Step 3: implement the Order choice.** `["hand", "By hand"]` appended to the Order choices.
- [ ] **Step 4: implement the drag.** One section, its own header comment explaining the Toolbelt constraints (moves come as held-button drags; capture can be lost). Shape:

```js
// A card dragged up or down takes the place it is dropped in, and the
// daemon keeps that order (Order: By hand). Only agent cards drag, inside
// their provider group, a card with its teammates and worktrees.
const DRAG_START_PX = 5;
const STALE_FRAME_MS = 5000;
let pressed = null;    // {li, key, startY, pointerId} until the move passes DRAG_START_PX
let dragging = null;   // {li, block, group, startY, before, index}
let droppedAt = 0;
let dropped = null;    // the hand_order posted by the last drop

function frameIsStale(frame) {
  return !!dropped && performance.now() - droppedAt < STALE_FRAME_MS
    && JSON.stringify(frame.hand_order || []) !== JSON.stringify(dropped);
}
```

  - `pointerdown` (capture) on `button.row.agent:not(.child)` whose `li` is not `.worktree`, primary button, target not inside `.answers`: set `pressed`, `setPointerCapture`.
  - `pointermove` with `buttons & 1`: past the threshold, build `dragging` (block and group as described under "The DOM as paint() builds it"), add class `dragging`; then `translateY(dy)` clamped to the group, and when the centre crosses a neighbour block, move the block in the DOM with `measureRows`/`animateRows` so neighbours slide.
  - `pointerup`: if dragging, compute `names = dropOrder(...)` = top-level agent labels now on screen, then any `SETTINGS.hand_order` names not on screen, cut to 200; set `dropped = names`, `droppedAt = now`; reorder `LATEST`'s AGENTS rows to match; `push({order: "hand", hand_order: names})`; swallow the next `click` (capture listener, once).
  - `keydown` Escape and `lostpointercapture`: cancel — put the block back where it began, `render(LATEST)`, no push.
  - `events.onmessage` (page.html ~4664): parse into a local first, `if (frameIsStale(frame)) { markFresh(); return; }`, and only then `LATEST = frame; render(LATEST, true)`. A stale frame must never become `LATEST`, because `push()`'s `.then` repaints `LATEST` without `arrived`.
  - `render`: at the top, `if (dragging) { heldFrame = snapshot; heldArrived = heldArrived || arrived; return; }` and `if (frameIsStale(snapshot)) return;` (this guard protects `releaseHeldFrame`); on drag end call `releaseHeldFrame()`.
  - On drop, reorder `LATEST`'s AGENTS rows with `rowBlocks` into the order of the new names (unknown names after, in their order) and set `LATEST.hand_order = names`, so `LATEST` is never stale against `dropped`.
  - CSS: `li.line.card.dragging { position: relative; z-index: 5; box-shadow: <the panel's raised shadow, e.g. the one #card uses>; }` and `transition: none` on it while dragging.
- [ ] **Step 5: run the E2E** — 10/10 PASS (or check 4 SKIP with the reason printed) twice; `e2e_card_hold.mjs` and `e2e_hold_answered.mjs` still pass.
- [ ] **Step 6:** `python -m pytest -q --color=no` — whole suite passes (page source tests included).
- [ ] **Step 7: Commit** `git commit -am "Drag an agent card up or down; the drop sets Order to By hand"`

### Task 4: Docs, figures, live check

**Files:**
- Modify: `docs/usage.md` (Order section, line ~31-49), `README.md` (any sentence listing the orders; settings row line ~178 needs no change unless it names choices)
- Check: `tests/test_docs.py`, `tests/test_figures.py`, the settings figure script if it draws Order choices (`rg -n "By attention" --glob '!**/.claude/worktrees/**'`)

- [ ] **Step 1:** usage.md Order table, a row:
  `| By hand | The order you dragged the cards into. Drag a card up or down to put it there; the first drop switches Order to By hand, starting from what you see, so only that card moves. A new session goes to the bottom of its group, and a closed one keeps its place for when it returns. Shell cards and teammates do not drag. |`
  and one sentence after the table that a card is remembered by its name.
- [ ] **Step 2:** `rg` for every list of the orders and update it; regenerate any figure that draws the choices; `python -m pytest tests/test_docs.py tests/test_figures.py -q --color=no`.
- [ ] **Step 3:** `vale --config ~/.claude/vale/.vale.ini --output=line --no-wrap docs/usage.md` on the new lines; fix or justify.
- [ ] **Step 4: Commit** `git commit -am "usage.md: By hand, and how a drag sets it"`
- [ ] **Step 5: live check** (the daemon reads `page.html` per request; a daemon restart is needed for the `sidebar.py` change — kill the python pid, never the wrapper, then relaunch per memory `project_plugin-hook-deploy-path`): drag in the hotkey window, drop, reload the panel, order kept; restart the daemon, order kept; Settings shows By hand.
- [ ] **Step 6:** whole suite once more; narrative entry; ask for the merge.
