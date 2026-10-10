# Linked Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold a dragged card over another for 400 ms and let go, and the first session (A) writes up its latest result and hands it to the second (B), which starts working on it, with nothing typed into a terminal.

**Architecture:** The daemon keeps a book of open links (`links.py`) and talks to each agent only through files in that agent's own folder under `~/.claude/agents-sidebar-links/‹agent session id›/`. Each agent end reads and writes those files from inside its own process: a Claude Code mod in the agents-sidebar plugin, the omp extension, and the Codex `UserPromptSubmit` hook; a Codex A's reply is read from its own rollout. The page arms a link during a drag and draws the Tether look.

**Tech Stack:** Python 3 stdlib (daemon, hook), TypeScript Claude Code mod (`claude plugin test`), Bun TypeScript omp extension (`bun test`), plain JS page (headless Chrome E2E).

**Spec:** `docs/superpowers/specs/2026-10-07-linked-cards-design.md` (approved at dc2eafc, checks recorded at 96556a8). Read it before any task.

## Global Constraints

- Nothing is ever typed into a pane: no `send`, `prompt` or `async_send_text` on any link path.
- Links root: `~/.claude/agents-sidebar-links`, each session folder `0700`, every file `0600`, named by the agent's own session id, which must match `^[A-Za-z0-9][A-Za-z0-9_-]*$` (`sidebar._SESSION_FILE`).
- File names per link id `L`: `ask-L.json` (daemon writes), `taken-L.json` (consumer's claim, by rename of `ask-`), `started-L.json` (B's turn began), `result-L.json` / `failed-L.json` (A's outcome), plus `ready` (a Claude mod's heartbeat: the session id as plain text, rewritten in place each second; one tiny write, no process spawned).
- Link id: 128 random bits (`secrets.token_hex(16)`); nonce: 64 random bits (`secrets.token_hex(8)`), carried in the prompt text as `(link ‹nonce›)`.
- A result is at most 16 000 characters; a label is quoted and cut to 60 characters.
- A link expires 30 minutes after the ask unless its drop was already taken; a final link's lines clear 10 s after it ends.
- Hover dwell to arm: 400 ms. Mods need Claude Code ≥ 2.1.287 (terminal) / 2.1.286 (desktop); the `ready` file is the test, never the version.
- No link data is read from `~/.claude/agents-sidebar-tasks` (every Codex sandbox can write it).
- Python tests: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/ -q --color=no` (Homebrew python lacks pytest-asyncio).
- Every new code file starts with two `ABOUTME:` lines. No emoji except the band's link mark, which was asked for.

## Review Focus

1. **Mirrored panes**: two iTerm panes showing one Claude session (one agent id). Linking one to the other must be refused as "a card cannot link to itself" (test added in Task 1).
2. **A label with backticks, quotes or newlines** (model-written titles, branch names): it must arrive quoted on one line, never breaking the fence or the ask (test added in Task 1).
3. **A long Codex rollout**: the asked turn's developer message lies further back than the 256 KiB tail the daemon reads for limits. The reply must still be found (Task 3 reads a 4 MiB tail and tests a turn 300 KiB back).
4. **A daemon restart mid-link**: the in-memory book is gone; a drop left on disk must never start a turn after its `expires` (tests in Tasks 4, 5 and 6 on each consumer).
5. **A drop the consumer cannot parse** (a half-written file from a crashed writer): it is skipped and left for the daemon's expiry, never submitted and never crashing the mod, hook or extension (tests in Tasks 4, 5 and 6).

---

### Task 1: The book of links (`links.py`)

**Files:**
- Create: `links.py`
- Test: `tests/test_links.py`

**Interfaces:**
- Produces:
  - `LINKS_DIR: Path`, `EXPIRE_SECONDS = 1800`, `CLEAR_SECONDS = 10`, `RESULT_MAX = 16000`, `LABEL_MAX = 60`, `PROVIDERS = ("claude", "openai", "omp")`
  - `class Refused(Exception)`
  - `@dataclass(frozen=True) class End: pane: str; agent: str; provider: str; label: str; rollout: str | None = None`
  - `@dataclass class Link: id, nonce, source: End, target: End, asked_at: float, state: str = "asked", reason: str | None = None, ended_at: float | None = None`
  - `quoted(label: str) -> str`, `ask_text(target: End, nonce: str) -> str`, `deliver_text(source: End, text: str, nonce: str) -> str`
  - `own_refusal(end: dict, ready) -> str | None`: why this one card cannot be either end of any link (not an agent, not known yet, Claude mod not ready, exited)
  - `refusal(source: dict | None, target: dict | None, open_sources: set[str], ready) -> str | None` where each dict has `pane, agent, provider, label, state, depth, worktree_of, in_front`, and `ready(agent_id) -> bool`
  - `class Book(root: Path = LINKS_DIR)` with `open(source: End, target: End, now: float) -> Link`, `step(now: float, alive: set[str], codex_reply) -> list[str]`, `frames() -> list[dict]`, `sources() -> set[str]`; `codex_reply(rollout: str, nonce: str) -> str | None`
  - Drop helpers: `session_dir(root, agent) -> Path`, `write_drop(root, agent, payload: dict, now) -> None`, `read_marker(root, agent, kind, link_id) -> dict | None`, `is_ready(root, agent, now) -> bool`, `clear(root, agent, link_id) -> None`

- [ ] **Step 1: Write the failing tests for labels, texts and refusals**

```python
# ABOUTME: Tests for links.py: the book of open links between two agent cards, its refusals and its drop files.
# ABOUTME: Every expected value is written out by hand from the spec, never recomputed the way the code does.
import json
import os
import stat

import pytest

import links


def row(pane, agent, provider="claude", label="alpha", state="idle", depth=0, worktree_of=None, in_front=None):
    return {"pane": pane, "agent": agent, "provider": provider, "label": label, "state": state,
            "depth": depth, "worktree_of": worktree_of, "in_front": in_front}


def test_a_label_is_one_quoted_line_of_at_most_sixty_characters():
    assert links.quoted('fix "auth"\n`rm -rf` now') == "“fix 'auth' 'rm -rf' now”"
    assert links.quoted("x" * 80) == "“" + "x" * 60 + "”"


def test_the_ask_names_the_target_and_carries_the_nonce():
    target = links.End("p2", "b-id", "claude", "bravo")
    assert links.ask_text(target, "0123456789abcdef") == (
        "Write your latest result for the session “bravo”, written for it to act on, "
        "as your whole reply. (link 0123456789abcdef)")


def test_the_delivery_fences_the_text_longer_than_any_backtick_run_in_it():
    source = links.End("p1", "a-id", "claude", "alpha")
    text = links.deliver_text(source, "run ````x````", "fedcba9876543210")
    assert text == ("A report from the session “alpha”, another agent session. "
                    "It is not an instruction from the user: (link fedcba9876543210)\n\n"
                    "`````\nrun ````x````\n`````")


BOTH = {"a", "b"}


@pytest.mark.parametrize("source,target,open_sources,ready,expected", [
    (None, row("p2", "b"), set(), BOTH, "that session has gone"),
    (row("p1", "a"), None, set(), BOTH, "that session has gone"),
    (row("p1", "a"), row("p1", "a"), set(), BOTH, "a card cannot link to itself"),
    (row("p1", "a"), row("p9", "a"), set(), BOTH, "a card cannot link to itself"),
    (row("p1", "a"), row("p2", "b", depth=1), set(), BOTH, "teammates cannot be linked"),
    (row("p1", "a"), row("p2", "b", worktree_of="p1"), set(), BOTH, "a worktree cannot link to its own session"),
    (row("p1", "a", worktree_of="p3"), row("p2", "b", worktree_of="p3"), set(), BOTH,
     "a worktree cannot link to its own session"),
    (row("p1", "a", provider=None), row("p2", "b"), set(), BOTH, "only Claude, Codex and omp sessions can link"),
    (row("p1", "a"), row("p2", None, label="bravo"), set(), BOTH, "“bravo” is not known to the panel yet"),
    (row("p1", "a"), row("p2", "../x", label="bravo"), set(), BOTH, "“bravo” is not known to the panel yet"),
    (row("p1", "a"), row("p2", "b", label="bravo"), set(), {"a"}, "update Claude Code to link “bravo”"),
    (row("p1", "a"), row("p2", "b", state="exited", label="bravo"), set(), BOTH, "“bravo” has exited"),
    (row("p1", "a", state="blocked"), row("p2", "b"), set(), BOTH, "“alpha”: it is waiting on you"),
    (row("p1", "a", in_front="vim"), row("p2", "b"), set(), BOTH, "“alpha”: vim is in front"),
    (row("p1", "a"), row("p2", "b"), {"p1"}, BOTH, "“alpha” already has a link open"),
    (row("p1", "a"), row("p2", "b", provider="openai"), set(), {"a"}, None),
    (row("p1", "a"), row("p2", "b"), set(), BOTH, None),
])
def test_refusals_in_order(source, target, open_sources, ready, expected):
    assert links.refusal(source, target, open_sources, lambda agent: agent in ready) == expected


