# ABOUTME: Guards tabcolour.py: which cards paint their iTerm2 tab, the 35% mix over each background,
# ABOUTME: what the painter keeps and puts back, whose colour it leaves alone, and a daemon's restart.
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tabcolour  # noqa: E402
from iterm_fakes import Api, App, Colour, Session  # noqa: E402


def test_the_mix_is_35_percent_of_the_colour_over_the_background_a_half_rounding_up():
    """Worked by hand, 0.35 * colour + 0.65 * background per channel. Orange over
    (253, 246, 227) is the tab the colour was picked on; blue's last channel is
    106.5, where round() would give 106."""
    palette = tabcolour.PALETTE
    assert tabcolour.mix(palette["orange"], (253, 246, 227)) == (240, 202, 178)
    assert tabcolour.mix(palette["blue"], (40, 42, 54)) == (63, 82, 107)
    assert tabcolour.mix(palette["cyan"], (30, 30, 30)) == (22, 70, 82)
    assert tabcolour.mix(palette["red"], (255, 255, 255)) == (243, 179, 179)


def test_the_palette_is_claude_codes_own_as_cs_keeps_it():
    """The values cs's _session_color_rgb gives each name, not the panel's SESSION_COLOURS."""
    assert tabcolour.PALETTE == {
        "red": (220, 38, 38), "blue": (106, 155, 204), "green": (22, 163, 74), "yellow": (202, 138, 4),
        "purple": (130, 125, 189), "orange": (217, 119, 87), "pink": (196, 102, 134), "cyan": (8, 145, 178)}


ON = {"tab_colour": True}
OFF = {"tab_colour": False}


def card(sid, colour=None, **more):
    row = {"session_id": sid, "depth": 0, **more}
    if colour:
        row["colour"] = colour
    return row


def teammate(sid, colour):
    return {"session_id": sid, "depth": 1, "colour": colour}


def test_only_a_local_card_in_a_colour_of_the_palette_paints_its_tab():
    """A teammate's pane, a card cs gave no colour, a name outside the palette
    and a remote card leave their tabs alone; so does every card while the
    setting is off."""
    rows = [card("a", "orange"), teammate("b", "blue"), card("c"), card("d", "default"),
            card("e", "green", host="build-box")]
    assert tabcolour.wanted(rows, ON) == {"a": "orange"}
    assert tabcolour.wanted(rows, OFF) == {}


def test_cards_that_share_one_pane_paint_its_tab_only_in_a_colour_they_all_wear():
    """Plain tmux puts several cards on one iTerm2 session, and its tab has one
    colour: in either one's it would name the other wrongly. A teammate there
    has no say."""
    assert tabcolour.wanted([card("t", "orange"), card("t", "orange")], ON) == {"t": "orange"}
    assert tabcolour.wanted([card("t", "orange"), card("t", "blue")], ON) == {}
    assert tabcolour.wanted([card("t", "orange"), card("t")], ON) == {}
    assert tabcolour.wanted([card("t", "orange"), teammate("t", "blue")], ON) == {"t": "orange"}


# ------------------------------------------------------------- the painter

#: Backgrounds as iTerm2 hands them out, floats a little off the whole numbers they round to:
#: (40, 42, 54), (253, 246, 227) and (21, 23, 40).
PLAIN, LIGHT, DARK = Colour(39.6, 42.4, 54.49), Colour(253.0, 246.0, 227.0), Colour(21.0, 23.0, 40.0)
TAB_FIELDS = ("tab_color", "tab_color_light", "tab_color_dark", "use_tab_color", "use_tab_color_light", "use_tab_color_dark")


class Profile:
    """A session's profile as iTerm2 hands it out: a key it lacks reads None."""
    def __init__(self, plain=PLAIN, light=LIGHT, dark=DARK, separate=False, **tab):
        self.background_color, self.background_color_light, self.background_color_dark = plain, light, dark
        self.use_separate_colors_for_light_and_dark_mode = separate
        for field in TAB_FIELDS:
            setattr(self, field, tab.pop(field, None))
        assert not tab, tab


