# ABOUTME: Tests for the daemon's ports on cards: the timed listener reading, the card each listener lands on, and every
# ABOUTME: check a Stop and an Open pass. The reading runs real lsof and ps on servers the tests start; refusals stub them.
import asyncio
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ports
import sidebar


class Quiet:
    def broadcast(self, frame):
        pass


def done(stdout="", code=0, stderr=""):
    return types.SimpleNamespace(stdout=stdout, returncode=code, stderr=stderr)


def log():
    path = Path(sidebar.STATUS_DIR) / "daemon.log"
    return [line.split(" ", 2)[2] for line in path.read_text().splitlines()] if path.exists() else []


# A server binds a port of its own choosing, says which in a file, and waits.
LISTENER = """
import os, socket, sys, time
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen()
with open(sys.argv[1] + ".part", "w") as said:
    said.write(f"{os.getpid()} {server.getsockname()[1]}")
os.rename(sys.argv[1] + ".part", sys.argv[1])
time.sleep(120)
"""
# A stand-in for an agent: it listens itself, as Claude Code's own sockets do,
# runs one server under it, and leaves one running with nohup, as an agent's
# Bash tool does with `cmd &`. Both inherit CLAUDE_PID, which Claude Code sets.
AGENT = """
import os, socket, subprocess, sys, time
listener, out = sys.argv[1], sys.argv[2]
own = socket.socket()
own.bind(("127.0.0.1", 0))
own.listen()
env = {**os.environ, "CLAUDE_PID": str(os.getpid())}
subprocess.Popen([sys.executable, listener, out + "/in-tree"], env=env)
subprocess.run(["/bin/sh", "-c", 'nohup "$0" "$1" "$2" >/dev/null 2>&1 &', sys.executable, listener, out + "/detached"],
               env=env, check=True)
with open(out + "/agent.part", "w") as said:
    said.write(f"{os.getpid()} {own.getsockname()[1]}")
os.rename(out + "/agent.part", out + "/agent")
time.sleep(120)
"""


def told(out, name):
    pid, port = (out / name).read_text().split()
    return int(pid), int(port)


@pytest.fixture
def servers(tmp_path):
    """A fake agent with a server in its tree and one it left running, a
    server no agent started whose argv carries CLAUDE_PID=<the agent's pid>,
    and one whose environment sets CLAUDE_PID to more digits than any pid."""
    listener, agent = tmp_path / "listener.py", tmp_path / "agent.py"
    listener.write_text(LISTENER)
    agent.write_text(AGENT)
    clean = {k: v for k, v in os.environ.items() if k != "CLAUDE_PID"}
    running = subprocess.Popen([sys.executable, str(agent), str(listener), str(tmp_path)], env=clean)
    names = ["agent", "in-tree", "detached", "forged", "garbled"]
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "agent").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        agent_pid = told(tmp_path, "agent")[0]
        subprocess.run(["/bin/sh", "-c", 'nohup "$0" "$1" "$2" "$3" >/dev/null 2>&1 &', sys.executable,
                        str(listener), str(tmp_path / "forged"), f"CLAUDE_PID={agent_pid}"], env=clean, check=True)
        subprocess.run(["/bin/sh", "-c", 'nohup "$0" "$1" "$2" >/dev/null 2>&1 &', sys.executable,
                        str(listener), str(tmp_path / "garbled")], env={**clean, "CLAUDE_PID": "9" * 5000}, check=True)
        while not all((tmp_path / name).exists() for name in names) and time.monotonic() < deadline:
            time.sleep(0.05)
        found = {name: told(tmp_path, name) for name in names}
        yield found
    finally:
        running.terminate()
        running.wait()
        for name in names[1:]:
            if (tmp_path / name).exists():
                try:
                    os.kill(told(tmp_path, name)[0], signal.SIGTERM)
                except ProcessLookupError:
                    pass


def system():
    """This moment's process listing, as a rebuild reads it."""
    listing = sidebar.read_process_listing()
    return sidebar.parse_resources(listing), sidebar.parse_processes(listing)[1], sidebar.parse_args(listing)


def card_rows(agent_pid, started):
    return [{"session_id": "pane-a", "agent_pid": agent_pid, "started_at": started[agent_pid], "conversation": None},
            {"session_id": "pane-z", "agent_pid": None, "started_at": None, "conversation": None}]


def place(b, rows, table, started, args, jobs=()):
    asyncio.run(b.place_ports(rows, table, started, args, list(jobs)))


