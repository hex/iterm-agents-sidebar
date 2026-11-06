# ABOUTME: Exercises uninstall over a real local HTTP connection with a harmless script.
# ABOUTME: Every uninstall target, HOME and output log belongs to the test directory.
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

import sidebar


def panel(tmp_path, monkeypatch):
    script = tmp_path / "uninstall.sh"
    monkeypatch.setattr(sidebar, "UNINSTALL_SCRIPT", script, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEST_PYTHON", sys.executable)
    page = tmp_path / "page.html"
    page.write_text("panel")
    return sidebar.Sidebar("test-token", page, lambda: {"groups": []}, lambda *_: None), script


async def request(app, target, received=None, body=b""):
    transport = sidebar.Server(app)
    handlers = []
    def connected(reader, writer):
        handlers.append(asyncio.create_task(transport._client(reader, writer)))
    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        writer.write(f"POST {target} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 5)
        if received:
            received.write_text("response received")
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(asyncio.gather(*handlers), 5)
        if app.uninstall_job and app.uninstall_job.process:
            await asyncio.wait_for(app.uninstall_job.process.wait(), 5)
    head, body = response.split(b"\r\n\r\n", 1)
    return int(head.split()[1]), body


@pytest.mark.parametrize("keep_accounts", [False, True])
def test_uninstall_answers_before_its_detached_script_finishes(tmp_path, monkeypatch, keep_accounts):
    app, script = panel(tmp_path, monkeypatch)
    received = tmp_path / "received"
    script.write_text(f'''#!/bin/bash
exec "$TEST_PYTHON" - "$@" <<'PY'
import json, os, sys, time
from pathlib import Path
deadline = time.monotonic() + 4
while not Path({str(received)!r}).exists():
    if time.monotonic() > deadline:
        raise RuntimeError("no response arrived")
    time.sleep(0.01)
print(json.dumps({{"detached": os.getsid(0) == os.getpid(), "home": os.environ["HOME"], "args": sys.argv[1:]}}))
print("script stderr", file=__import__("sys").stderr)
PY
''')
    status, body = asyncio.run(request(app, "/uninstall?token=test-token", received,
                                     json.dumps({"keep_accounts": keep_accounts}).encode()))
    assert status == 202
    reply = json.loads(body)
    log = Path(reply["log"])
    assert log.parent == tmp_path
    lines = log.read_text().splitlines()
    assert lines == ["script stderr", json.dumps({"detached": True, "home": str(tmp_path),
                                                "args": ["--keep-accounts"] if keep_accounts else []})]
    assert log.stat().st_mode & 0o777 == 0o600


def test_a_missing_uninstall_script_is_refused_before_creating_a_log(tmp_path, monkeypatch):
    app, script = panel(tmp_path, monkeypatch)
    status, body = asyncio.run(request(app, "/uninstall?token=test-token"))
    assert (status, json.loads(body)) == (409, {"error": f"uninstall script is missing: {script}"})
    assert list(tmp_path.glob("*.log")) == []


def test_a_second_uninstall_request_does_not_start_another_script(tmp_path, monkeypatch):
    app, script = panel(tmp_path, monkeypatch)
    script.write_text("exit 0\n")
    assert asyncio.run(request(app, "/uninstall?token=test-token"))[0] == 202
    status, body = asyncio.run(request(app, "/uninstall?token=test-token"))
    assert (status, json.loads(body)) == (409, {"error": "uninstall already requested"})
    assert len(list(tmp_path.glob("*.log"))) == 1


def test_a_wrong_token_cannot_create_a_log_or_run_the_script(tmp_path, monkeypatch):
    app, script = panel(tmp_path, monkeypatch)
    script.write_text("exit 42\n")
    assert asyncio.run(request(app, "/uninstall?token=wrong")) == (403, b"forbidden")
    assert list(tmp_path.glob("*.log")) == []


@pytest.mark.parametrize("body", [
    b'{"other": true}', b'{"keep_accounts": true, "other": false}',
    b'{"keep_accounts": "true"}', b'{"keep_accounts": 1}', b'{"keep_accounts": null}',
    b'[]', b'null', b'{',
])
def test_uninstall_accepts_only_a_boolean_keep_accounts_option(tmp_path, monkeypatch, body):
    app, script = panel(tmp_path, monkeypatch)
    script.write_text("exit 42\n")
    status, reply = asyncio.run(request(app, "/uninstall?token=test-token", body=body))
    assert (status, json.loads(reply)) == (400, {"error": "expected only an optional boolean keep_accounts"})
    assert app.uninstall_job is None
    assert list(tmp_path.glob("*.log")) == []
