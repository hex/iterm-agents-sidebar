# ABOUTME: Exercises the limit meter row's hover title: the figure, the reset, and the pace tick in words.
# ABOUTME: Runs the page's meterRow under a stub document and asserts the exact title text.
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")
RESET = 1_700_000_000 + 86400  # Wed Nov 15 2023 22:13:20 UTC

STUB = """
const document = {createElement: () => ({
  className: "", dataset: {}, classList: {add() {}}, append() {}, setAttribute() {}})};
"""


def title(label, used, **opts):
    script = "\n".join([
        STUB, function(PAGE, "duration"), function(PAGE, "untilReset"), function(PAGE, "tickSaid"), function(PAGE, "meterRow"),
        f"Date.now = () => {1_700_000_000 * 1000};",
        f"console.log(JSON.stringify(meterRow({json.dumps(label)}, {used}, {RESET}, {json.dumps(opts)}).title));",
    ])
    env = dict(os.environ, TZ="UTC", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, env=env)
    return json.loads(result.stdout)


def test_a_window_without_a_tick_says_its_figure_and_reset():
    assert title("5-hour", 40) == "5-hour: 40% used, resets Wed, Nov 15, 10:13 PM"


def test_a_weekly_window_under_its_tick_says_what_the_tick_is():
    assert title("Weekly", 65, tick=80) == (
        "Weekly: 65% used, resets Wed, Nov 15, 10:13 PM. "
        "Tick at 80%: where an even spend over the window would be now; 15 points under it")


def test_a_weekly_window_past_its_tick_says_so_and_names_the_pace_rule():
    assert title("Fable", 91, tick=80, ahead=True) == (
        "Fable: 91% used, resets Wed, Nov 15, 10:13 PM. "
        "Tick at 80%: where an even spend over the window would be now; 11 points past it, ahead of pace")


def until_reset(seconds):
    script = "\n".join([function(PAGE, "duration"), function(PAGE, "untilReset"),
                        f"console.log(JSON.stringify(untilReset({seconds}, 0)));"])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_a_reset_a_day_or_more_away_says_days_and_hours():
    assert until_reset(41 * 3600 + 48 * 60) == "1d 17h"
    assert until_reset(5 * 86400 + 3 * 3600 + 59 * 60) == "5d 3h"


def test_a_reset_on_a_whole_number_of_days_names_no_hours():
    assert until_reset(2 * 86400 + 59 * 60) == "2d"


def test_a_reset_under_a_day_keeps_its_one_unit():
    assert until_reset(23 * 3600 + 59 * 60) == "23h"
    assert until_reset(14 * 60) == "14m"
