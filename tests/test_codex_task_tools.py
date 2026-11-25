# ABOUTME: Drives the Codex task line's MCP server over stdin and stdout as Codex does, one JSON-RPC message a line,
# ABOUTME: with HOME in a temporary folder so every note it writes lands there.
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "plugin" / "hooks-handlers" / "codex-task-tools.py"
SESSION = "test-session"
HANDSHAKE = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "test-client", "version": "0"}}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"}]


def serve(home, *messages):
    """The server run to the end of its input, each message a line (bytes as they are, anything else as JSON)
    -> (exit code, its replies in order, stderr)."""
    lines = b"".join((m if isinstance(m, bytes) else json.dumps(m).encode()) + b"\n" for m in messages)
    done = subprocess.run([sys.executable, "-B", str(SERVER)], input=lines, capture_output=True,
                          timeout=20, env={"HOME": str(home), "PATH": os.environ["PATH"]})
    return (done.returncode, [json.loads(line) for line in done.stdout.decode().splitlines()],
            done.stderr.decode())


def call(id, name, arguments, meta=None):
    return {"jsonrpc": "2.0", "id": id, "method": "tools/call",
            "params": {"_meta": {"threadId": SESSION} if meta is None else meta, "name": name, "arguments": arguments}}


def text_result(id, text, error=False):
    return {"jsonrpc": "2.0", "id": id, "result": {"content": [{"type": "text", "text": text}], "isError": error}}


def note_of(home, session=SESSION):
    return json.loads((home / ".claude" / "agents-sidebar-tasks" / f"{session}.json").read_text())


