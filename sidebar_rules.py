# ABOUTME: Rules about a row the daemon and its helpers share: when a prompt must not be sent to it.
# ABOUTME: Kept apart from sidebar.py so links.py can use them without importing the whole daemon.


def prompt_refusal(row):
    """Why text meant as the agent's next input cannot land now, or None.

    `row` is the session's row in the last rebuild, None when it lists none.
    A waiting prompt would take the text as its answer, and an exited
    agent's pane is a shell that would run it. Mid-turn the agent queues it.
    A program in front of the agent (`in_front`, see program_in_front) would
    take the text in its place: an editor, or the shell of a suspended agent.
    """
    if row is None:
        return "the session has gone"
    if row.get("state") == "blocked":
        return "it is waiting on you"
    if row.get("state") == "exited":
        return "the agent has exited"
    if row.get("in_front"):
        return f"{row['in_front']} is in front"
    return None
