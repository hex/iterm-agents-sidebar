"""Resuming a session whose agent has exited, in the pane it died in.

Ways this can go wrong, and the test for each:
- the command is built from a conversation id some process wrote into a
  user variable, so a crafted id must never reach the shell;
- a cs session resumed with bare claude loses cs's memory and task list;
- a Codex pane handed a Claude command, or an omp pane handed anything;
- typing into a pane that is not at a shell prompt (something else runs there);
- the directory is gone, so the resume would start somewhere else;
- the agent died before it saved a word, so there is nothing to resume;
- the same conversation is already live in another pane: launched twice;
- a second click while the first resume is still starting: launched twice;
- cs still waiting on its own question after the hold: the second resume is
  typed into cs's prompt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidebar import RESUME_HOLD, conversation_saved, resume_command, resumable, still_resuming  # noqa: E402

CONVERSATION = "524ba3e7-6207-4c5a-af51-85392a3f541f"


def test_claude_resumes_its_conversation_by_id(tmp_path):
    assert resume_command(str(tmp_path), "claude", CONVERSATION) == f"claude --resume {CONVERSATION}"


def test_codex_resumes_with_its_own_verb(tmp_path):
    assert resume_command(str(tmp_path), "openai", CONVERSATION) == f"codex resume {CONVERSATION}"


def test_a_cs_session_goes_back_through_cs(tmp_path):
    (tmp_path / ".cs").mkdir()
    assert resume_command(str(tmp_path), "claude", CONVERSATION) == "cs ."


def test_a_codex_pane_in_a_cs_directory_is_still_codex(tmp_path):
    (tmp_path / ".cs").mkdir()
    assert resume_command(str(tmp_path), "openai", CONVERSATION) == f"codex resume {CONVERSATION}"


def test_an_id_that_is_not_a_uuid_never_reaches_the_shell(tmp_path):
    for crafted in ("x; rm -rf ~", f"{CONVERSATION}\nrm -rf ~", CONVERSATION.upper() + " ",
                    "$(touch /tmp/owned)", "", None, 42):
        assert resume_command(str(tmp_path), "claude", crafted) is None


def test_omp_and_unknown_providers_have_no_resume(tmp_path):
    assert resume_command(str(tmp_path), "omp", CONVERSATION) is None
    assert resume_command(str(tmp_path), None, CONVERSATION) is None


def test_no_directory_no_command():
    assert resume_command(None, "claude", CONVERSATION) is None


def row(tmp_path, **given):
    base = {"session_id": "A", "agent_state": "exited", "job_name": "zsh",
            "path": str(tmp_path), "provider": "claude", "conversation": CONVERSATION,
            "saved": True}
    return {**base, **given}


def test_an_exited_agent_at_a_shell_prompt_is_resumable(tmp_path):
    me = row(tmp_path)
    assert resumable(me, [me], resuming=set())


def test_a_login_shell_counts_as_a_prompt(tmp_path):
    for shell in ("-zsh", "bash", "fish", "sh"):
        me = row(tmp_path, job_name=shell)
        assert resumable(me, [me], resuming=set()), shell


def test_only_an_exited_agent_is_offered(tmp_path):
    for state in ("working", "idle", "blocked", "unknown", None):
        me = row(tmp_path, agent_state=state)
        assert not resumable(me, [me], resuming=set()), state


def test_not_while_something_else_runs_in_the_pane(tmp_path):
    for job in ("vim", "python3", "claude", None):
        me = row(tmp_path, job_name=job)
        assert not resumable(me, [me], resuming=set()), job


def test_not_when_the_directory_is_gone(tmp_path):
    me = row(tmp_path, path=str(tmp_path / "removed-worktree"))
    assert not resumable(me, [me], resuming=set())


def test_not_when_the_conversation_is_live_in_another_pane(tmp_path):
    me = row(tmp_path)
    twin = row(tmp_path, session_id="B", agent_state="idle", job_name="claude")
    assert not resumable(me, [me, twin], resuming=set())


def test_another_dead_pane_of_the_same_conversation_does_not_block_it(tmp_path):
    me = row(tmp_path)
    ghost = row(tmp_path, session_id="B")
    assert resumable(me, [me, ghost], resuming=set())


def test_not_twice_while_the_first_resume_is_starting(tmp_path):
    me = row(tmp_path)
    assert not resumable(me, [me], resuming={"A"})


def test_not_without_a_command_to_run(tmp_path):
    me = row(tmp_path, provider="omp")
    assert not resumable(me, [me], resuming=set())


def test_not_when_the_conversation_was_never_saved(tmp_path):
    me = row(tmp_path, saved=False)
    assert not resumable(me, [me], resuming=set())


def test_a_claude_conversation_is_saved_once_its_transcript_exists(tmp_path):
    projects = tmp_path / "projects"
    (projects / "-Users-someone-work").mkdir(parents=True)
    assert not conversation_saved("claude", CONVERSATION, None, projects)
    (projects / "-Users-someone-work" / f"{CONVERSATION}.jsonl").write_text("{}\n")
    assert conversation_saved("claude", CONVERSATION, None, projects)


def test_a_codex_conversation_is_saved_once_its_rollout_exists(tmp_path):
    rollout = tmp_path / f"rollout-2026-09-23T10-00-00-{CONVERSATION}.jsonl"
    assert not conversation_saved("openai", CONVERSATION, str(rollout), tmp_path)
    rollout.write_text("{}\n")
    assert conversation_saved("openai", CONVERSATION, str(rollout), tmp_path)
    assert not conversation_saved("openai", CONVERSATION, None, tmp_path)


def test_a_crafted_id_is_never_used_as_a_path(tmp_path):
    (tmp_path / "x.jsonl").write_text("{}\n")
    assert not conversation_saved("claude", "../x", None, tmp_path)
    assert not conversation_saved("claude", "*", None, tmp_path)


def test_a_resume_holds_while_its_hold_runs():
    rows = [{"session_id": "A", "agent_state": "exited", "job_name": "zsh"}]
    assert still_resuming({"A": (100.0, "zsh")}, rows, 100.0 + RESUME_HOLD - 1) == {"A": (100.0, "zsh")}
    assert still_resuming({"A": (100.0, "zsh")}, rows, 100.0 + RESUME_HOLD) == {}


def test_a_resume_holds_past_its_hold_while_what_it_started_still_runs():
    """cs waits on its [Y/n] as long as nobody answers it."""
    rows = [{"session_id": "A", "agent_state": "exited", "job_name": "bash"}]
    assert still_resuming({"A": (100.0, "zsh")}, rows, 100.0 + 10 * RESUME_HOLD) == {"A": (100.0, "zsh")}


def test_a_resume_ends_once_its_agent_reports_or_its_pane_is_gone():
    reported = [{"session_id": "A", "agent_state": "idle", "job_name": "bash"}]
    assert still_resuming({"A": (100.0, "zsh")}, reported, 101.0) == {}
    assert still_resuming({"A": (100.0, "zsh")}, [], 101.0) == {}
