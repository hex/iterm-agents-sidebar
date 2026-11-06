# ABOUTME: Exercises the details card's hover titles: every gauge, count and flag says what its figure means.
# ABOUTME: Runs the page's fieldsFor with literal rows and asserts the exact title text.
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")


def evaluate(row, pick, now=1_700_000_000):
    """`pick`, a JavaScript expression of `p`, for each pair fieldsFor makes of `row`."""
    consts = "\n".join(re.search(rf"\nconst {name} = .*?;\n", PAGE, re.S).group(0)
                       for name in ("until", "thousands", "tokens"))
    script = "\n".join([
        f"Date.now = () => {now * 1000};",
        function(PAGE, "forHumans"), consts, function(PAGE, "fieldsFor"),
        f"console.log(JSON.stringify(fieldsFor({json.dumps(row)}).map(p => {pick})));",
    ])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fields(row, now=1_700_000_000):
    return dict(evaluate(row, "[p.label, p.title]", now))


def test_every_gauge_and_count_carries_a_title_that_says_what_the_figure_means():
    titles = fields({
        "context": 62, "started_at": 1_700_000_000 - 7200, "agents": 2,
        "usage": {"cpu": {"percent": 90, "top": "node"}, "memory": {"gb": 3.2, "top": "claude"}},
        "details": {"five_hour": 40, "five_hour_at": 1_700_000_000 + 3600,
                    "seven_day": 15, "seven_day_at": 1_700_000_000 + 172800,
                    "cost": 1.5, "cache_hit": 80, "cache_cold_at": 1_700_000_000 + 120,
                    "lines_added": 1200, "lines_removed": 30},
    })
    assert titles == {
        "Context": "Context used: 62% of the window, as Claude Code measures it each turn",
        "5-hour": "The 5-hour window: 40% used, resets in 1h",
        "Weekly": "The weekly window: 15% used, resets in 2d",
        "CPU": "Its processes are using 90% CPU, most of it node",
        "Memory": "Its processes hold 3.2 GB of memory, most of it claude",
        "Up": "Its process started 2h ago",
        "Agents": "2 subagents running now",
        "Cost": "Spent this session, as Claude Code reports it",
        "Cache": "80% of the prompt came from cache, warm for 2m",
        "Lines": "1,200 added, 30 removed",
    }


def test_titles_without_a_reset_a_hog_or_a_single_agent():
    titles = fields({
        "agents": 1, "usage": {"cpu": {"percent": 100, "top": None}},
        "details": {"five_hour": 5, "cache_hit": 10, "cache_cold_at": 1_700_000_000 - 1, "recache": 120000},
    })
    assert titles["5-hour"] == "The 5-hour window: 5% used"
    assert titles["CPU"] == "Its processes are using 100% CPU"
    assert titles["Agents"] == "1 subagent running now"
    assert titles["Cache"] == "10% of the prompt came from cache, cold now, 120k to rebuild"


def test_the_scheduled_row_says_how_many_and_when_and_its_hover_has_each_whole_prompt():
    crons = [{"id": "6ba43431", "schedule": "*/10 * * * *", "recurring": True, "prompt": "say hello",
              "next": 1_700_000_400, "when": "every 10 min"},
             {"id": "20c147b9", "schedule": "31 13 * * *", "recurring": False, "prompt": "wake me",
              "next": 1_699_999_000, "due": True, "when": "due"}]
    assert evaluate({"crons": crons}, "[p.icon, p.label, p.value, p.title]") == [
        ["clock", "Scheduled", "2 \u00b7 every\u00a010\u00a0min \u00b7 due", "every 10 min: say hello\ndue: wake me"]]


def test_the_card_puts_each_title_on_its_row_and_names_every_flag():
    body = function(PAGE, "showCard")
    assert "if (title) dt.title = dd.title = title;" in body
    assert 'flags.push([(d.effort === "xhigh" ? "extra high" : d.effort) + " effort", "effort " + d.effort, `${d.effort} reasoning effort`]);' in body
    assert 'flags.push(["thinking", "", "Extended thinking on"]);' in body
    assert 'flags.push(["fast", "hot", "Fast mode on"]);' in body
    assert 'flags.push(["past 200k", "warn", "The conversation has passed 200k tokens"]);' in body
    assert "f.title = title;" in body
