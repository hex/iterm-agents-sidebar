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
#: A result no debt will read (filed after the panel already saw Remote Control back, or with the setting off) is
#: removed once this old.
UNREAD_SECONDS = 60
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
        #: Log lines from removing files, said once per path and error, handed out by the next step.
        self.notes = []

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
            lines += self._take_notes()
        elif switch_at is not None and switch_at != self.switch_seen:
            for owed in self.owed.values():
                if owed.filed_at is None:
                    owed.switch_at = switch_at
            # Every pane last read on: the switch is stamped when its account work began, seconds before it shows
            # here, so readings taken in between postdate the stamp; one already dropped reads off and is not owed.
            for pane, before in self.readings.items():
                end = ends.get(pane)
                if end and pane not in self.owed and before.state == "on":
                    self.owed[pane] = Owed(end["agent_pid"], end["agent"], switch_at)
        self.switch_seen = switch_at
        self.readings = dict(readings)
        for pane in list(self.owed):
            end = ends.get(pane)
            try:
                said = self._step_owed(pane, end, readings.get(pane), now)
            except (links.Refused, OSError) as error:
                said = self._lose(pane, end, f"its links folder: {error}", now)
            lines += self._take_notes() + said
        # After the debts have read theirs: what is left a minute on, nothing will read.
        for end in ends.values():
            self._sweep(end["agent"], now)
        lines += self._take_notes()
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
        """Removes one of our files from the agent's folder. Something else in its place (a directory) is left and
        logged once, never raised: a step that raised would fail every rebuild after it."""
        try:
            path = links.session_dir(self.root, agent) / name
        except links.Refused:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            if (str(path), error.strerror) not in self.faults_said:
                self.faults_said.add((str(path), error.strerror))
                self.notes.append(f"remote control: cannot remove {path}: {error.strerror}")

    def _sweep(self, agent, now):
        try:
            info = (links.session_dir(self.root, agent) / RESULT).lstat()
        except (links.Refused, OSError):
            return
        if stat.S_ISREG(info.st_mode) and now - info.st_mtime > UNREAD_SECONDS:
            self._unlink(agent, RESULT)

    def _take_notes(self):
        notes, self.notes = self.notes, []
        return notes
