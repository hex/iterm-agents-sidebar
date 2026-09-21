"""Tests for the per-session state document the hook keeps between events.

Hooks are one-shot processes with no memory of each other, and several can run
at once: a parent and its subagents all fire into the same session. Anything
the emitted state depends on beyond the current event has to live in a file,
and that file is contended.
"""
import importlib.util
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "emit_state",
    Path(__file__).resolve().parent.parent / "plugin" / "hooks-handlers" / "emit-state.py")
emit_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emit_state)


def blank():
    return emit_state.blank_state()


# ------------------------------------------------------------------ aggregate

def test_a_session_doing_nothing_is_idle():
    assert emit_state.aggregate(blank()) == "idle"


def test_a_working_parent_is_working():
    doc = blank()
    doc["parent_active"] = True
    assert emit_state.aggregate(doc) == "working"


def test_a_stopped_parent_with_a_live_subagent_is_still_working():
    """Stop arrives when the parent's own turn ends, which can be well before
    its children finish. Reporting idle there is the row saying "your turn"
    while the machine is busy.
    """
    doc = blank()
    doc["agents"] = {"agent-1": 100.0}
    assert emit_state.aggregate(doc) == "working"


def test_an_open_gate_outranks_any_amount_of_work():
    """Blocked is the only state that asks for a person. Whatever else is
    running, the thing to say is that something is waiting.
    """
    doc = blank()
    doc["parent_active"] = True
    doc["agents"] = {"agent-1": 100.0}
    doc["gates"] = {"toolu_1": 100.0}
    assert emit_state.aggregate(doc) == "blocked"


# ---------------------------------------------------------------------- gates

def test_a_gate_survives_a_sibling_finishing_a_tool():
    """The defect this file exists for. Agent A hits a permission prompt; agent
    B finishes an unrelated tool. "A tool ran, so the prompt is gone" is true
    only of the tool that was gated, and nothing tied the two together, so B
    cleared A's gate and the row stopped asking for a person who was still
    needed.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_use_id": "toolu_A"}, "blocked")
    doc = emit_state.apply_event(doc, "PostToolUse",
                                 {"tool_use_id": "toolu_B"}, "working")
    assert emit_state.aggregate(doc) == "blocked"


def test_a_gate_is_cleared_by_the_tool_it_gated():
    """There is no "permission granted" event. The gated tool running is the
    proof, since nothing runs while a prompt is open.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_use_id": "toolu_A"}, "blocked")
    doc = emit_state.apply_event(doc, "PostToolUse",
                                 {"tool_use_id": "toolu_A"}, "working")
    assert emit_state.aggregate(doc) == "working"


def test_a_gate_with_no_tool_id_is_held_rather_than_guessed_away():
    """The permission Notification carries no tool_use_id, and a payload can
    always turn out to lack one. Nothing may clear a gate it cannot prove it
    owns -- a badge that stays too long is a nuisance, one that vanishes while
    Claude waits is the failure.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "Notification",
                                 {"notification_type": "permission_prompt"}, "blocked")
    doc = emit_state.apply_event(doc, "PostToolUse",
                                 {"tool_use_id": "toolu_B"}, "working")
    assert emit_state.aggregate(doc) == "blocked"


def test_a_new_turn_clears_every_gate():
    """The bound on holding a gate we cannot correlate. Typing the next prompt
    is proof the prompt before it was answered, whatever we failed to observe.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "Notification",
                                 {"notification_type": "permission_prompt"}, "blocked")
    doc = emit_state.apply_event(doc, "UserPromptSubmit", {"prompt": "go"}, "working")
    assert emit_state.aggregate(doc) == "working"


