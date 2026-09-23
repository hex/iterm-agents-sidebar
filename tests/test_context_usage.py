"""Reading what fills a Claude conversation's context, from Claude Code's own /context.

Ways this can go wrong, and the test for each:
- a token count written as 2.4k, 1m or a bare 10 read as the wrong number;
- the category table missing or reshaped, and an empty or partial breakdown
  shown as if it were the whole;
- the tables after the categories (MCP tools, skills) read as categories;
- the fork cannot run: no claude binary, a non-zero exit, a hang past the
  timeout, output that is not the JSON list, no result entry, an error result,
  or a result that is not /context's; each refused with its reason, never an
  empty table;
- the warning Claude Code prints on stderr mixed into the JSON it prints on stdout;
- the fork writing a transcript or firing hooks: its argument list pins
  --no-session-persistence and hooks off;
- a row that is not a Claude conversation (another provider, no id, an id of
  the wrong shape, a directory that is gone) reaching the fork;
- a second click while the first read runs starting a second fork.
"""
import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import context_usage  # noqa: E402
from sidebar import context_target  # noqa: E402

CONVERSATION = "524ba3e7-6207-4c5a-af51-85392a3f541f"

#: Claude Code 2.1.280's /context, cut down to one row of each later table.
REPORT = """## Context Usage

**Model:** claude-opus-5-5[1m]
**Tokens:** 122.6k / 1m (12%)

### Estimated usage by category

| Category | Tokens | Percentage |
|----------|--------|------------|
| System prompt | 2.4k | 0.2% |
| System tools | 1.1k | 0.1% |
| MCP tools (deferred) | 107.9k | 10.8% |
| System tools (deferred) | 15k | 1.5% |
| Custom agents | 13.2k | 1.3% |
| Memory files | 9.5k | 0.9% |
| Skills | 9.9k | 1.0% |
| Messages | 88.2k | 8.8% |
| Compact buffer | 3k | 0.3% |
| Free space | 872.7k | 87.3% |

### MCP Tools

| Tool | Server | Tokens |
|------|--------|--------|
| mcp__example__search | example | 306 |

### Skills

| Skill | Source | Tokens |
|-------|--------|--------|
| example-skill | Plugin | 120 |
"""


def test_the_breakdown_reads_every_category_in_order():
    assert context_usage.parse(REPORT) == {
        "used": 122_600,
        "window": 1_000_000,
        "categories": [
            {"name": "System prompt", "tokens": 2_400},
            {"name": "System tools", "tokens": 1_100},
            {"name": "MCP tools (deferred)", "tokens": 107_900},
            {"name": "System tools (deferred)", "tokens": 15_000},
            {"name": "Custom agents", "tokens": 13_200},
            {"name": "Memory files", "tokens": 9_500},
            {"name": "Skills", "tokens": 9_900},
            {"name": "Messages", "tokens": 88_200},
            {"name": "Compact buffer", "tokens": 3_000},
            {"name": "Free space", "tokens": 872_700},
        ],
    }


def test_a_count_without_a_suffix_is_whole_tokens():
    """A fresh conversation's Messages row reads `| Messages | 10 | 0.0% |`."""
    report = REPORT.replace("| Messages | 88.2k | 8.8% |", "| Messages | 10 | 0.0% |")
    messages = [c for c in context_usage.parse(report)["categories"] if c["name"] == "Messages"]
    assert messages == [{"name": "Messages", "tokens": 10}]


def test_a_window_of_200k_reads_as_200_thousand():
    report = REPORT.replace("**Tokens:** 122.6k / 1m (12%)", "**Tokens:** 36.6k / 200k (18%)")
    assert (context_usage.parse(report)["used"], context_usage.parse(report)["window"]) == (36_600, 200_000)


def test_a_report_without_the_category_table_is_refused():
    report = REPORT.split("### Estimated usage by category")[0]
    with pytest.raises(context_usage.Refused, match="no category table in /context's output"):
        context_usage.parse(report)


def test_a_report_without_the_token_total_is_refused():
    report = REPORT.replace("**Tokens:** 122.6k / 1m (12%)", "")
    with pytest.raises(context_usage.Refused, match="no token total in /context's output"):
        context_usage.parse(report)


def test_a_count_that_is_not_a_number_is_refused_by_name():
    report = REPORT.replace("| Skills | 9.9k | 1.0% |", "| Skills | lots | 1.0% |")
    with pytest.raises(context_usage.Refused, match="unreadable token count 'lots' for Skills"):
        context_usage.parse(report)


def fake_claude(tmp_path, body):
    """A stand-in claude binary: a shell script that records its argv and cwd, then runs `body`."""
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n"
                      f'printf "%s\\n" "$PWD" "$@" > "{tmp_path}/called"\n' + body)
    binary.chmod(0o755)
    return binary


def printing(entries, stderr=""):
    """A body that prints `entries` as Claude Code's JSON list, and `stderr` beside it."""
    return (f"cat <<'JSON'\n{json.dumps(entries)}\nJSON\n"
            + (f"echo '{stderr}' >&2\n" if stderr else ""))


RESULT = {"type": "result", "subtype": "success", "is_error": False, "local_command": "context",
          "result": REPORT}


