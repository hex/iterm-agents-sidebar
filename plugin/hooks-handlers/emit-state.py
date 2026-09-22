#!/usr/bin/env python3
"""Publish this Claude session's state to iTerm2, for the Agents sidebar.

Writes OSC 1337 SetUserVar=claudeState to the session's TTY. iTerm2 exposes it
as the session variable `user.claudeState`, which the sidebar daemon reads the
same way it reads `path`. The escape sequence goes to one terminal's TTY, so
state is inherently per-session -- no session-id-to-terminal mapping needed.

An event says what happened to one participant; it cannot say what the session
is doing. A parent and its subagents all fire into this one terminal, so each
event is folded into a per-session document and the state published is derived
from the whole of it. Reading a single event as the answer is what let one
agent's finished tool clear another agent's permission gate.

What each event contributes, derived from a hook trace captured 2026-09-07,
not guesswork:

    UserPromptSubmit                       -> working, and clears the record
    PermissionRequest                      -> opens a gate on its tool
    Notification type=permission_prompt    -> opens an uncorrelated gate, unless
                                              the tool it could be about has run
    PreToolUse                             -> working
    PostToolUse                            -> working, closes its own gate
    PostToolUseFailure, PermissionDenied   -> closes its own gate
    Notification type=idle_prompt          -> the parent is done
    Stop (stop_hook_active false)          -> the parent is done, and its
                                              background_tasks list replaces
                                              what is held in flight
    Stop (stop_hook_active TRUE)           -> ignored, see below
    PreCompact                             -> working
    SessionStart                           -> the parent is done
    SubagentStart / SubagentStop           -> adds or removes one child
    SessionEnd                             -> cleared

    a gate open                            -> blocked
    else parent working, a child alive,
         or a background task in flight    -> working
    else                                   -> idle

A Stop hook that itself triggers Stop arrives with stop_hook_active true. The
trace showed two consecutive Stop events for one turn from another installed
hook, so acting on those would flap the state.

There is deliberately no "error" or "interrupted" state. The Stop payload
carries no exit reason, and eight council providers agreed it cannot be derived
from hooks. A wrong badge is worse than no badge.
"""
import base64
import fcntl
import glob
import json
import os
import re
import stat
import subprocess
import sys
import time

LOG = os.path.expanduser("~/.claude/agents-sidebar-events.jsonl")

#: One state document per session. Hooks are one-shot processes with no memory
#: of each other, and a parent and its subagents all fire into the same
#: session at once, so anything the emitted state depends on beyond the current
#: event lives here -- and is contended.
STATE_DIR = os.path.expanduser("~/.claude/agents-sidebar-subagents")

#: The slot a gate takes when its payload carries no tool_use_id. One slot, not
#: one per occurrence: an uncorrelated gate can only be cleared at a turn
#: boundary, so letting them accumulate would just be a longer wait.
UNKEYED = "?"

#: A gated tool that runs is proof the prompt was answered -- there is no
#: "permission granted" event. A denied or failed one never reaches PostToolUse
#: at all, and without these its gate would sit until the next prompt: minutes
#: of claiming Claude needs you after you have already told it no.
GATE_CLOSING = ("PostToolUse", "PostToolUseFailure", "PermissionDenied")

#: Where task.py keeps each session's note about its own work.
TASKS_DIR = os.path.expanduser("~/.claude/agents-sidebar-tasks")
#: A report older than this is worth a nudge at the next tool boundary, and
#: no session is nudged more often than this.
NUDGE_AFTER = 60
INSTRUCTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task-instructions.md")

def read_payload():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def blank_state():
    """A session nothing is known about: not working, no children, no gates."""
    return {"parent_active": False, "agents": {}, "finished": {}, "agent_types": {},
            "agent_info": {}, "gates": {}, "last_tool": None, "last_tool_ran": False,
            "turn_started": None, "reminded": 0, "question": None, "background": []}


def live_agents(doc):
    """Subagents run inside their parent's process and get no terminal of their
    own, so iTerm2 cannot see them at all. The only way they reach the sidebar
    is by the parent recording them here.

    Held as a set of agent ids rather than a counter: a lifecycle event
    delivered twice used to move the count twice, and an id makes the fold
    idempotent.
    """
    return len(doc.get("agents") or {})