def run(painter, app, rows, settings, log):
    asyncio.run(painter.step(app, rows, settings, log))


def test_a_card_paints_each_tab_colour_over_its_own_background_and_turns_all_three_on():
    """Plain over the plain background, light over the light one, dark over the
    dark one: a profile with separate light and dark colours shows those two
    and ignores the plain one, and either may be in front."""
    s = Session("a", Profile())
    logged, p = [], tabcolour.Painter(api=Api())
    run(p, App(s), [card("a", "orange")], ON, logged.append)
    assert s.writes == [{"tab_color": Colour(102, 69, 66), "use_tab_color": True,
                         "tab_color_light": Colour(240, 202, 178), "use_tab_color_light": True,
                         "tab_color_dark": Colour(90, 57, 56), "use_tab_color_dark": True}]
    assert logged == []


#: What a profile with a plain tab colour of its own, switched off, and no light or dark one gets back.
PUT_BACK = {"use_tab_color": False, "tab_color": Colour(10, 20, 30), "use_tab_color_light": False, "use_tab_color_dark": False}


@pytest.mark.parametrize("rows, settings", [([], ON), ([card("a", "orange")], OFF)], ids=["card gone", "setting off"])
def test_a_tab_no_longer_wanted_gets_back_what_the_paint_replaced(rows, settings):
    """The pane lives on. Each switch the paint turned on goes back off, and
    each colour the profile had goes back; one it never had is not written,
    since iTerm2 refuses None."""
    s = Session("a", Profile(tab_color=Colour(10, 20, 30), use_tab_color=False))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [card("a", "orange")], ON, logged.append)
    run(p, app, rows, settings, logged.append)
    assert s.writes[1:] == [PUT_BACK]
    assert p.have == {} and logged == []


def test_a_new_colour_repaints_the_tab_and_keeps_what_the_first_paint_replaced():
    """Turned off after the change, the tab gets the profile's own back, never
    the orange it wore in between."""
    s = Session("a", Profile(tab_color=Colour(10, 20, 30), use_tab_color=False))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [card("a", "orange")], ON, logged.append)
    run(p, app, [card("a", "blue")], ON, logged.append)
    run(p, app, [card("a", "blue")], OFF, logged.append)
    assert s.writes[1:] == [{"tab_color": Colour(63, 82, 107), "use_tab_color": True,
                             "tab_color_light": Colour(202, 214, 219), "use_tab_color_light": True,
                             "tab_color_dark": Colour(51, 69, 97), "use_tab_color_dark": True},
                            PUT_BACK]
    assert logged == []


@pytest.mark.parametrize("profile", [
    Profile(use_tab_color=True, tab_color=Colour(0, 128, 255)),
    Profile(separate=True, use_tab_color_dark=True, tab_color_dark=Colour(0, 128, 255)),
], ids=["plain", "dark of a separate profile"])
def test_a_pane_that_shows_a_tab_colour_of_its_own_keeps_it_and_the_log_says_so_once(profile):
    """Read at start and once to decide: nothing about it changes until its card wants another colour."""
    s = Session("abcdefgh-1", profile)
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    for _ in range(3):
        run(p, app, [card("abcdefgh-1", "orange")], ON, logged.append)
    assert (s.writes, s.reads, logged) == ([], 2, ["tab colour own abcdefgh"])


def test_a_colour_of_its_own_on_a_variant_the_pane_does_not_show_is_never_written_over():
    """A plain profile ignores its light tab colour, so the pane is painted, but
    that colour stays the profile's own."""
    s = Session("a", Profile(use_tab_color_light=True, tab_color_light=Colour(0, 128, 255)))
    logged, p = [], tabcolour.Painter(api=Api())
    run(p, App(s), [card("a", "orange")], ON, logged.append)
    assert s.writes == [{"tab_color": Colour(102, 69, 66), "use_tab_color": True,
                         "tab_color_dark": Colour(90, 57, 56), "use_tab_color_dark": True}]


