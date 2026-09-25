"""How the bridge takes its readings: off the event loop, and once per burst.

A process listing costs tens of milliseconds and every exec is inspected by
the endpoint agents, so a rebuild must not block the loop while it runs and a
burst of layout changes must not fan out into a listing each.
"""
import asyncio
import importlib.util
import json
import os
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


class CodexSession(Session):
    session_id = "s2"

    async def async_get_variable(self, name):
        if name == "user.codexState":
            return json.dumps({"state": "idle", "pid": os.getpid(), "ts": 1789480900,
                               "session": "codex-1", "model": "gpt-6-astra",
                               "transcript_path": "/Users/x/.codex/sessions/rollout-x.jsonl"})
        return None


class CodexTab(Tab):
    sessions = (CodexSession(),)


class CodexWindow(Window):
    tabs = (CodexTab(),)


class OneCodexSession(NoWindows):
    terminal_windows = (CodexWindow(),)


def test_a_codex_rollout_is_read_off_the_event_loop(monkeypatch):
    """The rollout is a file on disk like the rest, and its path comes from
    the pane, so a slow one must not hold every other row."""
    seen = []

    def read_session(path):
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            seen.append("in a thread")
        return {"effort": None, "context": None}
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar.codex, "read_session", read_session)
    b.app = OneCodexSession()
    asyncio.run(b.read_sessions())
    assert seen == ["in a thread"]


def test_a_rebuild_that_fails_is_reported_and_the_daemon_carries_on(monkeypatch, capsys):
    """The first rebuild runs before the panel registers, so one reading that
    raises must cost that frame and nothing else."""
    def read_system():
        raise RuntimeError("ps went away")
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system", read_system)
    asyncio.run(b.rebuild_or_report())
    assert capsys.readouterr().out == "sidebar: rebuild failed: RuntimeError('ps went away')\n"


class OmpSession(Session):
    session_id = "s3"

    async def async_get_variable(self, name):
        return {"autoName": "π ! Fix login", "jobName": "bun", "path": "/Users/x/atlas"}.get(name)


class OmpTab(Tab):
    sessions = (OmpSession(),)


class OmpWindow(Window):
    tabs = (OmpTab(),)


class OneOmpSession(NoWindows):
    terminal_windows = (OmpWindow(),)


def test_a_pane_titled_by_omp_is_an_omp_row_in_the_state_its_title_gives(monkeypatch):
    """omp reports through no hook, so its title is all the daemon has."""
    b = bridge(monkeypatch, [])
    b.app = OneOmpSession()
    [row] = asyncio.run(b.read_sessions())
    assert (row["provider"], row["agent_state"], row["topic"]) == ("omp", "blocked", "Fix login")


class OmpSessionWithAJob(OmpSession):
    async def async_get_variable(self, name):
        if name == "jobPid":
            return 4242
        return await super().async_get_variable(name)


def one_session(session):
    tab = type("OneTab", (Tab,), {"sessions": (session,)})
    window = type("OneWindow", (Window,), {"tabs": (tab(),)})
    return type("OnePane", (NoWindows,), {"terminal_windows": (window(),)})()


def test_an_omp_row_is_the_process_iterm2_names_as_the_panes_job(monkeypatch):
    """omp publishes no pid, and ps calls it bun; iTerm2 knows the pane's
    foreground job, which is where the row's start time comes from."""
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system",
                        lambda: (({}, {4242: 1789980000}, {}, {}), {}, {}, {}))
    b.app = one_session(OmpSessionWithAJob())
    [row] = asyncio.run(b.read_sessions())
    assert row["started_at"] == 1789980000


def test_a_job_pid_that_is_no_pid_leaves_the_omp_row_without_a_process(monkeypatch):
    class Odd(OmpSession):
        async def async_get_variable(self, name):
            return True if name == "jobPid" else await super().async_get_variable(name)
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system",
                        lambda: (({}, {1: 1789980000}, {}, {}), {}, {}, {}))
    b.app = one_session(Odd())
    [row] = asyncio.run(b.read_sessions())
    assert row["started_at"] is None


