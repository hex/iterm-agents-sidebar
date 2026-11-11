"""Each account's API key: kept in a Keychain, printed by the helper script, checked once against the API.

Ways this can go wrong, and the test for each:
- the key is written through argv, where a process listing shows it;
- a forgotten key stays behind, or forgetting one that is gone raises;
- a refused key, or one the API never answered for, counts as accepted;
- text that is not an Anthropic key reaches the network at all;
- the helper prints anything beside the key, or exits 0 with no key;
- one account's key is printed for another, or the item `api-key` another
  launcher keeps under the same service is read, written or deleted;
- an argument to the helper that is not an account id reaches the shell or the Keychain.

Every Keychain call here names a throwaway keychain created for the test:
`security` given a keychain path that does not exist falls through to the
login keychain, where the real key lives.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accounts  # noqa: E402
import api_fallback  # noqa: E402
import statusline  # noqa: E402
from conftest import scratch_keychain_at  # noqa: E402

HELPER_SCRIPT = Path(__file__).resolve().parent.parent / "api-key-helper.sh"
KEY = "sk-ant-test-" + "a1b2" * 20 + "wxyz"

live = pytest.mark.skipif(sys.platform != "darwin", reason="needs the macOS Keychain")


@pytest.fixture
def scratch_keychain(tmp_path, monkeypatch):
    """A keychain file of the test's own, named by every call."""
    with scratch_keychain_at(str(tmp_path / f"scratch-{uuid.uuid4().hex[:8]}.keychain-db")) as path:
        monkeypatch.setattr(accounts, "KEYCHAIN", path)
        # The helper script reads the panel's own service; in this keychain that is the test's item.
        monkeypatch.setattr(api_fallback, "KEY_SERVICE", accounts.PANEL_SERVICE)
        yield path


@pytest.fixture
def store(tmp_path):
    """An account store of the test's own: alice as acct-1, bob as acct-2."""
    path = str(tmp_path / "config" / "accounts.json")
    accounts.save_store(path, [{"id": "acct-1", "accountUuid": "uuid-a", "alias": "alice"},
                               {"id": "acct-2", "accountUuid": "uuid-b", "alias": "bob"}])
    return path


BOBS_KEY = "sk-ant-test-" + "e5f6" * 20 + "abcd"
#: What another launcher keeps under the panel's service as the single item `api-key`.
LAUNCHERS = "sk-ant-test-" + "0909" * 20 + "lnch"


def item(keychain, account):
    done = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", account, "-s", accounts.PANEL_SERVICE,
                           "-w", keychain], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


@live
def test_a_stored_key_reads_back_for_its_own_account_and_its_last_four_go_in_the_store(scratch_keychain, store):
    assert api_fallback.store_key(store, "acct-1", KEY) == "wxyz"
    assert api_fallback.store_key(store, "acct-2", BOBS_KEY) == "abcd"
    assert (api_fallback.read_key("acct-1"), api_fallback.read_key("acct-2")) == (KEY, BOBS_KEY)
    assert item(scratch_keychain, "api-key:acct-1") == KEY
    assert [a.get("apiKeyLast4") for a in accounts.load_store(store)] == ["wxyz", "abcd"]
    assert KEY not in Path(store).read_text()


@live
def test_a_forgotten_key_is_gone_with_its_last_four_and_forgetting_twice_is_fine(scratch_keychain, store):
    api_fallback.store_key(store, "acct-1", KEY)
    api_fallback.store_key(store, "acct-2", BOBS_KEY)
    api_fallback.forget_key(store, "acct-1")
    assert (api_fallback.read_key("acct-1"), api_fallback.read_key("acct-2")) == (None, BOBS_KEY)
    assert [a.get("apiKeyLast4") for a in accounts.load_store(store)] == [None, "abcd"]
    api_fallback.forget_key(store, "acct-1")


@live
def test_the_launchers_api_key_item_is_never_read_written_or_deleted(scratch_keychain, store, world):
    """The item `api-key` belongs to another launcher: nothing of the panel's names it."""
    subprocess.run(["/usr/bin/security", "add-generic-password", "-a", "api-key", "-s", accounts.PANEL_SERVICE,
                    "-w", LAUNCHERS, scratch_keychain], check=True)
    assert api_fallback.read_key("acct-1") is None, "alice has no key of her own, and the launcher's is not hers"
    done = run_helper(world, "acct-1")
    assert (done.returncode, done.stdout) == (1, ""), "the helper prints only alice's own item"
    api_fallback.store_key(store, "acct-1", KEY)
    api_fallback.forget_key(store, "acct-1")
    api_fallback.forget_key(store, "acct-2")
    assert item(scratch_keychain, "api-key") == LAUNCHERS
    for name in ("", "api-key", "acct-1:x"):
        with pytest.raises(ValueError, match="is not an account id"):
            api_fallback.key_item(name)