def test_a_variant_with_no_background_is_never_written_and_a_shown_one_leaves_the_tab_alone():
    """A plain profile often has no light background: its plain and dark tab
    colours are painted. A separate profile with no dark one cannot show the
    mix the user picked, so its tab is left alone and the log says so once."""
    plain = Session("a", Profile(light=None))
    separate = Session("abcdefgh-2", Profile(dark=None, separate=True))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(plain, separate)
    for _ in range(2):
        run(p, app, [card("a", "orange"), card("abcdefgh-2", "orange")], ON, logged.append)
    assert plain.writes == [{"tab_color": Colour(102, 69, 66), "use_tab_color": True,
                             "tab_color_dark": Colour(90, 57, 56), "use_tab_color_dark": True}]
    assert (separate.writes, separate.reads, logged) == ([], 2, ["tab colour no background abcdefgh"])


def painted_then(change, rows, settings=ON, sid="abcdefgh-3"):
    """A tab painted orange, `change` done to its pane outside the panel, then one more reading."""
    s = Session(sid, Profile(tab_color=Colour(10, 20, 30), use_tab_color=False))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [card(sid, "orange")], ON, logged.append)
    change(s)
    run(p, app, rows, settings, logged.append)
    return s, p, logged


def recolour(session):
    """What the tab menu's colour picker does: the pane's own tab colour, its switch on."""
    session.profile.tab_color = Colour(0, 128, 255)


def switch_off(session):
    """What the tab menu does for no colour: the switch off, the colour left as it was."""
    session.profile.use_tab_color = False


def swap(session):
    """Automatic Profile Switching gives the pane a profile with no tab colour."""
    session.profile = Profile()


@pytest.mark.parametrize("change", [recolour, switch_off, swap], ids=["recoloured", "switched off", "profile swapped"])
def test_a_tab_changed_outside_the_panel_after_its_paint_is_neither_painted_over_nor_put_back(change):
    """Read before every touch, after the reads at start and for the paint:
    the tab is as its owner left it while its card lasts, whatever colour the
    card turns, and the log says so once."""
    s, p, logged = painted_then(change, [card("abcdefgh-3", "blue")])
    run(p, App(s), [card("abcdefgh-3", "blue")], ON, logged.append)
    run(p, App(s), [], ON, logged.append)
    assert (s.writes[1:], s.reads, logged) == ([], 3, ["tab colour recoloured abcdefgh"])
    s, p, logged = painted_then(change, [])
    assert (s.writes[1:], s.reads, p.have, logged) == ([], 3, {}, ["tab colour recoloured abcdefgh"])


def test_a_card_that_comes_back_to_a_swapped_profile_paints_it_and_gives_back_that_profiles_own():
    s, p, logged = painted_then(swap, [])
    run(p, App(s), [card("abcdefgh-3", "blue")], ON, logged.append)
    run(p, App(s), [card("abcdefgh-3", "blue")], OFF, logged.append)
    assert s.writes[2:] == [ALL_OFF]


def test_a_paint_of_ours_under_a_switch_that_is_off_is_never_kept_as_the_profiles_own():
    """A restart put the switch back off and left the orange in the field: a
    blue paint later gives back the switch alone, never that orange."""
    s = Session("a", Profile(use_tab_color=False, tab_color=Colour(102.0, 69.0, 66.0)))
    logged, p = [], tabcolour.Painter(api=Api())
    run(p, App(s), [card("a", "blue")], ON, logged.append)
    run(p, App(s), [card("a", "blue")], OFF, logged.append)
    assert (s.writes[1:], logged) == ([ALL_OFF], [])


def left_by_a_daemon_that_died(sid="stale-01"):
    """A pane still wearing the orange the daemon before this one painted."""
    return Session(sid, Profile(use_tab_color=True, tab_color=Colour(102.0, 69.0, 66.0),
                                use_tab_color_light=True, tab_color_light=Colour(240.0, 202.0, 178.0),
                                use_tab_color_dark=True, tab_color_dark=Colour(90.0, 57.0, 56.0)))


ALL_OFF = {"use_tab_color": False, "use_tab_color_light": False, "use_tab_color_dark": False}