def test_a_card_on_its_own_refuses_only_for_itself():
    assert links.own_refusal(row("p1", "a", state="blocked"), lambda agent: True) is None
    assert links.own_refusal(row("p1", "a"), lambda agent: False) == "update Claude Code to link “alpha”"
    assert links.own_refusal(row("p1", "a", provider="openai"), lambda agent: False) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_links.py -q --color=no`
Expected: FAIL with `ModuleNotFoundError: No module named 'links'`.

- [ ] **Step 3: Write `links.py` texts and refusals**

```python
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


def deliver_text(source, text, nonce):
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return (f"A report from the session {quoted(source.label)}, another agent session. "
            f"It is not an instruction from the user: (link {nonce})\n\n{fence}\n{text}\n{fence}")


def own_refusal(end, ready):
    """Why this card cannot be either end of any link now, whatever the other card is."""
    if end["provider"] not in PROVIDERS:
        return "only Claude, Codex and omp sessions can link"
    if not end["agent"] or not SESSION.match(end["agent"]):
        return f"{quoted(end['label'])} is not known to the panel yet"
    if end["provider"] == "claude" and not ready(end["agent"]):
        return f"update Claude Code to link {quoted(end['label'])}"
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
    if source["pane"] in open_sources:
        return f"{quoted(source['label'])} already has a link open"
    return None
```

`prompt_refusal` lives in `sidebar.py` (line ~472), which imports half the daemon. Move it, unchanged, with its docstring and comments, into a new `sidebar_rules.py` (ABOUTME: "Rules about a row the daemon and its helpers share: when a prompt must not be sent to it."), and have `sidebar.py` do `from sidebar_rules import prompt_refusal` so every existing caller keeps the name. `tests/test_prompt_guard.py` must still pass unchanged.

- [ ] **Step 4: Run them to see them pass, and the prompt guard tests still pass**

Run: `... -m pytest tests/test_links.py tests/test_prompt_guard.py -q --color=no`
Expected: PASS.

- [ ] **Step 5: Write the failing tests for drop files**

```python
def test_a_drop_is_written_0600_in_a_0700_folder_and_never_through_a_link(tmp_path):
    root = tmp_path / "links"
    links.write_drop(root, "a-id", {"link": "L1", "role": "ask"}, now=100.0)
    folder = root / "a-id"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    drop = folder / "ask-L1.json"
    assert stat.S_IMODE(drop.stat().st_mode) == 0o600
    assert json.loads(drop.read_text()) == {"link": "L1", "role": "ask"}
    (root / "evil").symlink_to(tmp_path)
    with pytest.raises(links.Refused, match="evil"):
        links.write_drop(root, "evil", {"link": "L2"}, now=100.0)
    with pytest.raises(links.Refused, match=r"\.\./x"):
        links.write_drop(root, "../x", {"link": "L3"}, now=100.0)


def test_a_marker_is_read_once_written_and_skipped_while_half_written(tmp_path):
    root = tmp_path / "links"
    folder = root / "a-id"
    folder.mkdir(parents=True, mode=0o700)
    assert links.read_marker(root, "a-id", "result", "L1") is None
    (folder / "result-L1.json").write_text('{"link": "L1", "te')
    assert links.read_marker(root, "a-id", "result", "L1") is None
    (folder / "result-L1.json").write_text('{"link": "L1", "text": "done"}')
    assert links.read_marker(root, "a-id", "result", "L1") == {"link": "L1", "text": "done"}


def test_ready_needs_the_session_named_and_a_fresh_file(tmp_path):
    root = tmp_path / "links"
    folder = root / "a-id"
    folder.mkdir(parents=True, mode=0o700)
    (folder / "ready").write_text("a-id")
    os.utime(folder / "ready", (1000.0, 1000.0))
    assert links.is_ready(root, "a-id", now=1059.0)
    assert not links.is_ready(root, "a-id", now=1061.0)
    (folder / "ready").write_text("other")
    os.utime(folder / "ready", (1000.0, 1000.0))
    assert not links.is_ready(root, "a-id", now=1001.0)
```

- [ ] **Step 6: Run them to see them fail**

Run: `... -m pytest tests/test_links.py -q --color=no -k "drop or marker or ready"`
Expected: FAIL with `AttributeError: module 'links' has no attribute 'write_drop'`.

- [ ] **Step 7: Write the drop helpers**

```python
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


def write_drop(root, agent, payload, now):
    """Writes ask-‹link›.json for an agent: a staged file opened O_EXCL|O_NOFOLLOW, then renamed."""
    folder = session_dir(root, agent, make=True)
    staged = folder / f".ask-{payload['link']}.{os.getpid()}"
    staged.unlink(missing_ok=True)
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        json.dump(payload, out)
    os.replace(staged, folder / f"ask-{payload['link']}.json")