def test_the_key_goes_to_security_over_stdin(monkeypatch, store):
    calls = []
    monkeypatch.setattr(accounts, "_run_security",
                        lambda argv, stdin=None: calls.append((argv, stdin)) or subprocess.CompletedProcess(argv, 0, "", ""))
    api_fallback.store_key(store, "acct-1", KEY)
    (argv, stdin), = calls
    assert not any(KEY in word or KEY.encode().hex() in word for word in argv)
    assert KEY.encode().hex() in stdin
    assert '"api-key:acct-1"' in stdin


def test_a_key_for_an_account_that_is_not_stored_is_refused_before_the_keychain(monkeypatch, store):
    sent = []
    monkeypatch.setattr(accounts, "_run_security", lambda *a, **k: sent.append(a))
    for account_id, why in (("acct-9", "no stored account acct-9"), ("bob", "'bob' is not an account id")):
        with pytest.raises(ValueError, match=why):
            api_fallback.store_key(store, account_id, KEY)
        with pytest.raises(ValueError, match=why):
            api_fallback.forget_key(store, account_id)
    assert sent == []


def test_a_cap_is_kept_per_account_and_defaults_to_fifty(store):
    api_fallback.set_cap(store, "acct-2", 12.5)
    assert [accounts.api_key_cap(a) for a in accounts.load_store(store)] == [50.0, 12.5]
    for bad in (0, -5, float("nan"), float("inf"), "50", None, True):
        with pytest.raises(ValueError, match="a cap is a positive number of dollars"):
            api_fallback.set_cap(store, "acct-1", bad)
    with pytest.raises(ValueError, match="no stored account acct-9"):
        api_fallback.set_cap(store, "acct-9", 5)


@pytest.mark.parametrize("field,value", [("apiKeyLast4", "wxyzz"), ("apiKeyLast4", 1234), ("apiKeyCapUsd", 0),
                                         ("apiKeyCapUsd", "50"), ("apiKeyCapUsd", -1)])
def test_a_store_with_a_bad_key_field_is_not_trusted(tmp_path, field, value):
    text = json.dumps({"version": 1, "accounts": [{"id": "acct-1", "accountUuid": "uuid-a", field: value}]})
    with pytest.raises(accounts.StoreError, match=f"account acct-1 has an {field}"):
        accounts.parse_store(text)


def test_text_that_is_not_an_anthropic_key_is_refused_before_anything_is_stored_or_sent(monkeypatch, store):
    sent = []
    monkeypatch.setattr(accounts, "_run_security", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(api_fallback.urllib.request, "urlopen", lambda *a, **k: sent.append(a))
    for text in ("", "hunter2", "sk-ant-", "sk-ant-short\nsecond line", " sk-ant-test-" + "a" * 40, 42, None):
        with pytest.raises(ValueError, match="not an Anthropic API key"):
            api_fallback.store_key(store, "acct-1", text)
        assert api_fallback.validate_key(text) == api_fallback.KeyProblem("refused", "not an Anthropic API key")
    assert sent == []


class StandIn(http.server.BaseHTTPRequestHandler):
    """The models endpoint as the test needs it: 200 for KEY, 401 for any other, or a stall."""
    stall = 0.0
    heard = []
    status = None

    def do_GET(self):
        StandIn.heard.append((self.path, self.headers.get("x-api-key"), self.headers.get("anthropic-version")))
        time.sleep(StandIn.stall)
        status = StandIn.status or (200 if self.headers.get("x-api-key") == KEY else 401)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    def log_message(self, *args):
        pass


@pytest.fixture
def models_url():
    StandIn.stall, StandIn.heard, StandIn.status = 0.0, [], None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1/models"
    server.shutdown()
    server.server_close()


def test_a_key_the_api_answers_for_is_accepted(models_url):
    assert api_fallback.validate_key(KEY, url=models_url) is None
    assert StandIn.heard == [("/v1/models", KEY, "2023-06-01")]


@pytest.mark.parametrize("status", [401, 403])
def test_only_a_401_or_403_refuses_a_key(models_url, status):
    StandIn.status = status
    problem = api_fallback.validate_key(KEY, url=models_url)
    assert (problem.kind, problem.why) == ("refused", f"the key was refused ({status})")


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503, 529])
def test_any_other_status_says_the_key_could_not_be_checked(models_url, status):
    StandIn.status = status
    problem = api_fallback.validate_key(KEY, url=models_url)
    assert (problem.kind, problem.why) == ("unavailable", f"the API answered {status}")


