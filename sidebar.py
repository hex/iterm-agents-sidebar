#!/usr/bin/env python3.10
"""iTerm2 Toolbelt sidebar: every terminal session, agents first.

Runs as a Basic iTerm2 script (single file, stdlib only, no pip). The shebang
above is what iTerm2 parses to pick an interpreter -- it resolves
`iterm2env-3.10` from it -- so do not drop the version.
"""
import asyncio
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# AutoLaunch runs this file through runpy.run_path, which does not put its
# folder on the import path, so the modules beside it would not be found.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import accounts  # noqa: E402
import codex  # noqa: E402

#: Where the `cs` tool keeps its managed sessions. A terminal sitting anywhere
#: under here is an agent session even when nothing in the title says so.
CS_ROOT = Path.home() / ".claude-sessions"

#: Claude Code prefixes the terminal title with U+2733. It is the only signal
#: for an agent running outside a cs session directory -- jobName is useless
#: here, since it reports the foreground MCP subprocess (node, python3.12) or
#: nothing at all when there is no foreground job.
AGENT_TITLE_MARKER = "\u2733"

#: A working claim is refreshed by PostToolUse on every tool call, so silence
#: this long under one means the writer stopped reporting rather than that it
#: is still going. Generous, because a turn can think for a while without
#: touching a tool. Only `working` ages: idle is a resting state that nothing
#: refreshes and nothing needs to.
WORKING_GOES_STALE_AFTER = 300

#: A terminal whose foreground job is one of these is sitting at its prompt:
#: the shell itself is not a command anyone ran. A login shell reports "-zsh".
SHELLS = frozenset({"zsh", "bash", "fish", "sh", "dash", "ksh", "tcsh", "nu"})

#: What a row shows for anything iTerm2 could not tell us.
UNKNOWN = "?"

#: Everything v1 will do to a session. Deliberately short: nothing here takes
#: arbitrary code, and `send` targets a named session id only.
VERBS = ("focus", "send", "close",
         # focus that remembers where you were, and the trip back from it.
         "bring", "return")

#: What the page may do with accounts. Nothing here removes one.
ACCOUNT_OPS = ("add", "switch", "rename")

#: Settings live in a file, not in the page. The daemon takes an ephemeral
#: port, so the page's origin changes on every restart and anything stored
#: per-origin goes with it.
SETTINGS_FILE = Path.home() / ".claude" / "agents-sidebar-settings.json"

#: The daemon owns the shape. A key the page posts that is not here is a
#: version mismatch, not a new setting.
DEFAULT_SETTINGS = {
    "sound": True,
    "volume": 0.4,
    "sound_blocked": True,
    "sound_done": True,
    "focus_blocked": False,
    "return_after_blocked": True,
    "muted": False,
    "context_threshold": 70,
    "show_model": True,
    "show_branch": True,
    "show_agents": True,
    "show_shells": True,
    "expand_shells": False,
    # A multiplier on the stylesheet's own sizes, so 1.0 means "as designed".
    "ui_scale": 1.0,
}

#: (low, high) for the values that are numbers.
SETTING_RANGES = {"volume": (0.0, 1.0), "context_threshold": (0, 100),
                  # Below 0.8 the 9px metadata stops being readable; above 1.6
                  # a row no longer fits the 250px the Toolbelt gives us.
                  "ui_scale": (0.8, 1.6)}


def _clean(settings):
    """Keep only known keys, coerced and clamped to something usable."""
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        if key not in settings:
            continue
        value = settings[key]
        if isinstance(default, bool):
            out[key] = bool(value)
        else:
            try:
                value = type(default)(value)
            except (TypeError, ValueError):
                continue
            low, high = SETTING_RANGES[key]
            out[key] = max(low, min(high, value))
    return out


def load_settings(path=None):
    """-> the stored settings, filled in from the defaults.

    Any unreadable or half-written file falls back rather than taking the
    daemon down on the next start.
    """
    path = Path(path or SETTINGS_FILE)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)
    if not isinstance(stored, dict):
        return dict(DEFAULT_SETTINGS)
    return _clean(stored)


def save_settings(changes, path=None):
    """Merge `changes` over what is stored and write it back. -> the result."""
    path = Path(path or SETTINGS_FILE)
    merged = _clean({**load_settings(path), **(changes or {})})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    except OSError:
        pass
    return merged

#: Permanent. iterm2.tool exposes no unregister, so a tool identifier used
#: once sits in the Toolbelt forever.
TOOL_IDENTIFIER = "com.hex.agents-sidebar"
TOOL_DISPLAY_NAME = "Agents"


def classify(path, auto_name, agent_state=None):
    """One session's cwd, title and reported state -> (kind, label).

    Pure. `kind` is "agent" or "shell"; `label` is what the row shows.

    A path under the cs root is deliberately NOT evidence of an agent: it says
    which directory a terminal is in, not what is running there, and a shell
    cd'd into a session directory inherits the same path.
    """
    # iTerm2 hands back None for a variable it cannot resolve. Say so rather
    # than guessing -- a plausible wrong cwd is worse than a visible "?".
    resolved = Path(path) if path else None
    if resolved is None:
        label = UNKNOWN
    elif resolved == Path.home():
        label = "~"
    else:
        label = resolved.name

    marked = bool(auto_name) and auto_name.startswith(AGENT_TITLE_MARKER)
    # Union, not either alone: a session running inside tmux loses the marker
    # to tmux but still reports state, and an agent that has not reported yet
    # still carries the marker.
    if marked or agent_state:
        # A cwd says where a terminal is standing, not which session it is:
        # one session cd'd into another session's directory and took its name.
        # The marked title survives any cd, so prefer it when it is there.
        return ("agent", subagent_label(auto_name) or label if marked else label)
    return ("shell", label)


def agent_name(session_name):
    """A pane's name -> the agent running in it, or None.

    iTerm2 reports "agy-executor (node /path/to/mcp)" -- the agent's name, then
    whatever process is in the foreground. Only the first part identifies it.
    """
    if not session_name:
        return None
    # The marker is Claude Code's punctuation for "this pane is an agent", not
    # part of what the agent is called. A row reading "* general-purpose" is
    # showing the prefix as if it were a name.
    name = session_name.split(" (", 1)[0]
    return name.lstrip(AGENT_TITLE_MARKER).strip() or None


def subagent_label(auto_name):
    """A subagent pane's title -> the agent type it is running, or None.

    Claude Code titles a subagent pane with its type, e.g. "* general-purpose",
    which is what distinguishes it from the parent it shares a directory with.
    """
    if not auto_name:
        return None
    stripped = auto_name.lstrip(AGENT_TITLE_MARKER).strip()
    return stripped or None


