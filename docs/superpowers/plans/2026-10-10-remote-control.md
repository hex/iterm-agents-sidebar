# Remote Control Kept Across Switches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the panel switches accounts, Claude sessions that had Remote Control on get it back once idle (experimental setting, off by default), and every Claude card shows whether its session has Remote Control on.

**Architecture:** A new daemon module `remote.py` reads each Claude session's `~/.claude/sessions/<pid>.json`, notices a panel switch through `meters.last_switch["at"]`, owes a turn back on to every session that had it on just before, and asks the session's mod through `remote-control.json` in its links folder. The mod (`plugin/hooks/link.tsx`, its existing one-second `tick`) takes the file once, waits until its own state file says idle, checks Remote Control is still off, and runs `$.command.run({command: "remote-control"})`, filing the outcome. The frame carries `remote` per row; the page draws a glyph after the name and, when it did not come back, a line.

**Tech Stack:** Python 3 stdlib (daemon), TypeScript Claude Code mod (`claude plugin test`), plain JS page (headless Chrome E2E over CDP), iTerm2 Python API for the live E2E.

**Spec:** `docs/superpowers/specs/2026-10-10-remote-control-design.md` (approved 5221192, §7 checks at 6fa9eee). Read it before any task.

## Global Constraints

- Build on a new branch `feat/remote-control` off `spec/remote-control`.
- Claude sessions only. Codex and omp rows always carry `remote: null`.
- Nothing is ever typed into a pane, and the pane's screen is never read. Remote Control state comes only from `~/.claude/sessions/<pid>.json`.
- The ask file names no command. The command `remote-control` is fixed in the mod.
- Files in a session's links folder `~/.claude/agents-sidebar-links/<session id>/`: `remote-control.json` (daemon writes: `{"switch_at": float, "expires": float}`), `remote-control-taken.json` (mod, by `mv`), `remote-control-result.json` (mod writes: `{"switch_at": float, "outcome": "done" | "already-on" | "failed", "reason": str}`). All `0600`, written whole (daemon: `links.write_file`; mod: `writeWhole`), read with `links.read_json` / `readJson`.
- Windows: 120 s for a drop after a switch (`DROP_SECONDS`), 300 s ask life (`EXPIRE_SECONDS`), 30 s more for a taken ask to be answered (`ANSWER_GRACE`), 120 s to connect after `done` (`CONNECT_SECONDS`), 600 s for the line (`LOST_SECONDS`).
- A state file with no `bridgeSessionId` key, or `null`, reads **off**; a non-empty string **on**; anything else **unknown** (spec §2, §7 check 2).
- The setting key is `keep_remote`, default `False`. Label "Keep remote control after a switch"; note "When the panel switches accounts, sessions that had remote control on get it back once they are idle, under the account switched to."
- The line's text is exactly "Remote control did not come back: run /remote-control".
- The mark: Phosphor regular `broadcast`, 11 px, `var(--fg)`, after the name, 35 % opacity for `"reconnecting"`, no animation.
- Log lines (daemon.log through `Bridge.log`): `remote control back on “‹label›” after the switch`, `remote control did not come back on “‹label›”: ‹reason›`, and once per pid and fault `remote control: ‹path›: ‹fault›`.
- Python tests: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/ -q --color=no` (Homebrew python lacks pytest-asyncio; judge by the exit code).
- Mod tests: `~/.local/bin/claude plugin test plugin` from the repo root. Delete `plugin/tsconfig.json` if a `--plugin-dir` run laid one.
- Every new code file starts with two `ABOUTME:` lines. No emoji. Docs, specs and plans name no person. Never name another sidebar tool.
- The page's endless motion stays transform and opacity only (`tests/test_page_motion_cost.py`); this feature adds none.

## Review Focus

1. **Ticks overlapping a running command**: `$.command.run` takes about 4 s and the tick fires every second; a second run would open the Remote Control menu in the session. Must run once (test in Task 3: ticks during a pending run).
2. **`/clear` between the drop and the mod's tick**: the session id changes, so an untaken ask must move to the new id's folder (test in Task 1).
3. **Another `claude` started in the owed pane**: a different `agent_pid` forgets the entry, so the new session is never turned on (test in Task 1).
4. **A reading taken after the switch, or already off before it**: neither makes a session owed (tests in Task 1).
5. **A long card name**: the glyph stays visible and still while the name fades and glides (E2E in Task 4).

---

### Task 1: The keeper (`remote.py`)

**Files:**
- Create: `remote.py`
- Test: `tests/test_remote.py`

**Interfaces:**
- Consumes: `links.LINKS_DIR`, `links.write_file(root, agent, name, payload)`, `links.read_json(root, agent, name) -> dict | None`, `links.session_dir(root, agent, make=False)`, `links.Refused`, `links.quoted(label) -> str`.
- Produces:
  - `remote.SESSIONS_DIR: Path`, `STATE_MAX = 65536`, `DROP_SECONDS = 120`, `EXPIRE_SECONDS = 300`, `ANSWER_GRACE = 30`, `CONNECT_SECONDS = 120`, `LOST_SECONDS = 600`, `ASK`, `TAKEN`, `RESULT` (file names)
  - `@dataclass(frozen=True) class Reading: state: str; at: float; fault: str | None = None`
  - `read_state(path, pid: int, now: float) -> Reading`
  - `read_all(directory, pids: dict[str, int], now: float) -> dict[str, Reading]`
  - `class Keeper(root=None)`: `step(ends: dict[str, dict], readings: dict[str, Reading], switch_at: float | None, on: bool, now: float) -> list[str]`; `remote(pane: str) -> str | None` (`"on"`, `"reconnecting"`, `"lost"` or `None`). `ends` maps a pane to `{"agent": session id, "agent_pid": int, "label": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# ABOUTME: Tests for remote.py: reading a session's Remote Control from its state file, owing it back after a panel
# ABOUTME: switch, the ask and result files in the session's folder, and what each card shows. Values come from the spec.
import json
import os

import pytest

import links
import remote

PID = 4242


def state_file(tmp_path, pid=PID, **fields):
    path = tmp_path / f"{pid}.json"
    path.write_text(json.dumps({"pid": pid, "sessionId": "s-1", "status": "idle", **fields}))
    return path


def test_a_string_bridge_reads_on_and_a_null_or_absent_one_off(tmp_path):
    assert remote.read_state(state_file(tmp_path, bridgeSessionId="session_01x"), PID, 5.0) == remote.Reading("on", 5.0)
    assert remote.read_state(state_file(tmp_path, bridgeSessionId=None), PID, 5.0) == remote.Reading("off", 5.0)
    assert remote.read_state(state_file(tmp_path), PID, 5.0) == remote.Reading("off", 5.0)


def test_a_missing_file_reads_unknown_with_no_fault(tmp_path):
    assert remote.read_state(tmp_path / "9.json", 9, 5.0) == remote.Reading("unknown", 5.0)


@pytest.mark.parametrize("text, fault", [
    ('{"pid": 4242, "bridgeSess', "not whole JSON"),
    ("[1, 2]", "not a JSON object"),
    ('{"pid": 77, "bridgeSessionId": "session_01x"}', "pid 77, not 4242"),
    ('{"pid": 4242, "bridgeSessionId": 3}', "bridgeSessionId 3"),
    ('{"pid": 4242, "bridgeSessionId": ""}', "bridgeSessionId ''"),
])
def test_a_file_claude_code_would_not_write_reads_unknown_and_names_the_fault(tmp_path, text, fault):
    (tmp_path / f"{PID}.json").write_text(text)
    assert remote.read_state(tmp_path / f"{PID}.json", PID, 5.0) == remote.Reading("unknown", 5.0, fault)


def test_a_symlinked_or_oversized_state_file_reads_unknown(tmp_path):
    real = state_file(tmp_path, pid=1, bridgeSessionId="session_01x")
    os.symlink(real, tmp_path / f"{PID}.json")
    assert remote.read_state(tmp_path / f"{PID}.json", PID, 5.0).state == "unknown"
    big = tmp_path / "8.json"
    big.write_text(json.dumps({"pid": 8, "pad": "x" * remote.STATE_MAX}))
    assert remote.read_state(big, 8, 5.0) == remote.Reading("unknown", 5.0, f"{big.stat().st_size} bytes, over {remote.STATE_MAX}")


def test_read_all_reads_each_panes_own_pid(tmp_path):
    state_file(tmp_path, pid=1, bridgeSessionId="session_01x")
    state_file(tmp_path, pid=2)
    assert remote.read_all(tmp_path, {"p1": 1, "p2": 2}, 5.0) == {"p1": remote.Reading("on", 5.0),
                                                                    "p2": remote.Reading("off", 5.0)}


ON, OFF = "on", "off"
END = {"agent": "a-id", "agent_pid": PID, "label": "alpha"}


def r(state, at):
    return {"p1": remote.Reading(state, at)}


def keeper_owing(tmp_path):
    """A keeper with remote control on in p1 before a switch at 100, read off at 101: the ask is filed."""
    k = remote.Keeper(tmp_path)
    assert k.step({"p1": END}, r(ON, 90.0), None, True, 90.0) == []
    assert k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0) == []
    return k


