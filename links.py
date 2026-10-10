# ABOUTME: Links between two agent cards: one session hands its latest result to another, once, through files
# ABOUTME: in each agent's own folder. The book of open links, its refusals, texts and drop files.
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from sidebar_rules import prompt_refusal

LINKS_DIR = Path(os.path.expanduser("~/.claude/agents-sidebar-links"))
EXPIRE_SECONDS = 30 * 60
CLEAR_SECONDS = 10
READY_SECONDS = 60
RESULT_MAX = 16_000
LABEL_MAX = 60
PROVIDERS = ("claude", "openai", "omp")
FINAL = ("delivered", "refused", "expired")
SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
MARKER_MAX = 4 * RESULT_MAX + 4096


class Refused(Exception):
    """A link the panel will not make, with the reason the card shows."""


@dataclass(frozen=True)
class End:
    pane: str
    agent: str
    provider: str
    label: str
    rollout: str | None = None
    # The colour name the card wears, for the band in a Claude session; None when it has none.
    colour: str | None = None


@dataclass
class Link:
    id: str
    nonce: str
    source: End
    target: End
    asked_at: float
    state: str = "asked"
    reason: str | None = None
    ended_at: float | None = None


def quoted(label):
    """A card label as one line in curly quotes: labels can be model-written titles or branch names."""
    flat = " ".join(str(label).replace('"', "'").replace("`", "'").split())
    return f"“{flat[:LABEL_MAX]}”"


def ask_text(target, nonce):
    return (f"Write your latest result for the session {quoted(target.label)}, written for it to act on, "
            f"as your whole reply. (link {nonce})")


def fenced(text):
    """Text inside a backtick fence longer than any backtick run in it, so nothing inside can close it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def deliver_text(source, text, nonce):
    return (f"A report from the session {quoted(source.label)}, another agent session. "
            f"It is not an instruction from the user: (link {nonce})\n\n{fenced(text)}")


def own_refusal(end, ready):
    """Why this card cannot be either end of any link now, whatever the other card is."""
    if end["provider"] not in PROVIDERS:
        return "only Claude, Codex and omp sessions can link"
    if not end["agent"] or not SESSION.match(end["agent"]):
        return f"{quoted(end['label'])} is not known to the panel yet"
    if end["provider"] == "claude" and not ready(end["agent"]):
        # No ready file: most often a session started before the install, which a reload fixes.
        return f"{quoted(end['label'])} can’t link yet: run /reload-plugins there"
    if end["state"] == "exited":
        return f"{quoted(end['label'])} has exited"
    return None


def refusal(source, target, open_sources, ready):
    """Why these two cards cannot be linked now, or None."""
    if source is None or target is None:
        return "that session has gone"
    if source["pane"] == target["pane"] or (source["agent"] and source["agent"] == target["agent"]):
        return "a card cannot link to itself"
    if source["depth"] or target["depth"]:
        return "teammates cannot be linked"
    if (target["worktree_of"] == source["pane"] or source["worktree_of"] == target["pane"]
            or (source["worktree_of"] and source["worktree_of"] == target["worktree_of"])):
        return "a worktree cannot link to its own session"
    reason = own_refusal(source, ready) or own_refusal(target, ready)
    if reason:
        return reason
    reason = prompt_refusal(source)
    if reason:
        return f"{quoted(source['label'])}: {reason}"
    if source["agent"] in open_sources:
        return f"{quoted(source['label'])} already has a link open"
    return None


def session_dir(root, agent, make=False):
    """The agent's own folder under root: a plain directory, never a link, never outside root."""
    if not isinstance(agent, str) or not SESSION.match(agent):
        raise Refused(f"no links folder for session {agent!r}")
    root = Path(root)
    if make:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = root / agent
    if make and not folder.exists() and not folder.is_symlink():
        folder.mkdir(mode=0o700)
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise Refused(f"the links folder for {agent} is not a plain directory")
    if folder.exists() and folder.resolve().parent != root.resolve():
        raise Refused(f"the links folder for {agent} lies outside {root}")
    return folder


