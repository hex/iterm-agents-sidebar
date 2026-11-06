# ABOUTME: The TCP ports listening on this Mac for the panel's Ports fold, from lsof's field output.
# ABOUTME: Pure: the daemon runs lsof and ps, and hands the readings here to become the fold's rows.
"""lsof lists only the sockets of processes this user may inspect, so a
listener run as root never appears. One socket per address family means a
dual-stack server shows twice for one port; the fold shows it once."""
import os

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


def program(kernel, command, named):
    """What a row calls a listener's process.

    `named` is what its argv names: an interpreter by its script, Claude
    Code by `claude` where the kernel has the version its binary is named
    after, a symlinked python by its script where the kernel has python3.10.
    The kernel's name wins only where the program's path shows in argv past
    a first word that is not it: a space in that path split argv[0]
    (/Applications/Unity Hub.app/...), or the program rewrote its argv
    into a status line (nginx: master process /usr/sbin/nginx).
    """
    words = command.split()
    split = bool(words) and os.path.basename(words[0]) != kernel and f"/{kernel}" in command
    return named if named and not split else kernel


def rows(listeners, processes, owners, labels, hidden):
    """The Ports fold's rows: those held under a session first, then by port.

    `processes` is {pid: {started_at, command, program}} off the process
    listing, its command already masked; a listener whose pid it lacks
    exited between the two reads and is left out. `owners` maps a pid to
    the session whose process tree holds it and `labels` a session to its
    card's name. A pid in `hidden`, an agent's own or the daemon's, is never
    listed.
    """
    out = []
    for (pid, port), listener in listeners.items():
        held = processes.get(pid)
        if held is None or pid in hidden:
            continue
        session = owners.get(pid)
        out.append({"port": port, "addresses": listener["addresses"], "pid": pid,
                    "program": program(listener["kernel"], held["command"], held["program"]),
                    "command": held["command"], "started_at": held["started_at"],
                    "session_id": session, "session": labels.get(session) if session else None})
    return sorted(out, key=lambda row: (row["session_id"] is None, row["port"], row["pid"]))
