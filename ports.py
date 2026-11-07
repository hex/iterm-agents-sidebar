# ABOUTME: The TCP ports an agent's card shows: lsof's listening sockets, the agent a listener's environment names,
# ABOUTME: which card each belongs to and what language it runs. Pure but for inherited_agent, which asks the kernel.
"""lsof lists only the sockets of processes this user may inspect, so a
listener run as root never appears. One socket per address family means a
dual-stack server shows twice for one port; a card shows it once."""
import ctypes
import ctypes.util
import os
import re
import struct

LSOF = "/usr/sbin/lsof"
#: Every listening TCP socket: numeric hosts and ports, pid, kernel name and
#: address as fields, each ended by a NUL.
LISTENERS = [LSOF, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcn0"]


class Refused(Exception):
    """A reading the daemon could not take, or a Stop it will not send; the text says why."""


def holder_check(pid, port):
    """lsof's arguments for whether `pid` still listens on `port`: it prints p<pid> if so."""
    return [LSOF, "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp0"]


def holds(lsof_text, pid):
    """Whether holder_check's output names `pid`."""
    return f"p{pid}" in lsof_text.replace("\n", "\0").split("\0")


def parse_listeners(lsof_text):
    """LISTENERS' output -> {(pid, port): {"kernel": name, "addresses": [address, ...]}}.

    An address is lsof's host part: 127.0.0.1, [::1] or * for every
    interface. A name with no port after its last colon, or one before its
    process's command name, raises ValueError quoting it: lsof prints both
    for every listening socket.
    """
    found, pid, kernel = {}, None, None
    for field in lsof_text.replace("\n", "\0").split("\0"):
        kind, value = field[:1], field[1:]
        if kind == "p":
            pid, kernel = int(value), None
        elif kind == "c":
            kernel = value
        elif kind == "n":
            address, _, port = value.rpartition(":")
            if not address or not port.isdigit():
                raise ValueError(f"lsof listed {value!r} for pid {pid}, which names no port")
            if kernel is None:
                raise ValueError(f"lsof listed {value!r} for pid {pid} before naming its command")
            listener = found.setdefault((pid, int(port)), {"kernel": kernel, "addresses": []})
            if address not in listener["addresses"]:
                listener["addresses"].append(address)
    return found


#: A Python interpreter's file name, in any case: python, python3, python3.11 or the framework's Python.
PYTHON = re.compile(r"python(?:[0-9]+(?:\.[0-9]+)*)?", re.I)
#: The interpreters, other than Python, whose listeners a card tints by language.
RUNTIMES = {"node": "js", "bun": "js", "deno": "js", "ruby": "ruby"}


def kind(kernel):
    """The kernel's name for a listener's process -> the language it runs: js,
    python, ruby or other. Only an interpreter's name says one: a compiled
    server's kernel name is its own, so a Go or Rust one is other."""
    return "python" if PYTHON.fullmatch(kernel) else RUNTIMES.get(kernel.lower(), "other")


def program(kernel, command, named):
    """What a row calls a listener's process.

    `named` is what its argv names: an interpreter by its script, Claude
    Code by `claude` where the kernel has the version its binary is named
    after, a symlinked python by its script where the kernel has python3.10.
    Python's own `-m` option names its module instead. A script word, `-c`,
    or `--` ends that search; `-W` and `-X` consume their option values.
    The kernel's name wins only where the program's path shows in argv past
    a first word that is not it: a space in that path split argv[0]
    (/Applications/Unity Hub.app/...), or the program rewrote its argv
    into a status line (nginx: master process /usr/sbin/nginx).
    """
    words = command.split()
    split = bool(words) and os.path.basename(words[0]) != kernel and f"/{kernel}" in command
    if words and not split and PYTHON.fullmatch(os.path.basename(words[0])):
        at = 1
        while at < len(words):
            word = words[at]
            if word == "-m":
                if at + 1 < len(words):
                    return words[at + 1]
                break
            if word.startswith("-c") or word in ("--", "-") or not word.startswith("-"):
                break
            at += 2 if word in ("-W", "-X") else 1
    return named if named and not split else kernel


#: Claude Code puts its own pid in the environment of every process it
#: starts. A server started with `nohup ... &` is reparented to launchd at
#: once and leaves the agent's process tree, but keeps this.
AGENT_VARIABLE = "CLAUDE_PID"


def environment(procargs, names):
    """The kernel's argument block for one process -> {name: value} for each
    of `names` its environment sets, and nothing else it holds.

    The block (sysctl KERN_PROCARGS2) is argc as a native int, the
    executable's path, NUL padding, argc arguments, the environment's
    NAME=value strings up to an empty one, then the loader's own strings.
    Counting argc is what keeps an argument that reads `CLAUDE_PID=...` from
    passing for a variable. A name set twice reads as its first setting, as
    getenv does. A block with a negative count, or too short for its count,
    raises ValueError, whose text quotes none of the block: an environment
    holds secrets.
    """
    if len(procargs) < 4:
        raise ValueError(f"the kernel's argument block is {len(procargs)} bytes, too short to hold its count")
    argc = struct.unpack("i", procargs[:4])[0]
    if argc < 0:
        raise ValueError(f"the kernel's argument block counts {argc} arguments")
    # Only what a NUL ends is a string; the piece after the last NUL is not.
    strings = procargs[4:].split(b"\0")[:-1]
    at = 1
    while at < len(strings) and strings[at] == b"":
        at += 1
    if len(strings) - at < argc:
        raise ValueError(f"the kernel's argument block ends after {len(strings) - at} of its {argc} arguments")
    wanted = {name.encode() + b"=": name for name in names}
    found = {}
    for entry in strings[at + argc:]:
        if not entry:
            break
        for prefix, name in wanted.items():
            if entry.startswith(prefix) and name not in found:
                found[name] = entry[len(prefix):].decode("utf-8", "surrogateescape")
    return found


#: The largest pid_t; a longer number is no pid, however many digits it has.
PID_MAX = 2**31 - 1


def agent_named(procargs):
    """The agent pid a process's environment names in AGENT_VARIABLE, or None
    when it names none: unset, or not a plain pid past launchd's."""
    value = environment(procargs, [AGENT_VARIABLE]).get(AGENT_VARIABLE, "")
    if not (value.isascii() and value.isdigit() and len(value) <= len(str(PID_MAX))):
        return None
    return int(value) if 1 < int(value) <= PID_MAX else None


_LIBC = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
#: sysctl's names for the kernel's largest argument block, and one process's.
_CTL_KERN, _KERN_ARGMAX, _KERN_PROCARGS2 = 1, 8, 49


def _sysctl(mib, size):
    names = (ctypes.c_int * len(mib))(*mib)
    buffer = ctypes.create_string_buffer(size)
    length = ctypes.c_size_t(size)
    if _LIBC.sysctl(names, len(mib), buffer, ctypes.byref(length), None, ctypes.c_size_t(0)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    try:
        return buffer.raw[:length.value]
    finally:
        ctypes.memset(buffer, 0, size)


def inherited_agent(pid):
    """The agent pid `pid`'s environment names, or None.

    Read from the kernel's copy of its block, never from `ps -E`, whose text
    puts the arguments first with nothing to say where they end. The block
    is dropped once the one name is out of it. Raises OSError with the
    kernel's errno; macOS says EINVAL alike for a pid that is gone, a zombie
    and another user's process. An Apple platform binary such as /bin/sleep
    comes back with no environment at all, so it names no agent.
    """
    argmax = struct.unpack("i", _sysctl([_CTL_KERN, _KERN_ARGMAX], 4))[0]
    return agent_named(_sysctl([_CTL_KERN, _KERN_PROCARGS2, pid], argmax))


def by_card(reading, processes, trees, agents, hidden):
    """The daemon's last reading -> {session id: its card's listeners, by port}.

    `reading` maps (pid, port) to what lsof listed then: the kernel's name
    for the process, its addresses, when it began, and the agent pid its
    environment named (None when it named none or was not read).
    `processes` is {pid: {started_at, command, program}} off this rebuild's
    process listing: a listener whose pid it lacks, or lists as begun at
    another second, exited or is another process now, and is left out.
    `trees` maps a pid to the session whose card's process tree holds it,
    and `agents` a card's agent pid to (session id, when it began). A
    listener no tree holds goes to the card whose agent its environment
    names, if that agent began no later than it did: one that began after
    has a dead agent's pid. A pid in `hidden`, an agent's own or the
    daemon's, is never listed, and neither is a listener no card holds.
    Each listener's row names its program and its kind, the language it runs.
    """
    cards = {}
    for (pid, port), heard in reading.items():
        held = processes.get(pid)
        if pid in hidden or held is None or held["started_at"] != heard["started_at"]:
            continue
        session = trees.get(pid)
        if session is None and heard["agent"] in agents:
            agent_session, agent_began = agents[heard["agent"]]
            if agent_began is not None and agent_began <= heard["started_at"]:
                session = agent_session
        if session is None:
            continue
        cards.setdefault(session, []).append({
            "port": port, "addresses": heard["addresses"], "pid": pid,
            "program": program(heard["kernel"], held["command"], held["program"]),
            "kind": kind(heard["kernel"]), "started_at": heard["started_at"]})
    for listeners in cards.values():
        listeners.sort(key=lambda row: (row["port"], row["pid"]))
    return cards