def test_a_restarted_daemon_takes_its_own_paint_back_and_never_for_the_panes_own():
    """It reads every pane once and knows the mixes it would paint there. Still
    wanted, the tab is left as it is; gone or recoloured, its switches go back
    off, the state any painted variant had, and the paint stays unseen under them."""
    for rows, writes in [([card("stale-01", "orange")], []), ([], [ALL_OFF])]:
        s = left_by_a_daemon_that_died()
        logged, p = [], tabcolour.Painter(api=Api())
        run(p, App(s), rows, ON, logged.append)
        assert (s.writes, s.reads, logged) == (writes, 1 + len(writes), ["tab colour adopted stale-01 orange"])
    s = left_by_a_daemon_that_died()
    logged, p = [], tabcolour.Painter(api=Api())
    run(p, App(s), [card("stale-01", "blue")], ON, logged.append)
    run(p, App(s), [card("stale-01", "blue")], OFF, logged.append)
    assert s.writes == [{"tab_color": Colour(63, 82, 107), "use_tab_color": True,
                         "tab_color_light": Colour(202, 214, 219), "use_tab_color_light": True,
                         "tab_color_dark": Colour(51, 69, 97), "use_tab_color_dark": True}, ALL_OFF]
    assert logged == ["tab colour adopted stale-01 orange"]


def test_the_restart_reads_each_pane_once_and_a_colour_that_is_no_mix_of_ours_stays():
    own = Session("own-01", Profile(use_tab_color=True, tab_color=Colour(0, 128, 255)))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(own, left_by_a_daemon_that_died())
    for _ in range(2):
        run(p, app, [], ON, logged.append)
    assert (own.writes, own.reads) == ([], 1)
    assert logged == ["tab colour adopted stale-01 orange"]


class Refusing(Session):
    """A pane whose profile reads or writes fail while the test says so."""
    def __init__(self, sid, profile, reads=False, writes=False):
        super().__init__(sid, profile)
        self.refuse_reads, self.refuse_writes = reads, writes

    async def async_get_profile(self):
        if self.refuse_reads:
            raise RuntimeError("session closed")
        return await super().async_get_profile()

    async def async_set_profile_properties(self, local):
        if self.refuse_writes:
            raise RuntimeError("REQUEST_MALFORMED")
        await super().async_set_profile_properties(local)


def test_an_iterm2_call_that_fails_drops_that_tab_is_logged_and_the_rest_are_painted():
    """At start, at the paint and at the write: the rebuild goes on, and the
    failed tab is not tried again while its card wants the same colour."""
    unread = Refusing("unread-1", Profile(), reads=True)
    unwritten = Refusing("unwritten-1", Profile(), writes=True)
    fine = Session("fine-01", Profile())
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(unread, unwritten, fine)
    rows = [card("unread-1", "orange"), card("unwritten-1", "orange"), card("fine-01", "orange")]
    for _ in range(2):
        run(p, app, rows, ON, logged.append)
    assert logged == ["tab colour unread-1: RuntimeError('session closed')",
                      "tab colour unread-1: RuntimeError('session closed')",
                      "tab colour unwritte: RuntimeError('REQUEST_MALFORMED')"]
    assert (unwritten.writes, len(fine.writes)) == ([], 1)
    reads = unwritten.reads
    run(p, app, [], ON, logged.append)
    assert (unwritten.reads, len(logged)) == (reads, 3)


def test_a_paint_a_failed_put_back_left_is_taken_for_ours_when_its_card_returns():
    """It is a mix of ours over the pane's own background, not the pane's own colour."""
    s = Refusing("a", Profile(tab_color=Colour(10, 20, 30), use_tab_color=False))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [card("a", "orange")], ON, logged.append)
    s.refuse_writes = True
    run(p, app, [], ON, logged.append)
    s.refuse_writes = False
    run(p, app, [card("a", "blue")], ON, logged.append)
    run(p, app, [], ON, logged.append)
    assert logged == ["tab colour a: RuntimeError('REQUEST_MALFORMED')"]
    assert s.writes[-1] == ALL_OFF