def read_marker(root, agent, kind, link_id):
    """kind-‹link›.json from the agent's folder as a dict, or None when absent or not yet whole."""
    try:
        folder = session_dir(root, agent)
        descriptor = os.open(folder / f"{kind}-{link_id}.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (Refused, FileNotFoundError):
        return None
    with os.fdopen(descriptor, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MARKER_MAX:
            return None
        try:
            value = json.loads(f.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return value if isinstance(value, dict) else None


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
    for kind in ("ask", "taken", "started", "result", "failed"):
        (folder / f"{kind}-{link_id}.json").unlink(missing_ok=True)
```

- [ ] **Step 8: Run them to see them pass**

Run: `... -m pytest tests/test_links.py -q --color=no`
Expected: PASS.

- [ ] **Step 9: Write the failing tests for the book's life**

```python
def ends(source_provider="claude", target_provider="claude"):
    return (links.End("p1", "a-id", source_provider, "alpha", rollout="/r/a.jsonl" if source_provider == "openai" else None),
            links.End("p2", "b-id", target_provider, "bravo"))


def test_open_writes_the_ask_into_a_folder_and_the_frame_says_asked(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    drop = json.loads((tmp_path / "a-id" / f"ask-{link.id}.json").read_text())
    assert drop == {"link": link.id, "nonce": link.nonce, "role": "ask", "from": "alpha", "to": "bravo",
                    "text": links.ask_text(link.target, link.nonce), "expires": 1000.0 + 1800}
    assert len(link.id) == 32 and len(link.nonce) == 16
    assert book.frames() == [{"id": link.id, "from": "p1", "to": "p2", "from_label": "alpha", "to_label": "bravo",
                              "state": "asked", "reason": None, "waits": None}]
    assert book.sources() == {"p1"}


def test_a_claude_result_is_delivered_to_b_then_b_starting_makes_it_delivered(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (tmp_path / "a-id" / f"result-{link.id}.json").write_text(json.dumps({"link": link.id, "nonce": link.nonce, "text": "done X"}))
    assert book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None) == [f"link {link.id[:8]} sent"]
    deliver = json.loads((tmp_path / "b-id" / f"ask-{link.id}.json").read_text())
    assert deliver["role"] == "deliver" and deliver["text"] == links.deliver_text(link.source, "done X", link.nonce)
    (tmp_path / "b-id" / f"started-{link.id}.json").write_text("{}")
    assert book.step(1002.0, {"a-id", "b-id"}, lambda r, n: None) == [f"link {link.id[:8]} delivered"]
    assert book.frames()[0]["state"] == "delivered"
    book.step(1012.5, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames() == [] and list((tmp_path / "b-id").iterdir()) == []


def test_a_codex_reply_is_read_from_the_rollout_only_after_the_hook_took_the_ask(tmp_path):
    book = links.Book(tmp_path)
    link = book.open(*ends("openai"), now=1000.0)
    seen = []
    reply = lambda rollout, nonce: seen.append((rollout, nonce)) or "codex says"
    assert book.step(1001.0, {"a-id", "b-id"}, reply) == []
    assert seen == []
    assert book.frames()[0]["waits"] == "p1"
    os.rename(tmp_path / "a-id" / f"ask-{link.id}.json", tmp_path / "a-id" / f"taken-{link.id}.json")
    assert book.step(1002.0, {"a-id", "b-id"}, reply) == [f"link {link.id[:8]} sent"]
    assert seen == [("/r/a.jsonl", link.nonce)]


@pytest.mark.parametrize("marker,expected", [
    ({"failed": {"reason": "the turn was interrupted"}}, "the turn was interrupted"),
    ({"result": {"nonce": "wrong", "text": "x"}}, "the result did not match the link"),
    ({"result": {"text": "y" * 16001}}, "the result was longer than 16000 characters"),
    ({"result": {"text": "  "}}, "the turn ended without an answer"),
])
def test_a_bad_or_failed_result_refuses_the_link(tmp_path, marker, expected):
    book = links.Book(tmp_path)
    link = book.open(*ends(), now=1000.0)
    (kind, body), = marker.items()
    body = {"link": link.id, "nonce": link.nonce, **body}
    (tmp_path / "a-id" / f"{kind}-{link.id}.json").write_text(json.dumps(body))
    book.step(1001.0, {"a-id", "b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", expected)
    assert not (tmp_path / "b-id" / f"ask-{link.id}.json").exists()


def test_an_untaken_ask_expires_and_its_drop_is_removed_but_a_taken_one_waits(tmp_path):
    book = links.Book(tmp_path)
    first = book.open(*ends(), now=1000.0)
    book.step(2801.0, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames()[0]["state"] == "expired"
    assert not (tmp_path / "a-id" / f"ask-{first.id}.json").exists()
    book = links.Book(tmp_path)
    second = book.open(*ends(), now=1000.0)
    os.rename(tmp_path / "a-id" / f"ask-{second.id}.json", tmp_path / "a-id" / f"taken-{second.id}.json")
    book.step(2801.0, {"a-id", "b-id"}, lambda r, n: None)
    assert book.frames()[0]["state"] == "asked"


def test_a_source_that_goes_away_refuses_its_link(tmp_path):
    book = links.Book(tmp_path)
    book.open(*ends(), now=1000.0)
    book.step(1001.0, {"b-id"}, lambda r, n: None)
    assert (book.frames()[0]["state"], book.frames()[0]["reason"]) == ("refused", "“alpha” has gone")
```

- [ ] **Step 10: Run them to see them fail**

Run: `... -m pytest tests/test_links.py -q --color=no -k "open or result or codex or expire or goes"`
Expected: FAIL with `AttributeError: module 'links' has no attribute 'Book'`.

- [ ] **Step 11: Write the book**

```python
class Book:
    """The open links, in memory. A daemon restart forgets them; a drop left behind carries its own expiry."""

    def __init__(self, root=LINKS_DIR):
        self.root = Path(root)
        self.links = {}

    def open(self, source, target, now):
        link = Link(secrets.token_hex(16), secrets.token_hex(8), source, target, now)
        write_drop(self.root, source.agent, {
            "link": link.id, "nonce": link.nonce, "role": "ask", "from": source.label, "to": target.label,
            "text": ask_text(target, link.nonce), "expires": now + EXPIRE_SECONDS}, now)
        self.links[link.id] = link
        return link

    def sources(self):
        return {link.source.pane for link in self.links.values() if link.state not in FINAL}

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
                if read_marker(self.root, link.target.agent, "started", link.id) is not None:
                    said.append(self._end(link, "delivered", None, now))
                elif self._expired(link, link.target.agent, now):
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
            "to": link.target.label, "text": deliver_text(link.source, text, link.nonce),
            "expires": now + EXPIRE_SECONDS}, now)
        link.state = "sent"
        return [f"link {link.id[:8]} sent"]
```

- [ ] **Step 12: Run the whole file and the full suite**

Run: `... -m pytest tests/test_links.py -q --color=no` then the full suite.
Expected: PASS; full suite count = previous 1310 + the new tests, `pytest_exit=0`.

- [ ] **Step 13: Commit**

```bash
git add links.py sidebar_rules.py sidebar.py tests/test_links.py
git commit -m "The book of links: refusals, the ask and delivery texts, drop files in each agent's own folder"
```

---

### Task 2: Mutation check of the book

**Files:** none changed; a scratch script in the session scratchpad.

- [ ] **Step 1:** For each of these single-line mutants of `links.py`, apply it, run `tests/test_links.py`, confirm FAIL, restore (keep `PYTHONDONTWRITEBYTECODE=1`; judge by exit code with `--color=no`):
  1. `quoted`: drop `.replace("`", "'")`.
  2. `deliver_text`: `max(3, longest + 1)` → `3`.
  3. `refusal`: remove the `source["agent"] == target["agent"]` clause.
  4. `session_dir`: remove the `is_symlink()` check.
  5. `_asked`: skip the `taken` check for openai.
  6. `_expired`: drop `not taken and`.
  7. `_deliver`: drop the nonce comparison.
- [ ] **Step 2:** Any mutant that survives gets a sharper test in `tests/test_links.py`, watched failing against the mutant first. Commit only test changes: `git commit -m "Links tests catch every mutant of the book"` (skip the commit if none were needed).

---

### Task 3: A Codex A's reply from its rollout (`codex.py`)

**Files:**
- Modify: `codex.py` (after `_tail_lines`, ~line 171)
- Test: `tests/test_codex.py`

**Interfaces:**
- Produces: `codex.asked_reply(rollout_path: str | None, nonce: str) -> str | None`: `None` until the asked turn completes; its `last_agent_message` (possibly `""`) once it does.

- [ ] **Step 1: Write the failing tests**

```python
def rollout_lines(*items):
    return "\n".join(json.dumps(item) for item in items) + "\n"


def turn(turn_id, developer_text, answer, filler=0):
    yield {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn_id}}
    yield {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                 "content": [{"type": "input_text", "text": developer_text}]}}
    for _ in range(filler):
        yield {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "x" * 1000}]}}
    if answer is not None:
        yield {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": turn_id, "last_agent_message": answer}}


def test_the_asked_reply_is_the_last_message_of_the_turn_whose_context_carries_the_nonce(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t1", "Task line ...", "earlier"),
                                  *turn("t2", "Write your latest result ... (link 00aa11bb22cc33dd)", "the result", filler=300),
                                  *turn("t3", "Task line ...", "later")))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") == "the result"


def test_no_reply_until_the_asked_turn_completes_and_none_for_another_nonce(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t2", "... (link 00aa11bb22cc33dd)", None)))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") is None
    assert codex.asked_reply(str(path), "ffffffffffffffff") is None
    assert codex.asked_reply(None, "00aa11bb22cc33dd") is None
    assert codex.asked_reply(str(tmp_path / "missing.jsonl"), "00aa11bb22cc33dd") is None


def test_an_empty_last_message_is_returned_empty_for_the_book_to_refuse(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(rollout_lines(*turn("t2", "(link 00aa11bb22cc33dd)", None),
                                  {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "t2",
                                                                    "last_agent_message": None}}))
    assert codex.asked_reply(str(path), "00aa11bb22cc33dd") == ""
```

(The filler of 300 reasoning items of ~1 KB puts the asked turn ~300 KiB back, past `TAIL_BYTES`.)

- [ ] **Step 2: Run them to see them fail**

Run: `... -m pytest tests/test_codex.py -q --color=no -k asked_reply`
Expected: FAIL with `AttributeError: module 'codex' has no attribute 'asked_reply'`.

- [ ] **Step 3: Implement**

```python
#: How far back the asked turn is looked for: a long turn of tool output can
#: push its opening context well past the tail the limits read.
REPLY_TAIL_BYTES = 4 * 1024 * 1024