def test_a_light_session_never_asks_what_its_busiest_process_is_called(monkeypatch):
    """A plain login shell is `-zsh` in ps, so its args name no program;
    asking the kernel every rebuild for a row nobody is shown would cost a ps."""
    b = bridge(monkeypatch, [])
    resources = {4242: (1, 0.5, 9000, "ttys001")}
    monkeypatch.setattr(sidebar, "read_system",
                        lambda: (({}, {4242: 1789980000}, {}, {}), {}, resources, {4242: None}))
    asked = []
    monkeypatch.setattr(sidebar, "read_program_names", lambda pids: asked.append(pids) or {})
    b.app = one_session(OmpSessionWithAJob())
    [row] = asyncio.run(b.read_sessions())
    assert row["heavy"] == [] and row["usage"] == {}
    assert asked == []


class OmpSessionOnATerminal(OmpSession):
    async def async_get_variable(self, name):
        return "/dev/ttys008" if name == "tty" else await super().async_get_variable(name)


def test_an_omp_row_takes_its_model_and_effort_from_omps_session_off_the_loop(monkeypatch):
    seen = []

    def read_session(terminals_dir, tty):
        try:
            asyncio.get_running_loop()
            seen.append("on the loop")
        except RuntimeError:
            seen.append((terminals_dir, tty))
        return {"model": "gpt-5.6-luna", "effort": "high", "context": 16, "cost": 1.75,
                "doing": "Validate shell scripts", "jobs": ["cd /Users/x/atlas && ssh crawler ./force.sh"],
                "agents": [{"id": "DocsReview", "type": "scout", "since": 1789993123.47, "ended": None,
                            "model": "gpt-6-astra", "effort": "high", "context": 14, "cost": 0.02,
                            "doing": "Reading README"}]}
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar.omp, "read_session", read_session)
    b.app = one_session(OmpSessionOnATerminal())
    [row] = asyncio.run(b.read_sessions())
    assert seen == [(sidebar.omp.TERMINALS_DIR, "/dev/ttys008")]
    assert (row["model"], row["effort"], row["context"]) == ("gpt-5.6-luna", "high", 16)
    assert row["details"] == {"cost": 1.75}
    assert row["doing"] == "Validate shell scripts"
    # As a Claude Code shell reads: the command past its setup, whole on hover.
    assert row["shells"] == [{"label": "ssh crawler ./force.sh",
                              "command": "cd /Users/x/atlas && ssh crawler ./force.sh"}]
    # Named as omp names it, its kind where a Claude subagent has its type.
    assert row["subagents"] == [{"id": "DocsReview", "name": "DocsReview", "type": "scout", "since": 1789993123.47,
                                 "ended": None, "model": "gpt-6-astra", "effort": "high", "context": 14,
                                 "cost": 0.02, "doing": "Reading README", "provider": "omp", "depth": 0}]
    assert row["agents"] == 1


def test_an_omp_row_that_has_cost_nothing_yet_reports_no_cost(monkeypatch):
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar.omp, "read_session", lambda *_: {
        "model": None, "effort": None, "context": None, "cost": None, "doing": None, "jobs": [], "agents": []})
    b.app = one_session(OmpSessionOnATerminal())
    [row] = asyncio.run(b.read_sessions())
    assert row["details"] == {}


def test_an_omp_pane_inside_tmux_is_on_the_terminal_tmux_gave_it(monkeypatch):
    class InTmux(OmpSession):
        async def async_get_variable(self, name):
            return 72 if name == "tmuxWindowPane" else await super().async_get_variable(name)
    seen = []
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system", lambda: (
        ({}, {}, {}, {}), {72: {"tty": "ttys011", "path": "/Users/x/atlas"}}, {}, {}))
    monkeypatch.setattr(sidebar.omp, "read_session",
                        lambda _, tty: seen.append(tty) or {"model": None, "effort": None,
                                                            "context": None, "cost": None, "doing": None, "jobs": [], "agents": []})
    b.app = one_session(InTmux())
    asyncio.run(b.read_sessions())
    assert seen == ["ttys011"]


