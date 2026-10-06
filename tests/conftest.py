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


@pytest.fixture(autouse=True, scope="session")
def keychain_named_by_path():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(accounts, "KEYCHAIN", LOGIN_KEYCHAIN)
        yield
