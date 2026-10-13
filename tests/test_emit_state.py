"""Tests for the hook's event-to-state mapping.

Every case here comes from the hook trace captured 2026-09-07 in
~/.claude/agents-sidebar-events.jsonl across five real sessions.
"""
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "emit_state",
    Path(__file__).resolve().parent.parent / "plugin" / "hooks-handlers" / "emit-state.py")
emit_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emit_state)
state_for = emit_state.state_for


def test_a_submitted_prompt_means_working():
    assert state_for("UserPromptSubmit", {"prompt": "check prs"}) == "working"


def test_a_permission_request_means_blocked():
    assert state_for("PermissionRequest", {"tool_name": "Bash"}) == "blocked"


def test_the_permission_notification_also_means_blocked():
    """Traced: PermissionRequest is followed ~6s later by a Notification.
    Either alone must be enough, since one may be missed.
    """
    assert state_for("Notification", {"notification_type": "permission_prompt",
                                      "message": "Claude needs your permission"}) == "blocked"


def test_the_idle_notification_means_idle():
    """Traced in the `match` session with NO preceding Stop, so this cannot be
    treated as merely confirming a Stop that already arrived.
    """
    assert state_for("Notification", {"notification_type": "idle_prompt",
                                      "message": "Claude is waiting for your input"}) == "idle"


def test_an_unrecognised_notification_changes_nothing():
    """None means leave the variable alone. Guessing at an unknown notification
    would overwrite a state that was correct.
    """
    assert state_for("Notification", {"notification_type": "something_new"}) is None


def test_a_normal_stop_means_idle():
    assert state_for("Stop", {"stop_hook_active": False}) == "idle"


def test_a_stop_a_stop_hook_led_to_means_idle():
    """Claude Code sets stop_hook_active on every Stop of a turn a Stop hook
    kept going or a hook woke, the last one included: over 20 days of hook
    trace, 109 of the 111 turns a hook's wake started carried it on all their
    Stops.
    """
    assert state_for("Stop", {"stop_hook_active": True}) == "idle"


def test_a_turn_a_stop_hook_kept_going_ends_idle():
    """The traced shapes, each event read by state_for as the handler reads
    it: a Stop hook blocks the first Stop and the turn works on, or a hook
    wakes the session and every Stop of the turn carries the flag. Both end
    idle, and two Stops back to back read idle both times.
    """
    def run(events):
        doc = emit_state.blank_state()
        seen = []
        for event, payload in events:
            doc = emit_state.apply_event(doc, event, payload, state_for(event, payload))
            seen.append(emit_state.aggregate(doc))
        return seen

    blocked_then_worked = run([
        ("UserPromptSubmit", {"prompt": "go"}),
        ("Stop", {"stop_hook_active": False}),
        ("PreToolUse", {"tool_use_id": "t1"}),
        ("PostToolUse", {"tool_use_id": "t1"}),
        ("Stop", {"stop_hook_active": True}),
    ])
    assert blocked_then_worked == ["working", "idle", "working", "working", "idle"]

    woken = run([
        ("UserPromptSubmit", {"prompt": "<task-notification>"}),
        ("PreToolUse", {"tool_use_id": "t1"}),
        ("PostToolUse", {"tool_use_id": "t1"}),
        ("Stop", {"stop_hook_active": True}),
        ("Stop", {"stop_hook_active": True}),
    ])
    assert woken == ["working", "working", "working", "idle", "idle"]

    # A flagged Stop still leaves the turn working while a shell it started
    # runs on, and still bounds a question nobody answered.
    still_running = run([
        ("UserPromptSubmit", {"prompt": "<task-notification>"}),
        ("Stop", {"stop_hook_active": True,
                  "background_tasks": [{"type": "shell", "description": "pytest"}]}),
    ])
    assert still_running == ["working", "working"]

    doc = emit_state.blank_state()
    for event, payload in [
            ("UserPromptSubmit", {"prompt": "go"}),
            ("PreToolUse", {"tool_use_id": "q1", "tool_name": "AskUserQuestion"}),
            ("PermissionRequest", {"tool_name": "AskUserQuestion",
                                   "tool_input": {"questions": [{"question": "Which?", "options": []}]}}),
            ("Stop", {"stop_hook_active": True})]:
        doc = emit_state.apply_event(doc, event, payload, state_for(event, payload))
    assert (emit_state.aggregate(doc), doc["question"], emit_state.blocked_since(doc)) == ("idle", None, None)


def test_session_end_clears_the_variable():
    """Empty string clears, rather than leaving a dead session claiming a state
    forever. Distinct from None, which means leave it alone.
    """
    assert state_for("SessionEnd", {"reason": "prompt_input_exit"}) == ""


def test_there_is_no_error_state():
    """Deliberate. The Stop payload carries no exit reason, and the fourth
    state the user asked for could not be evidenced. No event maps to one.
    """
    mapped = {state_for(e, {"stop_hook_active": False}) for e in
              ("UserPromptSubmit", "PermissionRequest", "Stop", "SessionStart", "SessionEnd")}
    assert "error" not in mapped and "interrupted" not in mapped


def test_pid_lookup_of_a_tty_that_does_not_exist():
    """None, not a crash and not a wrong pid. The reader treats a missing pid
    as unknown, which is the honest answer when we cannot tell.
    """
    assert emit_state.agent_pid("/dev/ttys999", "claude") is None
    assert emit_state.agent_pid(None, "codex") is None


# `ps -t <tty> -o pid=,comm=` for a tmux pane running Codex, shaped as measured
# 2026-09-15: the node launcher, the native binary it starts, and the hook.
CODEX_PANE_PS = """\
51001 -zsh
51200 /Users/jane/.nvm/versions/node/v25.1.0/bin/node
51201 /Users/jane/.nvm/versions/node/v25.1.0/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex
51300 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python
"""


def test_the_codex_pid_is_the_native_binary_not_its_node_launcher():
    """The commands Codex runs, hooks included, are children of the binary."""
    assert emit_state.pid_named(CODEX_PANE_PS, "codex") == 51201


def test_a_codex_pane_has_no_claude_pid():
    assert emit_state.pid_named(CODEX_PANE_PS, "claude") is None


def test_the_claude_status_helper_is_not_claude():
    ps = "700 /usr/local/bin/claude-status\n701 /Users/jane/.local/bin/claude\n"
    assert emit_state.pid_named(ps, "claude") == 701


def test_codex_publishes_its_own_variable(tmp_path, monkeypatch):
    """A Codex pane may once have run Claude; separate variables keep a stale
    claudeState from being read as this session's."""
    monkeypatch.delenv("TMUX", raising=False)
    tty = tmp_path / "tty"
    tty.write_text("")
    emit_state.emit("x", str(tty), variable="codexState")
    assert "]1337;SetUserVar=codexState=eA==" in tty.read_text()


def test_codex_state_carries_its_model_and_rollout():
    """Codex has no statusline to bridge: the model comes from the hook
    payload and effort and context from the rollout the daemon reads."""
    payload = {"model": "gpt-6-astra",
               "transcript_path": "/Users/jane/.codex/sessions/2026/09/15/rollout-x.jsonl"}
    value = emit_state.published({"parent_active": True}, 51201, payload, codex=True, now=1789000000)
    assert value["state"] == "working"
    assert value["pid"] == 51201
    assert value["model"] == "gpt-6-astra"
    assert value["transcript_path"] == "/Users/jane/.codex/sessions/2026/09/15/rollout-x.jsonl"