def subagents(doc):
    """The subagents of this turn, oldest first: [{id, parent, type, since, ...}].

    SubagentStart names what kind of agent it is, never what it was asked to
    do; the task description travels on a tool event with no agent id, and
    pairing the two by timing is a guess when several start together.
    """
    types = doc.get("agent_types") or {}
    info = doc.get("agent_info") or {}
    listed = [(since, agent_id, None) for agent_id, since in (doc.get("agents") or {}).items()]
    listed += [(done["since"], agent_id, done["ended"])
               for agent_id, done in (doc.get("finished") or {}).items()]
    return [{"id": agent_id, "parent": (info.get(agent_id) or {}).get("parent"),
             "type": types.get(agent_id) or None, "since": round(since),
             "ended": round(ended) if ended is not None else None,
             "name": (info.get(agent_id) or {}).get("name"),
             "model": (info.get(agent_id) or {}).get("model")}
            for since, agent_id, ended in sorted(listed)]


#: How far into a subagent's transcript to look for its first reply's model.
#: One that inherits a long conversation files all of it ahead of that reply:
#: 615 KB in the longest seen.
MODEL_SCAN_BYTES = 4 * 1024 * 1024


def _subagent_file(transcript_path, agent_id, suffix):
    """Claude Code writes a subagent's files beside the session transcript:
    <session>/subagents/agent-<id><suffix>, or for a workflow's agents
    <session>/subagents/workflows/<run>/agent-<id><suffix>."""
    root = transcript_path.split("/subagents/")[0]
    if root.endswith(".jsonl"):
        root = root[:-len(".jsonl")]
    name = f"agent-{agent_id}{suffix}"
    direct = os.path.join(root, "subagents", name)
    if os.path.exists(direct):
        return direct
    found = glob.glob(os.path.join(glob.escape(os.path.join(root, "subagents", "workflows")), "*", name))
    return found[0] if found else direct


def _subagent_meta(path):
    """A subagent's meta file as {name, parent}, or None while it is unreadable.

    parentAgentId is there only for a subagent another subagent started."""
    try:
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
        name, parent = meta.get("description"), meta.get("parentAgentId")
    except (OSError, ValueError, AttributeError):
        return None
    return {"name": name if isinstance(name, str) and name else None,
            "parent": parent if isinstance(parent, str) and parent else None}


def _subagent_model(path):
    # The hook runs on every event, so the lines ahead of the reply, which
    # run to tens of kilobytes each, are passed over without being parsed.
    try:
        with open(path, "rb") as fh:
            left = MODEL_SCAN_BYTES
            while left > 0:
                line = fh.readline(left)
                if not line:
                    break
                left -= len(line)
                if b'"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                    model = entry["message"]["model"] if entry.get("type") == "assistant" else None
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
                if isinstance(model, str) and model:
                    return model
    except OSError:
        return None
    return None


def describe_subagents(doc, transcript_path):
    """Fill in each live subagent's name and model from its files. -> the doc.

    SubagentStart names only the agent's type. Its description (a workflow
    agent's label) is in the meta file, written in the same second as the
    event and so possibly not there yet, and its model appears with its first
    reply. The meta file also names the agent that started a nested one.
    Whatever is still missing is looked for again on the next event.
    """
    if not transcript_path:
        return doc
    info = dict(doc.get("agent_info") or {})
    for agent_id in [*(doc.get("agents") or {}), *(doc.get("finished") or {})]:
        known = dict(info.get(agent_id) or {})
        if not known.get("name") or "parent" not in known:
            meta = _subagent_meta(_subagent_file(transcript_path, agent_id, ".meta.json"))
            if meta:
                known.update(meta)
            else:
                known.setdefault("name", None)
        if not known.get("model"):
            known["model"] = _subagent_model(_subagent_file(transcript_path, agent_id, ".jsonl"))
        info[agent_id] = known
    return {**doc, "agent_info": info}


#: The most of each part of a question the state carries. A notice shows less
#: than this, and an agent can write a question of any length.
QUESTION_LIMIT, HEADER_LIMIT, OPTION_LIMIT, SUMMARY_LIMIT = 300, 40, 60, 200


