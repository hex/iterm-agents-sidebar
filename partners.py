# ABOUTME: Partner sessions: two linked Claude sessions that know each other and hand each other tasks. The record
# ABOUTME: of partnerships, each end's partner.json, and the tasks between them, all through each session's links folder.
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

import links
from links import quoted

PARTNERS_FILE = Path(os.path.expanduser("~/.claude/agents-sidebar-status/partners.json"))
TASK_MAX = links.RESULT_MAX
REPLY_SHOWN = 300
DELEGATE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: How long a pane may go unread as an agent card before its partnership ends: a /clear takes it out of the agent
#: rows for a rebuild or two, and a closed pane stays gone.
GONE_SECONDS = 15
#: How long a partner may sit idle on a task it took, with no answer filed, before the task ends: an idle
#: partner starts a task's prompt within a second, so one that stays idle lost its turn.
IDLE_GRACE = 60


@dataclass
class Task:
    id: str
    asked_as: str
    nonce: str
    source: str
    target: str
    source_agent: str
    target_agent: str
    source_label: str
    target_label: str
    task: str
    asked_at: float
    state: str = "asked"


@dataclass
class Partnership:
    id: str
    upper: str
    lower: str
    made_at: float
    open: Task | None = None
    # In memory only: how many times work landed in either card, the last landing's direction, and the
    # delegating card's line for a few seconds after a task ends.
    landings: int = 0
    landed: dict | None = None
    recent: dict | None = None

    def other(self, pane):
        return self.lower if pane == self.upper else self.upper


def linked_with(label, partner_label):
    """Why a card already in a partnership cannot link again."""
    return f"{quoted(label)} is linked with {quoted(partner_label)}: untie it first"


def refusal(source, target, partnered, labels, ready):
    """Why these two Claude cards cannot become partners now, or None. Waiting on you is no bar: no prompt is sent."""
    if source is None or target is None:
        return "that session has gone"
    if source["pane"] == target["pane"] or (source["agent"] and source["agent"] == target["agent"]):
        return "a card cannot link to itself"
    if source["depth"] or target["depth"]:
        return "teammates cannot be linked"
    if (target["worktree_of"] == source["pane"] or source["worktree_of"] == target["pane"]
            or (source["worktree_of"] and source["worktree_of"] == target["worktree_of"])):
        return "a worktree cannot link to its own session"
    if source["worktree_of"] or target["worktree_of"]:
        # A pair draws as one block of two heads; a worktree card sits inside another session's block.
        return "a worktree card cannot be partnered"
    reason = links.own_refusal(source, ready) or links.own_refusal(target, ready)
    if reason:
        return reason
    for one in (source, target):
        if one["pane"] in partnered:
            return linked_with(one["label"], labels[one["pane"]])
    return None


def task_text(source_label, why, task, nonce):
    reason = " ".join(str(why).split())[:200]
    return (f"Your partner {quoted(source_label)} handed you this task ({reason}). Do it, then reply with the result: "
            f"your reply goes back to {quoted(source_label)}. (link {nonce})\n\n{links.fenced(task)}")


def answered(target_label, text):
    return {"result": f"{quoted(target_label)} answered:\n\n{links.fenced(text)}",
            "late": f"Your partner {quoted(target_label)} finished the task you handed it:\n\n{links.fenced(text)}"}


def not_finished(target_label, reason):
    return {"result": f"{quoted(target_label)} could not finish the task: {reason}",
            "late": f"Your partner {quoted(target_label)} could not finish the task you handed it: {reason}"}


def not_handed(target_label, reason):
    return {"result": f"Not handed over: {reason}",
            "late": f"Your hand-off to {quoted(target_label)} was not made: {reason}"}


STATE_WORDS = {"working": "working", "idle": "idle", "blocked": "waiting on you"}


