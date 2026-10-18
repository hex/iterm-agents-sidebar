# Finished Marks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session that ends its turn while another pane has the eyes says so in its own iTerm2 pane (iTerm2's badge) and in the panel (lifted, washed green), each piece a setting, all cleared the moment the pane is focused.

**Architecture:** Every mark is a view of the existing `alerts.Unseen.sids` set. The daemon adds one pure band pass over the ordered rows after `unseen.step()`, and one marker that diffs the wanted set against the marked set and writes per-session profile fields through the iTerm2 API, restoring them on clear. The page adds a wash class and keeps banded cards out of the drag order. Settings gain one card.

**Tech Stack:** Python 3.11 daemon (`sidebar.py`, `alerts.py`, new `marks.py`), the iTerm2 Python API (`iterm2` package in iTerm2's own env), the single-file page `page.html`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-finished-marks-design.md`

## Global Constraints

- Mark text is exactly `Done` in the badge; the marker writes nothing else there. (Task 1 ruling: no title-bar mark; the subtitle does not render.)
- A profile field already non-empty (badge text) or already on (`use_tab_color`) is the user's: not written, logged once as `<field> busy <sid8>`.
- Only top-level cards (no `depth`, no `worktree_of`, no `partner_of`) are marked or banded; a block moves with its lead.
- Settings keys and defaults: `finished_first` true, `finished_wash` true, `mark_badge` true, `mark_tab` false. All booleans, none nested.
- Dark wash `#1f2e22`, light wash `#e8f5ec`; the card border mixes toward `--sev-ok`. No inset ring on a washed card.
- No motion, no sound, no focus change from any of this. Clearing follows `Unseen` alone.
- Test python: the mise 3.11 python first on PATH (Homebrew's lacks pytest-asyncio); `--color=no` and judge by exit code.
- Specs and docs name nobody.

## Review Focus

1. A session that finishes and starts a new turn inside one poll: `Unseen` never marks it, so no pane write happens and no `have` entry is left. Test in Task 5 (`test_a_turn_that_restarted_before_the_poll_is_never_marked`).
2. The iTerm2 session object vanishes between `want` and the write (pane closed): the write raises, the marker drops the sid without an entry in `have`, nothing else in the rebuild fails. Test in Task 5.
3. A setting turned off while marks are showing: that channel's `want` empties and the next rebuild clears only that channel's fields, restoring the kept values. Test in Task 5.
4. Provider grouping on with the band: the band runs inside each provider run, never pulls a Codex card above the Claude heading. Test in Task 3.
5. The hand order with a banded card dragged past: the saved order keeps the banded name at its remembered index. Test in Task 4.

---

### Task 1: Live check of the pane marks (done: subtitle renders nowhere, badge renders)

**Files:**
- Create: `tests/live/pane_marks_check.py` (manual, not collected by pytest: `tests/live/` has no `test_` files)
- Modify: `docs/superpowers/specs/2026-10-18-finished-marks-design.md` only if the check fails

**Interfaces:**
- Produces: a recorded answer in the spec's decision list: subtitle shows in the pane title bar, or falls back to tab level.

- [ ] **Step 1: Write the script** after the shape of the tab-colour test: `iterm2.run_until_complete(main)`, a new `Window`, one vertical split, `LocalWriteOnlyProfile().set_subtitle("Done")` written to the background pane with `async_set_profile_properties`, a `screencapture -R` of the window frame to the path given as `sys.argv[1]`, then `async_close(force=True)`. Run with iTerm2's own python (`~/Library/Application Support/iTerm2/iterm2env-*/versions/*/bin/python3`) and `ITERM2_COOKIE` from `osascript -e 'tell application "iTerm2" to request cookie'`.

- [ ] **Step 2: Run it and read the screenshot** with the Read tool. Expected: the word `Done` under the background pane's title in its own title bar. If it shows only in the tab bar, edit the spec's second decision bullet and section 3 "Title bar" to say the mark is tab-level, and say why.

- [ ] **Step 3: Commit**

```bash
git add tests/live/pane_marks_check.py docs/superpowers/specs/2026-10-18-finished-marks-design.md
git commit -m "Live check: the badge reaches a split pane, the subtitle does not"
```

### Task 2: Settings

**Files:**
- Modify: `sidebar.py:118-160` (`DEFAULT_SETTINGS`)
- Modify: `page.html:6474-6500` (`SETTING_ROWS`)
- Modify: `README.md` settings table, `docs/usage.md` settings section (names only; prose comes in Task 6)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `load_settings()[k]` for `finished_first`, `finished_wash`, `mark_badge`, `mark_tab`; the page's `SETTINGS.<k>`.

- [ ] **Step 1: Write the failing test** in `tests/test_settings.py`:

```python
def test_the_finished_settings_default_to_pane_marks_on_and_tab_colour_off(tmp_path):
    s = sidebar.load_settings(tmp_path / "none.json")
    assert {k: s[k] for k in ("finished_first", "finished_wash", "mark_badge", "mark_tab")} == \
        {"finished_first": True, "finished_wash": True, "mark_badge": True, "mark_tab": False}
```

- [ ] **Step 2: Run** `pytest tests/test_settings.py -k finished --color=no -q`. Expected: FAIL, KeyError.
- [ ] **Step 3: Add the four keys** to `DEFAULT_SETTINGS` after `return_after_blocked`, each with a one-line comment in the file's voice.
- [ ] **Step 4: Add the card** to `SETTING_ROWS` between the Focus rows and `{head: "Rows"}`: `{head: "Finished"}`, then `finished_first` "Finished first", `finished_wash` "Green wash", `mark_badge` "Badge in the pane", `mark_tab` "Tab colour". Plain switches, no `needs`.
- [ ] **Step 5: Name every label** in README's settings table and `docs/usage.md`, so `tests/test_docs.py::test_every_setting_is_named_in_the_docs` and `tests/test_figures.py::test_the_settings_figure_lists_every_setting_the_sheet_has` pass; regenerate `assets/settings.svg` with `python3 assets/make-settings.py`.
- [ ] **Step 6: Run** `pytest tests/test_settings.py tests/test_docs.py tests/test_figures.py --color=no -q`. Expected: PASS.
- [ ] **Step 7: Commit** `Settings: the Finished card, five switches`.

### Task 3: The band

**Files:**
- Modify: `sidebar.py` beside `by_attention` (~line 1010); `_rebuild_once` (~line 3787)
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces: `band(rows: list[dict], unseen: set[str], by_provider: bool) -> list[dict]`. Pure. Blocks via `_blocks`. A block's tier is its lead's: 0 when `state == "blocked"`, 1 when `state == "idle"` and `session_id in unseen`, else 2. Stable sort by tier inside each provider run when `by_provider` is true (a run is consecutive blocks sharing `provider`), else over all blocks. A tier 0 or 1 lead gets `row["band"] = "blocked" | "finished"` and loses `bucket` and `rested` (`pop`). Other rows untouched.
- Consumes: `Unseen.sids` from Task 0 (existing), `settings["finished_first"]`, `settings["provider_mark"] == "groups"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_snapshot.py` (rows built with the file's existing helpers):

```python
def test_the_band_lifts_blocked_then_unseen_finished_leads_and_keeps_the_rest_in_place():
    rows = [card("a", "idle"), card("b", "working"), card("c", "idle"), card("d", "blocked"), card("e", "idle")]
    out = sidebar.band(rows, unseen={"c", "e"}, by_provider=False)
    assert [r["session_id"] for r in out] == ["d", "c", "e", "a", "b"]
    assert [r.get("band") for r in out] == ["blocked", "finished", "finished", None, None]

def test_a_block_moves_with_its_lead():
    rows = [card("a", "idle"), card("b", "idle"), teammate("b1", of="b")]
    out = sidebar.band(rows, unseen={"b"}, by_provider=False)
    assert [r["session_id"] for r in out] == ["b", "b1", "a"]

def test_a_banded_lead_loses_its_attention_bucket_and_rest():
    row = card("a", "idle"); row["bucket"] = "idle"; row["rested"] = 2
    [out] = sidebar.band([row], unseen={"a"}, by_provider=False)
    assert "bucket" not in out and "rested" not in out

def test_the_band_stays_inside_a_provider_run():
    rows = [card("a", "idle", provider="claude"), card("b", "idle", provider="openai")]
    out = sidebar.band(rows, unseen={"b"}, by_provider=True)
    assert [r["session_id"] for r in out] == ["a", "b"]

def test_an_unseen_teammate_never_bands():
    rows = [card("a", "idle"), teammate("a1", of="a")]
    out = sidebar.band(rows, unseen={"a1"}, by_provider=False)
    assert [r.get("band") for r in out] == [None, None]
```

- [ ] **Step 2: Run** `pytest tests/test_snapshot.py -k band --color=no -q`. Expected: FAIL, no attribute `band`.
- [ ] **Step 3: Implement `band`** in `sidebar.py` after `by_provider`, with a docstring that names the exception to the terminal order's promise.
- [ ] **Step 4: Wire it** in `_rebuild_once`: after the `row["unseen"] = True` loop, when `settings["finished_first"]`, replace each group's rows with `band(group["rows"], self.unseen.sids, settings["provider_mark"] == "groups")` for the group named `AGENTS`.
- [ ] **Step 5: Run** `pytest tests/test_snapshot.py tests/test_rebuild.py --color=no -q`. Expected: PASS.
- [ ] **Step 6: Commit** `Band: blocked and unseen finished leads first, with their blocks`.

### Task 4: The page: wash, heads, drag order

**Files:**
- Modify: `page.html` CSS tokens (~lines 7-70), `.card.rested` rules (~274), the paint loop (~6195-6215), `shownNames`/`dropOrder` (~3236-3247)
- Test: `tests/test_page_unseen_mark.py`, `tests/test_page_contrast.py`

**Interfaces:**
- Consumes: `row.unseen`, `row.band`, `SETTINGS.finished_wash`, `SETTINGS.hand_order`.

- [ ] **Step 1: Write the failing tests** in `tests/test_page_unseen_mark.py`, in the file's source-regex style:

```python
def test_an_unseen_finished_card_wears_the_finished_class_when_the_wash_is_on():
    body = paint_source()
    assert 'if (row.unseen && row.state === "idle" && !row.depth && SETTINGS?.finished_wash !== false) li.classList.add("finished");' in body

def test_the_finished_wash_outranks_rest_and_has_no_ring():
    assert rule("li.line.card.finished") .index("background: var(--finished-bg)") >= 0
    assert "box-shadow" not in rule("li.line.card.finished")
    assert source().index("li.line.card.finished") > source().index("li.line.card.neglected")

def test_the_finished_tokens_are_the_specs_in_both_themes():
    assert "--finished-bg: #e8f5ec" in light_tokens() and "--finished-bg: #1f2e22" in dark_tokens()

def test_a_banded_card_keeps_its_remembered_index_in_the_drop_order():
    # shown, top first: x (banded), a, b; remembered: a, x, b, c
    assert drop_order(shown=[("x", "finished"), ("a", None), ("b", None)], remembered=["a", "x", "b", "c"]) == ["a", "x", "b", "c"]
    assert drop_order(shown=[("x", "finished"), ("a", None)], remembered=[]) == ["a", "x"]
```

`drop_order` evaluates the page's `dropOrder` under node with `topCards`, `cardRow` and `SETTINGS` stubbed, the way `tests/test_page_commands.py` evaluates page functions.

- [ ] **Step 2: Run** `pytest tests/test_page_unseen_mark.py --color=no -q`. Expected: FAIL.
- [ ] **Step 3: Add the tokens** `--finished-bg` to both theme blocks and the rule `li.line.card.finished { background: var(--finished-bg); border-color: color-mix(in srgb, var(--sev-ok) 45%, var(--card-border)); }` after `.neglected`; the hover rule follows the pattern the blocked card uses at lines 267-268 so the plain tint sits over the wash.
- [ ] **Step 4: Add the class** in the paint loop beside the `rested` line, exactly the condition in the test.
- [ ] **Step 5: Change `dropOrder`**: shown names without a `band` in DOM order; each shown banded name inserted at its index in `SETTINGS.hand_order` (appended when absent); then the remembered names not shown; dedupe; slice to `HAND_ORDER_MAX`.
- [ ] **Step 6: Check the heads need nothing**: `row.bucket` is popped by the daemon for banded rows, so the `run` filter at line 6208 already leaves them out. Add one assertion to the first test that the bucket head condition still reads `row.bucket && !row.depth`.
- [ ] **Step 7: Run** `pytest tests/test_page_unseen_mark.py tests/test_page_contrast.py tests/test_page_in_place.py --color=no -q`. Expected: PASS (contrast: `--fg` on both wash values clears the file's ratio).
- [ ] **Step 8: Commit** `Page: the finished wash, and banded cards keep their place in the hand order`.

### Task 5: The marker

**Files:**
- Create: `marks.py`
- Modify: `sidebar.py` `Bridge.__init__` (~3452), `_rebuild_once` after the band
- Test: `tests/test_marks.py`

**Interfaces:**
- Produces, in `marks.py`:
  - `FIELDS = ("badge_text", "use_tab_color", "tab_color")`
  - `def wanted(rows, unseen, settings) -> dict[str, set[str]]`: channel name (`badge`, `tab`) -> sids of top-level idle rows in `unseen`, only for channels whose setting is on.
  - `def plan(want: set[str], have: set[str]) -> tuple[set[str], set[str]]`: `(to_mark, to_clear)`.
  - `class Marker`: `have: dict[str, dict[str, Kept]]` sid -> channel -> kept values; `swept: bool`.
    - `async def step(self, app, rows, unseen, settings, log) -> None`: on first call runs `sweep(app, log)`; then per channel `plan` and `write`/`restore`.
    - `async def sweep(self, app, log)`: every session whose profile `badge_text == "Done"` gets it set to `""`; logs `swept <sid8> <field>`.
    - `async def write(self, session, channel, log) -> bool`: reads the profile, keeps the channel's fields, applies the busy rule (log `<field> busy <sid8>`, return False), writes `Done` / (`True`, `Color(48,209,88)`).
    - `async def restore(self, session, channel, log)`: writes the kept values back.
  - All iTerm2 calls wrapped: an exception drops the sid from `have` and logs `mark <channel> <sid8>: <error!r>`; the rebuild never fails for a mark.
- Consumes: `band` output rows (for `row["depth"]` etc.), `Unseen.sids`, `app.get_session_by_id`.

- [ ] **Step 1: Write the failing pure tests** in `tests/test_marks.py`:

```python
def test_plan_marks_the_new_and_clears_the_gone():
    assert marks.plan({"a", "b"}, {"b", "c"}) == ({"a"}, {"c"})

def test_wanted_takes_top_level_idle_unseen_rows_per_enabled_channel():
    rows = [card("a", "idle"), card("b", "working"), teammate("a1", of="a"), card("c", "idle")]
    want = marks.wanted(rows, {"a", "a1", "b", "c"}, {"mark_badge": True, "mark_tab": True})
    assert want == {"badge": {"a", "c"}, "tab": {"a", "c"}}

def test_a_turn_that_restarted_before_the_poll_is_never_marked():
    # Unseen drops a sid in `began`; wanted() only sees what Unseen kept
    u = alerts.Unseen(); u.step(ended={"a"}, began={"a"}, looking_at=None, states={"a": "working"})
    assert marks.wanted([card("a", "working")], u.sids, ALL_ON) == {}
```

Then the writer tests with a fake `session` whose `async_get_profile` returns an object with the three attributes and whose `async_set_profile_properties` records the `LocalWriteOnlyProfile` it got (read its `values` dict):

```python
async def test_write_keeps_the_fields_it_touches_and_restore_puts_them_back()
async def test_a_busy_badge_is_left_alone_and_logged_once()
async def test_a_session_that_vanishes_is_dropped_without_a_have_entry()
async def test_turning_a_channel_off_clears_only_that_channels_fields()
async def test_the_first_step_sweeps_a_done_left_by_a_dead_daemon()
```

Assert exact kept values and exact log lines.

- [ ] **Step 2: Run** `pytest tests/test_marks.py --color=no -q`. Expected: FAIL, no module `marks`.
- [ ] **Step 3: Implement `marks.py`** to the interface above. `Kept` is a dict of the channel's fields to the profile values read.
- [ ] **Step 4: Wire it**: `self.marks = marks.Marker()` in `Bridge.__init__`; in `_rebuild_once` after the band, `await self.marks.step(self.app, agent_rows, self.unseen.sids, settings, self.log)`.
- [ ] **Step 5: Run** `pytest tests/test_marks.py tests/test_rebuild.py --color=no -q`. Expected: PASS.
- [ ] **Step 6: Commit** `Marker: Done as the pane's badge, restored on focus`.

### Task 6: Docs and the figure

**Files:**
- Modify: `README.md` card-states table and settings table; `docs/usage.md` (order promise at line 38, a new Finished section); no title-bar mark anywhere; `assets/make-card-states.py` and `assets/card-states.svg`
- Test: `tests/test_docs.py`, `tests/test_figures.py`

- [ ] **Step 1: Write the failing figure test** in `tests/test_figures.py`: the card-states SVG contains a rect filled `#1f2e22` behind a card whose badge reads `Done`.
- [ ] **Step 2: Run** `pytest tests/test_figures.py --color=no -q`. Expected: FAIL.
- [ ] **Step 3: Draw the wash** on the Done card in `make-card-states.py`, regenerate, update the README alt text and the row "Finished while you looked elsewhere" to say the card is washed green and lifted under any waiting card, and its pane carries `Done` as iTerm2's badge.
- [ ] **Step 4: Write the Finished section** in `docs/usage.md`: the four settings, the clearing rule, the tmux limit (plain tmux marks the whole pane), the tab-colour limit (active pane only), the busy rule, the startup sweep. Add to the order table's terminal row: "With Finished first on, a blocked or finished card is lifted to the top until answered or focused; turn it off for the promise in full."
- [ ] **Step 5: Run** `pytest tests/test_docs.py tests/test_figures.py --color=no -q`. Expected: PASS.
- [ ] **Step 6: Commit** `Docs: finished marks, where they show and where they cannot`.

### Task 7: Live end-to-end run

**Files:**
- Create: `tests/live/finished_marks.py`

**Interfaces:**
- Consumes: the running daemon (restart it after Task 5: kill the python pid, never the wrapper's, then the osascript launch), `agents-sidebar wait`.

- [ ] **Step 1: Write the script**: opens a throwaway window with two splits, writes a hook state file for the background split's session id (the shape `tests/test_state.py` builds) that goes working then idle while the other split is active, polls the daemon's `/events` snapshot, and reads the pane's profile. No real agent runs; the state file is the turn. Expected sequence printed as PASS/FAIL lines: `marked badge`, `card finished`, `card banded`; then it activates the pane and expects `cleared badge`, `card plain`, each within 5 s. Screenshots before and after to `sys.argv[1]`. Closes the window.
- [ ] **Step 2: Run it** with iTerm2's python and the cookie. Expected: every line PASS, exit 0. Read both screenshots.
- [ ] **Step 3: Run the whole suite** with the mise python: `pytest --color=no -q`. Expected: exit 0.
- [ ] **Step 4: Commit** `Live check: finished marks appear in the pane and clear on focus`.
- [ ] **Step 5: Record** the run in the spec's section 7 with the date and the screenshot paths' basenames.
