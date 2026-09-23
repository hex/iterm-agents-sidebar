"""Putting the statusline bridge into Claude Code's settings, from install.sh or the panel.

Ways this can go wrong, and the test for each:
- the panel offers the bridge when it is already there, or stays quiet when
  something else (cs -statusline enable) has replaced it;
- a settings.json that is not JSON gets overwritten, losing everything in it;
- other settings, or the statusLine's own refreshInterval, are dropped;
- the user's own statusline is lost instead of kept to run inside the bridge;
- a second install saves the bridge itself as the "original", so the bridge
  then calls itself on every render;
- no settings.json at all (a fresh machine) stops the install.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import statusline  # noqa: E402

BRIDGE = "/opt/agents-sidebar/plugin/statusline-bridge.sh"


def settings_file(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


def test_the_bridge_reads_installed_only_when_it_is_the_command(tmp_path):
    ours = settings_file(tmp_path, {"statusLine": {"type": "command", "command": BRIDGE}})
    assert statusline.state(ours, BRIDGE) == "installed"
    theirs = settings_file(tmp_path, {"statusLine": {"type": "command", "command": "cs-statusline"}})
    assert statusline.state(theirs, BRIDGE) == "missing"
    bare = settings_file(tmp_path, {"model": "opus"})
    assert statusline.state(bare, BRIDGE) == "missing"
    assert statusline.state(tmp_path / "absent.json", BRIDGE) == "missing"


def test_settings_that_are_not_json_are_neither_offered_nor_touched(tmp_path):
    broken = settings_file(tmp_path, '{"model": "opus",')
    assert statusline.state(broken, BRIDGE) == "unreadable"
    with pytest.raises(ValueError, match="settings.json is not valid JSON"):
        statusline.install(broken, BRIDGE, tmp_path / "status")
    assert broken.read_text() == '{"model": "opus",'


def test_install_keeps_every_other_setting_and_the_refresh_rate(tmp_path):
    path = settings_file(tmp_path, {"model": "opus", "hooks": {"Stop": []},
                                    "statusLine": {"type": "command", "command": "cs-statusline",
                                                   "refreshInterval": 1}})
    statusline.install(path, BRIDGE, tmp_path / "status")
    assert json.loads(path.read_text()) == {
        "model": "opus", "hooks": {"Stop": []},
        "statusLine": {"type": "command", "command": BRIDGE, "refreshInterval": 1}}


def test_the_displaced_statusline_is_kept_to_run_inside_the_bridge(tmp_path):
    path = settings_file(tmp_path, {"statusLine": {"type": "command", "command": "cs-statusline"}})
    status = tmp_path / "status"
    assert statusline.install(path, BRIDGE, status) == "cs-statusline"
    assert (status / "original-statusline").read_text() == "cs-statusline"
    assert (tmp_path / "settings.json.before-agents-sidebar").read_text() == \
        json.dumps({"statusLine": {"type": "command", "command": "cs-statusline"}})


def test_an_installed_bridge_is_left_exactly_as_it_is(tmp_path):
    path = settings_file(tmp_path, {"statusLine": {"type": "command", "command": BRIDGE}})
    status = tmp_path / "status"
    status.mkdir()
    (status / "original-statusline").write_text("cs-statusline")
    before = path.read_text()
    assert statusline.install(path, BRIDGE, status) is None
    assert path.read_text() == before
    assert (status / "original-statusline").read_text() == "cs-statusline"
    assert not (tmp_path / "settings.json.before-agents-sidebar").exists()


def test_another_checkouts_bridge_is_never_kept_as_the_original(tmp_path):
    """It would run the bridge inside the bridge, forever."""
    elsewhere = "/Users/someone/.local/share/agents-sidebar/src/plugin/statusline-bridge.sh"
    path = settings_file(tmp_path, {"statusLine": {"type": "command", "command": elsewhere}})
    status = tmp_path / "status"
    status.mkdir()
    (status / "original-statusline").write_text("cs-statusline")
    assert statusline.install(path, BRIDGE, status) == ""
    assert (status / "original-statusline").read_text() == "cs-statusline"
    assert json.loads(path.read_text())["statusLine"]["command"] == BRIDGE


def test_a_machine_with_no_settings_file_gets_one(tmp_path):
    path = tmp_path / "claude" / "settings.json"
    assert statusline.install(path, BRIDGE, tmp_path / "status") == ""
    assert json.loads(path.read_text()) == {"statusLine": {"type": "command", "command": BRIDGE}}
    assert (tmp_path / "status" / "original-statusline").read_text() == ""