def ask(tmp_path, agent="a-id"):
    path = tmp_path / agent / remote.ASK
    return json.loads(path.read_text()) if path.exists() else None


def test_a_session_on_before_a_switch_and_off_after_it_is_asked_to_turn_it_back_on(tmp_path):
    k = keeper_owing(tmp_path)
    assert ask(tmp_path) == {"switch_at": 100.0, "expires": 401.0}
    assert oct((tmp_path / "a-id" / remote.ASK).stat().st_mode & 0o777) == "0o600"
    assert k.remote("p1") == "reconnecting"


def test_back_on_clears_the_debt_and_logs_one_line(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(ON, 106.0), 100.0, True, 106.0) == ["remote control back on “alpha” after the switch"]
    assert k.remote("p1") == "on"
    assert k.step({"p1": END}, r(ON, 107.0), 100.0, True, 107.0) == []


def test_a_session_off_before_the_switch_is_owed_nothing(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(OFF, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_a_reading_taken_after_the_switch_does_not_make_a_session_owed(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(ON, 100.5), None, True, 100.5)
    k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0)
    assert ask(tmp_path) is None


def test_a_switch_that_keeps_remote_control_owes_nothing_after_two_minutes(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(ON, 101.0), 100.0, True, 101.0)
    k.step({"p1": END}, r(ON, 221.0), 100.0, True, 221.0)
    k.step({"p1": END}, r(OFF, 230.0), 100.0, True, 230.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_with_the_setting_off_nothing_is_owed_and_an_untaken_ask_is_taken_back(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(OFF, 102.0), 100.0, False, 102.0) == []
    assert ask(tmp_path) is None and k.remote("p1") is None
    k.step({"p1": END}, r(OFF, 103.0), 100.0, True, 103.0)
    assert ask(tmp_path) is None


def test_another_agent_in_the_pane_forgets_the_debt(tmp_path):
    k = keeper_owing(tmp_path)
    k.step({"p1": {**END, "agent_pid": 5555}}, r(OFF, 102.0), 100.0, True, 102.0)
    assert ask(tmp_path) is None and k.remote("p1") is None


def test_a_clear_moves_an_untaken_ask_to_the_new_conversation(tmp_path):
    k = keeper_owing(tmp_path)
    k.step({"p1": {**END, "agent": "a2-id"}}, r(OFF, 102.0), 100.0, True, 102.0)
    assert ask(tmp_path) is None
    assert ask(tmp_path, "a2-id") == {"switch_at": 100.0, "expires": 401.0}


def result(tmp_path, outcome, switch_at=100.0, reason="", agent="a-id"):
    links.write_file(tmp_path, agent, remote.RESULT, {"switch_at": switch_at, "outcome": outcome, "reason": reason})


def test_a_failed_result_shows_the_line_and_logs_the_reason(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", reason="the session did not go idle")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == [
        "remote control did not come back on “alpha”: the session did not go idle"]
    assert k.remote("p1") == "lost"
    assert not (tmp_path / "a-id" / remote.RESULT).exists()


def test_already_on_clears_the_debt_without_a_line(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "already-on")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.remote("p1") is None


def test_a_result_for_another_switch_is_dropped_unread(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", switch_at=55.0, reason="old")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.remote("p1") == "reconnecting"
    assert not (tmp_path / "a-id" / remote.RESULT).exists()


def test_done_but_still_off_two_minutes_later_is_lost(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "done")
    assert k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0) == []
    assert k.step({"p1": END}, r(OFF, 230.0), 100.0, True, 230.0) == []
    assert k.step({"p1": END}, r(OFF, 231.0), 100.0, True, 231.0) == [
        "remote control did not come back on “alpha”: it ran /remote-control but did not connect"]


def test_an_ask_never_taken_is_lost_when_it_expires(tmp_path):
    k = keeper_owing(tmp_path)
    assert k.step({"p1": END}, r(OFF, 401.0), 100.0, True, 401.0) == []
    assert k.step({"p1": END}, r(OFF, 402.0), 100.0, True, 402.0) == [
        "remote control did not come back on “alpha”: the session never took it; is the agents-sidebar plugin loaded there?"]
    assert ask(tmp_path) is None


def test_an_ask_taken_and_never_answered_is_lost_after_the_grace(tmp_path):
    k = keeper_owing(tmp_path)
    os.rename(tmp_path / "a-id" / remote.ASK, tmp_path / "a-id" / remote.TAKEN)
    assert k.step({"p1": END}, r(OFF, 431.0), 100.0, True, 431.0) == []
    assert k.step({"p1": END}, r(OFF, 432.0), 100.0, True, 432.0) == [
        "remote control did not come back on “alpha”: the session took it and never answered"]


def lost_keeper(tmp_path):
    k = keeper_owing(tmp_path)
    result(tmp_path, "failed", reason="x")
    k.step({"p1": END}, r(OFF, 110.0), 100.0, True, 110.0)
    return k


def test_the_line_clears_when_remote_control_comes_back_or_after_ten_minutes(tmp_path):
    k = lost_keeper(tmp_path)
    k.step({"p1": END}, r(ON, 120.0), 100.0, True, 120.0)
    assert k.remote("p1") == "on"
    k = lost_keeper(tmp_path)
    k.step({"p1": END}, r(OFF, 710.0), 100.0, True, 710.0)
    assert k.remote("p1") == "lost"
    k.step({"p1": END}, r(OFF, 711.0), 100.0, True, 711.0)
    assert k.remote("p1") is None


def test_the_line_clears_when_the_pane_goes(tmp_path):
    k = lost_keeper(tmp_path)
    k.step({}, {}, 100.0, True, 120.0)
    assert k.remote("p1") is None


def test_a_second_switch_before_the_drop_restarts_the_window(tmp_path):
    k = remote.Keeper(tmp_path)
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    k.step({"p1": END}, r(ON, 101.0), 100.0, True, 101.0)
    k.step({"p1": END}, r(ON, 201.0), 200.0, True, 201.0)
    k.step({"p1": END}, r(OFF, 300.0), 200.0, True, 300.0)
    assert ask(tmp_path) == {"switch_at": 200.0, "expires": 600.0}


def test_a_fault_is_logged_once_per_pid_and_fault(tmp_path):
    k = remote.Keeper(tmp_path)
    bad = {"p1": remote.Reading("unknown", 1.0, "not whole JSON")}
    line = f"remote control: {remote.SESSIONS_DIR}/{PID}.json: not whole JSON"
    assert k.step({"p1": END}, bad, None, True, 1.0) == [line]
    assert k.step({"p1": END}, bad, None, True, 2.0) == []


def test_a_links_folder_that_is_a_symlink_loses_the_debt_with_the_reason(tmp_path):
    k = remote.Keeper(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "a-id")
    k.step({"p1": END}, r(ON, 90.0), None, True, 90.0)
    assert k.step({"p1": END}, r(OFF, 101.0), 100.0, True, 101.0) == [
        "remote control did not come back on “alpha”: its links folder: the links folder for a-id is not a plain directory"]
    assert k.remote("p1") == "lost"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_remote.py -q --color=no`
Expected: collection error, `ModuleNotFoundError: No module named 'remote'`.

- [ ] **Step 3: Write `remote.py`**

```python
# ABOUTME: Remote Control kept across account switches: reads each Claude session's state file, owes a turn back on
# ABOUTME: to sessions a panel switch dropped, asks their mod through a file, and says on the card how it went.
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import links

SESSIONS_DIR = Path(os.path.expanduser("~/.claude/sessions"))
STATE_MAX = 64 * 1024
#: A switch that has not dropped Remote Control by then never will.
DROP_SECONDS = 120
#: The ask's life in the session's folder; the mod gives up waiting for idle at the same moment.
EXPIRE_SECONDS = 300
#: How long a taken ask may go unanswered past its expiry.
ANSWER_GRACE = 30
#: After the mod ran the command.
CONNECT_SECONDS = 120
#: How long the card says it did not come back.
LOST_SECONDS = 600
ASK = "remote-control.json"
TAKEN = "remote-control-taken.json"
RESULT = "remote-control-result.json"


@dataclass(frozen=True)
class Reading:
    #: "on", "off" or "unknown".
    state: str
    at: float
    fault: str | None = None


def read_state(path, pid, now):
    """One session's Remote Control from its state file. A missing file reads unknown with no fault; a file that is
    not what Claude Code writes reads unknown with the fault named."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return Reading("unknown", now)
    except OSError as error:
        return Reading("unknown", now, f"cannot open: {error.strerror}")
    with os.fdopen(descriptor, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode):
            return Reading("unknown", now, "not a plain file")
        if info.st_size > STATE_MAX:
            return Reading("unknown", now, f"{info.st_size} bytes, over {STATE_MAX}")
        try:
            value = json.loads(f.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Reading("unknown", now, "not whole JSON")
    if not isinstance(value, dict):
        return Reading("unknown", now, "not a JSON object")
    if value.get("pid") != pid:
        return Reading("unknown", now, f"pid {value.get('pid')!r}, not {pid}")
    bridge = value.get("bridgeSessionId")
    if bridge is None:
        return Reading("off", now)
    if isinstance(bridge, str) and bridge:
        return Reading("on", now)
    return Reading("unknown", now, f"bridgeSessionId {bridge!r}")


def read_all(directory, pids, now):
    """pane -> its Reading, from the state file of the pane's agent pid."""
    return {pane: read_state(Path(directory) / f"{pid}.json", pid, now) for pane, pid in pids.items()}


@dataclass
class Owed:
    agent_pid: int
    #: The conversation seen at the switch, then the one the ask sits with.
    agent: str
    switch_at: float
    filed_at: float | None = None
    done_at: float | None = None


@dataclass
class Lost:
    agent_pid: int
    since: float


class Keeper:
    """Who is owed Remote Control after a panel switch, and whose did not come back. In memory: a daemon restart
    forgets both, and the card then shows only what the state file says."""

    def __init__(self, root=None):
        self.root = Path(root or links.LINKS_DIR)
        #: pane -> Reading, from the last step: the readings a new switch is judged by.
        self.readings = {}
        self.owed = {}
        self.lost = {}
        self.switch_seen = None
        self.faults_said = set()

    def step(self, ends, readings, switch_at, on, now):
        """Moves everything on by one rebuild. `ends` maps each Claude pane to {"agent", "agent_pid", "label"};
        `readings` are this rebuild's; `switch_at` is the last panel switch's time or None. -> log lines."""
        lines = []
        for pane, reading in readings.items():
            pid = ends[pane]["agent_pid"]
            if reading.fault and (pid, reading.fault) not in self.faults_said:
                self.faults_said.add((pid, reading.fault))
                lines.append(f"remote control: {SESSIONS_DIR}/{pid}.json: {reading.fault}")
        if not on:
            for owed in self.owed.values():
                self._unlink(owed.agent, ASK)
            self.owed.clear()
            self.lost.clear()
        elif switch_at is not None and switch_at != self.switch_seen:
            for owed in self.owed.values():
                if owed.filed_at is None:
                    owed.switch_at = switch_at
            for pane, before in self.readings.items():
                end = ends.get(pane)
                if end and pane not in self.owed and before.state == "on" and before.at < switch_at:
                    self.owed[pane] = Owed(end["agent_pid"], end["agent"], switch_at)
        self.switch_seen = switch_at
        self.readings = dict(readings)
        for pane in list(self.owed):
            end = ends.get(pane)
            try:
                lines += self._step_owed(pane, end, readings.get(pane), now)
            except (links.Refused, OSError) as error:
                lines += self._lose(pane, end, f"its links folder: {error}", now)
        for pane, lost in list(self.lost.items()):
            end, reading = ends.get(pane), readings.get(pane)
            if (end is None or end["agent_pid"] != lost.agent_pid or (reading is not None and reading.state == "on")
                    or now - lost.since > LOST_SECONDS):
                del self.lost[pane]
        return lines

    def remote(self, pane):
        """What the card shows: "on", "reconnecting", "lost" or None."""
        if pane in self.lost:
            return "lost"
        reading = self.readings.get(pane)
        if reading is not None and reading.state == "on":
            return "on"
        owed = self.owed.get(pane)
        return "reconnecting" if owed is not None and owed.filed_at is not None else None

    def _step_owed(self, pane, end, reading, now):
        owed = self.owed[pane]
        if end is None or end["agent_pid"] != owed.agent_pid:
            self._unlink(owed.agent, ASK)
            del self.owed[pane]
            return []
        if reading is not None and reading.state == "on" and owed.filed_at is not None:
            del self.owed[pane]
            self._unlink(end["agent"], RESULT)
            return [f"remote control back on {links.quoted(end['label'])} after the switch"]
        if owed.filed_at is None:
            if reading is not None and reading.state == "off":
                links.write_file(self.root, end["agent"], ASK, {"switch_at": owed.switch_at, "expires": now + EXPIRE_SECONDS})
                owed.agent, owed.filed_at = end["agent"], now
            elif now - owed.switch_at > DROP_SECONDS:
                del self.owed[pane]
            return []
        if end["agent"] != owed.agent:
            moved = links.read_json(self.root, owed.agent, ASK)
            if moved is not None:
                links.write_file(self.root, end["agent"], ASK, moved)
                self._unlink(owed.agent, ASK)
            owed.agent = end["agent"]
        answer = links.read_json(self.root, end["agent"], RESULT)
        if answer is not None:
            self._unlink(end["agent"], RESULT)
            if answer.get("switch_at") == owed.switch_at:
                if answer.get("outcome") == "already-on":
                    del self.owed[pane]
                    return []
                if answer.get("outcome") == "done":
                    owed.done_at = now
                elif answer.get("outcome") == "failed":
                    return self._lose(pane, end, str(answer.get("reason") or "the session could not run it"), now)
        if owed.done_at is not None:
            if now - owed.done_at > CONNECT_SECONDS:
                return self._lose(pane, end, "it ran /remote-control but did not connect", now)
        elif now - owed.filed_at > EXPIRE_SECONDS:
            if links.read_json(self.root, end["agent"], ASK) is not None:
                self._unlink(end["agent"], ASK)
                return self._lose(pane, end, "the session never took it; is the agents-sidebar plugin loaded there?", now)
            if now - owed.filed_at > EXPIRE_SECONDS + ANSWER_GRACE:
                return self._lose(pane, end, "the session took it and never answered", now)
        return []

    def _lose(self, pane, end, reason, now):
        owed = self.owed.pop(pane)
        self.lost[pane] = Lost(owed.agent_pid, now)
        label = links.quoted(end["label"]) if end else links.quoted(pane)
        return [f"remote control did not come back on {label}: {reason}"]

    def _unlink(self, agent, name):
        try:
            (links.session_dir(self.root, agent) / name).unlink(missing_ok=True)
        except links.Refused:
            pass
```

- [ ] **Step 4: Run the tests until they pass**

Run: the command from Step 2. Expected: all pass, exit 0. Two expected values depend on facts to confirm while doing this: `oct(...) == "0o600"` (from `links.write_file`'s mode) and the symlink refusal text (from `links.session_dir`, which says "the links folder for ‹agent› is not a plain directory"). If a test's expectation disagrees with the code, read the spec and fix whichever is wrong; never loosen an assertion.

- [ ] **Step 5: Check the tests can fail**

Apply each mutant by hand, run the file, see at least one test fail, and revert:
1. `before.at < switch_at` -> `before.at <= switch_at + 10` (expect `test_a_reading_taken_after_the_switch...` to fail).
2. Drop the `if end["agent"] != owed.agent:` block (expect `test_a_clear_moves...`).
3. `end["agent_pid"] != owed.agent_pid` -> `False` in `_step_owed` (expect `test_another_agent...`).
4. `if bridge is None:` -> `if bridge is None and "bridgeSessionId" in value:` (expect `test_a_string_bridge...`).
Record which test caught each in the commit body.

- [ ] **Step 6: Commit**

```bash
git add remote.py tests/test_remote.py
git commit -m "remote.py: read Remote Control from each session's state file and owe it back after a panel switch"
```

---

### Task 2: The daemon (`sidebar.py`): setting, readings each rebuild, `remote` on each row

**Files:**
- Modify: `sidebar.py` (`DEFAULT_SETTINGS` after `"links"`, `import remote`, `Bridge.__init__` beside `self.partners`, `_rebuild_once` after `self.step_links(...)`, a new `Bridge.step_remote`)
- Test: `tests/test_rebuild.py`

**Interfaces:**
- Consumes: Task 1's `remote.read_all`, `remote.SESSIONS_DIR`, `remote.Keeper`; `self.meters.last_switch` (`{"at", "from", "to", "why", "auto"}` or `None`, set by `accounts.Meters._switch_locked` on both switch paths); inner rows' `provider`, `agent_pid`, `conversation`.
- Produces: `DEFAULT_SETTINGS["keep_remote"] = False`; `Bridge.keeper: remote.Keeper`; every frame row carries `remote` (`"on" | "reconnecting" | "lost" | None`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_rebuild.py`, beside the `linking` fixture)

```python
def remoting(monkeypatch, tmp_path, keep=True):
    """A Bridge over one Claude card (pid 4242, conversation a-id), a Codex card and a shell, with remote control
    kept after a switch unless `keep` says otherwise, its state files in tmp_path / "sessions"."""
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    monkeypatch.setattr(sidebar.remote, "SESSIONS_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir()
    sidebar.save_settings({"keep_remote": keep})
    frame = {"groups": [{"name": "AGENTS", "rows": [
        {"session_id": "p1", "label": "alpha", "state": "idle", "depth": 0},
        {"session_id": "p2", "label": "bravo", "state": "idle", "depth": 0, "provider": "openai"}]},
        {"name": "SESSIONS", "rows": [{"session_id": "p3", "label": "zsh", "depth": 0}]}]}
    inner = [{"session_id": "p1", "provider": "claude", "conversation": "a-id", "agent_pid": 4242, "rollout": None},
             {"session_id": "p2", "provider": "openai", "conversation": "b-id", "agent_pid": 5353, "rollout": None},
             {"session_id": "p3", "provider": None, "conversation": None, "agent_pid": None, "rollout": None}]
    monkeypatch.setattr(sidebar, "snapshot", lambda *_, **__: json.loads(json.dumps(frame)))
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    b = sidebar.Bridge(None, Quiet())
    b.app = NoWindows()
    b.meters = types.SimpleNamespace(last_switch=None, snapshot=lambda: {})

    async def read_sessions():
        b.rows = inner
        return inner
    b.read_sessions = read_sessions
    b.links = sidebar.links.Book(tmp_path / "links")
    b.keeper = sidebar.remote.Keeper(tmp_path / "links")
    return b


def set_bridge(tmp_path, pid, bridge):
    (tmp_path / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, "bridgeSessionId": bridge}))


def remotes(b):
    return {row["session_id"]: row["remote"] for group in b.latest["groups"] for row in group["rows"]}


def test_each_claude_row_says_whether_remote_control_is_on_and_no_other_row_does(monkeypatch, tmp_path):
    b = remoting(monkeypatch, tmp_path)
    set_bridge(tmp_path, 4242, "session_01x")
    set_bridge(tmp_path, 5353, "session_01y")
    asyncio.run(b._rebuild_once())
    assert remotes(b) == {"p1": "on", "p2": None, "p3": None}
    set_bridge(tmp_path, 4242, None)
    asyncio.run(b._rebuild_once())
    assert remotes(b) == {"p1": None, "p2": None, "p3": None}


def test_a_panel_switch_that_drops_remote_control_asks_the_session_back_and_marks_it_reconnecting(monkeypatch, tmp_path):
    b = remoting(monkeypatch, tmp_path)
    set_bridge(tmp_path, 4242, "session_01x")
    asyncio.run(b._rebuild_once())
    b.meters.last_switch = {"at": time.time(), "from": "acct-1", "to": "acct-2", "why": None, "auto": False}
    set_bridge(tmp_path, 4242, None)
    asyncio.run(b._rebuild_once())
    assert remotes(b)["p1"] == "reconnecting"
    asked = json.loads((tmp_path / "links" / "a-id" / "remote-control.json").read_text())
    assert asked["switch_at"] == b.meters.last_switch["at"]
    set_bridge(tmp_path, 4242, "session_01z")
    asyncio.run(b._rebuild_once())
    assert remotes(b)["p1"] == "on"
    logged = [line.split(" ", 2)[2] for line in (tmp_path / "daemon.log").read_text().splitlines()]
    assert logged[-1] == "remote control back on “alpha” after the switch"


def test_with_the_setting_off_a_switch_owes_nothing_but_the_mark_still_shows(monkeypatch, tmp_path):
    b = remoting(monkeypatch, tmp_path, keep=False)
    set_bridge(tmp_path, 4242, "session_01x")
    asyncio.run(b._rebuild_once())
    assert remotes(b)["p1"] == "on"
    b.meters.last_switch = {"at": time.time(), "from": "acct-1", "to": "acct-2", "why": None, "auto": True}
    set_bridge(tmp_path, 4242, None)
    asyncio.run(b._rebuild_once())
    assert remotes(b)["p1"] is None
    assert not (tmp_path / "links" / "a-id" / "remote-control.json").exists()


def test_the_state_files_are_read_off_the_event_loop(monkeypatch, tmp_path):
    b = remoting(monkeypatch, tmp_path)
    threads = []
    real = sidebar.remote.read_all
    monkeypatch.setattr(sidebar.remote, "read_all", lambda *a: (threads.append(threading.current_thread()), real(*a))[1])
    asyncio.run(b._rebuild_once())
    assert threads and threads[0] is not threading.main_thread()


def test_keep_remote_starts_off():
    assert sidebar.DEFAULT_SETTINGS["keep_remote"] is False
```

Add `import threading`, `import time` and `import types` at the top of the file if missing.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_rebuild.py -q --color=no -k "remote or keep_remote"`
Expected: FAIL, `AttributeError: module 'sidebar' has no attribute 'remote'`.

- [ ] **Step 3: Implement**

In `DEFAULT_SETTINGS`, after the `"links": False,` entry:

```python
    # Experimental: after the panel switches accounts, Claude sessions that had
    # Remote Control on get it back once idle.
    "keep_remote": False,
```

Beside `import partners`: `import remote`. In `Bridge.__init__`, after the partners block:

```python
        #: Who is owed Remote Control after a panel switch, and whose did not come back.
        self.keeper = remote.Keeper()
```

In `_rebuild_once`, right after `self.step_links(settings["links"])`:

```python
        await self.step_remote(settings["keep_remote"])
```

And the method, after `step_links`:

```python
    async def step_remote(self, keep):
        """Reads each Claude session's Remote Control off the loop, moves the keeper on, and puts `remote` on every
        row: what the card's mark and line show."""
        labels = {row["session_id"]: row.get("label") or row["session_id"]
                  for group in self.latest["groups"] for row in group["rows"]}
        ends = {row["session_id"]: {"agent": row["conversation"], "agent_pid": row["agent_pid"],
                                    "label": labels.get(row["session_id"], row["session_id"])}
                for row in self.rows
                if row.get("provider") == "claude" and row.get("agent_pid") and row.get("conversation")}
        now = time.time()
        readings = await asyncio.to_thread(remote.read_all, remote.SESSIONS_DIR,
                                           {pane: end["agent_pid"] for pane, end in ends.items()}, now)
        switch = self.meters.last_switch if self.meters is not None else None
        for line in self.keeper.step(ends, readings, switch["at"] if switch else None, keep, now):
            self.log(line)
        for group in self.latest["groups"]:
            for row in group["rows"]:
                row["remote"] = self.keeper.remote(row["session_id"]) if row["session_id"] in ends else None
```

- [ ] **Step 4: Run the new tests, then the whole suite**

Run Step 2's command, then the full suite (Global Constraints). Expected: all pass. Existing rebuild fixtures build inner rows without `agent_pid`; those rows get `remote: None`, so no other test changes. If one fails, read why before touching it.

- [ ] **Step 5: Commit**

```bash
git add sidebar.py tests/test_rebuild.py
git commit -m "Daemon: remote on every row, and Remote Control owed back after a panel switch (keep_remote, off by default)"
```

---

### Task 3: The mod turns it back on (`plugin/hooks/link.tsx`)

**Files:**
- Modify: `plugin/hooks/link.tsx` (module state beside `band`, two functions after `readDrop`, one call in `tick`)
- Test: `plugin/hooks/link.test.tsx`

**Interfaces:**
- Consumes: the daemon's `remote-control.json` (Task 1's `ASK`); the session's `~/.claude/sessions/<pid>.json` (`sessionId`, `status`, `bridgeSessionId`); the mod's own `folderFor`, `readJson`, `writeWhole`, `succeeded`, `home`.
- Produces: `remote-control-taken.json` (by `mv`), `remote-control-result.json` `{switch_at, outcome, reason}` (Task 1 reads it).

- [ ] **Step 1: Write the failing tests** (append to `link.test.tsx`; extend `world` as shown)

In `World` add `commands: string[]`, `commandFails: string | null`, `hold: boolean` and `release: () => void`; initialise them (`commands: []`, `commandFails: null`, `hold: false`, `release: () => {}`). In `world(on)`, add one handler (one per event, as for every other engine call here):

```tsx
  // The session's own state file says Remote Control is on once the command has run, as Claude Code's does.
  // With `hold` set the command stays running until the test calls `release`.
  on('command.run', async ($, e) => {
    w.commands.push(e.command)
    if (w.hold) await new Promise<void>(resolve => { w.release = resolve })
    if (w.commandFails) throw new Error(w.commandFails)
    w.files.set(STATE, JSON.stringify({ ...JSON.parse(w.files.get(STATE) ?? '{}'), bridgeSessionId: 'session_01x' }))
    return { text: '' }
  })
```

Then the tests:

```tsx
const STATE = `${HOME}/.claude/sessions/4242.json`
const ASKED = `${F}/remote-control.json`
const RESULT = `${F}/remote-control-result.json`

function remoteAsk(w: World, expires = 2000) {
  w.files.set(ASKED, JSON.stringify({ switch_at: 100, expires }))
}

function sessionState(w: World, status: string, bridge: string | null = null, id = 'sess-1') {
  w.files.set(STATE, JSON.stringify({ pid: 4242, sessionId: id, status, bridgeSessionId: bridge }))
}

test('an idle session with remote control off runs /remote-control once and files done', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'idle')
  remoteAsk(w)
  await clock.advance(1000)
  expect(w.commands).toEqual(['remote-control'])
  expect(JSON.parse(w.files.get(RESULT)!)).toEqual({ switch_at: 100, outcome: 'done', reason: '' })
  expect(w.files.has(ASKED)).toBe(false)
  expect(w.files.has(`${F}/remote-control-taken.json`)).toBe(false)
  await clock.advance(3000)
  expect(w.commands).toEqual(['remote-control'])
})

