# ABOUTME: Checks how the Accounts foot draws Antigravity's quota: open, folded to a tile, and at compact width.
# ABOUTME: Runs page.html's functions under Node over the limits tests' stand-in DOM, fed a quota agy_quota.py shapes.
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agy_quota import Quota  # noqa: E402
from page_source import function  # noqa: E402
from test_page_limits_fold import DOM, HELPERS, LIMITS, NOW, PAGE, store  # noqa: E402

#: Accounts with room everywhere, so the compact foot's own lines say nothing tight.
CALM = store((12, 30, 20), (None, 40, 10), (3, 50, 5))


def quota(gemini_5h=0.92, third_party_5h=1.0, argon=0.99, failed=False):
    """A snapshot as the daemon sends it, built by the daemon's own code from agy's reply."""
    reply = {"status": "SUCCESS", "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "description": "Models within this group: Gemini 4 Neon, Gemini 3.8 Flash",
         "buckets": [{"window": "weekly", "remaining_fraction": 0.97, "reset_time": "2026-11-10T12:00:00Z"},
                     {"window": "5h", "remaining_fraction": gemini_5h, "reset_time": "2026-11-05T13:20:00Z"}]},
        {"name": "Claude and GPT models", "description": "Models within this group: Claude Opus 5.5, GPT-OSS 120B",
         "buckets": [{"window": "5h", "remaining_fraction": third_party_5h, "reset_time": "2026-11-05T14:10:00Z"},
                     {"window": "weekly", "remaining_fraction": 1, "reset_time": "2026-11-11T12:00:00Z"}]},
        {"name": "Gemini 4 Argon", "description": "Argon quota is separate.",
         "buckets": [{"window": "weekly", "remaining_fraction": argon, "reset_time": "2026-11-08T12:00:00Z"}]}]}}}
    answers = [(0, json.dumps(reply), "")] + ([(1, "", "")] if failed else [])
    q = Quota(find=lambda: "/bin/agy", run=lambda agy: answers.pop(0))
    q.step(NOW, True)
    if failed:
        q.step(NOW + 600, True)
    return q.snapshot(NOW + (600 if failed else 0))


def run(body, snapshot, compact=False, tiny=False):
    setup = f"""{DOM}
Date.now = () => {NOW * 1000};
let SETTINGS = {{auto_switch: false, limits_folded: true}};
let compact = {json.dumps(compact)}, tiny = {json.dumps(tiny)};
const STORE = {json.dumps(CALM)};
const AG = {json.dumps(snapshot)};
"""
    script = "\n".join([setup, *HELPERS, LIMITS, function(PAGE, "paintAntigravity"), body])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=10,
                            env={**os.environ, "TZ": "UTC"})
    return json.loads(result.stdout)


OPEN = """
const strip = document.createElement("div");
paintAntigravity(strip, AG);
const block = strip.children[0];
console.log(JSON.stringify({cls: block.className, words: words(block),
  lines: block.children.map(c => ({cls: c.className, words: words(c), title: c.title}))}));
"""


def test_the_open_foot_names_each_group_then_draws_its_windows():
    out = run(OPEN, quota())
    assert out["cls"] == "ag-limits"
    assert [(line["cls"], line["words"][0]) for line in out["lines"]] == [
        ("acct-line", "Antigravity"),
        ("ag-group", "Gemini Models"), ("win", "5-hour"), ("win", "Weekly"),
        ("ag-group", "Claude and GPT models"), ("win", "5-hour"), ("win", "Weekly"),
        ("ag-group", "Gemini 4 Argon"), ("win", "Weekly")]
    # 8% of the Gemini 5-hour spent, 1h 20m to its reset.
    assert out["lines"][2]["words"][1:] == ["8%", "1h"]


def test_a_groups_name_lists_its_models_on_hover_and_each_row_names_its_group():
    lines = run(OPEN, quota())["lines"]
    assert lines[1]["title"] == "Gemini 4 Neon, Gemini 3.8 Flash"
    assert lines[2]["title"].startswith("Gemini Models 5-hour: 8% used, resets ")
    # A group whose description lists no models has no hover.
    assert lines[7]["title"] == ""


def test_a_failed_ask_keeps_the_figures_and_says_how_old_they_are():
    head = run(OPEN, quota(failed=True))["lines"][0]
    assert head["words"] == ["Antigravity", "as of 12:00"]


TILE = """
const tile = foldedAntigravityTile(AG);
console.log(JSON.stringify({words: words(tile), title: tile.title, cls: tile.className}));
"""


def test_folded_one_tile_shows_the_fullest_window_of_any_group():
    out = run(TILE, quota(gemini_5h=0.92, third_party_5h=0.25))
    # Claude and GPT models' 5-hour, 75% spent, is the fullest.
    assert out["words"] == ["Antigravity", "75%", "5h 2h"]
    assert "climbing" in out["cls"]


def test_the_tiles_hover_names_every_group_with_its_windows():
    title = run(TILE, quota())["title"]
    assert title == ("Antigravity · Gemini Models: 5-hour 8%, Weekly 3% · "
                     "Claude and GPT models: 5-hour 0%, Weekly 0% · Gemini 4 Argon: Weekly 1%")


def test_a_folded_tile_after_a_failed_ask_says_as_of_in_place_of_the_reset():
    out = run(TILE, quota(failed=True))
    assert out["words"][-1] == "as of 12:00"
    assert out["title"].endswith("· as of 12:00")


COMPACT = """
const box = compactFoot(STORE, null, null, AG);
console.log(JSON.stringify(box.children.map(line => ({words: words(line), title: line.title}))));
"""


def test_at_compact_width_antigravity_gets_a_line_only_while_its_fullest_window_is_tight():
    assert not any(line["words"][:1] == ["Antigravity"] or "Antigravity" in line["words"]
                   for line in run(COMPACT, quota(), compact=True))
    lines = run(COMPACT, quota(third_party_5h=0.1), compact=True)
    [line] = [line for line in lines if "Antigravity" in line["words"]]
    # Tight, so its reset shows too, as Codex's line does.
    assert line["words"] == ["Antigravity", "5h", "90%", "2h"]
    assert line["title"].startswith("Antigravity · Gemini Models: 5-hour 8%")
    # Its hover says when each window resets, as Codex's line's does.
    assert "Claude and GPT models: 5-hour 90%, resets in 2h; Weekly 0%, resets in 6d" in line["title"]


def test_the_tiny_foot_says_antigravitys_figures_on_hover():
    [line] = run(COMPACT, quota(), compact=True, tiny=True)
    assert "Antigravity · Gemini Models: 5-hour 8%, resets in 1h; Weekly 3%, resets in 5d" in line["title"]
