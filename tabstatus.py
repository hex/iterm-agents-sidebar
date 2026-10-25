# ABOUTME: Writes iTerm2's status line under each agent's tab from the panel's own reading:
# ABOUTME: working, needs you or done in the panel's colours, nothing at rest, taken back when it stops.
"""The status indicator is a view of the agent rows, as the marks are a view
of Unseen. A rebuild says what every owned session should show; the writer
diffs that against what it last wrote and sends only the changes. A session
another writer owns (iTerm2's own cc-status hooks, while they are installed)
is yielded: never written, and handed back clean."""
import unicodedata
from dataclasses import dataclass
from typing import Literal

Word = Literal["working", "needs you", "done"]

#: The one table of words and colours, dark-theme values as the tab bar
#: cannot follow the panel's theme. Working is iTerm2's own working orange,
#: one unit off cc-status's #ff9500 so the signature still tells the two
#: dots apart; needs you is the panel's --blocked-border; done its --sev-ok.
FACES: dict = {"working": "#ff9501", "needs you": "#ff9f0a", "done": "#30d158"}
#: The longest detail written: one line under a tab title.
DETAIL_MOST = 60


@dataclass(frozen=True)
class Status:
    """What one tab shows. Built by `status_of`, so `detail` is always one
    clean, clipped line; dot and text both wear the word's colour."""
    word: Word
    detail: str
    background: int

    def args(self, session_id):
        """The set_session_status arguments."""
        colour = FACES[self.word]
        return {"session_id": session_id, "status": self.word, "detail": self.detail,
                "dot_color": colour, "text_color": colour, "background_tasks": self.background}


def clear_args(session_id):
    """Every field emptied in one call: a colour left out would survive the clear."""
    return {"session_id": session_id, "status": "", "detail": "", "dot_color": "",
            "text_color": "", "background_tasks": 0}


def one_line(text):
    """Whitespace runs to one space, control characters dropped, clipped to
    DETAIL_MOST with an ellipsis. Agent text crosses into an iTerm2
    expression here; its quoting is the iterm2 library's, this keeps it one line."""
    folded = " ".join(text.split())
    clean = "".join(ch for ch in folded if unicodedata.category(ch) != "Cc")
    if len(clean) <= DETAIL_MOST:
        return clean
    return clean[:DETAIL_MOST - 1].rstrip() + "…"


def _question(row):
    """What a blocked row waits on: an AskUserQuestion's question, else a
    permission gate's tool and what it wants, else what it was doing."""
    asked = row.get("question") or {}
    if "question" in asked:
        return asked["question"]
    if "tool" in asked:
        return f"{asked['tool']}: {asked['summary']}" if asked["summary"] else asked["tool"]
    return row.get("doing", "")


def status_of(row, unseen):
    """One agent row -> what its tab shows, or None for nothing.

    working -> "working" with what the agent says it is doing; blocked ->
    "needs you" with what it waits on; idle, finished unseen and a card ->
    "done" with no detail, as only a card shows Done on the panel. Anything
    else rests and shows nothing. The count beside the word is running
    subagents and background shells."""
    background = row.get("agents", 0) + len(row.get("shells", []))
    state = row.get("state")
    if state == "working":
        return Status("working", one_line(row.get("doing", "")), background)
    if state == "blocked":
        return Status("needs you", one_line(_question(row)), background)
    if state == "idle" and not row["depth"] and row["session_id"] in unseen:
        return Status("done", "", background)
    return None


#: Two rows on one session (agents in panes of a plain tmux) show the word
#: that most needs the reader, first in this order.
URGENCY = ("needs you", "working", "done")


def local_claude(row):
    """A Claude session on this machine: the only kind cc-status writes.
    The row names no provider for Claude, and a host only when remote."""
    return row.get("provider") is None and not row.get("host")


def wanted(rows, unseen, settings, hooks):
    """-> (sid -> Status for every owned row with something to show, the sids
    yielded to cc-status). Off, nothing is wanted and nothing yielded. A
    local Claude row is yielded while the hooks are "present" or "unreadable"."""
    if not settings["tab_status"]:
        return {}, set()
    want, yielded = {}, set()
    for row in rows:
        sid = row["session_id"]
        if local_claude(row) and hooks != "absent":
            yielded.add(sid)
            continue
        status = status_of(row, unseen)
        if status and (sid not in want or URGENCY.index(status.word) < URGENCY.index(want[sid].word)):
            want[sid] = status
    return {sid: status for sid, status in want.items() if sid not in yielded}, yielded


@dataclass(frozen=True)
class Plan:
    #: New or changed.
    writes: dict
    #: Ours on the tab, nothing wanted now.
    clears: set
    #: Ours on the tab, now yielded: read back, cleared only if the dot is still ours.
    releases: set


def plan(want, have, yielded):
    """`have` maps a sid to the Status on its tab, or None for a tab this
    daemon took over without knowing its shape, which no wanted Status equals."""
    return Plan(writes={sid: status for sid, status in want.items() if sid not in have or have[sid] != status},
                clears={sid for sid in have if sid not in want and sid not in yielded},
                releases={sid for sid in have if sid in yielded})


def notice(settings, hooks, available):
    """What the page is told: "unavailable" explains the setting and wins;
    "contested" only while the setting and the offer are both on."""
    if not available:
        return "unavailable"
    if settings["tab_status"] and settings["offer_tab_status"] and hooks == "present":
        return "contested"
    return None


