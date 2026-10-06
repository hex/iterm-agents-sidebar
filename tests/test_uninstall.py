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

import pytest

import accounts
from conftest import LOGIN_KEYCHAIN

REPO = Path(__file__).resolve().parent.parent
SERVICE = "agents-sidebar-accounts"


def run(script, home, *args):
    # These name omp's agent directory outside HOME; set in the shell running
    # the tests, the install would write into the real one.
    omp_dirs = {"OMP_PROFILE", "PI_PROFILE", "PI_CONFIG_DIR", "PI_CODING_AGENT_DIR"}
    env = {**{k: v for k, v in os.environ.items() if k not in omp_dirs},
           "HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
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
        {"command": "bash '/Users/jane/.codex/other-tool-state.sh' session", "timeout": 10, "type": "command"}]}]}}))
    (home / ".omp" / "agent" / "extensions").mkdir(parents=True)
    (home / ".omp" / "agent" / "extensions" / "mine.ts").write_text("// another extension\n")
    assert run("install.sh", home).returncode == 0
    return home


@pytest.fixture
def account():
    """An account name for the store, whose Keychain item, should the
    uninstall under test leave it, goes with the test whatever its outcome."""
    account = f"test-uninstall-{uuid.uuid4().hex[:8]}"
    yield account
    accounts.delete_secret(SERVICE, account)


def test_uninstall_reverses_the_install_and_keeps_what_is_not_ours(tmp_path, account):
    home = installed_home(tmp_path)
    subprocess.run(["/usr/bin/security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", "x",
                    LOGIN_KEYCHAIN], check=True)
    (home / ".config" / "agents-sidebar").mkdir(parents=True)
    (home / ".config" / "agents-sidebar" / "accounts.json").write_text(json.dumps({"accounts": [{"id": account}]}))
    checkout = home / ".local" / "share" / "agents-sidebar" / "src"
    checkout.mkdir(parents=True)
    (checkout / "marker").write_text("")
    endpoint = home / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    endpoint.write_text('{"port": 50123, "token": "t", "pid": 1}')

    extensions = home / ".omp" / "agent" / "extensions"
    assert sorted(p.name for p in extensions.iterdir()) == ["agents-sidebar.ts", "mine.ts"]
    assert str(home / ".claude" / "skills" / "agents-sidebar" / "hooks-handlers" / "emit-state.py") in (
        extensions / "agents-sidebar.ts").read_text()

    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr

    assert not os.path.lexists(home / ".local" / "bin" / "agents-sidebar")
    assert not endpoint.exists()
    assert sorted(p.name for p in extensions.iterdir()) == ["mine.ts"]

    assert not (home / "Library/Application Support/iTerm2/Scripts/AutoLaunch/agents_sidebar.py").exists()
    assert not (home / ".claude" / "skills" / "agents-sidebar").exists()
    assert not (home / ".local" / "share" / "agents-sidebar" / "Agents.app").exists()
    assert (checkout / "marker").exists()
    assert json.loads((home / ".claude" / "settings.json").read_text()) == {
        "statusLine": {"type": "command", "command": "my-own-statusline"}, "theme": "dark"}
    hooks = json.loads((home / ".codex" / "hooks.json").read_text())
    assert hooks == {"hooks": {"SessionStart": [{"hooks": [
        {"command": "bash '/Users/jane/.codex/other-tool-state.sh' session", "timeout": 10, "type": "command"}]}]}}
    assert not (home / ".config" / "agents-sidebar").exists()
    gone = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE,
                           LOGIN_KEYCHAIN], capture_output=True)
    assert gone.returncode != 0, "the Keychain item is still there"
    assert "1 Keychain items" in result.stdout