def test_a_begin_then_a_report_writes_the_note_and_answers_with_the_task_line(tmp_path):
    before = int(time.time())
    code, replies, err = serve(tmp_path, *HANDSHAKE,
                               call(1, "task_begin", {"title": "Fix the login bug"}),
                               call(2, "task_report", {"activity": "Reading code", "percent": 35}))
    after = round(time.time())
    assert (code, err) == (0, "")
    assert replies == [
        {"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                               "serverInfo": {"name": "agents-sidebar", "version": "1"}}},
        text_result(1, "Task line: Fix the login bug"),
        text_result(2, "Task line: Fix the login bug · Reading code · 35%")]
    note = note_of(tmp_path)
    assert before <= note.pop("ts") <= after and len(note.pop("task")) == 32
    assert note == {"title": "Fix the login bug", "activity": "Reading code", "percent": 35, "done": False}


def test_the_tools_say_they_touch_nothing_but_their_own_note(tmp_path):
    """Codex asks a person before each call of a tool that says nothing of itself; these four keep it from asking,
    and are true of a tool that rewrites its own session's note and nothing else."""
    code, replies, err = serve(tmp_path, *HANDSHAKE, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert (code, err) == (0, "")
    tools = replies[1]["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["task_begin", "task_report"]
    assert [tool["annotations"] for tool in tools] == [
        {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True}] * 2
    assert tools[1]["inputSchema"]["required"] == ["activity", "percent"]
    assert tools[1]["inputSchema"]["properties"]["percent"]["type"] == ["integer", "null"]


@pytest.fixture
def server(monkeypatch, tmp_path):
    """The server's module loaded here, its notes under tmp_path/tasks: the shared cases set the clock per step."""
    monkeypatch.syspath_prepend(str(SERVER.parent))
    spec = importlib.util.spec_from_file_location("codex_task_tools", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.task, "TASKS_DIR", str(tmp_path / "tasks"))
    return module


# The cases task.py and the Claude tools answer to (tests/test_task.py, plugin/hooks/task.test.tsx).
CASES = json.loads((REPO / "plugin" / "hooks" / "task-cases.ts").read_text().split("export default ", 1)[1])


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_shared_cases_hold_for_the_server(case, server, tmp_path, monkeypatch):
    for i, step in enumerate(case["steps"]):
        monkeypatch.setattr(server.task.time, "time", lambda now=step["now"]: now)
        if step["verb"] == "begin":
            message = call(i, "task_begin", {"title": step["title"]})
        else:
            message = call(i, "task_report", {"activity": step["activity"], "percent": step["percent"]})
        reply = server.answer(message)
        if i == len(case["steps"]) - 1 and "error" in case:
            assert reply == text_result(i, case["error"], error=True)
        else:
            assert reply["result"]["isError"] is False, reply
    if "expect" in case:
        got = json.loads((tmp_path / "tasks" / f"{SESSION}.json").read_text())
        assert {key: got[key] for key in case["expect"]} == case["expect"]


def test_a_call_that_names_no_plain_session_is_refused_and_writes_nothing(tmp_path):
    """The session comes from each call, never from the process: one server can outlive a thread, and a
    threadId is the note's file name, so anything but a plain token could name a file elsewhere."""
    code, replies, err = serve(tmp_path, *HANDSHAKE,
                               call(1, "task_begin", {"title": "Fix"}, meta={}),
                               call(2, "task_begin", {"title": "Fix"}, meta={"sessionId": SESSION}),
                               call(3, "task_begin", {"title": "Fix"}, meta={"threadId": "../x"}),
                               call(4, "task_begin", {"title": "Fix"}, meta={"threadId": 7}),
                               {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                "params": {"name": "task_begin", "arguments": {"title": "Fix"}}})
    assert (code, err) == (0, "")
    missing = "no session: the call carries no _meta.threadId"
    assert replies[1:] == [text_result(1, missing, error=True), text_result(2, missing, error=True),
                           text_result(3, "session id must be a plain token", error=True),
                           text_result(4, "session id must be a plain token", error=True),
                           text_result(5, missing, error=True)]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("arguments, refusal", [
    ({"activity": "Reading", "percent": True}, "percent must be 0 to 100"),
    ({"activity": "Reading", "percent": 35.5}, "percent must be 0 to 100"),
    ({"activity": "Reading", "percent": "35"}, "percent must be 0 to 100"),
    ({"activity": "Reading"}, "percent must be 0 to 100"),
    ({"activity": 5, "percent": 35}, "activity is empty"),
    ({"percent": 35}, "activity is empty"),
], ids=["true", "a fraction", "a string", "no percent", "a number for activity", "no activity"])
def test_a_report_takes_its_arguments_as_the_claude_tool_does(arguments, refusal, server, tmp_path):
    """Untyped input from the model: anything but an integer or null is not a percent, and null is the only
    way to say unknown; anything but a string is no activity. task-line.ts refuses the same."""
    assert server.answer(call(1, "task_begin", {"title": "Fix"}))["result"]["isError"] is False
    before = (tmp_path / "tasks" / f"{SESSION}.json").read_text()
    assert server.answer(call(2, "task_report", arguments)) == text_result(2, refusal, error=True)
    assert (tmp_path / "tasks" / f"{SESSION}.json").read_text() == before


@pytest.mark.parametrize("arguments", [{"title": None}, {}, None], ids=["null", "no title", "no arguments"])
def test_a_begin_without_a_title_string_is_refused(arguments, server, tmp_path):
    message = call(1, "task_begin", {})
    message["params"]["arguments"] = arguments
    assert server.answer(message) == text_result(1, "title is empty", error=True)
    assert not (tmp_path / "tasks" / f"{SESSION}.json").exists()


def rpc_error(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def test_malformed_input_is_answered_where_it_can_be_and_the_server_goes_on(tmp_path):
    """A line that is not a request names no id to answer, so it is logged; one that does gets a JSON-RPC error.
    Either way the next call is served."""
    code, replies, err = serve(tmp_path, *HANDSHAKE,
                               b"not json", b"\xff\xfe", b"[1, 2]", b"",
                               {"jsonrpc": "2.0", "id": 1},
                               {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
                               {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": "task_begin"},
                               {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                "params": {"_meta": {"threadId": SESSION}, "name": "task_end", "arguments": {}}},
                               {"jsonrpc": "2.0", "id": 5, "method": "ping"},
                               call(6, "task_begin", {"title": "Fix"}))
    assert code == 0
    assert err.splitlines() == [
        "codex-task-tools.py: skipped a line that is not JSON: Expecting value: line 1 column 1 (char 0)",
        "codex-task-tools.py: skipped a line that is not UTF-8",
        "codex-task-tools.py: skipped a line that is not a JSON-RPC message: [1, 2]"]
    assert replies[1:] == [
        rpc_error(1, -32600, "invalid request: no method"),
        rpc_error(2, -32601, "method not found: resources/list"),
        rpc_error(3, -32602, "invalid params: tools/call takes an object"),
        rpc_error(4, -32602, "unknown tool: task_end"),
        {"jsonrpc": "2.0", "id": 5, "result": {}},
        text_result(6, "Task line: Fix")]
