# ABOUTME: Exercises install and removal under a spare HOME with logged process commands.
# ABOUTME: Only this suite's scratch Keychain items may be created and deleted.
"""uninstall.sh reverses install.sh, under a spare HOME so nothing of the
real install is touched. Failure modes written first: the statusline key
must go back to what it was and only that key; another tool's Codex hook
entries must survive; the account store's Keychain items must go; the
checkout under ~/.local/share must not, since the script may run from it;
a second run must be quiet, not an error.
"""
import json
import os
import plistlib
import subprocess
import uuid
from pathlib import Path

import pytest

import accounts
from conftest import LOGIN_KEYCHAIN, iterm_prefs

REPO = Path(__file__).resolve().parent.parent
SERVICE = "agents-sidebar-accounts"


def run(script, home, *args, **extra_env):
    # These name omp's agent directory outside HOME; set in the shell running
    # the tests, the install would write into the real one.
    omp_dirs = {"OMP_PROFILE", "PI_PROFILE", "PI_CONFIG_DIR", "PI_CODING_AGENT_DIR"}
    commands = home.parent / "commands"
    commands.mkdir(exist_ok=True)
    for name in ("osascript", "pgrep", "ps", "kill", "swiftc"):
        command = commands / name
        command.write_text('''#!/bin/bash
printf '%s' "${0##*/}" >> "$TEST_COMMAND_LOG"
printf '\\t%s' "$@" >> "$TEST_COMMAND_LOG"
printf '\\n' >> "$TEST_COMMAND_LOG"
case "${0##*/}" in
  pgrep)
    if [ "$1" = -x ]; then [ "${TEST_ITERM:-0}" = 1 ];
    elif [ -n "${TEST_PIDS:-}" ]; then printf '%s\\n' "$TEST_PIDS";
    else exit 1; fi ;;
  ps)
    if [ "$2" = comm= ]; then printf '%s\\n' "${TEST_COMM:-python3}";
    else printf '%s\\n' "${TEST_ARGS:-python3 AutoLaunch/agents_sidebar.py}"; fi ;;
  osascript)
    if [ -n "${TEST_LAUNCH_ERROR:-}" ]; then printf '%s\\n' "$TEST_LAUNCH_ERROR" >&2; exit 1; fi ;;
  kill) exit 0 ;;
  swiftc) printf 'not compiled in script tests\\n' >&2; exit 1 ;;
esac
''')
        command.chmod(0o755)
    env = {**{k: v for k, v in os.environ.items() if k not in omp_dirs},
           "HOME": str(home), "PATH": f"{commands}:/usr/bin:/bin:/usr/sbin:/sbin",
           "TEST_COMMAND_LOG": str(home.parent / "commands.log"), **extra_env}
    return subprocess.run(["bash", "-c", 'enable -n kill; script=$1; shift; source "$script" "$@"',
                           "bash", str(REPO / script), *args],
                          env=env, capture_output=True, text=True, timeout=60)


def installed_home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # `security` reads the login keychain under HOME, so the spare home
    # shares the real one; the test's own item is the only one it touches.
    # Scratch items under SERVICE are authorized to use the login Keychain.
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
def account(throwaway_keychain):
    """An account name for the store, whose Keychain items, in the login
    keychain and the throwaway one, go with the test whatever its outcome."""
    account = f"test-uninstall-{uuid.uuid4().hex[:8]}"
    yield account
    accounts.delete_secret(SERVICE, account)
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", account, "-s", SERVICE,
                    throwaway_keychain], capture_output=True)


