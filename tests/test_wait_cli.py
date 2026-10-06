"""The agents-sidebar command against a real daemon server on a real socket.

Each test runs the script as its own process, the way a shell would, under a
spare HOME whose endpoint.json the daemon's own writer filled in. The
snapshot is test data the server streams, not a stand-in for the code under
test, as in test_integration.py.
"""
import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sidebar import Server, Sidebar, heartbeat_frame, sse_frame, write_endpoint

TOKEN = "wait-cli-token-not-a-real-secret"
CLI = ROOT / "agents-sidebar"


def agent(session_id, label, state=None, **more):
    row = {"session_id": session_id, "window_id": "w", "tab_id": "1", "label": label,
           "position": "", "depth": 0, **more}
    if state:
        row["state"] = state
    return row


def payload(*rows, shells=()):
    groups = [{"name": "AGENTS", "rows": list(rows)}]
    if shells:
        groups.append({"name": "SESSIONS", "rows": list(shells)})
    return {"groups": groups}


async def daemon(tmp_path, snapshot, fresh=True):
    """A listening server and a HOME that points at it. `snapshot` is a dict
    whose "now" key is what a client connecting this moment is sent; `fresh`
    is whether the daemon calls its reading current."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    sidebar = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: snapshot["now"],
                      action_fn=lambda *a: None)
    server = Server(sidebar, health_fn=lambda: fresh)
    port = await server.start()
    home = tmp_path / "home"
    write_endpoint(home / ".local" / "share" / "agents-sidebar" / "endpoint.json", port, TOKEN, os.getpid())
    return server, home


async def start(home, *args):
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return await asyncio.create_subprocess_exec(
        sys.executable, str(CLI), *args, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)


async def finish(process, within=10):
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout=within)
    except asyncio.TimeoutError:
        # Never left behind: a test run ends with no process of its own running.
        process.kill()
        await process.wait()
        raise
    return process.returncode, out.decode(), err.decode()


@pytest.mark.asyncio
async def test_status_lists_each_agent_with_its_label_provider_and_state(tmp_path):
    snapshot = {"now": payload(
        agent("AAAA-1", "atlas", "working"),
        agent("BBBB-2", "beacon", "idle", provider="openai"),
        agent("CCCC-3", "cove"),
        shells=[{"session_id": "DDDD-4", "window_id": "w", "tab_id": "2", "label": "~/src",
                 "position": "", "depth": 0}])}
    _, home = await daemon(tmp_path, snapshot)

    code, out, err = await finish(await start(home, "status"))

    assert (code, err) == (0, "")
    assert out == ("AAAA-1\tatlas\tclaude\tworking\n"
                   "BBBB-2\tbeacon\topenai\tidle\n"
                   "CCCC-3\tcove\tclaude\tunknown\n")


@pytest.mark.asyncio
async def test_status_json_gives_the_agent_rows_as_the_panel_has_them(tmp_path):
    rows = [agent("AAAA-1", "atlas", "idle", unseen=True, tty="ttys004")]
    _, home = await daemon(tmp_path, {"now": payload(*rows)})

    code, out, err = await finish(await start(home, "status", "--json"))

    assert (code, err) == (0, "")
    assert json.loads(out) == rows


@pytest.mark.asyncio
@pytest.mark.parametrize("args, out", [
    (["status"], "AAAA-1\tatlas\tclaude\tidle\n"),
    (["status", "--json"], json.dumps([agent("AAAA-1", "atlas", "idle")]) + "\n"),
])
async def test_status_from_a_stale_daemon_prints_its_rows_and_says_they_are_stale_with_exit_1(tmp_path, args, out):
    """The panel shows its STALE banner over the same rows."""
    _, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "idle"))}, fresh=False)

    assert await finish(await start(home, *args)) == (
        1, out, "agents-sidebar: the panel's reading is stale, so these rows may be out of date\n")


@pytest.mark.asyncio
async def test_no_daemon_is_said_on_stderr_with_exit_1(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    code, out, err = await finish(await start(home, "status"))

    endpoint = home / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    assert (code, out) == (1, "")
    assert err == (f"agents-sidebar: the sidebar is not running: cannot read {endpoint} "
                   f"([Errno 2] No such file or directory: '{endpoint}')\n")


@pytest.mark.asyncio
async def test_a_state_that_already_holds_returns_at_once_with_the_row(tmp_path):
    """Blocked or idle by default: the two states that want a person."""
    row = agent("AAAA-1", "atlas", "idle", idle_since=1789000000)
    _, home = await daemon(tmp_path, {"now": payload(agent("BBBB-2", "beacon", "working"), row)})

    code, out, err = await finish(await start(home, "wait", "AAAA-1"))

    assert (code, err) == (0, "")
    assert json.loads(out) == row


async def still_waiting(process, server, seconds=0.3):
    """Is the process on the stream, and still running this long after? It
    is left running. On the stream first: a frame broadcast before it
    connects reaches nobody."""
    for _ in range(100):
        if server.subscribers or process.returncode is not None:
            break
        await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=seconds)
    except asyncio.TimeoutError:
        return True
    return False


@pytest.mark.asyncio
async def test_done_waits_through_a_seen_idle_for_an_unseen_finish(tmp_path):
    """A turn that ended while nobody looked is idle with the unseen mark;
    an idle row without it has been seen, and is not done."""
    snapshot = {"now": payload(agent("AAAA-1", "atlas", "working"))}
    server, home = await daemon(tmp_path, snapshot)
    process = await start(home, "wait", "AAAA-1", "--until", "done")
    assert await still_waiting(process, server)

    server.broadcast(sse_frame(payload(agent("AAAA-1", "atlas", "idle"))))
    assert await still_waiting(process, server)

    finished = agent("AAAA-1", "atlas", "idle", unseen=True)
    server.broadcast(sse_frame(payload(finished)))
    code, out, err = await finish(process)
    assert (code, err) == (0, "")
    assert json.loads(out) == finished


@pytest.mark.asyncio
async def test_nothing_matches_while_the_daemon_says_its_data_is_stale(tmp_path):
    """An unchanged snapshot sends no frame, so the state that arrived while
    stale has to match on the heartbeat that says the data is fresh again."""
    server, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})
    process = await start(home, "wait", "AAAA-1")
    assert await still_waiting(process, server)

    server.broadcast(heartbeat_frame(False))
    server.broadcast(sse_frame(payload(agent("AAAA-1", "atlas", "idle"))))
    assert await still_waiting(process, server)

    server.broadcast(heartbeat_frame(True))
    code, out, err = await finish(process)
    assert (code, err) == (0, "")
    assert json.loads(out)["state"] == "idle"


@pytest.mark.asyncio
async def test_a_daemon_already_stale_when_the_wait_connects_matches_nothing_until_fresh(tmp_path):
    """The state a stale daemon streams first is as old as the rest of its
    reading, so it waits for the daemon to call it current."""
    server, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "idle"))}, fresh=False)
    process = await start(home, "wait", "AAAA-1")
    assert await still_waiting(process, server)

    server.broadcast(heartbeat_frame(True))
    code, out, err = await finish(process)
    assert (code, err) == (0, "")
    assert json.loads(out)["state"] == "idle"


@pytest.mark.asyncio
@pytest.mark.parametrize("frame, complaint", [
    (b"data: {not json\n\n",
     "the sidebar sent a frame that is not JSON (Expecting property name enclosed in double quotes: "
     "line 1 column 2 (char 1)): {not json"),
    (b"event: heartbeat\ndata: {}\n\n", "the sidebar sent a heartbeat with no fresh verdict: {}"),
    (b"data: \xff\n\n", "the sidebar sent a line that is not UTF-8 "
                        "('utf-8' codec can't decode byte 0xff in position 6: invalid start byte)"),
])
async def test_a_frame_the_command_cannot_read_is_said_with_exit_1(tmp_path, frame, complaint):
    server, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})
    process = await start(home, "wait", "AAAA-1")
    assert await still_waiting(process, server)

    server.broadcast(frame)

    assert await finish(process) == (1, "", f"agents-sidebar: {complaint}\n")


@pytest.mark.asyncio
async def test_a_session_that_closes_while_waited_on_is_exit_1(tmp_path):
    server, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})
    process = await start(home, "wait", "AAAA-1")
    assert await still_waiting(process, server)

    server.broadcast(sse_frame(payload(agent("BBBB-2", "beacon", "working"))))

    assert await finish(process) == (1, "", "agents-sidebar: session AAAA-1 has closed\n")


@pytest.mark.asyncio
async def test_a_timeout_ends_the_wait_with_exit_1_and_the_state_it_was_in(tmp_path):
    _, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})

    process = await start(home, "wait", "AAAA-1", "--timeout", "0.5")

    assert await finish(process, within=5) == (
        1, "", "agents-sidebar: timed out after 0.5 s: session AAAA-1 is working\n")


@pytest.mark.asyncio
async def test_a_timeout_holds_while_the_daemon_takes_the_connection_and_never_answers(tmp_path):
    """A daemon wedged mid-start still accepts on its port; the wait gives up
    when it was told to, not when the connection would."""
    import socket
    home = tmp_path / "home"
    with socket.socket() as wedged:
        wedged.bind(("127.0.0.1", 0))
        wedged.listen()
        write_endpoint(home / ".local" / "share" / "agents-sidebar" / "endpoint.json",
                       wedged.getsockname()[1], TOKEN, os.getpid())

        process = await start(home, "wait", "AAAA-1", "--timeout", "1")

        assert await finish(process, within=4) == (1, "", "agents-sidebar: timed out after 1 s for AAAA-1\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments, complaint", [
    (["wait", "AAAA-1", "--until", "finished"],
     "argument --until: invalid choice: 'finished' "
     "(choose from 'working', 'blocked', 'idle', 'done', 'unknown', 'exited')"),
    (["wait", "AAAA-1", "--timeout", "-1"], "argument --timeout: -1 is not a number of seconds above 0"),
    (["wait", "AAAA-1", "--timeout", "nan"], "argument --timeout: nan is not a number of seconds above 0"),
    (["wait"], "the following arguments are required: target"),
])
async def test_arguments_that_cannot_be_used_are_exit_2_before_any_connection(tmp_path, arguments, complaint):
    home = tmp_path / "home"
    home.mkdir()

    code, out, err = await finish(await start(home, *arguments))

    assert (code, out) == (2, "")
    assert err.splitlines()[-1] == f"agents-sidebar {arguments[0]}: error: {complaint}"


@pytest.mark.asyncio
async def test_a_label_names_the_one_session_that_has_it(tmp_path):
    beacon = agent("BBBB-2", "beacon", "blocked")
    _, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"), beacon)})

    code, out, err = await finish(await start(home, "wait", "beacon"))

    assert (code, err) == (0, "")
    assert json.loads(out) == beacon


@pytest.mark.asyncio
async def test_a_label_two_sessions_share_is_refused_with_both_listed(tmp_path):
    """Two tabs open on one repo carry the same label; guessing between them
    would wait on the wrong one. Naming them lets the script pick by id."""
    _, home = await daemon(tmp_path, {"now": payload(
        agent("AAAA-1", "atlas", "working"), agent("BBBB-2", "atlas", "idle", provider="openai"))})

    code, out, err = await finish(await start(home, "wait", "atlas"))

    assert (code, out) == (2, "")
    assert err == ("agents-sidebar: atlas names more than one session; wait on one by its id:\n"
                   "AAAA-1\tatlas\tclaude\tworking\n"
                   "BBBB-2\tatlas\topenai\tidle\n")


@pytest.mark.asyncio
async def test_a_target_no_row_answers_to_is_exit_1(tmp_path):
    _, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})

    assert await finish(await start(home, "wait", "cove")) == (
        1, "", "agents-sidebar: no agent is cove: not a session id or a label in the panel\n")


def cli_module():
    """The script as a module, for its one pure part. It has no .py suffix,
    being a command, so the loader is named outright."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    spec = spec_from_loader("agents_sidebar_cli", SourceFileLoader("agents_sidebar_cli", str(CLI)))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reconnecting_tries_only_inside_its_10_s(monkeypatch):
    """A daemon that takes each connection and never answers costs every try
    its whole allowance. No try starts or runs past the 10 s, however the
    tries and the pauses between them fall."""
    cli = cli_module()
    clock = [0.0]
    tries = []

    class Clock:
        @staticmethod
        def monotonic():
            return clock[0]

        @staticmethod
        def sleep(seconds):
            clock[0] += seconds

    def wedged(patience):
        tries.append((clock[0], patience))
        clock[0] += patience
        raise cli.Failure("the sidebar is not running: nothing answers on port 1 (timed out)")
    monkeypatch.setattr(cli, "time", Clock)
    monkeypatch.setattr(cli, "open_stream", wedged)

    with pytest.raises(cli.Failure, match=r"^the sidebar is not running: nothing answers on port 1 \(timed out\)$"):
        cli.reopen(lambda: cli.CONNECT_SECONDS)

    assert tries == [(0.0, 5), (5.25, 4.75)]
    assert clock[0] == 10


