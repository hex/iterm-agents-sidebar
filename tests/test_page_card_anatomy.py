# ABOUTME: Exercises the card anatomy's setting, title, state, and clocks without a browser.
# ABOUTME: Runs the page's actual JavaScript functions with literal expected display values.
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")


def run_page(names, body, setup=""):
    functions = []
    for name in names:
        if f"\nfunction {name}(" not in PAGE:
            raise AssertionError(f"Cannot exercise {name}: page does not define it")
        functions.append(function(PAGE, name))
    script = "\n".join([setup, *functions, body])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_card_anatomy_defaults_to_task_before_settings_and_tracks_the_choice():
    assert run_page(["applyCardAnatomy"], """
const seen = [];
for (const choice of [null, {}, {card_anatomy: 'name'}, {card_anatomy: 'task'}]) {
  SETTINGS = choice;
  applyCardAnatomy();
  seen.push(document.documentElement.dataset.cardAnatomy);
}
console.log(JSON.stringify(seen));
""", "let SETTINGS = null; const document = {documentElement: {dataset: {}}};") == [
        "task", "task", "name", "task"]


def test_task_card_title_uses_only_an_unfinished_nonempty_task_title():
    rows = [
        {"label": "sample-session", "task": {"title": "Check keyboard focus", "done": False}},
        {"label": "sample-session"},
        {"label": "sample-session", "task": {"title": "Check keyboard focus", "done": True}},
        {"label": "sample-session", "task": {"title": ""}},
        {"label": "sample-session", "task": {"title": "   "}},
        {"label": "sample-session", "topic": "Review the cache layer"},
        {"label": "sample-session", "provider": "openai", "topic": "Review the cache layer",
         "task": {"title": "Check keyboard focus", "done": False}},
        {"label": "sample-session", "topic": "Review the cache layer", "task": {"title": "Check keyboard focus", "done": True}},
    ]
    assert run_page(["taskCardTitle"],
                    f"console.log(JSON.stringify({json.dumps(rows)}.map(taskCardTitle)));") == [
        "Check keyboard focus", "sample-session", "sample-session", "sample-session", "sample-session",
        "Review the cache layer", "Review the cache layer", "Review the cache layer"]


def test_task_card_pills_keep_done_separate_from_a_completed_task():
    rows = [{"state": "working"}, {"state": "blocked"}, {"state": "idle"},
            {"state": "idle", "unseen": True}, {"state": "exited"}, {},
            {"state": "working", "task": {"done": True}},
            {"state": "working", "task": {"reported_at": 100}}]
    assert run_page(["taskCardPill"],
                    f"console.log(JSON.stringify({json.dumps(rows)}.map(taskCardPill)));") == [
        {"word": "Working", "badge": "working"},
        {"word": "Waiting for you", "badge": "blocked"},
        {"word": "Idle", "badge": "idle"},
        {"word": "Done", "badge": "unseen"},
        {"word": "Exited", "badge": "exited"},
        {"word": "No report", "badge": "unknown"},
        {"word": "Working", "badge": "working"},
        {"word": "Working", "badge": "working"}]


def test_task_card_recency_uses_the_freshest_clock_only_while_active():
    rows = [
        {"state": "working", "working_since": 900, "task": {"reported_at": 990}},
        {"state": "blocked", "blocked_since": 980, "task": {"reported_at": 900}},
        {"state": "working", "working_since": 875},
        {"state": "working", "task": {"reported_at": 1010}},
        {"state": "working"},
        {"state": "idle", "idle_since": 990},
        {"state": "idle", "unseen": True, "task": {"reported_at": 990}},
    ]
    assert run_page(["taskCardRecency"],
                    f"console.log(JSON.stringify({json.dumps(rows)}.map(r => taskCardRecency(r, 1000))));") == [
        "Updated 10 s ago", "Updated 20 s ago", "Updated 2 m ago", "Updated 0 s ago",
        None, None, None]


def test_task_card_stack_orders_identity_title_question_recency_facts_progress():
    body = function(PAGE, "taskCard")
    assert re.findall(r"stack\.(?:replaceChildren|append)\((.*)\);", body) == [
        "identity, name", "question", 'el("card-recency", recency)', "facts", "line"]


def test_task_card_gives_the_idle_pill_its_sweep():
    """The badge's text is rewritten, which drops the sweep the name-first
    chain added, so the idle pill gets one back."""
    body = function(PAGE, "taskCard")
    assert 'if (state.badge === "idle") addSweep(badge);' in body


def test_task_card_keeps_a_long_badge_and_shows_no_pill_without_a_state():
    """A long turn's badge is the warning the name-first chain built; a row
    that has not reported yet carries no pill at all."""
    body = function(PAGE, "taskCard")
    assert 'if (badge.classList.contains("long"))' in body
    assert "if (!row.state) badge.remove();" in body


def test_task_card_wears_the_fork_on_the_folder_line_of_a_worktree():
    body = function(PAGE, "taskCard")
    assert 'metaIcon(fork ? "fork" : "folder")' in body