def position(session, panes_in_tab, many_windows):
    """Where a session sits, as something a person can act on.

    Deliberately NOT tab_id: that is iTerm2's monotonic identifier, so six tabs
    can read t27. A number that looks like a position and is not one is the
    misleading display this design forbids.
    """
    where = "t{}".format(session["tab_index"])
    if panes_in_tab[(session["window_index"], session["tab_index"])] > 1:
        where += "\u00b7{}".format(session["pane_index"])
    if many_windows:
        # Tab indices restart per window, so t5 alone is ambiguous.
        where = "w{}\u00b7".format(session["window_index"]) + where
    return where


def snapshot(sessions):
    """Raw session dicts -> the payload the page renders.

    Agents first, then everything else; order within a group is the order
    handed in. Each input dict needs session_id, window_id, tab_id, path,
    auto_name and job_name.
    """
    # A tab is only worth numbering by pane when it actually has more than one,
    # and a window prefix is noise until a second window exists.
    panes_in_tab = {}
    for session in sessions:
        key = (session["window_index"], session["tab_index"])
        panes_in_tab[key] = panes_in_tab.get(key, 0) + 1
    many_windows = len({session["window_index"] for session in sessions}) > 1

    # A cs directory is one logical session however many panes it occupies. The
    # first pane found is the parent; later ones in the same directory are its
    # subagents, which is what the extra panes of an agent-team session are.
    # Grouping by directory rather than by title is deliberate: a session
    # running inside tmux loses its title to tmux, so titles cannot say which
    # pane is the parent.
    # Directory -> the rows in it, in the order they were enumerated. A child
    # must sit next to its own parent: depth without adjacency renders a
    # subagent under whichever unrelated row happens to precede it, which is a
    # lie the eye believes instantly.
    families = {}

    rows = {"agent": [], "shell": []}
    for session in sessions:
        kind, label = classify(session.get("path"), session.get("auto_name"),
                               session.get("agent_state"))
        resolved = Path(session["path"]) if session.get("path") else None
        # A family is one tab, not one directory. Two cs sessions open on the
        # same repo share a directory and nothing else, and keying on the
        # directory alone nested one under the other -- `cs: beacon` drawn as
        # a child of `atlas`, in a different tab, seen live 2026-09-08. A pane an
        # agent spawns is a split of that agent's own tab, so the tab is what
        # makes two panes relatives.
        home = (session.get("window_id"), session.get("tab_id"),
                session.get("path")) if session.get("path") else None
        # Sharing a directory is not enough to be a subagent: a plain shell
        # cd'd into a session directory shares it too, and nesting one under
        # the session -- labelled with its own prompt string -- is a lie the
        # indent makes look official. A real subagent pane carries Claude
        # Code's marker or has reported a state.
        # A subagent is a marked pane sharing a family with an agent already
        # listed, whose title differs from that parent's. Compared against the
        # parent's title rather than the current directory basename: a session
        # that cd's into a subdirectory changes the latter and would otherwise
        # look like a child of itself.
        # A teammate says so itself. Its transcript carries the team it was
        # spawned into; an ordinary session's carries none, however much else
        # the two have in common. Three earlier rules asked whether a pane
        # RESEMBLED a child -- marked title, shared directory, differing name
        # -- and each one nested a session that merely worked in the same
        # place. Resemblance was never evidence.
        #
        # A pane whose transcript cannot be read has no team and stays flat.
        # That is the safe direction: two rows say less, a false parent says
        # something untrue.
        # ...and something to be a child OF. A teammate whose lead has not
        # reported yet has no family to join, and an indent under nothing is
        # the same false claim pointing at empty space.
        child = (kind == "agent" and bool(session.get("team"))
                 and home is not None and bool(families.get(home)))
        if child:
            # A child repeating its parent's directory name would give two
            # identical rows. Prefer the agent's own name -- what Claude Code
            # puts on the teammate badge -- and fall back to its type.
            # The name Claude Code calls it by, then the name iTerm2 has for
            # the pane, then the agent type off the title. The type is the
            # weakest of the three: "general-purpose" says what a thing is and
            # never which one, so two of them are indistinguishable.
            label = (session.get("agent_name")
                     or agent_name(session.get("session_name"))
                     or subagent_label(session.get("auto_name"))
                     or label)

        row = {
            "depth": 1 if child else 0,
            "session_id": session["session_id"],
            "window_id": session["window_id"],
            "tab_id": session["tab_id"],
            "label": label,
            "position": position(session, panes_in_tab, many_windows),
        }
        # jobName is honest for a plain shell -- nvim really is what that
        # terminal is doing. For an agent it names the foreground MCP child, so
        # showing it would imply something false. An idle shell has no
        # foreground job at all, which is indistinguishable here from a job we
        # failed to read, so the column is omitted rather than claiming "?".
        job = session.get("job_name")
        if kind == "shell" and job and job.lstrip("-") not in SHELLS:
            row["job"] = job
            row["running"] = True

        # Optional signals. Absent means absent -- a key with a placeholder
        # would assert something false, and a session whose state cannot be
        # read is not "idle".
        if session.get("colour"):
            row["colour"] = session["colour"]
        if kind == "agent":
            # Claude rows are the page's unmarked default; others name themselves.
            if session.get("provider") not in (None, "claude"):
                row["provider"] = session["provider"]
            if session.get("agent_state"):
                row["state"] = session["agent_state"]
            if session.get("context") is not None:
                row["context"] = session["context"]
            if session.get("model"):
                row["model"] = session["model"]
            if session.get("effort"):
                row["effort"] = session["effort"]
            # Not nested under the branch: a session whose HEAD cannot be read
            # still has however many subagents it has.
            if session.get("agents"):
                row["agents"] = session["agents"]
            if session.get("subagents"):
                row["subagents"] = session["subagents"]
            if session.get("blocked_since") is not None:
                row["blocked_since"] = session["blocked_since"]
            if session.get("working_since") is not None:
                row["working_since"] = session["working_since"]
            if session.get("shells"):
                row["shells"] = session["shells"]
            if session.get("uptime") is not None:
                row["uptime"] = session["uptime"]
            if session.get("details"):
                row["details"] = session["details"]
        if session.get("branch"):
            row["branch"] = session["branch"]
        if kind == "agent" and home:
            families.setdefault(home, []).append(row)
        else:
            rows[kind].append(row)

    # Emit each family whole, in the order its parent first appeared, so the
    # list still never re-sorts on anything a session does.
    for family in families.values():
        rows["agent"].extend(family)

    groups = [
        {"name": "AGENTS", "rows": rows["agent"]},
        {"name": "SESSIONS", "rows": rows["shell"]},
    ]
    # A header over nothing reads as breakage, and costs a row of a narrow panel.
    return {"groups": [group for group in groups if group["rows"]]}


