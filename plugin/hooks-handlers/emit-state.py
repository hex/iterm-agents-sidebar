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
    Notification type=permission_prompt    -> opens an uncorrelated gate
    PreToolUse                             -> working
    PostToolUse                            -> working, closes its own gate
    PostToolUseFailure, PermissionDenied   -> closes its own gate
    Notification type=idle_prompt          -> the parent is done
    Stop (stop_hook_active false)          -> the parent is done
    Stop (stop_hook_active TRUE)           -> ignored, see below
    PreCompact                             -> working
    SessionStart                           -> the parent is done
    SubagentStart / SubagentStop           -> adds or removes one child
    SessionEnd                             -> cleared

    a gate open                            -> blocked
    else parent working or a child alive   -> working
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

def read_payload():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def blank_state():
    """A session nothing is known about: not working, no children, no gates."""
    return {"parent_active": False, "agents": {}, "finished": {}, "agent_types": {},
            "agent_info": {}, "gates": {}, "last_tool": None, "turn_started": None}


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
    """The running subagents, oldest first: [{type, since}].

    SubagentStart names what kind of agent it is, never what it was asked to
    do; the task description travels on a tool event with no agent id, and
    pairing the two by timing is a guess when several start together.
    """
    types = doc.get("agent_types") or {}
    info = doc.get("agent_info") or {}
    listed = [(since, agent_id, None) for agent_id, since in (doc.get("agents") or {}).items()]
    listed += [(done["since"], agent_id, done["ended"])
               for agent_id, done in (doc.get("finished") or {}).items()]
    return [{"type": types.get(agent_id) or None, "since": round(since),
             "ended": round(ended) if ended is not None else None,
             "name": (info.get(agent_id) or {}).get("name"),
             "model": (info.get(agent_id) or {}).get("model")}
            for since, agent_id, ended in sorted(listed)]


#: How far into a subagent's transcript to look for its first reply's model.
MODEL_SCAN_BYTES = 256 * 1024


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


def _subagent_name(path):
    try:
        with open(path, encoding="utf-8") as fh:
            name = json.load(fh).get("description")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None


def _subagent_model(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(MODEL_SCAN_BYTES)
    except OSError:
        return None
    for line in head.splitlines():
        try:
            entry = json.loads(line)
            model = entry["message"]["model"] if entry.get("type") == "assistant" else None
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        if isinstance(model, str) and model:
            return model
    return None


def describe_subagents(doc, transcript_path):
    """Fill in each live subagent's name and model from its files. -> the doc.

    SubagentStart names only the agent's type. Its description (a workflow
    agent's label) is in the meta file, written in the same second as the
    event and so possibly not there yet, and its model appears with its first
    reply. Whatever is still missing is looked for again on the next event.
    """
    if not transcript_path:
        return doc
    info = dict(doc.get("agent_info") or {})
    for agent_id in [*(doc.get("agents") or {}), *(doc.get("finished") or {})]:
        known = dict(info.get(agent_id) or {})
        if not known.get("name"):
            known["name"] = _subagent_name(_subagent_file(transcript_path, agent_id, ".meta.json"))
        if not known.get("model"):
            known["model"] = _subagent_model(_subagent_file(transcript_path, agent_id, ".jsonl"))
        info[agent_id] = known
    return {**doc, "agent_info": info}


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
    if doc.get("parent_active") or live_agents(doc):
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
           "turn_started": doc.get("turn_started")}
    now = round(time.time(), 3)

    if event == "UserPromptSubmit":
        # The one event that starts a turn; tool calls inside it keep this clock.
        doc["turn_started"] = now

    if is_fresh_start(event, payload):
        doc["agents"] = {}
        doc["finished"] = {}
        doc["agent_types"] = {}
        doc["agent_info"] = {}
        doc["gates"] = {}
        doc["last_tool"] = None

    if event == "PreToolUse":
        # The id a gate will need. PermissionRequest carries tool_name and
        # tool_input but no tool_use_id -- measured across 13 real gates on
        # 2026-09-08 -- and it arrives directly after the PreToolUse for the
        # same tool. That event has the id, so remember it.
        doc["last_tool"] = payload.get("tool_use_id") or doc["last_tool"]

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

    if said == "blocked":
        doc["gates"][payload.get("tool_use_id") or doc["last_tool"] or UNKEYED] = now
        # Asking to run a tool means a turn is under way.
        doc["parent_active"] = True
    elif said == "working":
        doc["parent_active"] = True
    elif said == "idle":
        # The parent's own turn ended. Its children may well outlive it, which
        # is why this is one input to aggregate and not the answer.
        doc["parent_active"] = False
        # Nothing runs while a permission prompt is open, so a turn that
        # reached its end had none pending. This is the bound on a gate nothing
        # could correlate, and it has to be this tight: waiting for the next
        # prompt instead left the badge standing for as long as the user took
        # to type, which in practice meant it never came down.
        doc["gates"] = {}

    return doc


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
            "last_tool": doc.get("last_tool") if isinstance(doc.get("last_tool"), str)
                         else None,
            "turn_started": doc.get("turn_started")
                            if isinstance(doc.get("turn_started"), (int, float)) else None}


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


def clear_state(session_id):
    """A session id is never reused, so anything left here leaks for the life
    of the machine.
    """
    if not session_id:
        return
    for path in (_state_path(session_id), _state_path(session_id) + ".lock"):
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


def claude_pid(tty):
    """The pid of the claude process owning this terminal, or None.

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
    for line in out.splitlines():
        pid, _, comm = line.strip().partition(" ")
        # The executable is the claude launcher itself; matching on the whole
        # path is what makes this work, since basename-only checks see "node".
        if "claude" in comm and "claude-status" not in comm:
            try:
                return int(pid)
            except ValueError:
                continue
    return None


def find_tty():
    """Hooks are setsid'd, so /dev/tty fails. Resolve the real device."""
    env_tty = os.environ.get("TTY")
    if env_tty and os.access(env_tty, os.W_OK):
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
        if out[0] not in ("??", "-") and os.access(device, os.W_OK):
            return device
        try:
            pid = int(out[-1])
        except ValueError:
            return None
    return None


def emit(value, target=None):
    target = target or find_tty()
    if not target:
        return
    encoded = base64.b64encode(value.encode()).decode()
    # ESC ST terminates, not BEL: iTerm2 flags a session as having had bell
    # activity on every BEL byte, even inside a well-formed OSC sequence.
    # Inside tmux passthrough every inner ESC must be doubled, per DCS rules.
    if os.environ.get("TMUX"):
        seq = f"\033Ptmux;\033\033]1337;SetUserVar=claudeState={encoded}\033\033\\\033\\"
    else:
        seq = f"\033]1337;SetUserVar=claudeState={encoded}\033\\"
    try:
        with open(target, "w") as tty:
            tty.write(seq)
    except OSError:
        pass


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = read_payload()
    state = state_for(event, payload)

    session_id = payload.get("session_id")
    if event == "SessionEnd":
        clear_state(session_id)
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
    pid = claude_pid(tty)

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
                                 "_agents": agents}) + "\n")
    except OSError:
        pass

    if state is None:
        pass                     # nothing this event should change
    elif state == "":
        emit("")
    else:
        emit(json.dumps({"state": state, "pid": pid,
                         "agents": agents, "subagents": subagents(doc),
                         "blocked_since": blocked_since(doc), "working_since": working_since(doc),
                         "ts": round(time.time())}),
             tty)

    # stdout belongs to the hook protocol. Anything else corrupts it.
    sys.stdout.write("{}")


if __name__ == "__main__":
    main()
