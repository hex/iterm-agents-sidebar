"""Tests for request handling: auth, SSE framing, action dispatch."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import Sidebar

TOKEN = "lQuxAh5DplagEnuB_cy5XepFMk2v6-7m"  # shape of a real secrets.token_urlsafe(24)


def build(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<h1>sidebar</h1>")
    return Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: {"groups": []},
                   action_fn=lambda session_id, verb, text: None)


def test_wrong_token_is_refused(tmp_path):
    """The daemon binds 127.0.0.1, but any local process can reach that port.
    The token is the only thing separating this sidebar from a local
    "focus any terminal and type into it" API.
    """
    status, _, _ = build(tmp_path).handle("GET", "/?token=wrong", b"")
    assert status == 403


def test_correct_token_serves_the_page(tmp_path):
    status, content_type, body = build(tmp_path).handle("GET", f"/?token={TOKEN}", b"")
    assert (status, content_type) == (200, "text/html; charset=utf-8")
    assert b"<h1>sidebar</h1>" in body


def test_missing_token_is_refused(tmp_path):
    """No token at all, not merely a wrong one."""
    assert build(tmp_path).handle("GET", "/", b"")[0] == 403


def record(tmp_path):
    calls = []
    page = tmp_path / "page.html"
    page.write_text("x")
    server = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: {"groups": []},
                     action_fn=lambda session_id, verb, text: calls.append((session_id, verb, text)))
    return server, calls


def test_focus_verb_dispatches(tmp_path):
    server, calls = record(tmp_path)
    status, _, _ = server.handle(
        "POST", f"/action?token={TOKEN}",
        b'{"session_id": "D515C9B9-0424-4EAF-8F38-19C1957C266E", "verb": "focus"}')
    assert status == 200
    assert calls == [("D515C9B9-0424-4EAF-8F38-19C1957C266E", "focus", None)]


def test_send_verb_carries_its_text(tmp_path):
    server, calls = record(tmp_path)
    server.handle("POST", f"/action?token={TOKEN}",
                  b'{"session_id": "abc", "verb": "send", "text": "ls\\n"}')
    assert calls == [("abc", "send", "ls\n")]


def test_close_verb_dispatches(tmp_path):
    server, calls = record(tmp_path)
    status, _, _ = server.handle("POST", f"/action?token={TOKEN}",
                                 b'{"session_id": "abc", "verb": "close"}')
    assert status == 200
    assert calls == [("abc", "close", None)]


def test_bring_and_return_verbs_dispatch(tmp_path):
    server, calls = record(tmp_path)
    for verb in ("bring", "return"):
        status, _, _ = server.handle(
            "POST", f"/action?token={TOKEN}",
            ('{"session_id": "abc", "verb": "%s"}' % verb).encode())
        assert status == 200
    assert calls == [("abc", "bring", None), ("abc", "return", None)]


def test_answer_verb_carries_the_pick_and_its_question(tmp_path):
    server, calls = record(tmp_path)
    status, _, _ = server.handle("POST", f"/action?token={TOKEN}",
                                 b'{"session_id": "abc", "verb": "answer", "text": "{\\"pick\\": 2, \\"question\\": \\"Q?\\"}"}')
    assert status == 200
    assert calls == [("abc", "answer", '{"pick": 2, "question": "Q?"}')]


def test_unknown_verb_is_refused_and_dispatches_nothing(tmp_path):
    """There is a short fixed list of verbs. Anything else is refused rather than passed
    through -- the action_fn reaches the live iTerm2 API.
    """
    server, calls = record(tmp_path)
    status, _, _ = server.handle("POST", f"/action?token={TOKEN}",
                                 b'{"session_id": "abc", "verb": "split"}')
    assert status == 400
    assert calls == []


def test_sse_frame_is_one_data_line_terminated_by_a_blank_line(tmp_path):
    from sidebar import sse_frame
    assert sse_frame({"groups": []}) == b'data: {"groups": []}\n\n'


def test_sse_frame_survives_a_newline_in_the_payload(tmp_path):
    """A literal newline inside data would split one frame into two and
    desynchronise the stream. A session label can contain anything a directory
    name can, so this is reachable, not theoretical.
    """
    from sidebar import sse_frame
    frame = sse_frame({"label": "two\nlines"})
    assert frame.count(b"\n\n") == 1
    assert frame.endswith(b"\n\n")
    assert b"two\nlines" not in frame


def test_heartbeat_is_a_distinct_event(tmp_path):
    """The page counts heartbeats to decide when to paint everything STALE, so
    it must not confuse one with a snapshot.
    """
    from sidebar import heartbeat_frame
    assert heartbeat_frame(True).startswith(b"event: heartbeat\n")
    assert not heartbeat_frame(True).startswith(b"data:")


def test_parse_request_reads_the_request_line_and_content_length():
    from sidebar import parse_request
    raw = (b"POST /action?token=x HTTP/1.1\r\n"
           b"Host: 127.0.0.1:62155\r\n"
           b"Content-Length: 17\r\n\r\n")
    assert parse_request(raw) == ("POST", "/action?token=x", 17)


def test_parse_request_defaults_to_no_body():
    from sidebar import parse_request
    assert parse_request(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n") == ("GET", "/", 0)


def test_parse_request_survives_a_garbage_first_line():
    """WebKit is not the only thing that can reach this port. A malformed
    request must not take the daemon down with an unhandled exception.
    """
    from sidebar import parse_request
    assert parse_request(b"\x16\x03\x01garbage\r\n\r\n") == (None, None, 0)


def test_a_heartbeat_says_whether_the_data_behind_it_is_fresh():
    """The heartbeat proves the socket is alive. On its own that is exactly the
    plausible-old-data failure this panel exists to avoid: a stalled iTerm
    refresh kept every row and permission badge looking current forever, while
    poll() only printed the error. The frame now carries the verdict.
    """
    from sidebar import heartbeat_frame
    assert heartbeat_frame(True) == b'event: heartbeat\ndata: {"fresh": true}\n\n'
    assert heartbeat_frame(False) == b'event: heartbeat\ndata: {"fresh": false}\n\n'


def test_data_is_not_fresh_before_the_first_successful_rebuild():
    """Startup with a failing iTerm2: nothing has ever been read, so the panel
    must say so rather than show an empty list as though it were the truth.
    """
    from sidebar import rebuild_is_fresh
    assert rebuild_is_fresh(None, 100.0) is False


def test_data_is_fresh_while_rebuilds_keep_landing():
    from sidebar import rebuild_is_fresh, POLL_SECONDS
    assert rebuild_is_fresh(100.0, 100.0) is True
    assert rebuild_is_fresh(100.0, 100.0 + POLL_SECONDS) is True


def test_data_goes_unfresh_once_rebuilds_stop_landing():
    """Three poll intervals with nothing succeeding. Two consecutive failures
    are a stall, not a blip -- one is within the noise of a busy iTerm2.
    """
    from sidebar import rebuild_is_fresh, POLL_SECONDS
    assert rebuild_is_fresh(100.0, 100.0 + POLL_SECONDS * 3 + 0.1) is False


def accounts_server(tmp_path, result=None):
    calls = []
    page = tmp_path / "page.html"
    page.write_text("x")

    def accounts_fn(op, request):
        calls.append((op, request.get("account_id")))
        if isinstance(result, Exception):
            raise result
        return result

    server = Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: {"groups": []},
                     action_fn=lambda *a: None, accounts_fn=accounts_fn)
    return server, calls


def test_adding_the_live_account_dispatches_and_reports_its_name(tmp_path):
    server, calls = accounts_server(tmp_path, result={"id": "acct-1", "name": "Account 1"})
    status, _, body = server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "add"}')
    assert (status, json.loads(body)) == (200, {"ok": True, "account": {"id": "acct-1", "name": "Account 1"}})
    assert calls == [("add", None)]


def test_an_account_op_outside_the_allowlist_never_reaches_the_handler(tmp_path):
    server, calls = accounts_server(tmp_path)
    status, _, _ = server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "delete"}')
    assert status == 400
    assert calls == []


def test_a_refused_add_says_why(tmp_path):
    server, _ = accounts_server(tmp_path, result=ValueError("no login in Claude Code's config"))
    status, _, body = server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "add"}')
    assert (status, json.loads(body)) == (409, {"error": "no login in Claude Code's config"})


def test_account_ops_need_the_token(tmp_path):
    server, calls = accounts_server(tmp_path)
    assert server.handle("POST", "/accounts", b'{"op": "add"}')[0] == 403
    assert calls == []


def test_switching_names_the_account_to_switch_to(tmp_path):
    server, calls = accounts_server(tmp_path, result={"id": "acct-2", "name": "home"})
    status, _, _ = server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "switch", "account_id": "acct-2"}')
    assert status == 200
    assert calls == [("switch", "acct-2")]


def test_a_switch_without_an_account_never_reaches_the_handler(tmp_path):
    server, calls = accounts_server(tmp_path)
    assert server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "switch"}')[0] == 400
    assert calls == []


def test_a_refused_switch_says_why(tmp_path):
    from accounts import SwitchRefused
    server, _ = accounts_server(tmp_path, result=SwitchRefused("Claude Code is refreshing, try again"))
    status, _, body = server.handle("POST", f"/accounts?token={TOKEN}", b'{"op": "switch", "account_id": "acct-2"}')
    assert (status, json.loads(body)) == (409, {"error": "Claude Code is refreshing, try again"})


def test_renaming_passes_the_account_and_its_nickname(tmp_path):
    server, calls = accounts_server(tmp_path, result={"id": "acct-2", "name": "home"})
    status, _, _ = server.handle("POST", f"/accounts?token={TOKEN}",
                                 b'{"op": "rename", "account_id": "acct-2", "alias": "home"}')
    assert status == 200
    assert calls == [("rename", "acct-2")]


@pytest.mark.parametrize("body", [b'{"op": "rename", "alias": "home"}',
                                  b'{"op": "rename", "account_id": "acct-2"}',
                                  b'{"op": "rename", "account_id": "acct-2", "alias": 7}'])
def test_a_rename_without_an_account_or_a_text_nickname_never_reaches_the_handler(tmp_path, body):
    server, calls = accounts_server(tmp_path)
    assert server.handle("POST", f"/accounts?token={TOKEN}", body)[0] == 400
    assert calls == []


def test_notify_dispatches_the_moment_as_its_text(tmp_path):
    """The page reports what happened; the daemon decides whether to post."""
    server, calls = record(tmp_path)
    status, _, _ = server.handle(
        "POST", f"/action?token={TOKEN}",
        b'{"session_id": "abc", "verb": "notify", "text": "blocked"}')
    assert status == 200
    assert calls == [("abc", "notify", "blocked")]


def update_server(tmp_path, result):
    page = tmp_path / "page.html"
    page.write_text("x")
    return Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: {"groups": []},
                   action_fn=lambda *a: None, update_fn=lambda: result)


def test_an_update_that_took_says_so(tmp_path):
    status, _, body = update_server(tmp_path, (True, "")).handle("POST", f"/update?token={TOKEN}", b"")
    assert (status, json.loads(body)) == (200, {"ok": True})


def test_an_update_that_failed_carries_the_text_the_panel_shows(tmp_path):
    server = update_server(tmp_path, (False, "fatal: Not possible to fast-forward, aborting.\n"))
    status, _, body = server.handle("POST", f"/update?token={TOKEN}", b"")
    assert (status, json.loads(body)) == (409, {"error": "fatal: Not possible to fast-forward, aborting.\n"})


def test_an_update_needs_the_token(tmp_path):
    assert update_server(tmp_path, (True, "")).handle("POST", "/update", b"")[0] == 403


def test_a_daemon_without_an_updater_refuses_the_request(tmp_path):
    assert build(tmp_path).handle("POST", f"/update?token={TOKEN}", b"")[0] == 400


def statusline_server(tmp_path, install):
    page = tmp_path / "page.html"
    page.write_text("x")
    return Sidebar(token=TOKEN, page_path=page, snapshot_fn=lambda: {"groups": []},
                   action_fn=lambda *a: None, statusline_fn=install)


def test_installing_the_statusline_bridge_says_so(tmp_path):
    calls = []
    server = statusline_server(tmp_path, lambda: calls.append("install") or "cs-statusline")
    status, _, body = server.handle("POST", f"/statusline?token={TOKEN}", b"")
    assert (status, json.loads(body), calls) == (200, {"ok": True}, ["install"])


def test_a_refused_statusline_install_carries_the_reason(tmp_path):
    def refuse():
        raise ValueError("/Users/x/.claude/settings.json is not valid JSON; left unchanged")
    status, _, body = statusline_server(tmp_path, refuse).handle("POST", f"/statusline?token={TOKEN}", b"")
    assert (status, json.loads(body)) == (
        409, {"error": "/Users/x/.claude/settings.json is not valid JSON; left unchanged"})


def test_a_statusline_install_needs_the_token(tmp_path):
    assert statusline_server(tmp_path, lambda: "").handle("POST", "/statusline", b"")[0] == 403


def test_the_bridge_is_offered_only_while_missing_and_not_declined():
    from sidebar import statusline_offer
    assert statusline_offer("missing", {"offer_statusline": True}) is True
    assert statusline_offer("missing", {"offer_statusline": False}) is False
    assert statusline_offer("installed", {"offer_statusline": True}) is False
    # A settings.json that is not JSON cannot be installed into; offering
    # a button that can only refuse would be noise.
    assert statusline_offer("unreadable", {"offer_statusline": True}) is False
