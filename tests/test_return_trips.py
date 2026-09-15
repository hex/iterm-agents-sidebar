"""Tests for going back to where you were once a blocked session you were
brought to has been answered."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import ReturnTrips


def test_answering_the_session_you_were_brought_to_goes_back():
    trips = ReturnTrips()
    trips.leave("blocked", active="editor")
    assert trips.back("blocked", active="blocked") == "editor"


def test_a_trip_is_used_once():
    trips = ReturnTrips()
    trips.leave("blocked", active="editor")
    trips.back("blocked", active="blocked")
    assert trips.back("blocked", active="blocked") is None


def test_having_moved_elsewhere_in_the_meantime_stays_put():
    """You went somewhere on purpose. Yanking you back is the bug this
    prevents."""
    trips = ReturnTrips()
    trips.leave("blocked", active="editor")
    assert trips.back("blocked", active="other") is None
    # And the stale trip does not fire later either.
    assert trips.back("blocked", active="blocked") is None


def test_a_session_nobody_was_brought_to_has_nowhere_to_go_back_to():
    assert ReturnTrips().back("blocked", active="blocked") is None


def test_already_being_there_leaves_no_trip():
    trips = ReturnTrips()
    trips.leave("blocked", active="blocked")
    assert trips.back("blocked", active="blocked") is None


def test_no_known_active_session_leaves_no_trip():
    trips = ReturnTrips()
    trips.leave("blocked", active=None)
    assert trips.back("blocked", active="blocked") is None


def test_chained_blocks_unwind_in_order():
    """Brought from the editor to A, then from A to B: answering B lands on A,
    answering A lands back on the editor."""
    trips = ReturnTrips()
    trips.leave("a", active="editor")
    trips.leave("b", active="a")
    assert trips.back("b", active="b") == "a"
    assert trips.back("a", active="a") == "editor"