test('ticks while the command is still running never run it a second time', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  w.hold = true
  await start($)
  sessionState(w, 'idle')
  remoteAsk(w)
  await clock.advance(4000)
  expect(w.commands).toEqual(['remote-control'])
  w.release()
  await clock.advance(1000)
  expect(w.commands).toEqual(['remote-control'])
})

test('a busy session waits, and runs the command once it is idle', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'busy')
  remoteAsk(w, 1_000_000)
  await clock.advance(5000)
  expect(w.commands).toEqual([])
  sessionState(w, 'idle')
  await clock.advance(1000)
  expect(w.commands).toEqual(['remote-control'])
})

test('a session waiting on a prompt counts as not idle', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'waiting')
  remoteAsk(w, 1_000_000)
  await clock.advance(3000)
  expect(w.commands).toEqual([])
})

test('remote control already on files already-on and opens no menu', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'idle', 'session_01x')
  remoteAsk(w)
  await clock.advance(1000)
  expect(w.commands).toEqual([])
  expect(JSON.parse(w.files.get(RESULT)!)).toEqual({ switch_at: 100, outcome: 'already-on', reason: '' })
})

test('a session busy until the ask expires files failed', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'busy')
  remoteAsk(w, 1_003)
  await clock.advance(1000)
  expect(w.files.has(RESULT)).toBe(false)
  await clock.advance(3000)
  expect(JSON.parse(w.files.get(RESULT)!)).toEqual({ switch_at: 100, outcome: 'failed', reason: 'the session did not go idle' })
})

