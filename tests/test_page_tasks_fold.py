# ABOUTME: Checks the task fold's counts and the activity marks on its open rows.
# ABOUTME: Executes the page's JavaScript under Node with literal display expectations.
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")


def run_page(name, body, setup=""):
    assert f"\nfunction {name}(" in PAGE, f"Page does not define {name}"
    result = subprocess.run(["node", "-e", "\n".join([setup, function(PAGE, name), body])],
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def test_tasks_head_reports_open_started_and_done_counts():
    assert run_page("tasksHead", """
console.log(JSON.stringify([
  tasksHead(27, 11, 40), tasksHead(1, 0, undefined), tasksHead(3, 2, 0),
  tasksHead(2, 0, 5), tasksHead(0, 0, 5), tasksHead(0, 0, undefined)
]));
""") == ["27 open · 11 started · 40 done", "1 task", "3 tasks · 2 started",
           "2 tasks · 5 done", "5 done", ""]


def test_a_started_task_wears_a_still_half_fill_whatever_the_session_does():
    assert run_page("taskMark", """
console.log(JSON.stringify([taskMark(true), taskMark(false)].map(el => [el.className, el.innerHTML])));
""", "const document = {createElement: () => ({className: '', innerHTML: ''})};") == [
        ["started-mark", ""], ["todo-mark", ""]]


def test_started_tasks_come_first_and_each_run_keeps_the_lists_order():
    tasks = [{"id": "1", "status": "pending"}, {"id": "2", "status": "in_progress"},
             {"id": "3", "status": "pending"}, {"id": "4", "status": "in_progress"}]
    assert run_page("tasksInOrder", f"console.log(JSON.stringify(tasksInOrder({json.dumps(tasks)}).map(t => t.id)));") == [
        "2", "4", "1", "3"]
