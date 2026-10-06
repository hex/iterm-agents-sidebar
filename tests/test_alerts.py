"""The daemon decides every alert from its own reading of the sessions.

A page used to decide, from whatever frames reached it: each window's page
kept its own copy of the settings, and a page that fell behind announced a
backlog of old changes at once. The daemon reads each session itself, so
what it decides is current and decided once.

Ways it could go wrong, each covered below:
- the first reading announces every standing state, as though it had just
  happened;
- a state that did not change is announced again on every reading;
- a turn that ends twice (a Stop hook flips the session to working for a few
  seconds without a prompt) sounds or posts "finished" twice;
- a setting that is off still lets its sound or banner through, or one that
  is on is ignored;
- a banner that is off leaves a standing one up after the session moves on;
- two sessions blocking in one reading each take focus in turn;
- focus goes back when return_after_blocked is off, or without focus_blocked;
- a session that closes leaves its banner standing;
- a session that first appears already blocked says nothing;
- one conversation shown in two panes (two tmux clients on one session) sounds,
  posts and takes focus twice for one moment.

The unseen mark a finished turn leaves on its card could go wrong too:
- a Stop hook's flip to working and back erases it for good;
- a turn that ends in front of you is marked, or a marked one stays marked
  once you look at it;
- it outlives a new turn, a block, an exit or the session;
- it depends on the alert settings, or only one pane of a conversation gets it.
"""
import alerts

ON = {"sound": True, "sound_blocked": True, "sound_done": True,
      "notify": True, "notify_blocked": True, "notify_done": True,
      "focus_blocked": False, "return_after_blocked": True}


def reading(*rows):
    return {"groups": [{"rows": [dict(zip(("session_id", "state", "working_since"), r)) for r in rows]}]}


def run(watch, *readings, settings=ON, conversations=None):
    out = []
    for snap in readings:
        out.append(watch.step(snap, settings, conversations or {}))
    return out


def test_the_first_reading_is_only_a_baseline():
    assert run(alerts.Watch(), reading(("a", "blocked", None), ("b", "idle", None))) == [[]]


def test_a_state_that_holds_says_nothing():
    r = reading(("a", "working", 100))
    assert run(alerts.Watch(), r, r, r)[1:] == [[], []]


def test_a_blocked_session_sounds_and_posts_its_banner():
    out = run(alerts.Watch(), reading(("a", "working", 100)), reading(("a", "blocked", None)))
    assert out[1] == [("sound", "a", "blocked"), ("notify", "a", "blocked")]


def test_a_finished_turn_sounds_and_posts_once_however_often_it_flips_back():
    out = run(alerts.Watch(),
              reading(("a", "working", 100)),
              reading(("a", "idle", None)),
              # A Stop hook runs a command: working again, no new prompt.
              reading(("a", "working", 100)),
              reading(("a", "idle", None)))
    assert out[1:] == [[("sound", "a", "done"), ("notify", "a", "done")], [], []]


def test_a_new_prompt_takes_the_finished_banner_down_and_finishes_again():
    out = run(alerts.Watch(),
              reading(("a", "working", 100)),
              reading(("a", "idle", None)),
              reading(("a", "working", 200)),
              reading(("a", "idle", None)))
    assert out[2:] == [[("notify", "a", "clear")],
                       [("sound", "a", "done"), ("notify", "a", "done")]]


def test_a_turn_with_no_known_start_still_finishes():
    out = run(alerts.Watch(), reading(("a", "working", None)), reading(("a", "idle", None)))
    assert out[1] == [("sound", "a", "done"), ("notify", "a", "done")]


def test_leaving_blocked_takes_the_banner_down():
    out = run(alerts.Watch(), reading(("a", "blocked", None)), reading(("a", "working", 100)))
    assert out[1] == [("notify", "a", "clear")]
    # Dismissed with Escape: back to idle, no turn under way.
    out = run(alerts.Watch(), reading(("a", "blocked", None)), reading(("a", "idle", None)))
    assert out[1] == [("notify", "a", "clear")]