test('a command that is refused files failed with its message', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'idle')
  w.commandFails = 'not now'
  remoteAsk(w)
  await clock.advance(1000)
  expect(JSON.parse(w.files.get(RESULT)!).outcome).toBe('failed')
  expect(JSON.parse(w.files.get(RESULT)!).reason).toContain('not now')
})

test('no state file naming this session files failed', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'idle', null, 'someone-else')
  remoteAsk(w)
  await clock.advance(1000)
  expect(w.commands).toEqual([])
  expect(JSON.parse(w.files.get(RESULT)!)).toEqual({ switch_at: 100, outcome: 'failed', reason: 'no session state file' })
})

test('an expired or half-written ask is removed and nothing runs', async ($, on) => {
  const w = world(on)
  const clock = mock.clock(on, { now: 1_000_000 })
  await start($)
  sessionState(w, 'idle')
  remoteAsk(w, 999)
  await clock.advance(1000)
  expect(w.files.has(ASKED)).toBe(false)
  w.files.set(ASKED, '{"switch_at": 1')
  await clock.advance(1000)
  expect(w.commands).toEqual([])
  expect(w.files.has(RESULT)).toBe(false)
  expect(w.files.has(ASKED)).toBe(true)
})
```

A half-written ask is left where it is for the next tick; only a whole, expired one is removed.

- [ ] **Step 2: Run them to see them fail**

Run: `~/.local/bin/claude plugin test plugin`
Expected: the new tests fail (`w.commands` stays `[]`); the existing ones pass.

- [ ] **Step 3: Implement** (in `link.tsx`)

Beside the module's other state (`band`, `asked`):

```tsx
// Remote Control the daemon asked this session to turn back on after an account switch: taken once, run when idle.
let remote: { switchAt: number; expires: number; running: boolean } | null = null
```

After `readDrop`:

```tsx
// This session's state file under ~/.claude/sessions, found by its session id, which /clear changes in the same file.
async function ownState($: EngineInterface): Promise<any> {
  const dir = `${home}/.claude/sessions`
  const id = await $.session.id()
  for (const entry of await $.fs.list(dir)) {
    if (!entry.name.endsWith('.json')) continue
    const state = await readJson($, `${dir}/${entry.name}`)
    if (state && state.sessionId === id) return state
  }
  return null
}