def test_an_api_that_does_not_answer_is_unavailable(models_url):
    StandIn.stall = 1.0
    problem = api_fallback.validate_key(KEY, url=models_url, timeout=0.2)
    assert (problem.kind, problem.why) == ("unavailable", "the API did not answer (timed out)")


def test_an_api_that_cannot_be_reached_is_unavailable():
    problem = api_fallback.validate_key(KEY, url="http://127.0.0.1:9/v1/models")
    assert problem.kind == "unavailable"
    assert problem.why.startswith("the API could not be reached (")


SETTINGS = {"model": "opus", "env": {"ALICE": "1"}, "apiKeyHelper": statusline.helper_command(HELPER_SCRIPT, "acct-1")}


@pytest.fixture
def world(tmp_path, scratch_keychain):
    """The helper's files, all under tmp: settings.json naming it, a status folder and an endpoint."""
    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps(SETTINGS, indent=2) + "\n")
    env = dict(os.environ, AGENTS_SIDEBAR_KEYCHAIN=scratch_keychain,
               AGENTS_SIDEBAR_ENDPOINT=str(tmp_path / "endpoint.json"),
               AGENTS_SIDEBAR_CLAUDE_SETTINGS=str(settings),
               AGENTS_SIDEBAR_STATUS_DIR=str(tmp_path / "status"),
               AGENTS_SIDEBAR_AUTOLAUNCH=str(tmp_path / "AutoLaunch" / "agents_sidebar.py"))
    return {"env": env, "settings": settings, "endpoint": tmp_path / "endpoint.json",
            "marker": tmp_path / "status" / "api-fallback-orphaned", "tmp": tmp_path}


def run_helper(world, *args):
    return subprocess.run([str(HELPER_SCRIPT), *(args or ("acct-1",))], capture_output=True, text=True,
                          env=world["env"], timeout=30)


def keep(key=KEY, account_id="acct-1"):
    """The key in the scratch keychain's item for `account_id`, as store_key leaves it."""
    accounts.write_secret(api_fallback.KEY_SERVICE, api_fallback.key_item(account_id), key)


def say_where(world, pid):
    world["endpoint"].write_text(json.dumps({"port": 1, "token": "never-printed-token", "pid": pid}))


def write_stub(path, checkout):
    """The AutoLaunch stub install.sh writes, with a sleep where the daemon would start."""
    path.parent.mkdir(exist_ok=True)
    path.write_text("import runpy\nimport time\ntime.sleep(60)\n"
                    f'runpy.run_path("{checkout}/sidebar.py", run_name="__main__")\n')


def launched(argv):
    proc = subprocess.Popen(argv)
    # Until the process has exec'd, ps still shows the fork's own command.
    time.sleep(0.2)
    return proc


@pytest.fixture
def daemon(tmp_path):
    """A live process running the AutoLaunch stub that loads this checkout, as the real daemon does."""
    script = tmp_path / "AutoLaunch" / "agents_sidebar.py"
    write_stub(script, HELPER_SCRIPT.parent)
    proc = launched([sys.executable, str(script)])
    yield proc.pid
    proc.kill()
    proc.wait()


@pytest.fixture
def stranger():
    """A live process that is not the panel's daemon."""
    proc = subprocess.Popen(["/bin/sleep", "60"])
    yield proc.pid
    proc.kill()
    proc.wait()


def dead_pid():
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


@live
def test_with_the_daemon_alive_the_helper_prints_the_key_and_changes_nothing(world, daemon):
    keep()
    say_where(world, daemon)
    before = world["settings"].read_bytes()
    done = run_helper(world)
    assert (done.returncode, done.stdout, done.stderr) == (0, KEY + "\n", "")
    assert world["settings"].read_bytes() == before
    assert not world["marker"].exists()


