# ABOUTME: Exercises the limit meter row's tiers: climbing from 70%, near from 90%, full from a shown 98%.
# ABOUTME: Runs the page's meterRow under a stub document and reads the classes it sets.
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")

STUB = """
const document = {createElement: () => {
  const node = {className: "", dataset: {}, append() {}, setAttribute() {}};
  node.classList = {add: c => { node.className = (node.className + " " + c).trim(); }};
  return node;
}};
"""


def tiers(*figures):
    script = "\n".join([
        STUB, function(PAGE, "duration"), function(PAGE, "untilReset"), function(PAGE, "tickSaid"), function(PAGE, "meterRow"),
        f"console.log(JSON.stringify({json.dumps(figures)}.map(u => meterRow('Weekly', u, null).className)));",
    ])
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


def test_each_tier_starts_at_its_figure_and_full_at_the_figure_shown():
    assert tiers(69, 70, 89.4, 90, 97.4, 97.6, 98, 100) == [
        "win", "win climbing", "win climbing", "win near", "win near", "win near full", "win near full",
        "win near full"]