def test_a_connection_gets_its_patience_once_however_slowly_the_daemon_answers(monkeypatch, tmp_path):
    """A daemon that answers each line just inside the patience would, with a
    timeout per read, hold a connection several times as long; reconnecting
    near the end of its 10 s would then run well past them."""
    import socket
    import threading
    cli = cli_module()
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    (tmp_path / "endpoint.json").write_text(json.dumps({"port": port, "token": "t", "pid": 1}))
    monkeypatch.setattr(cli, "ENDPOINT", str(tmp_path / "endpoint.json"))

    def dribble():
        peer, _ = listener.accept()
        peer.recv(1024)
        # The client gives up partway, so a later line meets a closed socket.
        with contextlib.suppress(OSError):
            for line in (b"HTTP/1.1 200 OK\r\n", b"Content-Type: text/event-stream\r\n", b"\r\n"):
                time.sleep(0.6)
                peer.sendall(line)
        peer.close()
    server = threading.Thread(target=dribble)
    server.start()

    started = time.monotonic()
    with pytest.raises(cli.Failure, match=rf"^the sidebar on port {port} did not answer: "):
        cli.open_stream(1.0)
    assert time.monotonic() - started < 1.5
    server.join()
    listener.close()


def test_the_callers_terminal_is_its_own_or_its_nearest_ancestors():
    """An agent's tool runs commands with no terminal of their own, under the
    agent that has the pane's; the walk stops at the first one, and a loop
    in a listing taken mid-change cannot hang it. The listing is
    `ps -eo pid=,ppid=,tty=` as macOS prints it."""
    listing = ("    1     0 ??\n"
               "  700     1 ttys009\n"
               "  710   700 ??\n"
               "  720   710 ??\n"
               "  800     1 ??\n"
               "  900   901 ??\n"
               "  901   900 ??\n")
    caller_tty = cli_module().caller_tty

    assert caller_tty(listing, 720) == "ttys009"
    assert caller_tty(listing, 700) == "ttys009"
    assert caller_tty(listing, 800) is None
    assert caller_tty(listing, 900) is None


