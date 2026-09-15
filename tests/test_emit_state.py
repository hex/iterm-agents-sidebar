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
    assert emit_state.claude_pid("/dev/ttys999") is None
    assert emit_state.claude_pid(None) is None


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