def asked_reply(rollout_path, nonce):
    """The final agent message of the turn whose hook context carried `(link ‹nonce›)`.

    None while that turn has not completed (or cannot be found); its
    last_agent_message, "" when it had none, once it has.
    """
    if not rollout_path:
        return None
    try:
        lines = _tail_lines(rollout_path, REPLY_TAIL_BYTES)
    except OSError:
        return None
    mark = f"(link {nonce})"
    current = asked = None
    for line in lines:
        event = _event(line)
        if event is None:
            continue
        payload = event["payload"]
        kind = payload.get("type")
        if kind == "task_started":
            current = payload.get("turn_id")
        elif kind == "message" and payload.get("role") == "developer" and asked is None:
            if any(mark in str(part.get("text") or "") for part in payload.get("content") or []):
                asked = current
        elif kind == "task_complete" and asked is not None and payload.get("turn_id") == asked:
            return payload.get("last_agent_message") or ""
    return None
```

Change `_tail_lines(path)` to `_tail_lines(path, size=TAIL_BYTES)` and seek with `size`; callers stay as they are. Confirm `_event` returns `None` for a non-JSON line (read it at `codex.py:185`); if it raises instead, catch `ValueError` around it here.

- [ ] **Step 4: Run them to see them pass; full `tests/test_codex.py` passes**

- [ ] **Step 5: Commit**

```bash
git add codex.py tests/test_codex.py
git commit -m "A Codex hand-off's reply is read from its own rollout, by the nonce in the turn's hook context"
```

---

### Task 4: The Codex hook takes asks and deliveries (`emit-state.py`)

**Files:**
- Modify: `plugin/hooks-handlers/emit-state.py` (constants near `STATE_DIR` line 72; `main()` tail line ~1160)
- Test: `tests/test_emit_state.py`

**Interfaces:**
- Produces: `emit_state.LINKS_DIR` (same path as `links.LINKS_DIR`), `emit_state.link_context(session_id: str, now: float, root=None) -> str | None`.
- Consumes: the drop shape from Task 1 (`link`, `nonce`, `role`, `text`, `expires`).

- [ ] **Step 1: Write the failing tests**

```python
def drop(folder, link, role, text, expires=2000.0):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / f"ask-{link}.json").write_text(json.dumps(
        {"link": link, "nonce": "n" * 16, "role": role, "text": text, "expires": expires}))


def test_a_codex_prompt_takes_its_asks_and_deliveries_once(tmp_path):
    folder = tmp_path / "s1"
    drop(folder, "L1", "ask", "Write your latest result ... (link nnnn)")
    drop(folder, "L2", "deliver", "A report from ... (link nnnn)")
    text = emit_state.link_context("s1", 1000.0, root=tmp_path)
    assert text == "Write your latest result ... (link nnnn)\n\nA report from ... (link nnnn)"
    assert sorted(p.name for p in folder.iterdir()) == ["started-L2.json", "taken-L1.json", "taken-L2.json"]
    assert emit_state.link_context("s1", 1001.0, root=tmp_path) is None


def test_an_expired_or_unreadable_drop_is_left_for_the_daemon(tmp_path):
    folder = tmp_path / "s1"
    drop(folder, "L1", "ask", "late", expires=999.0)
    (folder / "ask-L2.json").write_text('{"link": "L2", "ro')
    assert emit_state.link_context("s1", 1000.0, root=tmp_path) is None
    assert sorted(p.name for p in folder.iterdir()) == ["ask-L1.json", "ask-L2.json"]


def test_no_folder_or_a_bad_session_id_gives_nothing(tmp_path):
    assert emit_state.link_context("s1", 1000.0, root=tmp_path) is None
    assert emit_state.link_context("../x", 1000.0, root=tmp_path) is None
```

And a full-run test with the existing `run_handler(home, args, payload, env=None)` (test_emit_state.py:803): a Codex `UserPromptSubmit` with a drop in `home/.claude/agents-sidebar-links/<session>/` returns stdout whose `additionalContext` ends with the drop's text after the task-line text. Write it following the nearest existing `run_handler` Codex test in that file, asserting the exact `additionalContext` string.

- [ ] **Step 2: Run them to see them fail** (`AttributeError: ... 'link_context'`).

- [ ] **Step 3: Implement**

```python
#: Linked cards: the panel drops a link's ask or delivery in the agent's own
#: folder here; a Codex hook takes it on the next prompt. Hooks run outside
#: Codex's sandbox, the commands its model runs do not, and this root is not
#: one of their writable roots.
LINKS_DIR = os.path.expanduser("~/.claude/agents-sidebar-links")


def link_context(session_id, now, root=None):
    """The texts of this session's link drops, each taken once by renaming it, or None."""
    if not session_id or not _SESSION.match(session_id):
        return None
    folder = os.path.join(root or LINKS_DIR, session_id)
    try:
        names = sorted(n for n in os.listdir(folder) if n.startswith("ask-") and n.endswith(".json"))
    except OSError:
        return None
    texts = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as fh:
                drop = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(drop, dict) or not isinstance(drop.get("text"), str) or drop.get("expires", 0) < now:
            continue
        link = name[len("ask-"):-len(".json")]
        try:
            os.rename(path, os.path.join(folder, f"taken-{link}.json"))
        except OSError:
            continue
        if drop.get("role") == "deliver":
            with open(os.path.join(folder, f"started-{link}.json"), "w", encoding="utf-8") as fh:
                fh.write("{}")
        texts.append(drop["text"])
    return "\n\n".join(texts) or None
```

Use the module's existing id pattern name (`_SESSION`, line ~494). In `main()`, after `context = whisper(...)`:

```python
    if codex and event == "UserPromptSubmit":
        linked = link_context(session_id, time.time())
        if linked:
            context = f"{context}\n\n{linked}" if context else linked
```

- [ ] **Step 4: Run them to see them pass; full `tests/test_emit_state.py` passes**
- [ ] **Step 5: Commit**: `git commit -m "A Codex prompt takes the session's link asks and deliveries as hook context, each once"`

---

### Task 5: The omp extension takes asks, deliveries and the asked reply

**Files:**
- Modify: `plugin/omp/agents-sidebar.ts` (`register` at line 325, `EVENTS` at 309)
- Test: `plugin/omp/agents-sidebar.test.ts` (run `bun test` in `plugin/omp`; `tests/test_omp_extension.py` runs it)

**Interfaces:**
- Produces: `register(pi, env, run, pid, linksDir = LINKS_DIR)`; a `before_agent_start` handler returning `{ message: { customType: "agents-sidebar-link", content, display: true } }` when drops were taken; on the asked loop's `agent_end` without `willContinue`, `result-‹link›.json` `{link, nonce, text}` or `failed-‹link›.json` `{link, reason}` written by temp-then-rename.

- [ ] **Step 1: Write the failing tests** (in the existing `describe` style, with the file's `ompHost()` fake, which returns `{pi, fire}`):

```ts
describe("links", () => {
  const nonce = "0123456789abcdef";
  const setup = () => {
    const root = mkdtempSync(join(tmpdir(), "links-"));
    const host = ompHost();
    register(host.pi, {}, async () => {}, 4242, root);
    return { root, host, folder: join(root, "omp-session-1") };
  };
  const dropFile = (folder: string, link: string, role: string, expires = Date.now() / 1000 + 60) => {
    mkdirSync(folder, { recursive: true, mode: 0o700 });
    writeFileSync(join(folder, `ask-${link}.json`), JSON.stringify({ link, nonce, role, text: `${role} text (link ${nonce})`, expires }));
  };

  test("an ask joins the next prompt once and its loop's reply is the result", async () => {
    const { host, folder } = setup();
    await host.fire("session_start", {});
    dropFile(folder, "L1", "ask");
    const added = await host.fire("before_agent_start", { prompt: "hi" });
    expect(added).toEqual({ message: { customType: "agents-sidebar-link", content: `ask text (link ${nonce})`, display: true } });
    expect(await host.fire("before_agent_start", { prompt: "again" })).toBeUndefined();
    await host.fire("agent_end", { messages: [{ role: "assistant", content: [{ type: "text", text: "the result" }] }], willContinue: true });
    expect(existsSync(join(folder, "result-L1.json"))).toBe(false);
    await host.fire("agent_end", { messages: [{ role: "assistant", content: [{ type: "text", text: "the result" }] }] });
    expect(JSON.parse(readFileSync(join(folder, "result-L1.json"), "utf8"))).toEqual({ link: "L1", nonce, text: "the result" });
  });

  test("a delivery joins the prompt and marks started; an empty reply fails the ask", async () => {
    const { host, folder } = setup();
    await host.fire("session_start", {});
    dropFile(folder, "L2", "deliver");
    await host.fire("before_agent_start", { prompt: "hi" });
    expect(existsSync(join(folder, "started-L2.json"))).toBe(true);
    dropFile(folder, "L3", "ask");
    await host.fire("before_agent_start", { prompt: "go" });
    await host.fire("agent_end", { messages: [{ role: "assistant", content: [] }] });
    expect(JSON.parse(readFileSync(join(folder, "failed-L3.json"), "utf8"))).toEqual({ link: "L3", reason: "the turn ended without an answer" });
  });

  test("an expired or half-written drop is left alone", async () => {
    const { host, folder } = setup();
    await host.fire("session_start", {});
    dropFile(folder, "L4", "ask", 1);
    writeFileSync(join(folder, "ask-L5.json"), '{"link": "L5", "ro');
    expect(await host.fire("before_agent_start", { prompt: "hi" })).toBeUndefined();
    expect(readdirSync(folder).sort()).toEqual(["ask-L4.json", "ask-L5.json"]);
  });
});
```

The fake's session id must come out as `omp-session-1`; read `ompHost()` in the test file and set its `sessionManager.getSessionId` to that if it differs. `fire` must return the handler's return value; if it does not today, extend the fake to return it.

- [ ] **Step 2: Run them to see them fail** (`cd plugin/omp && bun test`): FAIL, `before_agent_start` returns undefined.

- [ ] **Step 3: Implement** in `agents-sidebar.ts` (imports from `node:fs`, `node:path`, `node:os`):

```ts
/** Linked cards: the panel's drops for this session, in a folder no Codex sandbox can write. */
export const LINKS_DIR = join(homedir(), ".claude", "agents-sidebar-links");
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

