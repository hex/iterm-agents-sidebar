# ABOUTME: Settings shared by the whole suite: every Keychain call the tests reach
# ABOUTME: names the login keychain by path, so a spare HOME never raises a dialog.
import contextlib
import os
import plistlib
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accounts  # noqa: E402

#: From the account database, not HOME: a run under a spare HOME has no
#: keychain settings, and `security` then asks in a dialog where to store an
#: item rather than failing.
LOGIN_KEYCHAIN = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "Library", "Keychains", "login.keychain-db")


@pytest.fixture(autouse=True)
def links_folder_of_the_test(monkeypatch, tmp_path_factory):
    """A daemon built in a test keeps its links in the test's own folder: a new book clears the files of
    links it never knew, and this machine's own links must never be among them."""
    import links
    monkeypatch.setattr(links, "LINKS_DIR", tmp_path_factory.mktemp("links"))


@pytest.fixture(autouse=True)
def partners_record_of_the_test(monkeypatch, tmp_path_factory):
    """A daemon built in a test keeps its partnerships in the test's own folder, never this machine's."""
    import partners
    monkeypatch.setattr(partners, "PARTNERS_FILE", tmp_path_factory.mktemp("partners") / "partners.json")


@pytest.fixture(autouse=True)
def codex_config_of_the_test(monkeypatch, tmp_path_factory):
    """A daemon built in a test reads Codex's default model from the test's own folder, where no
    config is, never from this machine's ~/.codex."""
    import codex
    folder = tmp_path_factory.mktemp("codex")
    monkeypatch.setattr(codex, "CONFIG", str(folder / "config.toml"))
    monkeypatch.setattr(codex, "MODELS_CACHE", str(folder / "models_cache.json"))


SIDEBAR_PY = str(Path(__file__).resolve().parent.parent / "sidebar.py")


def sidebar_modules(test_module):
    """Every loaded copy of sidebar.py: the one `import sidebar` shares and the ones a test file
    makes for itself with importlib, which never reach sys.modules."""
    seen = []
    for module in list(sys.modules.values()) + list(vars(test_module).values()):
        if isinstance(module, type(sys)) and getattr(module, "__file__", None) == SIDEBAR_PY and module not in seen:
            seen.append(module)
    return seen


@pytest.fixture(autouse=True)
def daemon_dirs_of_the_test(request, monkeypatch, tmp_path_factory):
    """A daemon built in a test logs and reads hook state in the test's own folders: the real
    daemon.log is this machine's record, and a test session id must never appear in it. The API
    fallback's record and the helper's marker live in STATUS_DIR, so they follow it here: a test
    never reads or moves this machine's fallback."""
    status = tmp_path_factory.mktemp("status")
    hook_state = tmp_path_factory.mktemp("hook-state")
    for module in sidebar_modules(request.module):
        monkeypatch.setattr(module, "STATUS_DIR", str(status))
        monkeypatch.setattr(module, "HOOK_STATE_DIR", str(hook_state))


@pytest.fixture(autouse=True)
def iterm_prefs_of_the_test(monkeypatch, tmp_path_factory):
    """Every `defaults` call the tests reach, the daemon's and uninstall.sh's, names a plist in the test's own
    folder: `defaults` ignores HOME, so a spare one would still write this machine's iTerm2 settings."""
    import tabunderline
    domain = str(tmp_path_factory.mktemp("iterm-prefs") / "com.googlecode.iterm2")
    monkeypatch.setattr(tabunderline, "DOMAIN", domain)
    monkeypatch.setenv("AGENTS_SIDEBAR_ITERM_PREFS", domain)


def iterm_prefs():
    """The test's own iTerm2 settings as their plist holds them; `defaults` adds .plist to a path domain."""
    import tabunderline
    path = Path(tabunderline.DOMAIN + ".plist")
    return plistlib.loads(path.read_bytes()) if path.exists() else {}