def test_each_setting_that_is_off_holds_back_its_own_alert_only():
    blocked = [reading(("a", "working", 100)), reading(("a", "blocked", None))]
    done = [reading(("a", "working", 100)), reading(("a", "idle", None))]
    assert run(alerts.Watch(), *blocked, settings={**ON, "sound_blocked": False})[1] == [("notify", "a", "blocked")]
    assert run(alerts.Watch(), *blocked, settings={**ON, "notify_blocked": False})[1] == [("sound", "a", "blocked")]
    assert run(alerts.Watch(), *done, settings={**ON, "sound_done": False})[1] == [("notify", "a", "done")]
    assert run(alerts.Watch(), *done, settings={**ON, "notify_done": False})[1] == [("sound", "a", "done")]
    assert run(alerts.Watch(), *done, settings={**ON, "sound": False, "notify": False})[1] == []


def test_a_finished_turn_held_back_by_settings_is_still_that_turns_end():
    """Turned back on a moment later, the Stop-hook flip must not post it late."""
    watch = alerts.Watch()
    run(watch, reading(("a", "working", 100)))
    run(watch, reading(("a", "idle", None)), settings={**ON, "sound": False, "notify": False})
    assert run(watch, reading(("a", "working", 100)), reading(("a", "idle", None))) == [[], []]


def test_a_banner_is_taken_down_even_with_banners_off():
    out = run(alerts.Watch(), reading(("a", "blocked", None)), reading(("a", "working", 100)),
              settings={**ON, "notify": False})
    assert out[1] == [("notify", "a", "clear")]


def test_only_the_first_of_two_blocking_sessions_takes_focus():
    out = run(alerts.Watch(),
              reading(("a", "working", 100), ("b", "working", 100)),
              reading(("a", "blocked", None), ("b", "blocked", None)),
              settings={**ON, "sound": False, "notify": False, "focus_blocked": True})
    assert out[1] == [("bring", "a", None)]


def test_focus_goes_back_only_when_both_settings_ask_for_it():
    readings = [reading(("a", "blocked", None)), reading(("a", "working", 100))]
    quiet = {**ON, "sound": False, "notify": False}
    assert run(alerts.Watch(), *readings, settings={**quiet, "focus_blocked": True})[1] == [
        ("notify", "a", "clear"), ("return", "a", None)]
    assert run(alerts.Watch(), *readings, settings={**quiet, "focus_blocked": True,
                                                    "return_after_blocked": False})[1] == [("notify", "a", "clear")]
    assert run(alerts.Watch(), *readings, settings=quiet)[1] == [("notify", "a", "clear")]


def test_a_session_that_closes_takes_its_banner_with_it():
    out = run(alerts.Watch(), reading(("a", "blocked", None), ("b", "idle", None)), reading(("b", "idle", None)))
    assert out[1] == [("notify", "a", "clear")]


def test_a_session_that_appears_already_blocked_is_announced():
    out = run(alerts.Watch(), reading(("a", "idle", None)), reading(("a", "idle", None), ("b", "blocked", None)))
    assert out[1] == [("sound", "b", "blocked"), ("notify", "b", "blocked")]


def test_one_conversation_in_two_panes_is_announced_once():
    both = {"a": "conv-1", "b": "conv-1"}
    out = run(alerts.Watch(),
              reading(("a", "working", 100), ("b", "working", 100)),
              reading(("a", "blocked", None), ("b", "blocked", None)),
              reading(("a", "working", 200), ("b", "working", 200)),
              reading(("a", "idle", None), ("b", "idle", None)),
              settings={**ON, "focus_blocked": True}, conversations=both)
    assert out[1] == [("sound", "a", "blocked"), ("notify", "a", "blocked"), ("bring", "a", None)]
    # Each pane's banner is its own to take down; only one was posted.
    assert out[2] == [("notify", "a", "clear"), ("return", "a", None),
                      ("notify", "b", "clear"), ("return", "b", None)]
    assert out[3] == [("sound", "a", "done"), ("notify", "a", "done")]