def test_a_denied_tool_clears_its_gate():
    """A denied tool never reaches PostToolUse, so without this the gate sits
    until the next prompt -- minutes of claiming Claude needs you when you have
    already told it no.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_use_id": "toolu_A"}, "blocked")
    doc = emit_state.apply_event(doc, "PermissionDenied",
                                 {"tool_use_id": "toolu_A"}, None)
    assert emit_state.aggregate(doc) == "working"


# ------------------------------------------------------------------- subagents

def test_subagents_are_counted_by_identity_not_by_arithmetic():
    """A lifecycle event delivered twice used to move a counter twice. Ids
    make the fold idempotent.
    """
    doc = blank()
    for _ in range(3):
        doc = emit_state.apply_event(doc, "SubagentStart", {"agent_id": "a1"}, "working")
    assert emit_state.live_agents(doc) == 1


def test_the_last_subagent_leaving_a_stopped_parent_is_idle():
    """The parent's Stop landed while children were running, so it reported
    working. If the last child's exit publishes nothing, the row is stuck on a
    state that was true minutes ago and ages into "unknown" instead of idle.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "SubagentStart", {"agent_id": "a1"}, "working")
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle")
    assert emit_state.aggregate(doc) == "working"
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    assert emit_state.aggregate(doc) == "idle"


def test_running_subagents_are_listed_oldest_first_with_their_type():
    doc = blank()
    doc = emit_state.apply_event(doc, "SubagentStart",
                                 {"agent_id": "a1", "agent_type": "Explore"}, "working")
    doc["agents"]["a1"] = 100.0
    doc = emit_state.apply_event(doc, "SubagentStart",
                                 {"agent_id": "a2", "agent_type": "general-purpose"}, "working")
    doc["agents"]["a2"] = 50.0
    assert emit_state.subagents(doc) == [
        {"id": "a2", "parent": None, "type": "general-purpose", "since": 50, "ended": None,
         "name": None, "model": None},
        {"id": "a1", "parent": None, "type": "Explore", "since": 100, "ended": None,
         "name": None, "model": None}]


def test_a_subagent_without_a_type_is_listed_without_one():
    """Real SubagentStop events arrived with an empty agent_type."""
    doc = emit_state.apply_event(blank(), "SubagentStart", {"agent_id": "a1"}, "working")
    assert [s["type"] for s in emit_state.subagents(doc)] == [None]


def test_a_stopped_subagent_is_no_longer_running():
    doc = emit_state.apply_event(blank(), "SubagentStart",
                                 {"agent_id": "a1", "agent_type": "Explore"}, "working")
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    assert emit_state.live_agents(doc) == 0
    assert [s["type"] for s in emit_state.subagents(doc)] == ["Explore"]


def test_a_fresh_turn_forgets_subagent_types_with_the_subagents():
    doc = emit_state.apply_event(blank(), "SubagentStart",
                                 {"agent_id": "a1", "agent_type": "Explore"}, "working")
    doc = emit_state.apply_event(doc, "UserPromptSubmit", {}, "working")
    assert doc["agent_types"] == {}


def test_blocked_since_is_the_oldest_open_gate():
    doc = blank()
    doc["gates"] = {"t1": 300.4, "t2": 120.6}
    assert emit_state.blocked_since(doc) == 121
    assert emit_state.blocked_since(blank()) is None


