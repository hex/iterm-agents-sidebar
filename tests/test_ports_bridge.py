# ABOUTME: Tests for the daemon's Ports reading and its Stop: which listeners it lists, under which session,
# ABOUTME: and every check a Stop passes before SIGTERM. lsof, ps and kill are stubbed; nothing is signalled.
import os
import signal
import subprocess
import sys
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


DAEMON = os.getpid()
ROW = "{pid} {parent} {pid} 0 ?? {start} 0.0 1000 {args}\n"
LISTING = "".join(ROW.format(pid=pid, parent=parent, start=start, args=args) for pid, parent, start, args in [
    (300, 1, "Thu Sep 17 12:00:00 2026", "-zsh"),
    (500, 300, "Thu Sep 17 12:00:00 2026", "claude --name alpha"),
    (4000, 500, "Thu Sep 17 12:00:00 2026", "/bin/zsh -c npm run dev"),
    (4100, 4000, "Thu Sep 17 12:00:00 2026", "node /work/app/node_modules/.bin/vite --port 5173"),
    (800, 1, "Thu Sep 17 12:00:00 2026", "claude --name beta"),
    (700, 1, "Thu Sep 17 12:00:00 2026", "/usr/local/bin/codex app-server"),
    (4300, 700, "Thu Sep 17 12:00:00 2026", "node /work/api/server.js"),
    (4200, 1, "Thu Sep 17 11:00:00 2026",
     "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
     " /opt/tools/serve.py --token s3cr3t"),
    (900, 1, "Thu Sep 17 11:00:00 2026", "/System/Library/CoreServices/ControlCenter.app/Contents/MacOS/ControlCenter"),
    (DAEMON, 1, "Thu Sep 17 11:00:00 2026", "/venvs/3.10/bin/python /Scripts/AutoLaunch/agents_sidebar.py"),
])
LSOF = (f"p500\0c2.1.318\0\nf40\0n127.0.0.1:58932\0\n"
        f"p4100\0cnode\0\nf21\0n*:5173\0\nf22\0n[::1]:5173\0\n"
        f"p700\0ccodex\0\nf9\0n127.0.0.1:61000\0\n"
        f"p4300\0cnode\0\nf12\0n127.0.0.1:3000\0\n"
        f"p4200\0cPython\0\nf4\0n127.0.0.1:8787\0\n"
        f"p900\0cControlCenter\0\nf9\0n*:7000\0\n"
        f"p{DAEMON}\0cpython3.10\0\nf7\0n127.0.0.1:60912\0\n")
JOBS = [
    {"id": "job-1", "session": "conv-b", "kind": "rescue", "status": "running", "phase": None, "pid": 700,
     "since": None, "ended": None, "thread": None},
    # A job that ended: its pid may be anyone's now.
    {"id": "job-0", "session": "conv-b", "kind": "rescue", "status": "completed", "phase": None, "pid": 4200,
     "since": None, "ended": None, "thread": None},
]


def bridge():
    b = sidebar.Bridge(None, Quiet())
    b.rows = [{"session_id": "pane-a", "agent_pid": 500, "conversation": "conv-a"},
              {"session_id": "pane-b", "agent_pid": 800, "conversation": "conv-b"},
              {"session_id": "pane-c", "agent_pid": None, "conversation": None}]
    b.latest = {"groups": [{"name": "AGENTS", "rows": [{"session_id": "pane-a", "label": "alpha"},
                                                        {"session_id": "pane-b", "label": "beta"}]},
                           {"name": "SESSIONS", "rows": [{"session_id": "pane-c", "label": "zsh"}]}]}
    return b


def reading(monkeypatch, lsof):
    """read_ports over the listing above, with `lsof` standing for what lsof does."""
    def run(argv, **_):
        if argv == ports.LISTENERS:
            return lsof() if callable(lsof) else lsof
        if argv == sidebar.PROCESS_LISTING:
            return done(LISTING)
        raise AssertionError(f"read_ports ran {argv}")
    monkeypatch.setattr(sidebar.subprocess, "run", run)
    monkeypatch.setattr(sidebar, "read_codex_jobs", lambda: JOBS)
    b = bridge()
    return b, b.read_ports()


def test_the_reading_lists_each_listener_under_the_session_that_holds_it_and_hides_the_agents_and_the_daemon(
        monkeypatch, utc):
    b, rows = reading(monkeypatch, done(LSOF))
    assert rows == [
        # The Codex job beta's session started holds this one.
        {"port": 3000, "addresses": ["127.0.0.1"], "pid": 4300, "program": "server.js",
         "command": "node /work/api/server.js", "started_at": 1789646400, "session_id": "pane-b", "session": "beta"},
        {"port": 5173, "addresses": ["*", "[::1]"], "pid": 4100, "program": "vite",
         "command": "node /work/app/node_modules/.bin/vite --port 5173", "started_at": 1789646400,
         "session_id": "pane-a", "session": "alpha"},
        {"port": 7000, "addresses": ["*"], "pid": 900, "program": "ControlCenter",
         "command": "/System/Library/CoreServices/ControlCenter.app/Contents/MacOS/ControlCenter",
         "started_at": 1789642800, "session_id": None, "session": None},
        {"port": 8787, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py",
         "command": "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
                    " /opt/tools/serve.py --token ***",
         "started_at": 1789642800, "session_id": None, "session": None},
    ]
    assert b.ports == rows