def test_a_codex_hook_with_no_terminal_files_its_whole_state_with_its_directory(tmp_path):
    """Codex runs its hooks in an app-server daemon that can outlive the Codex
    that started it and serve the next one; from there no terminal is found,
    and a state that reaches no pane has to be filed where the panel looks,
    with the directory it pairs the pane by."""
    payload = {"session_id": "codex-1", "cwd": "/Users/jane/atlas", "model": "gpt-6-astra",
               "transcript_path": "/t"}
    value = emit_state.published({"parent_active": True}, None, payload, codex=True, now=1789000000)
    assert value["cwd"] == "/Users/jane/atlas"
    emit_state.file_whole(value, "codex-1", directory=str(tmp_path))
    assert json.loads((tmp_path / "codex-1.published").read_text()) == value


def test_claude_state_carries_no_codex_fields():
    value = emit_state.published({}, 701, {"model": "claude-opus-5", "transcript_path": "/t"},
                                 codex=False, now=1789000000)
    assert "model" not in value and "transcript_path" not in value
    assert value["state"] == "idle"


def test_a_tool_running_means_the_permission_prompt_was_answered():
    """There is no 'permission granted' event. Without this, blocked persisted
    until the next Stop or prompt -- minutes of the panel claiming a session
    needs you when it is already working again.

    A tool executing is proof the prompt is gone: nothing runs while one is up.
    """
    assert state_for("PostToolUse", {"tool_name": "Bash"}) == "working"


def test_a_compaction_starting_means_working():
    """Traced 2026-09-07: /compact emits no UserPromptSubmit, so both
    compactions in this session's log show the row sitting at idle for the
    whole churn. PreCompact is the only event that marks the work.
    """
    assert state_for("PreCompact", {"trigger": "manual"}) == "working"
    assert state_for("PreCompact", {"trigger": "auto"}) == "working"


def test_a_compaction_resume_still_means_idle():
    """Same as a fresh start for the state itself. What differs is the tally,
    below -- the state has to fall back to idle or a manual /compact would be
    stuck at working with no Stop coming to clear it.
    """
    assert state_for("SessionStart", {"source": "compact"}) == "idle"


def test_a_compaction_resume_is_not_a_fresh_start():
    """The subagent tally survives. An auto-compact fires mid-turn, so zeroing
    it drops the parent to idle while its subagents are still running.
    """
    assert emit_state.is_fresh_start("SessionStart", {"source": "compact"}) is False


def test_every_other_session_start_is_a_fresh_start():
    """A stale tally file left by a crashed session has to die on resume."""
    for source in ("startup", "resume", "clear", None):
        assert emit_state.is_fresh_start("SessionStart", {"source": source}) is True


def test_a_submitted_prompt_is_a_fresh_start():
    """A new turn starts from zero subagents regardless of the last one."""
    assert emit_state.is_fresh_start("UserPromptSubmit", {}) is True
    assert emit_state.is_fresh_start("PostToolUse", {}) is False


def test_a_tool_starting_means_working():
    """Traced 2026-09-07 on a subagent running the codex CLI: SessionStart ->
    idle, PostToolUse -> working, Stop -> idle, and then nothing at all for
    144s while it sat inside one long Bash call. Only PostToolUse was
    subscribed, so the row claimed idle for the whole run.

    A tool cannot start without the session doing something.
    """
    assert state_for("PreToolUse", {"tool_name": "Bash"}) == "working"


def test_the_state_variable_names_its_session():
    """The daemon keys the task note on the session id, and without the
    statusline bridge this variable is the only place it can learn it."""
    value = emit_state.published({}, 701, {"session_id": "abc-123"}, codex=False, now=1789000000)
    assert value["session"] == "abc-123"


def test_the_state_variable_keeps_the_turn_start_after_the_turn_ends():
    """working_since goes to None once the session is idle, but a Codex job
    that finished during the turn stays listed until the next prompt, so the
    daemon needs the prompt's time on its own."""
    doc = emit_state.apply_event(emit_state.blank_state(),
                                 "UserPromptSubmit", {}, "working")
    started = doc["turn_started"]
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle")
    value = emit_state.published(doc, 701, {"session_id": "abc-123"}, codex=False, now=1789000000)
    assert value["working_since"] is None and value["turn_started"] == round(started)


def test_a_session_with_no_prompt_yet_has_no_turn_start():
    value = emit_state.published({}, 701, {"session_id": "abc-123"}, codex=False, now=1789000000)
    assert value["turn_started"] is None


NOTE = {"task": "t1", "title": "Fix login", "activity": "Reading code",
        "percent": 35, "done": False, "ts": 1789000000}
SCRIPT = "/plugin/hooks-handlers/task.py"


def whisper(event, payload, note=None, now=1789000030, reminded=0):
    return emit_state.whisper(event, dict(payload, session_id="abc-123"), note, now, reminded, SCRIPT)


def test_a_prompt_gets_the_instructions_the_note_and_the_bound_commands():
    text = whisper("UserPromptSubmit", {"prompt": "fix it"}, NOTE)
    assert "--session abc-123 begin --title" in text
    assert "--session abc-123 report --activity" in text
    assert SCRIPT in text and '"title": "Fix login"' in text
    assert "five" in text.lower() and "100" in text


def test_a_prompt_without_a_note_says_so():
    assert "Current task: none" in whisper("UserPromptSubmit", {}, None)


def test_a_tool_boundary_nudges_only_when_the_last_report_is_a_minute_old():
    assert whisper("PostToolUse", {}, NOTE, now=NOTE["ts"] + 30) is None
    text = whisper("PostToolUse", {}, NOTE, now=NOTE["ts"] + 61)
    assert "check-in" in text.lower() and "--session abc-123" in text


def test_a_done_task_is_never_nudged():
    assert whisper("PostToolUse", {}, dict(NOTE, done=True), now=NOTE["ts"] + 999) is None


def test_a_recent_reminder_holds_the_next_one_back():
    assert whisper("PostToolUse", {}, NOTE, now=NOTE["ts"] + 120, reminded=NOTE["ts"] + 90) is None
    assert whisper("PostToolUse", {}, None, now=1789000200, reminded=1789000170) is None
    assert whisper("PostToolUse", {}, None, now=1789000200, reminded=1789000100) is not None


def test_subagents_and_the_report_itself_get_no_whisper():
    assert whisper("UserPromptSubmit", {"agent_id": "child"}, NOTE) is None
    assert whisper("PostToolUse", {"transcript_path": "/s/subagents/agent-1.jsonl"}, None, now=1789009999) is None
    assert whisper("PostToolUse", {"tool_input": {"command": f"python3 {SCRIPT} --session x report"}}, None,
                   now=1789009999) is None
    assert whisper("Stop", {}, None, now=1789009999) is None


def test_the_hook_prints_the_context_in_the_hook_protocol_shape():
    out = emit_state.hook_output("UserPromptSubmit", "do this")
    assert out == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "do this"}}
    assert emit_state.hook_output("PostToolUse", None) == {}


