# ABOUTME: What the panel reads about an omp session from omp's own files.
# ABOUTME: Fixtures are written in omp 18.2.5's session shapes, under a tmp dir.
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import omp


UNKNOWN = {"model": None, "effort": None, "context": None, "cost": None, "doing": None, "jobs": []}


def entry(kind, **fields):
    return json.dumps({"type": kind, "id": "e1", "parentId": None, **fields})


def assistant(**message):
    return entry("message", message={"role": "assistant", **message})


def terminal(tmp_path, tty, lines):
    """An omp that started on `tty` and has written `lines` to its session."""
    session = tmp_path / "sessions" / "2026-09-21_abc.jsonl"
    session.parent.mkdir(exist_ok=True)
    session.write_text("".join(line + "\n" for line in lines))
    crumbs = tmp_path / "terminal-sessions"
    crumbs.mkdir(exist_ok=True)
    (crumbs / tty).write_text(f"/Users/x/atlas\n{session}\n1 2 3\n")
    return str(crumbs), session


def test_the_session_on_a_terminal_is_the_one_omp_filed_under_its_tty(tmp_path):
    crumbs, session = terminal(tmp_path, "ttys008", [])
    assert omp.session_file(crumbs, "ttys008") == str(session)
    assert omp.session_file(crumbs, "/dev/ttys008") == str(session)


def test_a_terminal_omp_never_ran_on_has_no_session(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [])
    assert omp.session_file(crumbs, "ttys009") is None
    assert omp.session_file(crumbs, None) is None
    assert omp.session_file(crumbs, 8) is None


def test_a_tty_shaped_like_a_path_is_refused(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [])
    (tmp_path / "outside").write_text("/Users/x\n/Users/x/outside.jsonl\n")
    assert omp.session_file(crumbs, "../outside") is None


def test_the_model_is_the_one_that_last_answered(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        entry("model_change", model="openai-codex/gpt-6-astra", role="default"),
        assistant(model="gpt-6-astra", provider="openai-codex"),
        assistant(model="gpt-5.6-luna", provider="openai-codex"),
        entry("message", message={"role": "toolResult", "toolName": "bash"}),
    ])
    assert omp.read_session(crumbs, "ttys008")["model"] == "gpt-5.6-luna"


def test_a_model_chosen_and_not_yet_heard_from_is_already_the_model(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-6-astra", provider="openai-codex"),
        entry("model_change", model="openrouter/~deepseek/deepseek-flash-latest", role="default"),
    ])
    assert omp.read_session(crumbs, "ttys008")["model"] == "~deepseek/deepseek-flash-latest"


def test_a_model_chosen_for_another_role_is_not_the_sessions(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        entry("model_change", model="openai-codex/gpt-6-astra"),
        entry("model_change", model="openai-codex/gpt-5.6-luna", role="smol"),
    ])
    assert omp.read_session(crumbs, "ttys008")["model"] == "gpt-6-astra"


def test_effort_is_the_last_thinking_level_set(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        entry("thinking_level_change", thinkingLevel="low", configured=None),
        entry("thinking_level_change", thinkingLevel="high", configured=None),
    ])
    assert omp.read_session(crumbs, "ttys008")["effort"] == "high"


def test_a_session_that_cannot_be_read_says_nothing(tmp_path):
    crumbs, session = terminal(tmp_path, "ttys008", ["not json", "[1, 2]", entry("message", message=7),
                                                     assistant(model=["x"]),
                                                     entry("thinking_level_change", thinkingLevel=3)])
    assert omp.read_session(crumbs, "ttys008") == UNKNOWN
    session.unlink()
    assert omp.read_session(crumbs, "ttys008") == UNKNOWN
    assert omp.read_session(crumbs, "ttys009") == UNKNOWN


