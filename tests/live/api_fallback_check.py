#!/usr/bin/env python3
# ABOUTME: Live checks of the API fallback against the installed Claude Code and a scratch CLAUDE_CONFIG_DIR:
# ABOUTME: settings reload of apiKeyHelper, the bad-key stall (--bad-key) and one real-key turn (--real-key).
"""Rerun against each new Claude Code: the fallback rests on behaviour only a
run can show. Nothing here writes the real settings.json. The first section
spends nothing: there is no login in the scratch folder and its helper fails,
so only the key source each turn reports is measured.

    python3 tests/live/api_fallback_check.py             # the settings reload, under a minute
    python3 tests/live/api_fallback_check.py --bad-key   # adds the invalid-key stall, about 4 minutes
    python3 tests/live/api_fallback_check.py --real-key  # adds one Haiku turn on the first stored account key, about $0.005
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import accounts  # noqa: E402
import api_fallback  # noqa: E402
import statusline  # noqa: E402

TURN_SECONDS = 120
BAD_KEY_SECONDS = 330
SETTLE_SECONDS = 3
PROMPT = {"type": "user", "message": {"role": "user", "content": "Reply with the single word ok."}}


class Session:
    """A streaming `claude -p` under a scratch config folder, taking one prompt at a time."""

    def __init__(self, config_dir, cwd):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
        env.update(CLAUDE_CONFIG_DIR=str(config_dir))
        self.process = subprocess.Popen(
            ["claude", "-p", "--model", "haiku", "--no-session-persistence", "--verbose",
             "--input-format", "stream-json", "--output-format", "stream-json"],
            cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def turn(self, timeout):
        """Send the prompt and read to the turn's result. -> the key source its init reported, and the result."""
        self.process.stdin.write(json.dumps(PROMPT) + "\n")
        self.process.stdin.flush()
        source, deadline = None, time.time() + timeout
        while time.time() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("claude exited before the turn's result")
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                source = event.get("apiKeySource")
            if event.get("type") == "result":
                return source, event
        raise RuntimeError(f"no result within {timeout} s")

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}: {name}{f' ({detail})' if detail else ''}", flush=True)


def scratch_helper(folder, body):
    """A helper script at a path of the test's own, for a scratch settings file to name."""
    script = folder / "api-key-helper.sh"
    script.write_text(f"#!/bin/bash\n{body}\n")
    script.chmod(0o755)
    return str(script)


def settings_reload(folder):
    print("-- apiKeyHelper added and removed under a running session", flush=True)
    config = folder / "config"
    config.mkdir()
    settings = config / "settings.json"
    settings.write_text("{}\n")
    helper = scratch_helper(folder, "exit 1")
    session = Session(config, folder)
    try:
        source, _ = session.turn(TURN_SECONDS)
        check("no helper: the key source is none", source == "none", source)
        command = statusline.helper_command(helper, "acct-1")
        statusline.set_api_key_helper(settings, command, [command])
        time.sleep(SETTLE_SECONDS)
        source, _ = session.turn(TURN_SECONDS)
        check("helper written: the next turn's source is apiKeyHelper", source == "apiKeyHelper", source)
        statusline.drop_api_key_helper(settings, [command])
        time.sleep(SETTLE_SECONDS)
        source, _ = session.turn(TURN_SECONDS)
        check("helper dropped: the next turn's source is none again", source == "none", source)
    finally:
        session.close()


def bad_key(folder):
    print("-- a bad key through the helper: StopFailure with authentication_failed (about 4 minutes)", flush=True)
    config = folder / "bad-config"
    config.mkdir()
    heard = folder / "stop-failure.json"
    hook = folder / "hook.sh"
    hook.write_text(f'#!/bin/bash\ncat > "{heard}"\n')
    hook.chmod(0o755)
    helper = scratch_helper(folder, "echo sk-ant-test-this-key-does-not-exist")
    (config / "settings.json").write_text(json.dumps({
        "apiKeyHelper": helper,
        "hooks": {"StopFailure": [{"hooks": [{"type": "command", "command": str(hook)}]}]}}))
    session = Session(config, folder)
    try:
        session.turn(BAD_KEY_SECONDS)
    finally:
        session.close()
    payload = json.loads(heard.read_text()) if heard.exists() else {}
    check("StopFailure names authentication_failed", payload.get("error") == "authentication_failed", payload.get("error"))


def real_key(folder):
    print("-- the first stored account key: validate_key and one Haiku turn", flush=True)
    keyed = [a["id"] for a in accounts.load_store(accounts.STORE_PATH) if a.get("apiKeyLast4")]
    key = api_fallback.read_key(keyed[0]) if keyed else None
    if key is None:
        print("SKIPPED: no account has a key stored")
        return
    check("the models list accepts the stored key", api_fallback.validate_key(key) is None)
    config = folder / "real-config"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps(
        {"apiKeyHelper": statusline.helper_command(ROOT / "api-key-helper.sh", keyed[0])}))
    session = Session(config, folder)
    try:
        source, result = session.turn(TURN_SECONDS)
    finally:
        session.close()
    check("the turn ran on the helper", source == "apiKeyHelper", source)
    check("the turn succeeded", result.get("is_error") is False, f"${result.get('total_cost_usd')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bad-key", action="store_true", help="run the invalid-key stall, about 4 minutes")
    parser.add_argument("--real-key", action="store_true", help="run one Haiku turn on the first stored account key")
    args = parser.parse_args()
    if not shutil.which("claude"):
        sys.exit("claude is not on PATH")
    print(subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip(), flush=True)
    with tempfile.TemporaryDirectory(prefix="api-fallback-live-") as scratch:
        folder = Path(scratch).resolve()
        settings_reload(folder)
        if args.bad_key:
            bad_key(folder)
        else:
            print("SKIPPED: the bad-key stall (--bad-key)")
        if args.real_key:
            real_key(folder)
        else:
            print("SKIPPED: the real-key turn (--real-key)")
    print(f"{sum(results)} of {len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