async function remoteDone($: EngineInterface, path: string, outcome: string, reason: string): Promise<void> {
  const job = remote
  remote = null
  if (!job) return
  await writeWhole($, 'remote-control-result.json', { switch_at: job.switchAt, outcome, reason })
  await succeeded($, ['rm', '-f', `${path}/remote-control-taken.json`])
}

// Turns Remote Control back on when the daemon asks: never while a turn runs or a prompt waits, never when it is
// already on (the command would open its menu instead), and never twice for one ask.
async function keepRemote($: EngineInterface, path: string, now: number): Promise<void> {
  if (!remote) {
    const file = `${path}/remote-control.json`
    const asked = await readJson($, file)
    if (!asked || typeof asked.switch_at !== 'number' || typeof asked.expires !== 'number') return
    if (!(asked.expires * 1000 >= now)) {
      await succeeded($, ['rm', '-f', file])
      return
    }
    if (!(await succeeded($, ['mv', file, `${path}/remote-control-taken.json`]))) return
    remote = { switchAt: asked.switch_at, expires: asked.expires, running: false }
  }
  if (remote.running) return
  const state = await ownState($)
  if (!state) return remoteDone($, path, 'failed', 'no session state file')
  if (state.status !== 'idle') {
    if (now > remote.expires * 1000) await remoteDone($, path, 'failed', 'the session did not go idle')
    return
  }
  if (typeof state.bridgeSessionId === 'string' && state.bridgeSessionId) return remoteDone($, path, 'already-on', '')
  remote.running = true
  try {
    await $.command.run({ command: 'remote-control' })
  } catch (error) {
    return remoteDone($, path, 'failed', String(error))
  }
  await remoteDone($, path, 'done', '')
}
```

In `tick`, after `const now = await $.clock.now()`:

```tsx
  await keepRemote($, path, now)