type Drop = { link: string; nonce: string; role: string; text: string; expires: number };

/** Takes each unexpired, whole drop once by renaming it ask- to taken-. */
function takeDrops(folder: string, now: number): Drop[] {
  let names: string[];
  try { names = readdirSync(folder).filter(n => n.startsWith("ask-") && n.endsWith(".json")).sort(); }
  catch { return []; }
  const taken: Drop[] = [];
  for (const name of names) {
    let drop: Drop;
    try { drop = JSON.parse(readFileSync(join(folder, name), "utf8")); }
    catch { continue; }
    if (typeof drop?.text !== "string" || typeof drop.link !== "string" || !(drop.expires >= now)) continue;
    try { renameSync(join(folder, name), join(folder, `taken-${drop.link}.json`)); }
    catch { continue; }
    taken.push(drop);
  }
  return taken;
}

function writeWhole(folder: string, name: string, value: unknown): void {
  const staged = join(folder, `.${name}.${process.pid}`);
  writeFileSync(staged, JSON.stringify(value), { mode: 0o600 });
  renameSync(staged, join(folder, name));
}

function lastText(messages: AgentMessage[]): string {
  const last = [...messages].reverse().find(m => m.role === "assistant");
  if (!last) return "";
  if (typeof last.content === "string") return last.content;
  return (last.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("");
}
```

Inside `register(pi, env, run, pid, linksDir = LINKS_DIR)`, alongside the existing `for (const name of EVENTS)` loop (leave `EVENTS` and `handle` as they are):

```ts
  let asked: { folder: string; link: string; nonce: string } | null = null;
  const folderOf = (): string | null => (session && SESSION_ID.test(session) ? join(linksDir, session) : null);
  pi.on("before_agent_start", () => {
    try {
      const folder = folderOf();
      if (!folder) return undefined;
      const drops = takeDrops(folder, Date.now() / 1000);
      if (drops.length === 0) return undefined;
      for (const drop of drops) {
        if (drop.role === "deliver") writeWhole(folder, `started-${drop.link}.json`, {});
        else asked = { folder, link: drop.link, nonce: drop.nonce };
      }
      return { message: { customType: "agents-sidebar-link", content: drops.map(d => d.text).join("\n\n"), display: true } };
    } catch {
      return undefined;
    }
  });
  pi.on("agent_end", (event) => {
    try {
      if (!asked || event.willContinue === true) return undefined;
      const { folder, link, nonce } = asked;
      asked = null;
      const text = lastText(event.messages ?? []);
      if (text.trim()) writeWhole(folder, `result-${link}.json`, { link, nonce, text });
      else writeWhole(folder, `failed-${link}.json`, { link, reason: "the turn ended without an answer" });
    } catch {
      // A throw here reaches omp; the panel's expiry ends the link instead.
    }
    return undefined;
  });
```

`session` is the existing variable `handle` fills; if `pi.on` for an event already in `EVENTS` replaces rather than adds a handler in the fake, register `agent_end` handling inside `handle` instead (read the fake and omp's `api.on` first). Keep `tests/test_omp_extension.py`'s exact file list (no new files in `plugin/omp`).

- [ ] **Step 4: Run them to see them pass**: `cd plugin/omp && bun test`, then `... pytest tests/test_omp_extension.py tests/test_omp_install.py`.
- [ ] **Step 5: Commit**: `git commit -m "omp takes link asks and deliveries on the next prompt and files the asked loop's reply"`

---

### Task 6: The Claude mod (`plugin/hooks/link.tsx`)

**Files:**
- Create: `plugin/hooks/link.tsx`, `plugin/hooks/link.test.ts`
- Modify: `plugin/hooks/hooks.json` (add `"modules": ["./link.tsx"]` beside `"hooks"`)
- Modify: `docs/superpowers/specs/2026-10-07-linked-cards-design.md` §4 "The asked turn" (see Step 5)

**Interfaces:**
- Consumes: drops from Task 1; Claude Code mod API 2.1.292 (types at the `plugin-authoring` skill's `types/claude-code.d.ts`; load the `plugin-authoring` skill before writing).
- Produces, in `~/.claude/agents-sidebar-links/‹$.session.id()›/`: `ready` (the session id as text) each second; `taken-L.json` by `mv`; `started-L.json` when a delivery's turn starts; `result-L.json` `{link, nonce, text}` or `failed-L.json` `{link, reason}` for an ask, each written to a dot-file then `mv`'d.

- [ ] **Step 1: Write the failing `claude plugin test` tests** in `plugin/hooks/link.test.ts`, one behaviour each, using the kit's `test`/`expect`/`mock` from `claude-code/testing` and the mocked clock and fs (read the plugin-authoring reference's "what a test holds" before writing). The behaviours, each with exact expected values:
  1. A tick with an `ask-L1.json` (role ask, unexpired) runs `mv ask-L1.json taken-L1.json` once and submits the drop's text with `$.prompt.submit`; a second tick submits nothing.
  2. A drop whose `expires` is in the past, or whose JSON is cut off, is neither moved nor submitted.
  3. `turn.start` whose text contains `(link ‹nonce›)` followed by `turn.complete` for that `turnId` with no `agentId` and answer `"done"` writes `result-L1.json` = `{"link":"L1","nonce":"‹nonce›","text":"done"}`; a `turn.complete` with an `agentId` (a subagent) writes nothing.
  4. The asked turn completing with `isAborted: true`, or with an answer of `"  "`, writes `failed-L1.json` with reason `"the turn was interrupted"` / `"the turn ended without an answer"`.
  5. A `prompt.submit` with `origin.kind` `"composer"` while the asked turn runs answers `{ drop: "the hand-off is running" }`, calls `$.prompt.fill({ text })` with the typed text and toasts `"the hand-off is running; send this when it ends"`; the same prompt when no asked turn runs passes through `next`.
  6. A delivery drop's turn starting writes `started-L2.json` = `{}`.
  7. `session.start` with a `taken-L9.json` (role ask) and no `result-L9`/`failed-L9` writes `failed-L9.json` reason `"the session reloaded during the hand-off"`.
  8. After `$.session.id()` changes between ticks (a `/clear`), `ready` holding the new id is written under the new id's folder.
  9. The `AbovePrompt` render shows `alpha 🔗 bravo · writing` while the asked turn runs, `· sent` after its result, `bravo`-side `alpha 🔗 bravo · delivered` after a delivery starts, and nothing 10 s after the last state (mocked clock).

- [ ] **Step 2: Run them to see them fail**: `claude plugin test plugin` → FAIL (module missing).

- [ ] **Step 3: Write the module** (helpers that take `$` stay top-level `function` declarations, as `claude plugin validate` requires):

```tsx
// ABOUTME: Linked cards, inside a Claude session: takes the panel's link drops from the session's own folder,
// ABOUTME: submits them as prompts, files the asked turn's reply, and shows the link in a band above the prompt.
import type { Register } from 'claude-code'

const TICK_MS = 1000
const CLEAR_MS = 10_000
const SESSION_ID = /^[A-Za-z0-9][A-Za-z0-9_-]*$/

type Drop = { link: string; nonce: string; role: 'ask' | 'deliver'; text: string; from: string; to: string; expires: number }
type Band = { from: string; to: string; state: 'writing' | 'sent' | 'delivered'; until: number | null }

let folder: string | null = null
let asked: { link: string; nonce: string; turnId: string | null } | null = null
let delivering: { link: string; nonce: string; from: string; to: string } | null = null
let running: string | null = null
let band: Band | null = null

async function succeeded($: any, argv: string[]): Promise<boolean> {
  return (await $.process.run(argv)).exitCode === 0
}

// The session's own folder; the id changes on /clear and on a resume, with no new session.start.
async function folderFor($: any): Promise<string | null> {
  const home = await $.env.get('HOME')
  const id = await $.session.id()
  if (!home || !SESSION_ID.test(id)) return null
  const path = `${home}/.claude/agents-sidebar-links/${id}`
  if (path !== folder) {
    if (!(await succeeded($, ['mkdir', '-m', '700', '-p', path]))) return null
    folder = path
  }
  return path
}

// Written to a dot-file, made 0600, then renamed, so the daemon never reads half a file.
async function writeWhole($: any, name: string, value: unknown): Promise<void> {
  if (!folder) return
  const staged = `${folder}/.${name}`
  await $.fs.write(staged, JSON.stringify(value))
  if (await succeeded($, ['chmod', '600', staged])) await succeeded($, ['mv', staged, `${folder}/${name}`])
}

async function readDrop($: any, path: string): Promise<Drop | null> {
  try {
    const drop = JSON.parse(await $.fs.read(path))
    const whole = drop && typeof drop.text === 'string' && typeof drop.link === 'string' && typeof drop.nonce === 'string'
    return whole ? drop : null
  } catch {
    return null
  }
}

async function tick($: any): Promise<void> {
  const path = await folderFor($)
  if (!path) return
  await $.fs.write(`${path}/ready`, await $.session.id())
  const now = await $.clock.now()
  if (band && band.until !== null && now >= band.until) {
    band = null
    $.ui.invalidate('ui.render')
  }
  for (const entry of await $.fs.list(path)) {
    if (!entry.name.startsWith('ask-') || !entry.name.endsWith('.json')) continue
    const drop = await readDrop($, `${path}/${entry.name}`)
    if (!drop || !(drop.expires * 1000 >= now)) continue
    if (!(await succeeded($, ['mv', `${path}/${entry.name}`, `${path}/taken-${drop.link}.json`]))) continue
    if (drop.role === 'ask') {
      asked = { link: drop.link, nonce: drop.nonce, turnId: null }
      band = { from: drop.from, to: drop.to, state: 'writing', until: null }
    } else {
      delivering = { link: drop.link, nonce: drop.nonce, from: drop.from, to: drop.to }
    }
    $.ui.invalidate('ui.render')
    void $.prompt.submit({ text: drop.text })
  }
}

// A reload forgets the asked turn, so an ask taken before it can never be answered: say so.
async function failTakenAsks($: any): Promise<void> {
  const path = await folderFor($)
  if (!path) return
  const names = new Set<string>((await $.fs.list(path)).map((entry: any) => entry.name))
  for (const name of names) {
    if (!name.startsWith('taken-') || !name.endsWith('.json')) continue
    const link = name.slice('taken-'.length, -'.json'.length)
    if (names.has(`result-${link}.json`) || names.has(`failed-${link}.json`)) continue
    const drop = await readDrop($, `${path}/${name}`)
    if (drop?.role === 'ask') await writeWhole($, `failed-${link}.json`, { link, reason: 'the session reloaded during the hand-off' })
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await failTakenAsks($)
    $.clock.every(TICK_MS, () => { void tick($) })
    return started
  })

  on('turn.start', async ($, e, next) => {
    // A subagent's turn starts inside the running one; the running turn stays the outer one.
    if (running === null) running = e.turnId
    if (asked && asked.turnId === null && e.text.includes(`(link ${asked.nonce})`)) asked.turnId = e.turnId
    if (delivering && e.text.includes(`(link ${delivering.nonce})`)) {
      await writeWhole($, `started-${delivering.link}.json`, {})
      band = { from: delivering.from, to: delivering.to, state: 'delivered', until: (await $.clock.now()) + CLEAR_MS }
      delivering = null
      $.ui.invalidate('ui.render')
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId) return next(e)
    if (e.turnId === running) running = null
    if (asked && asked.turnId === e.turnId) {
      const { link, nonce } = asked
      asked = null
      if (e.isAborted) await writeWhole($, `failed-${link}.json`, { link, reason: 'the turn was interrupted' })
      else if (!e.answer.trim()) await writeWhole($, `failed-${link}.json`, { link, reason: 'the turn ended without an answer' })
      else await writeWhole($, `result-${link}.json`, { link, nonce, text: e.answer })
      if (band) band = { ...band, state: 'sent', until: (await $.clock.now()) + CLEAR_MS }
      $.ui.invalidate('ui.render')
    }
    return next(e)
  })

  // A prompt you type during the hand-off would join its reply; it goes back to the box instead.
  on('prompt.submit', async ($, e, next) => {
    const yours = e.origin.kind === 'composer' || e.origin.kind === 'bridge'
    if (!yours || !asked?.turnId || running !== asked.turnId) return next(e)
    await $.prompt.fill({ text: e.text })
    $.ui.toast('the hand-off is running; send this when it ends')
    return { drop: 'the hand-off is running' }
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, ($, e, next) => {
    if (!band) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text>{`${band.from} 🔗 ${band.to} · ${band.state}`}</Text>
      </Box>
    )
  })
}
```

Check against the types file before running: the `turn.complete` input's `answer`, `isAborted` and `agentId` names, `$.session.id()`, `$.env.get`, `$.process.run(argv)` returning `{exitCode}`, `$.fs.list` entries' `name`, and that a `prompt.submit` hook may return `{ drop }`. If `turn.start` carries an `agentId` for a subagent turn, skip such turns there too. The guard's `.catch` lets your prompt through when the hook fails: losing a prompt is worse than mixing it into a hand-off.

- [ ] **Step 4: Run** `claude plugin test plugin`, `claude plugin validate plugin` (no errors; the existing command-hook quoting warnings stay as they are), and `... pytest tests/` (hooks.json shape tests, if any, still pass). Expected: PASS.

- [ ] **Step 5: Spec line.** §4 "The asked turn" says the mod keeps `{link, turnId}` in `$.state` across a reload; this plan fails a taken ask on reload instead (test 7), which needs no `$.state` contract. Change that paragraph to: "…keeps `{link, nonce, turnId}` in module memory and takes that turn's `turn.complete`… A reload loses that memory, so on `session.start` any `taken-` ask with no result is written `failed-` ("the session reloaded during the hand-off")." In §4 "Ready", change "rewrites `ready` there with its pid and Claude Code version" to "rewrites `ready` there with the session id as plain text (one small write a second, no process started)". Commit with the module.

- [ ] **Step 6: Commit**: `git add plugin/hooks/link.tsx plugin/hooks/link.test.ts plugin/hooks/hooks.json docs/superpowers/specs/2026-10-07-linked-cards-design.md && git commit -m "The link mod: a Claude session takes its link drops, files the asked reply, and shows the link above the prompt"`

---

### Task 7: The daemon: `POST /link`, the book in each rebuild, `links` in the frame

**Files:**
- Modify: `sidebar.py`: `Sidebar.__init__` (2773, add `link_fn=None`), `handle` (2797, route), new `_link`; `Bridge.__init__` (3049, `self.links = links.Book()`), new `Bridge.link_end`, `Bridge.link`, `_rebuild_once` (3340, step + frame); `main()` (3831, wire `link_fn`); `snapshot` rows get `link_refusal`.
- Test: `tests/test_server.py`, `tests/test_rebuild.py`

**Interfaces:**
- Consumes: `links.Book`, `links.End`, `links.refusal`, `links.is_ready`, `codex.asked_reply`.
- Produces: `POST /link?token=…` body `{"from": pane, "to": pane}` → `200 {"ok": true, "link": frame}` | `400 {"error": "a link needs from and to"}` | `409 {"error": reason}`; frame key `links: [ {id, from, to, from_label, to_label, state, reason, waits} ]`; each frame row `link_refusal: str | null` (the reasons that do not depend on the other card: not an agent, not known yet, Claude mod not ready, exited).

- [ ] **Step 1: Failing server tests** (use `record(tmp_path, snapshot)` / `TOKEN` as the file does; add a `link_server(tmp_path, link)` helper like `context_server`):

```python
def test_a_link_route_hands_from_and_to_to_the_bridge(tmp_path):
    seen = []
    server = link_server(tmp_path, lambda source, target: seen.append((source, target)) or {"id": "L"})
    status, _, body = server.handle("POST", f"/link?token={TOKEN}", b'{"from": "p1", "to": "p2"}')
    assert (status, json.loads(body), seen) == (200, {"ok": True, "link": {"id": "L"}}, [("p1", "p2")])