def test_a_card_shows_the_servers_its_agent_runs_and_left_running_and_no_forged_or_own_socket(servers):
    """A CLAUDE_PID that is no pid names no agent and leaves nothing to say."""
    agent, in_tree, detached, forged, garbled = (servers[name] for name in
                                                 ("agent", "in-tree", "detached", "forged", "garbled"))
    table, started, args = system()
    # Left running with nohup, it is launchd's child, outside the agent's tree.
    assert table[detached[0]][0] == 1 and table[forged[0]][0] == 1 and table[garbled[0]][0] == 1
    b = sidebar.Bridge(None, Quiet())
    rows = card_rows(agent[0], started)
    place(b, rows, table, started, args)
    expected = sorted([{"port": port, "addresses": ["127.0.0.1"], "pid": pid, "program": "listener.py",
                        "kind": "python", "started_at": started[pid]} for pid, port in (in_tree, detached)],
                      key=lambda p: p["port"])
    assert [row["ports"] for row in rows] == [expected, []]
    assert b.ports == {(p["pid"], p["port"], p["started_at"]): p for p in expected}
    assert log() == []


def test_a_listener_read_once_shows_on_its_card_till_its_process_exits(servers):
    """Launchd reaps the server left running at once; the agent's own child would stay a zombie in ps."""
    agent, detached = servers["agent"], servers["detached"]
    table, started, args = system()
    b = sidebar.Bridge(None, Quiet())
    place(b, card_rows(agent[0], started), table, started, args)
    os.kill(detached[0], signal.SIGTERM)
    deadline = time.monotonic() + 5
    while detached[0] in system()[1] and time.monotonic() < deadline:
        time.sleep(0.05)
    table, started, args = system()
    rows = card_rows(agent[0], started)
    place(b, rows, table, started, args)
    assert [p["pid"] for p in rows[0]["ports"]] == [servers["in-tree"][0]]


def test_the_reading_is_taken_at_most_once_every_five_seconds(servers, monkeypatch):
    real_run, readings = subprocess.run, []

    def run(argv, **kwargs):
        if argv == ports.LISTENERS:
            readings.append(time.monotonic())
        return real_run(argv, **kwargs)
    monkeypatch.setattr(sidebar.subprocess, "run", run)
    table, started, args = system()
    b = sidebar.Bridge(None, Quiet())
    for _ in range(3):
        place(b, card_rows(servers["agent"][0], started), table, started, args)
    assert len(readings) == 1
    b.listening_at -= sidebar.PORTS_READ_SECONDS
    place(b, card_rows(servers["agent"][0], started), table, started, args)
    assert len(readings) == 2


def test_a_stop_sends_sigterm_to_a_real_server_after_its_checks_and_it_leaves_its_card(servers):
    agent, detached = servers["agent"], servers["detached"]
    table, started, args = system()
    b = sidebar.Bridge(None, Quiet())
    b.loop = asyncio.new_event_loop()
    try:
        place(b, card_rows(agent[0], started), table, started, args)
        b.stop_port(detached[0], detached[1], started[detached[0]])
        deadline = time.monotonic() + 5
        while detached[0] in system()[1] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert detached[0] not in system()[1]
        assert log() == [f"stop-port {detached[0]} :{detached[1]} listener.py"]
    finally:
        b.loop.close()


# The daemon's own reading, off a listing it was handed: lsof and the kernel's
# argument block are stubbed, so every way they fail can be had on demand.
AGENT_PID, SERVER, LEFT = 500, 4100, 4300
TABLE = {300: (1, 0.0, 1000, None), AGENT_PID: (300, 0.0, 1000, None), 4000: (AGENT_PID, 0.0, 1000, None),
         SERVER: (4000, 0.0, 1000, None), LEFT: (1, 0.0, 1000, None)}
STARTED = {300: 1789640000, AGENT_PID: 1789640000, 4000: 1789646000, SERVER: 1789646400, LEFT: 1789646500}
ARGS = {300: "-zsh", AGENT_PID: "claude --name alpha", 4000: "/bin/zsh -c npm run dev",
        SERVER: "node /work/app/node_modules/.bin/vite --port 5173 --token s3cr3t", LEFT: "node /work/api/server.js"}
LSOF = ("p500\0c2.1.318\0\nf40\0n127.0.0.1:58932\0\n"
        "p4100\0cnode\0\nf21\0n*:5173\0\nf22\0n[::1]:5173\0\n"
        "p4300\0cnode\0\nf12\0n127.0.0.1:3000\0\n")