def test_a_reminder_is_remembered_in_the_state_document(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s9", "UserPromptSubmit", {}, "working")
    assert emit_state.read_state("s9")["reminded"] == 0
    emit_state.mark_reminded("s9", 1789000000)
    assert emit_state.read_state("s9")["reminded"] == 1789000000


def test_a_codex_run_inside_a_claude_tool_speaks_for_no_pane():
    """`codex exec` started by a Claude Bash tool inherits Claude Code's
    environment and shares the pane's tty. Its hooks would otherwise write a
    newer codexState over the Claude card, which then wore the OpenAI mark."""
    inside = lambda: [70001, 70000, 63630, 1]
    assert emit_state.nested_agent({"CLAUDECODE": "1", "CLAUDE_PID": "63630"}, True, inside) is True
    assert emit_state.nested_agent({"TERM": "xterm"}, True, inside) is False


def test_a_codex_daemon_started_from_a_claude_tool_still_speaks_for_its_pane():
    """Codex 0.159 runs hooks in a shared app-server daemon. One started by a
    codex run inside a Claude Bash tool keeps that tool's CLAUDECODE after the
    run ends and reparents to pid 1, then hosts the hooks of every later
    interactive Codex (seen 2026-10-01: a Codex card idle at a prompt)."""
    daemon = lambda: [45561, 1]
    assert emit_state.nested_agent({"CLAUDECODE": "1", "CLAUDE_PID": "5001"}, True, daemon) is False
    assert emit_state.nested_agent({"CLAUDECODE": "1"}, True, daemon) is False


def test_a_claude_hook_inside_claude_is_the_normal_case():
    """Claude Code's own hooks always run with CLAUDECODE set; that is not
    nesting, that is the session itself."""
    assert emit_state.nested_agent({"CLAUDECODE": "1", "CLAUDE_PID": "1"}, False, lambda: [1]) is False


ASK = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [
    {"question": "Which icon?", "header": "Icon", "multiSelect": False,
     "options": [{"label": "Dots", "description": "x"}, {"label": "Square", "description": "y"}]},
    {"question": "Which colour?", "header": "Colour", "multiSelect": False,
     "options": [{"label": "Blue", "description": ""}]},
]}}


def test_a_question_carries_its_first_question_and_option_labels():
    """The banner shows one question with its options as buttons; a second
    question is counted, and the card steps through the whole set."""
    assert emit_state.question_from(ASK) == {
        "header": "Icon", "question": "Which icon?",
        "options": ["Dots", "Square"], "multi": False, "more": 1,
        "set": [{"header": "Icon", "question": "Which icon?", "options": ["Dots", "Square"], "multi": False},
                {"header": "Colour", "question": "Which colour?", "options": ["Blue"], "multi": False}]}


def test_a_single_question_carries_no_set():
    one = {"tool_name": "AskUserQuestion", "tool_input": {"questions": ASK["tool_input"]["questions"][:1]}}
    assert "set" not in emit_state.question_from(one)


def test_any_other_gated_tool_names_itself_and_its_first_line():
    bash = {"tool_name": "Bash", "tool_input": {"command": "git push origin main\n&& echo ok"}}
    assert emit_state.question_from(bash) == {"tool": "Bash", "summary": "git push origin main"}
    edit = {"tool_name": "Edit", "tool_input": {"file_path": "/x/y.py", "old_string": "a"}}
    assert emit_state.question_from(edit) == {"tool": "Edit", "summary": "/x/y.py"}


def test_a_gate_that_says_why_carries_its_reason():
    """Codex puts the reason its escalation prompt shows in `description`, as
    Claude Code does its Bash description. Whitespace runs fold to one space."""
    bash = {"tool_name": "Bash", "tool_input": {"command": "python3 - <<'PY'\nimport os",
                                                "description": "Allow the status post\noutside the sandbox?"}}
    assert emit_state.question_from(bash) == {"tool": "Bash", "summary": "python3 - <<'PY'",
                                              "reason": "Allow the status post outside the sandbox?"}
    long = {"tool_name": "Bash", "tool_input": {"command": "x", "description": "y" * 400}}
    assert emit_state.question_from(long)["reason"] == "y" * 299 + "…"
    blank = {"tool_name": "Bash", "tool_input": {"command": "x", "description": "  "}}
    assert "reason" not in emit_state.question_from(blank)


def test_each_permission_gate_gets_its_own_id():
    """The card answers a gate by id: two gates with the same command are two
    gates, and a Notification echo of one keeps that gate's id."""
    gate = {"tool_name": "Bash", "tool_input": {"command": "make test"}}
    doc = emit_state.apply_event(emit_state.blank_state(), "PreToolUse", {"tool_use_id": "t1"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest", gate, "blocked")
    first = doc["question"]["id"]
    assert isinstance(first, str) and len(first) >= 12
    doc = emit_state.apply_event(doc, "Notification", {}, "blocked")
    assert doc["question"]["id"] == first
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working")
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t2"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest", gate, "blocked")
    assert doc["question"]["id"] != first


def test_a_gate_without_a_tool_has_no_question():
    assert emit_state.question_from({}) is None


def test_the_question_stands_with_its_gate_and_falls_with_it():
    """It is published beside blocked_since and cleared when the gates clear,
    so a banner can never offer buttons for a prompt that has gone."""
    doc = emit_state.blank_state()
    doc = emit_state.apply_event(doc, "PermissionRequest", {**ASK, "tool_use_id": "t1"}, "blocked")
    assert doc["question"]["question"] == "Which icon?"
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working")
    assert doc.get("question") is None


def test_the_question_survives_the_next_event_through_the_state_file(tmp_path, monkeypatch):
    """The permission_prompt Notification lands seconds after the
    PermissionRequest; the question has to come back off disk with it."""
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "PermissionRequest", {**ASK, "tool_use_id": "t1"}, "blocked")
    doc = emit_state.update("s1", "Notification", {"notification_type": "permission_prompt"}, "blocked")
    assert doc["question"]["question"] == "Which icon?"


def test_a_permission_notification_for_a_tool_that_already_ran_opens_no_gate():
    """Claude Code sends the permission_prompt Notification some seconds after
    the prompt opens, on its own clock, so it can land after the tool it was
    about has been approved and has finished. Traced on 2026-09-17: such a
    notification keyed a gate on the finished tool, which nothing could ever
    close, and the session read blocked through five minutes of work."""
    doc = emit_state.blank_state()
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t1"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest", {**ASK}, "blocked")
    assert emit_state.aggregate(doc) == "blocked"
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working")
    assert emit_state.aggregate(doc) == "working"
    doc = emit_state.apply_event(doc, "Notification", {"notification_type": "permission_prompt"}, "blocked")
    assert emit_state.aggregate(doc) == "working"
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t2"}, "working")
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t2"}, "working")
    assert emit_state.aggregate(doc) == "working"


def test_clearing_a_note_waits_for_a_report_in_progress(tmp_path, monkeypatch):
    import fcntl
    import threading
    monkeypatch.setattr(emit_state, "TASKS_DIR", str(tmp_path))
    (tmp_path / "s1.json").write_text('{"task": "x"}')
    holder = open(tmp_path / "s1.lock", "a")
    fcntl.flock(holder, fcntl.LOCK_EX)
    worker = threading.Thread(target=emit_state.clear_note, args=("s1",))
    worker.start()
    worker.join(0.3)
    assert worker.is_alive() and (tmp_path / "s1.json").exists()
    holder.close()
    worker.join(2)
    assert not (tmp_path / "s1.json").exists()


def _value(subagents):
    return {"state": "working", "pid": 100, "session": "s-1", "agents": subagents,
            "subagents": [{"id": f"a{n}", "type": "workflow-subagent", "name": f"verify:refute:file{n}.cs",
                           "since": 1789732485, "ended": None, "model": "claude-opus-5"}
                          for n in range(subagents)],
            "blocked_since": None, "working_since": 1789732000, "turn_started": 1789732000,
            "question": None, "ts": 1789733000}


def test_a_small_state_travels_whole_in_the_variable(tmp_path):
    import json
    value = _value(1)
    sent = emit_state.carried(value, "s-1", directory=str(tmp_path))
    assert json.loads(sent) == value
    assert list(tmp_path.iterdir()) == []