def test_no_listener_reads_as_an_empty_list(monkeypatch, utc):
    """lsof exits 1, saying nothing, when no socket matches."""
    b, rows = reading(monkeypatch, done("", code=1))
    assert (rows, b.ports) == ([], [])


def test_a_listener_of_a_process_ps_could_not_list_is_said_rather_than_read_as_none(monkeypatch, utc):
    monkeypatch.setattr(sidebar.subprocess, "run", lambda argv, **_: done(LSOF) if argv == ports.LISTENERS
                        else (_ for _ in ()).throw(FileNotFoundError(2, "No such file or directory")))
    monkeypatch.setattr(sidebar, "read_codex_jobs", lambda: JOBS)
    with pytest.raises(ports.Refused) as refused:
        bridge().read_ports()
    assert str(refused.value) == "could not run ps"


def raises(error):
    def run():
        raise error
    return run


@pytest.mark.parametrize("lsof, reason", [
    (raises(FileNotFoundError(2, "No such file or directory")), "could not run lsof: [Errno 2] No such file or directory"),
    (done("p4100\0cnode\0\nf21\0nlocalhost\0\n"), "could not read lsof: lsof listed 'localhost' for pid 4100, which names no port"),
])
def test_a_reading_that_cannot_be_taken_says_why_rather_than_listing_nothing(monkeypatch, utc, lsof, reason):
    with pytest.raises(ports.Refused) as refused:
        reading(monkeypatch, lsof)
    assert str(refused.value) == reason


# A Stop names a row of the last reading. Its pid is past macOS's highest, so a
# stub that failed to take kill's place would signal nothing.
PID = 400100
LAST = {"port": 5173, "addresses": ["*"], "pid": PID, "program": "vite", "command": "node vite",
        "started_at": 1789646400, "session_id": "pane-a", "session": "alpha"}
LISTENING = f"p{PID}\0\nf21\0\n"


def stopping(monkeypatch, holder=done(LISTENING), lstart=done("Thu Sep 17 12:00:00 2026    \n"), kill=None):
    """A Bridge whose last reading is LAST, with lsof's holder check, ps's start and kill stubbed."""
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
    b = bridge()
    b.ports = [dict(LAST)]
    return b, killed


def log():
    path = Path(sidebar.STATUS_DIR) / "daemon.log"
    return [line.split(" ", 2)[2] for line in path.read_text().splitlines()] if path.exists() else []


def test_a_stop_of_a_holder_still_listening_since_its_start_sends_sigterm_once(monkeypatch, utc):
    b, killed = stopping(monkeypatch)
    b.stop_port(PID, 5173, 1789646400)
    assert killed == [(PID, signal.SIGTERM)]
    assert log() == [f"stop-port {PID} :5173 vite"]
    # The row is spent: a second click is a stale one until the fold reads again.
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, 1789646400)
    assert str(refused.value) == "not in the last reading; open the fold again"
    assert killed == [(PID, signal.SIGTERM)]


@pytest.mark.parametrize("ask, reason", [
    ((PID, 5174, 1789646400), "not in the last reading; open the fold again"),
    ((PID, 5173, 1789646401), "not in the last reading; open the fold again"),
    ((PID + 1, 5173, 1789646400), "not in the last reading; open the fold again"),
])
def test_a_stop_of_a_row_the_last_reading_does_not_hold_is_refused(monkeypatch, utc, ask, reason):
    b, killed = stopping(monkeypatch)
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(*ask)
    assert (str(refused.value), killed) == (reason, [])


def test_a_holder_that_became_a_cards_agent_since_the_reading_is_refused(monkeypatch, utc):
    b, killed = stopping(monkeypatch)
    b.rows[0]["agent_pid"] = PID
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, 1789646400)
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
        b.stop_port(PID, 5173, 1789646400)
    assert (str(refused.value), killed, log()) == (reason, [], [])


@pytest.mark.parametrize("error, reason", [
    (ProcessLookupError(3, "No such process"), "already gone"),
    (PermissionError(1, "Operation not permitted"), "not yours to stop"),
])
def test_a_signal_the_system_refuses_says_why(monkeypatch, utc, error, reason):
    b, killed = stopping(monkeypatch, kill=error)
    with pytest.raises(ports.Refused) as refused:
        b.stop_port(PID, 5173, 1789646400)
    assert (str(refused.value), killed, log()) == (reason, [(PID, signal.SIGTERM)], [])
