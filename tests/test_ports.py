# ABOUTME: Tests for ports.py: lsof's listener records, the agent a listener's environment names, and the card each one goes to.
# ABOUTME: lsof and the kernel's argument block are given in the shapes they print; every expected value is written out by hand.
import struct
import subprocess
import sys
import time

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


def procargs(argv, env, path=None, apple=(b"executable_path=/x", b"security_config=0x0")):
    """KERN_PROCARGS2 as the kernel lays it out: argc, the executable's path,
    NUL padding, the arguments, the environment, then the loader's own
    strings after an empty one."""
    path = path or argv[0]
    return (struct.pack("i", len(argv)) + path + b"\0" * 6 + b"".join(a + b"\0" for a in argv)
            + b"".join(e + b"\0" for e in env) + b"\0" + b"".join(s + b"\0" for s in apple) + b"\0" * 8)


SECRETS = [b"CS_SECRETS_PASSWORD=hunter2", b"CLAUDE_CODE_MESSAGING_TOKEN=tok-123"]


def test_the_environment_gives_only_the_names_asked_for():
    raw = procargs([b"node", b"server.js"], [b"HOME=/Users/x", *SECRETS, b"CLAUDE_PID=4242", b"ITERM_SESSION_ID=w0t0p0:AB"])
    assert ports.environment(raw, ["CLAUDE_PID"]) == {"CLAUDE_PID": "4242"}
    assert ports.environment(raw, ["CLAUDE_PID", "ITERM_SESSION_ID", "NOT_SET"]) == {
        "CLAUDE_PID": "4242", "ITERM_SESSION_ID": "w0t0p0:AB"}


def test_an_argument_that_looks_like_a_variable_is_never_read_as_one():
    """argv comes first and anyone can put text there; argc says where it ends."""
    raw = procargs([b"python3", b"serve.py", b"CLAUDE_PID=500", b""], [b"HOME=/Users/x"])
    assert ports.environment(raw, ["CLAUDE_PID"]) == {}


def test_the_loaders_strings_after_the_environment_are_not_part_of_it():
    raw = procargs([b"node"], [b"HOME=/Users/x"], apple=(b"CLAUDE_PID=500",))
    assert ports.environment(raw, ["CLAUDE_PID"]) == {}


def test_a_process_whose_environment_the_kernel_withholds_names_nothing():
    """Measured on macOS 26: an Apple platform binary such as /bin/sleep comes
    back with its arguments and no environment at all."""
    raw = struct.pack("i", 2) + b"/bin/sleep\0\0\0\0\0\0/bin/sleep\x005\0"
    assert ports.environment(raw, ["CLAUDE_PID"]) == {}


def test_the_first_setting_of_a_name_is_the_one_a_process_reads():
    raw = procargs([b"node"], [b"CLAUDE_PID=4242", b"CLAUDE_PID=500"])
    assert ports.environment(raw, ["CLAUDE_PID"]) == {"CLAUDE_PID": "4242"}


@pytest.mark.parametrize("raw, error", [
    (b"\x02\0", "the kernel's argument block is 2 bytes, too short to hold its count"),
    (struct.pack("i", 3) + b"/bin/x\0\0\0/bin/x\0a\0", "the kernel's argument block ends after 2 of its 3 arguments"),
    (struct.pack("i", -1) + procargs([b"node"], [b"CLAUDE_PID=4242"])[4:],
     "the kernel's argument block counts -1 arguments"),
])
def test_a_block_cut_short_or_with_a_negative_count_is_an_error_that_quotes_no_content(raw, error):
    with pytest.raises(ValueError) as raised:
        ports.environment(raw, ["CLAUDE_PID"])
    assert str(raised.value) == error


def test_a_running_process_names_the_agent_its_environment_inherited():
    """The kernel's own copy, read from a real child: the environment counts, the arguments do not."""
    script = "import time; time.sleep(30)"
    inherited = subprocess.Popen([sys.executable, "-c", script], env={"CLAUDE_PID": "4242", "HOME": "/tmp"})
    forged = subprocess.Popen([sys.executable, "-c", script, "CLAUDE_PID=4242"], env={"HOME": "/tmp"})
    try:
        time.sleep(0.5)
        assert (ports.inherited_agent(inherited.pid), ports.inherited_agent(forged.pid)) == (4242, None)
    finally:
        for child in (inherited, forged):
            child.kill()
            child.wait()


