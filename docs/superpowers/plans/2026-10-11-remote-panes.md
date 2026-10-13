# Remote Panes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pane that runs `ssh host` or `et host` shows an honest card for the Claude session on the other machine (state, timers, host, folder, standing question with answer buttons), and a remote tmux pane never wears a local session's identity.

**Architecture:** The hook (`plugin/hooks-handlers/emit-state.py`) adds `host`, `front` and `cwd` to the state it writes on the pane and carries a standing question in a second user variable. The daemon (`sidebar.py`) reads each tab's tmux server through iTerm2, treats a state from another host as remote (no local process, file or git lookups), and types into a remote pane through one chokepoint that allows a single key under four checks. The page draws a host mark.

**Tech Stack:** Python 3 stdlib (hook and daemon), iTerm2 Python API, plain JS page, pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-remote-panes-design.md` (approved; checks measured at f5ce203, limits at 025ac0e). Read it before any task.

## Global Constraints

- Build on a new branch `feat/remote-panes` off `spec/remote-panes`.
- Nothing connects to the other machine. Everything travels in the pane's byte stream. No screen is read for state.
- `VARIABLE_CEILING` stays 512 bytes of base64. The envelope is written without spaces (`separators=(",", ":")`).
- The host name is `socket.gethostname()` up to its first dot, derived the same way in hook and daemon; the daemon reads its own at every rebuild.
- `TRANSPORTS = frozenset({"ssh", "et"})`.
- The question variable is `user.claudeQuestion`; it carries `since`, equal to the envelope's `blocked_since`.
- A remote row is never asked of the local process table, never has a local file opened by its path or pid, and never has its host or path used to build a command.
- Into a remote pane the daemon types one key that is not Enter, and only when: the transport is in front here, the envelope's `front` is true, the pane's `autoName` starts with `AGENT_TITLE_MARKER`, and the row's state is "blocked".
- Refusal wording, exact: "replies do not reach a remote session yet"; "the connection to ‹host› is not in front here"; "something is in front of the agent on ‹host›"; "the agent's title has gone from the pane"; "it is not waiting on you"; "a remote session cannot be linked yet".
- The frame row fields are `host` (string) and `remote_refusal` (string or absent). The existing `remote` field belongs to Remote Control and is not touched; the page's mark class is `host-mark`.
- The task-line instructions are added to a prompt only where `~/.local/share/agents-sidebar/endpoint.json` exists.
- Python tests: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/ -q --color=no` (Homebrew python lacks pytest-asyncio; judge by the exit code).
- Every new code file starts with two `ABOUTME:` lines. No emoji. Docs, specs and plans name no person and no real host. Never name another sidebar tool.
- Live scripts take the other machine from the environment (`REMOTE=user@host`) and are session files under `.cs/local/`, not committed.

## Review Focus

1. **A remote pid that equals a live local pid.** The row must not take that process's status line, shells, usage, colour or start time (test in Task 4: a remote state whose pid is in the local listing).
2. **A notice's Reply or a raw `send` into a remote pane.** Both end in Enter or carry text; the chokepoint must refuse them even though no card button sends them (tests in Task 5).
3. **A question variable left from an earlier question.** Its `since` differs from the envelope's `blocked_since`; no buttons may show (test in Task 4).
4. **A remote folder that also exists here** (`/private/tmp`, `/usr/local`). No branch, colour, worktree or `/context` read may run on it (test in Task 4).
5. **A tmux connection that could not be read.** Its panes must fall back to what iTerm2 reports, never to the local table (test in Task 1).
6. **A slow or dead link to a remote tmux server.** It must not delay local cards: connections are asked together, each under one second (test in Task 1).

---

### Task 1: tmux panes, per connection

**Files:**
- Modify: `sidebar.py` (`parse_tmux_panes` neighbours near line 1842; `Bridge.read_sessions` near line 3200)
- Modify: `tests/test_foreground.py`, `tests/test_rebuild.py`

**Interfaces:**
- Consumes: `parse_tmux_panes(out)`, `read_system()` (unchanged: its second element stays the local server's `{pane number: {job, path, tty}}`), `iterm2.async_get_tmux_connections`, `TmuxConnection.async_send_command`, `Tab.tmux_connection_id`.
- Produces:
  - `TMUX_TABLE_COMMAND = "list-panes -a -F '#{host_short} #{pane_id} #{pane_tty} #{pane_current_path}'"`, `TMUX_TABLE_SECONDS = 1`
  - `parse_tmux_table(out) -> {"host": str | None, "panes": {int: {"tty": str, "path": str | None}}}`
  - `tmux_pane(connection_id, tables, number, here, local_panes) -> dict` (`{}`, a local pane's `{job, path, tty}`, or a foreign pane's `{"path": ..., "host": ...}`)
  - `local_host() -> str`
  - `async Bridge.read_tmux_tables(ids) -> {connection id: table}` (a connection that could not be read is absent)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_foreground.py`)

```python
def test_a_tmux_table_names_its_host_and_its_panes():
    out = ("box %0 /dev/ttys001 /private/tmp\n"
           "box %4 /dev/ttys005 /srv/My App\n\ngarbage\n")
    assert sidebar.parse_tmux_table(out) == {
        "host": "box",
        "panes": {0: {"tty": "ttys001", "path": "/private/tmp"},
                  4: {"tty": "ttys005", "path": "/srv/My App"}}}


def test_a_tmux_table_with_no_pane_names_no_host():
    assert sidebar.parse_tmux_table("") == {"host": None, "panes": {}}


LOCAL_PANES = {4: {"job": "claude", "path": "/Users/x/atlas", "tty": "ttys004"}}
TABLES = {"here": {"host": "desk", "panes": {4: {"tty": "ttys004", "path": "/Users/x/atlas"}}},
          "there": {"host": "box", "panes": {4: {"tty": "ttys005", "path": "/srv/app"}}}}


def test_a_pane_of_a_tmux_server_on_this_machine_is_the_local_pane():
    assert sidebar.tmux_pane("here", TABLES, 4, "desk", LOCAL_PANES) == LOCAL_PANES[4]


def test_a_pane_of_a_tmux_server_elsewhere_never_takes_the_local_pane_of_its_number():
    assert sidebar.tmux_pane("there", TABLES, 4, "desk", LOCAL_PANES) == {"path": "/srv/app", "host": "box"}


def test_a_pane_of_a_connection_that_was_not_read_is_left_to_iterm2():
    assert sidebar.tmux_pane("lost", TABLES, 4, "desk", LOCAL_PANES) == {}


def test_a_session_outside_tmux_has_no_pane():
    assert sidebar.tmux_pane(None, TABLES, None, "desk", LOCAL_PANES) == {}


def test_a_tmux_session_whose_tab_names_no_connection_is_the_local_pane():
    assert sidebar.tmux_pane(None, {}, 4, "desk", LOCAL_PANES) == LOCAL_PANES[4]


def test_a_foreign_pane_the_table_does_not_list_has_a_host_and_no_path():
    assert sidebar.tmux_pane("there", TABLES, 9, "desk", LOCAL_PANES) == {"path": None, "host": "box"}


def test_this_machines_name_stops_at_its_first_dot(monkeypatch):
    monkeypatch.setattr(sidebar.socket, "gethostname", lambda: "desk.example.com")
    assert sidebar.local_host() == "desk"
```

```python
def test_a_tmux_server_that_does_not_answer_holds_the_others_up_no_longer_than_its_limit(monkeypatch):
    class Connection:
        def __init__(self, connection_id, answer):
            self.connection_id, self.answer = connection_id, answer

        async def async_send_command(self, command):
            if self.answer is None:
                await asyncio.sleep(60)
            return self.answer

    async def connections(_):
        return [Connection("slow", None), Connection("here", "desk %4 /dev/ttys004 /Users/x/atlas\n")]
    b = bridge(monkeypatch, [])
    monkeypatch.setitem(sys.modules, "iterm2", types.SimpleNamespace(async_get_tmux_connections=connections))
    monkeypatch.setattr(sidebar, "TMUX_TABLE_SECONDS", 0.05)
    began = time.monotonic()
    tables = asyncio.run(b.read_tmux_tables({"slow", "here"}))
    assert time.monotonic() - began < 1
    assert tables == {"here": {"host": "desk", "panes": {4: {"tty": "ttys004", "path": "/Users/x/atlas"}}}}
```

(`tests/test_rebuild.py` already imports `types` and `time`; add `import sys`.) That test goes in `tests/test_rebuild.py` with the one below.

In `tests/test_rebuild.py`, give the fake tab the attribute every real tab has (class `Tab`, near line 127): add `tmux_connection_id = None`. Then append:

```python
def test_a_remote_tmux_pane_does_not_wear_the_local_pane_of_its_number(monkeypatch):
    """Measured 2026-10-11: remote pane %4 took local %4's label, tty and branch."""
    class RemotePane(Session):
        async def async_get_variable(self, name):
            return {"tmuxWindowPane": 4, "jobName": "ssh", "path": "/Users/x/elsewhere"}.get(name)
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system", lambda: (
        ({}, {}, {}, {}), {4: {"job": "claude", "path": "/Users/x/atlas", "tty": "ttys004"}}, {}, {}, {}, {}))
    monkeypatch.setattr(sidebar, "local_host", lambda: "desk")

    async def tables(ids):
        assert ids == {"there"}
        return {"there": {"host": "box", "panes": {4: {"tty": "ttys005", "path": "/srv/app"}}}}
    b.read_tmux_tables = tables
    tab = type("RemoteTab", (Tab,), {"sessions": (RemotePane(),), "tmux_connection_id": "there"})
    window = type("W", (Window,), {"tabs": (tab(),)})
    b.app = type("A", (NoWindows,), {"terminal_windows": (window(),)})()
    [row] = asyncio.run(b.read_sessions())
    assert (row["path"], row["tty"], row["host"]) == ("/srv/app", None, "box")
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_foreground.py tests/test_rebuild.py -q --color=no`
Expected: FAIL, `module 'sidebar' has no attribute 'parse_tmux_table'` (and `tmux_pane`, `local_host`).

- [ ] **Step 3: Implement**

In `sidebar.py`, add `import socket` with the other imports, and after `parse_tmux_panes`:

```python
#: The longest a rebuild waits on a tmux server's answer; one on another machine can be slow or gone.
TMUX_TABLE_SECONDS = 1
#: One line per pane of a tmux server, its host first: what a connection is asked for.
TMUX_TABLE_COMMAND = "list-panes -a -F '#{host_short} #{pane_id} #{pane_tty} #{pane_current_path}'"