```

- [ ] **Step 4: Run the kit until it passes, then type-check**

Run: `~/.local/bin/claude plugin test plugin`. Expected: every test passes. If `on('command.run', ...)` in a test does not answer the mod's `$.command.run` the way `prompt.submit` is answered, read the testing types (`.claude-plugin/types/claude-code/testing`) for how a test answers an engine call and adjust `world`, not the mod.

- [ ] **Step 5: Check the tests can fail**

Mutants, one at a time, reverted after: drop `if (remote.running) return` (expect the overlapping-ticks test to fail); `state.status !== 'idle'` -> `state.status === 'busy'` (expect the waiting test); remove the `already-on` line (expect that test). Record in the commit body.

- [ ] **Step 6: Commit**

```bash
git add plugin/hooks/link.tsx plugin/hooks/link.test.tsx
git commit -m "Mod: turn Remote Control back on when the daemon asks, once idle and only while off"
```

---

### Task 4: The page: mark, line, setting row, figure

**Files:**
- Modify: `page.html` (`META_ICONS`, CSS beside `.ptag`, the row builder after `stack.append(label)`, the line beside `refusalLine`, `SETTING_ROWS`)
- Modify: `assets/settings.svg` (redrawn), `tests/test_figures.py` (count), `README.md` (figure alt text if the test asks)
- Create: `.cs/local/e2e_remote_mark.mjs` (session file, not committed)

**Interfaces:**
- Consumes: frame rows' `remote` (Task 2); `SETTINGS.keep_remote`.
- Produces: `span.name` wrapping `.label` and `svg.remote-mark` (`.reconnecting` when dimmed); `p.refusal.remote-lost`.

- [ ] **Step 1: Write the E2E first** (`.cs/local/e2e_remote_mark.mjs`)

Base it on `.cs/local/rc_variants.mjs` (CDP over the headless Chrome on port 9445, live panel URL from `~/.local/share/agents-sidebar/endpoint.json`, 380 px, `deviceScaleFactor: 2`). After load: `events.onmessage = () => {}; events.close()`, then take `LATEST`, set fields on the first AGENTS row with `structuredClone`, and call `render(snap)`. Checks, each printed `ok`/`FAIL` with the measured value, exit 1 on any FAIL:

1. `remote: "on"` -> `button.row .name > svg.remote-mark` exists, computed opacity `"1"`, width 11 px, its left edge 5-7 px after the `.label`'s right edge.
2. `remote: "reconnecting"` -> same glyph, opacity `"0.35"`.
3. `remote: null` -> no `.remote-mark`, no `.name` wrapper.
4. `remote: "lost"` -> no glyph; `li.line.card > p.refusal.remote-lost` with text exactly `Remote control did not come back: run /remote-control`, `role="status"`.
5. `remote: "on"` with `label` set to 90 characters -> `.label.clipped` present; the glyph's right edge stays left of the row's badge room (`row.right - getComputedStyle(row).getPropertyValue("--badge-room")` px); sample the glyph's `getBoundingClientRect().left` every 250 ms for 6 s: one value only (the name glides, the glyph does not).
6. `remote: "on"` -> the row button's `aria-label` contains `remote control on`; `"reconnecting"` -> `remote control reconnecting`.
7. Settings sheet: open with `gear.click()`; the Experimental card lists "Keep remote control after a switch" with the note text from Global Constraints.
8. Repeat 1 and 4 with `prefers-color-scheme: light`.

Run it: `node .cs/local/e2e_remote_mark.mjs "$(curl -s http://127.0.0.1:9445/json/version | python3 -c 'import json,sys;print(json.load(sys.stdin)["webSocketDebuggerUrl"])')"`. Expected before the page change: checks 1, 2, 4, 5, 6, 7 FAIL. The page is served from the working tree, so no restart is needed.

- [ ] **Step 2: Implement in `page.html`**

`META_ICONS`, a new entry (Phosphor regular `broadcast`, from `@phosphor-icons/core` `assets/regular/broadcast.svg`):

```js
  remote: '<path d="M128,88a40,40,0,1,0,40,40A40,40,0,0,0,128,88Zm0,64a24,24,0,1,1,24-24A24,24,0,0,1,128,152Zm73.71,7.14a80,80,0,0,1-14.08,22.2,8,8,0,0,1-11.92-10.67,63.95,63.95,0,0,0,0-85.33,8,8,0,1,1,11.92-10.67,80.08,80.08,0,0,1,14.08,84.47ZM69,103.09a64,64,0,0,0,11.26,67.58,8,8,0,0,1-11.92,10.67,79.93,79.93,0,0,1,0-106.67A8,8,0,1,1,80.29,85.34,63.77,63.77,0,0,0,69,103.09ZM248,128a119.58,119.58,0,0,1-34.29,84,8,8,0,1,1-11.42-11.2,103.9,103.9,0,0,0,0-145.56A8,8,0,1,1,213.71,44,119.58,119.58,0,0,1,248,128ZM53.71,200.78A8,8,0,1,1,42.29,212a119.87,119.87,0,0,1,0-168,8,8,0,1,1,11.42,11.2,103.9,103.9,0,0,0,0,145.56Z"/>',
