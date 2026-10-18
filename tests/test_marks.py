# ABOUTME: Guards marks.py: which sessions get the word Done as iTerm2's badge or a green tab,
# ABOUTME: what the marker keeps and restores, and that no iTerm2 failure reaches the rebuild.
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import alerts  # noqa: E402
import marks  # noqa: E402

ALL_ON = {"mark_badge": True, "mark_tab": True}


def card(sid, state):
    return {"session_id": sid, "state": state, "depth": 0}


def teammate(sid, of):
    return {"session_id": sid, "state": "idle", "depth": 1, "lead": of}


def test_plan_marks_the_new_and_clears_the_gone():
    assert marks.plan({"a", "b"}, {"b", "c"}) == ({"a"}, {"c"})


def test_wanted_takes_every_unseen_card_that_can_show_done_per_enabled_channel():
    """Unseen alone decides: it already drops a sid that began a turn, blocked or
    exited, and keeps one through a Stop hook's brief flip to working, which
    the mark must ride out too. A teammate's row never shows Done, so its pane
    gets no mark; a docked worktree or a linked partner is a card of its own."""
    worktree = dict(card("w", "idle"), worktree_of="a")
    rows = [card("a", "idle"), card("b", "working"), teammate("a1", of="a"), card("c", "idle"), worktree]
    want = marks.wanted(rows, {"a", "a1", "b", "c", "w"}, {"mark_badge": True, "mark_tab": True})
    assert want == {"badge": {"a", "b", "c", "w"}, "tab": {"a", "b", "c", "w"}}
    assert marks.wanted(rows, {"a"}, {"mark_badge": True, "mark_tab": False}) == {"badge": {"a"}}


def test_a_turn_that_restarted_before_the_poll_is_never_marked():
    """Working at one reading and working at the next: Watch sees no end and
    no beginning, Unseen holds nothing, and no pane is written."""
    u = alerts.Unseen()
    u.step(ended=set(), began=set(), looking_at=None, states={"a": "working"})
    assert marks.wanted([card("a", "working")], u.sids, ALL_ON) == {}


def test_a_profile_without_the_fields_is_kept_as_empty_and_off_not_none():
    s = Session("a", Profile(badge_text=None, use_tab_color=None, tab_color=None))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    kept = {"badge_text": "", "badge_color": Colour(234, 64, 37), "badge_color_light": Colour(255, 38, 0), "badge_color_dark": Colour(234, 64, 37)}
    assert m.have == {"a": {"badge": kept, "tab": {"use_tab_color": False, "tab_color": None}}}
    run(m, app, [card("a", "idle")], set(), ALL_ON, logged.append)
    assert s.writes[2:] == [kept, {"use_tab_color": False, "tab_color": None}]


# ------------------------------------------------------------- the writer

class Colour:
    def __init__(self, r, g, b, a=255):
        self.rgb = (r, g, b, a)

    def __eq__(self, other):
        return isinstance(other, Colour) and other.rgb == self.rgb

    def __repr__(self):
        return f"Colour{self.rgb}"


class LocalProfile:
    """What iterm2.LocalWriteOnlyProfile does for the marker: takes the fields and remembers them."""
    def __init__(self):
        self.values = {}

    def set_badge_text(self, value):
        self.values["badge_text"] = value

    def set_badge_color(self, value):
        self.values["badge_color"] = value

    def set_badge_color_light(self, value):
        self.values["badge_color_light"] = value

    def set_badge_color_dark(self, value):
        self.values["badge_color_dark"] = value

    def set_use_tab_color(self, value):
        self.values["use_tab_color"] = value

    def set_tab_color(self, value):
        self.values["tab_color"] = value


class Api:
    LocalWriteOnlyProfile = LocalProfile
    Color = Colour


class Profile:
    def __init__(self, badge_text="", use_tab_color=False, tab_color=Colour(0, 0, 0), badge_color=Colour(234, 64, 37)):
        self.badge_text, self.use_tab_color, self.tab_color = badge_text, use_tab_color, tab_color
        # A profile with separate light and dark colours shows these two and ignores badge_color.
        self.badge_color, self.badge_color_light, self.badge_color_dark = badge_color, Colour(255, 38, 0), Colour(234, 64, 37)