def test_two_subagents_already_go_to_disk(tmp_path):
    """The variable is written to the tty Claude Code is drawing on; a write
    the tty takes in pieces prints its tail as text. 632 bytes of base64
    for two subagents is over the line; one, at 444, is under it."""
    import json
    sent = emit_state.carried(_value(2), "s-1", directory=str(tmp_path))
    assert json.loads(sent)["detail"] is True and "subagents" not in json.loads(sent)
    assert json.loads((tmp_path / "s-1.published").read_text()) == _value(2)


def test_a_large_state_leaves_its_detail_on_disk_and_sends_the_rest(tmp_path):
    """A workflow's hundred subagents made a 28 KB variable on every event."""
    import base64, json
    value = _value(117)
    sent = emit_state.carried(value, "s-1", directory=str(tmp_path))
    assert len(base64.b64encode(sent.encode())) <= emit_state.VARIABLE_CEILING
    envelope = json.loads(sent)
    assert envelope == {"state": "working", "pid": 100, "session": "s-1", "agents": 117,
                        "blocked_since": None, "working_since": 1789732000,
                        "turn_started": 1789732000, "ts": 1789733000, "detail": True}
    assert json.loads((tmp_path / "s-1.published").read_text()) == value


def test_a_large_state_that_cannot_be_stored_says_its_detail_is_missing(tmp_path):
    import json
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    envelope = json.loads(emit_state.carried(_value(117), "s-1", directory=str(blocked)))
    assert envelope["detail"] is False and envelope["state"] == "working"
    assert "subagents" not in envelope


def test_a_long_question_is_clipped_and_its_options_keep_their_places():
    """The answer is sent as the option's number, so no option may be dropped."""
    ask = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{
        "header": "H" * 100, "question": "Q" * 1000, "multiSelect": False,
        "options": [{"label": "A" * 200}, {"label": "Rows"}, {"label": "B" * 200}]}]}}
    got = emit_state.question_from(ask)
    assert got["question"] == "Q" * 299 + "…"
    assert got["header"] == "H" * 39 + "…"
    assert got["options"] == ["A" * 59 + "…", "Rows", "B" * 59 + "…"]


def test_a_long_command_is_clipped_in_the_summary():
    got = emit_state.question_from({"tool_name": "Bash", "tool_input": {"command": "x" * 5000}})
    assert got == {"tool": "Bash", "summary": "x" * 199 + "…"}


def test_a_session_id_is_a_plain_token_or_the_event_has_none():
    """The id names the state file, the task note and the command the agent is
    handed, so one that carries a path or a shell word is no id."""
    session_of = emit_state.session_of
    assert session_of({"session_id": "0b9c4a52-7d1e-4c55-9a53-2f6f0c1d8e11"}) == "0b9c4a52-7d1e-4c55-9a53-2f6f0c1d8e11"
    for hostile in ("../outside", "/tmp/outside", "a b; rm -rf x", "", None, 7, ["s1"]):
        assert session_of({"session_id": hostile}) is None
    assert session_of({}) is None


def test_a_task_reminder_is_never_built_from_an_id_that_is_no_token():
    payload = {"session_id": "s1; touch /tmp/owned", "prompt": "go"}
    assert emit_state.whisper("UserPromptSubmit", payload, None, 1789000000, 0, "/x/task.py") is None


def test_a_tty_named_by_the_environment_must_be_a_terminal(tmp_path, monkeypatch):
    """The escape is written to whatever this returns, so a $TTY naming an
    ordinary writable file would have it overwritten."""
    target = tmp_path / "notes.txt"
    target.write_text("keep me")
    monkeypatch.setenv("TTY", str(target))
    assert emit_state.find_tty() != str(target)


def _task(directory, number, status, subject, doing=""):
    (directory / f"{number}.json").write_text(json.dumps(
        {"id": str(number), "subject": subject, "description": "", "activeForm": doing,
         "owner": "", "status": status, "blocks": [], "blockedBy": []}))


def test_a_task_list_is_named_by_the_environment_or_the_session():
    """cs names a session's list after the session; a bare Claude Code
    session writes to session-<first 8 hex of its id> (checked against 5
    lists in ~/.claude/tasks on 2026-09-22)."""
    assert emit_state.task_list_of({"CLAUDE_CODE_TASK_LIST_ID": "my-project"},
                                   "0b9c4a52-7d1e-4c55-9a53-2f6f0c1d8e11") == "my-project"
    assert emit_state.task_list_of({}, "0b9c4a52-7d1e-4c55-9a53-2f6f0c1d8e11") == "session-0b9c4a52"
    assert emit_state.task_list_of({}, None) is None
    assert emit_state.task_list_of({"CLAUDE_CODE_TASK_LIST_ID": "../x"}, "0b9c4a52-7d1e") is None


def test_open_tasks_are_the_pending_and_running_items_in_id_order(tmp_path):
    """A list is never pruned (one real list held 555 completed items against
    6 open), so completed items are left behind; a half-written file is
    skipped rather than costing the session its state."""
    _task(tmp_path, 10, "completed", "old")
    _task(tmp_path, 12, "pending", "Region editor: smoke test")
    _task(tmp_path, 3, "in_progress", "Registry flags", doing="Building the registry")
    (tmp_path / "13.json").write_text("{not json")
    (tmp_path / ".highwatermark").write_text("13")
    assert emit_state.open_tasks(str(tmp_path)) == [
        {"id": "3", "status": "in_progress", "subject": "Registry flags", "doing": "Building the registry"},
        {"id": "12", "status": "pending", "subject": "Region editor: smoke test", "doing": ""},
    ]
    assert emit_state.open_tasks(str(tmp_path / "missing")) == []


def test_a_task_subject_is_clipped(tmp_path):
    _task(tmp_path, 1, "pending", "x" * 1034)
    assert emit_state.open_tasks(str(tmp_path))[0]["subject"] == "x" * 239 + "…"


def test_the_published_state_carries_the_open_tasks_and_files_them_past_the_ceiling(tmp_path, monkeypatch):
    """Several tasks never fit the 512-byte variable, so they travel in the
    detail file with the subagents."""
    lists = tmp_path / "tasks"; (lists / "session-abc12345").mkdir(parents=True)
    for n in range(1, 7):
        _task(lists / "session-abc12345", n, "pending", f"Item number {n} with a subject of some length")
    monkeypatch.setattr(emit_state, "TASKS_DIR", str(lists))
    monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
    value = emit_state.published({}, 701, {"session_id": "abc12345-0000-4000-8000-000000000000"},
                                 codex=False, now=1789000000)
    assert [t["id"] for t in value["tasks"]] == ["1", "2", "3", "4", "5", "6"]
    envelope = json.loads(emit_state.carried(value, "abc12345-0000-4000-8000-000000000000", str(tmp_path / "state")))
    assert envelope["detail"] is True and "tasks" not in envelope
    whole = json.loads((tmp_path / "state" / "abc12345-0000-4000-8000-000000000000.published").read_text())
    assert whole["tasks"] == value["tasks"]


def test_a_codex_session_publishes_no_tasks():
    value = emit_state.published({}, 701, {"session_id": "abc-123", "model": "gpt-5"}, codex=True, now=1789000000)
    assert "tasks" not in value