@pytest.mark.parametrize("body", [b"[]", b'{"from": "p1"}', b'{"from": 1, "to": "p2"}', b"not json"])
def test_a_malformed_link_is_refused_400(tmp_path, body):
    server = link_server(tmp_path, lambda s, t: pytest.fail("should not be called"))
    status, _, out = server.handle("POST", f"/link?token={TOKEN}", body)
    assert (status, json.loads(out)) == (400, {"error": "a link needs from and to"})


def test_a_refused_link_is_409_with_the_reason(tmp_path):
    def link(source, target):
        raise links.Refused("“alpha”: it is waiting on you")
    status, _, out = link_server(tmp_path, link).handle("POST", f"/link?token={TOKEN}", b'{"from": "p1", "to": "p2"}')
    assert (status, json.loads(out)) == (409, {"error": "“alpha”: it is waiting on you"})


def test_a_link_without_the_token_is_forbidden(tmp_path):
    status, _, _ = link_server(tmp_path, lambda s, t: {}).handle("POST", "/link?token=wrong", b'{"from": "p1", "to": "p2"}')
    assert status == 403
```

- [ ] **Step 2: Run, see them fail; implement `_link`** (pattern of `_context`):

```python
    def _link(self, body):
        try:
            request = json.loads(body or b"{}")
        except ValueError:
            request = None
        if (not isinstance(request, dict) or not isinstance(request.get("from"), str)
                or not isinstance(request.get("to"), str) or self.link_fn is None):
            return self._json(400, {"error": "a link needs from and to"})
        try:
            return self._json(200, {"ok": True, "link": self.link_fn(request["from"], request["to"])})
        except links.Refused as refusal:
            return self._json(409, {"error": str(refusal)})