def test_a_growing_session_is_read_from_where_the_last_reading_stopped(tmp_path, monkeypatch):
    """A session log runs to megabytes and the panel reads every two seconds."""
    crumbs, session = terminal(tmp_path, "ttys008", [assistant(model="gpt-6-astra")])
    asked = []
    read = omp._read_from
    monkeypatch.setattr(omp, "_read_from", lambda path, offset: asked.append(offset) or read(path, offset))
    omp.read_session(crumbs, "ttys008")
    first = session.stat().st_size
    with session.open("a") as f:
        f.write(assistant(model="gpt-5.6-luna") + "\n" + '{"type": "mess')
    assert omp.read_session(crumbs, "ttys008")["model"] == "gpt-5.6-luna"
    with session.open("a") as f:
        f.write('age", "message": {"role": "assistant", "model": "kimi-k3"}}\n')
    assert omp.read_session(crumbs, "ttys008")["model"] == "kimi-k3"
    assert asked[:2] == [0, first]


def test_a_session_log_that_shrank_is_read_again_from_the_top(tmp_path):
    crumbs, session = terminal(tmp_path, "ttys008", [assistant(model="gpt-6-astra"),
                                                     assistant(model="gpt-5.6-luna")])
    omp.read_session(crumbs, "ttys008")
    session.write_text(assistant(model="kimi-k3") + "\n")
    assert omp.read_session(crumbs, "ttys008")["model"] == "kimi-k3"


def test_a_session_log_that_is_a_pipe_is_refused_without_waiting_on_it(tmp_path):
    import os
    crumbs, session = terminal(tmp_path, "ttys008", [])
    session.unlink()
    os.mkfifo(session)
    assert omp.read_session(crumbs, "ttys008") == UNKNOWN


def models_db(tmp_path, **providers):
    """omp's model cache: a row per provider, its models a JSON array."""
    path = tmp_path / "models.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS model_cache (provider_id TEXT PRIMARY KEY, models TEXT NOT NULL)")
    db.executemany("INSERT OR REPLACE INTO model_cache VALUES (?, ?)",
                   [(key, json.dumps(models)) for key, models in providers.items()])
    db.commit()
    db.close()
    return str(path)


def test_context_is_the_last_prompt_against_the_models_window(tmp_path):
    """Figures from a live session: 155576 tokens of openai-codex's
    gpt-5.6-luna, whose window is 1000000, is 16%. Another provider sells the
    same model with another window."""
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-5.6-luna", provider="openai-codex",
                  contextSnapshot={"promptTokens": 20000, "nonMessageTokens": 25115}),
        assistant(model="gpt-5.6-luna", provider="openai-codex",
                  contextSnapshot={"promptTokens": 155576, "nonMessageTokens": 25115}),
    ])
    db = models_db(tmp_path, **{
        "github-copilot:models-v2:x": [{"id": "gpt-5.6-luna", "provider": "github-copilot", "contextWindow": 200000}],
        "openai-codex": [{"id": "gpt-6-astra", "provider": "openai-codex", "contextWindow": 272000},
                         {"id": "gpt-5.6-luna", "provider": "openai-codex", "contextWindow": 1000000}]})
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 16


