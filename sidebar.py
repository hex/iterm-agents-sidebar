#!/usr/bin/env python3.10
"""iTerm2 Toolbelt sidebar: every terminal session, agents first.

Runs as a Basic iTerm2 script (single file, stdlib only, no pip). The shebang
above is what iTerm2 parses to pick an interpreter -- it resolves
`iterm2env-3.10` from it -- so do not drop the version.
"""
import asyncio
import datetime
import hmac
import json
import math
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
import context_usage  # noqa: E402
import omp  # noqa: E402
import sound  # noqa: E402
import statusline  # noqa: E402
import update  # noqa: E402

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

#: How long a resume typed into a pane holds its button down while nothing
#: reports and the pane is back at the shell it was typed at: long enough for
#: the agent to start, short enough to try again after one that did not.
RESUME_HOLD = 60

#: A terminal whose foreground job is one of these is sitting at its prompt:
#: the shell itself is not a command anyone ran. A login shell reports "-zsh".
SHELLS = frozenset({"zsh", "bash", "fish", "sh", "dash", "ksh", "tcsh", "nu"})

#: What a row shows for anything iTerm2 could not tell us.
UNKNOWN = "?"

#: Everything v1 will do to a session. Deliberately short: nothing here takes
#: arbitrary code, and `send` targets a named session id only.
VERBS = ("focus", "send", "close",
         # focus that remembers where you were, and the trip back from it.
         "bring", "return",
         # a macOS notice; the text names the moment, never the message.
         "notify",
         # reopen an exited agent's conversation where it died; the daemon
         # builds the command, the page sends no text.
         "resume",
         # pick an option of a standing AskUserQuestion; the daemon checks
         # the question and types only its digit.
         "answer",
         # one of the panel's two sounds, named by kind; the daemon plays a
         # fixed tone, and whether it plays at all is the settings' call.
         "sound")

#: What the page may do with accounts. Nothing here removes one.
ACCOUNT_OPS = ("add", "switch", "rename", "read")

#: Settings live in a file, not in the page. The daemon takes an ephemeral
#: port, so the page's origin changes on every restart and anything stored
#: per-origin goes with it.
SETTINGS_FILE = Path.home() / ".claude" / "agents-sidebar-settings.json"

#: The release number, YYYY.M.BUILD, written by release.sh. Nothing else
#: carries it: the plugin manifest and the panel both read from here.
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"