ROWS = [{"session_id": "pane-a", "agent_pid": AGENT_PID, "started_at": 1789640000, "conversation": "conv-a"}]
VITE = {"port": 5173, "addresses": ["*", "[::1]"], "pid": SERVER, "program": "vite", "kind": "js",
        "started_at": 1789646400}
API = {"port": 3000, "addresses": ["127.0.0.1"], "pid": LEFT, "program": "server.js", "kind": "js",
       "started_at": 1789646500}


def stubbed(monkeypatch, lsof, inherited):
    """A Bridge whose lsof answers `lsof` and whose environment reads answer `inherited`: pid -> agent pid or error."""
    def run(argv, **_):
        if argv != ports.LISTENERS:
            raise AssertionError(f"the reading ran {argv}")
        if isinstance(lsof, BaseException):
            raise lsof
        return done(lsof)

    def agent_of(pid):
        answer = inherited[pid]
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(sidebar.subprocess, "run", run)
    monkeypatch.setattr(sidebar.ports, "inherited_agent", agent_of)
    return sidebar.Bridge(None, Quiet())


def placed(b):
    rows = [dict(row) for row in ROWS]
    place(b, rows, TABLE, STARTED, ARGS)
    b.listening_at -= sidebar.PORTS_READ_SECONDS
    return rows[0]["ports"]


def test_the_frame_names_each_listener_by_port_program_kind_addresses_pid_and_start_and_never_its_command(monkeypatch):
    b = stubbed(monkeypatch, LSOF, {LEFT: AGENT_PID})
    assert placed(b) == [API, VITE]


def test_the_environment_is_read_only_for_a_listener_outside_every_tree_and_once_per_process(monkeypatch):
    asked = []
    b = stubbed(monkeypatch, LSOF, {LEFT: AGENT_PID})
    monkeypatch.setattr(sidebar.ports, "inherited_agent", lambda pid: asked.append(pid) or AGENT_PID)
    placed(b)
    placed(b)
    assert asked == [LEFT]


@pytest.mark.parametrize("lsof, inherited, line", [
    (FileNotFoundError(2, "No such file or directory"), {},
     "ports not read: could not run lsof: [Errno 2] No such file or directory"),
    ("p4100\0cnode\0\nf21\0nlocalhost\0\n", {},
     "ports not read: could not read lsof: lsof listed 'localhost' for pid 4100, which names no port"),
])
def test_a_reading_that_fails_shows_no_card_a_port_and_says_why_once(monkeypatch, lsof, inherited, line):
    b = stubbed(monkeypatch, lsof, inherited)
    assert (placed(b), placed(b), b.ports, log()) == ([], [], {}, [line])


@pytest.mark.parametrize("error, reason", [
    (OSError(22, "Invalid argument"), "[Errno 22] Invalid argument"),
    (ValueError("the kernel's argument block ends after 2 of its 3 arguments"),
     "the kernel's argument block ends after 2 of its 3 arguments"),
])
def test_a_listener_whose_environment_cannot_be_read_is_on_no_card_the_rest_are_and_it_is_said_once(
        monkeypatch, error, reason):
    # The process whose environment could not be read is still there.
    monkeypatch.setattr(sidebar.os, "kill", lambda pid, sig: None)
    b = stubbed(monkeypatch, LSOF, {LEFT: error})
    assert (placed(b), placed(b), [key[:2] for key in b.ports], log()) == (
        [VITE], [VITE], [(SERVER, 5173)],
        [f"ports: could not read the environment of pid {LEFT}, so no card shows its ports: {reason}"])


def test_a_failure_after_a_good_reading_shows_none_of_it_and_is_said_again(monkeypatch):
    """Never the old reading passed off as current."""
    b = stubbed(monkeypatch, FileNotFoundError(2, "No such file or directory"), {})
    shown = [placed(b)]
    stubbed(monkeypatch, LSOF, {LEFT: AGENT_PID})
    shown.append(placed(b))
    stubbed(monkeypatch, FileNotFoundError(2, "No such file or directory"), {})
    shown.append(placed(b))
    assert (shown, b.ports) == ([[], [API, VITE], []], {})
    assert log() == ["ports not read: could not run lsof: [Errno 2] No such file or directory"] * 2


def test_a_listener_gone_before_its_environment_was_read_is_left_out_and_the_rest_shown(monkeypatch):
    def gone(pid, sig):
        raise ProcessLookupError(3, "No such process")
    monkeypatch.setattr(sidebar.os, "kill", gone)
    b = stubbed(monkeypatch, LSOF, {LEFT: OSError(22, "Invalid argument")})
    assert (placed(b), log()) == ([VITE], [])