def test_the_fork_runs_in_the_conversations_directory_with_hooks_off_and_no_transcript(tmp_path):
    workdir = tmp_path / "project"
    workdir.mkdir()
    binary = fake_claude(tmp_path, printing([{"type": "system"}, RESULT]))
    breakdown = context_usage.read(str(workdir), CONVERSATION, binary=binary)
    assert breakdown["used"] == 122_600
    called = (tmp_path / "called").read_text().splitlines()
    assert Path(called[0]).resolve() == workdir.resolve()
    assert called[1:] == ["-p", "--resume", CONVERSATION, "--fork-session", "--no-session-persistence",
                          "--settings", '{"disableAllHooks":true}', "--output-format", "json", "/context"]


def test_the_warning_on_stderr_does_not_reach_the_parse(tmp_path):
    binary = fake_claude(tmp_path, printing([RESULT], stderr="claude.ai connectors are disabled"))
    assert context_usage.read(str(tmp_path), CONVERSATION, binary=binary)["window"] == 1_000_000


def test_a_missing_binary_is_named(tmp_path):
    with pytest.raises(context_usage.Refused, match=f"cannot run {tmp_path}/nowhere/claude"):
        context_usage.read(str(tmp_path), CONVERSATION, binary=tmp_path / "nowhere" / "claude")


def test_a_failed_fork_says_what_claude_said_last(tmp_path):
    binary = fake_claude(tmp_path, "echo 'starting' >&2\necho 'No conversation found' >&2\nexit 1\n")
    with pytest.raises(context_usage.Refused, match="^claude exited 1: No conversation found$"):
        context_usage.read(str(tmp_path), CONVERSATION, binary=binary)


def test_a_fork_that_hangs_is_given_up_on(tmp_path):
    binary = fake_claude(tmp_path, "exec sleep 5\n")
    with pytest.raises(context_usage.Refused, match="^/context took longer than 0.5 s$"):
        context_usage.read(str(tmp_path), CONVERSATION, binary=binary, timeout=0.5)


@pytest.mark.parametrize("body, reason", [
    ("echo 'not json'\n", "claude printed no JSON list"),
    (printing({"type": "result"}), "claude printed no JSON list"),
    (printing([{"type": "system"}]), "claude printed no result"),
    (printing([dict(RESULT, is_error=True, result="Prompt is too long")]), "/context failed: Prompt is too long"),
    (printing([dict(RESULT, local_command="cost")]), "claude answered something other than /context"),
])
def test_output_that_is_not_a_context_report_is_refused(tmp_path, body, reason):
    with pytest.raises(context_usage.Refused, match=f"^{re.escape(reason)}$"):
        context_usage.read(str(tmp_path), CONVERSATION, binary=fake_claude(tmp_path, body))


def claude_row(directory, **changes):
    return {"session_id": "s1", "provider": "claude", "conversation": CONVERSATION, "path": str(directory),
            **changes}


def test_a_claude_row_is_read_from_its_own_directory(tmp_path):
    rows = [claude_row(tmp_path, session_id="s0", conversation=None), claude_row(tmp_path)]
    assert context_target(rows, "s1") == (str(tmp_path), CONVERSATION)


def test_a_session_gone_since_the_last_rebuild_is_refused(tmp_path):
    with pytest.raises(context_usage.Refused, match="^no such session$"):
        context_target([claude_row(tmp_path)], "s9")


@pytest.mark.parametrize("changes, reason", [
    ({"provider": "openai"}, "only a Claude conversation has a /context"),
    ({"provider": "omp"}, "only a Claude conversation has a /context"),
    ({"conversation": None}, "no conversation id for this session yet"),
    ({"conversation": CONVERSATION + "; rm -rf ~"}, "no conversation id for this session yet"),
    ({"path": None}, "the session's directory is gone"),
])
def test_a_row_that_is_not_a_readable_claude_conversation_is_refused(tmp_path, changes, reason):
    with pytest.raises(context_usage.Refused, match=f"^{re.escape(reason)}$"):
        context_target([claude_row(tmp_path, **changes)], "s1")


def test_a_directory_removed_since_is_refused(tmp_path):
    with pytest.raises(context_usage.Refused, match="^the session's directory is gone$"):
        context_target([claude_row(tmp_path / "removed")], "s1")


def test_a_second_read_of_the_same_session_is_refused_while_the_first_runs(tmp_path):
    binary = fake_claude(tmp_path, "sleep 1\n" + printing([RESULT]))
    reads = context_usage.Reads(binary=binary)
    first = []
    thread = threading.Thread(target=lambda: first.append(reads.run("s1", str(tmp_path), CONVERSATION)))
    thread.start()
    time.sleep(0.3)
    with pytest.raises(context_usage.Refused, match="^already reading this session's context$"):
        reads.run("s1", str(tmp_path), CONVERSATION)
    thread.join()
    assert first[0]["used"] == 122_600


def test_a_session_can_be_read_again_once_a_read_has_failed(tmp_path):
    reads = context_usage.Reads(binary=fake_claude(tmp_path, "exit 3\n"))
    for _ in range(2):
        with pytest.raises(context_usage.Refused, match="^claude exited 3: no message$"):
            reads.run("s1", str(tmp_path), CONVERSATION)


def test_different_sessions_read_at_the_same_time(tmp_path):
    reads = context_usage.Reads(binary=fake_claude(tmp_path, "sleep 1\n" + printing([RESULT])))
    results = []
    threads = [threading.Thread(target=lambda sid=sid: results.append(reads.run(sid, str(tmp_path), CONVERSATION)))
               for sid in ("s1", "s2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [r["used"] for r in results] == [122_600, 122_600]
