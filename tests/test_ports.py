# ABOUTME: Tests for ports.py: lsof's listener records and the Ports fold's rows built from them.
# ABOUTME: Inputs are the shape lsof -Fpcn0 prints; every expected row is written out by hand.
import pytest

import ports

# Two processes: a dev server listening on one port over IPv4 and IPv6 on
# three descriptors, and a framework Python on another. lsof ends each field
# with a NUL and each set of fields with a newline.
LSOF = ("p4100\0cnode\0\n"
        "f21\0n*:5173\0\n"
        "f22\0n*:5173\0\n"
        "f23\0n[::1]:5173\0\n"
        "p4200\0cPython\0\n"
        "f4\0n127.0.0.1:8787\0\n"
        "f5\0n127.0.0.1:8788\0\n")


def test_lsof_records_become_one_listener_per_pid_and_port_with_each_address_once():
    assert ports.parse_listeners(LSOF) == {
        (4100, 5173): {"kernel": "node", "addresses": ["*", "[::1]"]},
        (4200, 8787): {"kernel": "Python", "addresses": ["127.0.0.1"]},
        (4200, 8788): {"kernel": "Python", "addresses": ["127.0.0.1"]},
    }


def test_no_listener_is_an_empty_reading():
    """lsof prints nothing, and exits 1, when no socket matches."""
    assert ports.parse_listeners("") == {}


@pytest.mark.parametrize("text, error", [
    ("p4100\0cnode\0\nf21\0nlocalhost\0\n", "lsof listed 'localhost' for pid 4100, which names no port"),
    ("p4100\0\nf21\0n*:5173\0\n", "lsof listed '*:5173' for pid 4100 before naming its command"),
])
def test_a_record_lsof_always_completes_is_an_error_that_quotes_it_when_it_does_not(text, error):
    with pytest.raises(ValueError) as raised:
        ports.parse_listeners(text)
    assert str(raised.value) == error


def process(command, program, started_at=1789646400):
    return {"started_at": started_at, "command": command, "program": program}


PROCESSES = {
    4100: process("node /work/app/node_modules/.bin/vite --port 5173", "vite"),
    4200: process("/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
                  " /opt/tools/serve.py", "serve.py", started_at=1789640000),
}


def test_a_sessions_listeners_come_first_with_its_label_then_the_rest_by_port():
    rows = ports.rows(ports.parse_listeners(LSOF), PROCESSES, owners={4200: "pane-b"},
                      labels={"pane-b": "beta"}, hidden=set())
    assert rows == [
        {"port": 8787, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py",
         "command": PROCESSES[4200]["command"], "started_at": 1789640000, "session_id": "pane-b", "session": "beta"},
        {"port": 8788, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py",
         "command": PROCESSES[4200]["command"], "started_at": 1789640000, "session_id": "pane-b", "session": "beta"},
        {"port": 5173, "addresses": ["*", "[::1]"], "pid": 4100, "program": "vite",
         "command": PROCESSES[4100]["command"], "started_at": 1789646400, "session_id": None, "session": None},
    ]


def test_the_agents_and_the_daemons_own_listeners_are_not_listed():
    listeners = ports.parse_listeners("p4100\0cnode\0\nf21\0n*:5173\0\n"
                                      "p500\0c2.1.318\0\nf40\0n127.0.0.1:58932\0\n"
                                      "p600\0cpython3.10\0\nf9\0n127.0.0.1:60912\0\n")
    processes = {4100: PROCESSES[4100], 500: process("claude --name alpha", "claude"),
                 600: process("/venvs/3.10/bin/python /Scripts/AutoLaunch/agents_sidebar.py", "agents_sidebar.py")}
    rows = ports.rows(listeners, processes, owners={500: "pane-a", 4100: "pane-a"}, labels={"pane-a": "alpha"},
                      hidden={500, 600})
    assert [(row["pid"], row["port"], row["session"]) for row in rows] == [(4100, 5173, "alpha")]


def test_a_listener_whose_process_left_the_listing_is_not_listed():
    """It exited between lsof and ps: there is nothing left to name or stop."""
    rows = ports.rows(ports.parse_listeners(LSOF), {4200: PROCESSES[4200]}, owners={}, labels={}, hidden=set())
    assert [(row["pid"], row["port"]) for row in rows] == [(4200, 8787), (4200, 8788)]


@pytest.mark.parametrize("kernel, command, named, shown", [
    # An interpreter is named by the script it runs.
    ("Python", "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
     " /opt/tools/serve.py", "serve.py", "serve.py"),
    # A symlink names the interpreter: the kernel has the file it resolves to.
    ("python3.10", "/venvs/3.10/bin/python /Scripts/AutoLaunch/agents_sidebar.py", "agents_sidebar.py",
     "agents_sidebar.py"),
    # Claude Code's binary is named after its version; its argv says claude.
    ("2.1.318", "claude --name alpha", "claude", "claude"),
    # A path with a space splits argv[0]: the words before it name nothing.
    ("SetappAgent", "/Users/x/Library/Application Support/Setapp/SetappAgent.app/Contents/MacOS/SetappAgent",
     "Application", "SetappAgent"),
    ("Unity Hub", "/Applications/Unity Hub.app/Contents/MacOS/Unity Hub", "Unity", "Unity Hub"),
    # A program that rewrites its argv keeps the kernel's name.
    ("nginx", "nginx: master process /opt/homebrew/opt/nginx/bin/nginx", "nginx:", "nginx"),
])
def test_a_holder_is_named_by_its_argv_unless_argv_split_or_rewrote_the_kernels_program(kernel, command, named, shown):
    listeners = {(4300, 9000): {"kernel": kernel, "addresses": ["127.0.0.1"]}}
    rows = ports.rows(listeners, {4300: process(command, named)}, owners={}, labels={}, hidden=set())
    assert [row["program"] for row in rows] == [shown]
