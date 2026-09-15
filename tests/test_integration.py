"""End-to-end over a real socket: real asyncio listener, real HTTP, real SSE.

No iTerm2 here -- Bridge is the only unit that needs it, and it gets a live
smoke test instead, because mocking that API would only test the mock. The
snapshot_fn below is test data, not a stand-in for the code under test.
"""
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import Server, Sidebar

TOKEN = "integration-token-not-a-real-secret"
PAYLOAD = {"groups": [{"name": "AGENTS", "rows": [
    {"session_id": "abc", "window_id": "w", "tab_id": "26", "label": "iterm"}]}]}


async def running_server(tmp_path, calls):
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    sidebar = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: PAYLOAD,
                      action_fn=lambda s, v, t: calls.append((s, v, t)))
    server = Server(sidebar)
    return server, await server.start()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


@pytest.mark.asyncio
async def test_page_and_auth_over_a_real_socket(tmp_path):
    calls = []
    server, port = await running_server(tmp_path, calls)

    status, body = await asyncio.to_thread(get, f"http://127.0.0.1:{port}/?token={TOKEN}")
    assert (status, body) == (200, b"<h1>agents</h1>")

    with pytest.raises(urllib.error.HTTPError) as refused:
        await asyncio.to_thread(get, f"http://127.0.0.1:{port}/?token=nope")
    assert refused.value.code == 403


@pytest.mark.asyncio
async def test_events_stream_opens_with_current_state(tmp_path):
    """A page connecting mid-session must not sit blank until something
    changes, so the stream leads with the current snapshot.
    """
    calls = []
    server, port = await running_server(tmp_path, calls)

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET /events?token={TOKEN} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()

    await reader.readuntil(b"\r\n\r\n")                       # response headers
    first = await asyncio.wait_for(reader.readuntil(b"\n\n"), timeout=5)
    assert json.loads(first.split(b"data: ", 1)[1]) == PAYLOAD

    # And a later broadcast reaches the same open stream.
    server.broadcast(b"data: {\"groups\": []}\n\n")
    second = await asyncio.wait_for(reader.readuntil(b"\n\n"), timeout=5)
    assert json.loads(second.split(b"data: ", 1)[1]) == {"groups": []}
    writer.close()


@pytest.mark.asyncio
async def test_action_reaches_the_handler_over_http(tmp_path):
    calls = []
    server, port = await running_server(tmp_path, calls)

    def post():
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/action?token={TOKEN}",
            data=b'{"session_id": "abc", "verb": "focus"}', method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status

    assert await asyncio.to_thread(post) == 200
    assert calls == [("abc", "focus", None)]


@pytest.mark.asyncio
async def test_a_slow_account_op_does_not_hold_up_other_requests(tmp_path):
    """A switch waits on Claude Code's locks and a token refresh for seconds; on
    the event loop that would stall every other request and the heartbeat, and
    the panel would flag itself stale in the middle of a switch."""
    import threading
    import time
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    # A thread event: a loop-side signal could not be delivered while the loop is blocked.
    started = threading.Event()

    def slow_switch(op, request):
        started.set()
        time.sleep(1.5)
        return {"id": "acct-2", "name": "home"}

    sidebar = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: PAYLOAD,
                      action_fn=lambda *a: None, accounts_fn=slow_switch)
    port = await Server(sidebar).start()

    def post():
        request = urllib.request.Request(f"http://127.0.0.1:{port}/accounts?token={TOKEN}",
                                         data=b'{"op": "switch", "account_id": "acct-2"}', method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status

    def page_while_switching():
        # Timed entirely off the loop: awaiting anything would wait for the loop too.
        assert started.wait(2)
        began = time.monotonic()
        status, _ = get(f"http://127.0.0.1:{port}/?token={TOKEN}")
        return status, time.monotonic() - began

    switching = asyncio.ensure_future(asyncio.to_thread(post))
    status, took = await asyncio.to_thread(page_while_switching)
    assert status == 200
    assert took < 0.5, f"the page waited {took:.2f}s behind the switch"
    assert await switching == 200