def test_a_process_that_is_gone_cannot_be_read():
    child = subprocess.Popen(["/usr/bin/true"])
    child.wait()
    with pytest.raises(OSError) as raised:
        ports.inherited_agent(child.pid)
    assert str(raised.value) == "[Errno 22] Invalid argument"


@pytest.mark.parametrize("value, agent", [("4242", 4242), ("", None), ("12a", None), ("-4", None), ("1", None),
                                          ("٤٢", None), ("2147483647", 2147483647), ("2147483648", None),
                                          ("9" * 5000, None)])
def test_only_a_plain_pid_past_launchd_names_an_agent(value, agent):
    assert ports.agent_named(procargs([b"node"], [f"CLAUDE_PID={value}".encode()])) == agent


def process(command, program, started_at=1789646400):
    return {"started_at": started_at, "command": command, "program": program}


def heard(kernel, addresses, started_at=1789646400, agent=None):
    """One listener of the daemon's reading."""
    return {"kernel": kernel, "addresses": addresses, "started_at": started_at, "agent": agent}


PROCESSES = {
    4100: process("node /work/app/node_modules/.bin/vite --port 5173", "vite"),
    4200: process("/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
                  " /opt/tools/serve.py", "serve.py", started_at=1789640000),
    4300: process("node /work/api/server.js", "server.js", started_at=1789647000),
}
READING = {
    (4100, 5173): heard("node", ["*", "[::1]"]),
    (4200, 8788): heard("Python", ["127.0.0.1"], started_at=1789640000),
    (4200, 8787): heard("Python", ["127.0.0.1"], started_at=1789640000),
    # Started by alpha's agent, then left on its own: no card's tree holds it.
    (4300, 3000): heard("node", ["127.0.0.1"], started_at=1789647000, agent=500),
}
AGENTS = {500: ("pane-a", 1789640000), 800: ("pane-b", 1789640000)}


def test_each_card_gets_the_listeners_its_tree_holds_and_those_its_agent_left_running_by_port():
    cards = ports.by_card(READING, PROCESSES, trees={4200: "pane-b"}, agents=AGENTS, hidden=set())
    assert cards == {
        "pane-a": [{"port": 3000, "addresses": ["127.0.0.1"], "pid": 4300, "program": "server.js", "kind": "js",
                    "started_at": 1789647000}],
        "pane-b": [{"port": 8787, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py", "kind": "python",
                    "started_at": 1789640000},
                   {"port": 8788, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py", "kind": "python",
                    "started_at": 1789640000}],
    }


def test_a_tree_outranks_the_agent_an_environment_names():
    """A server started by one agent and run under another's tree is the second's."""
    cards = ports.by_card({(4300, 3000): READING[(4300, 3000)]}, PROCESSES, trees={4300: "pane-b"},
                          agents=AGENTS, hidden=set())
    assert list(cards) == ["pane-b"]


def test_an_agent_that_started_after_the_listener_did_not_start_it():
    """Its pid is a dead agent's, reused: the listener is no card's."""
    later = {500: ("pane-a", 1789647001)}
    assert ports.by_card({(4300, 3000): READING[(4300, 3000)]}, PROCESSES, trees={}, agents=later,
                         hidden=set()) == {}
    same_second = {500: ("pane-a", 1789647000)}
    assert list(ports.by_card({(4300, 3000): READING[(4300, 3000)]}, PROCESSES, trees={}, agents=same_second,
                              hidden=set())) == ["pane-a"]


def test_a_listener_no_card_holds_is_not_listed():
    assert ports.by_card(READING, PROCESSES, trees={}, agents={}, hidden=set()) == {}


def test_the_agents_and_the_daemons_own_listeners_are_not_listed():
    reading = {(4100, 5173): READING[(4100, 5173)], (500, 58932): heard("2.1.318", ["127.0.0.1"])}
    processes = {4100: PROCESSES[4100], 500: process("claude --name alpha", "claude")}
    cards = ports.by_card(reading, processes, trees={500: "pane-a", 4100: "pane-a"}, agents=AGENTS, hidden={500})
    assert [(row["pid"], row["port"]) for row in cards["pane-a"]] == [(4100, 5173)]


def test_a_listener_whose_process_left_or_was_replaced_since_the_reading_is_not_listed():
    """It exited after lsof saw it, or its pid now names a process that began later."""
    replaced = {4200: process("python3 other.py", "other.py", started_at=1789649999)}
    trees = {4100: "pane-a", 4200: "pane-a"}
    assert ports.by_card(READING, replaced, trees=trees, agents={}, hidden=set()) == {}