def test_install_puts_the_command_in_local_bin_and_says_when_that_is_off_path(tmp_path):
    """The run here has a PATH without ~/.local/bin, as a fresh Mac does."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)

    result = run("install.sh", home, "--no-codex", "--no-statusline")

    assert result.returncode == 0, result.stderr
    link = home / ".local" / "bin" / "agents-sidebar"
    assert os.readlink(link) == str(REPO / "agents-sidebar")
    assert "  ✓ command     ~/.local/bin/agents-sidebar\n" in result.stdout
    assert "    ~/.local/bin is not on your PATH; add it to run agents-sidebar by name\n" in result.stdout


def test_a_command_of_that_name_that_is_not_ours_survives_both_scripts(tmp_path):
    """A file of another tool is never replaced; a link to another checkout
    is left by the uninstall of this one."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    command = home / ".local" / "bin" / "agents-sidebar"
    command.write_text("#!/bin/sh\necho another tool\n")

    installed = run("install.sh", home, "--no-codex", "--no-statusline")
    assert installed.returncode == 0
    assert command.read_text() == "#!/bin/sh\necho another tool\n"
    # Among the others a spare HOME draws, such as no iTerm2 Python in it.
    assert "  ! command     ~/.local/bin/agents-sidebar is not ours; left alone" in installed.stderr.splitlines()

    command.unlink()
    command.symlink_to(tmp_path / "another-checkout" / "agents-sidebar")
    assert run("uninstall.sh", home).returncode == 0
    assert os.readlink(command) == str(tmp_path / "another-checkout" / "agents-sidebar")


def test_a_home_that_never_had_a_statusline_gets_the_key_removed(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"theme": "dark"}))
    assert run("install.sh", home, "--no-codex").returncode == 0
    assert run("uninstall.sh", home).returncode == 0
    assert json.loads((home / ".claude" / "settings.json").read_text()) == {"theme": "dark"}


def test_an_install_that_insists_on_omp_where_there_is_none_writes_nothing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--omp")
    assert (result.returncode, result.stderr.strip()) == (
        1, "error: --omp, but omp is not on PATH and ~/.omp/agent does not exist; nothing installed.")
    assert list(home.iterdir()) == []


def test_an_install_that_insists_on_omp_fails_when_the_extension_cannot_be_written(tmp_path):
    home = tmp_path / "home"
    extensions = home / ".omp" / "agent" / "extensions"
    extensions.mkdir(parents=True)
    (extensions / "agents-sidebar.ts").write_text("// somebody else's extension\n")
    result = run("install.sh", home, "--no-codex", "--no-statusline", "--omp")
    assert result.returncode == 1
    assert result.stderr.strip().splitlines()[-1] == (
        f"error: --omp, but {extensions / 'agents-sidebar.ts'} was not written by the Agents panel; left unchanged.")
    assert (extensions / "agents-sidebar.ts").read_text() == "// somebody else's extension\n"


def test_an_install_that_finds_omp_warns_and_goes_on_when_the_extension_cannot_be_written(tmp_path):
    home = tmp_path / "home"
    extensions = home / ".omp" / "agent" / "extensions"
    extensions.mkdir(parents=True)
    (extensions / "agents-sidebar.ts").write_text("// somebody else's extension\n")
    result = run("install.sh", home, "--no-codex", "--no-statusline")
    assert result.returncode == 0
    assert f"{extensions / 'agents-sidebar.ts'} was not written by the Agents panel; left unchanged." in result.stderr
    assert (extensions / "agents-sidebar.ts").read_text() == "// somebody else's extension\n"


def test_no_omp_leaves_omps_directory_alone(tmp_path):
    home = tmp_path / "home"
    (home / ".omp" / "agent").mkdir(parents=True)
    assert run("install.sh", home, "--no-codex", "--no-omp", "--no-statusline").returncode == 0
    assert list((home / ".omp" / "agent").iterdir()) == []
    assert not (home / ".claude" / "skills" / "agents-sidebar" / "omp").exists()


def test_a_second_uninstall_is_quiet(tmp_path):
    home = installed_home(tmp_path)
    run("uninstall.sh", home)
    again = run("uninstall.sh", home)
    assert again.returncode == 0 and again.stderr == ""
    assert "not installed" in again.stdout