def test_context_is_unknown_without_a_window_to_measure_against(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-5.6-luna", provider="openai-codex", contextSnapshot={"promptTokens": 155576})])
    assert omp.read_session(crumbs, "ttys008", str(tmp_path / "absent.db"))["context"] is None
    unlisted = models_db(tmp_path, **{"openai-codex": [{"id": "gpt-6-astra", "provider": "openai-codex",
                                                         "contextWindow": 272000}]})
    assert omp.read_session(crumbs, "ttys008", unlisted)["context"] is None
    odd = models_db(tmp_path, **{"openai-codex": [{"id": "gpt-5.6-luna", "provider": "openai-codex",
                                                    "contextWindow": 0}, "junk"], "broken": {"not": "a list"}})
    assert omp.read_session(crumbs, "ttys008", odd)["context"] is None


def test_a_prompt_past_the_window_reads_as_full(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-6-astra", provider="openai-codex", contextSnapshot={"promptTokens": 300000})])
    db = models_db(tmp_path, **{"openai-codex": [{"id": "gpt-6-astra", "provider": "openai-codex",
                                                   "contextWindow": 272000}]})
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 100


def test_cost_is_what_every_answer_so_far_cost(tmp_path):
    """omp prices each answer itself. 0.0037 is a live reading; with 0.25 and
    1.5 beside it the session has cost 1.7537, shown to the cent."""
    crumbs, session = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-5.6-luna", usage={"input": 1464, "cost": {"input": 0.0003, "total": 0.0037}}),
        assistant(model="gpt-5.6-luna", usage={"cost": {"total": 0.25}}),
        entry("message", message={"role": "user", "usage": {"cost": {"total": 9}}}),
        assistant(model="gpt-5.6-luna", usage={"cost": {"total": "free"}}),
        assistant(model="gpt-5.6-luna", usage={"cost": {"total": -1}}),
        assistant(model="gpt-5.6-luna", usage={"cost": {"total": float("nan")}}),
    ])
    assert omp.read_session(crumbs, "ttys008")["cost"] == 0.25
    with session.open("a") as f:
        f.write(assistant(model="gpt-5.6-luna", usage={"cost": {"total": 1.5}}) + "\n")
    assert omp.read_session(crumbs, "ttys008")["cost"] == 1.75


def test_a_session_that_has_priced_nothing_has_no_cost(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [assistant(model="gpt-5.6-luna")])
    assert omp.read_session(crumbs, "ttys008")["cost"] is None


def test_a_window_omp_has_since_changed_is_the_one_measured_against(tmp_path):
    """The cache is megabytes, so it is kept between readings, and must not
    outlive what it was read from."""
    import os
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-6-astra", provider="openai-codex", contextSnapshot={"promptTokens": 68000})])
    listed = lambda window: {"openai-codex": [{"id": "gpt-6-astra", "provider": "openai-codex",
                                               "contextWindow": window}]}
    db = models_db(tmp_path, **listed(272000))
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 25
    models_db(tmp_path, **listed(136000))
    os.utime(db, ns=(1, 1))
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 50


LUNA = {"id": "gpt-5.6-luna", "provider": "openai-codex", "contextWindow": 1000000,
        "cost": {"input": 0.2, "longContext": {"inputThreshold": 272000, "input": 0.4}}}


def test_a_model_priced_higher_past_a_threshold_is_measured_against_the_threshold(tmp_path):
    """omp keeps such a model under its dearer tier, so its own status line
    read 18% of 272K for these 49358 tokens while the cache lists 1000000."""
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-5.6-luna", provider="openai-codex", contextSnapshot={"promptTokens": 49358})])
    db = models_db(tmp_path, **{"openai-codex": [LUNA]})
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 18


def test_a_threshold_past_the_window_changes_nothing(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        assistant(model="gpt-5.6-luna", provider="openai-codex", contextSnapshot={"promptTokens": 50000})])
    small = dict(LUNA, contextWindow=200000)
    db = models_db(tmp_path, **{"openai-codex": [small]})
    assert omp.read_session(crumbs, "ttys008", db)["context"] == 25



def starting(tool, intent=None, **data):
    return entry("custom", customType="tool_execution_start",
                 data={"toolCallId": "call_1", "toolName": tool, "startedAt": "2026-09-21T10:00:00Z",
                       **({"intent": intent} if intent is not None else {}), **data})


def test_what_omp_is_doing_is_the_intent_of_the_tool_it_last_started(tmp_path):
    """The line omp shows above its own status bar. A live pair: the bar read
    "Fingerprint crawler authorized keys locally" while the log's last tool
    start carried that intent."""
    crumbs, session = terminal(tmp_path, "ttys008", [
        starting("bash", "Verify crawler key block"),
        starting("bash", "Fingerprint crawler authorized keys locally"),
        entry("message", message={"role": "toolResult", "toolName": "bash", "toolCallId": "call_1"}),
    ])
    assert omp.read_session(crumbs, "ttys008")["doing"] == "Fingerprint crawler authorized keys locally"
    with session.open("a") as f:
        f.write(starting("read", "Read the deploy script") + "\n")
    assert omp.read_session(crumbs, "ttys008")["doing"] == "Read the deploy script"


