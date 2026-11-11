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
    # Then whether that state is current, so a stale one is never taken for fresh.
    verdict = await asyncio.wait_for(reader.readuntil(b"\n\n"), timeout=5)
    assert verdict == b'event: heartbeat\ndata: {"fresh": true}\n\n'

    # And a later broadcast reaches the same open stream.
    server.broadcast(b"data: {\"groups\": []}\n\n")
    second = await asyncio.wait_for(reader.readuntil(b"\n\n"), timeout=5)
    assert json.loads(second.split(b"data: ", 1)[1]) == {"groups": []}
    writer.close()


#: RFC 6455's own example: this key is answered with s3pPLMBiTxaQ9kYGzzhZRbK+xOo=.
SAMPLE_KEY = "dGhlIHNhbXBsZSBub25jZQ=="


async def open_live(port, token=TOKEN, origin=None):
    """-> (reader, writer, response head) for a WebSocket handshake on /live,
    as a script sends it, or as a page on `origin` would."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((f"GET /live?token={token} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                  + (f"Origin: {origin}\r\n" if origin else "")
                  + f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {SAMPLE_KEY}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    return reader, writer, head


async def server_message(reader):
    """-> (first byte, payload) of the daemon's next frame. A server never masks."""
    first, second = await asyncio.wait_for(reader.readexactly(2), timeout=5)
    assert second & 0x80 == 0, "the daemon masked a frame"
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    return first, await asyncio.wait_for(reader.readexactly(length), timeout=5)


def client_frame(opcode, payload, mask=b"\x37\xfa\x21\x3d"):
    """One final frame from a client, masked as RFC 6455 requires of every one."""
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    if len(payload) < 126:
        length = bytes([0x80 | len(payload)])
    else:
        length = bytes([0x80 | 126]) + len(payload).to_bytes(2, "big")
    return bytes([0x80 | opcode]) + length + mask + masked


@pytest.mark.asyncio
async def test_live_socket_opens_with_current_state(tmp_path):
    """The panel's own transport carries the same frames as /events: the
    current snapshot, then whether it is current, then every broadcast."""
    server, port = await running_server(tmp_path, [])
    reader, writer, head = await open_live(port)

    status, *headers = head.decode().rstrip("\r\n").split("\r\n")
    assert status == "HTTP/1.1 101 Switching Protocols"
    assert dict(line.split(": ", 1) for line in headers) == {
        "Upgrade": "websocket", "Connection": "Upgrade",
        "Sec-WebSocket-Accept": "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="}

    first, snapshot = await server_message(reader)
    assert first == 0x81                                      # final text frame
    assert (snapshot[:6], snapshot[-2:]) == (b"data: ", b"\n\n")
    assert json.loads(snapshot[6:-2]) == PAYLOAD
    assert await server_message(reader) == (0x81, b'event: heartbeat\ndata: {"fresh": true}\n\n')

    # Past the one-byte and two-byte length forms too: a snapshot of many
    # sessions runs to tens of kilobytes.
    for size in (300, 70_000):
        frame = b"data: " + json.dumps({"groups": [], "pad": "x" * size}).encode() + b"\n\n"
        server.broadcast(frame)
        assert await server_message(reader) == (0x81, frame)
    writer.close()


@pytest.mark.asyncio
async def test_live_socket_refuses_a_wrong_token_and_a_plain_request(tmp_path):
    server, port = await running_server(tmp_path, [])
    reader, writer, head = await open_live(port, token="nope")
    assert head == b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"
    writer.close()

    with pytest.raises(urllib.error.HTTPError) as plain:
        await asyncio.to_thread(get, f"http://127.0.0.1:{port}/live?token={TOKEN}")
    assert plain.value.code == 400
    assert server.subscribers == set()


@pytest.mark.asyncio
async def test_live_socket_takes_only_the_panels_own_origin(tmp_path):
    """A WebSocket skips the browser's cross-origin rules, so a page elsewhere
    that held the token could read the frames. Its Origin header gives it away;
    the panel's own passes, and a script sends none."""
    server, port = await running_server(tmp_path, [])
    reader, writer, head = await open_live(port, origin="http://evil.example")
    assert head == b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"
    writer.close()
    assert server.subscribers == set()

    reader, writer, head = await open_live(port, origin=f"http://127.0.0.1:{port}")
    assert head.startswith(b"HTTP/1.1 101 Switching Protocols\r\n")
    first, payload = await server_message(reader)
    assert json.loads(payload.split(b"data: ", 1)[1]) == PAYLOAD
    writer.close()


@pytest.mark.asyncio
async def test_a_close_from_the_page_ends_its_subscription(tmp_path):
    """A closed panel must stop costing a queue the moment it says so, not at
    the next write that fails."""
    server, port = await running_server(tmp_path, [])
    reader, writer, _ = await open_live(port)
    await server_message(reader)                              # snapshot
    await server_message(reader)                              # heartbeat
    assert len(server.subscribers) == 1

    # A message the daemon has no use for, long enough for the two-byte length
    # form: the ping after it is only answered if that frame was read whole.
    writer.write(client_frame(0x1, b"y" * 300) + client_frame(0x9, b"still there?"))
    assert await server_message(reader) == (0x8A, b"still there?")

    writer.write(client_frame(0x8, (1000).to_bytes(2, "big")))
    assert await asyncio.wait_for(reader.read(), timeout=5) == b"\x88\x00"
    assert server.subscribers == set()
    writer.close()