def clip(text, limit):
    """`text` as a string of at most `limit` characters, the last an ellipsis when cut."""
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def question_from(payload):
    """What a permission gate is asking, from its PermissionRequest payload.

    AskUserQuestion carries the question and its option labels, which a
    notice can show as buttons; the first question is shown and the rest
    counted. Any other tool names itself and the first line of what it wants
    to run, so the notice can say "wants to run: git push". None when the
    payload names no tool.
    """
    tool = payload.get("tool_name")
    if not tool:
        return None
    given = payload.get("tool_input") or {}
    if tool == "AskUserQuestion":
        questions = given.get("questions") or []
        if not questions:
            return None
        first = questions[0]
        # Every option keeps its place: the answer is sent as its number.
        return {"header": clip(first.get("header") or "", HEADER_LIMIT),
                "question": clip(first.get("question") or "", QUESTION_LIMIT),
                "options": [clip(o.get("label") or "", OPTION_LIMIT)
                            for o in first.get("options") or []],
                "multi": bool(first.get("multiSelect")),
                "more": len(questions) - 1}
    summary = given.get("command") or given.get("file_path") or given.get("path") or ""
    return {"tool": tool,
            "summary": clip(str(summary).strip().splitlines()[0], SUMMARY_LIMIT) if summary else ""}


def blocked_since(doc):
    """When the oldest open permission gate was raised (epoch s), or None."""
    gates = doc.get("gates") or {}
    return round(min(gates.values())) if gates else None


def working_since(doc):
    """When the turn now under way began (epoch s), or None when nothing is working."""
    started = doc.get("turn_started")
    if aggregate(doc) != "working" or not isinstance(started, (int, float)):
        return None
    return round(started)


def turn_started(doc):
    """When the latest prompt arrived (epoch s), working or not, or None."""
    started = doc.get("turn_started")
    return round(started) if isinstance(started, (int, float)) else None


def aggregate(doc):
    """The whole session's state, derived rather than taken from one event.

    An event says what just happened to one participant. It cannot say what
    the session is doing, and treating it as though it could is what let a
    sibling's finished tool clear another agent's permission gate.

    Blocked outranks everything: it is the only state that asks for a person,
    so whatever else is running, that is the thing to say.
    """
    if doc.get("gates"):
        return "blocked"
    if doc.get("parent_active") or live_agents(doc) or doc.get("background"):
        return "working"
    return "idle"