GET, SET = "iterm2.get_session_status", "iterm2.set_session_status"
#: A dot in one of these colours was written by this daemon: cc-status uses none of them.
SIGNATURE = frozenset(FACES.values())
#: cc-status's own palette, read out of its binary: a dot in one of these is its word.
CC_PALETTE = frozenset({"#ff9500", "#00d75f", "#888888", "#ff3b30", "#5f87ff"})
#: How iTerm2 before 3.7.6 answers a call to a function it does not have.
UNKNOWN_FUNCTION = "No function registered"


def _dot(status):
    return (status.get("dot_color") or "").lower()


def _parsed(status):
    """A status read back -> the Status it is, when word and colour agree;
    None for a word of ours in a shape this daemon would not write."""
    word = status.get("status")
    if word in FACES and _dot(status) == FACES[word]:
        return Status(word, status.get("detail") or "", status.get("background_tasks") or 0)
    return None


class Writer:
    """Brings every owned tab's status into line with one reading. A tab is
    written only while the daemon owns it, and a dot in the daemon's colours
    stays only on a tab it owns: a tab that becomes yielded is read back and
    cleared if the dot is still ours, a dead daemon's dots are adopted at
    start, and cc-status's words are taken over only once its hooks are gone."""

    def __init__(self, invoke):
        #: async (function name, {argument: value}) -> the status dict iTerm2 answers.
        self._invoke = invoke
        #: sid -> the Status this daemon last wrote there, or None for a word it took over.
        self.have = {}
        #: False once iTerm2 has no such function, or no session's status could be read at start.
        self.available = True
        self.adopted = False
        #: The sids whose last call failed, so each failure is said once until one succeeds.
        self.failing = set()
        #: Whether local Claude tabs were the daemon's at the last reading: when
        #: they become so, the words cc-status left on them are taken over.
        self.claude_ours = False

    async def step(self, app, rows, unseen, settings, hooks, log):
        """`rows` are the agent rows, `unseen` Unseen.sids, `hooks` what
        statusline.cc_status says. Never raises for an iTerm2 call."""
        if not self.available:
            return
        want, yielded = wanted(rows, unseen, settings, hooks)
        claude_ours = settings["tab_status"] and hooks == "absent"
        if not self.adopted:
            self.adopted = True
            await self.adopt(app, yielded, claude_ours, log)
        elif claude_ours and not self.claude_ours:
            await self.sweep_handed_over(app, {row["session_id"] for row in rows if local_claude(row)}, log)
        self.claude_ours = claude_ours
        if not self.available:
            return
        todo = plan(want, self.have, yielded)
        for sid in sorted(todo.releases):
            if app.get_session_by_id(sid) is None:
                del self.have[sid]
                continue
            status = await self._call(GET, {"session_id": sid}, log)
            if status is None or (_dot(status) in SIGNATURE and await self._call(SET, clear_args(sid), log) is None):
                continue
            del self.have[sid]
        for sid in sorted(todo.clears):
            if app.get_session_by_id(sid) is None or await self._call(SET, clear_args(sid), log) is not None:
                del self.have[sid]
        for sid, status in sorted(todo.writes.items()):
            if app.get_session_by_id(sid) is not None and await self._call(SET, status.args(sid), log) is not None:
                self.have[sid] = status
            if not self.available:
                return

    async def adopt(self, app, yielded, claude_ours, log):
        """Read every session's status once. A dot in the daemon's colours was
        left by one that died: on an owned tab it enters `have`, so the first
        plan corrects or clears it; on a yielded tab it is cleared now. While
        local Claude tabs are the daemon's, a cc-status word on an owned tab is
        taken over the same way. Doubles as the probe for the functions."""
        sessions = [session for window in app.terminal_windows for tab in window.tabs for session in tab.sessions]
        read = 0
        for session in sessions:
            sid = session.session_id
            status = await self._call(GET, {"session_id": sid}, log)
            if not self.available:
                return
            if status is None:
                continue
            read += 1
            if _dot(status) in SIGNATURE:
                if sid in yielded:
                    await self._call(SET, clear_args(sid), log)
                else:
                    self.have[sid] = _parsed(status)
            elif claude_ours and sid not in yielded and _dot(status) in CC_PALETTE:
                self.have[sid] = None
        if sessions and not read:
            self.available = False
            log("tab status off: no session's status could be read")

    async def sweep_handed_over(self, app, sids, log):
        """Local Claude tabs just became the daemon's: take over the words
        cc-status left on them, so its idle and done do not stay for good."""
        for sid in sorted(sids):
            if sid in self.have or app.get_session_by_id(sid) is None:
                continue
            status = await self._call(GET, {"session_id": sid}, log)
            if not self.available:
                return
            if status is not None and _dot(status) in CC_PALETTE:
                self.have[sid] = None

    async def clear_all(self, log):
        """Take back every word in `have`: the daemon is stopping."""
        for sid in sorted(self.have):
            if await self._call(SET, clear_args(sid), log) is not None:
                del self.have[sid]

    async def _call(self, name, args, log):
        """-> the status iTerm2 answers, or None when the call failed. A
        failure is said once per session until a call there succeeds; an
        iTerm2 without the function turns the writer off."""
        sid = args["session_id"]
        try:
            answer = await self._invoke(name, args)
        except Exception as error:  # noqa: BLE001 -- an iTerm2 call; the rebuild goes on
            if UNKNOWN_FUNCTION in str(error):
                self.available = False
                log(f"tab status off: {error}")
            elif sid not in self.failing:
                self.failing.add(sid)
                log(f"status {sid[:8]}: {error!r}")
            return None
        self.failing.discard(sid)
        return answer
