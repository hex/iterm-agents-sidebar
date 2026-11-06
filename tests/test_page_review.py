# ABOUTME: Guards the menu item that asks a card's partner to review the card's change: offered only while the pair
# ABOUTME: has no open task and the card is not working, it posts to /review, and a refusal shows its reason on the card.
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")
QUOTED = next(line for line in PAGE.splitlines() if line.startswith("const quotedLabel = "))

#: Just enough of the page beneath a row's menu: nodes that keep their children, text and click handler, the
#: menu's fixed items, and a fetch that records what was posted and answers as the test says.
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.classList = {add() {}, contains() { return false; }};
                     this.hidden = false; this.textContent = ""; this.title = ""; }
  append(...kids) { this.children.push(...kids); }
  setAttribute() {}
  addEventListener(kind, fn) { if (kind === "click") this.click = () => fn({stopPropagation() {}}); }
}
const document = {createElement: tag => new Node(tag)};
const DETAILS = {label: "Details", run() {}};
const CLOSE = {label: "Close", destructive: true, run() {}};
const HOUSEKEEPING = [];
const untieShown = () => {};
const closeMenu = () => {};
const TOKEN = "t0k";
const REFUSAL_SHOWN_MS = 4000;
const refusedPrompts = new Map();
const render = () => {};
let LATEST = {};
const posted = [];
let answer = {status: 200, json: async () => ({ok: true})};
const fetch = (url, init) => { posted.push([url, init.method, JSON.parse(init.body)]); return Promise.resolve(answer); };
const row = (session_id, label, state, partner) => ({session_id, label, state, provider: "claude", partner});
const ALPHA = row("p1", "alpha", "idle", {side: "upper", with: "p2"});
const BRAVO = row("p2", "bravo", "idle", {side: "lower", with: "p1"});
const pair = open => ({id: "P1", upper: "p1", lower: "p2", open, landings: 0, landed: null, lines: {}});
const labels = (one, rows) => menuFor(one, {name: "AGENTS", rows}).children.filter(node => node.tag === "button")
  .map(item => item.textContent);
const item = (menu, text) => menu.children.find(node => node.textContent === text);
"""


def run(body):
    """Runs `body` under node after page.html's menu and review functions; -> what it logs, parsed."""
    script = "\n".join([DOM, QUOTED, function(PAGE, "menuFor"), function(PAGE, "postReview"), body])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_partnered_card_with_no_task_open_is_offered_a_review_beside_untie():
    assert run("""
        LATEST = {partners: [pair(null)]};
        console.log(JSON.stringify(labels(ALPHA, [ALPHA, BRAVO])));
    """) == ["Details", "Ask “bravo” to review", "Untie from “bravo”", "Close"]


def test_no_review_is_offered_while_a_task_is_open_the_card_works_or_it_has_no_partner():
    assert run("""
        LATEST = {partners: [pair({from: "p2", to: "p1", state: "started"})]};
        const open = labels(ALPHA, [ALPHA, BRAVO]);
        LATEST = {partners: [pair(null)]};
        const working = labels({...ALPHA, state: "working"}, [ALPHA, BRAVO]);
        const alone = labels(row("p3", "charlie", "idle", undefined), [row("p3", "charlie", "idle", undefined)]);
        console.log(JSON.stringify([open, working, alone]));
    """) == [["Details", "Untie from “bravo”", "Close"], ["Details", "Untie from “bravo”", "Close"],
             ["Details", "Close"]]


def test_the_review_item_posts_the_card_to_the_daemon():
    assert run("""
        (async () => {
          LATEST = {partners: [pair(null)]};
          item(menuFor(ALPHA, {name: "AGENTS", rows: [ALPHA, BRAVO]}), "Ask “bravo” to review").click();
          await new Promise(r => setTimeout(r, 0));
          console.log(JSON.stringify([posted, [...refusedPrompts]]));
        })();
    """) == [[["/review?token=t0k", "POST", {"pane": "p1"}]], []]


def test_a_review_the_daemon_refuses_shows_its_reason_on_the_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“bravo” is waiting on you"})};
          postReview("p1");
          await new Promise(r => setTimeout(r, 0));
          console.log(JSON.stringify(refusedPrompts.get("p1").text));
        })();
    """) == "not asked: “bravo” is waiting on you"
