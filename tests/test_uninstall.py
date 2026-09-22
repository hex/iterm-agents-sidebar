"""uninstall.sh reverses install.sh, under a spare HOME so nothing of the
real install is touched. Failure modes written first: the statusline key
must go back to what it was and only that key; another tool's Codex hook
entries must survive; the account store's Keychain items must go; the
checkout under ~/.local/share must not, since the script may run from it;
a second run must be quiet, not an error.
"""
import json
import os
import subprocess
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVICE = "agents-sidebar-accounts"


def run(script, home, *args):
    env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    return subprocess.run(["bash", str(REPO / script), *args], env=env, capture_output=True, text=True)


def installed_home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # `security` reads the login keychain under HOME, so the spare home
    # shares the real one; the test's own item is the only one it touches.
    (home / "Library").mkdir()
    (home / "Library" / "Keychains").symlink_to(Path.home() / "Library" / "Keychains")
    (home / ".claude" / "settings.json").write_text(json.dumps(
        {"statusLine": {"type": "command", "command": "my-own-statusline"}, "theme": "dark"}))
    (home / ".codex").mkdir()
    (home / ".codex" / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"command": "bash '/Users/jane/.codex/herdr-agent-state.sh' session", "timeout": 10, "type": "command"}]}]}}))
    assert run("install.sh", home).returncode == 0
    return home


def test_uninstall_reverses_the_install_and_keeps_what_is_not_ours(tmp_path):
    home = installed_home(tmp_path)
    account = f"test-uninstall-{uuid.uuid4().hex[:8]}"
    subprocess.run(["/usr/bin/security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", "x"], check=True)
    (home / ".config" / "agents-sidebar").mkdir(parents=True)
    (home / ".config" / "agents-sidebar" / "accounts.json").write_text(json.dumps({"accounts": [{"id": account}]}))
    checkout = home / ".local" / "share" / "agents-sidebar" / "src"
    checkout.mkdir(parents=True)
    (checkout / "marker").write_text("")

    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr

    assert not (home / "Library/Application Support/iTerm2/Scripts/AutoLaunch/agents_sidebar.py").exists()
    assert not (home / ".claude" / "skills" / "agents-sidebar").exists()
    assert not (home / ".local" / "share" / "agents-sidebar" / "Agents.app").exists()
    assert (checkout / "marker").exists()
    assert json.loads((home / ".claude" / "settings.json").read_text()) == {
        "statusLine": {"type": "command", "command": "my-own-statusline"}, "theme": "dark"}
    hooks = json.loads((home / ".codex" / "hooks.json").read_text())
    assert hooks == {"hooks": {"SessionStart": [{"hooks": [
        {"command": "bash '/Users/jane/.codex/herdr-agent-state.sh' session", "timeout": 10, "type": "command"}]}]}}
    assert not (home / ".config" / "agents-sidebar").exists()
    gone = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE], capture_output=True)
    assert gone.returncode != 0, "the Keychain item is still there"
    assert "1 Keychain items" in result.stdout


def test_a_home_that_never_had_a_statusline_gets_the_key_removed(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"theme": "dark"}))
    assert run("install.sh", home, "--no-codex").returncode == 0
    assert run("uninstall.sh", home).returncode == 0
    assert json.loads((home / ".claude" / "settings.json").read_text()) == {"theme": "dark"}


def test_a_second_uninstall_is_quiet(tmp_path):
    home = installed_home(tmp_path)
    run("uninstall.sh", home)
    again = run("uninstall.sh", home)
    assert again.returncode == 0 and again.stderr == ""
    assert "not installed" in again.stdout