def test_a_codex_prompt_is_answered_once_codex_issues_its_next_tool():
    """Traced 2026-09-29 over nine Codex gates: the approved command started
    2 to 34 s after the prompt, always before Codex's next PreToolUse, and
    nothing fired in the prompt window even when it lasted 34 s. Codex issues
    no new tool while its prompt is up, so the next one proves it answered;
    its PostToolUse alone left the card WAITING for the whole of a two-minute
    test run. Claude Code runs tools beside an open prompt, so there the same
    sequence stays blocked."""
    for codex, after in ((True, "working"), (False, "blocked")):
        doc = emit_state.blank_state()
        doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t1"}, "working", codex=codex)
        doc = emit_state.apply_event(doc, "PermissionRequest", {**ASK}, "blocked", codex=codex)
        assert emit_state.aggregate(doc) == "blocked"
        doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t2"}, "working", codex=codex)
        assert emit_state.aggregate(doc) == after, codex
        assert (doc["question"] is None) == (after == "working")


def _plan(*steps):
    """A Codex update_plan PostToolUse payload: (step, status) pairs."""
    return {"tool_name": "update_plan", "tool_use_id": "p",
            "tool_input": {"plan": [{"step": step, "status": status} for step, status in steps]}}


def test_a_codex_plan_publishes_its_open_steps_until_the_next_one():
    """Codex keeps its plan in the update_plan tool, not in files, so the
    hook holds the latest one and publishes its open steps as the session's
    tasks, in plan order, on every event after it."""
    doc = emit_state.blank_state()
    doc = emit_state.apply_event(doc, "PostToolUse", _plan(("Alpha step", "completed"),
                                 ("Beta step", "in_progress"), ("Gamma step", "pending")), "working", codex=True)
    for event, payload, said in (("PreToolUse", {"tool_name": "Bash", "tool_use_id": "b"}, "working"),
                                 ("Stop", {"stop_hook_active": False}, "idle")):
        doc = emit_state.apply_event(doc, event, payload, said, codex=True)
        assert emit_state.published(doc, 1, {}, codex=True, now=1)["tasks"] == [
            {"id": "2", "status": "in_progress", "subject": "Beta step", "doing": ""},
            {"id": "3", "status": "pending", "subject": "Gamma step", "doing": ""}], event


def test_a_new_codex_plan_replaces_the_last_and_a_finished_one_leaves_no_tasks():
    doc = emit_state.apply_event(emit_state.blank_state(), "PostToolUse",
                                 _plan(("Alpha step", "in_progress"), ("Beta step", "pending")), "working", codex=True)
    doc = emit_state.apply_event(doc, "PostToolUse", _plan(("Write it", "in_progress")), "working", codex=True)
    assert [t["subject"] for t in emit_state.published(doc, 1, {}, codex=True, now=1)["tasks"]] == ["Write it"]
    doc = emit_state.apply_event(doc, "PostToolUse", _plan(("Write it", "completed")), "working", codex=True)
    assert "tasks" not in emit_state.published(doc, 1, {}, codex=True, now=1)


def test_a_malformed_codex_plan_publishes_only_the_steps_it_can_read():
    """Each malformed step is skipped, and a plan that is not a list keeps
    nothing; the hook never fails on what the model sent."""
    doc = emit_state.blank_state()
    for tool_input in (None, "a plan", {"plan": "Alpha"}, {"plan": [None, 3, {"step": "No status"},
                                                                     {"step": "", "status": "pending"},
                                                                     {"step": 7, "status": "pending"},
                                                                     {"step": "Odd", "status": "blocked"}]}):
        doc = emit_state.apply_event(doc, "PostToolUse", {"tool_name": "update_plan", "tool_input": tool_input},
                                     "working", codex=True)
        assert "tasks" not in emit_state.published(doc, 1, {}, codex=True, now=1), tool_input
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_name": "update_plan", "tool_input": {"plan": [
        {"step": "Kept", "status": "pending"}, "junk", {"step": "Also kept", "status": "in_progress"}]}},
        "working", codex=True)
    assert emit_state.published(doc, 1, {}, codex=True, now=1)["tasks"] == [
        {"id": "1", "status": "pending", "subject": "Kept", "doing": ""},
        {"id": "3", "status": "in_progress", "subject": "Also kept", "doing": ""}]


def test_a_codex_step_is_cut_to_the_subject_limit():
    doc = emit_state.apply_event(emit_state.blank_state(), "PostToolUse",
                                 _plan(("x" * 1000, "pending")), "working", codex=True)
    subject = emit_state.published(doc, 1, {}, codex=True, now=1)["tasks"][0]["subject"]
    assert len(subject) == emit_state.SUBJECT_MAX and subject.endswith("…")


def test_the_state_counts_the_tools_started_and_not_finished():
    """Codex runs tools side by side, so the newest one finishing says
    nothing of an older one still running; each is counted until its own
    end, and a turn ending drops whatever was left."""
    doc = emit_state.blank_state()
    for event, tool in (("PreToolUse", "t1"), ("PreToolUse", "t2"), ("PostToolUse", "t2")):
        doc = emit_state.apply_event(doc, event, {"tool_use_id": tool}, "working", codex=True)
    assert emit_state.published(doc, 1, {}, codex=True, now=1)["tools_running"] == 1
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working", codex=True)
    assert emit_state.published(doc, 1, {}, codex=True, now=1)["tools_running"] == 0
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t3"}, "working", codex=True)
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle", codex=True)
    assert emit_state.published(doc, 1, {}, codex=True, now=1)["tools_running"] == 0


def test_the_card_asks_what_the_gates_still_open_ask():
    """Two prompts open, the newer answered first: the card goes back to the
    older one's question, never the closed one's."""
    doc = emit_state.blank_state()
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t1"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_name": "Bash", "tool_input": {"command": "make test"}}, "blocked")
    older = doc["question"]["id"]
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "t2"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "blocked")
    newer = doc["question"]["id"]
    assert doc["question"] == {"tool": "Bash", "summary": "git push", "id": newer}
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t2"}, "working")
    assert doc["question"] == {"tool": "Bash", "summary": "make test", "id": older}
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working")
    assert doc["question"] is None


