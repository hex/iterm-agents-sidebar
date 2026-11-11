# API Credits Fallback Implementation Plan

> **For agentic workers:** one owner builds this task by task, test first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When every account is full, running sessions move to prepaid API credits through `apiKeyHelper`, behind one off-by-default setting, and move back at the first reading that shows room, with a notice and a Not now before each flip.

**Architecture:** One persisted record in the status folder is the fallback's whole state, and one pure function, `api_fallback.step(record, reading, now)`, moves it and names the effects. The daemon builds the reading after each meter tick, runs the step on the event loop, carries out the effects (notice, helper in, helper out, log line) and saves the record before it touches `~/.claude/settings.json`. `statusline.py` owns the key-only settings edit. The panel and the hooks only read the record or send answers to the daemon.

**Tech Stack:** Python 3 stdlib, pytest, `page.html` (vanilla DOM, Phosphor icons), the `agents-notifier` sender, `security` for the Keychain, `urllib` for one `GET /v1/models`.

**Spec:** `docs/superpowers/specs/2026-11-09-api-fallback-design.md` (approved, rulings 1 to 6).

## Global Constraints

- stdlib only; no new dependency.
- Constants: `NOTICE_GRACE_SECONDS = 60`, `EXIT_ASK_AGAIN_SECONDS = 1800`, `ACTIVE_SESSION_SECONDS = 300` (sessions whose context counts toward the re-read figure), `SWITCH_THRESHOLD` imported from `accounts.py`, never copied.
- Settings: `api_fallback` (bool, default `False`), `api_fallback_cap_usd` (positive number, default `50`). Both go in `DEFAULT_SETTINGS` with validation in `_clean`, or `_clean` drops them.
- Keychain item: service `agents-sidebar-accounts`, account `api-key`. The key is written over stdin, never argv, and never returned by any route, snapshot, log line or hook. The page sees the last four characters only.
- Never write the real `~/.claude/settings.json` or the real Keychain item in a test. Settings tests use `tmp_path` files; Keychain tests use a throwaway keychain created first (a missing keychain path falls through to the login keychain, task #481). The conftest autouse fixture must redirect the record path along with `STATUS_DIR`.
- TDD in vertical slices: one failure from the list, its test, watch it fail, then the code. Expected values are literals from the spec or this plan, never recomputed by the code under test.
- Fixtures use `alice`, `bob`, `example.com`, `acct-N`, `sk-ant-test-…` only.
- Every source file keeps its `ABOUTME:` opening lines; comments say what the code does, never what it used to do.
- Run tests with a Python that has pytest-asyncio first on `PATH` (`python3 -m pytest -q --color=no ...`); judge by the exit code.
- Panel taste: no left accent bars, plain tint hovers, Phosphor icons only, one badge style at every width, decoration never gets a row on the card face.
- Docs and this plan ship publicly: they name no person and no other tool.
- Work on branch `feat/api-fallback`.

## Throughput checkpoint

- **Blocking first steps.** Task 1 (the structured `blocked` reason) and Task 2 (the record and `step`) fix the shapes every later task reads. Nothing else starts before both are green.
- **Independent workstreams.** Tasks 3 (settings writer) and 4 (key and helper script) touch disjoint files and could run beside Task 2. Tasks 5 to 9 all touch `sidebar.py` or `page.html`.
- **Shared mutable state.** `sidebar.py`, `page.html` and the docs are shared by Tasks 5 to 10, so they serialize. At run time the record has one writer, the daemon's event loop; routes and notice answers queue an input for the next step and never write the record themselves.
- **Smallest safe decomposition.** One owner, tasks in order. The feature is code-coupled through one record and one snapshot field; a second worker would only contend for `sidebar.py`.

## The record

`api_fallback.py` owns it. Stored as `STATUS_DIR/api-fallback.json`, replaced by rename.

```python
{
  "phase": "off" | "entering" | "on" | "leaving",
  "deadline": float | None,        # entering/leaving: when the grace ends
  "since": float | None,           # on/leaving: when entry happened
  "ask_again_at": float | None,    # on: a Not now on the way out
  "hold": None | {"reason": "not_now" | "cap" | "billing_error" | "authentication_failed"
                            | "refused" | "helper_gone", "at": float, "why": str},
  "baseline": {session_id: cost_usd},   # each Claude session's total_cost_usd at entry
  "seen": {session_id: cost_usd},       # highest total_cost_usd seen since entry
  "flips": int,                    # entries plus exits, for the agent context line
  "last4": str | None,             # of the stored key
}
```

A missing or unreadable record loads as `off` with no hold, and the log says when it was unreadable.

The reading the daemon builds for each step:

```python
{
  "enabled": bool, "cap_usd": float, "key_stored": bool,
  "blocked": None | "full" | "model_full" | "unreadable",   # switch_decision of the active account, no gates
  "room": bool,       # active binding figure < SWITCH_THRESHOLD, or a "switch" to a non-needsLogin account
  "helper": "ours" | "absent" | "foreign" | "unreadable",   # what settings.json holds now
  "costs": {session_id: total_cost_usd},                    # Claude sessions on the cards now
  "stop_failures": [error, ...],    # StopFailure errors seen since the last step
  "answer": None | "not_now",       # from the notice or the panel
}
```

`step` transitions, each a test:

| From | When | To | Effects |
|---|---|---|---|
| off, no hold | enabled, key stored, blocked in {full, model_full}, helper not foreign | entering, deadline now+60 | entry notice |
| off, hold | `room` | off, no hold | none |
| off, hold cap | cap raised above spent | off, no hold | none |
| entering | answer not_now | off, hold not_now | notice down |
| entering | `room`, or blocked becomes None or unreadable | off | notice down |
| entering | deadline passed, still due | on, since=now, baseline=costs, flips+1 | helper in, log |
| on | `room` and now ≥ ask_again_at | leaving, deadline now+60 | exit notice |
| on | spent > cap | off, hold cap | helper out, notice, log |
| on | stop_failures has billing_error or authentication_failed | off, hold with that reason | helper out, notice, log |
| on | helper absent | off, hold helper_gone | log only, no write |
| on | enabled turned off | off, no hold | helper out, log |
| leaving | answer not_now | on, ask_again_at now+1800 | notice down |
| leaving | `room` gone | on | notice down |
| leaving | deadline passed | off, flips+1 | helper out, log |

"Helper in" is carried out by the daemon as: validate the key (`GET /v1/models`), check the helper is not foreign, write. A failure calls `api_fallback.refused(record, why, now)`: off with hold `refused`. Saving a key lifts a `refused` hold. The spend estimate is `sum(seen[s] - baseline.get(s, 0))`; `seen` only grows, so a session that ends keeps its share.

## Files

- `accounts.py`: `switch_decision`'s `blocked` gains `"reason"`; `AccountMeters.fallback_view(now)` returns what the reading needs, under the meters lock.
- `api_fallback.py` (new): record, `load`/`save`, `step`, `refused`, `key_saved`, `spent`, Keychain read/write/delete, `validate_key`.
- `api-key-helper.sh` (new, repo root): prints the Keychain item.
- `statusline.py`: `api_key_helper_state`, `set_api_key_helper`, `drop_api_key_helper`.
- `sidebar.py`: settings defaults, the step loop in `watch_accounts`, reconcile at start, `POST /api-fallback` (`not_now`, `save_key`, `forget_key`), the fallback notice in `Notices`, snapshot `api_fallback`, StopFailure pickup.
- `plugin/hooks/hooks.json`, `plugin/hooks-handlers/emit-state.py`: StopFailure; the context line.
- `page.html`: Accounts section of the settings card; the fold head's chip.
- `uninstall.sh`: helper out when ours; key deleted unless logins are kept.
- `tests/test_api_fallback.py`, `tests/test_api_fallback_settings.py`, `tests/test_api_fallback_key.py`, `tests/test_page_api_fallback.py` (new); `tests/test_autoswitch.py`, `tests/test_settings.py`, `tests/test_uninstall.py`, `tests/test_emit_state.py` extended.
- `tests/live/api_fallback_check.py` (new).
- `README.md`, `docs/accounts.md`, `docs/usage.md`, `docs/integrations.md`, `docs/troubleshooting.md`, `docs/development.md`.

---

### Task 1: `blocked` says why in a field

**Files:** `accounts.py` (`switch_decision`), `tests/test_autoswitch.py`

- [ ] Test: every account full gives `{"act": "blocked", "reason": "full", ...}`; a model full everywhere gives `"model_full"`; an unreadable other account gives `"unreadable"`. Existing `why` strings unchanged.
- [ ] Add the field at the three return sites. Run `tests/test_autoswitch.py`.
- [ ] Commit.

### Task 2: The record and `step`

**Files:** create `api_fallback.py`, `tests/test_api_fallback.py`

**Interfaces:** `load(path) -> record`, `save(path, record)`, `step(record, reading, now) -> (record, effects)` where effects are dicts `{"do": "notice", "which": "entry"|"exit"|"cap"|"billing_error"|"authentication_failed"|"helper_gone", ...}`, `{"do": "notice_down"}`, `{"do": "helper_in"}`, `{"do": "helper_out"}`, `{"do": "log", "line": str}`; `refused(record, why, now)`, `key_saved(record, last4)`, `spent(record) -> float`.

Failure list, one test each, in this order:

- [ ] `unreadable` never starts entry.
- [ ] Off with the setting off, or no key, never starts entry.
- [ ] One account, auto-switch off: `blocked: "full"` from the gate-free decision starts entry.
- [ ] Entry waits the grace: at deadline − 1 s still `entering`, no `helper_in`.
- [ ] Not now during entry holds until `room`; a blocked reading in between does not re-enter.
- [ ] A foreign helper never starts entry.
- [ ] Exit waits for `room`; `room` false with every account still above 90 keeps `on`.
- [ ] Exit Not now asks again only after 1800 s.
- [ ] Cap: spent 50.01 against cap 50 leaves at once with hold `cap`; the next blocked tick does not re-enter; a cap raised to 60 lifts the hold.
- [ ] `billing_error` and `authentication_failed` leave at once and hold; a StopFailure while `off` changes nothing.
- [ ] Helper gone while `on` goes off with hold `helper_gone` and emits no `helper_out`.
- [ ] Spend never shrinks: a session that leaves `costs` keeps its share; a session first seen after entry counts from 0.
- [ ] `refused` holds; `key_saved` lifts a `refused` hold and no other.
- [ ] An unreadable record file loads as off and reports it.
- [ ] Commit after each green pair of slices.

### Task 3: The key-only settings edit

**Files:** `statusline.py`, create `tests/test_api_fallback_settings.py`

**Interfaces:** `api_key_helper_state(path, helper) -> "ours"|"absent"|"foreign"|"unreadable"`; `set_api_key_helper(path, helper)` and `drop_api_key_helper(path, helper)`, each raising `ValueError` with the reason when refused.

- [ ] A foreign `apiKeyHelper` is never changed by either call; the error names it.
- [ ] Every other key is written back as read, including ones added by hand.
- [ ] Read back after the write; a mismatch retries once from a fresh read; a second mismatch raises and leaves the file as it is (test with a writer injected between write and read-back).
- [ ] Settings that are not JSON: refused, file untouched.
- [ ] `drop` with no helper writes nothing (mtime unchanged).
- [ ] Commit.

### Task 4: The key and the helper script

**Files:** `api_fallback.py`, create `api-key-helper.sh`, `tests/test_api_fallback_key.py`, `sidebar.py` (settings defaults), `tests/test_settings.py`

- [ ] Settings: `api_fallback` defaults to `false`; `api_fallback_cap_usd` defaults to `50`; a non-number, zero or negative cap is dropped to the default.
- [ ] `store_key` writes over stdin to a throwaway keychain and reads back; `forget_key` deletes; absent is fine.
- [ ] `validate_key` against a local `http.server` stand-in: 200 accepted, 401 refused with "the key was refused (401)", a timeout refused with its reason. The real endpoint is checked only in Task 9's live script.
- [ ] A key that is not `sk-ant-` text is refused before any call.
- [ ] `api-key-helper.sh` prints the item and nothing else, exits non-zero when it is absent; `set -euo pipefail`.
- [ ] Commit.

### Task 5: The daemon runs the step

**Files:** `accounts.py` (`fallback_view`), `sidebar.py`, `tests/test_meter_loop.py` or a new loop test

- [ ] `fallback_view` returns the gate-free `switch_decision` for the active account and `room` read from the binding figure; a `read` decision or a stale active reading gives `room: False` and `blocked: None`.
- [ ] `watch_accounts` builds the reading after each tick, runs `step`, saves the record, then carries out the effects. The record is saved before settings.json changes.
- [ ] Reconcile at start: record not `on` and helper ours → helper out; record `on` and helper absent → off, hold `helper_gone`.
- [ ] `POST /api-fallback` with `op` in `not_now`, `save_key` (validates, stores, `key_saved`), `forget_key`; each queues input for the next step and triggers one. The key never appears in a response or the log.
- [ ] Snapshot `api_fallback: {phase, deadline, since, spent_usd, cap_usd, hold, last4, reread_tokens}`; `reread_tokens` sums the context figures of Claude sessions active in the last 300 s.
- [ ] The fallback notice: `agents-notifier post --id api-fallback` with a Not now button, registered in `Notices` under `api-fallback` so a response read by any sender routes to it; `answer` turns the button into `not_now`. Posted only while the `notify` setting is on.
- [ ] Commit.

### Task 6: StopFailure and the agent's line

**Files:** `plugin/hooks/hooks.json`, `plugin/hooks-handlers/emit-state.py`, `sidebar.py`, `tests/test_emit_state.py`

- [ ] `StopFailure` registered to the existing handler; it stores `{"stop_failure": {"error": ..., "at": ...}}` in the session's state document under its lock.
- [ ] The daemon collects stop failures newer than its last step into the reading.
- [ ] `UserPromptSubmit` adds the spec's line once per flip per session: the record's `flips` against the session's last told value, kept in its state document. Subagents never get it. Nothing when the record is missing.
- [ ] Commit.

### Task 7: The panel

**Files:** `page.html`, create `tests/test_page_api_fallback.py`

- [ ] Settings card, Accounts section: the switch "When every account is full, use API credits", a password field for the key with Save, the last four once saved and Forget, the cap in dollars, and the live note naming `apiKeyHelper` in `~/.claude/settings.json` and that the file may be synced to other machines. The switch is disabled until a key is saved.
- [ ] Accounts fold head, in place of the next-switch chip: `entering`/`leaving` show "→ API in 42 s" or "→ subscription in 42 s" with a Not now button; `on` shows "on API · $1.84" with a title naming what is off (claude.ai connectors and Remote Control); a hold or refusal shows in the alert colour with its reason. The chip shows with one account too.
- [ ] The switch line records each entry and exit.
- [ ] Screenshots at 380 and 250 px, light and dark, with a fixture snapshot per phase; a WKWebView shot of the settings section for descenders.
- [ ] Regenerate any figure the settings section appears in.
- [ ] Commit.

### Task 8: Uninstall

**Files:** `uninstall.sh`, `tests/test_uninstall.py`

- [ ] The helper comes out when it is ours; a foreign one stays and the line says so.
- [ ] The key is deleted unless logins are kept.
- [ ] The record goes with the status folder.
- [ ] Commit.

### Task 9: Live checks

**Files:** create `tests/live/api_fallback_check.py`

- [ ] Against a scratch `CLAUDE_CONFIG_DIR`: helper absent → `apiKeySource: none`; `set_api_key_helper` mid-session → `apiKeyHelper`; `drop_api_key_helper` → `none`.
- [ ] A bad key through a test helper: `StopFailure` with `authentication_failed` (slow, about 4 minutes; behind a flag).
- [ ] With the real key, one Haiku turn and `validate_key` returning accepted; skipped, and said so, when no key is stored.
- [ ] Prints a summary a reader can rerun; commit the script only.

### Task 10: Docs

- [ ] `docs/accounts.md`: the fallback, entry, exit, holds, the cap, the record file.
- [ ] `docs/usage.md`: the settings section and the chip's states.
- [ ] `docs/integrations.md`: the `apiKeyHelper` write as the exception to the settings rule, read back and retried once, never a foreign helper.
- [ ] `docs/troubleshooting.md`: refused key, foreign helper, helper gone, cap reached, credits out.
- [ ] `docs/development.md`: `api_fallback.py`, `api-key-helper.sh`, the record in the status folder list.
- [ ] `README.md`: one feature line and the privacy write list.
- [ ] `tests/test_docs.py` passes; Vale on changed prose.
- [ ] Full suite, exit 0. Commit.