def local_host():
    """This machine's name as hooks and tmux write it: up to the first dot."""
    return socket.gethostname().split(".")[0]


def parse_tmux_table(out):
    """A connection's answer to TMUX_TABLE_COMMAND -> {host, panes}. The host
    is the first line's; every line of one server carries the same."""
    host, rest = None, []
    for line in out.splitlines():
        name, _, pane = line.partition(" ")
        if pane.startswith("%"):
            host = host or name
            rest.append(pane)
    return {"host": host, "panes": {number: {"tty": pane["tty"], "path": pane["path"]}
                                    for number, pane in parse_tmux_panes("\n".join(rest)).items()}}


def tmux_pane(connection_id, tables, number, here, local_panes):
    """What tmux knows of one session's pane, from the server its tab is on.

    Pane numbers start at zero on every server, so a number alone names a
    pane only of the server on this machine. A pane of a server elsewhere
    gives its folder and its host and is never paired with a local terminal;
    a connection that could not be read leaves the pane to iTerm2.
    """
    if number is None:
        return {}
    if connection_id is None:
        return local_panes.get(number) or {}
    table = tables.get(connection_id)
    if table is None:
        return {}
    if table["host"] == here:
        return local_panes.get(number) or {}
    return {"path": (table["panes"].get(number) or {}).get("path"), "host": table["host"]}
```

In `Bridge`, a method beside `read_terminal_font`:

```python
    async def read_tmux_tables(self, ids):
        """Each of these tmux connections' own pane table, asked through iTerm2.
        One that cannot be read is left out and said once."""
        import iterm2

        tables = {}
        try:
            connections = await iterm2.async_get_tmux_connections(self.connection)
        except Exception as error:                   # noqa: BLE001
            self.log("tmux connections not read:", repr(error))
            return tables
        wanted = [one for one in connections if one.connection_id in ids]
        # Together: a slow link to another machine must not hold up the
        # others, and none may hold a rebuild longer than its own limit.
        answers = await asyncio.gather(
            *(asyncio.wait_for(one.async_send_command(TMUX_TABLE_COMMAND), TMUX_TABLE_SECONDS)
              for one in wanted), return_exceptions=True)
        for one, answer in zip(wanted, answers):
            if isinstance(answer, BaseException):
                if one.connection_id not in self._tmux_unread:
                    self._tmux_unread.add(one.connection_id)
                    self.log(f"tmux connection {one.connection_id!r} not read: {answer!r}")
            else:
                tables[one.connection_id] = parse_tmux_table(answer)
        self._tmux_unread &= set(ids)
        return tables
```

Add `self._tmux_unread = set()` in `Bridge.__init__`.

In `read_sessions`, after `codex_jobs = ...` and before the window loop:

```python
        here = local_host()
        connections = {tab.tmux_connection_id for window in self.app.terminal_windows
                       for tab in window.tabs} - {None}
        tables = await self.read_tmux_tables(connections) if connections else {}
```

and replace `pane = tmux_panes.get(values["tmuxWindowPane"]) or {}` with:

```python
                    pane = tmux_pane(tab.tmux_connection_id, tables, values["tmuxWindowPane"],
                                     here, tmux_panes)
```

In the row dict add `"host": pane.get("host"),` after `"tty": tty or None,`. (Task 4 extends it.)

- [ ] **Step 4: Run the tests**

Run the command from Step 2. Expected: PASS. Then the whole suite; expected exit code 0.

- [ ] **Step 5: Live check on this machine** (session file `.cs/local/remote-probes/check1_connections.py`, already written)

Install and restart the daemon (`./install.sh`, then the restart in the project memory). Read one frame from `/events` and confirm the local tmux panes still have their `tty` and `path` (compare with a frame saved before the change), and that `display-message -p '#{host_short}'` through the local connection equals `local_host()`. With `REMOTE` set, attach a remote `tmux -CC`, open panes until a number collides, and confirm the remote pane's frame row has the remote folder and no `tty` or `branch`.

- [ ] **Step 6: Commit**

```bash
git add sidebar.py tests/test_foreground.py tests/test_rebuild.py
git commit -m "Daemon: a tmux pane is looked up on its own server, so a remote pane never takes a local pane's row"
```

---

### Task 2: The hook says where it runs (`host`, `front`, `cwd`)

**Files:**
- Modify: `plugin/hooks-handlers/emit-state.py` (`published` near line 952, `carried` near 1004, `main`)
- Test: `tests/test_emit_state.py`

**Interfaces:**
- Produces:
  - `short_host() -> str`
  - `front_of(ps_out: str) -> bool | None` (the output of `ps -o tpgid=,pgid= -p <pid>`)
  - `in_front(pid) -> bool | None`
  - `published(doc, pid, payload, codex, now, tasks=True, front=None)`: the value gains `host`, `front`, and `cwd` for every agent
  - `carried(value, session_id, directory=None)`: compact JSON; an envelope over the ceiling has its `cwd` cut to its last two components, then dropped

- [ ] **Step 1: Write the failing tests** (append to `tests/test_emit_state.py`)

```python
def test_the_published_state_says_which_machine_and_folder_it_is_from(monkeypatch):
    monkeypatch.setattr(emit_state.socket, "gethostname", lambda: "box.example.com")
    value = emit_state.published({}, 701, {"session_id": "abc-123", "cwd": "/srv/app"},
                                 codex=False, now=1789000000, tasks=False, front=True)
    assert (value["host"], value["front"], value["cwd"]) == ("box", True, "/srv/app")