@pytest.mark.parametrize("keep_accounts", [False, True])
def test_uninstall_reverses_the_install_and_keeps_what_is_not_ours(tmp_path, account, unlocked_keychain,
                                                                    keep_accounts):
    """The logins go from the keychain the run names, here the throwaway one;
    an item of the same name in the login keychain is not the run's to take."""
    home = installed_home(tmp_path)
    for keychain in (unlocked_keychain, LOGIN_KEYCHAIN):
        subprocess.run(["/usr/bin/security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", "x",
                        keychain], check=True)
    config = home / ".config" / "agents-sidebar"
    (config / "locks").mkdir(parents=True)
    (config / "locks" / "store.lock").write_text("")
    (config / "state.json").write_text("{}")
    store = config / "accounts.json"
    stored = json.dumps({"accounts": [{"id": account}]})
    store.write_text(stored)
    checkout = home / ".local" / "share" / "agents-sidebar" / "src"
    checkout.mkdir(parents=True)
    (checkout / "marker").write_text("")
    endpoint = home / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    endpoint.write_text('{"port": 50123, "token": "t", "pid": 1}')

    extensions = home / ".omp" / "agent" / "extensions"
    assert sorted(p.name for p in extensions.iterdir()) == ["agents-sidebar.ts", "mine.ts"]
    assert str(home / ".claude" / "skills" / "agents-sidebar" / "hooks-handlers" / "emit-state.py") in (
        extensions / "agents-sidebar.ts").read_text()

    result = run("uninstall.sh", home, *(["--keep-accounts"] if keep_accounts else []))
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
    gone = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE,
                           unlocked_keychain], capture_output=True)
    assert item_in(LOGIN_KEYCHAIN, account), "an uninstall naming a keychain reached the login keychain"
    if keep_accounts:
        assert store.read_text() == stored
        assert sorted(p.name for p in config.iterdir()) == ["accounts.json"]
        assert gone.returncode == 0, "the scratch Keychain item was removed"
        assert "  ✓ accounts    logins kept in ~/.config/agents-sidebar/accounts.json and the Keychain\n" in result.stdout
    else:
        assert not config.exists()
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


