"""The daemon says where it listens, in a file only its own user can read.

Ways it could go wrong: a file other users can read hands them the token; a
reader catching the file half written gets no JSON; a restart that cannot
replace the old file leaves a script knocking on a dead port.
"""
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import write_endpoint


def test_the_endpoint_file_names_port_token_and_pid_for_the_owner_alone(tmp_path):
    path = tmp_path / "share" / "agents-sidebar" / "endpoint.json"

    write_endpoint(path, 50123, "a-token", 4242)

    assert json.loads(path.read_text()) == {"port": 50123, "token": "a-token", "pid": 4242}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_a_write_that_fails_part_way_leaves_the_last_endpoint_whole(tmp_path):
    """The file is replaced, never written over in place, so a reader never
    finds half of one. A token JSON cannot hold fails after the port is out."""
    path = tmp_path / "endpoint.json"
    write_endpoint(path, 50123, "a-token", 4242)

    with pytest.raises(TypeError):
        write_endpoint(path, 50124, object(), 4343)

    assert json.loads(path.read_text()) == {"port": 50123, "token": "a-token", "pid": 4242}


class NoWindows:
    terminal_windows = ()
    current_terminal_window = None
    app_active = False

    async def async_refresh(self):
        pass


@pytest.fixture
def daemon(monkeypatch, tmp_path):
    """A Server and a Bridge over no iTerm2, reading only this test's files.
    -> (server, bridge)."""
    import sidebar
    monkeypatch.setattr(sidebar, "SETTINGS_FILE", tmp_path / "agents-sidebar-settings.json")
    monkeypatch.setattr(sidebar, "CLAUDE_SETTINGS", str(tmp_path / "claude-settings.json"))
    monkeypatch.setattr(sidebar, "CODEX_JOBS_DIR", str(tmp_path / "codex-jobs"))
    monkeypatch.setattr(sidebar, "STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setattr(sidebar.codex, "read_limits", lambda *_: {})
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    server = sidebar.Server(sidebar.Sidebar(token="a-token", page_path=page, snapshot_fn=lambda: {},
                                            action_fn=lambda *a: None))
    bridge = sidebar.Bridge(None, server)
    bridge.app = NoWindows()
    return server, bridge


def read_of_nothing(sidebar):
    """The snapshot a whole rebuild makes over no windows, on a machine whose
    Claude settings lack the statusline bridge."""
    return {"groups": [], "version": sidebar.version(), "terminal_font": None, "statusline": "missing", "codex": {}}


async def test_the_daemon_says_where_it_listens_once_it_has_read_iterm2(monkeypatch, tmp_path, daemon):
    """Before the first reading the daemon's list is empty, which a script
    would take for "no sessions", so the file comes after it."""
    import sidebar
    server, bridge = daemon
    path = tmp_path / "endpoint.json"
    there_at_first_reading = []

    def read_system():
        there_at_first_reading.append(path.exists())
        return ({}, {}, {}, {}), {}, {}, {}, {}, {}
    monkeypatch.setattr(sidebar, "read_system", read_system)

    port = await sidebar.start_serving(server, bridge, "a-token", path)

    assert there_at_first_reading == [False]
    assert bridge.healthy() is True
    assert bridge.latest == read_of_nothing(sidebar)
    assert json.loads(path.read_text()) == {"port": port, "token": "a-token", "pid": os.getpid()}


async def test_a_first_reading_that_fails_says_nothing_until_one_succeeds(monkeypatch, tmp_path, daemon, capsys):
    """The list a failed reading leaves is the empty one the daemon starts
    with, so the file waits for a reading that worked."""
    import sidebar
    server, bridge = daemon
    path = tmp_path / "endpoint.json"
    listings = iter([OSError("ps could not run"), (({}, {}, {}, {}), {}, {}, {}, {}, {})])

    def read_system():
        outcome = next(listings)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(sidebar, "read_system", read_system)

    port = await sidebar.start_serving(server, bridge, "a-token", path)
    assert path.exists() is False
    assert capsys.readouterr().out == "sidebar: rebuild failed: OSError('ps could not run')\n"

    await bridge.rebuild_or_report()
    await asyncio.sleep(0)

    assert bridge.latest == read_of_nothing(sidebar)
    assert json.loads(path.read_text()) == {"port": port, "token": "a-token", "pid": os.getpid()}