def test_an_omp_pane_iterm2_names_no_terminal_for_is_on_its_processs_terminal(monkeypatch):
    """The process listing knows the terminal of every pid, and the omp row
    has one, so nothing hangs on a variable iTerm2 may leave empty."""
    seen = []
    b = bridge(monkeypatch, [])
    monkeypatch.setattr(sidebar, "read_system", lambda: (
        ({}, {}, {}, {}), {}, {4242: (1, 0.0, 0, "ttys014")}, {}))
    monkeypatch.setattr(sidebar.omp, "read_session",
                        lambda _, tty: seen.append(tty) or {"model": None, "effort": None,
                                                            "context": None, "cost": None, "doing": None, "jobs": [], "agents": []})
    b.app = one_session(OmpSessionWithAJob())
    asyncio.run(b.read_sessions())
    assert seen == ["ttys014"]


def test_a_newer_mirror_release_rides_every_snapshot_and_an_absent_one_leaves_no_key(monkeypatch):
    """`latest` is rebuilt from scratch each cycle, so the offer has to be
    copied in every time; and a panel that is current sees no key at all,
    rather than a null to interpret."""
    monkeypatch.setattr(sidebar, "read_system", lambda: (({}, {}, {}, {}), {}, {}, {}))
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    b = sidebar.Bridge(None, Quiet())
    b.app = NoWindows()
    asyncio.run(b.rebuild())
    assert "update" not in b.latest
    b.update = "2026.09.20"
    asyncio.run(b.rebuild())
    assert b.latest["update"] == "2026.09.20"


def test_the_refresh_button_asks_the_mirror_for_a_release_too(monkeypatch):
    """Asked 2026-09-22: a daily check is too slow when a friend has just
    been told a release is out. The reload button's account read now also
    checks the mirror, and the reloaded page sees the offer at once."""
    class Meters:
        def read_now(self, now):
            return {"accounts": []}
    b = sidebar.Bridge(None, Quiet(), Meters())
    b.latest = {"groups": []}
    monkeypatch.setattr(sidebar.update, "check", lambda: "2027.01.1")
    monkeypatch.setattr(sidebar, "version", lambda: "2026.09.28")
    b.account_op("read", {})
    assert b.update == "2027.01.1"
    assert b.latest["update"] == "2027.01.1"
    monkeypatch.setattr(sidebar.update, "check", lambda: None)
    b.account_op("read", {})
    assert b.update is None and "update" not in b.latest


def test_each_rebuild_decides_the_alerts_and_carries_them_out(monkeypatch, tmp_path):
    """The daemon, not a page, turns a change it read into a sound and a banner,
    under the settings on disk at that moment."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"notify_done": False, "sound_blocked": False}))
    monkeypatch.setattr(sidebar, "SETTINGS_FILE", settings)
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path))
    readings = iter([{"groups": [{"rows": [{"session_id": "a", "state": "working", "working_since": 100},
                                           {"session_id": "b", "state": "working", "working_since": 100}]}]},
                     {"groups": [{"rows": [{"session_id": "a", "state": "blocked"},
                                           {"session_id": "b", "state": "idle"}]}]}])
    monkeypatch.setattr(sidebar, "snapshot", lambda *_: next(readings))
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    b = sidebar.Bridge(None, Quiet())
    b.app = NoWindows()
    done = []

    class Player:
        async def play(self, session_id, kind, settings):
            done.append(("sound", session_id, kind))

    async def notify(session_id, kind):
        done.append(("notify", session_id, kind))
    b.player = Player()
    b.notify = notify

    async def two_rebuilds():
        await b._rebuild_once()
        await b._rebuild_once()
        await asyncio.sleep(0)
    asyncio.run(two_rebuilds())
    assert sorted(done) == [("notify", "a", "blocked"), ("sound", "b", "done")]
    logged = [line.split(" ", 2)[2] for line in (tmp_path / "daemon.log").read_text().splitlines()]
    assert logged == ["alert notify a blocked", "alert sound b done"]