```

The path is the downloaded file's (`curl -sL https://unpkg.com/@phosphor-icons/core/assets/regular/broadcast.svg`); compare before pasting.

CSS, after the `.ptag svg` rule:

```css
  /* Remote Control on: a glyph after the name, outside the name's clip and fade,
     so a long name fades before it and glides without it. Dimmed while the panel
     is bringing it back after an account switch. */
  .name {
    display: flex; align-items: center; gap: 6px; min-width: 0;
    max-width: calc(100% - var(--badge-room, 0px));
  }
  .name > .label { max-width: 100%; min-width: 0; }
  .remote-mark { flex: none; width: 11px; height: 11px; color: var(--fg); }
  .remote-mark.reconnecting { opacity: .35; }
```

Row builder: replace `stack.append(label);` with

```js
      // Remote Control on in this session, from its own state file: a glyph after the name.
      if (row.remote === "on" || row.remote === "reconnecting") {
        const glyph = metaIcon("remote");
        glyph.classList.remove("mi");
        glyph.classList.add("remote-mark");
        if (row.remote === "reconnecting") glyph.classList.add("reconnecting");
        glyph.dataset.spoken = row.remote === "on" ? "remote control on" : "remote control reconnecting";
        const name = Object.assign(document.createElement("span"), {className: "name"});
        name.append(label, glyph);
        stack.append(name);
      } else {
        stack.append(label);
      }
```