@contextlib.contextmanager
def a_terminal():
    """A pseudo-terminal for the command to run on. -> (its descriptor, its
    name as ps prints it)."""
    controller, terminal = os.openpty()
    try:
        yield terminal, os.ttyname(terminal).removeprefix("/dev/")
    finally:
        os.close(terminal)
        os.close(controller)


async def run_on(terminal, home, *args, **environ):
    """Run the command as a script in a pane is: in a session of its own,
    with `terminal` as its controlling terminal. -> (exit code, stdout, stderr)."""
    import fcntl
    import termios

    def take_terminal():
        fcntl.ioctl(terminal, termios.TIOCSCTTY, 0)

    process = await asyncio.create_subprocess_exec(
        sys.executable, str(CLI), *args,
        env={"HOME": str(home), "PATH": os.environ["PATH"], **environ},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True, preexec_fn=take_terminal, pass_fds=(terminal,))
    return await finish(process)


@pytest.mark.asyncio
async def test_current_is_the_session_on_the_callers_terminal(tmp_path):
    """Inside tmux, $ITERM_SESSION_ID is whatever the tmux server was
    started under, so the terminal is what names the pane."""
    with a_terminal() as (terminal, name):
        here = agent("BBBB-2", "beacon", "idle", tty=name)
        _, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "idle", tty="ttys999"), here)})

        code, out, err = await run_on(terminal, home, "wait", "current", ITERM_SESSION_ID="w0t0p0:AAAA-1")

    assert (code, err) == (0, "")
    assert json.loads(out) == here