@pytest.fixture
def utc(monkeypatch):
    """Start stamps read as UTC for the test, and the process clock goes back
    with the variable: tzset() reads TZ once, so restoring the variable alone
    would leave every later test in the wrong zone."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def search_list():
    listed = subprocess.run([accounts.SECURITY, "list-keychains", "-d", "user"], capture_output=True, text=True,
                            check=True).stdout
    return [line.strip().strip('"') for line in listed.splitlines() if line.strip()]


@contextlib.contextmanager
def scratch_keychain_at(path):
    """A keychain file at `path`, unlocked, out of the user's search list, deleted on the way out.

    It never locks: a keychain create-keychain makes locks after 300 s, and a locked one asks for
    its password in a dialog nobody running the tests can answer. It must exist before anything
    names it: `security` given a path that is not there looks in the login keychain instead.
    """
    searched = search_list()
    subprocess.run([accounts.SECURITY, "create-keychain", "-p", "scratch", path], check=True, capture_output=True)
    try:
        subprocess.run([accounts.SECURITY, "list-keychains", "-d", "user", "-s", *searched], check=True)
        subprocess.run([accounts.SECURITY, "set-keychain-settings", path], check=True)
        subprocess.run([accounts.SECURITY, "unlock-keychain", "-p", "scratch", path], check=True)
        info = subprocess.run([accounts.SECURITY, "show-keychain-info", path], capture_output=True, text=True)
        assert "no-timeout" in info.stdout + info.stderr, info.stdout + info.stderr
        assert os.path.exists(path), "a missing keychain path would fall through to the login keychain"
        yield path
    finally:
        subprocess.run([accounts.SECURITY, "delete-keychain", path], capture_output=True)
        assert search_list() == searched


def panel_items_in_the_login_keychain():
    """The account names of the login keychain's items under the panel's service, read from their
    attributes alone: `dump-keychain` without -d prints no secret and asks for nothing."""
    dump = subprocess.run([accounts.SECURITY, "dump-keychain", LOGIN_KEYCHAIN], capture_output=True, text=True,
                          check=True).stdout
    names = set()
    for item in dump.split("keychain: ")[1:]:
        if f'"svce"<blob>="{accounts.PANEL_SERVICE}"' in item:
            names.update(re.findall(r'"acct"<blob>="([^"]*)"', item))
    return names


@pytest.fixture(autouse=True, scope="session")
def the_machines_own_logins_survive_the_run():
    """Every item the panel keeps in the login keychain before the run is there after it. A script run
    under a spare HOME still reaches the login keychain, where a scratch store naming acct-1 names the
    machine's own login."""
    if sys.platform != "darwin":
        yield
        return
    before = {name for name in panel_items_in_the_login_keychain() if not name.startswith("test-")}
    yield
    gone = before - panel_items_in_the_login_keychain()
    assert not gone, f"the run deleted the machine's own Keychain items {sorted(gone)} under {accounts.PANEL_SERVICE}"


@pytest.fixture(autouse=True, scope="session")
def throwaway_keychain(tmp_path_factory):
    """A keychain file for anything that deletes or reads the API key, named through the variable
    uninstall.sh and api-key-helper.sh take: the spare HOME shares the real keychains, and a script
    that named none would reach the machine's real key."""
    if sys.platform != "darwin":
        yield None
        return
    with scratch_keychain_at(str(tmp_path_factory.mktemp("keychain") / "scratch.keychain-db")) as path:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("AGENTS_SIDEBAR_KEYCHAIN", path)
            yield path


@pytest.fixture
def unlocked_keychain(throwaway_keychain):
    """The session's throwaway keychain, unlocked again with its password just before a test writes
    to it: a run outlives any lock the system applies, and a locked keychain asks in a dialog."""
    subprocess.run([accounts.SECURITY, "unlock-keychain", "-p", "scratch", throwaway_keychain], check=True)
    return throwaway_keychain


@pytest.fixture(autouse=True, scope="session")
def api_key_item_of_the_tests():
    """The API key's Keychain calls name a service of the tests' own: the login keychain these tests
    reach holds the machine's real key under the panel's service. A test that runs the helper script,
    which names the real service, points it and the calls at a throwaway keychain first."""
    import api_fallback
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_fallback, "KEY_SERVICE", "agents-sidebar-test")
        yield


@pytest.fixture(autouse=True, scope="session")
def keychain_named_by_path():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accounts, "KEYCHAIN", LOGIN_KEYCHAIN)
        yield
