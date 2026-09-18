"""How the bridge takes its readings: off the event loop, and once per burst.

A process listing costs tens of milliseconds and every exec is inspected by
the endpoint agents, so a rebuild must not block the loop while it runs and a
burst of layout changes must not fan out into a listing each.
"""
import asyncio
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sidebar", Path(__file__).resolve().parent.parent / "sidebar.py")
sidebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidebar)


class NoWindows:
    terminal_windows = ()
    current_terminal_window = None

    async def async_refresh(self):
        pass


class Quiet:
    def broadcast(self, frame):
        pass


def bridge(monkeypatch, readings):
    def read_system():
        readings.append(1)
        return ({}, {}, {}, {}), {}, {}, {}
    monkeypatch.setattr(sidebar, "read_system", read_system)
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    b = sidebar.Bridge(None, Quiet())
    b.app = NoWindows()
    return b


def test_the_process_listing_is_read_off_the_event_loop(monkeypatch):
    seen = []

    def read_system():
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            seen.append("in a thread")
        return ({}, {}, {}, {}), {}, {}, {}
    monkeypatch.setattr(sidebar, "read_system", read_system)
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    b = sidebar.Bridge(None, Quiet())
    b.app = NoWindows()
    asyncio.run(b.rebuild())
    assert seen == ["in a thread"]


def test_rebuilds_asked_for_during_a_rebuild_fold_into_one_more(monkeypatch):
    """A tab opening fires several layout events in a row. The rebuild under
    way finishes, one more runs to catch what changed, and that is all."""
    readings = []
    b = bridge(monkeypatch, readings)

    async def burst():
        await asyncio.gather(*(b.rebuild() for _ in range(5)))
    asyncio.run(burst())
    assert len(readings) == 2


class Session:
    """A session whose variable reads each take a turn of the loop, so the
    test can see whether they were issued together or one after another."""
    in_flight = 0
    most_in_flight = 0
    session_id = "s1"

    async def async_get_variable(self, name):
        Session.in_flight += 1
        Session.most_in_flight = max(Session.most_in_flight, Session.in_flight)
        await asyncio.sleep(0)
        Session.in_flight -= 1
        if name == "path":
            return "/Users/x/atlas"
        return None


class Tab:
    tab_id = "t1"
    sessions = (Session(),)


class Window:
    window_id = "w1"
    tabs = (Tab(),)


class OneSession(NoWindows):
    terminal_windows = (Window(),)


def test_a_sessions_variables_are_read_together(monkeypatch):
    """Each read is a round trip to iTerm2; issued one at a time they cost
    a session's worth of latency times the variable count, every rebuild."""
    readings = []
    b = bridge(monkeypatch, readings)
    b.app = OneSession()
    rows = asyncio.run(b.read_sessions())
    assert rows[0]["path"] == "/Users/x/atlas"
    assert Session.most_in_flight == len(sidebar.SESSION_VARIABLES)