@pytest.mark.asyncio
async def test_two_agents_on_the_callers_terminal_are_refused_with_both_listed(tmp_path):
    """As for a label two agents share: the command names them and lets the
    script pick by id."""
    with a_terminal() as (terminal, name):
        _, home = await daemon(tmp_path, {"now": payload(
            agent("AAAA-1", "atlas", "working", tty=name), agent("BBBB-2", "beacon", "idle", tty=name))})

        code, out, err = await run_on(terminal, home, "wait", "current")

    assert (code, out) == (2, "")
    assert err == (f"agents-sidebar: current: more than one agent is on this terminal, {name}; "
                   f"wait on one by its id:\n"
                   "AAAA-1\tatlas\tclaude\tworking\n"
                   "BBBB-2\tbeacon\tclaude\tidle\n")


async def drop_streams():
    """End every open /events stream from the daemon's side, as a restart
    does, leaving its listener up."""
    streams = [task for task in asyncio.all_tasks() if task.get_coro().__name__ == "_client"]
    for task in streams:
        task.cancel()
    await asyncio.gather(*streams, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_dropped_stream_follows_the_daemon_to_its_new_port(tmp_path):
    """An update restarts the daemon on a new port with a new token; the
    wait carries on against it, on the session it had resolved."""
    before, home = await daemon(tmp_path / "before", {"now": payload(agent("AAAA-1", "atlas", "working"))})
    process = await start(home, "wait", "atlas")
    assert await still_waiting(process, before)

    after, _ = await daemon(tmp_path / "after", {"now": payload(
        agent("AAAA-1", "renamed", "idle"), agent("BBBB-2", "atlas", "working"))})
    os.replace(tmp_path / "after" / "home" / ".local" / "share" / "agents-sidebar" / "endpoint.json",
               home / ".local" / "share" / "agents-sidebar" / "endpoint.json")
    await drop_streams()

    code, out, err = await finish(process)
    assert (code, err) == (0, "")
    assert json.loads(out) == agent("AAAA-1", "renamed", "idle")


@pytest.mark.asyncio
async def test_a_daemon_that_does_not_come_back_in_10_s_is_exit_1(tmp_path):
    import errno
    import socket
    import time
    server, home = await daemon(tmp_path, {"now": payload(agent("AAAA-1", "atlas", "working"))})
    process = await start(home, "wait", "AAAA-1")
    assert await still_waiting(process, server)
    # A port nothing listens on, as an endpoint.json left by a daemon that died.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    write_endpoint(home / ".local" / "share" / "agents-sidebar" / "endpoint.json", dead, TOKEN, os.getpid())

    dropped = time.monotonic()
    await drop_streams()
    code, out, err = await finish(process, within=20)

    # At 10 s, not before; the upper bound is slack for a loaded machine.
    assert 10 <= time.monotonic() - dropped < 15
    assert (code, out) == (1, "")
    assert err == (f"agents-sidebar: the sidebar is not running: nothing answers on port {dead} "
                   f"([Errno {errno.ECONNREFUSED}] {os.strerror(errno.ECONNREFUSED)})\n")
