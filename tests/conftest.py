# ABOUTME: Settings shared by the whole suite: every Keychain call the tests reach
# ABOUTME: names the login keychain by path, so a spare HOME never raises a dialog.
import os
import pwd
import sys
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
    daemon.log is this machine's record, and a test session id must never appear in it."""
    status = tmp_path_factory.mktemp("status")
    hook_state = tmp_path_factory.mktemp("hook-state")
    for module in sidebar_modules(request.module):
        monkeypatch.setattr(module, "STATUS_DIR", str(status))
        monkeypatch.setattr(module, "HOOK_STATE_DIR", str(hook_state))


@pytest.fixture(autouse=True, scope="session")
def keychain_named_by_path():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accounts, "KEYCHAIN", LOGIN_KEYCHAIN)
        yield