@live
def test_with_the_daemon_dead_the_helper_hands_out_the_key_once_more_and_takes_itself_out(world):
    keep()
    say_where(world, dead_pid())
    done = run_helper(world)
    assert (done.returncode, done.stdout, done.stderr) == (0, KEY + "\n", "")
    assert json.loads(world["settings"].read_text()) == {"model": "opus", "env": {"ALICE": "1"}}
    assert world["marker"].exists()
    assert "never-printed-token" not in done.stdout + done.stderr


@live
def test_no_endpoint_at_all_counts_as_a_dead_daemon(world):
    keep()
    done = run_helper(world)
    assert (done.returncode, done.stdout) == (0, KEY + "\n")
    assert "apiKeyHelper" not in json.loads(world["settings"].read_text())
    assert world["marker"].exists()


@live
def test_a_live_pid_that_is_not_the_daemon_counts_as_dead(world, stranger):
    keep()
    say_where(world, stranger)
    done = run_helper(world)
    assert (done.returncode, done.stdout) == (0, KEY + "\n")
    assert "apiKeyHelper" not in json.loads(world["settings"].read_text())


def assert_counts_as_dead(world, proc):
    try:
        keep()
        say_where(world, proc.pid)
        done = run_helper(world)
        assert (done.returncode, done.stdout) == (0, KEY + "\n")
        assert "apiKeyHelper" not in json.loads(world["settings"].read_text()), "the helper took itself out"
        assert world["marker"].exists()
    finally:
        proc.kill()
        proc.wait()


@live
def test_a_stub_that_loads_another_checkout_counts_as_dead(world, tmp_path):
    stub = tmp_path / "AutoLaunch" / "agents_sidebar.py"
    write_stub(stub, "/opt/another/checkout")
    assert_counts_as_dead(world, launched([sys.executable, str(stub)]))


@live
def test_any_other_process_named_sidebar_py_counts_as_dead(world, tmp_path):
    script = tmp_path / "elsewhere" / "sidebar.py"
    script.parent.mkdir()
    script.write_text("import time\ntime.sleep(60)\n")
    assert_counts_as_dead(world, launched([sys.executable, str(script)]))


@live
def test_a_long_argv_that_merely_mentions_the_daemon_counts_as_dead(world):
    words = [sys.executable, "-c", "import time; time.sleep(60)", "a" * 3000, "/fake/agents_sidebar.py"]
    assert_counts_as_dead(world, launched(words))


@pytest.fixture
def spaced_checkout(tmp_path, world):
    """This checkout's helper files copied under a path holding a space, its sidebar.py asleep."""
    checkout = tmp_path / "my checkout"
    checkout.mkdir()
    (checkout / "api-key-helper.sh").write_text(HELPER_SCRIPT.read_text())
    (checkout / "api-key-helper.sh").chmod(0o755)
    for module in ("statusline.py", "accounts.py"):
        (checkout / module).write_text((HELPER_SCRIPT.parent / module).read_text())
    (checkout / "sidebar.py").write_text("import time\ntime.sleep(60)\n")
    command = statusline.helper_command(checkout / "api-key-helper.sh", "acct-1")
    world["settings"].write_text(json.dumps(dict(SETTINGS, apiKeyHelper=command), indent=2) + "\n")
    return {"dir": checkout, "command": command}


def run_command(world, command):
    return subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, env=world["env"], timeout=30)


@live
def test_the_command_runs_from_a_path_with_a_space_with_its_daemon_alive(world, spaced_checkout):
    """The daemon runs the checkout's sidebar.py directly here, so that exact file is what counts as alive."""
    keep()
    proc = launched([sys.executable, str(spaced_checkout["dir"] / "sidebar.py")])
    try:
        say_where(world, proc.pid)
        before = world["settings"].read_bytes()
        done = run_command(world, spaced_checkout["command"])
        assert (done.returncode, done.stdout, done.stderr) == (0, KEY + "\n", "")
        assert world["settings"].read_bytes() == before
    finally:
        proc.kill()
        proc.wait()


@live
def test_a_helper_at_a_path_with_a_space_takes_its_quoted_command_out(world, spaced_checkout):
    keep()
    done = run_command(world, spaced_checkout["command"])
    assert (done.returncode, done.stdout) == (0, KEY + "\n")
    assert "apiKeyHelper" not in json.loads(world["settings"].read_text())
    assert world["marker"].exists()


@live
def test_a_drop_that_fails_still_hands_out_the_key_and_says_why(world):
    """An exit other than 0 fails the turn in flight."""
    keep()
    world["settings"].write_text("{ not json")
    done = run_helper(world)
    assert (done.returncode, done.stdout) == (0, KEY + "\n")
    assert "not valid JSON" in done.stderr
    assert world["settings"].read_text() == "{ not json"