def test_install_makes_the_links_folder_private_and_uninstall_removes_it(tmp_path):
    """Linked cards drop asks in each session's folder under it; only its owner may read them."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    assert run("install.sh", home, "--no-codex", "--no-statusline").returncode == 0
    folder = home / ".claude" / "agents-sidebar-links"
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    (folder / "s1").mkdir(mode=0o700)
    (folder / "s1" / "ready").write_text("s1")
    assert run("uninstall.sh", home).returncode == 0
    assert not folder.exists()


def saved_statusline(home, command, **settings):
    status = home / ".claude" / "agents-sidebar-status"
    status.mkdir(parents=True)
    (status / "original-statusline").write_text(command)
    path = home / ".claude" / "settings.json"
    path.write_text(json.dumps({**settings, "statusLine": {
        "type": "command", "command": str(REPO / "plugin" / "statusline-bridge.sh")}}))
    return path


@pytest.mark.parametrize("prefix", ["", "bash "])
def test_a_missing_saved_script_is_removed_instead_of_restored(tmp_path, prefix):
    home = tmp_path / "home"
    missing = home / "gone status.sh"
    settings = saved_statusline(home, f"{prefix}'{missing}' --quiet", theme="dark")
    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text()) == {"theme": "dark"}
    assert result.stderr == f"  ! statusline  statusLine removed; missing script: {missing}\n"


def test_an_existing_saved_script_is_restored_without_running_it(tmp_path):
    home = tmp_path / "home"
    command = 'bash "$HOME/status.sh"'
    settings = saved_statusline(home, command, theme="dark")
    script = home / "status.sh"
    script.write_text("exit 42\n")
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(settings.read_text()) == {
        "theme": "dark", "statusLine": {"type": "command", "command": command}}


def test_a_saved_script_name_can_be_resolved_on_path(tmp_path):
    home = tmp_path / "home"
    settings = saved_statusline(home, "bash status.sh")
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "status.sh").write_text("exit 42\n")
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(settings.read_text()) == {"statusLine": {"type": "command", "command": "bash status.sh"}}


@pytest.mark.parametrize("command", ["bash ./status.sh", "./scripts/status.sh"])
def test_a_relative_saved_script_keeps_its_original_working_directory_meaning(tmp_path, command):
    home = tmp_path / "home"
    settings = saved_statusline(home, command)
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(settings.read_text()) == {"statusLine": {"type": "command", "command": command}}


def test_a_quoted_script_path_can_contain_a_literal_dollar_sign(tmp_path):
    home = tmp_path / "home"
    script = home / "$STATUS_TOOL" / "status.sh"
    command = f"bash '{script}'"
    settings = saved_statusline(home, command)
    script.parent.mkdir()
    script.write_text("exit 42\n")
    result = run("uninstall.sh", home, STATUS_TOOL="different-directory")
    assert (result.returncode, result.stderr) == (0, "")
    assert json.loads(settings.read_text()) == {"statusLine": {"type": "command", "command": command}}


UNDERLINE = "MinimalSelectedTabUnderlineProminence"


def iterm_sets(*value):
    subprocess.run(["/usr/bin/defaults", "write", os.environ["AGENTS_SIDEBAR_ITERM_PREFS"], UNDERLINE, *value],
                   check=True)


def underline_record(home, record):
    status = home / ".claude" / "agents-sidebar-status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "tab-underline.json").write_text(json.dumps(record))


@pytest.mark.parametrize("kept, after", [
    (None, {}),
    ({"type": "float", "value": "0.4"}, {UNDERLINE: 0.4000000059604645}),
    ({"type": "string", "value": "0.5"}, {UNDERLINE: "0.5"}),
    ({"type": "boolean", "value": "1"}, {UNDERLINE: True}),
], ids=["unset", "float", "string", "boolean"])
def test_uninstall_puts_back_the_line_under_the_selected_tab_that_the_panel_held(tmp_path, kept, after):
    home = tmp_path / "home"
    underline_record(home, {"kept": kept})
    iterm_sets("-float", "0")
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr, iterm_prefs()) == (0, "", after)
    assert "  ✓ underline   iTerm2's line under the selected tab is back\n" in result.stdout


@pytest.mark.parametrize("change, after", [(["-float", "0.7"], {UNDERLINE: 0.699999988079071}), (None, {})],
                         ids=["set again", "deleted"])
def test_uninstall_leaves_a_line_under_the_selected_tab_the_user_changed_since(tmp_path, change, after):
    """A key the user deleted makes `defaults read` exit 1, which must not end the uninstall under set -e."""
    home = tmp_path / "home"
    underline_record(home, {"kept": None})
    if change:
        iterm_sets(*change)
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr, iterm_prefs()) == (0, "", after)
    assert "  - underline   changed since the panel hid it; left as it is\n" in result.stdout
    assert "  ✓ data        settings, state and the account store removed\n" in result.stdout


@pytest.mark.parametrize("record, said", [
    ({"aside": True}, "  - underline   yours while the tab tint was on; left as it is\n"),
    (None, "  - underline   not hidden by the panel\n"),
], ids=["the users", "no record"])
def test_uninstall_leaves_a_line_the_panel_never_held(tmp_path, record, said):
    home = tmp_path / "home"
    if record:
        underline_record(home, record)
    iterm_sets("-float", "0")
    result = run("uninstall.sh", home)
    assert (result.returncode, result.stderr, iterm_prefs()) == (0, "", {UNDERLINE: 0.0})
    assert said in result.stdout


@pytest.mark.parametrize("kept, verb, complaint, after", [
    (None, "delete", "Domain ({domain}) not found. Defaults have not been changed.", {}),
    ({"type": "float", "value": "0.4"}, "write", "Could not write domain {domain}; exiting",
     {UNDERLINE: 0.4000000059604645}),
], ids=["delete", "write"])
def test_an_underline_that_cannot_be_put_back_keeps_its_record_for_another_uninstall(tmp_path, kept, verb, complaint,
                                                                                      after):
    """The record holds what goes back, which the panel's other files never do: it stays where a second uninstall,
    or a reinstalled daemon, looks for it."""
    home = tmp_path / "home"
    underline_record(home, {"kept": kept})
    status = home / ".claude" / "agents-sidebar-status"
    (status / "daemon.log").write_text("a line\n")
    locked = tmp_path / "locked"
    locked.mkdir()
    domain = str(locked / "com.googlecode.iterm2")
    subprocess.run(["/usr/bin/defaults", "write", domain, UNDERLINE, "-float", "0"], check=True)
    locked.chmod(0o555)
    result = run("uninstall.sh", home, AGENTS_SIDEBAR_ITERM_PREFS=domain)
    assert (result.returncode, result.stderr) == (
        0, "  ! underline   still hidden, and ~/.claude/agents-sidebar-status/tab-underline.json kept, so running "
           f"uninstall again tries again; defaults {verb} said {complaint.format(domain=domain)}\n")
    assert [path.name for path in status.iterdir()] == ["tab-underline.json"]
    assert json.loads((status / "tab-underline.json").read_text()) == {"kept": kept}
    locked.chmod(0o755)
    result = run("uninstall.sh", home, AGENTS_SIDEBAR_ITERM_PREFS=domain)
    assert (result.returncode, result.stderr) == (0, "")
    assert "  ✓ underline   iTerm2's line under the selected tab is back\n" in result.stdout
    plist = Path(domain + ".plist")
    assert (plistlib.loads(plist.read_bytes()) if plist.exists() else {}) == after
    assert not status.exists()


@pytest.mark.parametrize("kept, why", [
    ({"type": "dictionary", "value": "{}"}, "kept {'type': 'dictionary', 'value': '{}'}"),
    ({"type": "float"}, "kept {'type': 'float'}"),
    ("0.4", "'str' object has no attribute 'get'"),
], ids=["a type defaults cannot write back", "no value", "not an object"])
def test_an_underline_record_the_panel_did_not_write_is_warned_about_and_left(tmp_path, kept, why):
    home = tmp_path / "home"
    underline_record(home, {"kept": kept})
    iterm_sets("-float", "0")
    result = run("uninstall.sh", home)
    record = home / ".claude" / "agents-sidebar-status" / "tab-underline.json"
    assert (result.returncode, result.stderr, iterm_prefs()) == (
        0, f"  ! underline   {record} unreadable: {why}; left as it is\n", {UNDERLINE: 0.0})


HELPER = str(REPO / "api-key-helper.sh")
#: This checkout's command for alice's key, as the daemon writes it.
HELPER_COMMAND = f"{HELPER} acct-1"
#: What another launcher keeps under the panel's service as the single item `api-key`.
LAUNCHERS = "sk-ant-test-launcher-not-a-real-key"


def item_in(keychain, account):
    return subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", SERVICE, keychain],
                          capture_output=True).returncode == 0


def store_item(keychain, account, value="sk-ant-test-not-a-real-key"):
    subprocess.run(["/usr/bin/security", "add-generic-password", "-U", "-a", account, "-s", SERVICE,
                    "-w", value, keychain], check=True)


def store_accounts(home, ids):
    """An account store naming `ids`, with no login items behind them: only their keys are the test's."""
    config = home / ".config" / "agents-sidebar"
    config.mkdir(parents=True, exist_ok=True)
    (config / "accounts.json").write_text(json.dumps({"version": 1, "accounts": [
        {"id": ident, "accountUuid": f"uuid-{ident}", "apiKeyLast4": "-key"} for ident in ids]}))