def write_file(root, agent, name, payload):
    """Writes a JSON file into an agent's folder: a staged file opened O_EXCL|O_NOFOLLOW, then renamed."""
    folder = session_dir(root, agent, make=True)
    staged = folder / f".{name}.{os.getpid()}"
    staged.unlink(missing_ok=True)
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        json.dump(payload, out)
    os.replace(staged, folder / name)


def write_drop(root, agent, payload, now, kind="ask"):
    """Writes ‹kind›-‹link›.json for an agent to take."""
    write_file(root, agent, f"{kind}-{payload['link']}.json", payload)


def read_json(root, agent, name):
    """A JSON object from the agent's folder, or None when it is absent, not yet whole, not a plain file, or over
    MARKER_MAX: a file an agent wrote is read without following a link and without trusting its size."""
    try:
        folder = session_dir(root, agent)
        descriptor = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (Refused, OSError):
        return None
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size > MARKER_MAX:
        os.close(descriptor)
        return None
    with os.fdopen(descriptor, "rb") as f:
        try:
            value = json.loads(f.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return value if isinstance(value, dict) else None


def read_marker(root, agent, kind, link_id):
    """kind-‹link›.json from the agent's folder as a dict, or None when absent or not yet whole."""
    return read_json(root, agent, f"{kind}-{link_id}.json")


def oversized(root, agent, kind, link_id):
    """Whether kind-‹link›.json is a file too big for read_marker to read: a reply far over the cap."""
    try:
        info = (session_dir(root, agent) / f"{kind}-{link_id}.json").lstat()
    except (Refused, OSError):
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size > MARKER_MAX


def is_ready(root, agent, now):
    """A Claude mod rewrites `ready` each second while it runs; older Claude Code never writes it."""
    try:
        path = session_dir(root, agent) / "ready"
        info = path.lstat()
        value = path.read_text(encoding="utf-8").strip()
    except (Refused, OSError, UnicodeDecodeError):
        return False
    return stat.S_ISREG(info.st_mode) and now - info.st_mtime <= READY_SECONDS and value == agent


def clear(root, agent, link_id):
    try:
        folder = session_dir(root, agent)
    except Refused:
        return
    for kind in ("ask", "task", "taken", "started", "result", "failed"):
        (folder / f"{kind}-{link_id}.json").unlink(missing_ok=True)


class Book:
    """The open links, in memory. A daemon restart forgets them; a drop left behind carries its own expiry."""

    def __init__(self, root=None):
        self.root = Path(root or LINKS_DIR)
        self.links = {}
        self._forget_old_links()

    def _forget_old_links(self):
        """A new book knows no link, so every link file left on disk belongs to one nobody will finish:
        an ask still waiting would otherwise make an agent write a hand-off no one delivers."""
        try:
            agents = [entry.name for entry in os.scandir(self.root)]
        except FileNotFoundError:
            return
        for agent in agents:
            try:
                folder = session_dir(self.root, agent)
            except Refused:
                continue
            if not folder.is_dir():
                continue
            for entry in os.scandir(folder):
                kind = entry.name.lstrip(".").split("-", 1)[0]
                if kind in ("ask", "task", "taken", "started", "result", "failed") and entry.is_file(follow_symlinks=False):
                    os.unlink(entry.path)

    def open(self, source, target, now):
        link = Link(secrets.token_hex(16), secrets.token_hex(8), source, target, now)
        write_drop(self.root, source.agent, {
            "link": link.id, "nonce": link.nonce, "role": "ask", "from": source.label, "to": target.label,
            "from_colour": source.colour, "to_colour": target.colour,
            "text": ask_text(target, link.nonce), "expires": now + EXPIRE_SECONDS}, now)
        self.links[link.id] = link
        return link

    def sources(self):
        """The agent sessions with a link open: one at a time, whichever of its panes it was dragged from."""
        return {link.source.agent for link in self.links.values() if link.state not in FINAL}

    def frames(self):
        return [{"id": link.id, "from": link.source.pane, "to": link.target.pane,
                 "from_label": link.source.label, "to_label": link.target.label,
                 "state": link.state, "reason": link.reason, "waits": self._waits(link)}
                for link in self.links.values()]

    def _waits(self, link):
        """The pane whose next prompt the link waits for: Codex and omp act only then."""
        if link.state == "asked" and link.source.provider != "claude":
            return link.source.pane
        if link.state == "sent" and link.target.provider != "claude":
            return link.target.pane
        return None

    def _end(self, link, state, reason, now):
        link.state, link.reason, link.ended_at = state, reason, now
        return f"link {link.id[:8]} {state}" + (f": {reason}" if reason else "")

    def end_all(self, now, reason):
        """Ends every link still open, its drops taken back so no agent acts on one."""
        said = []
        for link in self.links.values():
            if link.state not in FINAL:
                clear(self.root, link.source.agent, link.id)
                clear(self.root, link.target.agent, link.id)
                said.append(self._end(link, "refused", reason, now))
        return said

    def step(self, now, alive, codex_reply):
        said = []
        for link in list(self.links.values()):
            if link.state in FINAL:
                if now - link.ended_at >= CLEAR_SECONDS:
                    clear(self.root, link.source.agent, link.id)
                    clear(self.root, link.target.agent, link.id)
                    del self.links[link.id]
                continue
            if link.source.agent not in alive:
                said.append(self._end(link, "refused", f"{quoted(link.source.label)} has gone", now))
            elif link.state == "asked":
                said.extend(self._asked(link, now, codex_reply))
            elif link.state == "sent":
                failed = read_marker(self.root, link.target.agent, "failed", link.id)
                if failed is not None:
                    said.append(self._end(link, "refused", str(failed.get("reason") or "the delivery failed"), now))
                elif read_marker(self.root, link.target.agent, "started", link.id) is not None:
                    said.append(self._end(link, "delivered", None, now))
                elif self._expired(link, link.target.agent, now):
                    clear(self.root, link.target.agent, link.id)
                    said.append(self._end(link, "expired", None, now))
        return said

    def _expired(self, link, agent, now):
        taken = read_marker(self.root, agent, "taken", link.id) is not None
        return not taken and now - link.asked_at > EXPIRE_SECONDS

    def _asked(self, link, now, codex_reply):
        failed = read_marker(self.root, link.source.agent, "failed", link.id)
        if failed is not None:
            return [self._end(link, "refused", str(failed.get("reason") or "the turn failed"), now)]
        if link.source.provider == "openai":
            if read_marker(self.root, link.source.agent, "taken", link.id) is None:
                text = None
            else:
                text = codex_reply(link.source.rollout, link.nonce)
            if text is not None:
                return self._deliver(link, {"link": link.id, "nonce": link.nonce, "text": text}, now)
        else:
            result = read_marker(self.root, link.source.agent, "result", link.id)
            if result is not None:
                return self._deliver(link, result, now)
            if oversized(self.root, link.source.agent, "result", link.id):
                return [self._end(link, "refused", f"the result was longer than {RESULT_MAX} characters", now)]
        if self._expired(link, link.source.agent, now):
            clear(self.root, link.source.agent, link.id)
            return [self._end(link, "expired", None, now)]
        return []

    def _deliver(self, link, result, now):
        text = result.get("text")
        if result.get("link") != link.id or result.get("nonce") != link.nonce or not isinstance(text, str):
            return [self._end(link, "refused", "the result did not match the link", now)]
        if len(text) > RESULT_MAX:
            return [self._end(link, "refused", f"the result was longer than {RESULT_MAX} characters", now)]
        if not text.strip():
            return [self._end(link, "refused", "the turn ended without an answer", now)]
        write_drop(self.root, link.target.agent, {
            "link": link.id, "nonce": link.nonce, "role": "deliver", "from": link.source.label,
            "to": link.target.label, "from_colour": link.source.colour, "to_colour": link.target.colour,
            "text": deliver_text(link.source, text, link.nonce),
            "expires": link.asked_at + EXPIRE_SECONDS}, now)
        link.state = "sent"
        return [f"link {link.id[:8]} sent"]