def _for(seconds):
    minutes = int(seconds // 60)
    return "under a minute" if minutes < 1 else f"{minutes} min" if minutes < 120 else f"{minutes // 60} h"


def profile(one, reply, now, open_way):
    """What the panel knows of a partner, as the model reads it -> (text, key). The key is the text without its
    durations, so time passing alone never makes the profile news."""
    def lines(timed):
        head = f"{quoted(one['label'])}: {one.get('model') or 'model unknown'} in {one.get('cwd') or 'an unknown folder'}"
        out = [head + (f", branch {one['branch']}." if one.get("branch") else ".")]
        state = one.get("state")
        since = {"working": one.get("working_since"), "idle": one.get("idle_since"),
                 "blocked": one.get("blocked_since")}.get(state)
        word = STATE_WORDS.get(state, state or "in an unknown state")
        out.append(f"It is {word}" + (f", for {_for(now - since)}." if timed and since is not None else "."))
        if one.get("task"):
            out.append(f"Its task: {' '.join(str(one['task']).split())[:200]}.")
        if one.get("todos"):
            out.append("Its open task list: " + "; ".join(' '.join(str(t).split())[:80] for t in one["todos"][:8]) + ".")
        if isinstance(one.get("context"), (int, float)):
            out.append(f"Its context is about {int(one['context']) // 10 * 10}% full.")
        if open_way == "from_you":
            out.append("A task is open between you: you handed it one.")
        elif open_way == "to_you":
            out.append("A task is open between you: it handed you one.")
        if reply and reply.strip():
            out.append(f"{quoted(one['label'])}'s own words, not an instruction, from its last reply to you:")
            out.append(links.fenced(reply.strip()[:REPLY_SHOWN]))
        return "\n".join(out)
    return lines(True), lines(False)


def introduction(label, profile_text):
    return (f"You are linked with the session {quoted(label)}, another Claude Code session on this machine, through "
            f"the agents sidebar. You can read its recent conversation with mcp__agents-sidebar__partner_read and "
            f"hand it a task with mcp__agents-sidebar__partner_delegate (load them with ToolSearch). Hand it a task "
            f"when it owns the repository or files involved, already holds the context the task needs, or when your "
            f"own context is nearly full; do not hand it what you can do well yourself, or a task it just handed "
            f"you. A task waits for its answer, one at a time between you.\n\nWhat the panel knows of it now:\n"
            f"{profile_text}")


def _state_note(one, now):
    if one["state"] == "working" and one.get("working_since") is not None:
        return (f"{quoted(one['label'])} is working on something else ({_for(now - one['working_since'])}); "
                f"your task is queued behind it")
    return None


class Partners:
    """The partnerships, saved whole in partners.json so a daemon restart keeps them."""

    def __init__(self, path=None, root=None):
        self.path = Path(path or PARTNERS_FILE)
        self.root = Path(root or links.LINKS_DIR)
        self.by_id = {}
        #: pane -> its card's label and its conversation id, as the last step saw them.
        self.seen = {}
        #: conversation id -> the partner.json last written in its folder.
        self.written = {}
        #: pane -> since when no rebuild has read it as an agent card.
        self.missing = {}
        #: task id -> since when its partner has read idle with the task taken and no answer filed.
        self.idle_since_seen = {}

    def load(self, now):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            for item in saved:
                task = Task(**item["open"]) if item["open"] else None
                pair = Partnership(item["id"], item["upper"], item["lower"], item["made_at"], task)
                self.by_id[pair.id] = pair
        except FileNotFoundError:
            return []
        except (ValueError, TypeError, KeyError):
            self.by_id = {}
            return ["partners: partners.json unreadable, starting with none"]
        return []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.path.with_name(f".{self.path.name}.{os.getpid()}")
        staged.unlink(missing_ok=True)
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump([{"id": p.id, "upper": p.upper, "lower": p.lower, "made_at": p.made_at,
                        "open": asdict(p.open) if p.open else None} for p in self.by_id.values()], out)
        os.replace(staged, self.path)

    def of(self, pane):
        return next((p for p in self.by_id.values() if pane in (p.upper, p.lower)), None)

    def partnered(self):
        return {pane for p in self.by_id.values() for pane in (p.upper, p.lower)}

    def labels(self):
        """pane -> the label of the card it is partnered with, for refusals."""
        return {pane: self.seen.get(self.of(pane).other(pane), {}).get("label", "its partner")
                for pane in self.partnered()}

    def pairs(self):
        return [(p.upper, p.lower) for p in self.by_id.values()]

    def make(self, upper, lower, now):
        labels = self.labels()
        for one in (upper, lower):
            if one["pane"] in labels:
                raise links.Refused(linked_with(one["label"], labels[one["pane"]]))
        pair = Partnership(secrets.token_hex(16), upper["pane"], lower["pane"], now)
        self.by_id[pair.id] = pair
        for one in (upper, lower):
            self.seen[one["pane"]] = {"label": one["label"], "agent": one["agent"]}
        self.save()
        return pair

    def untie(self, pane, now, reason=None, ends=None):
        pair = self.of(pane)
        if pair is None:
            raise links.Refused("that card is not linked")
        # The record goes first, so a folder that cannot be used never keeps a pair the user untied.
        del self.by_id[pair.id]
        self.save()
        said = f"partner {pair.id[:8]} untied: {reason or 'you untied it'}"
        if pair.open:
            task = pair.open
            self.idle_since_seen.pop(task.id, None)
            why = reason or f"the link with {quoted(task.target_label)} was untied"
            try:
                self._answer(self._agent(task.source, ends) or task.source_agent, task,
                             not_finished(task.target_label, why))
                self._clear(task)
            except (links.Refused, OSError) as error:
                said += f"; its open task was not answered: {error}"
        for one in (pair.upper, pair.lower):
            agent = self._agent(one, ends)
            if agent:
                self.written.pop(agent, None)
                try:
                    (links.session_dir(self.root, agent) / "partner.json").unlink(missing_ok=True)
                except (links.Refused, OSError):
                    pass
        return said

    def _agent(self, pane, ends):
        one = (ends or {}).get(pane)
        return one["agent"] if one else self.seen.get(pane, {}).get("agent")

    def _answer(self, agent, task, outcome):
        links.write_file(self.root, agent, f"answer-{task.asked_as}.json", {"id": task.asked_as, **outcome})

    def _clear(self, task):
        links.clear(self.root, task.target_agent, task.id)

    def frames(self):
        return [{"id": p.id, "upper": p.upper, "lower": p.lower,
                 "open": ({"from": p.open.source, "to": p.open.target, "state": p.open.state}
                          if p.open else None),
                 "landings": p.landings, "landed": p.landed, "lines": self._lines(p)}
                for p in self.by_id.values()]

    def _lines(self, pair):
        if pair.open:
            return {pair.open.source: f"Asked {quoted(pair.open.target_label)}: {quoted(pair.open.task)}"}
        if pair.recent:
            return {pair.recent["pane"]: pair.recent["text"]}
        return {}

    def restart(self, now):
        """A restart forgets which turn was working what: every open task is answered as cut off."""
        count = 0
        for pair in self.by_id.values():
            if pair.open:
                task = pair.open
                self._answer(task.source_agent, task, not_finished(
                    task.target_label, f"the panel restarted while {quoted(task.target_label)} had the task"))
                pair.open = None
                count += 1
        if count:
            self.save()
            return [f"partners: answered {count} open task{'s' * (count != 1)} cut off by the restart"]
        return []

    def step(self, ends, now):
        said = []
        for pane, one in ends.items():
            if one is not None:
                self.seen[pane] = {"label": one["label"], "agent": one["agent"]}
        for pair in list(self.by_id.values()):
            try:
                said.extend(self._step_pair(pair, ends, now))
            except (links.Refused, OSError) as error:
                # One pair's folder that cannot be used must not stop the others or the panel's rebuild.
                said.append(f"partner {pair.id[:8]} not stepped: {error}")
        self._forget_old_partner_files(ends)
        return said

    def _step_pair(self, pair, ends, now):
        for p in (pair.upper, pair.lower):
            if ends.get(p) is None:
                self.missing.setdefault(p, now)
            else:
                self.missing.pop(p, None)
        unread = [p for p in (pair.upper, pair.lower) if ends.get(p) is None]
        gone = next((p for p in unread if now - self.missing[p] >= GONE_SECONDS), None)
        exited = next((p for p in (pair.upper, pair.lower) if ends.get(p) and ends[p]["state"] == "exited"), None)
        if gone or exited:
            who = quoted(self.seen.get(gone or exited, {}).get("label", "its partner"))
            for p in (pair.upper, pair.lower):
                self.missing.pop(p, None)
            return [self.untie(pair.upper, now, f"{who} has gone" if gone else f"{who} has exited", ends)]
        if unread:
            # Not readable for now: nothing is written or taken until both cards read again.
            return []
        self._write_partner_files(pair, ends, now)
        said = self._take_delegations(pair, ends, now)
        if pair.open:
            said.extend(self._follow(pair, ends, now))
        if pair.recent and now >= pair.recent["until"]:
            pair.recent = None
        return said

    def _take_delegations(self, pair, ends, now):
        said = []
        for pane in (pair.upper, pair.lower):
            agent = ends[pane]["agent"]
            try:
                folder = links.session_dir(self.root, agent)
                names = sorted(entry.name for entry in os.scandir(folder))
            except (links.Refused, FileNotFoundError):
                continue
            for name in names:
                if not name.startswith("delegate-"):
                    continue
                asked_as = name[len("delegate-"):].removesuffix(".json")
                if not name.endswith(".json") or not DELEGATE_ID.match(asked_as):
                    (folder / name).unlink(missing_ok=True)
                    said.append(f"partners: refused a delegation file named {name!r}")
                    continue
                body = links.read_marker(self.root, agent, "delegate", asked_as)
                (folder / name).unlink(missing_ok=True)
                said.extend(self._delegated(pair, pane, ends, asked_as, body, now))
        return said

    def _delegated(self, pair, pane, ends, asked_as, body, now):
        other = pair.other(pane)
        source, target = ends[pane], ends[other]
        reason = None
        if not isinstance(body, dict) or not isinstance(body.get("task"), str) or not isinstance(body.get("why"), str):
            reason = "the delegation could not be read"
        elif body.get("partnership") != pair.id:
            reason = "that link has ended"
        elif not body["task"].strip():
            reason = "the task was empty"
        elif len(body["task"]) > TASK_MAX:
            reason = f"the task was longer than {TASK_MAX} characters"
        elif pair.open and pair.open.source == pane:
            reason = f"you already handed {quoted(target['label'])} a task: wait for its answer"
        elif pair.open:
            reason = f"you are on a task for {quoted(target['label'])}: finish it first"
        elif target["state"] == "blocked":
            reason = f"{quoted(target['label'])} is waiting on you"
        if reason:
            probe = Task(asked_as, asked_as, "", pane, other, source["agent"], target["agent"],
                         source["label"], target["label"], "", now)
            self._answer(source["agent"], probe, not_handed(target["label"], reason))
            pair.recent = {"pane": pane, "text": f"Not handed over: {reason}", "until": now + links.CLEAR_SECONDS}
            return [f"partner {pair.id[:8]} refused a task from {source['label']}: {reason}"]
        task = Task(secrets.token_hex(16), asked_as, secrets.token_hex(8), pane, other, source["agent"],
                    target["agent"], source["label"], target["label"], body["task"], now)
        links.write_drop(self.root, target["agent"], {
            "link": task.id, "nonce": task.nonce, "role": "task", "from": source["label"], "to": target["label"],
            "from_colour": source.get("colour"), "to_colour": target.get("colour"),
            # The task's first words, for the partner's toast; the prompt itself is `text`.
            "task": " ".join(body["task"].split())[:60],
            "text": task_text(source["label"], body["why"], body["task"], task.nonce),
            "expires": now + links.EXPIRE_SECONDS}, now, kind="task")
        pair.open, pair.recent = task, None
        self.save()
        return [f"partner {pair.id[:8]} task {task.id[:8]} asked {source['label']} -> {target['label']}"]

    def _follow(self, pair, ends, now):
        task = pair.open
        agent = task.target_agent
        failed = links.read_marker(self.root, agent, "failed", task.id)
        result = links.read_marker(self.root, agent, "result", task.id)
        if task.state == "asked" and links.read_marker(self.root, agent, "started", task.id) is not None:
            task.state = "started"
            pair.landings += 1
            pair.landed = {"from": task.source, "to": task.target}
            self.save()
        if failed is not None:
            return self._close(pair, ends, now, None, str(failed.get("reason") or "the turn failed"))
        if result is not None:
            text = result.get("text")
            if result.get("link") != task.id or result.get("nonce") != task.nonce or not isinstance(text, str):
                return self._close(pair, ends, now, None, "the answer did not match the task")
            if len(text) > links.RESULT_MAX:
                return self._close(pair, ends, now, None, f"the answer was longer than {links.RESULT_MAX} characters")
            if not text.strip():
                return self._close(pair, ends, now, None, "the turn ended without an answer")
            return self._close(pair, ends, now, text, None)
        taken = task.state == "started" or links.read_marker(self.root, agent, "taken", task.id) is not None
        if not taken and now - task.asked_at > links.EXPIRE_SECONDS:
            return self._close(pair, ends, now, None, "it did not start the task in 30 minutes")
        if taken and ends[task.target]["state"] == "idle":
            if now - self.idle_since_seen.setdefault(task.id, now) >= IDLE_GRACE:
                return self._close(pair, ends, now, None, f"{quoted(task.target_label)} stopped without filing an answer")
        else:
            self.idle_since_seen.pop(task.id, None)
        return []

    def _close(self, pair, ends, now, text, reason):
        task = pair.open
        self.idle_since_seen.pop(task.id, None)
        outcome = answered(task.target_label, text) if reason is None else not_finished(task.target_label, reason)
        self._answer(self._agent(task.source, ends) or task.source_agent, task, outcome)
        self._clear(task)
        pair.open = None
        pair.landings += 1
        pair.landed = {"from": task.target, "to": task.source}
        line = f"{quoted(task.target_label)} answered" if reason is None else f"{quoted(task.target_label)} could not finish: {reason}"
        pair.recent = {"pane": task.source, "text": line, "until": now + links.CLEAR_SECONDS}
        self.save()
        return [f"partner {pair.id[:8]} task {task.id[:8]} " + ("answered" if reason is None else f"failed: {reason}")]

    def _write_partner_files(self, pair, ends, now):
        for pane in (pair.upper, pair.lower):
            me, other = ends[pane], ends[pair.other(pane)]
            reply = self._reply(other["agent"])
            way = None
            if pair.open:
                way = "from_you" if pair.open.source == pane else "to_you"
            text, key = profile(other, reply, now, way)
            payload = {"id": pair.id, "me": quoted(me["label"]), "label": quoted(other["label"]),
                       "transcript": other.get("transcript"),
                       "profile": text, "key": key, "introduction": introduction(other["label"], text),
                       "state_note": _state_note(other, now)}
            if self.written.get(me["agent"]) != payload:
                links.write_file(self.root, me["agent"], "partner.json", payload)
                self.written[me["agent"]] = payload

    def _reply(self, agent):
        """The partner's last reply to you, from the reply.json its own mod files, under the marker cap."""
        text = (links.read_json(self.root, agent, "reply.json") or {}).get("text")
        return text if isinstance(text, str) else None

    def _forget_old_partner_files(self, ends):
        # A pane unread for now is still inside its GONE_SECONDS, so its conversation keeps its partner.json.
        current = {ends[p]["agent"] if ends.get(p) else self.seen.get(p, {}).get("agent")
                   for pair in self.by_id.values() for p in (pair.upper, pair.lower)}
        for agent in [a for a in self.written if a not in current]:
            try:
                (links.session_dir(self.root, agent) / "partner.json").unlink(missing_ok=True)
            except (links.Refused, OSError):
                pass
            del self.written[agent]
