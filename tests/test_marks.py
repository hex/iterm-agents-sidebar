# ABOUTME: Guards marks.py: which sessions get the word Done as iTerm2's badge,
# ABOUTME: what the marker keeps and restores, and that no iTerm2 failure reaches the rebuild.
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import alerts  # noqa: E402
import marks  # noqa: E402
from iterm_fakes import Api, App, Colour, Session  # noqa: E402

ALL_ON = {"mark_badge": True}
OFF = {"mark_badge": False}


def card(sid, state):
    return {"session_id": sid, "state": state, "depth": 0}


def teammate(sid, of):
    return {"session_id": sid, "state": "idle", "depth": 1, "lead": of}


def test_plan_marks_the_new_and_clears_the_gone():
    assert marks.plan({"a", "b"}, {"b", "c"}) == ({"a"}, {"c"})


def test_wanted_takes_every_unseen_card_that_can_show_done_while_the_badge_is_on():
    """Unseen alone decides: it already drops a sid that began a turn, blocked or
    exited, and keeps one through a Stop hook's brief flip to working, which
    the mark must ride out too. A teammate's row never shows Done, so its pane
    gets no mark; a docked worktree or a linked partner is a card of its own."""
    worktree = dict(card("w", "idle"), worktree_of="a")
    rows = [card("a", "idle"), card("b", "working"), teammate("a1", of="a"), card("c", "idle"), worktree]
    want = marks.wanted(rows, {"a", "a1", "b", "c", "w"}, ALL_ON)
    assert want == {"badge": {"a", "b", "c", "w"}}
    assert marks.wanted(rows, {"a"}, OFF) == {}


def test_a_turn_that_restarted_before_the_poll_is_never_marked():
    """Working at one reading and working at the next: Watch sees no end and
    no beginning, Unseen holds nothing, and no pane is written."""
    u = alerts.Unseen()
    u.step(ended=set(), began=set(), looking_at=None, states={"a": "working"})
    assert marks.wanted([card("a", "working")], u.sids, ALL_ON) == {}


def test_a_profile_without_a_badge_is_kept_as_empty_not_none():
    s = Session("a", Profile(badge_text=None))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    kept = {"badge_text": "", "badge_color": Colour(234, 64, 37), "badge_color_light": Colour(255, 38, 0), "badge_color_dark": Colour(234, 64, 37)}
    assert m.have == {"a": {"badge": kept}}
    run(m, app, [card("a", "idle")], set(), ALL_ON, logged.append)
    assert s.writes[1:] == [kept]
    assert logged == []


# ------------------------------------------------------------- the writer

class Profile:
    def __init__(self, badge_text="", badge_color=Colour(234, 64, 37)):
        self.badge_text = badge_text
        # A profile with separate light and dark colours shows these two and ignores badge_color.
        self.badge_color, self.badge_color_light, self.badge_color_dark = badge_color, Colour(255, 38, 0), Colour(234, 64, 37)


class Gone:
    session_id = "gone"

    async def async_get_profile(self):
        raise RuntimeError("session closed")


def run(marker, app, rows, unseen, settings, log):
    asyncio.run(marker.step(app, rows, unseen, settings, log))


def test_write_keeps_the_fields_it_touches_and_restore_puts_them_back():
    s = Session("a", Profile(badge_text=""))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    green = Colour(48, 209, 88, 90)
    red, light = Colour(234, 64, 37), Colour(255, 38, 0)
    assert s.writes == [{"badge_text": "Done", "badge_color": green, "badge_color_light": green, "badge_color_dark": green}]
    assert m.have == {"a": {"badge": {"badge_text": "", "badge_color": red, "badge_color_light": light, "badge_color_dark": red}}}
    run(m, app, [card("a", "idle")], set(), ALL_ON, logged.append)
    assert s.writes[1:] == [{"badge_text": "", "badge_color": red, "badge_color_light": light, "badge_color_dark": red}]
    assert m.have == {}
    assert logged == []


def test_a_busy_badge_is_left_alone_and_logged_once():
    s = Session("abcdefgh-1", Profile(badge_text="mine"))
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("abcdefgh-1", "idle")], {"abcdefgh-1"}, ALL_ON, logged.append)
    run(m, app, [card("abcdefgh-1", "idle")], {"abcdefgh-1"}, ALL_ON, logged.append)
    assert s.writes == []
    assert logged == ["badge busy abcdefgh"]
    assert m.have == {}


def test_a_session_that_vanishes_is_dropped_without_a_have_entry():
    app, logged, m = App(Gone()), [], marks.Marker(api=Api())
    run(m, app, [card("gone", "idle")], {"gone"}, ALL_ON, logged.append)
    assert m.have == {}
    assert logged == ["sweep gone: RuntimeError('session closed')", "mark badge gone: RuntimeError('session closed')"]
    # A session the app no longer knows is simply not wanted: no log, no entry.
    run(m, App(), [card("x", "idle")], {"x"}, ALL_ON, logged.append)
    assert m.have == {} and len(logged) == 2


def test_turning_the_badge_off_puts_back_what_it_replaced():
    s = Session("a", Profile())
    app, logged, m = App(s), [], marks.Marker(api=Api())
    run(m, app, [card("a", "idle")], {"a"}, ALL_ON, logged.append)
    run(m, app, [card("a", "idle")], {"a"}, OFF, logged.append)
    assert s.writes[1:] == [{"badge_text": "", "badge_color": Colour(234, 64, 37),
                             "badge_color_light": Colour(255, 38, 0), "badge_color_dark": Colour(234, 64, 37)}]
    assert m.have == {}


def test_the_first_step_sweeps_a_done_left_by_a_dead_daemon():
    stale, clean = Session("stale-01", Profile(badge_text="Done")), Session("clean-01", Profile(badge_text="mine"))
    app, logged, m = App(stale, clean), [], marks.Marker(api=Api())
    run(m, app, [], set(), ALL_ON, logged.append)
    assert stale.writes == [{"badge_text": ""}] and clean.writes == []
    assert logged == ["swept stale-01 badge_text"]
    run(m, app, [], set(), ALL_ON, logged.append)
    assert stale.writes == [{"badge_text": ""}]