def test_panes_whose_conversation_is_unknown_are_each_their_own():
    out = run(alerts.Watch(),
              reading(("a", "working", 100), ("b", "working", 100)),
              reading(("a", "blocked", None), ("b", "blocked", None)),
              settings={**ON, "sound": False}, conversations={"a": None})
    assert out[1] == [("notify", "a", "blocked"), ("notify", "b", "blocked")]


def marks(*readings, looking_at=None, settings=ON, conversations=None):
    """The unseen set after each reading, Watch and Unseen stepped together."""
    watch, unseen = alerts.Watch(), alerts.Unseen()
    out = []
    for snap in readings:
        watch.step(snap, settings, conversations or {})
        unseen.step(watch.ended, watch.began, looking_at, watch.states)
        out.append(set(unseen.sids))
    return out


def test_a_stop_hook_that_flips_the_session_to_working_keeps_its_unseen_finish():
    """A Stop hook that runs a command does this on every turn: cleared on the
    flip, the mark would never come back, since the flip back to idle ends
    no new turn."""
    out = marks(reading(("a", "working", 100)),
                reading(("a", "idle", None)),
                reading(("a", "working", 100)),
                reading(("a", "idle", None)))
    assert out == [set(), {"a"}, {"a"}, {"a"}]


def test_a_turn_that_ends_in_front_of_you_is_not_marked():
    out = marks(reading(("a", "working", 100), ("b", "working", 100)),
                reading(("a", "idle", None), ("b", "idle", None)),
                looking_at="a")
    assert out == [set(), {"b"}]


def test_looking_at_a_marked_session_takes_its_mark_off():
    watch, unseen = alerts.Watch(), alerts.Unseen()
    idle = reading(("a", "idle", None))
    for snap, looking_at in ((reading(("a", "working", 100)), None), (idle, None), (idle, "a")):
        watch.step(snap, ON, {})
        unseen.step(watch.ended, watch.began, looking_at, watch.states)
    assert unseen.sids == set()


def test_a_new_turn_takes_the_mark_off_and_its_end_marks_again():
    out = marks(reading(("a", "working", 100)),
                reading(("a", "idle", None)),
                reading(("a", "working", 200)),
                reading(("a", "idle", None)))
    assert out == [set(), {"a"}, set(), {"a"}]


def test_blocking_exiting_or_closing_takes_the_mark_off():
    rows = (("a", "working", 100), ("b", "working", 100), ("c", "working", 100), ("d", "working", 100))
    ended = tuple((sid, "idle", None) for sid, _, _ in rows)
    out = marks(reading(*rows), reading(*ended),
                reading(("a", "blocked", None), ("b", "exited", None), ("d", "idle", None)))
    assert out[1:] == [{"a", "b", "c", "d"}, {"d"}]


def test_a_mark_outlasts_a_state_nobody_can_read():
    out = marks(reading(("a", "working", 100)),
                reading(("a", "idle", None)),
                reading(("a", "unknown", None)),
                reading(("a", "idle", None)))
    assert out == [set(), {"a"}, {"a"}, {"a"}]


def test_a_session_seen_from_the_panel_loses_its_mark_at_once():
    watch, unseen = alerts.Watch(), alerts.Unseen()
    for snap in (reading(("a", "working", 100), ("b", "working", 100)),
                 reading(("a", "idle", None), ("b", "idle", None))):
        watch.step(snap, ON, {})
        unseen.step(watch.ended, watch.began, None, watch.states)
    unseen.seen("a")
    unseen.seen("c")
    assert unseen.sids == {"b"}


def test_a_finish_is_marked_with_every_alert_turned_off():
    quiet = {**ON, "sound": False, "notify": False}
    out = marks(reading(("a", "working", 100)), reading(("a", "idle", None)), settings=quiet)
    assert out == [set(), {"a"}]


def test_both_panes_of_one_conversation_are_marked():
    out = marks(reading(("a", "working", 100), ("b", "working", 100)),
                reading(("a", "idle", None), ("b", "idle", None)),
                conversations={"a": "conv-1", "b": "conv-1"})
    assert out == [set(), {"a", "b"}]