@pytest.mark.asyncio
async def test_a_frame_too_long_for_the_page_to_send_ends_its_subscription(tmp_path):
    """The page sends nothing the daemon acts on; a frame that claims 70 KB is
    not waited for and buffered."""
    server, port = await running_server(tmp_path, [])
    reader, writer, _ = await open_live(port)
    await server_message(reader)                              # snapshot
    await server_message(reader)                              # heartbeat

    writer.write(bytes([0x81, 0x80 | 127]) + (70_000).to_bytes(8, "big"))
    assert await asyncio.wait_for(reader.read(), timeout=5) == b"\x88\x00"
    assert server.subscribers == set()
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


def post_json(port, path, body):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}?token={TOKEN}", data=body, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


async def page_timed_behind(tmp_path, ask, handler_name, slow_answer):
    """Serve the page while a slow route's handler holds its request open: -> the
    page's (status, seconds it took), and what the slow route answered."""
    import threading
    import time
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    # A thread event: a loop-side signal could not be delivered while the loop is blocked.
    started = threading.Event()

    def slow(*_):
        started.set()
        time.sleep(1.5)
        return slow_answer

    sidebar = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: PAYLOAD,
                      action_fn=lambda *a: None, **{handler_name: slow})
    port = await Server(sidebar).start()

    def page_while_busy():
        # Timed entirely off the loop: awaiting anything would wait for the loop too.
        assert started.wait(2)
        began = time.monotonic()
        status, _ = get(f"http://127.0.0.1:{port}/?token={TOKEN}")
        return status, time.monotonic() - began

    asked = asyncio.ensure_future(asyncio.to_thread(ask, port))
    timed = await asyncio.to_thread(page_while_busy)
    return timed, await asked


@pytest.mark.asyncio
async def test_a_slow_account_op_does_not_hold_up_other_requests(tmp_path):
    """A switch waits on Claude Code's locks and a token refresh for seconds; on
    the event loop that would stall every other request and the heartbeat, and
    the panel would flag itself stale in the middle of a switch."""
    (status, took), answered = await page_timed_behind(
        tmp_path, lambda port: post_json(port, "/accounts", b'{"op": "switch", "account_id": "acct-2"}'),
        "accounts_fn", {"id": "acct-2", "name": "home"})
    assert status == 200
    assert took < 0.5, f"the page waited {took:.2f}s behind the switch"
    assert answered == 200


@pytest.mark.asyncio
async def test_a_cold_activity_report_does_not_hold_up_other_requests(tmp_path):
    """A week's report reads every transcript written in it, for seconds the first time;
    on the event loop the heartbeat would stop and the panel flag itself stale."""
    (status, took), answered = await page_timed_behind(
        tmp_path, lambda port: get(f"http://127.0.0.1:{port}/activity?token={TOKEN}"),
        "activity_fn", {"generated_at": 1, "days": []})
    assert status == 200
    assert took < 0.5, f"the page waited {took:.2f}s behind the report"
    assert answered == (200, b'{"generated_at": 1, "days": []}')


@pytest.mark.asyncio
async def test_saving_an_api_key_does_not_hold_up_other_requests(tmp_path):
    """Saving a key waits on the API and the Keychain for up to ten seconds."""
    (status, took), answered = await page_timed_behind(
        tmp_path, lambda port: post_json(port, "/api-fallback", b'{"op": "not_now"}'), "api_fallback_fn", {})
    assert status == 200
    assert took < 0.5, f"the page waited {took:.2f}s behind the key check"
    assert answered == 200


async def update_over_http(tmp_path, result):
    """-> (response status, restarts requested) for one POST /update."""
    page = tmp_path / "page.html"
    page.write_text("<h1>agents</h1>")
    restarts = []
    sidebar = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: PAYLOAD,
                      action_fn=lambda *a: None, update_fn=lambda: result)
    server = Server(sidebar, restart_fn=lambda: restarts.append(True))
    port = await server.start()

    def post():
        request = urllib.request.Request(f"http://127.0.0.1:{port}/update?token={TOKEN}", data=b"", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as refused:
            return refused.code

    status = await asyncio.to_thread(post)
    await asyncio.sleep(0.05)
    return status, len(restarts)


@pytest.mark.asyncio
async def test_a_taken_update_restarts_the_daemon_after_answering(tmp_path):
    """The answer has to reach the page before the process goes: the page
    says "restarting, reopen the panel" from it."""
    assert await update_over_http(tmp_path, (True, "")) == (200, 1)


@pytest.mark.asyncio
async def test_a_failed_update_leaves_the_daemon_running(tmp_path):
    assert await update_over_http(tmp_path, (False, "fatal: no network\n")) == (409, 0)