def test_a_tool_started_without_a_stated_intent_leaves_the_last_one_said(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        starting("bash", "Verify crawler key block"), starting("todo"), starting("bash", 7),
        entry("custom", customType="tool_execution_start", data="junk"),
        entry("custom", customType="todo_hud_state", data={"intent": "not a tool"}),
    ])
    assert omp.read_session(crumbs, "ttys008")["doing"] == "Verify crawler key block"


def bash_start(call, command):
    return entry("custom", customType="tool_execution_start",
                 data={"toolCallId": call, "toolName": "bash", "args": {"command": command}})


def backgrounded(call, job):
    return entry("message", message={"role": "toolResult", "toolName": "bash", "toolCallId": call,
                                     "details": {"async": {"state": "running", "jobId": job, "type": "bash"},
                                                 "timeoutSeconds": 1800}})


def hub(op, *jobs):
    return entry("message", message={"role": "toolResult", "toolName": "hub", "details": {
        "op": op, "jobs": [{"id": job, "type": "bash", "status": status, "label": label, "durationMs": 5}
                           for job, status, label in jobs]}})


def finished(job):
    return entry("custom_message", customType="async-result", display=True,
                 details={"jobs": [{"jobId": job, "type": "bash", "label": "x", "durationMs": 9}]})


def test_a_command_omp_sent_to_the_background_is_a_job_until_it_ends(tmp_path):
    """Shapes from a live log: the bash result says a job started, omp's hub
    lists jobs with a status, and an async-result message says one ended."""
    crumbs, session = terminal(tmp_path, "ttys008", [
        bash_start("c1", "ls"), entry("message", message={"role": "toolResult", "toolName": "bash", "toolCallId": "c1"}),
        bash_start("c2", "ssh crawler ./force.sh"), backgrounded("c2", "bg_3"),
        hub("wait", ("bg_3", "running", "ssh crawler ./force.sh")),
    ])
    assert omp.read_session(crumbs, "ttys008")["jobs"] == ["ssh crawler ./force.sh"]
    with session.open("a") as f:
        f.write(finished("bg_3") + "\n")
    assert omp.read_session(crumbs, "ttys008")["jobs"] == []


def test_the_hub_says_which_jobs_still_run(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        bash_start("c1", "make watch"), backgrounded("c1", "bg_1"),
        bash_start("c2", "npm run dev"), backgrounded("c2", "bg_2"),
        hub("jobs", ("bg_1", "cancelled", "make watch"), ("bg_2", "running", "npm run dev"),
            ("bg_9", "running", "tail -f crawl.log")),
    ])
    assert omp.read_session(crumbs, "ttys008")["jobs"] == ["npm run dev", "tail -f crawl.log"]


def test_a_job_record_that_is_not_one_is_passed_over(tmp_path):
    crumbs, _ = terminal(tmp_path, "ttys008", [
        bash_start("c1", "make watch"), backgrounded("c1", "bg_1"),
        entry("message", message={"role": "toolResult", "toolName": "bash", "details": {"async": "yes"}}),
        entry("message", message={"role": "toolResult", "toolName": "bash", "details": {"async": {"state": "running", "jobId": 7}}}),
        entry("message", message={"role": "toolResult", "toolName": "hub", "details": {"jobs": [3, {"id": None, "status": "running"}]}}),
        entry("custom_message", customType="async-result", details={"jobs": "bg_1"}),
    ])
    assert omp.read_session(crumbs, "ttys008")["jobs"] == ["make watch"]