```

and in `handle`: `if method == "POST" and path == "/link": return self._link(body)`. Run → PASS.

- [ ] **Step 3: Failing rebuild tests** (in `tests/test_rebuild.py` with its `bridge(monkeypatch, readings)` helper; point `links.LINKS_DIR`-based books at `tmp_path` by constructing `b.links = links.Book(tmp_path / "links")`):
  1. `b.link("p1", "p2")` on two idle Claude rows whose `conversation`s are `a-id`/`b-id` and whose `ready` files are fresh writes `ask-‹id›.json` under `a-id` and returns the frame dict with `state` `"asked"`; on a blocked source it raises `links.Refused("“‹label›”: it is waiting on you")`; a second link from the same source raises `"… already has a link open"`.
  2. After `_rebuild_once`, `b.latest["links"]` equals `b.links.frames()`, and a Claude result file placed under `a-id` moves the link to `"sent"` within one rebuild, with a `daemon.log` line `link ‹id8› sent` (monkeypatch `STATUS_DIR` as the file's other tests do).
  3. A frame row for a Claude pane without a fresh `ready` carries `link_refusal == "update Claude Code to link “‹label›”"`; a ready one carries `None`; a SESSIONS row carries `"only Claude, Codex and omp sessions can link"`.

- [ ] **Step 4: Implement**:

```python
    def link_end(self, pane):
        """One card as a link end: its frame row's facts plus the agent's own session id."""
        frame_row = next((r for g in self.latest.get("groups", []) if g["name"] == "AGENTS"
                          for r in g["rows"] if r["session_id"] == pane), None)
        inner = next((r for r in self.rows if r["session_id"] == pane), None)
        if frame_row is None or inner is None:
            return None
        return {"pane": pane, "agent": inner.get("conversation"), "provider": frame_row.get("provider") or "claude",
                "label": frame_row.get("label") or pane, "state": frame_row.get("state"),
                "depth": frame_row.get("depth", 0), "worktree_of": frame_row.get("worktree_of"),
                "in_front": frame_row.get("in_front"), "rollout": inner.get("rollout")}

    def link(self, source_pane, target_pane):
        source, target = self.link_end(source_pane), self.link_end(target_pane)
        now = time.time()
        reason = links.refusal(source, target, self.links.sources(),
                               lambda agent: links.is_ready(self.links.root, agent, now))
        if reason:
            raise links.Refused(reason)
        end = lambda e: links.End(e["pane"], e["agent"], e["provider"], e["label"], e.get("rollout"))
        made = self.links.open(end(source), end(target), now)
        self.log(f"link {made.id[:8]} asked {source['label']} -> {target['label']}")
        self.latest["links"] = self.links.frames()
        return next(f for f in self.links.frames() if f["id"] == made.id)
```

In `_rebuild_once`, after the `self.alert(...)` line and before `frame = sse_frame(...)`:

```python
        alive = {row.get("conversation") for row in self.rows if row.get("conversation")}
        for line in self.links.step(time.time(), alive, codex.asked_reply):
            self.log(line)
        self.latest["links"] = self.links.frames()
        now = time.time()
        ready = lambda agent: links.is_ready(self.links.root, agent, now)
        for group in self.latest["groups"]:
            for frame_row in group["rows"]:
                end = self.link_end(frame_row["session_id"]) if group["name"] == "AGENTS" else None
                frame_row["link_refusal"] = (links.own_refusal(end, ready) if end
                                             else "only Claude, Codex and omp sessions can link")
```

(Only reasons that hold whatever the other card is go in the frame; a busy or blocked source and an already open link are judged at the drop by `links.refusal`.)

Wire `main()`: `link_fn=lambda source, target: bridge.link(source, target)`; `/link` runs inline (no thread: it touches `self.latest`). Run → PASS; full suite PASS.

- [ ] **Step 5: Commit**: `git commit -m "The daemon opens links on POST /link, steps them each rebuild, and puts them and each card's link refusal in the frame"`

---

### Task 8: The page: arming, Tether, release, card lines

**Files:**
- Modify: `page.html`: drag section (`startDrag` 2592, `moveDrag` 2655, `endDrag` 2683, `cancelDrag` 2705, pointer listeners 2752–2789), CSS near `.drag-ghost` (164), row painting near `refusalLine` use (4169), new `linkLine(row)`.
- Test (local E2E, not committed, as the drag E2Es are): `.cs/local/e2e_link_arm.mjs`; plus `tests/test_page_*.py` static checks where the page tests already pin CSS tokens (contrast of the new line colour, if a new colour is added).

**Interfaces:**
- Consumes: frame `links` and per-row `link_refusal` (Task 7); `POST /link` (Task 7).
- Produces: `ARM_MS = 400`; `dragging.arming = {li, since} | null`, `dragging.armed = li | null`; `postLink(fromPane, toPane)`; an SVG overlay `#link-overlay` (fixed, `pointer-events: none`, `aria-hidden`).

