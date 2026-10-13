# ABOUTME: Rules about a row the daemon and its helpers share: when a prompt must not be sent to it.
# ABOUTME: Kept apart from sidebar.py so links.py can use them without importing the whole daemon.


REMOTE_NO_REPLY = "replies do not reach a remote session yet"
#: Every key the panel types as an answer: an option's digit, Codex's y, and Escape for no.
ANSWER_KEYS = frozenset("0123456789y\x1b")


def prompt_refusal(row):
    """Why text meant as the agent's next input cannot land now, or None.

    `row` is the session's row in the last rebuild, None when it lists none.
    A waiting prompt would take the text as its answer, and an exited
    agent's pane is a shell that would run it. Mid-turn the agent queues it.
    A program in front of the agent (`in_front`, see program_in_front) would
    take the text in its place: an editor, or the shell of a suspended agent.
    Nothing on this machine can tell whether a line typed into a remote pane
    reaches the agent or a shell there, so a remote row takes none.
    """
    if row is None:
        return "the session has gone"
    if row.get("host"):
        return REMOTE_NO_REPLY
    if row.get("state") == "blocked":
        return "it is waiting on you"
    if row.get("state") == "exited":
        return "the agent has exited"
    if row.get("in_front"):
        return f"{row['in_front']} is in front"
    return None


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


def typing_refusal(row, strokes):
    """Why these writes may not be typed into the row's pane, or None. Only a remote row is judged here.

    Every write the daemon makes into a pane passes this. A remote pane
    takes one answer key (ANSWER_KEYS), while it waits on you and its own
    checks hold (`remote_refusal`). A line, or any other key, could be run
    by a shell there or end what runs in it.
    """
    if row is None or not row.get("host"):
        return None
    keys = "".join(strokes)
    if len(keys) != 1 or keys not in ANSWER_KEYS:
        return REMOTE_NO_REPLY
    if row.get("remote_refusal"):
        return row["remote_refusal"]
    return None if row.get("state") == "blocked" else "it is not waiting on you"