def version(path=None):
    """-> the release number, or None for a checkout that has none."""
    try:
        return (path or VERSION_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None

#: The daemon owns the shape. A key the page posts that is not here is a
#: version mismatch, not a new setting.
DEFAULT_SETTINGS = {
    "sound": True,
    "volume": 0.4,
    "sound_blocked": True,
    "sound_done": True,
    "focus_blocked": False,
    "return_after_blocked": True,
    "notify": True,
    "notify_blocked": True,
    "notify_done": True,
    # Leave an account that is filling up, without being asked.
    "auto_switch": False,
    "context_threshold": 40,
    # A session tree at or over either reads as heavy: percent of one core,
    # and gigabytes resident.
    "cpu_threshold": 100,
    "memory_threshold": 2.0,
    "show_model": True,
    "show_branch": True,
    "show_task": True,
    "show_task_activity": True,
    "show_task_age": True,
    "show_task_bar": True,
    "show_task_list": True,
    # The foot offers the statusline bridge while settings.json lacks it,
    # until the offer is declined.
    "offer_statusline": True,
    "show_agents": True,
    "show_shells": True,
    # The list follows the terminals by default: a card sits where its tab
    # does, and nothing a session does moves it.
    "sort_by_name": False,
    "expand_shells": False,
    # A multiplier on the stylesheet's own sizes, so 1.0 means "as designed".
    "ui_scale": 1.0,
    # How a card says which agent runs in it, beyond the glyph on its facts line.
    "provider_mark": "groups",
}

#: (low, high) for the values that are numbers.
SETTING_RANGES = {"volume": (0.0, 1.0), "context_threshold": (0, 100),
                  "cpu_threshold": (25, 1600), "memory_threshold": (0.5, 32.0),
                  # Below 0.8 the 9px metadata stops being readable; above 1.6
                  # a row no longer fits the 250px the Toolbelt gives us.
                  "ui_scale": (0.8, 1.6)}


#: The values a setting that is one of a few words can take.
SETTING_CHOICES = {"provider_mark": ("tag", "corner", "groups", "off")}


def _clean(settings):
    """Keep only known keys, coerced and clamped to something usable."""
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        if key not in settings:
            continue
        value = settings[key]
        if isinstance(default, bool):
            out[key] = bool(value)
        elif key in SETTING_CHOICES:
            if isinstance(value, str) and value in SETTING_CHOICES[key]:
                out[key] = value
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
TOOL_IDENTIFIER = "com.hexul.agents-sidebar"
TOOL_DISPLAY_NAME = "Agents"

#: Clicking a notice brings iTerm2 forward. Which tab it lands on is whichever
#: was last in front: reaching a named session would mean baking this daemon's
#: port and token into the notification, and both change on every restart.
ITERM_BUNDLE_ID = "com.googlecode.iterm2"

#: Our own sender, assembled by install.sh: a notification wears its sender's
#: icon and name and nothing the poster passes changes that, and
#: UNUserNotificationCenter refuses to run outside a bundle. Both reasons the
#: bundle exists.
NOTIFIER_APP = Path.home() / ".local" / "share" / "agents-sidebar" / "Agents.app"

#: What each moment says. The session's own name is the title, so the message
#: only has to finish the sentence.
NOTIFY_MESSAGES = {
    "blocked": "is asking a question",
    "done": "finished a turn",
}

#: One standing notice for account switches: a second switch replaces the first.
SWITCH_NOTICE_ID = "account-switch"


def switch_notice_argv(app, name, why):
    """agents-notifier's argv for an account the daemon switched to on its own."""
    exe = str(Path(app) / "Contents" / "MacOS" / "agents-notifier")
    return [exe, "post", "--id", SWITCH_NOTICE_ID, "--title", f"Switched to {name}", "--body", why]


def switch_log_line(event):
    """One account event from the meter loop, as the log says it."""
    if event["kind"] == "switched":
        return f"auto-switch -> {event['name']} ({event['why']})"
    if event["kind"] == "blocked":
        return f"auto-switch: nowhere to go, {event['why']}"
    return f"auto-switch refused: {event['why']}"

#: macOS shows no more buttons than this on a notice.
NOTICE_BUTTONS = 4


def notify_argv(app, session_id, name, kind, question):
    """agents-notifier's argv for one moment, or None for a moment we skip.

    `kind` is a key of NOTIFY_MESSAGES, or "clear" to take a standing notice
    down. `question` is the row's, when the session is asking one: its
    options become buttons, and Other -- which Claude Code always offers --
    becomes the reply field. A multi-select question gets neither, since one
    button cannot express several picks. Any other gated tool gets a single
    Allow button. A finished turn offers a reply that becomes the next prompt.
    """
    exe = str(Path(app) / "Contents" / "MacOS" / "agents-notifier")
    if kind == "clear":
        return [exe, "remove", "--id", session_id]
    body = NOTIFY_MESSAGES.get(kind)
    if body is None:
        return None
    argv = [exe, "post", "--id", session_id,
            # The sender titles an empty string with its own name, which is
            # not what this is about.
            "--title", name or "Session"]
    if kind == "done":
        return argv + ["--body", body, "--reply", "Next prompt"]
    if question and "options" in question:
        body = question.get("question") or body
        if question.get("more"):
            body += f" (+{question['more']} more)"
        argv += ["--body", body]
        if not question.get("multi"):
            for n, label in enumerate(question["options"][:NOTICE_BUTTONS], 1):
                argv += ["--button", f"{n}={label}"]
            argv += ["--reply", "Other"]
        return argv
    if question and question.get("tool"):
        # One action is all macOS shows flat; two fold into an Options menu.
        # Allow is the one worth a click, and No stays in the terminal.
        return argv + ["--body", "wants to run: " + (question.get("summary") or question["tool"]),
                       "--button", "allow=Allow"]
    return argv + ["--body", body]


def notify_response(line, kind, question):
    """One line the sender printed -> (verb, text) for act, or (None, None).

    A click brings the session forward. Allow on a tool gate sends 1, the
    Yes of every permission prompt. A button sends the digit that picks
    that option: Claude Code's prompt takes the number outright, and a digit
    that somehow misses moves a cursor and confirms nothing. A reply to a
    question picks Other -- the option after the last listed -- and types
    the text; a reply to a finished turn is the next prompt. Both are sent
    only while the question the buttons were built for still stands, since
    keystrokes into whatever replaced it are the one failure this must not
    have.
    """
    try:
        response = json.loads(line)
        action = response.get("action")
    except (ValueError, TypeError, AttributeError):
        return None, None
    if action == "default":
        return "bring", None
    if action == "reply":
        text = response.get("text") or ""
        if kind == "done":
            return "send", text + "\n"
        if question and "options" in question:
            return "send", f"{len(question['options']) + 1}{text}\n"
        return None, None
    if action == "allow" and question and question.get("tool") and "options" not in question:
        # Yes is option 1 on every Claude Code permission prompt.
        return "send", "1"
    if isinstance(action, str) and action.isdigit() and question and "options" in question:
        if 1 <= int(action) <= min(len(question["options"]), NOTICE_BUTTONS):
            return "send", action
    return None, None


def _typed(standing, answered):
    """How many steps of the standing question the card has typed: the
    answered entry names that question, with its count (1 when it has none)."""
    if not isinstance(answered, dict):
        return 0
    if {key: value for key, value in answered.items() if key != "typed"} != standing:
        return 0
    return answered.get("typed", 1)


def next_answered(standing, answered):
    """The answered entry once one more step of `standing` has been typed."""
    return {**standing, "typed": _typed(standing, answered) + 1}


def answer_keys(text, standing, answered):
    """A click on a card's answer button -> the digit to type, or None.

    The page sends the option's number and the question it drew the button
    for; `standing` is the row's question now and `answered` what this
    session has typed into it from the card. The digit goes only to the
    question the button was drawn for, once: a replaced question and a second
    click send nothing. A set is walked in order: each question once, then
    Submit (1; 2 is Cancel, which throws the set away), and a click must name
    the step the daemon expects next. A question answered in the terminal is
    not seen, so the card's next click answers the question after it. A
    multi-select question is never answered here, since its digits toggle
    boxes and submit nothing.
    """
    try:
        request = json.loads(text)
        pick, meant = request["pick"], request["question"]
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if not isinstance(standing, dict) or "options" not in standing or standing.get("multi"):
        return None
    if meant != standing.get("question"):
        return None
    questions = standing.get("set") or [standing]
    typed = _typed(standing, answered)
    if typed > len(questions) or (typed == len(questions) and "set" not in standing):
        return None
    if "set" in standing:
        step = typed if typed < len(questions) else "submit"
        if request.get("step") != step:
            return None
        if step != "submit" and questions[step].get("multi"):
            return None
    options = questions[typed]["options"] if typed < len(questions) else ["Submit answers"]
    if type(pick) is not int or not 1 <= pick <= len(options):
        return None
    return str(pick)


def still_answered(answered, snapshot):
    """Keep only the answers whose question still stands on its row.

    Once a question closes it is forgotten, so the same words asked again
    later can be answered from the card again.
    """
    return {session_id: entry for session_id, entry in answered.items()
            if _typed((find_row(snapshot, session_id) or {}).get("question"), entry)}


def response_target(line, own_session_id):
    """Which session's notice one sender's line answers.

    macOS hands every response for the bundle to one running sender,
    whichever notice was clicked, so a sender prints the notice's id with
    the response and the daemon routes on it. A line without one is the
    sender answering for itself.
    """
    try:
        named = json.loads(line).get("id")
    except (ValueError, TypeError, AttributeError):
        named = None
    return named if isinstance(named, str) and named else own_session_id


def keystrokes(text):
    """Text for a session -> the writes that type it, Enter on its own.

    A newline written together with text reaches Claude Code as a pasted
    block, where a newline is a line break; sent by itself, as carriage
    return, it is the Enter key.
    """
    if text.endswith(("\n", "\r")):
        body = text[:-1]
        return ([body] if body else []) + ["\r"]
    return [text] if text else []


class Notices:
    """One standing notice per session: the sender process behind it.

    The sender stays alive until the notice is acted on, so the response
    reaches a daemon that still remembers the session and nothing about this
    daemon -- port, token -- is ever written into a notification. A new notice
    for the same session replaces the old, and a session going back to work
    takes its notice down.
    """

    def __init__(self):
        self._procs = {}
        self._asked = {}

    def standing(self, session_id):
        proc = self._procs.get(session_id)
        return proc if proc is not None and proc.returncode is None else None

    def asked(self, session_id):
        """(kind, question) the standing notice was built from, or None."""
        return self._asked.get(session_id) if self.standing(session_id) else None

    def replace(self, session_id, proc, kind, question):
        self.clear(session_id)
        self._procs[session_id] = proc
        self._asked[session_id] = (kind, question)

    def clear(self, session_id):
        proc = self._procs.pop(session_id, None)
        self._asked.pop(session_id, None)
        if proc is not None and proc.returncode is None:
            proc.terminate()

    async def retire(self, session_id):
        """Take the standing notice down and wait until it is gone.

        A sender's exit removes the notice by id, and its replacement will
        carry the same id: posted before the old sender has finished, the
        new notice is the one that disappears.
        """
        proc = self._procs.pop(session_id, None)
        self._asked.pop(session_id, None)
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            pass

    def forget(self, session_id, proc):
        """Drop `proc` once it ended on its own, unless it was replaced first."""
        if self._procs.get(session_id) is proc:
            del self._procs[session_id]
            self._asked.pop(session_id, None)


def find_row(snapshot, session_id):
    """The panel's row for that session, or None when it does not list it."""
    for group in snapshot.get("groups", []):
        for row in group.get("rows", []):
            if row.get("session_id") == session_id:
                return row
    return None


def row_label(snapshot, session_id):
    """What the panel calls that session, or "" when it does not list it.

    The notice takes its title from here rather than from iTerm2 so that the
    banner and the card always say the same thing -- teammates included, which
    the panel names by their agent name and iTerm2 does not know about.
    """
    row = find_row(snapshot, session_id)
    return row.get("label", "") if row else ""


def statusline_offer(state, settings):
    """Should the foot offer the statusline bridge? Only while settings.json
    lacks it and can take it, and until the person says not now."""
    return state == "missing" and bool(settings["offer_statusline"])


def running_models(snapshot):
    """The model families the Claude sessions on the panel and their running
    subagents use, for switching: {"opus", "fable"}. One whose model is not
    known yet is left out: it reports one within seconds, and counting every
    limit meanwhile moved the account for a limit nothing ran. Only when none
    has reported a model is it None, so every limit decides. A finished
    subagent uses nothing, and neither does an exited session."""
    families, unknown = set(), False
    for group in snapshot.get("groups", []):
        for row in group["rows"]:
            if row.get("state") in (None, "exited") or row.get("provider") not in (None, "claude"):
                continue
            running = [row] + [sub for sub in row.get("subagents") or []
                               if sub.get("ended") is None and sub.get("provider") in (None, "claude")]
            for agent in running:
                if agent.get("model"):
                    families.add(accounts.family(agent["model"]))
                else:
                    unknown = True
    return None if unknown and not families else families


def notifies_itself(row):
    """Whether the row's agent already tells the terminal about its own moments."""
    return row.get("provider") == "omp"


def notify_wanted(kind, session_id, active, app_active):
    """Whether a notice is worth posting, given what you are looking at.

    Pointless only when that very session is in front AND iTerm2 is the
    frontmost application. Another tab of the same window still gets one --
    that is the case a shell hook cannot see, and the one that matters most.

    Unknown focus posts: a banner you did not need costs less than a question
    you never saw.
    """
    if kind == "clear":
        return True
    return not (session_id == active and app_active is True)


def classify(path, auto_name, agent_state=None, agent_job=False):
    """One session's cwd, title, reported state and foreground job -> (kind, label).

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
    # Union, not any one alone: a session running inside tmux loses the marker
    # to tmux but still reports state, an agent that has not reported yet
    # still carries the marker, and a Codex TUI has neither until its first
    # prompt, when the process itself is the only evidence there is.
    if marked or agent_state or agent_job:
        # A cwd says where a terminal is standing, not which session it is:
        # one session cd'd into another session's directory and took its name.
        # The marked title survives any cd, so prefer it when it is there.
        return ("agent", subagent_label(auto_name) or label if marked else label)
    # A plain terminal is a place, and its row says what its prompt says:
    # the path from home. The basename alone repeats the agent card above
    # it when both stand in the same directory.
    return ("shell", tilde_path(resolved) if resolved else label)


#: omp opens every title with its brand, then one mark for the state, then
#: the session's label: `π > label`, `π ! label`, `π <spinner frame> label`.
OMP_TITLE_BRAND = "\u03c0"
OMP_TITLE_MARKS = {">": "idle", "!": "blocked"}


def omp_title_state(auto_name):
    """An omp pane's title -> "idle", "working", "blocked" or "unknown"; None
    when the title is not omp's.

    The title is the only thing omp publishes without an extension loaded into
    it. Working is whatever mark is not one of the other two: the spinner's
    frames are a setting, and a terminal that cannot animate gets a colon.
    "unknown" is omp with its title states switched off (`π: label`, or the
    brand alone).
    """
    if not auto_name:
        return None
    brand, _, rest = auto_name.partition(" ")
    if brand == OMP_TITLE_BRAND + ":" or auto_name == OMP_TITLE_BRAND:
        return "unknown"
    if brand != OMP_TITLE_BRAND or not rest:
        return None
    return OMP_TITLE_MARKS.get(rest.split(" ", 1)[0], "working")


def omp_title_topic(auto_name):
    """An omp title -> the name omp gave the session, or None when it gave none.

    The word after the brand is the state mark, whatever glyph it is; with
    title states off the brand's own colon stands there instead.
    """
    if omp_title_state(auto_name) is None:
        return None
    brand, _, rest = auto_name.partition(" ")
    if brand == OMP_TITLE_BRAND:
        rest = rest.partition(" ")[2]
    return rest.strip() or None


def tilde_path(path):
    """A path as a prompt writes it: home and below as `~/...`, others whole."""
    try:
        return "~/" + str(path.relative_to(Path.home())) if path != Path.home() else "~"
    except ValueError:
        return str(path)


def shell_title(session_name, auto_name, path):
    """The title a person gave a plain terminal's tab, or None.

    zsh's default title is user@host:path and iTerm2's automatic name is the
    shell's own; both repeat what the row already says, so only a title
    that mentions neither the shell nor the place is worth a line.
    """
    if not session_name or session_name == auto_name:
        return None
    place = os.path.basename(path) if path else None
    if place and place in session_name:
        return None
    if session_name.lstrip("-") in SHELLS:
        return None
    return session_name


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


def _blocks(rows):
    """Rows -> each top-level card with everything nested in it.

    A card's block is its own row plus the teammates indented under it and
    the worktree cards docked to it; moving the rows flat would put an
    indent under whatever row happened to land above it.
    """
    blocks = []
    for row in rows:
        if blocks and (row["depth"] or row.get("worktree_of")):
            blocks[-1].append(row)
        else:
            blocks.append([row])
    return blocks


def by_name(rows):
    """Top-level cards in name order, each with everything nested in it."""
    blocks = sorted(_blocks(rows), key=lambda block: block[0]["label"].casefold())
    return [row for block in blocks for row in block]


#: The order agents' groups take. Fixed, so a group stays put when a session
#: of another agent opens above it; an agent not named here comes after.
PROVIDER_ORDER = ("claude", "openai", "omp")


def by_provider(rows):
    """Top-level cards gathered by agent, each group in the order it had."""
    def place(block):
        provider = block[0].get("provider") or "claude"
        return PROVIDER_ORDER.index(provider) if provider in PROVIDER_ORDER else len(PROVIDER_ORDER)
    return [row for block in sorted(_blocks(rows), key=place) for row in block]


def snapshot(sessions, sort_by_name=False, group_by_provider=False):
    """Raw session dicts -> the payload the page renders.

    Agents first, then everything else. Order within a group is the order
    handed in, which is the order iTerm2 enumerates windows, tabs and panes,
    so a card sits where its terminal does and nothing a session does moves
    it; `sort_by_name` puts the top-level cards in name order instead. Each
    input dict needs session_id, window_id, tab_id, path, auto_name and
    job_name.
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
    teammates = []          # (lead's claude session id, name) per row, in row order
    leads = {}              # claude session id -> its row
    by_path = {}            # an agent's directory -> its row, first one wins
    worktrees = []          # (row, main worktree path, own path) for linked worktrees

    rows = {"agent": [], "shell": []}
    for session in sessions:
        kind, label = classify(session.get("path"), session.get("auto_name"),
                               session.get("agent_state"), session.get("agent_job"))
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

        # A teammate's process names its lead's session outright; that is
        # settled after every row exists, since the lead may be enumerated
        # later, and it holds wherever the teammate runs.
        if kind == "agent" and session.get("parent_session"):
            teammates.append((session["parent_session"],
                              session.get("agent_name") or agent_name(session.get("session_name"))
                              or subagent_label(session.get("auto_name")) or label))
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
        if kind == "shell":
            title = shell_title(session.get("session_name"), session.get("auto_name"), session.get("path"))
            if title:
                row["title"] = title

        # Optional signals. Absent means absent -- a key with a placeholder
        # would assert something false, and a session whose state cannot be
        # read is not "idle".
        if session.get("colour"):
            row["colour"] = session["colour"]
        if session.get("task"):
            row["task"] = session["task"]
        if kind == "agent":
            # Claude rows are the page's unmarked default; others name themselves.
            if session.get("provider") not in (None, "claude"):
                row["provider"] = session["provider"]
            if session.get("agent_state"):
                row["state"] = session["agent_state"]
            if session.get("resumable"):
                row["resumable"] = True
            # The same test context_target makes, so the page offers the
            # breakdown only where the daemon would run it.
            conversation = session.get("conversation")
            if (session.get("provider") == "claude" and isinstance(conversation, str)
                    and CONVERSATION_ID.fullmatch(conversation)):
                row["context_readable"] = True
            if session.get("context") is not None:
                row["context"] = session["context"]
            if session.get("model"):
                row["model"] = session["model"]
            if session.get("effort"):
                row["effort"] = session["effort"]
            if session.get("topic"):
                row["topic"] = session["topic"]
            # At rest the agent's last stated intent still stands, and on a
            # card that would read as work going on.
            if session.get("doing") and session.get("agent_state") in ("working", "blocked"):
                row["doing"] = session["doing"]
            # Not nested under the branch: a session whose HEAD cannot be read
            # still has however many subagents it has.
            if session.get("agents"):
                row["agents"] = session["agents"]
            if session.get("subagents"):
                row["subagents"] = session["subagents"]
            if session.get("tasks"):
                row["tasks"] = session["tasks"]
            if session.get("blocked_since") is not None:
                row["blocked_since"] = session["blocked_since"]
            if session.get("question"):
                row["question"] = session["question"]
            if session.get("working_since") is not None:
                row["working_since"] = session["working_since"]
            if session.get("shells"):
                row["shells"] = session["shells"]
            if session.get("started_at") is not None:
                row["started_at"] = session["started_at"]
            if session.get("details"):
                row["details"] = session["details"]
            if session.get("heavy"):
                row["heavy"] = session["heavy"]
            if session.get("usage"):
                row["usage"] = session["usage"]
        if session.get("branch"):
            row["branch"] = session["branch"]
        if kind == "agent" and session.get("claude_session"):
            leads[session["claude_session"]] = row
        if kind == "agent" and session.get("parent_session"):
            row["_lead"] = teammates[-1]
        if kind == "agent" and not child and session.get("path"):
            by_path.setdefault(session["path"], row)
            # Git names the main worktree; failing that, cs's own naming
            # does: `<base>@<feature>` beside a session directory `<base>`
            # is that project, whatever the shell's path or the checkout
            # says. Beside it only: a `<base>` in another folder is another
            # project.
            main_path = session.get("worktree_of") or sibling_base(session["path"])
            if main_path:
                worktrees.append((row, main_path, session["path"]))
        if kind == "agent" and home:
            families.setdefault(home, []).append(row)
        else:
            rows[kind].append(row)

    # Emit each family whole, in the order its parent first appeared, so the
    # list still never re-sorts on anything a session does.
    for family in families.values():
        rows["agent"].extend(family)

    # Then teammates that name a listed lead move under it, after any child
    # already there, and take the name Claude Code calls them by. One whose
    # lead is not listed stays where it is: an indent under nothing is a
    # claim pointing at empty space.
    for row in [r for r in rows["agent"] if "_lead" in r]:
        lead_session, name = row.pop("_lead")
        row["label"] = name
        lead = leads.get(lead_session)
        if lead is None or lead is row:
            continue
        rows["agent"].remove(row)
        row["depth"] = 1
        at = rows["agent"].index(lead) + 1
        while at < len(rows["agent"]) and rows["agent"][at]["depth"]:
            at += 1
        rows["agent"].insert(at, row)

    # A session in a linked worktree of another session's repo is its own
    # card, placed right after that session and everything nested in it, and
    # named by its feature: cs names the directory `<repo>@<feature>`, and
    # the branch already has its own chip. A directory without an `@` is
    # named by its branch. One whose main session is not open stays where it
    # is under its own name.
    for row, main_path, path in worktrees:
        main = by_path.get(main_path)
        if main is None or main is row or row not in rows["agent"]:
            continue
        rows["agent"].remove(row)
        row["worktree_of"] = main["session_id"]
        feature = Path(path).name.partition("@")[2]
        if feature or row.get("branch"):
            row["label"] = feature or row["branch"]
        at = rows["agent"].index(main) + 1
        while at < len(rows["agent"]) and (rows["agent"][at]["depth"]
                                           or rows["agent"][at].get("worktree_of") == main["session_id"]):
            at += 1
        rows["agent"].insert(at, row)

    if sort_by_name:
        for kind in rows:
            rows[kind] = by_name(rows[kind])
    if group_by_provider:
        rows["agent"] = by_provider(rows["agent"])
    mark_busy_teammates(rows["agent"])

    groups = [
        {"name": "AGENTS", "rows": rows["agent"]},
        {"name": "SESSIONS", "rows": rows["shell"]},
    ]
    # A header over nothing reads as breakage, and costs a row of a narrow panel.
    return {"groups": [group for group in groups if group["rows"]]}


def mark_busy_teammates(rows):
    """Give each lead the number of its teammates that are working. -> None.

    A teammate is its own session in its own pane with its own state, so a
    lead reads idle while work goes on under it. The count is the honest
    middle: the lead still says what its own pane is doing.
    """
    lead = None
    for row in rows:
        if not row.get("depth"):
            lead = row
        elif lead is not None and row.get("state") == "working":
            lead["busy_kids"] = lead.get("busy_kids", 0) + 1


#: States the hooks can actually establish. "unknown" and "exited" are
#: reader-derived, never emitted: "exited" is a claim whose writer has died,
#: "unknown" one nobody can vouch for either way.
STATES = ("working", "blocked", "idle", "unknown")

#: iTerm2 renders context usage into user.claudeStatus as "886k (88%)".
CONTEXT_PERCENT = re.compile(r"\((\d{1,3})%\)")


def parse_session(raw):
    """The claudeState user variable -> the session id the hook published, or None."""
    if not raw:
        return None
    try:
        session = json.loads(raw).get("session")
    except (ValueError, TypeError, AttributeError):
        return None
    return session if isinstance(session, str) and session else None


def parse_state(raw, command_running=False):
    """The claudeState user variable -> one of STATES, or None if unset.

    Verifies the writer is still alive. SetUserVar is last-writer-wins with no
    concept of death, so a session killed mid-turn leaves "working" sitting in
    the variable indefinitely. A claim whose writer is gone is "exited"; one
    that cannot be checked, or has gone quiet, is "unknown".

    `command_running` says a command is running in the writer's own process
    tree. No hook fires inside a tool call, so that is what keeps a quiet
    working claim believable through a long one.
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        state = payload["state"]
        pid = int(payload["pid"])
    except (ValueError, TypeError, KeyError, OverflowError):
        return "unknown"

    if state not in STATES:
        return "unknown"
    # Guard before kill(): pid 0 addresses the whole process group and negative
    # pids address other groups, so neither is a liveness question at all.
    if pid <= 0:
        return "unknown"
    try:
        os.kill(pid, 0)          # signal 0 tests existence, sends nothing
    except ProcessLookupError:
        return "exited"
    except (ValueError, OverflowError):
        return "unknown"
    except PermissionError:
        pass                     # alive, just not ours to signal

    if state == "working":
        try:
            age = time.time() - float(payload.get("ts") or 0)
        except (TypeError, ValueError):
            return "unknown"
        if age > WORKING_GOES_STALE_AFTER and not command_running:
            # The writer is alive but has gone quiet. Liveness answers whether
            # it exists, not whether it is still doing what it claimed.
            return "unknown"
    return state


#: A conversation id as Claude Code and Codex write it. The id comes from a
#: user variable any process in the pane can set, and it is typed into a
#: shell, so nothing but this exact shape is ever let through.
CONVERSATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

def resume_command(path, provider, conversation):
    """What to type at a pane's prompt to reopen the conversation that died
    there, or None when there is no safe way to.

    A cs session goes back through cs, which resumes its own recorded
    conversation and keeps its memory and task list; bare claude would lose
    both. cs then asks before it resumes, and that question is the confirmation.
    """
    if not path or not isinstance(conversation, str) or not CONVERSATION_ID.fullmatch(conversation):
        return None
    if provider == "claude":
        return "cs ." if os.path.isdir(os.path.join(path, ".cs")) else f"claude --resume {conversation}"
    if provider == "openai":
        return f"codex resume {conversation}"
    return None


def context_target(rows, session_id):
    """-> (directory, conversation id) to read the session's /context from.

    From the last rebuild's rows, never the page's copy. Raises
    context_usage.Refused when the session is not a Claude conversation the
    fork can resume: the id comes from a user variable any process in the pane
    can set, so only its exact shape reaches the argument list.
    """
    row = next((row for row in rows if row["session_id"] == session_id), None)
    if row is None:
        raise context_usage.Refused("no such session")
    if row.get("provider") != "claude":
        raise context_usage.Refused("only a Claude conversation has a /context")
    conversation = row.get("conversation")
    if not isinstance(conversation, str) or not CONVERSATION_ID.fullmatch(conversation):
        raise context_usage.Refused("no conversation id for this session yet")
    if not row.get("path") or not os.path.isdir(row["path"]):
        raise context_usage.Refused("the session's directory is gone")
    return row["path"], conversation


#: Where Claude Code keeps a transcript per conversation, one folder per cwd.
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def conversation_saved(provider, conversation, transcript_path, projects=CLAUDE_PROJECTS_DIR):
    """Has the conversation written a transcript to resume from?

    An agent killed before its first turn is saved leaves an id that resumes
    to "No conversation found". Claude's hook names no transcript, so any
    project folder may hold it; Codex's names its rollout.
    """
    if not isinstance(conversation, str) or not CONVERSATION_ID.fullmatch(conversation):
        return False
    if provider == "openai":
        return bool(transcript_path) and os.path.isfile(transcript_path)
    return any(Path(projects).glob(f"*/{conversation}.jsonl"))


def still_resuming(resuming, rows, now):
    """The resumes still under way: {session id: (when sent, job it was typed at)}.

    One ends when its agent reports, or its pane goes. Otherwise it holds for
    RESUME_HOLD, and past that for as long as something other than the shell
    it was typed at runs in the pane: cs waits on its question until it is
    answered, and a second resume would be typed into it.
    """
    exited = {row["session_id"]: row.get("job_name") for row in rows if row["agent_state"] == "exited"}
    return {sid: (sent, shell) for sid, (sent, shell) in resuming.items()
            if sid in exited and (now - sent < RESUME_HOLD or exited[sid] != shell)}


def resumable(row, rows, resuming):
    """Can this pane's exited agent be resumed where it died, right now?

    Only at a shell prompt, since anything else running there would get the
    keystrokes; only while its directory stands and its transcript exists
    (`row["saved"]`, read once the agent has exited); and never twice: not while
    the conversation is live in another pane, nor while a resume sent to this
    pane (its session id in `resuming`) is still starting.
    """
    if row["agent_state"] != "exited" or row["session_id"] in resuming:
        return False
    if (row.get("job_name") or "").lstrip("-") not in SHELLS:
        return False
    if not row.get("path") or not os.path.isdir(row["path"]):
        return False
    if resume_command(row["path"], row.get("provider"), row.get("conversation")) is None:
        return False
    if not row.get("saved"):
        return False
    return not any(other["session_id"] != row["session_id"]
                   and other.get("conversation") == row["conversation"]
                   and other["agent_state"] not in ("exited", None)
                   for other in rows)


#: claude-status writes "<glyph> <model>  <bar>  <tokens> (<pct>%)", with TWO
#: spaces between fields. The model itself may contain one -- it is either an
#: id like claude-opus-5 or a display name like "Fable 5.1", depending on which
#: branch of claude-status resolved it.
MODEL = re.compile(r"^\S+\s+(.+?)\s\s")


#: Claude Code sources this into every shell it opens. Matching on it rather
#: than on a shell's name survives a different $SHELL and ignores the user's
#: own subprocesses.
SHELL_MARKER = "/.claude/shell-snapshots/"


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


#: How ps prints `lstart`, a process's start as a calendar stamp in local
#: time, under the C locale the listing is run in.
PROCESS_START_FORMAT = "%a %b %d %H:%M:%S %Y"


def process_start(lstart):
    """ps `lstart` -> POSIX seconds, or None.

    The moment a process began rather than how long ago: an elapsed time
    grows on every rebuild, and a snapshot that differs each time is pushed
    and redrawn each time for nothing.
    """
    if not lstart or not lstart.strip():
        return None
    try:
        return int(time.mktime(time.strptime(lstart.strip(), PROCESS_START_FORMAT)))
    except (ValueError, OverflowError):
        return None


#: Claude Code passes a teammate its badge colour and its lead's session id
#: on the command line, and records neither anywhere else the sidebar can read.
_AGENT_COLOUR = re.compile(r"\s--agent-color[ =]([a-z]+)\b")
_AGENT_PARENT = re.compile(r"\s--parent-session-id[ =]([0-9a-fA-F-]+)\b")


#: The panel's own task report, run by the model at the prompt hook's word.
#: Counting it would make every report grow and shrink the card it describes.
OWN_REPORT = "/agents-sidebar/hooks-handlers/task.py"


def parse_processes(raw, home=None):
    """One process listing -> (shell commands by parent pid, start time by pid,
    teammate colour by pid, lead session id by teammate pid).

    All four come off the same ps: running it once per fact per rebuild would
    be silly. A home directory in a label reads as ~, so the part that
    differs is not pushed off the row by the part that never does.
    """
    home = os.path.expanduser("~") if home is None else home
    shells, started, colours, parents = {}, {}, {}, {}
    for line in (raw or "").splitlines():
        parts = line.split(None, PROCESS_FIELDS)
        if len(parts) <= PROCESS_FIELDS:
            continue
        pid, parent, args = parts[0], parts[1], parts[PROCESS_FIELDS]
        try:
            pid, parent = int(pid), int(parent)
        except ValueError:
            continue
        began = process_start(" ".join(parts[LSTART]))
        if began is not None:
            started[pid] = began
        if SHELL_MARKER in args and OWN_REPORT not in args:
            command = shell_command(args) or UNKNOWN
            shells.setdefault(parent, []).append(
                {"label": shell_label(command).replace(home + "/", "~/"), "command": command})
        colour = _AGENT_COLOUR.search(args)
        if colour:
            colours[pid] = colour.group(1)
        parent_session = _AGENT_PARENT.search(args)
        if parent_session:
            parents[pid] = parent_session.group(1)
    return shells, started, colours, parents


#: The one process listing a rebuild takes, and the fields before args. Every
#: fact read off the process table -- shells, start times, teammates,
#: foreground jobs -- parses this shape, so it is run once: an exec costs tens
#: of milliseconds on the event loop, and the endpoint agents inspect each
#: one. -ww: the command sits at the end of a long line, past any width cap.
#: lstart is five words, so %cpu and rss are the eleventh and twelfth fields
#: and args the thirteenth.
PROCESS_LISTING = ["/bin/ps", "-ww", "-eo", "pid=,ppid=,pgid=,tpgid=,tty=,lstart=,%cpu=,rss=,args="]
PROCESS_FIELDS = 12
LSTART = slice(5, 10)


def parse_resources(raw):
    """The process listing -> {pid: (parent pid, %cpu, resident KB, tty or None)}."""
    table = {}
    for line in (raw or "").splitlines():
        parts = line.split(None, PROCESS_FIELDS)
        if len(parts) <= PROCESS_FIELDS:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), float(parts[10]), int(parts[11]),
                                    None if parts[4] in ("??", "-") else parts[4])
        except ValueError:
            continue
    return table


def parse_commands(raw):
    """The process listing -> {pid: the program it runs, without its path}.

    None for a process whose first argument is a flag: its args name no
    program. jdtls, for one, execs java with its JVM flags and no argv[0];
    a login shell's is `-zsh`. tree_hogs asks the kernel for the few it shows.
    """
    names = {}
    for line in (raw or "").splitlines():
        parts = line.split(None, PROCESS_FIELDS)
        if len(parts) <= PROCESS_FIELDS:
            continue
        try:
            first = parts[PROCESS_FIELDS].split()[0]
            names[int(parts[0])] = None if first.startswith("-") else os.path.basename(first)
        except ValueError:
            continue
    return names


def read_program_names(pids):
    """-> {pid: its executable's name} from the kernel, for processes whose
    args name no program. Missing for a process already gone.

    A separate ps, since ucomm can hold spaces and only the last column may.
    """
    if not pids:
        return {}
    try:
        out = subprocess.run(["/bin/ps", "-o", "pid=,ucomm=", "-p", ",".join(map(str, pids))],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    names = {}
    for line in out.splitlines():
        pid, _, name = line.strip().partition(" ")
        if pid.isdigit():
            names[int(pid)] = name.strip()
    return names


def heavy_on(cpu, rss_kb, settings):
    """-> which of "cpu" and "memory" are at or over their thresholds.

    Only the verdict goes to the page: the figures move on every reading, and
    a snapshot that changes every rebuild is pushed every rebuild.
    """
    heavy = []
    if cpu >= settings["cpu_threshold"]:
        heavy.append("cpu")
    if rss_kb >= settings["memory_threshold"] * 1024 * 1024:
        heavy.append("memory")
    return heavy


def usage_shown(heavy, cpu, rss_kb, hogs):
    """-> the figure and the hungriest program for each kind in `heavy`.

    Rounded to ten percent and a tenth of a gigabyte, and only for a kind that
    reads heavy, so a light session's snapshot holds still between readings.
    """
    usage = {}
    if "cpu" in heavy:
        usage["cpu"] = {"percent": int(round(cpu, -1)), "top": hogs.get("cpu")}
    if "memory" in heavy:
        usage["memory"] = {"gb": round(rss_kb / 1024 / 1024, 1), "top": hogs.get("memory")}
    return usage


#: How long a chip stays after its last heavy reading.
HEAVY_HOLD_SECONDS = 15


def hold_heavy(seen, heavy, pid, now):
    """-> the kinds `pid` has read heavy within the hold, in heavy_on's order.

    Under load a process pegging a core reads anywhere from a quarter to most
    of one from one listing to the next, so a session near a threshold would
    light and clear every refresh. `seen` maps (pid, kind) to its last heavy
    reading and is updated in place.
    """
    for kind in heavy:
        seen[(pid, kind)] = now
    return [kind for kind in ("cpu", "memory")
            if now - seen.get((pid, kind), -HEAVY_HOLD_SECONDS) < HEAVY_HOLD_SECONDS]


def forget_heavy(seen, live):
    """Drop the holds of sessions whose process is no longer listed."""
    for key in [key for key in seen if key[0] not in live]:
        del seen[key]


def tree_usage(table, root, stop_at):
    """(%cpu, resident KB) summed over `root` and every process below it.

    A descendant in `stop_at` is another session's card and is left to it,
    so one busy teammate does not light its lead as well.
    """
    cpu, rss = 0.0, 0
    for pid in tree_pids(table, root, stop_at):
        cpu += table[pid][1]
        rss += table[pid][2]
    return cpu, rss


def tree_pids(table, root, stop_at):
    """`root` and every process below it, down to but not into `stop_at`."""
    children = {}
    for pid, (parent, *_) in table.items():
        children.setdefault(parent, []).append(pid)
    pids, pending = [], [root] if root in table else []
    while pending:
        pid = pending.pop()
        pids.append(pid)
        pending.extend(child for child in children.get(pid, []) if child not in stop_at)
    return pids


def tree_hogs(table, names, root, stop_at):
    """-> {"cpu": program, "memory": program}: what in `root`'s tree uses the
    most of each. Empty when the tree is gone.

    A hog whose args name no program is named by the kernel, which costs a
    ps; the rebuild asks only for a heavy tree's hogs, so that is rare.
    """
    pids = tree_pids(table, root, stop_at)
    if not pids:
        return {}
    hogs = {"cpu": max(pids, key=lambda pid: table[pid][1]),
            "memory": max(pids, key=lambda pid: table[pid][2])}
    unnamed = [pid for pid in set(hogs.values()) if names.get(pid) is None]
    found = read_program_names(unnamed)
    return {kind: names.get(pid) or found.get(pid) for kind, pid in hogs.items()}


def read_process_listing():
    """The process table as text, or "" when ps cannot be run."""
    try:
        # The C locale pins lstart's shape whatever iTerm2 was started under.
        return subprocess.run(PROCESS_LISTING, capture_output=True, text=True,
                              timeout=5, env={**os.environ, "LC_ALL": "C"}).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def read_system():
    """Everything a rebuild learns from outside iTerm2, off one ps and one tmux."""
    listing = read_process_listing()
    return (parse_processes(listing), read_tmux_panes(listing), parse_resources(listing),
            parse_commands(listing))


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
        words, name = words[1:], os.path.basename(words[1])
    # A Codex subcommand is a job, not a person's session: `codex exec` and
    # `codex app-server` say so in the name, so only the bare TUI reads as
    # Codex itself.
    if name == "codex" and len(words) > 1 and not words[1].startswith("-"):
        return f"codex {words[1]}"
    return name


def parse_foreground(out):
    """The process listing -> {tty: what its foreground runs}.

    A terminal's foreground job is its foreground process group; the group's
    leader is the command that was typed. Its children (a vendored binary, a
    helper) and background groups (MCP servers, prompt daemons) are not.
    """
    running = {}
    for line in out.splitlines():
        parts = line.split(None, PROCESS_FIELDS)
        if len(parts) <= PROCESS_FIELDS or parts[4] in ("??", "-"):
            continue
        pid, _, pgid, tpgid, tty, args = *parts[:5], parts[PROCESS_FIELDS]
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


def read_tmux_panes(listing):
    """{tmux pane number: {job, path, tty}}, or {} without tmux.

    iTerm2 cannot see inside a tmux pane: it reports no jobName, and a `path`
    that can belong to another pane of the same tmux window, which gave
    sessions each other's branches and nested teammates under the wrong
    agent. tmux knows the pane, and the process listing the rebuild already
    holds knows what runs on its tty. One tmux listing per rebuild, however
    many panes there are.
    """
    tmux = next((path for path in TMUX_PATHS if os.path.exists(path)), None)
    if tmux is None:
        return {}
    try:
        panes = subprocess.run([tmux, "list-panes", "-a", "-F",
                                "#{pane_id} #{pane_tty} #{pane_current_path}"],
                               capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    if not panes:
        return {}
    running = parse_foreground(listing)
    return {number: {"job": running.get(pane["tty"]), "path": pane["path"], "tty": pane["tty"]}
            for number, pane in parse_tmux_panes(panes).items()}


def _reported_at(raw):
    try:
        ts = json.loads(raw)["ts"]
    except (ValueError, TypeError, KeyError):
        return None
    return ts if isinstance(ts, (int, float)) else None


def stale_state_entries(entries, now, live):
    """Names among (name, mtime) pairs that a session long gone left behind.

    A session's files share its id as their stem: the document, its lock, the
    filed detail, and a temp file a killed hook never renamed. They go
    together or not at all, and not while the session has a card or wrote
    anything lately: taking the lock never touches it, so a live session's
    lock is old, and one that sat idle overnight has an old document too.
    """
    stem = lambda name: name.split(".", 1)[0]
    fresh = {stem(name) for name, mtime in entries if now - mtime <= STATUS_SWEEP_AFTER}
    return [name for name, _ in entries if stem(name) not in fresh and stem(name) not in live]


def sweep_state_dir(now, live, directory):
    """Remove what dead sessions left in the hook's state directory.

    The directory is named by the caller: a test that sweeps with a time of
    its own must never be one forgotten patch away from the real one.
    """
    try:
        with os.scandir(directory) as it:
            found = [(e.name, e.stat().st_mtime) for e in it if e.is_file()]
    except OSError:
        return
    for name in stale_state_entries(found, now, live):
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            pass


#: Where the hook files a published state too large for the session variable.
HOOK_STATE_DIR = os.path.expanduser("~/.claude/agents-sidebar-subagents")
#: A session id as a file name: any program in a pane can set its variable,
#: so the id is checked before it names a path.
_SESSION_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def with_detail(raw, directory=None):
    """The session variable -> the whole published state, as JSON text.

    A variable that says `detail: true` left its subagents, its tasks and its
    question in a file under the session id. A file as new as the variable is
    the whole state and replaces it. An older one lost a race with a later
    event: its subagents and tasks still stand, its question may have been
    answered since and is dropped. No readable file leaves the variable as it
    came.
    """
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(envelope, dict) or envelope.get("detail") is not True:
        return raw
    session = envelope.get("session")
    if not isinstance(session, str) or not _SESSION_FILE.match(session):
        return raw
    try:
        with open(os.path.join(directory or HOOK_STATE_DIR, session + ".published"),
                  encoding="utf-8") as fh:
            whole = json.load(fh)
    except (OSError, ValueError):
        return raw
    if not isinstance(whole, dict):
        return raw
    stamp = lambda doc: doc.get("ts") if isinstance(doc.get("ts"), (int, float)) else 0
    if stamp(whole) >= stamp(envelope):
        return json.dumps(whole)
    return json.dumps(dict(envelope, subagents=whole.get("subagents"), tasks=whole.get("tasks")))


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
    def text(value):
        return value if isinstance(value, str) else None
    return {"model": text(payload.get("model")), "transcript_path": text(payload.get("transcript_path"))}


def job_pid(value):
    """iTerm2's jobPid for a pane -> the pid of its foreground job, or None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


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
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return round(value)
    return None


def parse_subagents(raw):
    """The claudeState payload -> the subagents as a tree: [{type, since, depth, ...}].

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
    items = [item for item in listed if isinstance(item, dict)]
    return [{"type": text(item.get("type")), "since": _epoch(item.get("since")),
             "ended": _epoch(item.get("ended")),
             "name": text(item.get("name")), "model": short_model(item.get("model")),
             "depth": depth}
            for item, depth in _subagent_tree(items, text)]


def _subagent_tree(items, text):
    """Flat subagents, oldest first -> [(item, depth)] with each one's own
    subagents directly below it.

    A parent that is not in the list makes its child a top-level entry, and
    entries caught in a parent loop are kept at the top after the rest.
    """
    ids = {text(item.get("id")) for item in items} - {None}
    children = {}
    for item in items:
        parent = text(item.get("parent"))
        children.setdefault(parent if parent in ids else None, []).append(item)
    ordered, placed = [], set()

    def place(item, depth):
        placed.add(id(item))
        ordered.append((item, depth))
        own_id = text(item.get("id"))
        for child in children.get(own_id, []) if own_id else []:
            if id(child) not in placed:
                place(child, depth + 1)

    for item in children.get(None, []):
        place(item, 0)
    ordered += [(item, 0) for item in items if id(item) not in placed]
    return ordered


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


def parse_question(raw):
    """The claudeState payload -> what its open gate is asking, or None."""
    try:
        asked = json.loads(raw).get("question")
    except (ValueError, TypeError, AttributeError):
        return None
    return asked if isinstance(asked, dict) else None


def parse_tasks(raw):
    """The claudeState payload -> its open tasks: [{id, status, subject, doing}]."""
    try:
        listed = json.loads(raw).get("tasks")
    except (ValueError, TypeError, AttributeError):
        return []
    return listed if isinstance(listed, list) else []


def parse_working_since(raw):
    """The claudeState payload -> when the turn under way began, or None."""
    try:
        return _epoch(json.loads(raw).get("working_since"))
    except (ValueError, TypeError, AttributeError):
        return None


#: Where the codex plugin keeps its jobs: one directory per workspace, each
#: with a state.json listing that workspace's last fifty jobs.
CODEX_JOBS_DIR = os.path.expanduser("~/.claude/plugins/data/codex-openai-codex/state")


def _iso_epoch(value):
    """An ISO 8601 time such as 2026-09-17T15:00:01.000Z -> epoch s, or None.

    Python 3.10, which iTerm2 runs this under, does not read a trailing Z."""
    if not isinstance(value, str):
        return None
    try:
        return round(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def parse_codex_state(raw):
    """A codex plugin state.json -> its jobs: [{id, session, kind, status,
    phase, pid, since, ended}].

    Prompts, results and rendered reviews stay behind: they are the bulk of
    the file and nothing on a card needs them. A file of another version is
    skipped rather than guessed at.
    """
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("jobs"), list):
        return []
    text = lambda value: value if isinstance(value, str) and value else None
    jobs = []
    for item in doc["jobs"]:
        if not isinstance(item, dict) or not (text(item.get("id")) and text(item.get("sessionId"))
                                              and text(item.get("status"))):
            continue
        pid = item.get("pid")
        jobs.append({"id": item["id"], "session": item["sessionId"], "kind": text(item.get("kindLabel")),
                     "status": item["status"], "phase": text(item.get("phase")),
                     "pid": pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
                     "since": _iso_epoch(item.get("startedAt")) or _iso_epoch(item.get("createdAt")),
                     "ended": _iso_epoch(item.get("completedAt"))})
    return jobs


def codex_job_rows(jobs, session, turn_started, live_pids):
    """The session's Codex jobs as subagent entries, oldest first.

    A job is running while its status says so and its process, when it has
    one yet, is alive: a companion that died mid-job never writes its end.
    A job that ended is kept only when it ended after the latest prompt, as
    a finished subagent is.
    """
    listed = []
    for job in jobs:
        if job["session"] != session:
            continue
        active = job["status"] in ("queued", "running")
        running = active and (job["pid"] is None or job["pid"] in live_pids)
        ended_this_turn = (not active and turn_started is not None
                           and job["ended"] is not None and job["ended"] >= turn_started)
        if not (running or ended_this_turn):
            continue
        listed.append({"id": job["id"], "parent": None, "type": job["kind"], "since": job["since"],
                       "ended": None if running else job["ended"], "name": None, "model": None,
                       "provider": "codex", "phase": job["phase"]})
    return sorted(listed, key=lambda row: row["since"] or 0)


def merge_codex_rows(subagents, codex_rows):
    """Subagents as a tree plus the Codex rows, each placed at the top level
    before the first top-level subagent that started after it."""
    merged = list(subagents)
    for row in codex_rows:
        at = next((i for i, sub in enumerate(merged)
                   if sub["depth"] == 0 and (sub["since"] or 0) > (row["since"] or 0)), len(merged))
        merged.insert(at, {**row, "depth": 0})
    return merged


def parse_turn_started(raw):
    """The claudeState payload -> when its latest prompt arrived, or None."""
    try:
        return _epoch(json.loads(raw).get("turn_started"))
    except (ValueError, TypeError, AttributeError):
        return None


def read_codex_jobs():
    """Every job in every workspace the codex plugin has kept. [] without it."""
    try:
        with os.scandir(CODEX_JOBS_DIR) as it:
            stores = [os.path.join(e.path, "state.json") for e in it if e.is_dir()]
    except OSError:
        return []
    jobs = []
    for path in stores:
        try:
            with open(path, encoding="utf-8") as fh:
                jobs += parse_codex_state(fh.read())
        except OSError:
            continue
    return jobs


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
#: Claude Code's user settings, whose statusLine.command must be the bridge
#: for any of the payload above to reach the panel.
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
#: The bridge in this checkout, which is what install.sh points settings at.
BRIDGE = str(Path(__file__).resolve().parent / "plugin" / "statusline-bridge.sh")

#: Where task.py keeps each session's own note about its work, by session id.
TASKS_DIR = os.path.expanduser("~/.claude/agents-sidebar-tasks")


def read_task(session_id):
    """What the session last said it was doing, and when, or None.

    The note is the session's own claim, stamped by the reporting script;
    the page works the report's age out from the stamp on its own clock, so
    it can grey one nobody refreshed without the snapshot changing every
    tick to say so.
    """
    if not isinstance(session_id, str) or not _SESSION_FILE.match(session_id):
        return None
    try:
        with open(os.path.join(TASKS_DIR, f"{session_id}.json"), encoding="utf-8") as fh:
            note = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(note, dict) or "task" not in note:
        return None
    ts = note.get("ts")
    return {"title": note.get("title"), "activity": note.get("activity"),
            "percent": note.get("percent") if isinstance(note.get("percent"), int) else None,
            "done": bool(note.get("done")),
            "reported_at": ts if isinstance(ts, (int, float)) else None}


#: How old a statusline payload may be and still describe its pid. Claude Code
#: renders every tick, so a live session rewrites its file every
#: few seconds; anything this far behind belongs to a process that has stopped
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
             "transcript": None, "session": None}
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
    session = payload.get("session_id")
    return {"context": int(used) if isinstance(used, (int, float)) else None,
            "model": name,
            "effort": field("effort", "level"),
            "details": details(payload, field),
            "transcript": transcript if isinstance(transcript, str) else None,
            "session": session if isinstance(session, str) else None}


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


#: A status file this old was left by a session that has exited; a live one
#: is rewritten every few seconds.
STATUS_SWEEP_AFTER = 86400
#: Every file the bridge has ever written beside a session's payload: the
#: payload, the rendered line, the render lock, and the temp files of this
#: and earlier designs. `original-statusline` is the user's own and never
#: matches.
_STATUS_ENTRY = re.compile(r"^\d+\.(json|line|rendering)(\.(\d+|tmp))?$")


def stale_status_entries(entries, now):
    """Names among (name, mtime) pairs that belong to sessions long gone."""
    return [name for name, mtime in entries
            if _STATUS_ENTRY.match(name) and now - mtime > STATUS_SWEEP_AFTER]


def sweep_status_dir(now):
    """Remove what dead sessions left in the status directory.

    Nothing reads the directory as a whole, so the leftovers cost nothing
    but clutter; still, 470 of them for nine live sessions is a mess.
    """
    try:
        with os.scandir(STATUS_DIR) as it:
            found = [(e.name, e.stat().st_mtime, e.is_dir()) for e in it]
    except OSError:
        found = []
    stale = set(stale_status_entries([(n, m) for n, m, _ in found], now))
    for name, _, is_dir in found:
        if name not in stale:
            continue
        try:
            (os.rmdir if is_dir else os.remove)(os.path.join(STATUS_DIR, name))
        except OSError:
            pass
    # A task note outlives its session the same way; a day-old one is nobody's.
    # Its lock goes with it, but only once no fresh note stands beside it:
    # taking a lock never touches the file, so a live session's lock is old.
    try:
        with os.scandir(TASKS_DIR) as it:
            found = [(e.name, e.stat().st_mtime) for e in it]
    except OSError:
        return
    fresh = {name[:-len(".json")] for name, mtime in found
             if name.endswith(".json") and now - mtime <= STATUS_SWEEP_AFTER}
    for name, mtime in found:
        stem, ext = os.path.splitext(name)
        if ext in (".json", ".lock") and now - mtime > STATUS_SWEEP_AFTER and stem not in fresh:
            try:
                os.remove(os.path.join(TASKS_DIR, name))
            except OSError:
                pass


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


def sibling_base(path):
    """`<dir>/<base>@<feature>` -> `<dir>/<base>`, or None for any other name."""
    if not path:
        return None
    here = Path(path)
    base = here.name.partition("@")[0]
    return str(here.with_name(base)) if "@" in here.name and base else None


def git_main_worktree(path):
    """The main worktree a linked worktree belongs to, or None.

    A linked worktree's `.git` is a file naming `<main>/.git/worktrees/<name>`.
    The main worktree, a submodule and a plain directory all answer None:
    only a session in a linked worktree has a session to be tied to.
    """
    if not path:
        return None
    here = Path(path)
    for folder in [here, *here.parents]:
        marker = folder / ".git"
        if not marker.exists():
            continue
        if not marker.is_file():
            return None
        try:
            pointer = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not pointer.startswith("gitdir:"):
            return None
        gitdir = Path(pointer.split(":", 1)[1].strip())
        # <main>/.git/worktrees/<name>
        if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
            return None
        return str(gitdir.parent.parent.parent.resolve())
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
                 settings_path=None, accounts_fn=None, update_fn=None, statusline_fn=None,
                 context_fn=None):
        self.token = token
        self.page_path = Path(page_path)
        self.snapshot_fn = snapshot_fn
        self.action_fn = action_fn
        self.settings_path = settings_path
        self.accounts_fn = accounts_fn
        #: () -> (ok, text): takes the release the panel was offered.
        self.update_fn = update_fn
        #: () -> the statusline it displaced; raises ValueError when it may not.
        self.statusline_fn = statusline_fn
        #: session id -> context_usage.parse()'s breakdown; raises context_usage.Refused.
        self.context_fn = context_fn

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
        if method == "POST" and path == "/update":
            if self.update_fn is None:
                return self._json(400, {"error": "this daemon cannot update itself"})
            ok, text = self.update_fn()
            if ok:
                return self._json(200, {"ok": True})
            # The text is git's or install.sh's own: the panel shows its last
            # line, the console the whole of it.
            print(f"sidebar: update refused:\n{text}", flush=True)
            return self._json(409, {"error": text})

        if method == "POST" and path == "/statusline":
            if self.statusline_fn is None:
                return self._json(400, {"error": "this daemon cannot install the statusline bridge"})
            try:
                self.statusline_fn()
            except (ValueError, OSError) as refusal:
                print(f"sidebar: statusline bridge refused: {refusal}", flush=True)
                return self._json(409, {"error": str(refusal)})
            return self._json(200, {"ok": True})

        if method == "POST" and path == "/context":
            return self._context(body)

        # Read the page from disk per request, so editing it needs no restart.
        return (200, "text/html; charset=utf-8", self.page_path.read_bytes())

    def _action(self, body):
        try:
            request = json.loads(body or b"{}")
        except ValueError:
            return self._json(400, {"error": "malformed body"})

        if not isinstance(request, dict):
            return self._json(400, {"error": "malformed body"})
        verb = request.get("verb")
        session_id = request.get("session_id")
        text = request.get("text")
        if verb not in VERBS or not isinstance(session_id, str) or not session_id:
            return self._json(400, {"error": "unknown verb"})
        if text is not None and not isinstance(text, str):
            return self._json(400, {"error": "malformed body"})

        self.action_fn(session_id, verb, text)
        return self._json(200, {"ok": True})

    def _context(self, body):
        try:
            session_id = json.loads(body or b"{}").get("session_id")
        except (ValueError, AttributeError):
            return self._json(400, {"error": "malformed body"})
        if not isinstance(session_id, str) or self.context_fn is None:
            return self._json(400, {"error": "a context read needs a session_id"})
        try:
            breakdown = self.context_fn(session_id)
        except context_usage.Refused as refusal:
            return self._json(409, {"error": str(refusal)})
        return self._json(200, {"ok": True, "context": breakdown})

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
#: How often the mirror is asked for a newer release.
RELEASE_CHECK_SECONDS = 24 * 60 * 60

#: Variables Bridge reads per session. `path` and `autoName` drive classify;
#: `jobName` is display only, and only on shell rows; `jobPid` and `tty` are
#: an omp row's process and terminal, since omp publishes neither.
SESSION_VARIABLES = ("path", "autoName", "jobName", "jobPid", "tty", "name", "tmuxWindowPane",
                     # Written by the plugin hook (Claude Code and Codex) and by claude-status.
                     "user.claudeState", "user.codexState", "user.claudeStatus")


class Server:
    """The asyncio listener. A thin adapter over Sidebar.handle plus the one
    thing handle cannot express: a response that never ends (SSE).
    """

    def __init__(self, sidebar, health_fn=lambda: True, restart_fn=lambda: None):
        self.sidebar = sidebar
        self.subscribers = set()
        #: Runs once a taken update has been answered; the process does not
        #: come back from it.
        self.restart_fn = restart_fn
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

        path = urlsplit(target).path
        if path in ("/accounts", "/update", "/context"):
            # Account ops wait on the Keychain, Claude Code's locks and the
            # network, for seconds, an update on a pull and install.sh, and a
            # context read on a fork of claude; off the loop, the heartbeat
            # keeps going.
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
        # Only once the answer is on the wire: the page says "restarting" from it.
        if path == "/update" and status == 200:
            self.restart_fn()

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
        self._rebuilding = False
        self._rebuild_again = False
        #: (pid, kind) -> when that session last read heavy, for hold_heavy.
        self._heavy_seen = {}
        #: The hook session ids that have a card, which the state sweep spares.
        self.live_sessions = set()
        self.trips = ReturnTrips()
        #: The rows of the last rebuild, which a resume and a context read
        #: re-check against.
        self.rows = []
        self.context_reads = context_usage.Reads()
        #: Session id -> (when a resume was typed into it, the job it was typed
        #: at), until its agent reports; see still_resuming.
        self.resuming = {}
        #: session id -> the question last answered from its card.
        self.answered = {}
        self.notifier_missing_said = False
        #: The mirror release newer than this checkout, or None; set by watch_releases.
        self.update = None
        self.notices = Notices()
        #: Plays the panel's sounds; main() makes it before the server takes
        #: its first request, since making it writes the tone files.
        self.player = None

    def active_session_id(self):
        """The session in front of the key iTerm2 window, or None."""
        window = self.app.current_terminal_window
        tab = window.current_tab if window else None
        session = tab.current_session if tab else None
        return session.session_id if session else None

    async def read_sessions(self):
        # Two execs and a walk of the process table: in a thread, or the
        # heartbeat, the settings sheet and every focus click wait behind them.
        (shells, started, agent_colours, agent_parents), tmux_panes, resources, commands = \
            await asyncio.to_thread(read_system)
        codex_jobs = await asyncio.to_thread(read_codex_jobs)
        rows, pids, live_sessions = [], [], set()
        for window_index, window in enumerate(self.app.terminal_windows, start=1):
            for tab_index, tab in enumerate(window.tabs, start=1):
                for pane_index, session in enumerate(tab.sessions, start=1):
                    # Issued together: each is a round trip to iTerm2.
                    # Unreadable is a real state, not an error to hide;
                    # classify renders it as "?".
                    read = await asyncio.gather(
                        *(session.async_get_variable(name) for name in SESSION_VARIABLES),
                        return_exceptions=True)
                    values = {name: None if isinstance(value, BaseException) else value
                              for name, value in zip(SESSION_VARIABLES, read)}
                    pane = tmux_panes.get(values["tmuxWindowPane"]) or {}
                    # tmux's directory for its own pane over iTerm2's guess.
                    values["path"] = pane.get("path") or values["path"]
                    raw, provider = agent_variable(values["user.claudeState"], values["user.codexState"])
                    raw = with_detail(raw)
                    live_sessions.add(parse_session(raw))
                    # Codex opens its session at the first prompt, so a TUI
                    # waiting at its prompt has published nothing. The
                    # foreground job is then the only evidence that a person
                    # is sitting in front of an agent; a pane that has
                    # published state is left to speak for itself.
                    job = values["jobName"] or pane.get("job")
                    codex_tui = provider is None and job == "codex"
                    if codex_tui:
                        provider = "openai"
                    # omp reports through no hook: its title is its only word,
                    # and a pane that did publish state speaks for itself.
                    titled = omp_title_state(values["autoName"]) if provider is None else None
                    if titled:
                        provider = "omp"
                    pid = job_pid(values["jobPid"]) if titled else parse_pid(raw)
                    doing = running = spawned = None
                    if provider == "openai" and raw:
                        # Codex has no statusline: the hook names the model and
                        # the rollout has the rest.
                        published = parse_codex(raw)
                        status = dict(parse_status(None), model=published["model"],
                                      **await asyncio.to_thread(codex.read_session,
                                                                published["transcript_path"]))
                    elif titled:
                        # tmux's terminal for its own pane over iTerm2's,
                        # which has none for a pane tmux drives.
                        told = await asyncio.to_thread(
                            omp.read_session, omp.TERMINALS_DIR,
                            pane.get("tty") or (resources.get(pid) or (None,) * 4)[3] or values["tty"])
                        status = dict(parse_status(None), model=told["model"], effort=told["effort"],
                                      context=told["context"],
                                      details={} if told["cost"] is None else {"cost": told["cost"]})
                        doing = told["doing"]
                        # omp runs its background commands itself, under no
                        # marker a process listing could match; its log names them.
                        home = os.path.expanduser("~") + "/"
                        running = [{"label": shell_label(command).replace(home, "~/"), "command": command}
                                   for command in told["jobs"]]
                        # omp names a subagent itself, and says what kind it is
                        # where a Claude subagent has its type.
                        spawned = [{**agent, "name": agent["id"], "provider": "omp", "depth": 0}
                                   for agent in told["agents"]]
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
                        "job_name": job,
                        "agent_job": codex_tui,
                        "provider": provider,
                        "agent_state": titled or parse_state(raw, command_running=bool(shells.get(pid))),
                        "topic": omp_title_topic(values["autoName"]) if titled else None,
                        "doing": doing,
                        "agents": parse_agents(raw) if spawned is None
                                  else sum(agent["ended"] is None for agent in spawned),
                        # A Codex job a Claude session started through the
                        # codex plugin runs outside its process tree, so the
                        # plugin's own job store is the only place it shows.
                        "subagents": spawned if spawned is not None else merge_codex_rows(
                            parse_subagents(raw), codex_job_rows(
                                codex_jobs, parse_session(raw), parse_turn_started(raw), resources)
                            if provider == "claude" else []),
                        "blocked_since": parse_blocked_since(raw),
                        "question": parse_question(raw),
                        "tasks": parse_tasks(raw),
                        "working_since": parse_working_since(raw),
                        "context": status["context"],
                        "model": status["model"],
                        "effort": status["effort"],
                        "details": status["details"],
                        # Read here, not in snapshot: the transcript is IO and
                        # snapshot is the pure unit that the tests pin down.
                        "agent_name": marks["agent"],
                        "team": marks["team"],
                        "shells": shells.get(pid, []) if running is None else running,
                        "started_at": started.get(pid),
                        # A teammate wears the colour it was spawned with; a
                        # session wears the one cs gave its directory.
                        "colour": agent_colours.get(pid)
                                  or session_colour(values["path"]),
                        "task": read_task(parse_session(raw)),
                        # Who spawned this pane, and which Claude session it
                        # is, so a teammate can be nested under its lead.
                        "parent_session": agent_parents.get(pid),
                        "claude_session": status["session"],
                        # The hook's own id for the conversation, which outlives
                        # the process: the statusline's dies with it.
                        "conversation": parse_session(raw),
                        "rollout": parse_codex(raw)["transcript_path"] if provider == "openai" else None,
                        "branch": git_branch(values["path"]),
                        "worktree_of": git_main_worktree(values["path"]),
                    })
                    pids.append(pid)
        # After every row is known: a session's tree ends where another's begins.
        self.live_sessions = live_sessions - {None}
        settings, roots, now = load_settings(), set(pids), time.monotonic()
        self.resuming = still_resuming(self.resuming, rows, now)
        for row in rows:
            # Read only once the agent is gone: it is a walk of every project folder.
            row["saved"] = row["agent_state"] == "exited" and conversation_saved(
                row["provider"], row["conversation"], row["rollout"])
            row["resumable"] = resumable(row, rows, self.resuming)
        self.rows = rows
        forget_heavy(self._heavy_seen, roots)
        for row, pid in zip(rows, pids):
            cpu, rss_kb = tree_usage(resources, pid, roots)
            row["heavy"] = hold_heavy(self._heavy_seen, heavy_on(cpu, rss_kb, settings), pid, now)
            hogs = tree_hogs(resources, commands, pid, roots) if row["heavy"] else {}
            row["usage"] = usage_shown(row["heavy"], cpu, rss_kb, hogs)
        return rows

    def healthy(self):
        return rebuild_is_fresh(self.last_ok, time.monotonic())

    async def rebuild(self):
        """Read everything and push the result if it changed.

        Asked for while one is under way -- a tab opening fires several
        layout events -- it only marks that the running one should go round
        once more, so a burst costs two readings, not one each.
        """
        if self._rebuilding:
            self._rebuild_again = True
            return
        self._rebuilding = True
        try:
            while True:
                self._rebuild_again = False
                await self._rebuild_once()
                if not self._rebuild_again:
                    return
        finally:
            self._rebuilding = False

    async def _rebuild_once(self):
        await self.app.async_refresh()
        settings = load_settings()
        self.latest = snapshot(await self.read_sessions(), settings["sort_by_name"],
                               settings["provider_mark"] == "groups")
        self.latest["version"] = version()
        self.answered = still_answered(self.answered, self.latest)
        if statusline_offer(statusline.state(CLAUDE_SETTINGS, BRIDGE), settings):
            self.latest["statusline"] = "missing"
        if self.update:
            self.latest["update"] = self.update
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
        # Before the lookup below: a notice names a session, it does not touch
        # one, so taking a stale notice down must still work once the session
        # it belongs to has closed.
        if verb == "notify":
            await self.notify(session_id, text)
            return
        # Nor does a sound: the moment it marks may already be over.
        if verb == "sound":
            await self.player.play(session_id, text, load_settings())
            return
        session = self.app.get_session_by_id(session_id)
        if session is None:
            # A row can outlive the session it names: the page holds a
            # snapshot. Say so in the Script Console rather than pretending
            # the action worked.
            print(f"sidebar: {verb} on {session_id}: gone", flush=True)
            return
        if verb == "resume":
            await self.resume(session, session_id)
            return
        if verb == "answer":
            await self.answer_from_card(session, session_id, text)
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
            for stroke in keystrokes(text or ""):
                await session.async_send_text(stroke)
                await asyncio.sleep(0.05)
        elif verb == "close":
            # Forced: the page has already asked for a second click, and
            # iTerm2's own "a job is running" prompt would then ask a third
            # time, behind the panel, for every agent pane.
            await session.async_close(force=True)
        print(f"sidebar: {verb} on {session_id}: ok", flush=True)

    async def resume(self, session, session_id):
        """Type the resume command at the prompt of the pane the agent died in.

        Re-checked against the last rebuild, not the page's copy: the page
        can be seconds old, and a second click must find the first one held.
        """
        row = next((row for row in self.rows if row["session_id"] == session_id), None)
        if row is None or not resumable(row, self.rows, self.resuming):
            self.log("resume refused", session_id[:8])
            return
        command = resume_command(row["path"], row["provider"], row["conversation"])
        self.resuming[session_id] = (time.monotonic(), row["job_name"])
        await session.async_send_text(command + "\n")
        # In front, so cs's own question is where the answer is typed.
        await session.async_activate(select_tab=True, order_window_front=True)
        self.log("resume", session_id[:8], command)
        await self.rebuild()

    def read_context(self, session_id):
        """What fills the session's context, by /context on a fork. Blocks for
        seconds: the server runs it off the loop."""
        path, conversation = context_target(self.rows, session_id)
        self.log("context", session_id[:8], conversation[:8])
        return self.context_reads.run(session_id, path, conversation)

    async def answer_from_card(self, session, session_id, text):
        """Type the digit of the option clicked on a card, if its question still stands.

        Checked against the last rebuild, not the page's copy, and remembered,
        so a second click types nothing until a different question stands.
        """
        standing = (find_row(self.latest, session_id) or {}).get("question")
        keys = answer_keys(text, standing, self.answered.get(session_id))
        if keys is None:
            self.log("answer refused", session_id[:8], repr(text))
            return
        self.answered[session_id] = next_answered(standing, self.answered.get(session_id))
        await session.async_send_text(keys)
        self.log("answer", session_id[:8], keys)

    def log(self, *words):
        """Say it in the Script Console and in a file beside the status files.

        The console cannot be read from a shell, and a notice's life is a
        chain of processes whose failures are otherwise invisible.
        """
        line = " ".join(str(w) for w in words)
        print("sidebar: " + line, flush=True)
        try:
            with open(os.path.join(STATUS_DIR, "daemon.log"), "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
        except OSError:
            pass

    async def sweep_notices(self):
        """Take down every notice a previous daemon left standing.

        Their senders died with it, or die on their own once they notice, and
        a banner whose reply has nowhere to go is worse than none.
        """
        argv = notify_argv(NOTIFIER_APP, "ALL", "", "clear", None)
        if not os.access(argv[0], os.X_OK):
            return
        try:
            sweeper = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await sweeper.wait()
        except OSError as error:
            self.log(f"sweeping notices: {error!r}")

    async def notify(self, session_id, kind):
        """Post one session's notice, or take a standing one down.

        The sender stays alive until the notice is acted on and then prints
        what happened; that answer is turned into an action on the session.
        Silent when the bundle is not installed -- install.sh builds it, and
        a panel that works everywhere else should not stop because a notice
        cannot be sent. It says so once so the reason is findable in the
        Script Console.
        """
        if not notify_wanted(kind, session_id, self.active_session_id(),
                             self.app.app_active):
            return
        if kind == "clear":
            if self.notices.standing(session_id):
                self.log("notice down", session_id[:8])
            self.notices.clear(session_id)
            return
        row = find_row(self.latest, session_id) or {}
        if notifies_itself(row):
            return
        question = row.get("question")
        argv = notify_argv(NOTIFIER_APP, session_id, row.get("label", ""), kind, question)
        if argv is None:
            return
        if not os.access(argv[0], os.X_OK):
            if not self.notifier_missing_said:
                self.notifier_missing_said = True
                self.log(f"no notifier at {NOTIFIER_APP}; run install.sh")
            return
        await self.notices.retire(session_id)
        try:
            poster = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as error:
            self.log(f"notify {kind} on {session_id}: {error!r}")
            return
        self.notices.replace(session_id, poster, kind, question)
        self.log("notice up", session_id[:8], kind, "question" if question else "plain")
        asyncio.ensure_future(self.answer(session_id, poster))

    async def notify_switch(self, name, why):
        """Say that the daemon changed the login, since nobody clicked anything.

        The sender takes its notice down when it exits, so it is left running
        and reaped when the notice is dismissed.
        """
        argv = switch_notice_argv(NOTIFIER_APP, name, why)
        if not load_settings()["notify"] or not os.access(argv[0], os.X_OK):
            return
        try:
            poster = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as error:
            self.log(f"notify switch: {error!r}")
            return
        asyncio.ensure_future(poster.wait())

    async def answer(self, session_id, poster):
        """Read the sender's lines and act on each, for whichever notice.

        macOS hands every response for the bundle to one running sender, so
        a line may answer another session's notice; the id it names says
        which, and that notice's own sender is then taken down. The question
        is checked again against the row as it is NOW, not as it was when
        the notice went up: a button for a prompt the user has since
        answered in the terminal must send nothing.
        """
        while True:
            line = (await poster.stdout.readline()).decode("utf-8", "replace").strip()
            if not line:
                break
            target = response_target(line, session_id)
            asked = self.notices.asked(target)
            if asked is None:
                self.log("notice answered", target[:8], line, "but nothing stands for it")
                continue
            kind, question = asked
            if target != session_id:
                self.notices.clear(target)
            standing = (find_row(self.latest, target) or {}).get("question")
            if kind == "blocked" and standing != question:
                self.log("notice answered", target[:8], "but its question has gone")
                question = None
            verb, text = notify_response(line, kind, question)
            self.log("notice answered", target[:8], line, "->", verb, repr(text))
            if verb is None:
                continue
            try:
                await self.act(target, verb, text)
            except Exception as error:               # noqa: BLE001
                self.log(f"acting on a notice for {target}: {error!r}")
        await poster.wait()
        self.notices.forget(session_id, poster)

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
        if op == "read":
            # The reload button: a person asking for fresh figures wants a
            # fresh answer about releases too, not tomorrow's.
            self.check_release()
            return self.meters.read_now(time.time())
        if op == "add":
            result = self.meters.add(time.time())
        elif op == "rename":
            result = self.meters.rename(request["account_id"], request["alias"])
        else:
            result = self.meters.switch(request["account_id"], time.time())
        self.meters.tick(time.time(), models=self.models_running())
        return result

    def models_running(self):
        """The families switching should count, or None before the first
        rebuild has said which sessions there are."""
        return running_models(self.latest) if self.last_ok is not None else None

    async def watch_accounts(self):
        """Read account usage in the background; rebuild picks the result up.

        Every reading is Keychain and network IO that can take seconds, so it
        runs in a thread: on the event loop it would stall the heartbeat and
        flag the whole panel stale.
        """
        while True:
            try:
                auto = load_settings()["auto_switch"]
                events = await asyncio.to_thread(self.meters.tick, time.time(), auto, self.models_running())
                for event in events:
                    self.log(switch_log_line(event))
                    if event["kind"] == "switched":
                        await self.notify_switch(event["name"], event["why"])
            except Exception as error:               # noqa: BLE001
                print(f"sidebar: account meters failed: {error!r}", flush=True)
            await asyncio.sleep(ACCOUNT_TICK_SECONDS)

    async def sweep_status(self):
        """Clear dead sessions' status files, on the account loop's cadence."""
        while True:
            try:
                await asyncio.to_thread(sweep_status_dir, time.time())
                # Not before a rebuild has said which sessions have a card.
                if self.healthy():
                    await asyncio.to_thread(sweep_state_dir, time.time(),
                                            set(self.live_sessions), HOOK_STATE_DIR)
            except Exception as error:               # noqa: BLE001
                print(f"sidebar: status sweep failed: {error!r}", flush=True)
            await asyncio.sleep(ACCOUNT_TICK_SECONDS)

    async def rebuild_or_report(self):
        try:
            await self.rebuild()
        except Exception as error:               # noqa: BLE001
            # Reaches iTerm2's log via the webview "logger" handler is not
            # available here, so print -- the Script Console shows it.
            print(f"sidebar: rebuild failed: {error!r}", flush=True)

    async def poll(self):
        while True:
            await asyncio.sleep(POLL_SECONDS)
            await self.rebuild_or_report()

    def check_release(self):
        """Ask the mirror once, off the loop, and put the answer where the next
        page connect and the next rebuild both find it. A check that cannot
        answer offers nothing."""
        self.update = update.offer(update.check(), version())
        if self.update:
            print(f"sidebar: release {self.update} is on the mirror", flush=True)
            self.latest["update"] = self.update
        else:
            self.latest.pop("update", None)

    async def watch_releases(self):
        """Once at start, then daily: is there a newer release on the mirror?
        The reload button asks in between.
        """
        while True:
            await asyncio.to_thread(self.check_release)
            await self.rebuild_or_report()
            await asyncio.sleep(RELEASE_CHECK_SECONDS)


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
        update_fn=lambda: update.take(here),
        statusline_fn=lambda: statusline.install(CLAUDE_SETTINGS, BRIDGE, STATUS_DIR),
        context_fn=lambda session_id: bridge.read_context(session_id),
    )
    server = Server(sidebar, health_fn=lambda: bridge.healthy(), restart_fn=restart)
    bridge = Bridge(connection, server, meters)
    bridge.player = sound.Player.for_dir(os.path.join(STATUS_DIR, "tones"), bridge.log)
    bridge.app = await iterm2.async_get_app(connection)

    port = await server.start()
    await bridge.rebuild_or_report()
    await bridge.sweep_notices()

    await iterm2.tool.async_register_web_view_tool(
        connection, TOOL_DISPLAY_NAME, TOOL_IDENTIFIER, True,
        f"http://127.0.0.1:{port}/?token={token}")
    print(f"sidebar: serving on 127.0.0.1:{port}", flush=True)

    asyncio.ensure_future(bridge.watch_layout())
    asyncio.ensure_future(bridge.poll())
    asyncio.ensure_future(bridge.watch_accounts())
    asyncio.ensure_future(bridge.sweep_status())
    asyncio.ensure_future(bridge.watch_releases())


def restart():
    """Replace this process with a fresh start of the same script, so the
    checkout just pulled is what runs. iTerm2 started this one through its
    AutoLaunch stub and relaunches nothing on its own; the stub is argv[0], so
    the same command brings the new code up under the same wrapper.
    """
    print("sidebar: restarting on the new release", flush=True)
    os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    import iterm2
    iterm2.run_forever(main)