- [ ] **Step 1: Write the E2E first** (`.cs/local/e2e_link_arm.mjs`, modelled on `.cs/local/e2e_drag_order.mjs`: in-page frozen frames via `events.onmessage = () => {}`, `fetch` stubbed for `/link` to record bodies and answer 200 or 409). Checks, each written as a named `check(...)` with exact values:
  1. Holding the ghost over another agent card for 350 ms does not arm (no `.link-target` class, no overlay path); at 450 ms it arms (`.link-target` on the target, one `path` in `#link-overlay`).
  2. While armed, moving within the target keeps the order unchanged (`order()` as before the drag); leaving the target disarms within one move and reordering resumes.
  3. Releasing armed POSTs `/link` once with `{"from": ‹dragged pane›, "to": ‹target pane›}`, restores the original order, and posts no `/settings`.
  4. A target whose row has `link_refusal: "update Claude Code to link “bravo”"` never arms; while hovered past 400 ms, a `.link-refusal` label near the pointer reads exactly that reason.
  5. A 409 answer shows the reason as the dragged card's refusal line for 4 s (the existing `refusedPrompts` path).
  6. A frame with `links: [{from: A, to: B, state: "asked", waits: null, …}]` shows on A's card `Asked to send to “bravo”`; `state: "sent", waits: B` shows `Sent; waits for your next prompt in “bravo”`; `"delivered"` shows `Delivered to “bravo”` on A and `From “alpha”` on B; `"refused", reason: R` shows `Refused: R`; `"expired"` shows `Expired`.
  7. Escape while armed cancels with no POST; a drag that never hovers another card behaves exactly as before (rerun `e2e_drag_order.mjs`: 40/40).
  8. Reduced motion: arming still works, the tether is drawn without the flow animation.

Run it against the current page: the arming checks FAIL (no `.link-target`).

- [ ] **Step 2: Implement arming in the drag.** In `moveDrag`, after the ghost transform:

```js
  const under = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest("#groups li.line.card:not(.worktree):not(.placeholder)");
  const target = under && under.querySelector(":scope > button.row.agent") ? under : null;
  if (!target || target !== dragging.arming?.li) {
    disarm();
    dragging.arming = target ? {li: target, since: performance.now()} : null;
  }
```

A `requestAnimationFrame` loop started in `startDrag` (and stopped in `endDrag`) arms once `performance.now() - dragging.arming.since >= ARM_MS`: if the target row's `link_refusal` is set, show the `.link-refusal` label at the pointer; otherwise set `dragging.armed = li`, add `.link-target`, and draw the Tether (Step 3). While `dragging.armed` is set, `moveDrag` skips the neighbour-stepping loop (reordering pauses) but still moves the ghost. The ghost follows the pointer across the whole list: compute the ghost's translate from the unclamped `grabTop + (event.clientY - grabY) / zoom`, keep the clamped `want` for reordering only.

- [ ] **Step 3: Draw the Tether** (picked from `.cs/local/link-variants.html`, `tether()`): the target and the ghost each get `box-shadow: 0 0 0 1px ‹hue›, 0 0 ‹16·p›px -2px ‹hue›` where `‹hue›` is that session's swatch colour (the colour the card's own mark uses) and `p` eases from 0 to 1 over 450 ms; an SVG path from the ghost's lower edge (6 px above its bottom) to the target's vertical middle, at the panel's right gutter (12 px in from the right edge), `stroke: var(--fg)`, `stroke-opacity: .5`, `stroke-width: 1.5`, drawn in by `stroke-dashoffset` over the same 450 ms, then `stroke-dasharray: 3 5` flowing with `stroke-dashoffset = -(t·30)`. With reduced motion: full glow and a still dashed line at once. No rotation, no popping, no accent bar.

- [ ] **Step 4: Release.** In the `pointerup` listener: `if (dragging) outside ? cancelDrag() : dragging.armed ? linkDrag() : dropDrag();` with:

```js
function linkDrag() {
  const from = cardRow(dragging.block[0]).session_id;
  const to = cardRow(dragging.armed).session_id;
  cancelDrag();
  postLink(from, to);
}

function postLink(from, to) {
  fetch(`/link?token=${encodeURIComponent(TOKEN)}`, {method: "POST", body: JSON.stringify({from, to})})
    .then(r => r.status === 409 ? r.json() : null)
    .then(reply => {
      if (!reply?.error) return;
      refusedPrompts.set(from, {text: reply.error, at: performance.now()});
      render(LATEST, false, true);
    })
    .catch(err => console.log("sidebar: link failed", err));
}
```

Read `prompt()` (line 1776) first and store the refusal exactly as it does (its map value shape may differ from `{text, at}`; match it). `cancelDrag` and `endDrag` must clear the glow, the overlay and the label.

- [ ] **Step 5: Card lines.** `linkLine(row)` returns a `<p class="link-line" role="status">` or null from `LATEST.links`: the texts of E2E check 6, labels through the same curly-quote form the daemon uses (`“‹label›”`), dim like `.refusal` but not alert-coloured; appended where `refusalLine` is (both for top-level cards and teammates). On drop, the target shows `Sent · from “‹A›”` for 2 s (from the variant), then the frame's lines take over.

- [ ] **Step 6: Run** the new E2E (all PASS), `e2e_drag_order.mjs` (40/40), `e2e_menu_still.mjs`, `e2e_card_hold.mjs`, and `... pytest tests/test_page_*.py tests/test_docs.py`. Then mutants: (a) `ARM_MS` → 0, (b) skip the `link_refusal` check, (c) keep reordering while armed, (d) `linkDrag` → `dropDrag`: each must turn at least one E2E check red. WebKit check: render the armed state in WKWebView (`.cs/local/low-dpi/shot1x.swift` pattern) and look at descenders and the glow at 1x.

- [ ] **Step 7: Commit**: `git add page.html tests/ && git commit -m "Hold a dragged card over another to arm a link: the Tether draws, a release asks the daemon, the cards say how it went"`

---

### Task 9: Install, docs, live end-to-end

**Files:**
- Modify: `install.sh` (make `~/.claude/agents-sidebar-links` `0700`; the mod ships inside the `plugin/` copy already), `docs/usage.md` (Linking section), `README.md` (pointer), `docs/integrations.md` (the mod, the drops, the hook context, omp's `before_agent_start`), `docs/development.md` (link this plan under the plans list, after the drag-order plan), `tests/test_docs.py` stays green.
- Live E2E (local, not committed): `.cs/local/e2e_link_live.py`.

- [ ] **Step 1: install.sh**: after the tasks dir line, add `install -d -m 700 "$HOME/.claude/agents-sidebar-links"`. Run `./install.sh` from the branch; restart the daemon (memory `project_plugin-hook-deploy-path`: `pgrep -f 'venvs/3.10/bin/python'`, check exactly one pid, kill it, osascript launch). In a fresh Claude session, `/plugin` shows the mod (`1 mod active` or the plugin's name); this is spec §6 check 2 confirmed live.

- [ ] **Step 2: Live E2E** in scratch iTerm2 windows (pattern of `.cs/local/probe_mod_turns.py`: command in a script file, pane re-looked up by window id, folders inside the repo so they are trusted): for each of Claude → Claude (both `--permission-mode bypassPermissions`, haiku, no setting changed), Claude → Codex, Codex → Claude: A is asked for "the code word ‹random›" set up in its first prompt; POST `/link` with the daemon token from `endpoint.json` (never printed); assert the frame's link reaches `delivered` and B's transcript (Claude: the session JSONL; Codex: its rollout) holds the random word inside the fenced block. Record each run's link id, timings and result in the narrative.

- [ ] **Step 3: Docs.** usage.md "Linking": the gesture (hold 0.4 s over a card, let go), what A writes and B does, the band in Claude sessions, which ends wait for your next prompt (Codex, omp) and the card line saying so, the refusals list (from `links.refusal`), a prompt typed in A during the hand-off going back to the box, the trust note (B acts on A's report with B's permissions), and that linking needs Claude Code ≥ 2.1.287 with mods on. Run the docs audit rule (memory `feedback_release-docs-audit`) on every changed doc, and Vale on the new prose.

- [ ] **Step 4: Full suite, `bun test`, `claude plugin test plugin`, all E2Es; commit**: `git commit -m "Linking: install makes the links folder, docs describe the gesture, routes, band and refusals"`

- [ ] **Step 5: Whole-branch review** by a fresh reviewer on the most capable model, given the spec and the diff (not this plan's reasoning); fix findings test-first; then ask for the merge.