def test_each_gates_question_survives_the_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "PreToolUse", {"tool_use_id": "t1"}, "working")
    doc = emit_state.update("s1", "PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "make test"}}, "blocked")
    older = doc["question"]["id"]
    emit_state.update("s1", "PreToolUse", {"tool_use_id": "t2"}, "working")
    emit_state.update("s1", "PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "blocked")
    doc = emit_state.update("s1", "PostToolUse", {"tool_use_id": "t2"}, "working")
    assert doc["question"] == {"tool": "Bash", "summary": "make test", "id": older}


def test_tools_still_running_survive_the_state_file(tmp_path, monkeypatch):
    """Each hook event is its own process, so the count lives on disk."""
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "PreToolUse", {"tool_use_id": "t1"}, "working", codex=True)
    doc = emit_state.update("s1", "PreToolUse", {"tool_use_id": "t2"}, "working", codex=True)
    assert emit_state.published(doc, 1, {}, codex=True, now=1)["tools_running"] == 2


def test_the_state_variable_says_when_the_session_last_went_idle():
    """A turn that ends leaves the time it ended; a prompt that starts the
    next turn leaves it standing, since the panel orders a card that has
    worked for only a moment by the rest it came from."""
    doc = emit_state.apply_event(emit_state.blank_state(), "UserPromptSubmit", {}, "working")
    assert emit_state.published(doc, 701, {}, codex=False, now=1789000000)["idle_since"] is None
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle")
    rested = emit_state.published(doc, 701, {}, codex=False, now=1789000000)["idle_since"]
    assert isinstance(rested, int) and abs(rested - time.time()) < 5
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_name": "Bash"}, "working")
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_name": "Bash"}, "working")
    assert emit_state.published(doc, 701, {}, codex=False, now=1789000000)["idle_since"] == rested
    doc = emit_state.apply_event(doc, "UserPromptSubmit", {}, "working")
    assert emit_state.published(doc, 701, {}, codex=False, now=1789000000)["idle_since"] == rested


def test_a_rest_that_goes_on_keeps_its_start():
    doc = emit_state.apply_event(emit_state.blank_state(), "UserPromptSubmit", {}, "working")
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle")
    doc["idle_since"] = 1788999000.5
    doc = emit_state.apply_event(doc, "Notification", {"notification_type": "idle_prompt"}, "idle")
    assert emit_state.published(doc, 701, {}, codex=False, now=1789000000)["idle_since"] == 1788999000


def test_a_filed_rest_survives_the_next_event(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s-9", "UserPromptSubmit", {}, "working")
    emit_state.update("s-9", "Stop", {"stop_hook_active": False}, "idle")
    rested = emit_state.read_state("s-9")["idle_since"]
    assert isinstance(rested, float)
    assert emit_state.update("s-9", "PreToolUse", {"tool_name": "Bash"}, "working")["idle_since"] == rested


HANDLER = Path(__file__).resolve().parent.parent / "plugin" / "hooks-handlers" / "emit-state.py"
SET_VAR = re.compile(rb"\]1337;SetUserVar=(\w+)=([A-Za-z0-9+/=]*)")
OMP_SESSION = "019a0c5e-7d1e-7c55-9a53-2f6f0c1d8e11"


def run_handler(home, args, payload, env=None):
    """Run the handler as an agent does, with a real terminal named by $TTY.
    -> (exit code, stdout, [(variable, value)] written to the terminal)."""
    leader, follower = os.openpty()
    try:
        done = subprocess.run([sys.executable, "-B", str(HANDLER), *args], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=20,
                              env={"HOME": str(home), "PATH": os.environ["PATH"],
                                   "TTY": os.ttyname(follower), **(env or {})})
        os.set_blocking(leader, False)
        written = b""
        try:
            while chunk := os.read(leader, 65536):
                written += chunk
        except BlockingIOError:
            pass
    finally:
        os.close(leader)
        os.close(follower)
    return done.returncode, done.stdout, [(name.decode(), base64.b64decode(value).decode())
                                          for name, value in SET_VAR.findall(written)]


def test_an_omp_event_publishes_omp_state_with_the_pid_omp_sent(tmp_path):
    """omp's process is bun, so no process name finds it: its extension sends
    its own pid. It reads no hook output, so nothing goes to stdout."""
    code, out, written = run_handler(tmp_path, ["UserPromptSubmit", "--agent", "omp"],
                                     {"session_id": OMP_SESSION, "pid": 4242})
    assert (code, out) == (0, "")
    assert [name for name, _ in written] == ["ompState"]
    value = json.loads(written[0][1])
    assert (value["state"], value["pid"], value["session"]) == ("working", 4242, OMP_SESSION)


def test_omp_state_carries_no_claude_task_list(tmp_path):
    """A Claude session's list is found by its id's first eight characters;
    an omp session's id would name a list that is not its own."""
    listed = tmp_path / ".claude" / "tasks" / f"session-{OMP_SESSION[:8]}"
    listed.mkdir(parents=True)
    _task(listed, 1, "in_progress", "Somebody else's task")
    _, _, written = run_handler(tmp_path, ["UserPromptSubmit", "--agent", "omp"],
                                {"session_id": OMP_SESSION, "pid": 4242})
    assert "tasks" not in json.loads(written[0][1])


def omp_states(home, *events):
    """Each (event, payload) through the handler as omp's extension sends it
    -> the state published after each."""
    states = []
    for event, payload in events:
        _, _, written = run_handler(home, [event, "--agent", "omp"],
                                    {"session_id": OMP_SESSION, "pid": 4242, **payload})
        value = json.loads(written[0][1]) if written[0][1] else {}
        states.append((value.get("state"), value.get("question")))
    return states


def test_an_omp_ask_reads_blocked_with_its_question_until_the_tool_ends(tmp_path):
    asked = {"questions": [{"header": "Scope", "question": "Which branch?",
                            "options": [{"label": "main"}, {"label": "dev"}], "multiSelect": False}]}
    states = omp_states(
        tmp_path,
        ("UserPromptSubmit", {}),
        ("Notification", {"notification_type": "permission_prompt", "tool_use_id": "call_1",
                          "tool_name": "AskUserQuestion", "tool_input": asked}),
        ("PostToolUse", {"tool_use_id": "call_1"}),
        ("Stop", {}))
    assert states == [("working", None),
                      ("blocked", {"header": "Scope", "question": "Which branch?",
                                   "options": ["main", "dev"], "multi": False, "more": 0}),
                      ("working", None),
                      ("idle", None)]


def test_an_omp_approval_stands_through_another_tool_starting(tmp_path):
    """omp runs a batch of tools side by side, so a tool starting proves
    nothing about a prompt still open: only the gated tool's own end does."""
    states = omp_states(
        tmp_path,
        ("UserPromptSubmit", {}),
        ("PreToolUse", {"tool_use_id": "call_1", "tool_name": "bash"}),
        ("PermissionRequest", {"tool_use_id": "call_1", "tool_name": "bash",
                               "tool_input": {"command": "git push"}}),
        ("PreToolUse", {"tool_use_id": "call_2", "tool_name": "read"}),
        ("PostToolUse", {"tool_use_id": "call_1"}))
    assert [state for state, _ in states] == ["working", "working", "blocked", "blocked", "working"]
    assert {k: v for k, v in states[2][1].items() if k != "id"} == {"tool": "bash", "summary": "git push"}


def test_omps_beat_through_a_quiet_turn_keeps_its_clock_and_its_open_prompt(tmp_path):
    """The extension's beat is a tool start naming no tool: it says the turn
    is still working and changes nothing else."""
    def published(event, payload):
        _, _, written = run_handler(tmp_path, [event, "--agent", "omp"],
                                    {"session_id": OMP_SESSION, "pid": 4242, **payload})
        return json.loads(written[0][1])
    started = published("UserPromptSubmit", {})["turn_started"]
    asked = published("PermissionRequest", {"tool_use_id": "call_1", "tool_name": "bash"})
    beat = published("PreToolUse", {})
    assert (beat["state"], beat["turn_started"], beat["question"]) == ("blocked", started, asked["question"])
    closed = published("PostToolUse", {"tool_use_id": "call_1"})
    beat = published("PreToolUse", {})
    assert (closed["state"], beat["state"], beat["turn_started"]) == ("working", "working", started)


def test_an_agent_the_handler_does_not_know_publishes_nothing(tmp_path):
    for args in (["UserPromptSubmit", "--agent", "aider"], ["UserPromptSubmit", "--agent"]):
        assert run_handler(tmp_path, args, {"session_id": OMP_SESSION, "pid": 4242}) == (0, "", [])


def test_an_omp_event_without_a_usable_pid_publishes_nothing(tmp_path):
    for pid in (None, 0, -1, "4242", 4242.0, True):
        assert run_handler(tmp_path, ["Stop", "--agent", "omp"],
                           {"session_id": OMP_SESSION, "pid": pid}) == (0, "", [])


def drop(folder, link, role, text, expires=2000.0):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / f"ask-{link}.json").write_text(json.dumps(
        {"link": link, "nonce": "n" * 16, "role": role, "text": text, "expires": expires}))


def test_a_codex_prompt_takes_its_asks_and_deliveries_once(tmp_path):
    folder = tmp_path / "s1"
    drop(folder, "L1", "ask", "Write your latest result ... (link nnnn)")
    drop(folder, "L2", "deliver", "A report from ... (link nnnn)")
    text = emit_state.link_context("s1", 1000.0, root=tmp_path)
    assert text == "Write your latest result ... (link nnnn)\n\nA report from ... (link nnnn)"
    assert sorted(p.name for p in folder.iterdir()) == ["started-L2.json", "taken-L1.json", "taken-L2.json"]
    assert oct((folder / "started-L2.json").stat().st_mode & 0o777) == "0o600"
    assert emit_state.link_context("s1", 1001.0, root=tmp_path) is None


def test_an_expired_or_unreadable_drop_is_left_for_the_daemon(tmp_path):
    folder = tmp_path / "s1"
    drop(folder, "L1", "ask", "late", expires=999.0)
    (folder / "ask-L2.json").write_text('{"link": "L2", "ro')
    (folder / "ask-L3.json").write_text('{"link": "L3", "text": "x", "expires": "later"}')
    assert emit_state.link_context("s1", 1000.0, root=tmp_path) is None
    assert sorted(p.name for p in folder.iterdir()) == ["ask-L1.json", "ask-L2.json", "ask-L3.json"]


def test_no_folder_or_a_bad_session_id_gives_nothing(tmp_path):
    assert emit_state.link_context("s1", 1000.0, root=tmp_path) is None
    assert emit_state.link_context("../x", 1000.0, root=tmp_path) is None


def test_a_codex_prompt_hands_its_link_drop_to_codex_after_the_task_line(tmp_path):
    session = "019a0c5e-7d1e-7c55-9a53-2f6f0c1d8e22"
    drop(tmp_path / ".claude" / "agents-sidebar-links" / session, "L1", "deliver",
         "A report from the session “alpha” ... (link nnnn)", expires=time.time() + 600)
    # The task line is told only where the panel runs: its endpoint file says so.
    endpoint = tmp_path / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text("{}")
    code, out, _ = run_handler(tmp_path, ["UserPromptSubmit", "--codex"], {"session_id": session})
    instructions = (HANDLER.parent / "task-instructions.md").read_text().strip()
    bound = f"python3 {HANDLER.parent / 'task.py'} --session {session}"
    assert code == 0
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": (
        f"{instructions}\n\nCurrent task: none\n\nCommands:\n"
        f"{bound} begin --title 'Task title'\n"
        f"{bound} report --activity 'Reading code' --percent 25\n"
        f"{bound} report --activity 'Assessing task' --unknown\n"
        "\n\nA report from the session “alpha” ... (link nnnn)")}}


