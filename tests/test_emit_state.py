"""Tests for the hook's event-to-state mapping.

Every case here comes from the hook trace captured 2026-09-07 in
~/.claude/agents-sidebar-events.jsonl across five real sessions.
"""
import importlib.util
import sys
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


def test_a_reentrant_stop_is_ignored():
    """Traced in empire-og-client: two consecutive Stop events for one turn,
    the second with stop_hook_active true, caused by another installed Stop
    hook. Acting on it flaps the state.
    """
    assert state_for("Stop", {"stop_hook_active": True}) is None


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
    assert emit_state.nested_agent({"CLAUDECODE": "1", "CLAUDE_PID": "63630"}, codex=True) is True
    assert emit_state.nested_agent({"CLAUDECODE": "1"}, codex=True) is True
    assert emit_state.nested_agent({"TERM": "xterm"}, codex=True) is False


def test_a_claude_hook_inside_claude_is_the_normal_case():
    """Claude Code's own hooks always run with CLAUDECODE set; that is not
    nesting, that is the session itself."""
    assert emit_state.nested_agent({"CLAUDECODE": "1", "CLAUDE_PID": "1"}, codex=False) is False


ASK = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [
    {"question": "Which icon?", "header": "Icon", "multiSelect": False,
     "options": [{"label": "Dots", "description": "x"}, {"label": "Square", "description": "y"}]},
    {"question": "Which colour?", "header": "Colour", "multiSelect": False,
     "options": [{"label": "Blue", "description": ""}]},
]}}


def test_a_question_carries_its_first_question_and_option_labels():
    """The banner shows one question with its options as buttons; a second
    question is counted, not shown."""
    assert emit_state.question_from(ASK) == {
        "header": "Icon", "question": "Which icon?",
        "options": ["Dots", "Square"], "multi": False, "more": 1}


def test_any_other_gated_tool_names_itself_and_its_first_line():
    bash = {"tool_name": "Bash", "tool_input": {"command": "git push origin main\n&& echo ok"}}
    assert emit_state.question_from(bash) == {"tool": "Bash", "summary": "git push origin main"}
    edit = {"tool_name": "Edit", "tool_input": {"file_path": "/x/y.py", "old_string": "a"}}
    assert emit_state.question_from(edit) == {"tool": "Edit", "summary": "/x/y.py"}


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