def apply_event(doc, event, payload, said):
    """Fold one hook event into a session's state document. Pure.

    `said` is what state_for made of the event on its own -- kept as the
    reading of a single event, which is all it can honestly be, and turned
    into a change to the record here.
    """
    doc = {"parent_active": bool(doc.get("parent_active")),
           "agents": dict(doc.get("agents") or {}),
           "finished": dict(doc.get("finished") or {}),
           "agent_types": dict(doc.get("agent_types") or {}),
           "agent_info": dict(doc.get("agent_info") or {}),
           "gates": dict(doc.get("gates") or {}),
           "last_tool": doc.get("last_tool"),
           "last_tool_ran": bool(doc.get("last_tool_ran")),
           "turn_started": doc.get("turn_started"),
           "reminded": doc.get("reminded") or 0,
           "question": doc.get("question"),
           "background": list(doc.get("background") or [])}
    now = round(time.time(), 3)

    if event == "UserPromptSubmit":
        # The one event that starts a turn; tool calls inside it keep this clock.
        doc["turn_started"] = now

    if is_fresh_start(event, payload):
        # A subagent sent to the background runs on through the next prompt;
        # only a launch finds none, since none survives the process.
        running = doc["agents"] if event == "UserPromptSubmit" else {}
        doc["agents"] = dict(running)
        doc["finished"] = {}
        doc["agent_types"] = {k: v for k, v in doc["agent_types"].items() if k in running}
        doc["agent_info"] = {k: v for k, v in doc["agent_info"].items() if k in running}
        doc["gates"] = {}
        doc["last_tool"] = None

    if event == "PreToolUse":
        # The id a gate will need. PermissionRequest carries tool_name and
        # tool_input but no tool_use_id -- measured across 13 real gates on
        # 2026-09-08 -- and it arrives directly after the PreToolUse for the
        # same tool. That event has the id, so remember it.
        if payload.get("tool_use_id"):
            doc["last_tool"] = payload["tool_use_id"]
            doc["last_tool_ran"] = False

    if event == "SubagentStart":
        doc["agents"][payload.get("agent_id") or UNKEYED] = now
        doc["agent_types"][payload.get("agent_id") or UNKEYED] = payload.get("agent_type")
    elif event == "SubagentStop":
        # Kept, dimmed, until the next prompt: a row that vanished on finish
        # shifted every row below it, several times a second in a workflow.
        agent_id = payload.get("agent_id") or UNKEYED
        if agent_id in doc["agents"]:
            doc["finished"][agent_id] = {"since": doc["agents"].pop(agent_id), "ended": now}
    elif event in GATE_CLOSING:
        # Only the gate this tool owns. Nothing may clear a gate it cannot
        # prove it owns: a badge that stays too long is a nuisance, one that
        # vanishes while Claude waits is the failure.
        key = payload.get("tool_use_id")
        if key:
            doc["gates"].pop(key, None)
            if not doc["gates"]:
                doc["question"] = None
            if key == doc["last_tool"]:
                doc["last_tool_ran"] = True

    if (said == "blocked" and event == "Notification" and not payload.get("tool_use_id")
            and doc["last_tool"] and doc["last_tool_ran"]):
        # The permission_prompt Notification comes seconds after the prompt
        # opens, on its own clock, and can land after the tool it was about
        # was approved and has run. The only tool it could name has finished,
        # so it is that echo, and a gate keyed on it would never be closed:
        # traced 2026-09-17, five minutes of blocked through steady work. A
        # notification with no tool seen at all still holds its gate.
        pass
    elif said == "blocked":
        doc["gates"][payload.get("tool_use_id") or doc["last_tool"] or UNKEYED] = now
        # What the newest gate asks; the notice needs the question, not
        # only the fact of one.
        doc["question"] = question_from(payload) or doc["question"]
        # Asking to run a tool means a turn is under way.
        doc["parent_active"] = True
    elif said == "working":
        doc["parent_active"] = True
    elif said == "idle":
        # The parent's own turn ended. Its children may well outlive it, which
        # is why this is one input to aggregate and not the answer.
        doc["parent_active"] = False
        # Nor are its background tasks over: a Stop while any run is a pause,
        # and the task's end wakes the session for another turn. Stop lists the
        # whole in-flight set each time, and nothing fires when one task ends,
        # so the list is replaced, never added to.
        if event == "Stop":
            doc["background"] = [{"type": t.get("type"), "description": t.get("description")}
                                 for t in payload.get("background_tasks") or []]
            # A subagent in the foreground cannot outlive the turn, and the
            # list names every one in the background. So a Stop that lists
            # none ends whichever never reported its own end, which nothing
            # else would: it would hold the session at working for good.
            if isinstance(payload.get("background_tasks"), list) \
                    and not any(t.get("type") == "subagent" for t in doc["background"]):
                for agent_id in list(doc["agents"]):
                    doc["finished"][agent_id] = {"since": doc["agents"].pop(agent_id), "ended": now}
        # Nothing runs while a permission prompt is open, so a turn that
        # reached its end had none pending. This is the bound on a gate nothing
        # could correlate, and it has to be this tight: waiting for the next
        # prompt instead left the badge standing for as long as the user took
        # to type, which in practice meant it never came down.
        doc["gates"] = {}
        doc["question"] = None

    return doc


#: What a session id may be: it names files here and in the daemon, and is
#: typed into the command the agent is handed.
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def session_of(payload):
    """The event's session id, or None when it is not a plain token."""
    session_id = payload.get("session_id")
    return session_id if isinstance(session_id, str) and _SESSION.match(session_id) else None


def _state_path(session_id):
    return os.path.join(STATE_DIR, session_id)