def test_uninstall_takes_the_panels_key_helper_out_and_leaves_the_rest(tmp_path, unlocked_keychain):
    home = installed_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    store_accounts(home, ["acct-1"])
    settings.write_text(json.dumps(dict(json.loads(settings.read_text()), apiKeyHelper=HELPER_COMMAND)))
    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    assert "apiKeyHelper" not in json.loads(settings.read_text())
    assert json.loads(settings.read_text())["theme"] == "dark"
    assert "  ✓ api key     apiKeyHelper taken out of ~/.claude/settings.json\n" in result.stdout


def test_uninstall_leaves_a_helper_that_only_shares_the_file_name(tmp_path, unlocked_keychain):
    home = installed_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps(dict(json.loads(settings.read_text()), apiKeyHelper="/opt/acme/api-key-helper.sh")))
    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text())["apiKeyHelper"] == "/opt/acme/api-key-helper.sh"
    assert "  - api key     apiKeyHelper is not the panel's; left alone\n" in result.stdout


def test_uninstall_takes_out_the_command_the_record_says_was_written(tmp_path, unlocked_keychain):
    """A checkout that moved left this command behind; the record says it is the panel's."""
    home = installed_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    moved = "/elsewhere/agents-sidebar/api-key-helper.sh"
    settings.write_text(json.dumps(dict(json.loads(settings.read_text()), apiKeyHelper=moved)))
    status = home / ".claude" / "agents-sidebar-status"
    status.mkdir(exist_ok=True)
    (status / "api-fallback.json").write_text(json.dumps({"command": moved}))
    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    assert "apiKeyHelper" not in json.loads(settings.read_text())


