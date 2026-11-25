#!/usr/bin/env python3
# ABOUTME: The task line's two tools for a Codex session, task_begin and task_report, served over MCP on stdin and stdout.
# ABOUTME: Each call names its session in _meta.threadId; the rules and the locked write are task.py's.
"""Codex starts this from the entry install.sh adds to its config.toml:

    [mcp_servers.agents-sidebar]
    command = "python3"
    args = ["<plugin>/hooks-handlers/codex-task-tools.py"]

Newline-delimited JSON-RPC 2.0. A tool call writes the same note as
`task.py --session <id> begin|report`, through the same function, so the
two never disagree about the rules or race each other for the file.
"""
import json
import sys
import time

import task

SERVER = {"name": "agents-sidebar", "version": "1"}
PROTOCOL = "2025-06-18"
INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32600, -32601, -32602
#: What each tool tells Codex about itself: it writes (not read-only), only its own session's note (not destructive,
#: not open-world), and the same call twice leaves the card as one call does. Without them MCP's defaults apply,
#: destructive and open-world, and Codex 0.171.0 asked a person before every call.
ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": True}

TOOLS = [
    {"name": "task_begin",
     "annotations": ANNOTATIONS,
     "description": "Starts a new task on this session's Agents sidebar card: the title of the user's current request. "
                    "Replaces any task before it.",
     "inputSchema": {"type": "object", "required": ["title"], "properties": {
         "title": {"type": "string", "description": "A short title for the whole request, up to 80 characters."}}}},
    {"name": "task_report",
     "annotations": ANNOTATIONS,
     "description": "Reports progress on the current task to this session's Agents sidebar card. 100 marks it Complete "
                    "and locks it; more work needs task_begin.",
     "inputSchema": {"type": "object", "required": ["activity", "percent"], "properties": {
         "activity": {"type": "string", "description": 'Two to four words, such as "Reading code", up to 40 characters.'},
         "percent": {"type": ["integer", "null"], "minimum": 0, "maximum": 100,
                     "description": "Your estimate of the whole request in five-point steps, "
                                    "or null while the scope is unclear."}}}},
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


def summary(note):
    """One line for the model after a write: link.tsx's summary, word for word."""
    if note["done"]:
        return f"Task line: {note['title']} · Complete"
    if note["activity"] is None:
        return f"Task line: {note['title']}"
    percent = "?" if note["percent"] is None else note["percent"]
    return f"Task line: {note['title']} · {note['activity']} · {percent}%"


#: A percent the call left out, which task.report refuses as it does any value that is not one.
NOT_GIVEN = object()


def text_of(arguments, key):
    """The argument when it is a string, else the empty string task.py refuses: task-line.ts does the same."""
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def tool_result(text, error=False):
    """A tool's answer: a refusal is one the model reads, not a protocol error."""
    return {"content": [{"type": "text", "text": text}], "isError": error}


class InvalidParams(Exception):
    """A tools/call that names no tool of this server, or is not shaped as one: a protocol error, not a refusal."""


def tool_call(params):
    """A tools/call's params -> its result. Raises InvalidParams."""
    if not isinstance(params, dict):
        raise InvalidParams("invalid params: tools/call takes an object")
    if params.get("name") not in TOOL_NAMES:
        raise InvalidParams(f"unknown tool: {params.get('name')}")
    # Codex names the thread in every call's _meta; it is the session id the hooks see. Nothing promises one
    # server process per thread, so it is read from each call and never kept.
    meta = params.get("_meta")
    session = meta.get("threadId") if isinstance(meta, dict) else None
    if session is None:
        return tool_result("no session: the call carries no _meta.threadId", error=True)
    if not isinstance(session, str):
        return tool_result("session id must be a plain token", error=True)
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}

    def change(note):
        if params["name"] == "task_begin":
            return task.begin(text_of(arguments, "title"), time.time())
        # No percent is refused like a wrong one, as the Claude tool does: null is how to say unknown.
        return task.report(note, text_of(arguments, "activity"), arguments.get("percent", NOT_GIVEN), time.time())

    try:
        note = task.update_note(session, change)
    except ValueError as refusal:
        return tool_result(str(refusal), error=True)
    except OSError as error:
        return tool_result(f"the note could not be written: {error}", error=True)
    return tool_result(summary(note))


def answer(message):
    """One message, an object -> the reply to send, or None for a notification or a reply to us."""
    if "id" not in message:
        return None
    method = message.get("method")
    if not isinstance(method, str):
        return error_reply(message["id"], INVALID_REQUEST, "invalid request: no method")
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": SERVER}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            result = tool_call(message.get("params"))
        except InvalidParams as error:
            return error_reply(message["id"], INVALID_PARAMS, str(error))
    else:
        return error_reply(message["id"], METHOD_NOT_FOUND, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def error_reply(id, code, message):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def serve(lines, out, log):
    """Answer each line of `lines` (bytes) on `out` until the input ends. A line with no id to answer is
    reported on `log` and skipped."""
    for raw in lines:
        if not raw.strip():
            continue
        try:
            message = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            print("codex-task-tools.py: skipped a line that is not UTF-8", file=log, flush=True)
            continue
        except ValueError as error:
            print(f"codex-task-tools.py: skipped a line that is not JSON: {error}", file=log, flush=True)
            continue
        if not isinstance(message, dict):
            print(f"codex-task-tools.py: skipped a line that is not a JSON-RPC message: {json.dumps(message)}",
                  file=log, flush=True)
            continue
        reply = answer(message)
        if reply is not None:
            out.write(json.dumps(reply) + "\n")
            out.flush()


if __name__ == "__main__":
    serve(sys.stdin.buffer, sys.stdout, sys.stderr)