def test_a_rebuild_that_changes_nothing_asks_iterm2_nothing():
    s = Session("a", Profile())
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    for _ in range(4):
        run(p, app, [card("a", "orange")], ON, logged.append)
    assert (s.reads, len(s.writes), logged) == (2, 1, [])


def test_a_pane_that_closed_is_forgotten_without_a_call():
    s = Session("a", Profile())
    logged, p = [], tabcolour.Painter(api=Api())
    run(p, App(s), [card("a", "orange")], ON, logged.append)
    run(p, App(), [], ON, logged.append)
    run(p, App(), [card("b", "blue")], ON, logged.append)
    assert (s.reads, len(s.writes), p.have, logged) == (2, 1, {}, [])


def test_a_restart_leaves_a_tab_whose_shown_colours_are_not_all_one_paint_of_ours():
    """The light one wears the orange mix and the dark one a colour the user
    picked since: the tab is theirs, in both appearances."""
    s = Session("mixed-01", Profile(separate=True, use_tab_color_light=True, tab_color_light=Colour(240.0, 202.0, 178.0),
                                    use_tab_color_dark=True, tab_color_dark=Colour(0, 128, 255)))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [], ON, logged.append)
    run(p, app, [card("mixed-01", "orange")], ON, logged.append)
    assert (s.writes, logged) == ([], ["tab colour own mixed-01"])


class NullTabColour(Profile):
    """A profile whose tab colour key holds null, as a Dynamic Profile can: iterm2.Profile fails to read it."""
    def __getattribute__(self, name):
        if name == "tab_color":
            raise TypeError("'NoneType' object is not subscriptable")
        return super().__getattribute__(name)


def test_a_profile_iterm2_hands_over_but_its_package_cannot_read_drops_that_tab_and_the_rebuild_goes_on():
    unreadable, fine = Session("null-001", NullTabColour()), Session("fine-01", Profile())
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(unreadable, fine)
    for _ in range(2):
        run(p, app, [card("null-001", "orange"), card("fine-01", "orange")], ON, logged.append)
    assert logged == ["tab colour null-001: TypeError(\"'NoneType' object is not subscriptable\")"] * 2
    assert (unreadable.writes, len(fine.writes)) == ([], 1)


def test_a_tab_left_alone_is_looked_at_again_when_its_card_wants_another_colour():
    """A refused write is tried again then, and a colour of the pane's own is
    found again and kept."""
    refused = Refusing("refused1", Profile(), writes=True)
    own = Session("own-0001", Profile(use_tab_color=True, tab_color=Colour(0, 128, 255)))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(refused, own)
    run(p, app, [card("refused1", "orange"), card("own-0001", "orange")], ON, logged.append)
    refused.refuse_writes = False
    run(p, app, [card("refused1", "blue"), card("own-0001", "blue")], ON, logged.append)
    assert refused.writes == [{"tab_color": Colour(63, 82, 107), "use_tab_color": True,
                               "tab_color_light": Colour(202, 214, 219), "use_tab_color_light": True,
                               "tab_color_dark": Colour(51, 69, 97), "use_tab_color_dark": True}]
    assert (own.writes, logged) == ([], ["tab colour own own-0001", "tab colour refused1: RuntimeError('REQUEST_MALFORMED')",
                                         "tab colour own own-0001"])


def test_a_background_edited_under_the_paint_takes_the_next_colour_over_the_new_background():
    """The tab still shows what was written, so it is still the panel's."""
    s = Session("a", Profile(tab_color=Colour(10, 20, 30), use_tab_color=False))
    logged, p = [], tabcolour.Painter(api=Api())
    app = App(s)
    run(p, app, [card("a", "orange")], ON, logged.append)
    s.profile.background_color = Colour(0.0, 0.0, 0.0)
    run(p, app, [card("a", "blue")], ON, logged.append)
    run(p, app, [], ON, logged.append)
    assert s.writes[1:] == [{"tab_color": Colour(37, 54, 71), "use_tab_color": True,
                             "tab_color_light": Colour(202, 214, 219), "use_tab_color_light": True,
                             "tab_color_dark": Colour(51, 69, 97), "use_tab_color_dark": True}, PUT_BACK]
    assert logged == []