@pytest.mark.parametrize("kernel, command, named, shown, kind", [
    # An interpreter is named by the script it runs; its kind is the interpreter's.
    ("Python", "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
     " /opt/tools/serve.py", "serve.py", "serve.py", "python"),
    # A symlink names the interpreter: the kernel has the file it resolves to.
    ("python3.10", "/venvs/3.10/bin/python /Scripts/AutoLaunch/agents_sidebar.py", "agents_sidebar.py",
     "agents_sidebar.py", "python"),
    ("Python", "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
     " -m http.server 18766 --bind 127.0.0.1", "Python", "http.server", "python"),
    ("python3.11", "python3 -u -m uvicorn app:main --port 8000", "python3", "uvicorn", "python"),
    ("python3.11", "python3 -X dev -W ignore -m flask run", "python3", "flask", "python"),
    ("python3.11", "python3 serve.py -m fast", "serve.py", "serve.py", "python"),
    ("python3.11", "python3 -c import http.server", "python3", "python3", "python"),
    ("python3.11", "python3 -m", "python3", "python3", "python"),
    ("node", "node -m server.js", "node", "node", "js"),
    ("python3.11", "/venv/bin/PyThOn3.11 -m http.server", "PyThOn3.11", "http.server", "python"),
    ("python3.11", "python -Xdev -Wignore -m flask run", "python", "flask", "python"),
    ("python3.11", "python3 -W -m serve.py", "serve.py", "serve.py", "python"),
    ("python3.11", "python3 -X -m serve.py", "serve.py", "serve.py", "python"),
    ("python3.11", "python3 -c pass -m http.server", "python3", "python3", "python"),
    ("python3.11", "python3 -cpass -m http.server", "python3", "python3", "python"),
    ("python3.11", "python3 -- -m http.server", "python3", "python3", "python"),
    ("python3.11", "python3 - -m http.server", "python3", "python3", "python"),
    # Claude Code's binary is named after its version; its argv says claude.
    ("2.1.318", "claude --name alpha", "claude", "claude", "other"),
    # A path with a space splits argv[0]: the words before it name nothing.
    ("SetappAgent", "/Users/x/Library/Application Support/Setapp/SetappAgent.app/Contents/MacOS/SetappAgent",
     "Application", "SetappAgent", "other"),
    ("Unity Hub", "/Applications/Unity Hub.app/Contents/MacOS/Unity Hub", "Unity", "Unity Hub", "other"),
    # A program that rewrites its argv keeps the kernel's name.
    ("nginx", "nginx: master process /opt/homebrew/opt/nginx/bin/nginx", "nginx:", "nginx", "other"),
])
def test_a_holder_is_named_by_its_argv_unless_argv_split_or_rewrote_the_kernels_program(kernel, command, named, shown,
                                                                                        kind):
    reading = {(4300, 9000): heard(kernel, ["127.0.0.1"])}
    cards = ports.by_card(reading, {4300: process(command, named)}, trees={4300: "pane-a"}, agents={}, hidden=set())
    assert [(row["program"], row["kind"]) for row in cards["pane-a"]] == [(shown, kind)]


@pytest.mark.parametrize("kernel, kind", [
    ("node", "js"), ("bun", "js"), ("deno", "js"),
    ("Python", "python"), ("python", "python"), ("python3", "python"), ("PYTHON3.12", "python"),
    ("ruby", "ruby"),
    # A compiled server's kernel name is its own, so a Go one is no kind.
    ("hugo", "other"), ("postgres", "other"),
    # An interpreter the panel has no tint for.
    ("perl", "other"),
    # A name that starts like an interpreter's is not one.
    ("pythonista", "other"), ("rubymine", "other"),
])
def test_a_listener_is_of_the_kind_its_holders_kernel_name_runs(kernel, kind):
    """Whatever its argv names: a script, a module or a renamed argv[0] leave the interpreter the kernel ran."""
    reading = {(4300, 9000): heard(kernel, ["127.0.0.1"])}
    cards = ports.by_card(reading, {4300: process("dev-server --port 9000", "dev-server")}, trees={4300: "pane-a"},
                          agents={}, hidden=set())
    assert [(row["program"], row["kind"]) for row in cards["pane-a"]] == [("dev-server", kind)]