def read_state(session_id):
    """This session's document, or a blank one.

    Anything unreadable reads as blank rather than raising: a hook that raises
    writes no state at all, and it runs on every turn of a session it is only
    meant to describe. A bare integer is what this file held before ids
    replaced the counter, and an upgrade lands mid-session.
    """
    if not session_id:
        return blank_state()
    try:
        with open(_state_path(session_id), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return blank_state()
    if not isinstance(doc, dict):
        return blank_state()
    return {"parent_active": bool(doc.get("parent_active")),
            "agents": doc.get("agents") if isinstance(doc.get("agents"), dict) else {},
            "agent_types": doc.get("agent_types") if isinstance(doc.get("agent_types"), dict)
                           else {},
            "agent_info": doc.get("agent_info") if isinstance(doc.get("agent_info"), dict)
                          else {},
            "finished": doc.get("finished") if isinstance(doc.get("finished"), dict) else {},
            "gates": doc.get("gates") if isinstance(doc.get("gates"), dict) else {},
            "last_tool_ran": bool(doc.get("last_tool_ran")),
            "last_tool": doc.get("last_tool") if isinstance(doc.get("last_tool"), str)
                         else None,
            "turn_started": doc.get("turn_started")
                            if isinstance(doc.get("turn_started"), (int, float)) else None,
            "reminded": doc.get("reminded") if isinstance(doc.get("reminded"), (int, float)) else 0,
            "question": doc.get("question") if isinstance(doc.get("question"), dict) else None,
            "background": doc.get("background") if isinstance(doc.get("background"), list) else []}


def update(session_id, event, payload, said):
    """Fold the event in and store the result. -> the new document.

    Held under an exclusive lock across read and write, and replaced by rename:
    several hooks fire into one session at once, and an unserialized
    read-modify-write lost the losers' updates -- two subagent starts stored
    one, after which the parent's Stop could report idle with children alive.

    The lock is a sibling file rather than the document itself, so the rename
    that replaces the document cannot pull the lock out from under a waiter.
    """
    if not session_id:
        return apply_event(blank_state(), event, payload, said)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_state_path(session_id) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            doc = apply_event(read_state(session_id), event, payload, said)
            doc = describe_subagents(doc, payload.get("transcript_path"))
            path = _state_path(session_id)
            temp = path + f".{os.getpid()}.tmp"
            with open(temp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            os.replace(temp, path)
            return doc
    except OSError:
        return apply_event(blank_state(), event, payload, said)


def mark_reminded(session_id, now):
    """Remember that the session was just asked for a check-in."""
    if not session_id:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_state_path(session_id) + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            doc = dict(read_state(session_id), reminded=round(now))
            path = _state_path(session_id)
            temp = path + f".{os.getpid()}.tmp"
            with open(temp, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            os.replace(temp, path)
    except OSError:
        pass


def read_note(session_id):
    """The session's own note about its work, or None."""
    if not session_id:
        return None
    try:
        with open(os.path.join(TASKS_DIR, f"{session_id}.json"), encoding="utf-8") as fh:
            note = json.load(fh)
    except (OSError, ValueError):
        return None
    return note if isinstance(note, dict) and "task" in note else None


def clear_note(session_id):
    """Remove the session's task note, under the lock task.py holds while it
    writes, so a report in flight cannot bring the note back."""
    if not session_id:
        return
    try:
        with open(os.path.join(TASKS_DIR, f"{session_id}.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            os.remove(os.path.join(TASKS_DIR, f"{session_id}.json"))
    except OSError:
        pass


def whisper(event, payload, note, now, reminded, script):
    """What to add to the agent's context about its task line, or None.

    The agent writes the note itself; this is the reminder. Every prompt
    gets the instructions and the bound commands. A tool boundary gets one
    line, when the last report is a minute old and no reminder went out in
    the last minute. Subagents never hear it, and the report itself is not a
    boundary worth a nudge.
    """
    if payload.get("agent_id") or "/subagents/" in str(payload.get("transcript_path") or ""):
        return None
    session_id = session_of(payload)
    if not session_id:
        return None
    bound = f"python3 {script} --session {session_id}"
    if event == "UserPromptSubmit":
        try:
            with open(INSTRUCTIONS, encoding="utf-8") as fh:
                instructions = fh.read().strip()
        except OSError:
            return None
        current = json.dumps(note) if note else "none"
        return (f"{instructions}\n\nCurrent task: {current}\n\nCommands:\n"
                f"{bound} begin --title 'Task title'\n"
                f"{bound} report --activity 'Reading code' --percent 25\n"
                f"{bound} report --activity 'Assessing task' --unknown\n")
    if event != "PostToolUse" or "task.py" in json.dumps(payload.get("tool_input") or {}):
        return None
    if now - reminded < NUDGE_AFTER:
        return None
    if note and (note.get("done") or now - (note.get("ts") or 0) < NUDGE_AFTER):
        return None
    return ("Progress check-in is due if this is a natural boundary. Reassess the "
            f"current task; do not invent progress. {bound} report --activity '...' --percent N")


def hook_output(event, text):
    """The hook protocol's shape for added context, or nothing to add."""
    if not text:
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def clear_state(session_id):
    """A session id is never reused, so anything left here leaks for the life
    of the machine.
    """
    if not session_id:
        return
    for path in (_state_path(session_id), _state_path(session_id) + ".lock",
                 _published_path(session_id)):
        try:
            os.remove(path)
        except OSError:
            pass


def state_for(event, payload):
    """-> a state name, "" to clear it, or None to leave the variable alone."""
    if event == "UserPromptSubmit":
        return "working"
    if event == "PermissionRequest":
        return "blocked"
    if event == "Notification":
        kind = payload.get("notification_type")
        if kind == "permission_prompt":
            return "blocked"
        if kind == "idle_prompt":
            return "idle"
        return None
    if event == "Stop":
        # A Stop hook re-entering Stop. Acting on it flaps the state.
        return None if payload.get("stop_hook_active") else "idle"
    if event == "PreCompact":
        # /compact emits no UserPromptSubmit, so without this the row reads
        # idle for the whole churn -- traced across both compactions in this
        # session on 2026-09-07. Both triggers are equally busy work.
        return "working"
    if event == "SessionStart":
        return "idle"
    if event == "PreToolUse":
        # Without this nothing fires between a tool starting and finishing, so
        # a session inside one long call keeps whatever it last said. Traced on
        # a subagent running the codex CLI: Stop -> idle, then 144s of silence
        # while it worked. PermissionRequest arrives after this, so a gated
        # tool still ends up blocked rather than working.
        return "working"
    if event == "PostToolUse":
        # There is no "permission granted" event. A tool executing is proof the
        # prompt is gone, since nothing runs while one is open -- without this,
        # blocked persisted until the next Stop, minutes of claiming a session
        # needs you when it is already working again.
        return "working"
    if event in ("SubagentStart", "SubagentStop"):
        # A turn whose subagents are still running is not idle, whatever Stop
        # said. Counted rather than inferred.
        return "working" if event == "SubagentStart" else None
    if event == "SessionEnd":
        return ""
    return None


def is_fresh_start(event, payload):
    """Should this event reset the session's subagent tally to zero?

    A new turn starts from no subagents, and so does a launch. A compaction
    resume does neither: an auto-compact fires in the middle of a turn, so
    zeroing there drops a parent to idle while its subagents are still running.
    """
    if event == "SessionStart":
        return payload.get("source") != "compact"
    return event == "UserPromptSubmit"


def pid_named(ps_output, name):
    """`ps -o pid=,comm=` output -> the pid whose executable path names the agent.

    The executable is the agent's own binary, and matching on the whole path
    is what makes this work: basename-only checks see "node". For Codex the
    match is the native binary under vendor/, not the node launcher that
    starts it, and the commands Codex runs are that binary's children.
    """
    for line in ps_output.splitlines():
        pid, _, comm = line.strip().partition(" ")
        if name in comm and "claude-status" not in comm:
            try:
                return int(pid)
            except ValueError:
                continue
    return None


def agent_pid(tty, name):
    """The pid of the agent process (`name`) owning this terminal, or None.

    Found via the controlling TTY rather than by walking parents: Claude Code
    setsid's its hooks, so getppid() is often 1 and a parent walk dies at the
    first step. Measured 2026-09-07 -- an earlier parent-walking version
    emitted "pid": null for every session, which made every row read "unknown".

    The TTY route also survives tmux: a pane's pts is claude's controlling
    terminal, so the lookup is the same inside and outside.
    """
    if not tty:
        return None
    device = tty.rsplit("/", 1)[-1]
    try:
        out = subprocess.run(["/bin/ps", "-t", device, "-o", "pid=,comm="],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return pid_named(out, name)


def _is_terminal(path):
    """Whether path is a character device this process may write to."""
    try:
        return stat.S_ISCHR(os.stat(path).st_mode) and os.access(path, os.W_OK)
    except OSError:
        return False


def find_tty():
    """Hooks are setsid'd, so /dev/tty fails. Resolve the real device."""
    env_tty = os.environ.get("TTY")
    if env_tty and _is_terminal(env_tty):
        return env_tty
    pid = os.getppid()
    for _ in range(8):
        if pid <= 1:
            return None
        try:
            out = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "tty=,ppid="],
                                 capture_output=True, text=True, timeout=2).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return None
        if not out:
            return None
        device = "/dev/" + out[0]
        if out[0] not in ("??", "-") and _is_terminal(device):
            return device
        try:
            pid = int(out[-1])
        except ValueError:
            return None
    return None


def emit(value, target=None, variable="claudeState"):
    target = target or find_tty()
    if not target:
        return
    encoded = base64.b64encode(value.encode()).decode()
    # ESC ST terminates, not BEL: iTerm2 flags a session as having had bell
    # activity on every BEL byte, even inside a well-formed OSC sequence.
    # Inside tmux passthrough every inner ESC must be doubled, per DCS rules.
    if os.environ.get("TMUX"):
        seq = f"\033Ptmux;\033\033]1337;SetUserVar={variable}={encoded}\033\033\\\033\\"
    else:
        seq = f"\033]1337;SetUserVar={variable}={encoded}\033\\"
    # One write call, unbuffered: two would give the tty a seam to split on.
    try:
        fd = os.open(target, os.O_WRONLY | os.O_NOCTTY)
        try:
            os.write(fd, seq.encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def published(doc, pid, payload, codex, now):
    """The JSON the session variable carries, from the folded state document.

    Codex has no statusline to bridge, so its variable also carries the model
    (on every Codex payload but SessionEnd) and the rollout the daemon reads
    effort and context from.
    """
    value = {"state": aggregate(doc), "pid": pid, "session": session_of(payload),
             "agents": live_agents(doc), "subagents": subagents(doc),
             "blocked_since": blocked_since(doc), "working_since": working_since(doc),
             "turn_started": turn_started(doc),
             "question": doc.get("question") if doc.get("gates") else None,
             "ts": round(now)}
    if codex:
        value["model"] = payload.get("model")
        value["transcript_path"] = payload.get("transcript_path")
    return value


#: The most base64 the session variable may carry. Every hook event writes
#: the variable to the pane's tty, the same tty Claude Code is redrawing its
#: status line on, and a write the tty cannot take whole lands in pieces: the
#: escape is cut and the rest of the base64 prints as text after the status
#: line (seen 2026-09-22 with five subagents, under the old 4 KB ceiling).
#: A bare state is about 260 bytes of base64; one subagent fits, more go to
#: a file beside the state document and the variable says only that.
VARIABLE_CEILING = 512
#: What the variable leaves behind when it is over the ceiling.
DETAIL_FIELDS = ("subagents", "question")


def _published_path(session_id, directory=None):
    return os.path.join(directory or STATE_DIR, session_id + ".published")


def carried(value, session_id, directory=None):
    """The published value -> the JSON text the variable carries.

    Whole when it fits. Otherwise the whole value is stored for the daemon to
    read, replaced by rename so it is never read half written, and the
    variable carries the rest with `detail: true`. When it cannot be stored
    the variable says `detail: false`: a card without its subagents, rather
    than a state that never arrives.
    """
    whole = json.dumps(value)
    if len(base64.b64encode(whole.encode())) <= VARIABLE_CEILING:
        return whole
    envelope = {key: item for key, item in value.items() if key not in DETAIL_FIELDS}
    try:
        if not session_id:
            raise OSError("no session to file the detail under")
        path = _published_path(session_id, directory)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + f".{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            fh.write(whole)
        os.replace(temp, path)
        envelope["detail"] = True
    except OSError:
        envelope["detail"] = False
    return json.dumps(envelope)


def nested_agent(environ, codex):
    """Whether this hook belongs to an agent running inside another's tool.

    A `codex exec` started by a Claude Bash tool inherits Claude Code's
    environment and shares the pane's tty, so its hooks would publish a
    codexState over the pane's claudeState and the card would turn into a
    Codex card. Claude Code's own hooks always carry CLAUDECODE; only a Codex
    hook seeing it is nested.
    """
    return bool(codex and environ.get("CLAUDECODE"))


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    # Codex runs this same handler: its hook events and payloads have the
    # shape Claude Code's do, measured by a probe hook on 2026-09-15.
    codex = "--codex" in sys.argv[2:]
    # A nested run speaks for no pane; the agent that started it does.
    if nested_agent(os.environ, codex):
        return
    payload = read_payload()
    state = state_for(event, payload)

    session_id = session_of(payload)
    if event == "SessionEnd":
        clear_state(session_id)
        clear_note(session_id)
        doc = blank_state()
    else:
        doc = update(session_id, event, payload, state)
    agents = live_agents(doc)

    # What the session is doing, not what one event said about one participant.
    # Published on every event, including the ones state_for reads as "changes
    # nothing": a subagent's exit changes nothing about that event and
    # everything about the session, and staying silent there left the last
    # child able to finish without ever restoring the row to idle.
    state = "" if event == "SessionEnd" else aggregate(doc)

    tty = find_tty()
    pid = agent_pid(tty, "codex" if codex else "claude")
    variable = "codexState" if codex else "claudeState"

    # Keep tracing while the interrupt question is open: an Esc or Ctrl+C
    # during ordinary use gets captured, and the fourth state can then be
    # added with evidence rather than assumption.
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"_event_arg": event, "_ts": round(time.time(), 3),
                                 "notification_type": payload.get("notification_type"),
                                 "stop_hook_active": payload.get("stop_hook_active"),
                                 "_source": payload.get("source"),
                                 "_trigger": payload.get("trigger"),
                                 "cwd": payload.get("cwd"),
                                 "_state": state,
                                 # Does a subagent's hook carry an agent id? The
                                 # herdr integration tests exactly this field to
                                 # bail out of subagent events, which implies it
                                 # exists. Verifying rather than assuming.
                                 "_session": session_id,
                                 "_agent_id": payload.get("agent_id"),
                                 "_agent_name": payload.get("agent_name"),
                                 "_agent_type": payload.get("agent_type"),
                                 # A gate raised by one subagent is cleared by
                                 # any sibling's PostToolUse, because the rule
                                 # is "a tool ran, so the prompt is gone" with
                                 # nothing tying the two to the same agent. The
                                 # fix needs a shared identity on both events.
                                 # Over 2745 logged events agent_id appeared on
                                 # SubagentStart/Stop only, never on
                                 # PermissionRequest or PostToolUse -- but the
                                 # docs say agent_id is present only inside a
                                 # subagent, so absence there may just mean the
                                 # main agent raised every gate so far. Key
                                 # names settle it: they say what the payload
                                 # actually offers, not what we thought to ask
                                 # for. Names only, never values.
                                 "_tool_use_id": payload.get("tool_use_id"),
                                 "_tool_name": payload.get("tool_name"),
                                 "_keys": sorted(payload),
                                 "_background": len(payload.get("background_tasks") or []),
                                 "_agents": agents}) + "\n")
    except OSError:
        pass

    if state is None:
        pass                     # nothing this event should change
    elif state == "":
        emit("", variable=variable)
    else:
        emit(carried(published(doc, pid, payload, codex, time.time()), session_id), tty, variable)

    # The task line: what the agent should be told about reporting its work.
    context = whisper(event, payload, read_note(session_id), time.time(), doc.get("reminded") or 0,
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "task.py"))
    if context:
        mark_reminded(session_id, time.time())

    # stdout belongs to the hook protocol. Anything else corrupts it.
    sys.stdout.write(json.dumps(hook_output(event, context)))


if __name__ == "__main__":
    main()