def test_a_compaction_resume_leaves_running_subagents_alone():
    """An auto-compact fires mid-turn. Clearing there drops a parent to idle
    while its children are still working.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "SubagentStart", {"agent_id": "a1"}, "working")
    doc = emit_state.apply_event(doc, "SessionStart", {"source": "compact"}, "idle")
    assert emit_state.live_agents(doc) == 1


def test_a_fresh_session_start_drops_a_crashed_session_s_leftovers():
    doc = blank()
    doc = emit_state.apply_event(doc, "SubagentStart", {"agent_id": "a1"}, "working")
    doc = emit_state.apply_event(doc, "SessionStart", {"source": "startup"}, "idle")
    assert emit_state.live_agents(doc) == 0


# ------------------------------------------------------------------ durability

def test_concurrent_starts_all_survive(tmp_path, monkeypatch):
    """Read-modify-write from eight hooks at once. Unserialized, the losers'
    ids vanish and Stop can then report idle with children still alive.
    """
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    threads, per_thread = 8, 25
    ready = threading.Barrier(threads)

    def run(worker):
        ready.wait()
        for n in range(per_thread):
            emit_state.update("s1", "SubagentStart",
                              {"agent_id": f"a{worker}-{n}"}, "working")

    workers = [threading.Thread(target=run, args=(i,)) for i in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert emit_state.live_agents(emit_state.read_state("s1")) == threads * per_thread


def test_a_tally_file_from_an_older_version_reads_as_a_blank_state(tmp_path, monkeypatch):
    """Before this the file held a bare integer. An upgrade lands mid-session,
    so the first hook after it meets one. It must start over, not raise -- a
    hook that raises writes no state at all.
    """
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    (tmp_path / "s1").write_text("3")
    assert emit_state.read_state("s1") == emit_state.blank_state()


def test_an_unreadable_state_directory_does_not_take_the_hook_down(monkeypatch):
    """Hooks run on every turn. One that raises on a full or read-only disk
    would break the session it is only supposed to describe.
    """
    monkeypatch.setattr(emit_state, "STATE_DIR", "/dev/null/nope")
    assert emit_state.read_state("s1") == emit_state.blank_state()
    assert emit_state.update("s1", "SubagentStart", {"agent_id": "a1"}, "working") is not None


def test_state_survives_a_round_trip_through_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "PermissionRequest", {"tool_use_id": "toolu_A"}, "blocked")
    assert emit_state.aggregate(emit_state.read_state("s1")) == "blocked"
    emit_state.update("s1", "PostToolUse", {"tool_use_id": "toolu_A"}, "working")
    assert emit_state.aggregate(emit_state.read_state("s1")) == "working"


def test_a_session_end_leaves_nothing_behind(tmp_path, monkeypatch):
    """The file is keyed by session id, which is never reused, so anything not
    deleted here is a leak that accumulates for the life of the machine.
    """
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "SubagentStart", {"agent_id": "a1"}, "working")
    emit_state.clear_state("s1")
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_a_session_end_takes_the_filed_detail_with_it(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    (tmp_path / "s1.published").write_text("{}")
    emit_state.clear_state("s1")
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_a_gate_is_closed_by_the_tool_the_prompt_was_for():
    """PermissionRequest carries tool_name and tool_input but NOT tool_use_id --
    measured across 13 real gates on 2026-09-08. The id is on the PreToolUse
    immediately before it, for the same tool, so the gate borrows it.

    Without this the gate took the uncorrelated slot, which only a new prompt
    could clear, and a session stayed BLOCKED for the rest of the turn after
    the user had already answered.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PreToolUse",
                                 {"tool_use_id": "toolu_A", "tool_name": "AskUserQuestion"},
                                 "working")
    doc = emit_state.apply_event(doc, "PermissionRequest",
                                 {"tool_name": "AskUserQuestion"}, "blocked")
    assert emit_state.aggregate(doc) == "blocked"
    doc = emit_state.apply_event(doc, "PostToolUse",
                                 {"tool_use_id": "toolu_A"}, "working")
    assert emit_state.aggregate(doc) == "working"