@live
def test_sessions_fetching_the_key_at_once_all_get_it_and_the_drop_lands_once(world):
    keep()
    procs = [subprocess.Popen([str(HELPER_SCRIPT), "acct-1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env=world["env"]) for _ in range(6)]
    results = [proc.communicate(timeout=30) + (proc.returncode,) for proc in procs]
    assert all(out == KEY + "\n" and code == 0 for out, _, code in results), results
    assert json.loads(world["settings"].read_text()) == {"model": "opus", "env": {"ALICE": "1"}}
    assert sorted(p.name for p in world["settings"].parent.iterdir()) == ["settings.json"], "no staged file left"


@live
def test_a_helper_that_cannot_read_the_key_steps_aside_and_fails_the_turn(world, daemon):
    """Later turns then run on the subscription, whatever the daemon is doing."""
    say_where(world, daemon)
    done = run_helper(world)
    assert (done.returncode, done.stdout) == (1, "")
    assert done.stderr, "security says why on stderr, which Claude Code shows with the failed turn"
    assert json.loads(world["settings"].read_text()) == {"model": "opus", "env": {"ALICE": "1"}}
    assert world["marker"].exists()


@live
def test_a_helper_that_cannot_read_the_key_and_cannot_drop_still_fails_the_turn(world):
    world["settings"].write_text("{ not json")
    done = run_helper(world)
    assert (done.returncode, done.stdout) == (1, "")
    assert world["settings"].read_text() == "{ not json"
    assert world["marker"].exists()


def test_the_helper_stops_on_the_first_failure():
    assert "set -euo pipefail" in HELPER_SCRIPT.read_text().splitlines()[3:6]


def test_the_helper_reads_only_the_pid_from_the_endpoint():
    """The endpoint also holds the daemon's token, which no key fetch needs."""
    text = HELPER_SCRIPT.read_text()
    assert "-extract pid raw" in text
    assert "token" not in text


@live
def test_the_helper_prints_the_key_of_the_account_it_names(world, daemon):
    keep()
    keep(BOBS_KEY, "acct-2")
    say_where(world, daemon)
    world["settings"].write_text(json.dumps(dict(SETTINGS, apiKeyHelper=statusline.helper_command(HELPER_SCRIPT, "acct-2"))))
    done = run_helper(world, "acct-2")
    assert (done.returncode, done.stdout, done.stderr) == (0, BOBS_KEY + "\n", "")


@live
def test_each_fetch_is_filed_under_the_process_that_asked_with_the_account_and_never_the_key(world, daemon):
    """Claude Code runs the helper as its own child, so the parent's pid names the session; the
    daemon blames a key only for a failure in a session that fetched it."""
    keep()
    keep(BOBS_KEY, "acct-2")
    say_where(world, daemon)
    asker = subprocess.run(["/bin/bash", "-c", f'"{HELPER_SCRIPT}" acct-1 >/dev/null; "{HELPER_SCRIPT}" acct-2 >/dev/null; echo $$'],
                           capture_output=True, text=True, env=world["env"], timeout=30)
    filed = (world["tmp"] / "status" / "api-key-fetches" / asker.stdout.strip()).read_text()
    lines = [line.split() for line in filed.splitlines()]
    assert [line[1] for line in lines] == ["acct-1", "acct-2"]
    assert all(line[0].isdigit() and abs(int(line[0]) - time.time()) < 60 for line in lines)
    assert KEY not in filed and BOBS_KEY not in filed


@pytest.mark.parametrize("args", [(), ("acct-1", "acct-2"), ("",), ("bob",), ("acct-1; touch pwned",),
                                  ("$(touch pwned)",), ("`touch pwned`",), ("acct-1\ntouch pwned",), ("api-key",)])
def test_the_helper_refuses_an_argument_that_is_not_one_account_id_and_runs_none_of_it(world, args):
    keep()
    before = world["settings"].read_bytes()
    done = subprocess.run([str(HELPER_SCRIPT), *args], capture_output=True, text=True, env=world["env"],
                          timeout=30, cwd=world["tmp"])
    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr == "api-key-helper.sh: expected one account id like acct-1\n"
    assert not (world["tmp"] / "pwned").exists()
    assert world["settings"].read_bytes() == before, "a call that is not the panel's takes nothing out"
    assert not world["marker"].exists()