def test_a_codex_job_its_session_runs_holds_its_servers_for_the_card_and_its_own_socket_is_hidden(monkeypatch):
    jobs = [{"id": "job-1", "session": "conv-a", "status": "running", "pid": 700},
            {"id": "job-0", "session": "conv-a", "status": "completed", "pid": LEFT}]
    table = {**TABLE, 700: (1, 0.0, 1000, None), 4400: (700, 0.0, 1000, None)}
    started = {**STARTED, 700: 1789646000, 4400: 1789646600}
    args = {**ARGS, 700: "/usr/local/bin/codex app-server", 4400: "node /work/api/worker.js"}
    lsof = LSOF + "p700\0ccodex\0\nf9\0n127.0.0.1:61000\0\np4400\0cnode\0\nf3\0n127.0.0.1:3001\0\n"
    b = stubbed(monkeypatch, lsof, {LEFT: None})
    rows = [dict(row) for row in ROWS]
    asyncio.run(b.place_ports(rows, table, started, args, jobs))
    assert [(p["pid"], p["port"]) for p in rows[0]["ports"]] == [(4400, 3001), (SERVER, 5173)]


# A Stop names a listener of the last reading. Its pid is past macOS's
# highest, so a stub that failed to take kill's place would signal nothing.
PID = 400100
START = 1789646400
LAST = {"port": 5173, "addresses": ["*"], "pid": PID, "program": "vite", "kind": "js", "started_at": START}
LISTENING = f"p{PID}\0\nf21\0\n"


def stopping(monkeypatch, holder=done(LISTENING), lstart=done("Thu Sep 17 12:00:00 2026    \n"), kill=None):
    """A Bridge whose last reading is LAST on alpha's card, with lsof's holder check, ps's start and kill stubbed."""
    killed = []

    def run(argv, **_):
        if argv == ports.holder_check(PID, 5173):
            answer = holder
        elif argv == ["/bin/ps", "-o", "lstart=", "-p", str(PID)]:
            answer = lstart
        else:
            raise AssertionError(f"stop_port ran {argv}")
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def record(pid, sig):
        killed.append((pid, sig))
        if kill:
            raise kill

    monkeypatch.setattr(sidebar.subprocess, "run", run)
    monkeypatch.setattr(sidebar.os, "kill", record)
    b = sidebar.Bridge(None, Quiet())
    b.rows = [{"session_id": "pane-a", "agent_pid": 500}, {"session_id": "pane-b", "agent_pid": 800}]
    b.latest = {"groups": [{"name": "AGENTS", "rows": [{"session_id": "pane-a", "label": "alpha"},
                                                        {"session_id": "pane-b", "label": "beta"}]}]}
    b.ports = {(PID, 5173, START): dict(LAST)}
    # The loop that would read again a second later; the timing has a test of its own on a real loop.
    b.loop = types.SimpleNamespace(call_later=None, call_soon_threadsafe=lambda *call: None)
    return b, killed


def test_a_stop_of_a_holder_still_listening_since_its_start_sends_sigterm_once(monkeypatch, utc):
    b, killed = stopping(monkeypatch)
    b.stop_port(PID, 5173, START)
    assert killed == [(PID, signal.SIGTERM)]
    assert log() == [f"stop-port {PID} :5173 vite"]
    # Spent: a second click waits for the reading after the signal.
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, START)
    assert (str(refused.value), killed) == ("already stopping", [(PID, signal.SIGTERM)])


async def test_a_stop_reads_the_ports_again_a_second_later(monkeypatch, utc):
    b, _ = stopping(monkeypatch)
    b.loop = asyncio.get_running_loop()
    b.listening_at = time.monotonic()
    rebuilt = []

    async def rebuild():
        rebuilt.append((time.monotonic(), b.listening_at))
    b.rebuild_or_report = rebuild
    sent = time.monotonic()
    await asyncio.to_thread(b.stop_port, PID, 5173, START)
    await asyncio.sleep(0.5)
    assert rebuilt == []
    # The floor proves the wait; the ceiling leaves room for a loaded machine.
    while not rebuilt and time.monotonic() - sent < 2.5:
        await asyncio.sleep(0.05)
    assert len(rebuilt) == 1 and rebuilt[0][1] is None and 0.95 <= rebuilt[0][0] - sent < 2.5