def test_a_borrowed_gate_still_survives_a_siblings_tool():
    """The borrowed id must not weaken the rule it was added to. Another
    agent's tool finishing is still not evidence about this gate.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PreToolUse", {"tool_use_id": "toolu_A"}, "working")
    doc = emit_state.apply_event(doc, "PermissionRequest", {}, "blocked")
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "toolu_B"}, "working")
    assert emit_state.aggregate(doc) == "blocked"


def test_a_finished_turn_clears_a_gate_nothing_could_correlate():
    """Nothing runs while a permission prompt is open, so a turn that reached
    its end had none pending. Tighter than waiting for the next prompt, which
    left a badge standing for as long as the user took to type.
    """
    doc = blank()
    doc = emit_state.apply_event(doc, "PermissionRequest", {}, "blocked")
    assert emit_state.aggregate(doc) == "blocked"
    doc = emit_state.apply_event(doc, "Stop", {"stop_hook_active": False}, "idle")
    assert emit_state.aggregate(doc) == "idle"


def test_going_idle_at_the_prompt_clears_a_gate_too():
    """The idle notification is the same proof by another route."""
    doc = blank()
    doc = emit_state.apply_event(doc, "PermissionRequest", {}, "blocked")
    doc = emit_state.apply_event(doc, "Notification",
                                 {"notification_type": "idle_prompt"}, "idle")
    assert emit_state.aggregate(doc) == "idle"


# ------------------------------------------------------------------ invariants

def _turn(doc, events):
    for event, payload, said in events:
        doc = emit_state.apply_event(doc, event, payload, said)
    return doc


def test_a_turn_that_ends_cleanly_always_reads_idle():
    """The invariant both stuck-BLOCKED bugs broke. Whatever happened inside a
    turn, once it has ended with no children left the session is idle -- a row
    that keeps asking for a person after the turn is over is the failure this
    panel exists to avoid, and it shipped twice.

    Sequences are built from the shapes seen in the real event log rather than
    invented: gated tools, ungated tools, denials, failures, subagents.
    """
    import itertools
    middles = [
        [("PreToolUse", {"tool_use_id": "t1"}, "working"),
         ("PostToolUse", {"tool_use_id": "t1"}, "working")],
        # The one that broke it: a gate whose PermissionRequest carries no id.
        [("PreToolUse", {"tool_use_id": "t2"}, "working"),
         ("PermissionRequest", {"tool_name": "AskUserQuestion"}, "blocked"),
         ("Notification", {"notification_type": "permission_prompt"}, "blocked"),
         ("PostToolUse", {"tool_use_id": "t2"}, "working")],
        # A gate the user denied: no PostToolUse ever arrives.
        [("PreToolUse", {"tool_use_id": "t3"}, "working"),
         ("PermissionRequest", {}, "blocked"),
         ("PermissionDenied", {"tool_use_id": "t3"}, None)],
        # A gate whose tool then failed.
        [("PreToolUse", {"tool_use_id": "t4"}, "working"),
         ("PermissionRequest", {}, "blocked"),
         ("PostToolUseFailure", {"tool_use_id": "t4"}, None)],
        # A gate nothing ever resolves. Only the turn ending can bound it.
        [("PreToolUse", {"tool_use_id": "t5"}, "working"),
         ("PermissionRequest", {}, "blocked")],
        [("SubagentStart", {"agent_id": "a1"}, "working"),
         ("SubagentStop", {"agent_id": "a1"}, None)],
    ]
    end = ("Stop", {"stop_hook_active": False}, "idle")
    checked = 0
    for length in (1, 2):
        for combo in itertools.permutations(middles, length):
            events = [("UserPromptSubmit", {"prompt": "go"}, "working")]
            for middle in combo:
                events.extend(middle)
            events.append(end)
            doc = _turn(blank(), events)
            assert emit_state.aggregate(doc) == "idle", \
                f"stuck at {emit_state.aggregate(doc)} after {[e[0] for e in events]}"
            checked += 1
    assert checked >= 30


def test_a_turn_still_ends_working_while_a_subagent_runs():
    """The invariant above must not be won by clearing everything on Stop. A
    child outliving its parent's turn is the one case where idle would lie.
    """
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("SubagentStart", {"agent_id": "a1"}, "working"),
        ("Stop", {"stop_hook_active": False}, "idle"),
    ])
    assert emit_state.aggregate(doc) == "working"


def test_gates_cannot_pile_up_across_one_turn():
    """Every uncorrelated gate takes the one shared slot, so a session that
    prompts repeatedly does not accumulate a badge per prompt.
    """
    doc = blank()
    for _ in range(20):
        doc = emit_state.apply_event(doc, "PermissionRequest", {}, "blocked")
    assert len(doc["gates"]) == 1


# ------------------------------------------------------- subagent name and model

def _session_files(tmp_path, agent_id, meta=None, lines=()):
    """A transcript laid out the way Claude Code writes it: <session>.jsonl, and
    beside it <session>/subagents/agent-<id>.meta.json and .jsonl."""
    transcript = tmp_path / "s1.jsonl"
    transcript.write_text("")
    sub = tmp_path / "s1" / "subagents"
    sub.mkdir(parents=True)
    if meta is not None:
        (sub / f"agent-{agent_id}.meta.json").write_text(meta)
    if lines:
        (sub / f"agent-{agent_id}.jsonl").write_text("\n".join(lines) + "\n")
    return str(transcript)


def _started(agent_id="a1"):
    return emit_state.apply_event(blank(), "SubagentStart",
                                  {"agent_id": agent_id, "agent_type": "workflow-subagent"},
                                  "working")


def test_a_subagent_is_named_by_its_description_and_model(tmp_path):
    transcript = _session_files(
        tmp_path, "a1",
        meta='{"agentType":"workflow-subagent","description":"read:theirs-features"}',
        lines=['{"type":"user","message":{"content":"model: pretend"}}',
               '{"type":"assistant","message":{"model":"claude-fable-5-1","content":[]}}'])
    doc = emit_state.describe_subagents(_started(), transcript)
    [sub] = emit_state.subagents(doc)
    assert (sub["name"], sub["model"]) == ("read:theirs-features", "claude-fable-5-1")


def test_a_name_and_model_that_are_not_on_disk_yet_are_filled_in_later(tmp_path):
    """The meta file appears in the same second as SubagentStart, and the
    model only once the subagent first replies."""
    transcript = _session_files(tmp_path, "a1")
    doc = emit_state.describe_subagents(_started(), transcript)
    assert emit_state.subagents(doc)[0]["name"] is None
    sub = tmp_path / "s1" / "subagents"
    (sub / "agent-a1.meta.json").write_text('{"description":"Variant 2"}')
    (sub / "agent-a1.jsonl").write_text('{"type":"assistant","message":{"model":"claude-opus-5"}}\n')
    doc = emit_state.describe_subagents(doc, transcript)
    [got] = emit_state.subagents(doc)
    assert (got["name"], got["model"]) == ("Variant 2", "claude-opus-5")


def test_an_unreadable_meta_file_leaves_the_subagent_unnamed(tmp_path):
    transcript = _session_files(tmp_path, "a1", meta="{not json",
                                lines=["garbage", '{"type":"assistant","message":"x"}'])
    [sub] = emit_state.subagents(emit_state.describe_subagents(_started(), transcript))
    assert (sub["name"], sub["model"]) == (None, None)


def test_a_nested_subagent_names_the_agent_that_started_it(tmp_path):
    """A subagent's own subagent carries parentAgentId in its meta file, and a
    top-level one has none -- measured on a Fable review on 2026-09-17."""
    transcript = _session_files(
        tmp_path, "a2",
        meta='{"agentType":"claude-code-guide","description":"Verify",'
             '"parentAgentId":"a1","spawnDepth":2}')
    (tmp_path / "s1" / "subagents" / "agent-a1.meta.json").write_text(
        '{"agentType":"general-purpose","description":"Review","spawnDepth":1}')
    doc = emit_state.apply_event(_started("a1"), "SubagentStart", {"agent_id": "a2"}, "working")
    doc["agents"]["a2"] = doc["agents"]["a1"] + 1
    listed = emit_state.subagents(emit_state.describe_subagents(doc, transcript))
    assert [(s["id"], s["parent"]) for s in listed] == [("a1", None), ("a2", "a1")]


def test_a_parent_is_read_even_when_the_name_is_already_known(tmp_path):
    """The name is read once; a doc written before parents were recorded
    still has to learn them."""
    transcript = _session_files(tmp_path, "a2", meta='{"description":"x","parentAgentId":"a1"}')
    doc = emit_state.apply_event(blank(), "SubagentStart", {"agent_id": "a2"}, "working")
    doc["agent_info"] = {"a2": {"name": "x", "model": "claude-opus-5"}}
    [sub] = emit_state.subagents(emit_state.describe_subagents(doc, transcript))
    assert sub["parent"] == "a1"


def test_describing_without_a_transcript_changes_nothing():
    doc = _started()
    assert emit_state.describe_subagents(doc, None) == doc


def test_the_next_prompt_forgets_subagent_descriptions(tmp_path):
    transcript = _session_files(tmp_path, "a1", meta='{"description":"x"}')
    doc = emit_state.describe_subagents(_started(), transcript)
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    doc = emit_state.apply_event(doc, "UserPromptSubmit", {}, "working")
    assert doc["agent_info"] == {}


def test_a_workflow_subagent_is_found_under_its_run(tmp_path):
    """Workflow agents write <session>/subagents/workflows/<run>/agent-<id>.*
    -- measured on a live workflow on 2026-09-15."""
    transcript = tmp_path / "s1.jsonl"
    transcript.write_text("")
    run = tmp_path / "s1" / "subagents" / "workflows" / "wf_71c8f0f4-d95"
    run.mkdir(parents=True)
    (run / "agent-a1.meta.json").write_text('{"description":"read:theirs-features"}')
    (run / "agent-a1.jsonl").write_text('{"type":"assistant","message":{"model":"claude-opus-5"}}\n')
    [sub] = emit_state.subagents(emit_state.describe_subagents(_started(), str(transcript)))
    assert (sub["name"], sub["model"]) == ("read:theirs-features", "claude-opus-5")


# ------------------------------------------------------------ finished subagents

def test_a_finished_subagent_stays_listed_with_when_it_ended(tmp_path):
    """Workflows start and finish subagents every few seconds; a row that
    vanished on finish shifted the whole list each time."""
    transcript = _session_files(tmp_path, "a1", meta='{"description":"read:x"}')
    doc = emit_state.describe_subagents(_started("a1"), transcript)
    doc["agents"]["a1"] = 100.0
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    [sub] = emit_state.subagents(doc)
    assert sub["name"] == "read:x" and sub["since"] == 100 and isinstance(sub["ended"], int)
    assert emit_state.live_agents(doc) == 0


def test_running_subagents_have_no_end_and_keep_their_place_among_finished():
    doc = emit_state.apply_event(blank(), "SubagentStart", {"agent_id": "a1"}, "working")
    doc["agents"]["a1"] = 10.0
    doc = emit_state.apply_event(doc, "SubagentStart", {"agent_id": "a2"}, "working")
    doc["agents"]["a2"] = 20.0
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    listed = emit_state.subagents(doc)
    assert [s["since"] for s in listed] == [10, 20]
    assert listed[0]["ended"] is not None and listed[1]["ended"] is None


def test_the_next_prompt_clears_finished_subagents():
    doc = emit_state.apply_event(blank(), "SubagentStart", {"agent_id": "a1"}, "working")
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    doc = emit_state.apply_event(doc, "UserPromptSubmit", {}, "working")
    assert emit_state.subagents(doc) == []


def test_a_stop_delivered_twice_finishes_once():
    doc = emit_state.apply_event(blank(), "SubagentStart", {"agent_id": "a1"}, "working")
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    doc = emit_state.apply_event(doc, "SubagentStop", {"agent_id": "a1"}, None)
    assert len(emit_state.subagents(doc)) == 1


def test_a_finished_subagent_still_gets_its_name_filled_in(tmp_path):
    transcript = _session_files(tmp_path, "a1")
    doc = emit_state.apply_event(_started("a1"), "SubagentStop", {"agent_id": "a1"}, None)
    (tmp_path / "s1" / "subagents" / "agent-a1.meta.json").write_text('{"description":"late"}')
    [sub] = emit_state.subagents(emit_state.describe_subagents(doc, transcript))
    assert sub["name"] == "late"


# ------------------------------------------------------------ working_since

def test_a_prompt_starts_the_turn_clock_and_tool_calls_do_not_restart_it():
    doc = emit_state.apply_event(blank(), "UserPromptSubmit", {}, "working")
    started = doc["turn_started"]
    assert isinstance(started, float)
    doc["turn_started"] = 1000.0
    doc = emit_state.apply_event(doc, "PostToolUse", {"tool_use_id": "t1"}, "working")
    assert doc["turn_started"] == 1000.0


def test_working_since_is_when_the_turn_began_while_the_session_works():
    doc = emit_state.apply_event(blank(), "UserPromptSubmit", {}, "working")
    doc["turn_started"] = 1000.4
    assert emit_state.working_since(doc) == 1000


def test_working_since_is_none_once_the_turn_is_over():
    doc = emit_state.apply_event(blank(), "UserPromptSubmit", {}, "working")
    doc = emit_state.apply_event(doc, "Stop", {}, "idle")
    assert emit_state.working_since(doc) is None


def test_a_turn_clock_survives_being_read_back_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "UserPromptSubmit", {}, "working")
    assert isinstance(emit_state.read_state("s1")["turn_started"], float)


# ------------------------------------------------------- background tasks

SHELL_TASK = {"id": "task-001", "type": "shell", "status": "running",
              "description": "tail logs", "command": "tail -f /var/log/syslog"}


def test_a_turn_still_ends_working_while_a_background_task_runs():
    """Stop arrives when the model pauses, which it does while a background
    shell, workflow or monitor it started is still going: the task's end
    wakes it for another turn. The Stop payload lists what is in flight.
    """
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("Stop", {"stop_hook_active": False, "background_tasks": [SHELL_TASK]}, "idle"),
    ])
    assert emit_state.aggregate(doc) == "working"


def test_the_next_stop_with_nothing_in_flight_is_idle():
    """Nothing fires when a background task ends; its end wakes the session,
    and that turn's Stop says what is left. So each Stop replaces the list.
    """
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("Stop", {"stop_hook_active": False, "background_tasks": [SHELL_TASK]}, "idle"),
        ("Stop", {"stop_hook_active": False, "background_tasks": []}, "idle"),
    ])
    assert emit_state.aggregate(doc) == "idle"


def test_a_new_prompt_forgets_background_tasks():
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("Stop", {"stop_hook_active": False, "background_tasks": [SHELL_TASK]}, "idle"),
        ("UserPromptSubmit", {"prompt": "again"}, "working"),
        ("Stop", {"stop_hook_active": False}, "idle"),
    ])
    assert emit_state.aggregate(doc) == "idle"


def test_a_subagent_stop_does_not_hold_the_parent_for_the_parent_s_tasks():
    """SubagentStop carries the parent session's list too, but a child ending
    says nothing about the parent's turn; only the parent's own Stop does.
    """
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("SubagentStart", {"agent_id": "a1"}, "working"),
        ("Stop", {"stop_hook_active": False, "background_tasks": []}, "idle"),
        ("SubagentStop", {"agent_id": "a1", "background_tasks": [SHELL_TASK]}, None),
    ])
    assert emit_state.aggregate(doc) == "idle"


def test_an_idle_prompt_notice_does_not_end_a_background_hold():
    """The idle_prompt Notification comes a minute into a wait and carries no
    task list; only a Stop knows what is in flight.
    """
    doc = _turn(blank(), [
        ("UserPromptSubmit", {"prompt": "go"}, "working"),
        ("Stop", {"stop_hook_active": False, "background_tasks": [SHELL_TASK]}, "idle"),
        ("Notification", {"notification_type": "idle_prompt"}, "idle"),
    ])
    assert emit_state.aggregate(doc) == "working"


def test_a_background_hold_survives_being_read_back_from_disk(tmp_path, monkeypatch):
    """Each hook is its own process, so what one Stop recorded reaches the
    next event only through the file."""
    monkeypatch.setattr(emit_state, "STATE_DIR", str(tmp_path))
    emit_state.update("s1", "UserPromptSubmit", {"prompt": "go"}, "working")
    emit_state.update("s1", "Stop", {"stop_hook_active": False, "background_tasks": [SHELL_TASK]}, "idle")
    doc = emit_state.update("s1", "Notification", {"notification_type": "idle_prompt"}, "idle")
    assert doc["background"] == [{"type": "shell", "description": "tail logs"}]
    assert emit_state.aggregate(doc) == "working"