#: States the hooks can actually establish. "unknown" is reader-derived, not
#: emitted: it is what a row shows when the writer died mid-turn, leaving a
#: claim nobody is backing any more.
STATES = ("working", "blocked", "idle", "unknown")

#: iTerm2 renders context usage into user.claudeStatus as "886k (88%)".
CONTEXT_PERCENT = re.compile(r"\((\d{1,3})%\)")


def parse_state(raw):
    """The claudeState user variable -> one of STATES, or None if unset.

    Verifies the writer is still alive. SetUserVar is last-writer-wins with no
    concept of death, so a session killed mid-turn leaves "working" sitting in
    the variable indefinitely. A claim nobody is alive to back is "unknown".
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        state = payload["state"]
        pid = int(payload["pid"])
    except (ValueError, TypeError, KeyError):
        return "unknown"

    if state not in STATES:
        return "unknown"
    # Guard before kill(): pid 0 addresses the whole process group and negative
    # pids address other groups, so neither is a liveness question at all.
    if pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)          # signal 0 tests existence, sends nothing
    except (ProcessLookupError, ValueError):
        return "unknown"
    except PermissionError:
        pass                     # alive, just not ours to signal

    if state == "working":
        try:
            age = time.time() - float(payload.get("ts") or 0)
        except (TypeError, ValueError):
            return "unknown"
        if age > WORKING_GOES_STALE_AFTER:
            # The writer is alive but has gone quiet. Liveness answers whether
            # it exists, not whether it is still doing what it claimed.
            return "unknown"
    return state


#: claude-status writes "<glyph> <model>  <bar>  <tokens> (<pct>%)", with TWO
#: spaces between fields. The model itself may contain one -- it is either an
#: id like claude-opus-5 or a display name like "Fable 5.1", depending on which
#: branch of claude-status resolved it.
MODEL = re.compile(r"^\S+\s+(.+?)\s\s")


#: Claude Code sources this into every shell it opens. Matching on it rather
#: than on a shell's name survives a different $SHELL and ignores the user's
#: own subprocesses.
SHELL_MARKER = "/.claude/shell-snapshots/"


def parse_shells(raw):
    """`ps -eo pid=,ppid=,args=` -> {parent pid: shells it has open}.

    Counted from the process tree because nothing publishes it: the statusline
    payload has eighteen fields and none is this, and the transcript records
    nothing about shells either. Claude Code draws its own "N shells" from
    memory it never writes down.
    """
    counts = {}
    if not raw:
        return counts
    for line in raw.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or SHELL_MARKER not in parts[2]:
            continue
        try:
            # Both fields, not just the one we key on: a row whose pid does
            # not parse is not a ps row, and half of it is not evidence.
            int(parts[0])
            parent = int(parts[1])
        except ValueError:
            continue
        counts[parent] = counts.get(parent, 0) + 1
    return counts


def shell_command(args):
    """A Claude Code shell's ps args -> the command it is running, or None.

    Claude Code wraps every command as `... && eval '<cmd>' < /dev/null &&
    pwd -P >| /tmp/claude-XXXX-cwd`, quoting an embedded ' as '"'"'. ps prints
    newlines as \\012; they become "; " so the command fits on one row.
    """
    start = args.find(" eval '")
    if start < 0:
        return None
    body = args[start + len(" eval '"):]
    end = body.rfind(" && pwd -P >| ")
    if end >= 0:
        body = body[:end].removesuffix(" < /dev/null")
    body = body.removesuffix("'")
    lines = body.replace("'\"'\"'", "'").split("\\012")
    return "; ".join(line.strip() for line in lines if line.strip()) or None


#: One piece of setup at the front of a command: `cd <dir>` ended by ; or &&,
#: or a `NAME=value` assignment ended by ; or && or the command it prefixes.
_SETUP = re.compile(
    r"""^(?:cd\s+(?:"[^"]*"|'[^']*'|[^\s;&]+)\s*(?:;|&&)
         |[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|[^\s;&]*)(?:\s*(?:;|&&))?
        )\s*""", re.VERBOSE)


def shell_label(command):
    """A shell's command -> what its row shows: the command past its setup.

    Claude Code usually opens with a `cd` or a few variables, which read the
    same on every row and push the part that differs off the edge.
    """
    rest = command
    while (match := _SETUP.match(rest)) and match.end() < len(rest):
        rest = rest[match.end():]
    return rest


def uptime_seconds(etime):
    """ps ELAPSED -> seconds, or None.

    Four shapes depending on how long ago it started: MM:SS, HH:MM:SS,
    D-HH:MM:SS, and DD-HH:MM:SS. Anything else is not a duration.
    """
    if not etime or not etime.strip():
        return None
    days, _, clock = etime.strip().rpartition("-")
    parts = clock.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        numbers = [int(part) for part in parts]
        total = int(days) * 86400 if days else 0
    except ValueError:
        return None
    if len(numbers) == 3:
        total += numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        total += numbers[0] * 60 + numbers[1]
    return total


#: Claude Code passes a teammate its badge colour on the command line, and
#: records it nowhere else the sidebar can read.
_AGENT_COLOUR = re.compile(r"\s--agent-color[ =]([a-z]+)\b")


def parse_processes(raw):
    """One process listing -> (shell commands by parent pid, uptime by pid,
    teammate colour by pid).

    All three come off the same ps: running it once per fact per rebuild would
    be silly.
    """
    shells, uptime, colours = {}, {}, {}
    for line in (raw or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, parent, elapsed, args = parts
        try:
            pid, parent = int(pid), int(parent)
        except ValueError:
            continue
        seconds = uptime_seconds(elapsed)
        if seconds is not None:
            uptime[pid] = seconds
        if SHELL_MARKER in args:
            command = shell_command(args) or UNKNOWN
            shells.setdefault(parent, []).append(
                {"label": shell_label(command), "command": command})
        colour = _AGENT_COLOUR.search(args)
        if colour:
            colours[pid] = colour.group(1)
    return shells, uptime, colours


def read_processes():
    """Shell commands, uptimes and teammate colours, from one listing."""
    try:
        # -ww: the command sits at the end of a long line, past any width cap.
        out = subprocess.run(["/bin/ps", "-ww", "-eo", "pid=,ppid=,etime=,args="],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}, {}, {}
    return parse_processes(out)


#: Programs that run a script: the script names what is running, not them.
INTERPRETERS = re.compile(r"^(node|bun|deno|ruby|perl|php|python[0-9.]*)$")


def foreground_command(args):
    """A process's command line -> the short name of what it runs.

    `node .../bin/codex` is Codex, not node: an interpreter handed a script is
    named by the script. One given only flags (`python3 -m http.server`) keeps
    its own name.
    """
    words = args.split()
    if not words:
        return None
    name = os.path.basename(words[0])
    if INTERPRETERS.match(name) and len(words) > 1 and not words[1].startswith("-"):
        return os.path.basename(words[1])
    return name


def parse_foreground(out):
    """`ps -eo pid=,pgid=,tpgid=,tty=,args=` -> {tty: what its foreground runs}.

    A terminal's foreground job is its foreground process group; the group's
    leader is the command that was typed. Its children (a vendored binary, a
    helper) and background groups (MCP servers, prompt daemons) are not.
    """
    running = {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5 or parts[3] in ("??", "-"):
            continue
        pid, pgid, tpgid, tty, args = parts
        if pid == pgid == tpgid:
            command = foreground_command(args)
            if command:
                running[tty] = command
    return running


def parse_tmux_panes(out):
    """`tmux list-panes -a -F '#{pane_id} #{pane_tty} #{pane_current_path}'`
    -> {pane number: {tty, path}}. The path is last so one with spaces survives.
    """
    panes = {}
    for line in out.splitlines():
        pane, _, rest = line.partition(" ")
        tty, _, path = rest.partition(" ")
        if pane.startswith("%") and pane[1:].isdigit() and tty.startswith("/dev/"):
            panes[int(pane[1:])] = {"tty": tty.removeprefix("/dev/"), "path": path.strip() or None}
    return panes


#: Where tmux lives; the daemon starts from iTerm2 without a login shell's PATH.
TMUX_PATHS = ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux")


def read_tmux_panes():
    """{tmux pane number: {job, path}}, or {} without tmux.

    iTerm2 cannot see inside a tmux pane: it reports no jobName, and a `path`
    that can belong to another pane of the same tmux window, which gave
    sessions each other's branches and nested teammates under the wrong
    agent. tmux knows both. One tmux listing and one process listing per
    rebuild, however many panes there are.
    """
    tmux = next((path for path in TMUX_PATHS if os.path.exists(path)), None)
    if tmux is None:
        return {}
    try:
        panes = subprocess.run([tmux, "list-panes", "-a", "-F",
                                "#{pane_id} #{pane_tty} #{pane_current_path}"],
                               capture_output=True, text=True, timeout=3).stdout
        if not panes:
            return {}
        out = subprocess.run(["/bin/ps", "-ww", "-eo", "pid=,pgid=,tpgid=,tty=,args="],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    running = parse_foreground(out)
    return {number: {"job": running.get(pane["tty"]), "path": pane["path"]}
            for number, pane in parse_tmux_panes(panes).items()}


def read_shells():
    """Shell counts for every session, from one process listing.

    One subprocess per rebuild rather than one per row: this runs for every
    session every two seconds, and the per-row version of exactly this
    reasoning is why git_branch reads .git/HEAD instead of shelling out.
    """
    try:
        out = subprocess.run(["/bin/ps", "-eo", "pid=,ppid=,args="],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_shells(out)


def _reported_at(raw):
    try:
        ts = json.loads(raw)["ts"]
    except (ValueError, TypeError, KeyError):
        return None
    return ts if isinstance(ts, (int, float)) else None


def agent_variable(claude_raw, codex_raw):
    """A pane's claudeState and codexState -> (the one that speaks for it, provider).

    Both are set only when one agent left its variable behind and another
    started in the same pane (a Claude killed without SessionEnd, then Codex);
    the newer report is the one still running. Provider is "claude" or
    "openai", or None when neither reported.
    """
    if not codex_raw:
        return (claude_raw, "claude") if claude_raw else (None, None)
    if not claude_raw:
        return codex_raw, "openai"
    claude_ts, codex_ts = _reported_at(claude_raw), _reported_at(codex_raw)
    if codex_ts is not None and (claude_ts is None or codex_ts >= claude_ts):
        return codex_raw, "openai"
    return claude_raw, "claude"


def parse_codex(raw):
    """The codexState variable -> the model and rollout path the Codex hook published."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        payload = {}
    return {"model": payload.get("model"), "transcript_path": payload.get("transcript_path")}