def test_the_next_reading_takes_the_spent_mark_off_a_holder_that_is_still_listening(monkeypatch, utc):
    """It ignored SIGTERM: once the ports are read again, its card offers Stop again and the daemon sends it."""
    b, killed = stopping(monkeypatch)
    b.stop_port(PID, 5173, START)
    checks = sidebar.subprocess.run

    def run(argv, **kwargs):
        return done(f"p{PID}\0cnode\0\nf21\0n*:5173\0\n") if argv == ports.LISTENERS else checks(argv, **kwargs)
    monkeypatch.setattr(sidebar.subprocess, "run", run)
    rows = [{"session_id": "pane-a", "agent_pid": 500, "started_at": START - 600, "conversation": None}]
    place(b, rows, {500: (1, 0.0, 1, None), PID: (500, 0.0, 1, None)}, {500: START - 600, PID: START},
          {500: "claude", PID: "node vite"})
    b.stop_port(PID, 5173, START)
    assert killed == [(PID, signal.SIGTERM)] * 2


@pytest.mark.parametrize("ask", [(PID, 5174, START), (PID, 5173, START + 1), (PID + 1, 5173, START)])
def test_a_stop_of_a_listener_the_last_reading_does_not_hold_is_refused(monkeypatch, utc, ask):
    b, killed = stopping(monkeypatch)
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(*ask)
    assert (str(refused.value), killed) == ("not in the last reading", [])


def test_a_holder_that_became_a_cards_agent_since_the_reading_is_refused(monkeypatch, utc):
    b, killed = stopping(monkeypatch)
    b.rows[0]["agent_pid"] = PID
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, START)
    assert (str(refused.value), killed) == ("alpha's agent", [])


@pytest.mark.parametrize("checks, reason", [
    ({"holder": done("", code=1)}, "no longer listening on :5173"),
    ({"holder": FileNotFoundError(2, "No such file or directory")}, "could not check: [Errno 2] No such file or directory"),
    ({"holder": subprocess.TimeoutExpired(["lsof"], 5)},
     "could not check: Command '['lsof']' timed out after 5 seconds"),
    ({"lstart": done("Thu Sep 17 12:30:00 2026    \n")}, f"pid {PID} is another program now"),
    ({"lstart": done("", code=1)}, "already gone"),
    ({"lstart": PermissionError(1, "Operation not permitted")}, "could not check: [Errno 1] Operation not permitted"),
])
def test_a_stop_whose_holder_changed_since_the_reading_is_refused_before_any_signal(monkeypatch, utc, checks, reason):
    b, killed = stopping(monkeypatch, **checks)
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, START)
    assert (str(refused.value), killed, log()) == (reason, [], [])


@pytest.mark.parametrize("error, reason", [
    (ProcessLookupError(3, "No such process"), "already gone"),
    (PermissionError(1, "Operation not permitted"), "not yours to stop"),
])
def test_a_signal_the_system_refuses_says_why(monkeypatch, utc, error, reason):
    b, killed = stopping(monkeypatch, kill=error)
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, START)
    assert (str(refused.value), killed, log()) == (reason, [(PID, signal.SIGTERM)], [])


def opening(monkeypatch, answer=done()):
    """A Bridge whose last reading is LAST, with `open` stubbed: no test opens a browser."""
    opened = []

    def run(argv, **kwargs):
        opened.append(argv)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(sidebar.subprocess, "run", run)
    b = sidebar.Bridge(None, Quiet())
    b.ports = {(PID, 5173, START): dict(LAST)}
    return b, opened


def test_open_sends_the_browser_to_the_listeners_port_on_localhost(monkeypatch):
    b, opened = opening(monkeypatch)
    b.open_port(PID, 5173, START)
    assert opened == [["open", "http://localhost:5173"]]


@pytest.mark.parametrize("answer, ask, reason", [
    (done(), (PID, 5173, START + 1), "not in the last reading"),
    (subprocess.CalledProcessError(1, ["open"], stderr="LSOpenURLsWithRole() failed\n"), (PID, 5173, START),
     "could not open http://localhost:5173: LSOpenURLsWithRole() failed"),
    (FileNotFoundError(2, "No such file or directory"), (PID, 5173, START),
     "could not open http://localhost:5173: [Errno 2] No such file or directory"),
])
def test_an_open_the_daemon_cannot_make_says_why(monkeypatch, answer, ask, reason):
    b, opened = opening(monkeypatch, answer)
    with pytest.raises(ports.Refused) as refused:
        b.open_port(*ask)
    assert str(refused.value) == reason