def test_the_published_state_says_which_machine_and_folder_it_is_from(monkeypatch):
    monkeypatch.setattr(emit_state.socket, "gethostname", lambda: "box.example.com")
    value = emit_state.published({}, 701, {"session_id": "abc-123", "cwd": "/srv/app"},
                                 codex=False, now=1789000000, tasks=False, front=True)
    assert (value["host"], value["front"], value["cwd"]) == ("box", True, "/srv/app")


def test_the_agent_is_in_front_when_its_group_is_its_terminals_foreground_group():
    assert emit_state.front_of(" 4321  4321\n") is True
    assert emit_state.front_of(" 4400  4321\n") is False


def test_a_process_with_no_terminal_or_no_listing_is_not_known_to_be_in_front():
    assert emit_state.front_of("    0  4321\n") is False
    assert emit_state.front_of("") is None
    assert emit_state.front_of("garbage\n") is None


def test_the_variable_is_written_without_spaces(tmp_path):
    assert emit_state.carried({"state": "idle", "pid": 7}, "s-1", str(tmp_path)) == '{"state":"idle","pid":7}'


def _over_the_ceiling(cwd):
    return {"state": "blocked", "pid": 31432, "session": "0f0e0d0c-0b0a-4a09-8807-060504030201",
            "agents": 1, "subagents": [{"id": "a" * 40, "type": "general-purpose"}] * 6,
            "blocked_since": 1791700000, "working_since": 1791699000, "turn_started": 1791699000,
            "idle_since": None, "question": None, "ts": 1791700000, "tasks": [],
            "host": "box", "front": True, "cwd": cwd}