def test_the_agent_is_in_front_when_its_group_is_its_terminals_foreground_group():
    assert emit_state.front_of(" 4321  4321\n") is True
    assert emit_state.front_of(" 4400  4321\n") is False


def test_a_process_with_no_terminal_or_no_listing_is_not_known_to_be_in_front():
    assert emit_state.front_of("    0  4321\n") is False
    assert emit_state.front_of("") is None
    assert emit_state.front_of("garbage\n") is None


def test_the_variable_is_written_without_spaces(tmp_path):
    assert emit_state.carried({"state": "idle", "pid": 7}, "s-1", str(tmp_path)) == '{"state":"idle","pid":7}'


def _over_the_ceiling(cwd):
    return {"state": "blocked", "pid": 31432, "session": "0f0e0d0c-0b0a-4a09-8807-060504030201",
            "agents": 1, "subagents": [{"id": "a" * 40, "type": "general-purpose"}] * 6,
            "blocked_since": 1791700000, "working_since": 1791699000, "turn_started": 1791699000,
            "idle_since": None, "question": None, "ts": 1791700000, "tasks": [],
            "host": "box", "front": True, "cwd": cwd}


def test_an_envelope_keeps_host_front_and_folder_under_the_ceiling(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/srv/app"), "s-1", str(tmp_path))
    envelope = json.loads(text)
    assert (envelope["host"], envelope["front"], envelope["cwd"], envelope["detail"]) == ("box", True, "/srv/app", True)
    assert len(base64.b64encode(text.encode())) <= 512


def test_a_long_folder_is_cut_to_its_last_two_parts(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/" + "/".join(["deep"] * 60) + "/projects/some-repo"),
                              "s-1", str(tmp_path))
    assert json.loads(text)["cwd"] == "projects/some-repo"
    assert len(base64.b64encode(text.encode())) <= 512


def test_a_folder_too_long_even_cut_is_left_out(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/a/" + "x" * 300 + "/" + "y" * 300), "s-1", str(tmp_path))
    assert "cwd" not in json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_emit_state.py -q --color=no`
Expected: FAIL on the eight new tests (`no attribute 'socket'`, `front_of`, a `TypeError` for `front=`, spaced JSON).

- [ ] **Step 3: Implement**

`import socket` with the other imports. Beside `agent_pid`:

```python
def short_host():
    """This machine's name up to its first dot: what a panel on another machine tells this session by."""
    return socket.gethostname().split(".")[0]


def front_of(ps_out):
    """`ps -o tpgid=,pgid=` for the agent -> whether its group holds its terminal, or None when unread."""
    parts = ps_out.split()
    if len(parts) != 2 or not all(part.lstrip("-").isdigit() for part in parts):
        return None
    return parts[0] == parts[1]


def in_front(pid):
    """Whether the agent is what its terminal's keys reach, at this event."""
    if not pid:
        return None
    try:
        out = subprocess.run(["/bin/ps", "-o", "tpgid=,pgid=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return front_of(out)
```

In `published`, add the parameter `front=None`, and to `value`: `"host": short_host(), "front": front,`. Move `value["cwd"] = payload.get("cwd")` out of the `if codex:` branch so every agent carries it (keep its comment with the Codex lines that still need it, reworded to say Codex pairs by it).

In `carried`, write compact JSON and fit the envelope:

```python
    compact = lambda doc: json.dumps(doc, separators=(",", ":"))
    fits = lambda text: len(base64.b64encode(text.encode())) <= VARIABLE_CEILING
    whole = compact(value)
    if fits(whole):
        return whole
    envelope = {key: item for key, item in value.items() if key not in DETAIL_FIELDS}
    try:
        file_whole(value, session_id, directory)
        envelope["detail"] = True
    except OSError:
        envelope["detail"] = False
    # A panel on another machine has no file to read: the folder rides in the
    # envelope while it fits, shortened before it is given up.
    folder = envelope.get("cwd")
    if isinstance(folder, str) and not fits(compact(envelope)):
        envelope["cwd"] = "/".join(folder.rstrip("/").split("/")[-2:])
        if not fits(compact(envelope)):
            del envelope["cwd"]
    return compact(envelope)
```

In `main`, pass `front=in_front(pid)` to both `published(...)` calls.

Existing tests that compare the variable's text to spaced JSON now fail on the spacing alone, and tests that assert a published value's exact keys (the Codex and omp ones among them) now see `host`, `front` and `cwd` as well. Change those expectations to the compact form and the three added keys and nothing else; list each one in the commit body.

- [ ] **Step 4: Run the tests**

Run the command from Step 2, then the whole suite. Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add plugin/hooks-handlers/emit-state.py tests/test_emit_state.py
git commit -m "Hook: the state names its host, whether the agent is in front, and its folder; written without spaces"
```

---

### Task 3: The question in a variable of its own, and a quiet task line

**Files:**
- Modify: `plugin/hooks-handlers/emit-state.py` (`apply_event`'s field list near line 338, a writer beside `mark_reminded`, `main`)
- Test: `tests/test_emit_state.py`

**Interfaces:**
- Consumes: `emit(value, target, variable)`, `blocked_since(doc)`, `clip(text, limit)`, `VARIABLE_CEILING`.
- Produces:
  - `QUESTION_VARIABLE = "claudeQuestion"`, `ENDPOINT = os.path.expanduser("~/.local/share/agents-sidebar/endpoint.json")`
  - `question_short(question, since) -> str | None` (JSON text under the ceiling, or None when it cannot be carried)
  - `question_write(sent, question, since) -> (text | None, sent')`: `text` is what to write to the variable now (`""` clears it, `None` writes nothing); `sent` and `sent'` are the digest (`written(text)`) of what stands in the variable, or None when it is empty
  - `written(text) -> str` (the first 16 hex characters of the text's SHA-1)
  - the state document's new field `question_sent`
  - `mark_question_sent(session_id, sent)`

- [ ] **Step 1: Write the failing tests**

```python
ASKED = {"header": "First slice", "question": "What should the first slice be?",
         "options": ["State over the pane (Recommended)", "Relay from the start", "Bug fix only first"],
         "multi": False, "more": 0}


def test_a_question_that_fits_travels_whole_with_when_it_was_raised():
    assert json.loads(emit_state.question_short(ASKED, 1791700000)) == dict(ASKED, since=1791700000)


def test_a_long_question_keeps_every_option_and_fits():
    asked = dict(ASKED, question="q" * 300, options=["a" * 60, "b" * 60, "c" * 60, "d" * 60])
    text = emit_state.question_short(asked, 1791700000)
    carried = json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512
    assert [label[0] for label in carried["options"]] == ["a", "b", "c", "d"]
    assert len({len(label) for label in carried["options"]}) == 1
    assert carried["question"].startswith("q") and carried["since"] == 1791700000


def test_options_that_cannot_all_be_carried_send_no_question():
    """An answer is a number: a missing option would renumber the rest."""
    assert emit_state.question_short(dict(ASKED, options=["x" * 60] * 60), 1791700000) is None


def test_a_set_or_a_multi_select_sends_no_question():
    assert emit_state.question_short(dict(ASKED, more=1, set=[ASKED, ASKED]), 1791700000) is None
    assert emit_state.question_short(dict(ASKED, multi=True), 1791700000) is None


def test_a_tool_approval_keeps_its_id_and_drops_its_reason():
    asked = {"tool": "Bash", "summary": "git push " + "x" * 400, "reason": "y" * 300, "id": "f" * 32}
    text = emit_state.question_short(asked, 1791700000)
    carried = json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512
    assert (carried["tool"], carried["id"], carried["since"]) == ("Bash", "f" * 32, 1791700000)
    assert carried["summary"].startswith("git push ") and "reason" not in carried


def test_a_new_question_is_written_once():
    text, sent = emit_state.question_write(None, ASKED, 1791700000)
    assert json.loads(text)["since"] == 1791700000 and sent == emit_state.written(text)
    assert emit_state.question_write(sent, ASKED, 1791700000) == (None, sent)


def test_a_second_gate_opened_while_the_first_stands_replaces_the_question():
    """The newest gate's question stands, but the oldest gate's time is the state's blocked_since:
    told apart by time alone, the first question's buttons would stay up over the second."""
    _, sent = emit_state.question_write(None, ASKED, 1791700000)
    second = dict(ASKED, question="And the second?", options=["Yes", "No"])
    text, sent_after = emit_state.question_write(sent, second, 1791700000)
    assert json.loads(text)["question"] == "And the second?" and sent_after != sent


def test_a_question_gone_clears_the_variable_once():
    assert emit_state.question_write("0123456789abcdef", None, None) == ("", None)
    assert emit_state.question_write(None, None, None) == (None, None)


def test_a_question_that_cannot_be_carried_clears_what_stood():
    assert emit_state.question_write("0123456789abcdef", dict(ASKED, multi=True), 1791700999) == ("", None)


def test_the_question_reaches_the_terminal_before_the_state_that_names_it(tmp_path):
    """The panel reads on the state's arrival; the question must already be there."""
    payload = {"session_id": "abc-123", "tool_name": "AskUserQuestion", "tool_use_id": "t1",
               "tool_input": {"questions": [{"header": "Pick", "question": "Which one?",
                                             "options": [{"label": "This"}, {"label": "That"}]}]}}
    _, _, written = run_handler(tmp_path, ["PermissionRequest"], payload)
    names = [name for name, _ in written]
    assert names == ["claudeQuestion", "claudeState"]
    question = json.loads(dict(written)["claudeQuestion"])
    state = json.loads(dict(written)["claudeState"])
    assert question["options"] == ["This", "That"] and question["since"] == state["blocked_since"]


def test_a_machine_with_no_panel_gets_no_task_line_instructions(tmp_path):
    _, out, _ = run_handler(tmp_path, ["UserPromptSubmit"], {"session_id": "abc-123", "prompt": "hi"})
    assert "additionalContext" not in out


def test_a_machine_with_a_panel_gets_them(tmp_path):
    endpoint = tmp_path / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text("{}")
    _, out, _ = run_handler(tmp_path, ["UserPromptSubmit"], {"session_id": "abc-123", "prompt": "hi"})
    assert "Current task: none" in out
```

`run_handler` returns `(exit code, stdout, [(variable, decoded value)])`.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_emit_state.py -q --color=no`
Expected: FAIL (`no attribute 'question_short'`; one variable written, not two; instructions present without the endpoint file).

- [ ] **Step 3: Implement**

```python
#: The standing question, in a variable of its own: it does not fit beside the state.
QUESTION_VARIABLE = "claudeQuestion"
#: Label lengths tried, longest first, when a question has to be cut to fit.
LABEL_STEPS = (60, 40, 30, 20, 12, 8)
#: The panel's daemon writes this where it runs; a machine with hooks alone has none.
ENDPOINT = os.path.expanduser("~/.local/share/agents-sidebar/endpoint.json")


def _fits(text):
    return len(base64.b64encode(text.encode())) <= VARIABLE_CEILING


def _longest_fitting(build, text):
    """`build(text cut to n characters)` for the largest n whose result fits, or None."""
    low, high, best = 0, len(text), None
    while low <= high:
        middle = (low + high) // 2
        made = build(clip(text, middle) if middle else "")
        if _fits(made):
            best, low = made, middle + 1
        else:
            high = middle - 1
    return best


def question_short(question, since):
    """The standing question as the text its variable carries, or None when it cannot travel.

    The shape is the question's own, with `since`: the time its gate opened,
    which pairs it with the state that names it. Every option is kept in its
    place or nothing is sent, since an answer is the option's number.
    """
    if not isinstance(question, dict) or question.get("multi") or question.get("more") or "set" in question:
        return None
    compact = lambda doc: json.dumps(doc, separators=(",", ":"))
    if "options" in question:
        whole = compact(dict(question, since=since))
        if _fits(whole):
            return whole
        for limit in LABEL_STEPS:
            labels = [clip(label, limit) for label in question["options"]]
            made = _longest_fitting(
                lambda text: compact({"header": "", "question": text, "options": labels,
                                      "multi": False, "more": 0, "since": since}),
                question.get("question") or "")
            if made:
                return made
        return None
    if question.get("tool"):
        return _longest_fitting(
            lambda text: compact({"tool": question["tool"], "summary": text,
                                  "id": question.get("id"), "since": since}),
            question.get("summary") or "")
    return None


def written(text):
    """What stands in the question variable, as the state document remembers it."""
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def question_write(sent, question, since):
    """What to write to the question variable at this event -> (text or None, what now stands there).

    Written when the text to carry differs from what stands, and cleared
    when no question does; an event that changes neither writes nothing, so
    the terminal gets a second escape sequence only when the question
    changes. Compared by what was written, not by when the gate opened: a
    second gate raised while the first stands changes the question and
    leaves the oldest gate's time as it was.
    """
    text = question_short(question, since) if question and since is not None else None
    if text is None:
        return ("", None) if sent is not None else (None, None)
    return (None, sent) if sent == written(text) else (text, written(text))
```

`import hashlib` with the other imports. `mark_question_sent(session_id, sent)`: the body of `mark_reminded` with `question_sent=sent` in place of `reminded=round(now)`. Unify the two into one private writer that takes the field and its value, and keep both public names as one-line callers.

In `apply_event`'s rebuilt `doc`, add `"question_sent": doc.get("question_sent"),` so the field survives every event.

In `main`, in the final `else:` branch (a state written to a terminal), before `emit(carried(...))`:

```python
        value = published(doc, pid, payload, codex, time.time(), tasks=agent == "claude", front=in_front(pid))
        if agent == "claude":
            text, standing = question_write(doc.get("question_sent"), value.get("question"),
                                            value.get("blocked_since"))
            if text is not None:
                # Before the state: the panel reads when the state arrives.
                emit(text, tty, QUESTION_VARIABLE)
                mark_question_sent(session_id, standing)
        emit(carried(value, session_id), tty, variable)
```

On `SessionEnd` (the `state == ""` branch) also `emit("", variable=QUESTION_VARIABLE)` for a Claude agent.

The task line: wrap the `whisper(...)` call so it runs only when `os.path.exists(ENDPOINT)`; otherwise `context = None`. Existing handler tests that expect the instructions create the endpoint file under their `home` first, as the new test does; change those tests' setup and no assertion.

- [ ] **Step 4: Run the tests**

Run the command from Step 2, then the whole suite. Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add plugin/hooks-handlers/emit-state.py tests/test_emit_state.py
git commit -m "Hook: a standing question travels in its own variable, written before the state; no task-line instructions where no panel runs"
```

---

### Task 4: The daemon recognises a remote row

**Files:**
- Modify: `sidebar.py` (`parse_state` near line 1270, parsers near 2054, `SESSION_VARIABLES`/`STATE_VARIABLES` near 3005, `read_sessions` row building near 3236-3380, `snapshot` near 1095, `context_target` near 1343, `Bridge.run` where `watch_state` tasks are started)
- Modify: `sidebar_rules.py`
- Test: `tests/test_remote_rows.py` (new), `tests/test_rebuild.py`, `tests/test_snapshot.py`, `tests/test_context_usage.py`

**Interfaces:**
- Consumes: Task 1's `local_host()`, `tmux_pane`; Task 2's `host`, `front`, `cwd`; Task 3's `user.claudeQuestion` with `since`.
- Produces:
  - `TRANSPORTS = frozenset({"ssh", "et"})`
  - `remote_host(raw, here) -> str | None` (a `host` in the state that is not `here`, clipped to 64 characters)
  - `parse_front(raw) -> bool | None`, `parse_cwd(raw) -> str | None`
  - `remote_question(raw, question_raw) -> dict | None`
  - `parse_state(raw, command_running=False, remote=False)`
  - `sidebar_rules.remote_key_refusal(host, transport, front, marked) -> str | None`
  - row and frame fields `host`, `remote_refusal`

- [ ] **Step 1: Write the failing tests** (`tests/test_remote_rows.py`)

```python
# ABOUTME: A state published on another machine: recognised by its host, never checked against this machine's
# ABOUTME: processes or files, live only while its transport is in front, and answered only under its checks.
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar
from sidebar_rules import remote_key_refusal

STATE = {"state": "blocked", "pid": 31432, "session": "0f0e0d0c-0b0a-4a09-8807-060504030201",
         "blocked_since": 1791700000, "ts": 1791700000, "host": "box", "front": True, "cwd": "/srv/app",
         "detail": True}
raw = lambda **changes: json.dumps(dict(STATE, **changes))


def test_a_state_from_another_host_is_remote():
    assert sidebar.remote_host(raw(), "desk") == "box"


def test_a_state_from_this_host_or_from_a_hook_that_names_none_is_local():
    assert sidebar.remote_host(raw(host="desk"), "desk") is None
    assert sidebar.remote_host(json.dumps({"state": "idle", "pid": 7}), "desk") is None
    assert sidebar.remote_host(raw(host=7), "desk") is None
    assert sidebar.remote_host(None, "desk") is None


def test_a_host_name_is_clipped():
    assert sidebar.remote_host(raw(host="h" * 500), "desk") == "h" * 64


def test_a_remote_state_is_never_asked_of_the_local_process_table(monkeypatch):
    def kill(pid, signal):
        raise AssertionError("a pid from another machine was asked of this one")
    monkeypatch.setattr(sidebar.os, "kill", kill)
    assert sidebar.parse_state(raw(), remote=True) == "blocked"


def test_a_local_state_whose_writer_is_gone_still_reads_exited(monkeypatch):
    def gone(pid, signal):
        raise ProcessLookupError
    monkeypatch.setattr(sidebar.os, "kill", gone)
    assert sidebar.parse_state(raw()) == "exited"


def test_the_question_shows_only_while_it_is_the_one_the_state_names():
    asked = {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0, "since": 1791700000}
    shown = {key: item for key, item in asked.items() if key != "since"}
    assert sidebar.remote_question(raw(), json.dumps(asked)) == shown
    assert sidebar.remote_question(raw(blocked_since=1791700999), json.dumps(asked)) is None
    assert sidebar.remote_question(raw(state="working"), json.dumps(asked)) is None
    assert sidebar.remote_question(raw(), "") is None
    assert sidebar.remote_question(raw(), "not json") is None


def test_one_key_may_be_typed_only_under_every_check():
    assert remote_key_refusal("box", True, True, True) is None
    assert remote_key_refusal("box", False, True, True) == "the connection to box is not in front here"
    assert remote_key_refusal("box", True, False, True) == "something is in front of the agent on box"
    assert remote_key_refusal("box", True, None, True) == "something is in front of the agent on box"
    assert remote_key_refusal("box", True, True, False) == "the agent's title has gone from the pane"
```

Append to `tests/test_rebuild.py` (it has the `bridge`, `one_session` and `Session` fakes):

```python
REMOTE_STATE = {"state": "blocked", "pid": 4242, "session": "0f0e0d0c-0b0a-4a09-8807-060504030201",
                "blocked_since": 1791700000, "ts": 1791700000, "host": "box", "front": True, "cwd": "/private/tmp",
                "detail": True}
REMOTE_ASKED = {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0,
                "since": 1791700000}


def remote_session(job="ssh", title="✳ Claude Code"):
    class RemoteSession(Session):
        async def async_get_variable(self, name):
            return {"user.claudeState": json.dumps(REMOTE_STATE), "user.claudeQuestion": json.dumps(REMOTE_ASKED),
                    "jobName": job, "autoName": title, "path": "/Users/x/atlas", "tty": "/dev/ttys004"}.get(name)
    return RemoteSession()


def remote_bridge(monkeypatch, tmp_path):
    """A remote pid that is also a live local pid, with a status file, shells and a start time of its own."""
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "local_host", lambda: "desk")
    monkeypatch.setattr(sidebar, "read_system", lambda: (
        ({4242: [{"label": "ls", "command": "ls"}]}, {4242: 1789980000}, {4242: "blue"}, {4242: "parent"}),
        {}, {4242: (0, 12.0, 50000, "ttys004")}, {4242: "claude"}, {}, {4242: (4242, 4242, "ttys004")}))
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    (tmp_path / "4242.json").write_text(json.dumps({"model": {"display_name": "Local Model"}}))
    monkeypatch.setattr(sidebar, "git_branch", lambda path: pytest.fail(f"read a branch at {path}") if path else None)
    monkeypatch.setattr(sidebar, "session_colour", lambda path: pytest.fail(f"read a colour at {path}") if path else None)
    monkeypatch.setattr(sidebar, "git_main_worktree",
                        lambda path: pytest.fail(f"read a worktree at {path}") if path else None)
    return b


def test_a_remote_row_takes_nothing_from_the_local_process_of_its_pid(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    b.app = one_session(remote_session())
    [row] = asyncio.run(b.read_sessions())
    assert (row["host"], row["agent_state"], row["path"]) == ("box", "blocked", "/private/tmp")
    assert (row["agent_pid"], row["model"], row["shells"], row["started_at"], row["colour"],
            row["parent_session"], row["branch"], row["worktree_of"], row["in_front"]) == (
        None, None, [], None, None, None, None, None, None)
    assert row["question"] == {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0}
    assert row["remote_refusal"] is None


def test_a_remote_row_whose_transport_is_not_in_front_reads_unknown(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    b.app = one_session(remote_session(job="zsh"))
    [row] = asyncio.run(b.read_sessions())
    assert row["agent_state"] == "unknown"
    assert row["remote_refusal"] == "the connection to box is not in front here"


def test_a_remote_row_without_the_agents_title_takes_no_key(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    b.app = one_session(remote_session(title="user@box:~"))
    [row] = asyncio.run(b.read_sessions())
    assert row["remote_refusal"] == "the agent's title has gone from the pane"
```

Append to `tests/test_snapshot.py` (it has the `_agent` builder):

```python
def test_a_remote_row_carries_its_host_and_offers_no_context_breakdown():
    frame = snapshot([_agent(host="box", remote_refusal="the agent's title has gone from the pane",
                             provider="claude", conversation="524ba3e7-6207-4c5a-af51-85392a3f541f")])
    [row] = [r for g in frame["groups"] for r in g["rows"]]
    assert (row["host"], row["remote_refusal"]) == ("box", "the agent's title has gone from the pane")
    assert "context_readable" not in row


def test_a_local_row_carries_no_host():
    [row] = [r for g in snapshot([_agent()])["groups"] for r in g["rows"]]
    assert "host" not in row and "remote_refusal" not in row
```

In `tests/test_context_usage.py`, add one case to the parametrized list above `test_a_row_that_is_not_a_readable_claude_conversation_is_refused`:

```python
    ({"host": "box"}, "a remote session has no /context here"),
```

- [ ] **Step 2: Run them and see them fail**

The first rebuild test proves nothing unless a local process of that pid would have shown: once Step 4 is in, delete `"host"` from `REMOTE_STATE` for one run and confirm the row then carries the shells, the start time 1789980000 and the colour "blue". Put it back.

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_remote_rows.py tests/test_rebuild.py tests/test_snapshot.py tests/test_context_usage.py -q --color=no`
Expected: FAIL (`no attribute 'remote_host'`, `cannot import name 'remote_key_refusal'`, a `TypeError` for `remote=`).

- [ ] **Step 3: Implement the rule** (`sidebar_rules.py`)

```python
def remote_key_refusal(host, transport, front, marked):
    """Why not even one key may be typed into a pane whose agent runs on `host`, or None.

    Nothing here can see the other machine, so three witnesses stand in for
    the local foreground check: the transport is what this pane's keys reach,
    the agent held its terminal at its last event, and its title is still on
    the pane (a shell prompt repaints it once the agent is gone).
    """
    if not transport:
        return f"the connection to {host} is not in front here"
    if front is not True:
        return f"something is in front of the agent on {host}"
    if not marked:
        return "the agent's title has gone from the pane"
    return None
```

- [ ] **Step 4: Implement the daemon side** (`sidebar.py`)

Constants and parsers, beside `parse_pid`:

```python
#: The programs a pane runs to reach another machine. While one is the pane's
#: foreground job, the pane's keys go to that machine.
TRANSPORTS = frozenset({"ssh", "et"})
HOST_LIMIT = 64


def _published(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def remote_host(raw, here):
    """The machine a state was published on when it is not this one, or None.
    Text from that machine: clipped, shown as text, never part of a command."""
    host = _published(raw).get("host")
    return host[:HOST_LIMIT] if isinstance(host, str) and host and host != here else None


def parse_front(raw):
    """Whether the agent held its terminal at its last event: True, False, or None when not said."""
    front = _published(raw).get("front")
    return front if isinstance(front, bool) else None


def parse_cwd(raw):
    folder = _published(raw).get("cwd")
    return folder if isinstance(folder, str) and folder else None


def remote_question(raw, question_raw):
    """The question a remote state names, from the variable of its own, or None.
    Shown only while the state is blocked and the question is the one raised with it."""
    state, asked = _published(raw), _published(question_raw)
    if state.get("state") != "blocked" or not asked or asked.get("since") != state.get("blocked_since"):
        return None
    return {key: item for key, item in asked.items() if key != "since"}
```

`parse_state`: add the parameter `remote=False` and wrap the liveness block so a remote state skips it:

```python
    if not remote:
        try:
            os.kill(pid, 0)          # signal 0 tests existence, sends nothing
        except ProcessLookupError:
            return "exited"
        except (ValueError, OverflowError):
            return "unknown"
        except PermissionError:
            pass                     # alive, just not ours to signal
```

Add to its docstring: a state from another machine names a process this one cannot ask about, so its liveness is the caller's to judge.

`SESSION_VARIABLES`: add `"user.claudeQuestion"`. Where `Bridge.run` starts one `watch_state` per entry of `STATE_VARIABLES`, start one more for `"user.claudeQuestion"`, so a question that lands after its state costs no wait for the poll.

`read_sessions`, at `pid = job_pid(values["jobPid"]) if titled else parse_pid(raw)`, add after it:

```python
                    # A state published on another machine: its pid, its
                    # files and its folder are that machine's. Nothing of
                    # this machine's is looked up by them.
                    host = remote_host(raw, here) or pane.get("host")
                    transport = job in TRANSPORTS
                    if host:
                        pid = None
                        values["path"] = parse_cwd(raw) or (pane.get("path") if pane.get("host") else None)
```

Then, further down:

- `agent_state = titled or parse_state(raw, command_running=bool(shells.get(pid)), remote=bool(host))`, followed by:

```python
                    if host and raw and not transport:
                        # The variable outlives the link: with the transport
                        # gone from the foreground nothing says the session
                        # can still be reached.
                        agent_state = "unknown"
```

- in the row dict: `"host": host,` (replacing Task 1's line), `"remote_refusal": remote_key_refusal(host, transport, parse_front(raw), bool(values["autoName"]) and values["autoName"].startswith(AGENT_TITLE_MARKER)) if host and raw else None,`
- `"question": remote_question(raw, values["user.claudeQuestion"]) if host else parse_question(raw),`
- `"colour": agent_colours.get(pid) or (None if host else session_colour(values["path"])),`
- `"branch": None if host else git_branch(values["path"]),` and `"worktree_of": None if host else git_main_worktree(values["path"]),`

`pid = None` already empties `read_status`, `shells`, `started`, `agent_parents`, `program_in_front` and the usage readings, which the first rebuild test pins.

Import `remote_key_refusal` from `sidebar_rules` beside `prompt_refusal`.

`snapshot`: beside the `in_front` lines, add

```python
            if session.get("host"):
                row["host"] = session["host"]
            if session.get("remote_refusal"):
                row["remote_refusal"] = session["remote_refusal"]
```

and add `and not session.get("host")` to the `context_readable` condition. A shell row on a remote tmux connection carries `host` too: add the same two `host` lines where shell rows are built.

`context_target`: after the provider check,

```python
    if row.get("host"):
        raise context_usage.Refused("a remote session has no /context here")
```

- [ ] **Step 5: Run the tests**

Run the command from Step 2, then the whole suite. Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add sidebar.py sidebar_rules.py tests/test_remote_rows.py tests/test_rebuild.py tests/test_snapshot.py tests/test_context_usage.py
git commit -m "Daemon: a state from another host is a remote row, read from its envelope alone and live only while its transport is in front"
```

---

### Task 5: One place that types, and what a remote row refuses

**Files:**
- Modify: `sidebar_rules.py` (`prompt_refusal`, new `typing_refusal`), `sidebar.py` (`Bridge.act`, `resume`, `answer_from_card`, `notify_argv`, `notify`, `link_end`), `links.py` (`own_refusal`)
- Test: `tests/test_prompt_guard.py`, `tests/test_notify.py`, `tests/test_links.py`

**Interfaces:**
- Consumes: frame rows' `host`, `remote_refusal`, `state` (Task 4).
- Produces:
  - `sidebar_rules.REMOTE_NO_REPLY = "replies do not reach a remote session yet"`
  - `sidebar_rules.typing_refusal(row, strokes) -> str | None`
  - `async Bridge.type_keys(session, session_id, strokes, pause=0) -> bool`: the only caller of `async_send_text`
  - `notify_argv(app, session_id, name, kind, question, remote=False)`

- [ ] **Step 1: Write the failing tests**

`tests/test_prompt_guard.py`:

```python
from sidebar_rules import typing_refusal

REMOTE = {"session_id": "abc", "state": "blocked", "host": "box"}


def test_a_reply_to_a_remote_session_is_refused():
    assert prompt_refusal(dict(REMOTE, state="idle")) == "replies do not reach a remote session yet"
    assert prompt_refusal(REMOTE) == "replies do not reach a remote session yet"


def test_a_local_row_is_typed_into_as_before():
    assert typing_refusal({"session_id": "abc", "state": "idle"}, ["fix it", "\r"]) is None
    assert typing_refusal(None, ["1"]) is None


def test_a_remote_row_takes_one_key_while_it_waits_on_you():
    assert typing_refusal(REMOTE, ["2"]) is None
    assert typing_refusal(REMOTE, ["\x1b"]) is None


@pytest.mark.parametrize("strokes", [["2\n"], ["2", "\r"], ["\r"], ["\n"], ["3 use the other one\n"], ["yes"], []])
def test_a_remote_row_takes_no_line_and_no_text(strokes):
    assert typing_refusal(REMOTE, strokes) == "replies do not reach a remote session yet"


def test_a_remote_row_that_is_not_waiting_takes_no_key():
    assert typing_refusal(dict(REMOTE, state="working"), ["2"]) == "it is not waiting on you"
    assert typing_refusal(dict(REMOTE, state="unknown"), ["2"]) == "it is not waiting on you"


def test_a_remote_row_says_why_its_own_checks_refuse():
    row = dict(REMOTE, remote_refusal="the agent's title has gone from the pane")
    assert typing_refusal(row, ["2"]) == "the agent's title has gone from the pane"
```

Also in `tests/test_prompt_guard.py` (it has `bridge_over` and a `Pane` that records what is typed; add `import json`):

```python
def remote_bridge(monkeypatch, tmp_path, **changes):
    """A Bridge whose last frame lists "abc" as a remote card with one question standing."""
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    row = {"session_id": "abc", "state": "blocked", "host": "box",
           "question": {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0}}
    b.latest = {"groups": [{"name": "AGENTS", "rows": [dict(row, **changes)]}]}
    return b


def test_an_answer_types_its_digit_into_a_remote_pane_that_passes_its_checks(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": 2, "question": "Which one?"})))
    assert b.app.pane.typed == ["2"]


def test_an_answer_is_not_typed_into_a_remote_pane_that_fails_its_checks(monkeypatch, tmp_path):
    """Nothing is typed, and the click is not remembered as an answer: the next one can still land."""
    b = remote_bridge(monkeypatch, tmp_path, remote_refusal="the agent's title has gone from the pane")
    asyncio.run(b.act("abc", "answer", json.dumps({"pick": 1, "question": "Which one?"})))
    assert b.app.pane.typed == [] and b.answered == {}


def test_a_notices_reply_is_not_typed_into_a_remote_pane(monkeypatch, tmp_path):
    """Other, then the text, then Enter: a line a shell there could run."""
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "send", "3use the other one\n"))
    assert b.app.pane.typed == []
    assert (tmp_path / "daemon.log").read_text().split(" ", 2)[2] == (
        "typing refused abc replies do not reach a remote session yet\n")


def test_a_notices_button_types_its_one_key_into_a_remote_pane_that_passes(monkeypatch, tmp_path):
    b = remote_bridge(monkeypatch, tmp_path)
    asyncio.run(b.act("abc", "send", "1"))
    assert b.app.pane.typed == ["1"]


def test_a_local_pane_is_typed_into_as_before(monkeypatch, tmp_path):
    b = bridge_over(monkeypatch, tmp_path, "blocked")
    asyncio.run(b.act("abc", "send", "3use the other one\n"))
    assert b.app.pane.typed == ["3use the other one", "\r"]
```

`tests/test_notify.py`:

```python
def test_a_remote_question_offers_buttons_and_no_reply_field():
    argv = sidebar.notify_argv("/Applications/N.app", "s1", "atlas", "blocked",
                               {"question": "Which one?", "options": ["This", "That"]}, remote=True)
    assert "--button" in argv and "--reply" not in argv


def test_a_remote_finished_turn_offers_no_next_prompt():
    argv = sidebar.notify_argv("/Applications/N.app", "s1", "atlas", "done", None, remote=True)
    assert "--reply" not in argv
```

`tests/test_links.py`, beside the `own_refusal` tests (`row` is its end builder):

```python
def test_a_remote_session_cannot_be_an_end_of_a_link():
    assert links.own_refusal(dict(row("p1", "a"), host="box"), lambda agent: True) == (
        "a remote session cannot be linked yet")
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 ~/.local/share/mise/installs/python/3.11.14/bin/python -m pytest tests/test_prompt_guard.py tests/test_notify.py tests/test_links.py -q --color=no`
Expected: FAIL (`cannot import name 'typing_refusal'`, `unexpected keyword argument 'remote'`, text typed into the fake session).

- [ ] **Step 3: Implement the rules** (`sidebar_rules.py`)

```python
REMOTE_NO_REPLY = "replies do not reach a remote session yet"
```

In `prompt_refusal`, after the `row is None` check:

```python
    if row.get("host"):
        return REMOTE_NO_REPLY
```

and extend its docstring: nothing on this machine can tell whether a line typed into a remote pane reaches the agent or a shell.

```python
def typing_refusal(row, strokes):
    """Why these writes may not be typed into the row's pane, or None. Only a remote row is judged here.

    Every write the daemon makes into a pane passes this. A remote pane
    takes one key that is not Enter, while it waits on you and its own
    checks hold (`remote_refusal`): an answer's digit, y or Escape. A line,
    or any text, could be run by a shell there.
    """
    if row is None or not row.get("host"):
        return None
    keys = "".join(strokes)
    if len(keys) != 1 or keys in "\r\n":
        return REMOTE_NO_REPLY
    if row.get("state") != "blocked":
        return "it is not waiting on you"
    return row.get("remote_refusal")
```

- [ ] **Step 4: Implement the chokepoint** (`sidebar.py`)

```python
    async def type_keys(self, session, session_id, strokes, pause=0):
        """Type into a pane. The only place the daemon does: a remote pane's
        rule (typing_refusal) is asked here, against the last frame."""
        refusal = typing_refusal(find_row(self.latest, session_id), strokes)
        if refusal:
            self.log("typing refused", session_id[:8], refusal)
            return False
        for stroke in strokes:
            await session.async_send_text(stroke)
            if pause:
                await asyncio.sleep(pause)
        return True
```

- `act`, the `send`/`prompt` branch: `await self.type_keys(session, session_id, keystrokes(text or ""), pause=0.05)`.
- `resume`: `await self.type_keys(session, session_id, [command + "\n"])`; when it returns False, drop the `self.resuming` entry it just made and return.
- `answer_from_card`: after `keys` is known and before `self.answered` is set,

```python
        if typing_refusal(find_row(self.latest, session_id), [keys]):
            self.log("answer refused", session_id[:8], repr(text))
            return
```

then type through `type_keys`.

After this, `rg -n 'async_send_text' sidebar.py` must show one line, inside `type_keys`. Add that as a test in `tests/test_prompt_guard.py`:

```python
def test_the_daemon_types_in_one_place():
    source = (Path(__file__).resolve().parent.parent / "sidebar.py").read_text()
    assert source.count("async_send_text(") == 1
```

`notify_argv`: add `remote=False`; skip both `--reply` arguments when it is true. `notify`: pass `remote=bool(row.get("host"))`.

`link_end`: add `"host": frame_row.get("host")`. `links.own_refusal`, first line of the body:

```python
    if end.get("host"):
        return "a remote session cannot be linked yet"
```

- [ ] **Step 5: Run the tests**

Run the command from Step 2, then the whole suite. Expected: exit code 0.

- [ ] **Step 6: Review the diff as a trust boundary**

Text from another machine now reaches the frame (`host`, the question's text and labels, `cwd`). Read the diff of Tasks 4 and 5 for: any of the three reaching an argument list, a path opened, or `innerHTML`; any write into a pane outside `type_keys`. Report what was found before Task 6.

- [ ] **Step 7: Commit**

```bash
git add sidebar.py sidebar_rules.py links.py tests/test_prompt_guard.py tests/test_notify.py tests/test_links.py
git commit -m "Daemon: every write into a pane goes through one place; a remote pane takes one key under its checks, and no reply, resume or link"
```

---

### Task 6: The page

**Files:**
- Modify: `page.html` (CSS beside `.remote-mark` near line 703, the row builder near line 4790, the question block near 5018)
- Modify: `assets/make-card-anatomy.py`, `assets/card-anatomy.svg`, `tests/test_figures.py` if it counts marks
- Create: `.cs/local/host_mark_variants.mjs`, `.cs/local/e2e_host_mark.mjs` (session files, not committed)

**Interfaces:**
- Consumes: frame rows' `host`, `remote_refusal`, `state`, `question`.
- Produces: `.host-mark` on a row with `host`; `p.refusal.question-standing` under a remote row that is blocked with no question.

- [ ] **Step 1: The variant round (a gate: the look is picked from renders, not described)**

Base `.cs/local/host_mark_variants.mjs` on `.cs/local/rc_variants.mjs` (CDP over headless Chrome, a live `/events` frame, 380 px, `deviceScaleFactor: 2`, dark and light). Give one live agent row `host: "box"` and render four placements: (A) the host as a small tag at the end of the facts line, in the facts line's grey; (B) a glyph after the name with the host as its title; (C) the host as a prefix of the label, "box · atlas", the prefix in grey; (D) a glyph in the corner beside the provider mark with the host in the facts line. No left accent bar, no new colour, no motion. Ask which one, with the image; build only the one picked. Steps 2 to 4 below are written for (A) and are adjusted to the pick.

- [ ] **Step 2: Write the E2E first** (`.cs/local/e2e_host_mark.mjs`)

After loading a live frame and patching one agent row:

1. `host: "box"` -> the row holds one `.host-mark` whose text is `box`, computed colour equal to the facts line's, and the row button's `aria-label` contains `on box`.
2. No `host` -> no `.host-mark`.
3. `host` set to 64 characters -> the mark is clipped inside the row (its right edge is left of the row's right edge) and no horizontal scroll appears.
4. `host: "<img src=x onerror=alert(1)>"` -> the mark's `textContent` is that string and the row contains no `img` element.
5. `host: "box"`, `state: "blocked"`, a `question` with two options -> two `button.answer` elements, as on a local card.
6. `host: "box"`, `state: "blocked"`, no `question` -> `p.refusal.question-standing` with text exactly `A question is waiting in the pane`, and no `button.answer`.
7. Cases 1 and 6 again with `prefers-color-scheme: light`.

Run it against the unchanged page first. Expected: cases 1, 3, 4, 6 and 7 fail.

- [ ] **Step 3: Implement in `page.html`**

CSS beside `.remote-mark`:

```css
  /* The agent runs on another machine: its host, in the facts line's grey. */
  .host-mark { flex: none; max-width: 12ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
               color: var(--dim); }
```

In the row builder, after the facts line `meta` (the `span` made near line 4843) has its chips, append when `row.host`:

```js
      if (row.host) {
        const host = Object.assign(document.createElement("span"), {className: "host-mark", textContent: row.host});
        host.title = `Runs on ${row.host}`;
        host.dataset.spoken = `on ${row.host}`;
        meta.append(host);
      }
```

The row's `aria-label` already gathers every `[data-spoken]` inside the row (near line 4983), so the mark is spoken with no more code.

Beside `remoteLostLine`:

```js
// A remote card that waits on you with no question the panel could carry: the pane has it.
function questionStandingLine(row) {
  if (!row.host || row.state !== "blocked" || row.question) return null;
  const line = Object.assign(document.createElement("p"), {className: "refusal question-standing",
                             textContent: "A question is waiting in the pane"});
  line.setAttribute("role", "status");
  return line;
}
```

and append its result where `remoteLostLine(row)`'s is appended (near line 5001).

- [ ] **Step 4: Run the E2E and the page's tests**

Run `.cs/local/e2e_host_mark.mjs` (all cases pass), then `tests/test_page_*.py` and `tests/test_figures.py`. The page's endless motion stays transform and opacity only (`tests/test_page_motion_cost.py`); this adds none.

- [ ] **Step 5: The figure**

Add the host mark to one card in `assets/make-card-anatomy.py`, regenerate `assets/card-anatomy.svg`, and update the README's alt text if `tests/test_figures.py` asks.

- [ ] **Step 6: Commit**

```bash
git add page.html assets/make-card-anatomy.py assets/card-anatomy.svg tests/test_figures.py README.md
git commit -m "Page: a remote card names its host, and says when a question waits in the pane"
```

---

### Task 7: Docs, the live run, the final review

**Files:**
- Modify: `README.md`, `docs/usage.md`, `docs/development.md` (the plan's link)
- Create: `.cs/local/e2e_remote_panes.py` (session file, not committed), `.cs/local/remote-panes-run.md` (the recorded result)

- [ ] **Step 1: Docs**

README, a section "Sessions on another machine": what a remote card shows (state, timers, host, folder, a standing question with its buttons, a subagent count) and what it does not until the next slice (model, context, cost, tasks, branch, usage, Remote Control, links, Reply, Resume; Codex sessions). ssh and Eternal Terminal are supported, with or without tmux there; mosh is not. An answer types one key and only while four things hold, named in plain words; the title check depends on the remote prompt setting a title, and where it sets none a key can land on a shell line after the agent died, with no Enter. How a second machine gets the hooks: the `plugin/` folder of a tagged release placed at `~/.claude/skills/agents-sidebar` by a dotfiles manager; no daemon is installed there; a hook older than this release shows remote cards as before. Verify each sentence against the code, not against the spec.

Link this plan from `docs/development.md` beside the other plans (`tests/test_docs.py` requires it).

- [ ] **Step 2: Put the built hook on the second machine (a gate: ask first)**

The live run needs this branch's `plugin/` at `~/.claude/skills/agents-sidebar` on the second machine. That writes into another machine's `~/.claude`; ask before doing it, name the exact command (`rsync -a --delete plugin/ "$REMOTE":.claude/skills/agents-sidebar/`), and say how it is undone (remove the folder).

Then confirm Claude Code there loads it before anything is measured: start a throwaway session there and read the last line of its `~/.claude/agents-sidebar-events.jsonl`; a `SessionStart` line stamped within the last minute is the proof. Without one the hook is not loaded (the plugin may need enabling there), and the live run stops here with that said, since every later check would fail and read like a daemon fault. With the session up, read `ps -o tpgid=,pgid=` for the agent once under a `cs` wrapper too, which the spec's check 4 left unmeasured.

- [ ] **Step 3: The live script** (`.cs/local/e2e_remote_panes.py`, iTerm2 Python, `REMOTE` from the environment)

Each check prints `ok` or `FAIL` with what it saw, and the script exits non-zero on any failure. Windows it opens are created with `command="/bin/zsh -l"` after `async_get_app`, and every one is closed in `finally`; remote processes it starts are killed by pid.

Over ssh, then over et:
1. Start a real Claude session there in a trusted folder (`--setting-sources user`, a cheap model). The frame row for the pane has `host` equal to the remote short name, `path` equal to the remote folder, state `idle`, no `tty`-keyed facts (`model`, `branch`, `usage` absent).
2. Send a prompt that makes it ask one AskUserQuestion with two options. The row turns `blocked` with the question and both labels; `remote_refusal` is absent. Answer option 2 from the daemon (`POST /action`, verb `answer`); the session's transcript there shows option 2 chosen.
3. Raise 50 questions in a row (a prompt that loops) and count the frames where the question arrived whole: 50 of 50. This is the spec's check 3 with the real hook.
4. With a question standing, suspend the transport (`~^Z` for ssh; for et, stop the client with SIGSTOP and bring the shell forward): the row reads `unknown`, `POST /action` `answer` types nothing, the daemon log says `typing refused`.
5. With a question standing, `kill -9` the agent there: once the prompt repaints the title, `remote_refusal` is "the agent's title has gone from the pane" and an answer types nothing.
6. `POST /action` verb `prompt` on the remote row answers 409 with "replies do not reach a remote session yet".
7. Remote `tmux -CC`: open panes until a number collides with a local pane; the remote pane's row has the remote folder and host, and the local pane's row is unchanged.

Then the spec's check 7, by hand: with an et pane showing a remote card, break the second machine's network for about 20 seconds. Record `jobName` and the card's state during and after.

- [ ] **Step 4: Record the run**

Write the script's output and the check-7 readings to `.cs/local/remote-panes-run.md`, and put the measured results into the spec's section 7 (check 3 with the real hook, check 7).

- [ ] **Step 5: Whole suite, then one reviewer on the whole branch**

Run the Python suite; expected exit code 0. Then one fresh reviewer on the most capable model reads the branch against the spec, given the spec and the diff and not this plan's reasoning. Fix what it finds; anything that changes a decision goes back for a decision first.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/usage.md docs/development.md docs/superpowers/specs/2026-10-11-remote-panes-design.md
git commit -m "Docs: sessions on another machine; the remote panes checks measured with the real hook"
```

---

## After the release (the dotfiles repository, not this one)

A separate change, made once a release carries this plugin, and only with a yes at that time:

1. A dotfiles external that unpacks `plugin/` of the release tag into `~/.claude/skills/agents-sidebar` on every machine except the one that runs `install.sh`, pinned to the tag.
2. The status line setting made per-machine: it names a path inside this checkout, which exists on one machine.
3. On each other machine: apply, then `/reload-plugins` in running sessions.

## Not in this plan

- The relay (Reply, tasks, subagents, model and context, Codex, sessions with no pane here). Its own spec.
- A second tmux server on this machine colliding with the first: both are local, and the local table is still keyed by number.
- mosh.
