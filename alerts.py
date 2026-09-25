# ABOUTME: Decides the panel's alerts from successive readings of the sessions: which
# ABOUTME: sound, banner, focus move or banner removal each change of state calls for.


class Watch:
    """Compares each reading with the one before and says what to announce.

    Pure: it returns decisions and the daemon carries them out. An alert
    marks a change of state, never the state itself -- a reading comes every
    few seconds, and announcing a standing state again is how an alert
    becomes noise.
    """

    def __init__(self):
        #: session id -> state at the last reading; None before the first.
        self.states = None
        #: session id -> when its current turn began. Kept while the session
        #: is idle, when the reading no longer carries it: a Stop hook that
        #: runs a command flips a session to working for a few seconds
        #: without a new prompt, and only a prompt moves this.
        self.turns = {}
        #: session id -> the turn it last finished, whether or not that was
        #: announced, so a setting turned back on cannot announce it late.
        self.finished = {}

    def step(self, snapshot, settings, conversations):
        """-> [(verb, session id, kind or None)], in the order to carry out.

        `conversations` maps a session id to the agent conversation it shows,
        where known. Two tmux clients on one session put one conversation in
        two panes, and a moment of that conversation is announced once.
        """
        now = {}
        for group in snapshot.get("groups") or []:
            for row in group.get("rows") or []:
                now[row["session_id"]] = row.get("state")
                if row.get("working_since") is not None:
                    self.turns[row["session_id"]] = row["working_since"]
        before_all, self.states = self.states, now
        if before_all is None:
            return []

        out = []
        focused = False
        announced = set()
        for sid, state in now.items():
            before = before_all.get(sid)
            if state == before:
                continue
            turn = self.turns.get(sid)
            finished = self.finished.get(sid)
            turn_done = (state == "idle" and before == "working"
                         and (turn is None or turn != finished))
            new_turn = state == "working" and turn is not None and turn != finished
            if turn_done and turn is not None:
                self.finished[sid] = turn
            conversation = conversations.get(sid)
            moment = (conversation, state)
            if conversation is not None and moment in announced and (state == "blocked" or turn_done):
                continue
            announced.add(moment)

            if state == "blocked":
                if settings["sound"] and settings["sound_blocked"]:
                    out.append(("sound", sid, "blocked"))
                if settings["notify"] and settings["notify_blocked"]:
                    out.append(("notify", sid, "blocked"))
            elif turn_done:
                if settings["sound"] and settings["sound_done"]:
                    out.append(("sound", sid, "done"))
                if settings["notify"] and settings["notify_done"]:
                    out.append(("notify", sid, "done"))
            # Taken down whatever the settings say now: a banner up from
            # before they changed must not outlive what it announced.
            elif before == "blocked" or new_turn:
                out.append(("notify", sid, "clear"))

            # One session per reading: two blocking at once would otherwise
            # each take focus in turn, leaving you on whichever came last.
            if state == "blocked" and settings["focus_blocked"] and not focused:
                out.append(("bring", sid, None))
                focused = True
            # The daemon goes back only if it brought you there and you are
            # still there, so this is safe for every session leaving blocked.
            if before == "blocked" and settings["focus_blocked"] and settings["return_after_blocked"]:
                out.append(("return", sid, None))

        for sid in before_all.keys() - now.keys():
            self.turns.pop(sid, None)
            self.finished.pop(sid, None)
            out.append(("notify", sid, "clear"))
        return out