Check that the `[data-spoken]` collection for the button's `aria-label` runs after this point (it does: it reads `b.querySelectorAll` when the row is finished).

Beside `refusalLine`:

```js
// The line under a card whose Remote Control did not come back after an account switch.
function remoteLostLine(row) {
  if (row.remote !== "lost") return null;
  const line = Object.assign(document.createElement("p"), {className: "refusal remote-lost",
                             textContent: "Remote control did not come back: run /remote-control"});
  line.setAttribute("role", "status");
  return line;
}
```

Where the card's lines are appended (`const refusal = refusalLine(row.session_id);`), add `const lost = remoteLostLine(row);` and append it right after `refusal` in both places: `if (lost) b.after(lost);` in the teammate branch, just before `if (refusal) b.after(refusal);` (each `after` lands right under the row, so the lost line ends up last), and `if (lost) li.append(lost);` after `if (refusal) li.append(refusal);`.

`SETTING_ROWS`, after the `links` row:

```js
  {k: "keep_remote",  label: "Keep remote control after a switch",
   note: "When the panel switches accounts, sessions that had remote control on get it back once they are idle, under the account switched to."},
```

- [ ] **Step 3: Run the E2E until it passes, both themes**

Expected: 8/8 ok. Then the link, drag and partner E2Es that exercise the row builder: `node .cs/local/e2e_link_arm.mjs`, `node .cs/local/e2e_drag_order.mjs`, `node .cs/local/e2e_partner_pair.mjs` (each as its header says); all must still pass.

- [ ] **Step 4: Redraw the settings figure and run the page tests**

Run: `python3 assets/make-settings.py`, then change `assert len(labels) == 28` to `29` in `tests/test_figures.py`, then `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_figures.py tests/test_docs.py tests/test_page_motion_cost.py -q --color=no`. If the README alt-text test fails, copy the new `aria-label` from `assets/settings.svg` into the README's alt text for that figure. Expected: all pass. Look at `assets/settings.svg` (rendered with `qlmanage -t` or a browser) to see the new row and its note.

- [ ] **Step 5: Commit**

```bash
git add page.html assets/settings.svg tests/test_figures.py README.md
git commit -m "Page: the remote control glyph after the name, the line when it did not come back, and the Experimental setting"
```

---

### Task 5: Docs, install, live check, review

**Files:**
- Modify: `docs/usage.md`, `docs/integrations.md`, `docs/development.md`, `README.md`
- Create: `.cs/local/e2e_remote_live.py` (session file, not committed)

- [ ] **Step 1: Docs**

- `docs/usage.md`: a "Remote control" section after "Linking two sessions": the glyph after a Claude card's name (solid on, dimmed while the panel brings it back), the line and what to type, the Experimental setting with its note text, that it acts only after a switch the panel makes and only for sessions that had it on, that it turns it back on under the account switched to, and that a disconnect you make in the two minutes after a switch Claude Code did not drop it for is undone.
- `docs/integrations.md`: in the files table and the links-folder section, the three files with who writes each, and that the daemon reads `~/.claude/sessions/<pid>.json` (fields `pid`, `bridgeSessionId`) for every Claude row.
- `docs/development.md`: `remote.py` in the module list; the three files in the links-folder list.
- `README.md`: the Experimental row of the settings table names both settings.

Run `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_docs.py -q --color=no`; expected pass.

- [ ] **Step 2: Full suite and kit**

Run the full Python suite and `~/.local/bin/claude plugin test plugin`. Expected: both exit 0. Record the counts.

- [ ] **Step 3: Install and restart the daemon**

Run `./install.sh`. Restart the daemon the way memory `project_plugin-hook-deploy-path` says (kill the daemon's python pid, never the wrapper's, then launch it again with the osascript line from that memory). Confirm the new pid and that `daemon.log` shows a clean start.

- [ ] **Step 4: Live E2E** (`.cs/local/e2e_remote_live.py`, iTerm2 venv python)

Modeled on `.cs/local/rc_check2.py`: a throwaway haiku session in `.cs/local/e2e-live/rc-live` with the repo plugin (`--plugin-dir plugin`), user settings on, `--settings .cs/local/rc-off.json`. Checks:
1. The panel row for it reads `remote: null` within 10 s.
2. Write `remote-control.json` `{"switch_at": 1.0, "expires": now + 300}` into `~/.claude/agents-sidebar-links/<its session id>/` with mode 0600, as the daemon would. Within 15 s: `remote-control-result.json` says `done`, the state file's `bridgeSessionId` is set, and the row reads `remote: "on"`.
3. Write the ask again: the result says `already-on` and the session's state file `status` stays `idle` (no menu).
4. Close the window; remove `plugin/tsconfig.json` if laid.

The switch-and-drop path is covered by Tasks 1-2's tests; it runs live only on a real switch to an account that can be switched back from (spec §8). Say so in the report.

- [ ] **Step 5: Final review**

One fresh reviewer on the whole branch (`git diff spec/remote-control...HEAD`), given the spec and this plan. Fix what it confirms, re-run Steps 2 and 4.

- [ ] **Step 6: Commit and finish**

```bash
git add docs/usage.md docs/integrations.md docs/development.md README.md
git commit -m "Docs: remote control kept across account switches"
```

Then `superpowers:finishing-a-development-branch`; merge only on an explicit go-ahead.