class Session:
    def __init__(self, sid, profile=None):
        self.session_id = sid
        self.profile = profile or Profile()
        self.writes = []

    async def async_get_profile(self):
        return self.profile

    async def async_set_profile_properties(self, local):
        self.writes.append(dict(local.values))
        for field, value in local.values.items():
            setattr(self.profile, field, value)


class Gone:
    session_id = "gone"

    async def async_get_profile(self):
        raise RuntimeError("session closed")


class App:
    def __init__(self, *sessions):
        self.sessions = {s.session_id: s for s in sessions}
        self.terminal_windows = [type("W", (), {"tabs": [type("T", (), {"sessions": list(self.sessions.values())})()]})()]

    def get_session_by_id(self, sid):
        return self.sessions.get(sid)


def run(marker, app, rows, unseen, settings, log):
    asyncio.run(marker.step(app, rows, unseen, settings, log))


def test_write_keeps_the_fields_it_touches_and_restore_puts_them_back():
    s = Session("a", Profile(badge_text="", use_tab_color=False, tab_color=Colour(1, 2, 3)))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    green = Colour(48, 209, 88, 90)
    red, light = Colour(234, 64, 37), Colour(255, 38, 0)
    assert s.writes == [{"badge_text": "Done", "badge_color": green, "badge_color_light": green, "badge_color_dark": green},
                        {"use_tab_color": True, "tab_color": Colour(48, 209, 88)}]
    assert m.have == {"a": {"badge": {"badge_text": "", "badge_color": red, "badge_color_light": light, "badge_color_dark": red},
                            "tab": {"use_tab_color": False, "tab_color": Colour(1, 2, 3)}}}
    run(m, app, [card("a", "idle")], set(), ALL_ON, logged.append)
    assert s.writes[2:] == [{"badge_text": "", "badge_color": red, "badge_color_light": light, "badge_color_dark": red},
                            {"use_tab_color": False, "tab_color": Colour(1, 2, 3)}]
    assert m.have == {}
    assert logged == []


def test_a_busy_badge_is_left_alone_and_logged_once():
    s = Session("abcdefgh-1", Profile(badge_text="mine"))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("abcdefgh-1", "idle")], {"abcdefgh-1"}, {"mark_badge": True, "mark_tab": False}, logged.append)
    run(m, app, [card("abcdefgh-1", "idle")], {"abcdefgh-1"}, {"mark_badge": True, "mark_tab": False}, logged.append)
    assert s.writes == []
    assert logged == ["badge busy abcdefgh"]
    assert m.have == {}


def test_a_session_that_vanishes_is_dropped_without_a_have_entry():
    app, logged, m = App(Gone()), [], marks.Marker(api=Api())
    run(m, app, [card("gone", "idle")], {"gone"}, ALL_ON, logged.append)
    assert m.have == {}
    assert logged == ["sweep gone: RuntimeError('session closed')",
                      "mark badge gone: RuntimeError('session closed')", "mark tab gone: RuntimeError('session closed')"]
    # A session the app no longer knows is simply not wanted: no log, no entry.
    run(m, App(), [card("x", "idle")], {"x"}, ALL_ON, logged.append)
    assert m.have == {} and len(logged) == 3


def test_turning_a_channel_off_clears_only_that_channels_fields():
    s = Session("a")
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    run(m, app, [card("a", "idle")], {"a"}, {"mark_badge": True, "mark_tab": False}, logged.append)
    assert s.writes[2:] == [{"use_tab_color": False, "tab_color": Colour(0, 0, 0)}]
    assert m.have == {"a": {"badge": {"badge_text": "", "badge_color": Colour(234, 64, 37),
                                      "badge_color_light": Colour(255, 38, 0), "badge_color_dark": Colour(234, 64, 37)}}}


def test_the_first_step_sweeps_a_done_left_by_a_dead_daemon():
    stale, clean = Session("stale-01", Profile(badge_text="Done")), Session("clean-01", Profile(badge_text="mine"))
    app, logged, m = App(stale, clean), [], marks.Marker(api=Api())
    run(m, app, [], set(), ALL_ON, logged.append)
    assert stale.writes == [{"badge_text": ""}] and clean.writes == []
    assert logged == ["swept stale-01 badge_text"]
    run(m, app, [], set(), ALL_ON, logged.append)
    assert stale.writes == [{"badge_text": ""}]