def parse_pid(raw):
    """The claudeState variable -> the claude pid, or None.

    The same pid the statusline bridge files are named after. Zero and
    negative values are not pids at all, whatever else they mean to kill().
    """
    if not raw:
        return None
    try:
        pid = int(json.loads(raw)["pid"])
    except (ValueError, TypeError, KeyError):
        return None
    return pid if pid > 0 else None


def parse_agents(raw):
    """The claudeState payload -> how many subagents are running under it.

    Zero for anything unreadable: an unknown count is not a count.
    """
    if not raw:
        return 0
    try:
        return max(0, int(json.loads(raw).get("agents") or 0))
    except (ValueError, TypeError, AttributeError):
        return 0


def _epoch(value):
    """A JSON number of seconds, or None. bool is an int to Python; not here."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value)
    return None


def parse_subagents(raw):
    """The claudeState payload -> the running subagents: [{type, since}].

    An entry that is not an object is dropped; a field that is not what it
    should be becomes None rather than taking the entry down with it.
    """
    try:
        listed = json.loads(raw).get("subagents")
    except (ValueError, TypeError, AttributeError):
        return []
    if not isinstance(listed, list):
        return []
    text = lambda value: value if isinstance(value, str) and value else None
    return [{"type": text(item.get("type")), "since": _epoch(item.get("since")),
             "ended": _epoch(item.get("ended")),
             "name": text(item.get("name")), "model": short_model(item.get("model"))}
            for item in listed if isinstance(item, dict)]


def short_model(model_id):
    """A model id -> the name the statusline shows: claude-fable-5-1 -> Fable 5.1.

    Drops the "claude-" prefix, a trailing release date and a context-size
    suffix such as [1m]. An id that is not a Claude model is None, not a guess.
    """
    if not isinstance(model_id, str):
        return None
    found = re.fullmatch(r"claude-([a-z]+)((?:-\d{1,2})+)(?:-\d{8})?(?:\[\w+\])?", model_id)
    if not found:
        return None
    return found.group(1).capitalize() + " " + ".".join(found.group(2).strip("-").split("-"))


def parse_blocked_since(raw):
    """The claudeState payload -> when its oldest permission gate opened, or None."""
    try:
        return _epoch(json.loads(raw).get("blocked_since"))
    except (ValueError, TypeError, AttributeError):
        return None


def parse_working_since(raw):
    """The claudeState payload -> when the turn under way began, or None."""
    try:
        return _epoch(json.loads(raw).get("working_since"))
    except (ValueError, TypeError, AttributeError):
        return None


def parse_model(status):
    """user.claudeStatus -> a short model name, or None.

    Drops the "claude-" prefix, which is on every model and so carries no
    information in a 250px row. A session that has not resolved one reports
    the literal "unknown", which is worse than printing nothing.
    """
    if not status:
        return None
    found = MODEL.match(status.strip())
    if not found:
        return None
    name = found.group(1)
    if name == "unknown":
        return None
    return name[len("claude-"):] if name.startswith("claude-") else name


#: Where the statusline bridge drops each session's payload, one file per
#: claude pid. The bridge learns that pid for free: it is the $PPID of the
#: statusline process itself.
STATUS_DIR = os.path.expanduser("~/.claude/agents-sidebar-status")

#: How old a statusline payload may be and still describe its pid. Claude Code
#: renders at refreshInterval 1, so a live session rewrites its file every
#: second; anything this far behind belongs to a process that has stopped
#: rendering or died. macOS reuses pids, and these files outlive the process
#: they are named for, so without this a recycled pid reads as another
#: session's context.
STATUS_GOES_STALE_AFTER = 30


#: How much of a transcript's end to read. These files reach megabytes and
#: this runs per session on every rebuild, so the answer is taken from the end,
#: where it is also the most current.
TRANSCRIPT_TAIL_BYTES = 64 * 1024


def transcript_marks(path):
    """An agent's transcript -> what it is called and whose team it is on.

    Two facts a terminal cannot supply, both stamped on every user, assistant
    and attachment record:

    `agentName` is the name the agent was spawned with -- "ctx-fix" -- where
    the pane title carries only its type, "general-purpose". A type names a
    kind, so two general-purpose agents are indistinguishable by it.

    `teamName` is the one honest sign that a pane is somebody's teammate and
    not a session in its own right. Measured across every live transcript on
    2026-09-08: both teammates carried a team, and all seven ordinary cs
    sessions carried none. `isSidechain` does not separate them -- it reads
    False on both -- so this had to be measured rather than assumed.

    Reads the tail only, and yields nothing for anything it cannot parse: a
    rotated or half-written transcript should cost one row its name, not the
    snapshot.
    """
    blank = {"agent": None, "team": None}
    if not path:
        return blank
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - TRANSCRIPT_TAIL_BYTES)
            fh.seek(start)
            chunk = fh.read()
    except OSError:
        return blank
    lines = chunk.split(b"\n")
    # A seek lands mid-line, so the first is a fragment -- but only when the
    # file was actually longer than the window.
    if start:
        lines = lines[1:]
    found = dict(blank)
    for line in reversed(lines):
        if b'"agentName"' not in line and b'"teamName"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue                    # the last line is written as we read
        for key, field in (("agent", "agentName"), ("team", "teamName")):
            value = record.get(field)
            if found[key] is None and isinstance(value, str) and value.strip():
                found[key] = value.strip()
        if all(found.values()):
            break
    return found


def parse_status(raw):
    """Claude Code's statusline payload -> the three fields a row shows.

    This payload is the only place Claude Code publishes the size of the
    context window. The model id loses its "[1m]" suffix before the request
    goes out, so a percentage cannot be computed from the transcript however
    carefully you read it -- 143k tokens is 14% of one window and 71% of
    another, and nothing on disk says which.

    A missing or unreadable payload yields None for every field, so the row
    renders nothing rather than a figure we cannot stand behind.
    """
    blank = {"context": None, "model": None, "effort": None, "details": {},
             "transcript": None}
    if not raw:
        return blank
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return blank
    if not isinstance(payload, dict):
        return blank

    def field(section, key):
        holder = payload.get(section)
        return holder.get(key) if isinstance(holder, dict) else None

    used = field("context_window", "used_percentage")
    name = field("model", "display_name")
    if isinstance(name, str):
        # "Opus 5 (1M context)" -> "Opus 5". The window size is what the
        # percentage beside it is measured against, so printing both spends
        # a quarter of the row saying the same thing twice.
        name = name.split(" (", 1)[0].strip() or None
    transcript = payload.get("transcript_path")
    return {"context": int(used) if isinstance(used, (int, float)) else None,
            "model": name,
            "effort": field("effort", "level"),
            "details": details(payload, field),
            "transcript": transcript if isinstance(transcript, str) else None}


def details(payload, field):
    """Everything the payload knows that a 250px row cannot hold.

    Absent fields stay absent rather than becoming zero: a session that has
    published nothing should show no panel, not a panel full of nulls.
    """
    def limit(section, key):
        holder = payload.get("rate_limits")
        holder = holder.get(section) if isinstance(holder, dict) else None
        value = holder.get(key) if isinstance(holder, dict) else None
        return value if isinstance(value, (int, float)) else None

    def percent(section):
        value = limit(section, "used_percentage")
        return round(value) if value is not None else None

    cache = payload.get("prompt_cache")
    cache = cache if isinstance(cache, dict) else {}
    ratio = cache.get("hit_ratio")

    money = field("cost", "total_cost_usd")
    found = {
        "model": field("model", "display_name"),
        "model_id": field("model", "id"),
        "effort": field("effort", "level"),
        "thinking": field("thinking", "enabled"),
        "output_style": field("output_style", "name"),
        "fast_mode": payload.get("fast_mode"),
        "beyond_200k": payload.get("exceeds_200k_tokens"),
        "version": payload.get("version"),
        "session_name": payload.get("session_name"),
        "five_hour": percent("five_hour"),
        "seven_day": percent("seven_day"),
        "cost": round(money, 2) if isinstance(money, (int, float)) else None,
        "lines_added": field("cost", "total_lines_added"),
        "lines_removed": field("cost", "total_lines_removed"),
        # When each window frees up. A percentage on its own says how much is
        # gone; with a reset it says whether to wait or move on.
        "five_hour_at": limit("five_hour", "resets_at"),
        "seven_day_at": limit("seven_day", "resets_at"),
        # What a cold cache would cost on the next turn. The strongest
        # act-now number the payload carries.
        "cache_hit": round(ratio * 100) if isinstance(ratio, (int, float)) else None,
        "cache_cold_at": cache.get("expires_at"),
        "recache": cache.get("recache_tokens_if_cold"),
    }
    return {k: v for k, v in found.items() if v is not None}


def read_status(pid):
    """The newest statusline payload for a claude process, by pid.

    Refuses one that has stopped being refreshed. The bridge rewrites this
    file every render, so a current file is always seconds old; an old one is
    a dead session, or a pid the system has handed to somebody else.
    """
    if not pid:
        return parse_status(None)
    path = os.path.join(STATUS_DIR, f"{int(pid)}.json")
    try:
        if time.time() - os.path.getmtime(path) > STATUS_GOES_STALE_AFTER:
            return parse_status(None)
        with open(path) as fh:
            return parse_status(fh.read())
    except (OSError, ValueError):
        return parse_status(None)


def parse_context(status):
    """user.claudeStatus -> percent of context used, or None.

    The string is built for human eyes ("* claude-opus-5  --*-------  270k
    (27%)"), so read only the part that is unambiguous.
    """
    if not status:
        return None
    found = CONTEXT_PERCENT.search(status)
    return int(found.group(1)) if found else None


def git_branch(path):
    """The branch a directory is on, or None.

    Reads .git/HEAD directly rather than shelling out to git: this runs for
    every session on every rebuild, and a subprocess per session per two
    seconds is a real cost for a string sitting in a file.
    """
    if not path:
        return None
    here = Path(path)
    for folder in [here, *here.parents]:
        marker = folder / ".git"
        if not marker.exists():
            continue
        head = marker / "HEAD"
        if marker.is_file():
            # A worktree or submodule: .git is a file pointing at the real dir.
            try:
                pointer = marker.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if not pointer.startswith("gitdir:"):
                return None
            head = Path(pointer.split(":", 1)[1].strip()) / "HEAD"
        try:
            ref = head.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if ref.startswith("ref: refs/heads/"):
            return ref[len("ref: refs/heads/"):] or None
        # Detached: HEAD holds the commit itself, so show enough to recognise.
        return ref[:7] if ref else None
    return None


def session_colour(path):
    """A cs session directory -> the colour the user gave it, or None.

    cs stores it in .cs/local/state, which is machine-local and gitignored, so
    it is read live rather than cached.
    """
    if not path:
        return None
    state_file = Path(path) / ".cs" / "local" / "state"
    try:
        for line in state_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "claude_session_color":
                return value.strip() or None
    except OSError:
        return None
    return None


def parse_request(raw):
    """Raw request head -> (method, target, content_length).

    (None, None, 0) for anything that is not a request line. WebKit is not the
    only thing that can reach this port -- a stray TLS handshake or a port
    scanner must not take the daemon down.
    """
    try:
        head = raw.decode("latin-1")
        request_line, *header_lines = head.split("\r\n")
        method, target, version = request_line.split(" ")
        if not version.startswith("HTTP/"):
            return (None, None, 0)
    except ValueError:
        return (None, None, 0)

    length = 0
    for line in header_lines:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            try:
                length = int(value.strip())
            except ValueError:
                length = 0
    return (method, target, length)


def sse_frame(payload):
    """One Server-Sent Events message carrying a JSON snapshot.

    json.dumps escapes newlines by default, which matters here: a literal
    newline inside `data:` would split one frame into two and desynchronise the
    stream, and a session label is a directory name, which can contain one.
    """
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def heartbeat_frame(fresh):
    """A named event the page counts. Two missed in a row and it paints the
    whole list STALE rather than keep showing plausible old data.

    It carries a verdict because arriving is not the same as being right. The
    heartbeat runs on its own timer, so it kept beating through a stalled or
    failing iTerm2 refresh and the page read that as proof of freshness --
    every row and every permission badge looking current indefinitely, which
    is the exact failure the STALE banner exists to prevent.
    """
    return b'event: heartbeat\ndata: {"fresh": ' + (b"true" if fresh else b"false") + b'}\n\n'


def rebuild_is_fresh(last_ok, now):
    """Has a rebuild succeeded recently enough to trust what is on screen?

    Pure, so the threshold is testable without a clock. `last_ok` is None until
    the first rebuild lands: a daemon that has never read iTerm2 has nothing to
    show, and an empty list is not the same as no sessions.

    Three poll intervals, so a single slow refresh on a busy iTerm2 does not
    flap the banner. Two consecutive misses is a stall.
    """
    if last_ok is None:
        return False
    return (now - last_ok) <= POLL_SECONDS * 3


class ReturnTrips:
    """Where to go back to once a session you were brought to is answered.

    One trip per brought-forward session, so chained blocks unwind in order.
    A trip is used once, and only while you are still on that session: if you
    moved somewhere yourself, that was deliberate and is left alone.
    """

    def __init__(self):
        self._from = {}

    def leave(self, session_id, active):
        """Note the session that was in front before `session_id` is brought."""
        if active and active != session_id:
            self._from[session_id] = active
        else:
            self._from.pop(session_id, None)

    def back(self, session_id, active):
        """`session_id` resumed. -> the session to return to, or None."""
        origin = self._from.pop(session_id, None)
        return origin if active == session_id else None


class Sidebar:
    """Request handling, independent of the socket that carried the request.

    Splitting it this way keeps auth and dispatch testable without a live
    iTerm2 or a real listener.
    """

    def __init__(self, token, page_path, snapshot_fn, action_fn,
                 settings_path=None, accounts_fn=None):
        self.token = token
        self.page_path = Path(page_path)
        self.snapshot_fn = snapshot_fn
        self.action_fn = action_fn
        self.settings_path = settings_path
        self.accounts_fn = accounts_fn

    def authorized(self, target):
        supplied = parse_qs(urlsplit(target).query).get("token", [""])[0]
        # Constant time: the token is the only thing between a local process
        # and an API that focuses terminals and types into them.
        return hmac.compare_digest(supplied, self.token)

    def handle(self, method, target, body):
        """-> (status, content_type, body bytes)."""
        if not self.authorized(target):
            return (403, "text/plain; charset=utf-8", b"forbidden")

        path = urlsplit(target).path
        if path == "/settings":
            if method == "POST":
                try:
                    changes = json.loads(body or b"{}")
                except ValueError:
                    return self._json(400, {"error": "malformed body"})
                return self._json(200, save_settings(changes, self.settings_path))
            return self._json(200, load_settings(self.settings_path))
        if method == "POST" and path == "/action":
            return self._action(body)
        if method == "POST" and path == "/accounts":
            return self._accounts(body)

        # Read the page from disk per request, so editing it needs no restart.
        return (200, "text/html; charset=utf-8", self.page_path.read_bytes())

    def _action(self, body):
        try:
            request = json.loads(body or b"{}")
        except ValueError:
            return self._json(400, {"error": "malformed body"})

        verb = request.get("verb")
        session_id = request.get("session_id")
        if verb not in VERBS or not session_id:
            return self._json(400, {"error": "unknown verb"})

        self.action_fn(session_id, verb, request.get("text"))
        return self._json(200, {"ok": True})

    def _accounts(self, body):
        try:
            request = json.loads(body or b"{}")
            op = request.get("op")
        except (ValueError, AttributeError):
            return self._json(400, {"error": "malformed body"})
        if op not in ACCOUNT_OPS or self.accounts_fn is None:
            return self._json(400, {"error": "unknown account op"})
        if op in ("switch", "rename") and not isinstance(request.get("account_id"), str):
            return self._json(400, {"error": f"{op} needs an account_id"})
        if op == "rename" and not isinstance(request.get("alias"), str):
            return self._json(400, {"error": "rename needs an alias"})
        try:
            result = self.accounts_fn(op, request)
        except (ValueError, accounts.KeychainError, accounts.SwitchRefused) as refusal:
            # A refusal the person can act on: nobody logged in, a locked
            # Keychain, a store the panel will not overwrite.
            return self._json(409, {"error": str(refusal)})
        return self._json(200, {"ok": True, "account": result})

    @staticmethod
    def _json(status, payload):
        return (status, "application/json", json.dumps(payload).encode())


HEARTBEAT_SECONDS = 4
#: How often the meter loop looks for due accounts. Each account still waits
#: its own poll interval; this only bounds how late a due reading starts.
ACCOUNT_TICK_SECONDS = 30
POLL_SECONDS = 2

#: Variables Bridge reads per session. `path` and `autoName` drive classify;
#: `jobName` is display only, and only on shell rows.
SESSION_VARIABLES = ("path", "autoName", "jobName", "name", "tmuxWindowPane",
                     # Written by the plugin hook (Claude Code and Codex) and by claude-status.
                     "user.claudeState", "user.codexState", "user.claudeStatus")


class Server:
    """The asyncio listener. A thin adapter over Sidebar.handle plus the one
    thing handle cannot express: a response that never ends (SSE).
    """

    def __init__(self, sidebar, health_fn=lambda: True):
        self.sidebar = sidebar
        self.subscribers = set()
        #: Whether the data behind a heartbeat is current. Late-bound the same
        #: way snapshot_fn is: Bridge needs the Server, so it cannot exist yet.
        self.health_fn = health_fn

    def broadcast(self, frame):
        for queue in list(self.subscribers):
            queue.put_nowait(frame)

    async def _events(self, writer):
        queue = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            writer.write(b"HTTP/1.1 200 OK\r\n"
                         b"Content-Type: text/event-stream\r\n"
                         b"Cache-Control: no-store\r\n"
                         b"Connection: keep-alive\r\n\r\n")
            # Current state immediately, so a reconnecting page is never blank
            # while it waits for something to change.
            writer.write(sse_frame(self.sidebar.snapshot_fn()))
            await writer.drain()
            print("sidebar: page connected", flush=True)
            while True:
                writer.write(await queue.get())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            self.subscribers.discard(queue)

    async def _client(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                asyncio.TimeoutError, ConnectionResetError):
            writer.close()
            return

        method, target, length = parse_request(head)
        if method is None:
            writer.close()
            return

        body = await reader.readexactly(length) if length else b""

        if urlsplit(target).path == "/events":
            if not self.sidebar.authorized(target):
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                writer.close()
                return
            await self._events(writer)
            writer.close()
            return

        if urlsplit(target).path == "/accounts":
            # Account ops wait on the Keychain, Claude Code's locks and the
            # network, for seconds; off the loop, the heartbeat keeps going.
            status, content_type, payload = await asyncio.to_thread(
                self.sidebar.handle, method, target, body)
        else:
            status, content_type, payload = self.sidebar.handle(method, target, body)
        writer.write(f"HTTP/1.1 {status} OK\r\n"
                     f"Content-Type: {content_type}\r\n"
                     f"Content-Length: {len(payload)}\r\n"
                     f"Cache-Control: no-store\r\n"
                     f"Connection: close\r\n\r\n".encode() + payload)
        await writer.drain()
        writer.close()

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            self.broadcast(heartbeat_frame(self.health_fn()))

    async def start(self):
        """-> the OS-assigned port. Ephemeral is safe: re-registering the tool
        identifier with a new URL is proven to follow (spike, 2026-09-07).
        """
        server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        asyncio.ensure_future(self._heartbeat())
        return server.sockets[0].getsockname()[1]


class Bridge:
    """The only part that needs a live iTerm2. Deliberately without logic:
    read sessions, hand them to snapshot, push if the result changed.

    It polls rather than registering a VariableMonitor per session per
    variable. Per-session monitors would need teardown as sessions come and
    go, and a lifecycle bug there shows stale rows -- the exact failure this
    sidebar is built to avoid. LayoutChangeMonitor makes window and tab churn
    instant, so the interval only bounds cwd and title drift.
    """

    def __init__(self, connection, server, meters=None):
        self.connection = connection
        self.server = server
        self.meters = meters
        self.app = None
        self.latest = {"groups": []}
        self._last_pushed = None
        #: When a rebuild last completed. None until the first one lands, so a
        #: daemon that has never reached iTerm2 reports unfresh rather than
        #: publishing its empty starting list as though it were an answer.
        self.last_ok = None
        self.trips = ReturnTrips()

    def active_session_id(self):
        """The session in front of the key iTerm2 window, or None."""
        window = self.app.current_terminal_window
        tab = window.current_tab if window else None
        session = tab.current_session if tab else None
        return session.session_id if session else None

    async def read_sessions(self):
        shells, uptime, agent_colours = read_processes()
        tmux_panes = read_tmux_panes()
        rows = []
        for window_index, window in enumerate(self.app.terminal_windows, start=1):
            for tab_index, tab in enumerate(window.tabs, start=1):
                for pane_index, session in enumerate(tab.sessions, start=1):
                    values = {}
                    for name in SESSION_VARIABLES:
                        try:
                            values[name] = await session.async_get_variable(name)
                        except Exception:            # noqa: BLE001
                            # Unreadable is a real state, not an error to hide.
                            # classify renders it as "?".
                            values[name] = None
                    pane = tmux_panes.get(values["tmuxWindowPane"]) or {}
                    # tmux's directory for its own pane over iTerm2's guess.
                    values["path"] = pane.get("path") or values["path"]
                    raw, provider = agent_variable(values["user.claudeState"], values["user.codexState"])
                    pid = parse_pid(raw)
                    if provider == "openai":
                        # Codex has no statusline: the hook names the model and
                        # the rollout has the rest.
                        published = parse_codex(raw)
                        status = dict(parse_status(None), model=published["model"],
                                      **codex.read_session(published["transcript_path"]))
                    else:
                        status = read_status(pid)
                    marks = transcript_marks(status.get("transcript"))
                    rows.append({
                        "session_id": session.session_id,
                        "window_id": window.window_id,
                        "tab_id": tab.tab_id,
                        # Positions, not ids: tab_id is monotonic, so six tabs
                        # can read t27. Only an index is actionable.
                        "window_index": window_index,
                        "tab_index": tab_index,
                        "pane_index": pane_index,
                        "path": values["path"],
                        "auto_name": values["autoName"],
                        "session_name": values["name"],
                        "job_name": values["jobName"] or pane.get("job"),
                        "provider": provider,
                        "agent_state": parse_state(raw),
                        "agents": parse_agents(raw),
                        "subagents": parse_subagents(raw),
                        "blocked_since": parse_blocked_since(raw),
                        "working_since": parse_working_since(raw),
                        "context": status["context"],
                        "model": status["model"],
                        "effort": status["effort"],
                        "details": status["details"],
                        # Read here, not in snapshot: the transcript is IO and
                        # snapshot is the pure unit that the tests pin down.
                        "agent_name": marks["agent"],
                        "team": marks["team"],
                        "shells": shells.get(pid, []),
                        "uptime": uptime.get(pid),
                        # A teammate wears the colour it was spawned with; a
                        # session wears the one cs gave its directory.
                        "colour": agent_colours.get(pid)
                                  or session_colour(values["path"]),
                        "branch": git_branch(values["path"]),
                    })
        return rows

    def healthy(self):
        return rebuild_is_fresh(self.last_ok, time.monotonic())

    async def rebuild(self):
        await self.app.async_refresh()
        self.latest = snapshot(await self.read_sessions())
        if self.meters is not None:
            self.latest["accounts"] = self.meters.snapshot()
        # A few file reads; kept off the loop like every other disk or Keychain read.
        self.latest["codex"] = await asyncio.to_thread(codex.read_limits, codex.SESSIONS_DIR, time.time())
        # Stamped only on the way out: a refresh that raised has not produced
        # anything worth calling current.
        self.last_ok = time.monotonic()
        frame = sse_frame(self.latest)
        if frame != self._last_pushed:
            self._last_pushed = frame
            self.server.broadcast(frame)

    async def act(self, session_id, verb, text):
        session = self.app.get_session_by_id(session_id)
        if session is None:
            # A row can outlive the session it names: the page holds a
            # snapshot. Say so in the Script Console rather than pretending
            # the action worked.
            print(f"sidebar: {verb} on {session_id}: gone", flush=True)
            return
        if verb == "bring":
            self.trips.leave(session_id, self.active_session_id())
        if verb in ("focus", "bring"):
            await session.async_activate(select_tab=True, order_window_front=True)
        elif verb == "return":
            origin = self.app.get_session_by_id(
                self.trips.back(session_id, self.active_session_id()) or "")
            if origin is None:
                print(f"sidebar: return from {session_id}: stayed", flush=True)
                return
            await origin.async_activate(select_tab=True, order_window_front=True)
        elif verb == "send":
            await session.async_send_text(text or "")
        elif verb == "close":
            # Forced: the page has already asked for a second click, and
            # iTerm2's own "a job is running" prompt would then ask a third
            # time, behind the panel, for every agent pane.
            await session.async_close(force=True)
        print(f"sidebar: {verb} on {session_id}: ok", flush=True)

    async def watch_layout(self):
        import iterm2

        try:
            async with iterm2.LayoutChangeMonitor(self.connection) as monitor:
                while True:
                    await monitor.async_get()
                    await self.rebuild()
        except Exception as error:                   # noqa: BLE001
            # Losing this only costs instant window and tab updates -- poll
            # still runs -- but say so rather than dying at GC time with an
            # unretrieved task exception.
            print(f"sidebar: layout monitor stopped, falling back to polling "
                  f"every {POLL_SECONDS}s: {error!r}", flush=True)

    def account_op(self, op, request):
        """Add the live login, switch to or rename a stored one, then read accounts now.

        Runs in the server's worker thread, not on the loop, so the reading
        that follows is made here directly.
        """
        if op == "add":
            result = self.meters.add(time.time())
        elif op == "rename":
            result = self.meters.rename(request["account_id"], request["alias"])
        else:
            result = self.meters.switch(request["account_id"], time.time())
        self.meters.tick(time.time())
        return result

    async def watch_accounts(self):
        """Read account usage in the background; rebuild picks the result up.

        Every reading is Keychain and network IO that can take seconds, so it
        runs in a thread: on the event loop it would stall the heartbeat and
        flag the whole panel stale.
        """
        while True:
            try:
                await asyncio.to_thread(self.meters.tick, time.time())
            except Exception as error:               # noqa: BLE001
                print(f"sidebar: account meters failed: {error!r}", flush=True)
            await asyncio.sleep(ACCOUNT_TICK_SECONDS)

    async def poll(self):
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                await self.rebuild()
            except Exception as error:               # noqa: BLE001
                # Reaches iTerm2's log via the webview "logger" handler is not
                # available here, so print -- the Script Console shows it.
                print(f"sidebar: rebuild failed: {error!r}", flush=True)


async def main(connection):
    import iterm2
    import iterm2.tool

    here = Path(__file__).resolve().parent
    token = secrets.token_urlsafe(24)

    claude_dir, claude_json = accounts.claude_paths(os.environ, str(Path.home()), os.path.exists)
    meters = accounts.AccountMeters(accounts.STORE_PATH, accounts.PANEL_SERVICE,
                                    accounts.live_item(), claude_json, claude_dir=claude_dir)
    sidebar = Sidebar(
        token=token,
        page_path=here / "page.html",
        snapshot_fn=lambda: bridge.latest,
        action_fn=lambda session_id, verb, text: asyncio.ensure_future(
            bridge.act(session_id, verb, text)),
        accounts_fn=lambda op, request: bridge.account_op(op, request),
    )
    server = Server(sidebar, health_fn=lambda: bridge.healthy())
    bridge = Bridge(connection, server, meters)
    bridge.app = await iterm2.async_get_app(connection)

    port = await server.start()
    await bridge.rebuild()

    await iterm2.tool.async_register_web_view_tool(
        connection, TOOL_DISPLAY_NAME, TOOL_IDENTIFIER, True,
        f"http://127.0.0.1:{port}/?token={token}")
    print(f"sidebar: serving on 127.0.0.1:{port}", flush=True)

    asyncio.ensure_future(bridge.watch_layout())
    asyncio.ensure_future(bridge.poll())
    asyncio.ensure_future(bridge.watch_accounts())


if __name__ == "__main__":
    import iterm2
    iterm2.run_forever(main)