def test_an_envelope_keeps_host_front_and_folder_under_the_ceiling(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/srv/app"), "s-1", str(tmp_path))
    envelope = json.loads(text)
    assert (envelope["host"], envelope["front"], envelope["cwd"], envelope["detail"]) == ("box", True, "/srv/app", True)
    assert len(base64.b64encode(text.encode())) <= 512


def test_a_long_folder_is_cut_to_its_last_two_parts(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/" + "/".join(["deep"] * 60) + "/projects/some-repo"),
                              "s-1", str(tmp_path))
    assert json.loads(text)["cwd"] == "projects/some-repo"
    assert len(base64.b64encode(text.encode())) <= 512


def test_a_folder_too_long_even_cut_is_left_out(tmp_path):
    text = emit_state.carried(_over_the_ceiling("/a/" + "x" * 300 + "/" + "y" * 300), "s-1", str(tmp_path))
    assert "cwd" not in json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512


ASKED = {"header": "First slice", "question": "What should the first slice be?",
         "options": ["State over the pane (Recommended)", "Relay from the start", "Bug fix only first"],
         "multi": False, "more": 0}


def test_a_question_that_fits_travels_whole_with_when_it_was_raised():
    assert json.loads(emit_state.question_short(ASKED, 1791700000)) == dict(ASKED, since=1791700000)


def test_a_long_question_keeps_every_option_and_fits():
    asked = dict(ASKED, question="q" * 300, options=["a" * 60, "b" * 60, "c" * 60, "d" * 60])
    text = emit_state.question_short(asked, 1791700000)
    carried = json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512
    assert [label[0] for label in carried["options"]] == ["a", "b", "c", "d"]
    assert len({len(label) for label in carried["options"]}) == 1
    assert carried["question"].startswith("q") and carried["since"] == 1791700000


def test_options_that_cannot_all_be_carried_send_no_question():
    """An answer is a number: a missing option would renumber the rest."""
    assert emit_state.question_short(dict(ASKED, options=["x" * 60] * 60), 1791700000) is None


def test_a_set_or_a_multi_select_sends_no_question():
    assert emit_state.question_short(dict(ASKED, more=1, set=[ASKED, ASKED]), 1791700000) is None
    assert emit_state.question_short(dict(ASKED, multi=True), 1791700000) is None


def test_a_tool_approval_keeps_its_id_and_drops_its_reason():
    asked = {"tool": "Bash", "summary": "git push " + "x" * 400, "reason": "y" * 300, "id": "f" * 32}
    text = emit_state.question_short(asked, 1791700000)
    carried = json.loads(text)
    assert len(base64.b64encode(text.encode())) <= 512
    assert (carried["tool"], carried["id"], carried["since"]) == ("Bash", "f" * 32, 1791700000)
    assert carried["summary"].startswith("git push ") and "reason" not in carried


def test_a_new_question_is_written_once():
    text, sent = emit_state.question_write(None, ASKED, 1791700000)
    assert json.loads(text)["since"] == 1791700000 and sent == emit_state.written(text)
    assert emit_state.question_write(sent, ASKED, 1791700000) == (None, sent)


def test_a_second_gate_opened_while_the_first_stands_replaces_the_question():
    """The newest gate's question stands, but the oldest gate's time is the state's blocked_since:
    told apart by time alone, the first question's buttons would stay up over the second."""
    _, sent = emit_state.question_write(None, ASKED, 1791700000)
    second = dict(ASKED, question="And the second?", options=["Yes", "No"])
    text, sent_after = emit_state.question_write(sent, second, 1791700000)
    assert json.loads(text)["question"] == "And the second?" and sent_after != sent


def test_a_question_gone_clears_the_variable_once():
    assert emit_state.question_write("0123456789abcdef", None, None) == ("", None)
    assert emit_state.question_write(None, None, None) == (None, None)


def test_a_question_that_cannot_be_carried_clears_what_stood():
    assert emit_state.question_write("0123456789abcdef", dict(ASKED, multi=True), 1791700999) == ("", None)


def test_the_question_reaches_the_terminal_before_the_state_that_names_it(tmp_path):
    """The panel reads on the state's arrival; the question must already be there."""
    payload = {"session_id": "abc-123", "tool_name": "AskUserQuestion", "tool_use_id": "t1",
               "tool_input": {"questions": [{"header": "Pick", "question": "Which one?",
                                             "options": [{"label": "This"}, {"label": "That"}]}]}}
    _, _, written = run_handler(tmp_path, ["PermissionRequest"], payload)
    names = [name for name, _ in written]
    assert names == ["claudeQuestion", "claudeState"]
    question = json.loads(dict(written)["claudeQuestion"])
    state = json.loads(dict(written)["claudeState"])
    assert question["options"] == ["This", "That"] and question["since"] == state["blocked_since"]


def test_a_machine_with_no_panel_gets_no_task_line_instructions(tmp_path):
    _, out, _ = run_handler(tmp_path, ["UserPromptSubmit"], {"session_id": "abc-123", "prompt": "hi"})
    assert "additionalContext" not in out


def test_a_machine_with_a_panel_gets_them(tmp_path):
    endpoint = tmp_path / ".local" / "share" / "agents-sidebar" / "endpoint.json"
    endpoint.parent.mkdir(parents=True)
    endpoint.write_text("{}")
    _, out, _ = run_handler(tmp_path, ["UserPromptSubmit"], {"session_id": "abc-123", "prompt": "hi"})
    assert "Current task: none" in out


CODEX_SESSION = "01a135bf-0000-7000-8000-00000000c0de"


def _rollout(tmp_path, *turns):
    """A Codex rollout holding one turn_context line per (turn id, reviewer, approval policy)."""
    path = tmp_path / "rollout.jsonl"
    path.write_text("".join(json.dumps({"timestamp": "2026-01-01T00:00:00.000Z", "type": "turn_context", "payload": {
        "turn_id": turn, "approvals_reviewer": reviewer, "approval_policy": policy}}, separators=(",", ":")) + "\n"
        for turn, reviewer, policy in turns))
    return str(path)


def _codex_gate(tmp_path, rollout, turn="t1", tool="Bash"):
    """The state a Codex session publishes on a PermissionRequest of `turn` for `tool`."""
    code, _, written = run_handler(tmp_path, ["PermissionRequest", "--codex"], {
        "session_id": CODEX_SESSION, "transcript_path": rollout, "turn_id": turn, "tool_name": tool,
        "tool_input": {"command": "python3 probe.py", "description": "Allow a probe"}})
    assert code == 0
    [state] = [json.loads(value) for name, value in written if name == "codexState"]
    return state["state"], state.get("question")


def test_a_codex_command_its_own_reviewer_rules_on_does_not_wait_on_you(tmp_path):
    """With approvals_reviewer auto_review Codex hands a command to a reviewer agent and stops for no one, but
    fires PermissionRequest all the same: the card said WAITING, with Yes and No, for the seconds the review took."""
    assert _codex_gate(tmp_path, _rollout(tmp_path, ("t1", "auto_review", "on-request"))) == ("working", None)


def test_only_a_command_is_known_to_go_to_codex_s_reviewer(tmp_path):
    """Codex still brings some approvals to the person under Auto-review, an app's for Computer Use among them,
    and nothing measured says which tools those arrive as. Any tool but the shell keeps its gate."""
    reviewed = _rollout(tmp_path, ("t1", "auto_review", "on-request"))
    assert _codex_gate(tmp_path, reviewed, tool="mcp__desk__open_app")[0] == "blocked"
    assert emit_state.codex_asks_a_person({"transcript_path": reviewed, "turn_id": "t1"}) is True


def test_a_codex_request_with_any_other_reviewer_waits_on_you(tmp_path):
    for reviewer, policy in (("user", "never"), ("guardian_subagent", "on-request"), (None, "on-request")):
        assert _codex_gate(tmp_path, _rollout(tmp_path, ("t1", reviewer, policy)))[0] == "blocked", reviewer


def test_a_codex_request_you_are_the_reviewer_of_waits_on_you(tmp_path):
    assert _codex_gate(tmp_path, _rollout(tmp_path, ("t1", "user", "on-request")))[0] == "blocked"


def test_a_codex_request_whose_turn_cannot_be_read_waits_on_you(tmp_path):
    """Nothing says who rules on it, so the card asks: a badge missing while Codex waits is the worse error."""
    assert _codex_gate(tmp_path, str(tmp_path / "gone.jsonl"))[0] == "blocked"
    assert _codex_gate(tmp_path, _rollout(tmp_path, ("t0", "auto_review", "on-request")))[0] == "blocked"


def test_a_codex_request_is_read_by_its_own_turn_s_reviewer(tmp_path):
    """The reviewer can change between turns of one session, either way."""
    earlier = _rollout(tmp_path, ("t1", "auto_review", "on-request"), ("t2", "user", "on-request"))
    ask = lambda **turn: emit_state.codex_asks_a_person({"transcript_path": earlier, "tool_name": "Bash", **turn})
    assert ask(turn_id="t1") is False
    assert ask(turn_id="t2") is True
    assert ask() is True


def test_a_long_turn_s_reviewer_is_found_far_back_in_the_rollout(tmp_path, monkeypatch):
    """A turn's context is written as it starts; megabytes of tool output follow it in a long one."""
    monkeypatch.setattr(emit_state, "TURN_SCAN_STEP", 64)
    rollout = _rollout(tmp_path, ("t1", "auto_review", "on-request"))
    with open(rollout, "a") as fh:
        fh.write("".join(json.dumps({"type": "response_item", "payload": {"n": n}}) + "\n" for n in range(40)))
    assert emit_state.codex_asks_a_person({"transcript_path": rollout, "turn_id": "t1", "tool_name": "Bash"}) is False


def test_a_standing_question_reaches_the_terminal_once_across_events(tmp_path, monkeypatch):
    """Each hook is its own process, so what was written lives in the session's state file between them. The
    permission_prompt notification comes seconds after the prompt and is the same gate: it moves neither the
    gate's time nor the question carried."""
    session = {"session_id": "abc12345-0000-4000-8000-000000000000"}
    asked = {**session, "tool_name": "AskUserQuestion",
             "tool_input": {"questions": [{"header": "Pick", "question": "Which one?",
                                           "options": [{"label": "A"}, {"label": "B"}]}]}}
    run_handler(tmp_path, ["PreToolUse"], {**session, "tool_use_id": "toolu_A", "tool_name": "AskUserQuestion"})
    writes = []
    for event, payload in (("PermissionRequest", asked),
                           ("Notification", {**session, "notification_type": "permission_prompt"})):
        code, _, written = run_handler(tmp_path, [event], payload)
        assert code == 0
        writes.append([json.loads(value)["since"] for name, value in written if name == "claudeQuestion"])
        time.sleep(1.1)
    assert len(writes[0]) == 1 and writes[1] == []