def test_uninstall_leaves_another_tools_key_helper_and_says_so(tmp_path, unlocked_keychain):
    home = installed_home(tmp_path)
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps(dict(json.loads(settings.read_text()), apiKeyHelper="/usr/local/bin/print-my-key")))
    result = run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text())["apiKeyHelper"] == "/usr/local/bin/print-my-key"
    assert "  - api key     apiKeyHelper is not the panel's; left alone\n" in result.stdout


@pytest.mark.parametrize("keep_accounts", [False, True])
def test_each_accounts_key_is_deleted_unless_logins_are_kept_and_the_launchers_item_never(
        tmp_path, unlocked_keychain, keep_accounts):
    """The keys go with the logins of the accounts the store names. The single item `api-key` belongs
    to another launcher: uninstall leaves it whatever it is told about logins."""
    home = installed_home(tmp_path)
    store_accounts(home, ["acct-1", "acct-2"])
    for account in ("api-key:acct-1", "api-key:acct-2", "api-key:acct-3"):
        store_item(unlocked_keychain, account)
    store_item(unlocked_keychain, "api-key", LAUNCHERS)
    try:
        result = run("uninstall.sh", home, *(["--keep-accounts"] if keep_accounts else []))
        assert result.returncode == 0, result.stderr
        assert [item_in(unlocked_keychain, f"api-key:acct-{n}") for n in (1, 2)] == [keep_accounts] * 2
        assert item_in(unlocked_keychain, "api-key:acct-3"), "an account the store does not name is not the panel's to take"
        assert item_in(unlocked_keychain, "api-key")
        if not keep_accounts:
            assert "  ✓ api key     2 API keys deleted\n" in result.stdout
    finally:
        for account in ("api-key:acct-1", "api-key:acct-2", "api-key:acct-3", "api-key"):
            subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", account, "-s", SERVICE,
                            unlocked_keychain], capture_output=True)


def test_a_keychain_named_that_does_not_exist_deletes_nothing(tmp_path, account):
    """`security` given a path that is not there looks in the login keychain, where the real logins and
    keys are."""
    home = installed_home(tmp_path)
    store_accounts(home, [account, "acct-1"])
    subprocess.run(["/usr/bin/security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", "x",
                    LOGIN_KEYCHAIN], check=True)
    missing = tmp_path / "no-such.keychain-db"
    result = run("uninstall.sh", home, AGENTS_SIDEBAR_KEYCHAIN=str(missing))
    assert result.returncode == 0, result.stderr
    assert item_in(LOGIN_KEYCHAIN, account), "the login went from the login keychain"
    assert f"  ! accounts    keychain not found at {missing}; logins and keys left alone\n" in result.stderr


def test_the_fallback_record_goes_with_the_status_folder(tmp_path, unlocked_keychain):
    home = installed_home(tmp_path)
    status = home / ".claude" / "agents-sidebar-status"
    status.mkdir(exist_ok=True)
    (status / "api-fallback.json").write_text("{}")
    (status / "api-fallback-orphaned").write_text("")
    assert run("uninstall.sh", home).returncode == 0
    assert not (status / "api-fallback.json").exists()
    assert not (status / "api-fallback-orphaned").exists()
