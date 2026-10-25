# ABOUTME: Guards the foot's offers about the panel's own setup: the tab status hand-over shows while
# ABOUTME: iTerm2's hooks hold Claude tabs and until declined, posts to the daemon, and the setting says when iTerm2 is too old.
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")
OFFERS = PAGE[PAGE.index("const OFFERS = ["):PAGE.index("// Per offer box:")]

#: Just enough of the DOM for an offer: nodes that keep their children, text,
#: title and click handler, and a box found by its id.
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.classList = {add() {}};
                     this.hidden = false; this.textContent = ""; this.title = ""; this.disabled = false; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  addEventListener(kind, fn) { this.click = fn; }
  text() { return [this.textContent, ...this.children.map(c => c.text())].filter(Boolean).join(" | "); }
  find(text) { return this.textContent === text ? this : this.children.map(c => c.find(text)).find(Boolean); }
}
const boxes = {"sl-offer": new Node("section"), "ts-offer": new Node("section")};
const document = {getElementById: id => boxes[id] || null, createElement: tag => new Node(tag),
                  createElementNS: (ns, tag) => new Node(tag)};
const META_ICONS = {plug: "", computer: ""};
const TOKEN = "t0k";
let SETTINGS = {offer_statusline: true, offer_tab_status: true};
let LATEST = {};
const posted = [];
let answer = {ok: true, status: 200, json: async () => ({ok: true, removed: 10})};
const fetch = (url, init) => { posted.push([url, init.method]); return Promise.resolve(answer); };
const pushed = [];
const push = change => { pushed.push(change); SETTINGS = {...SETTINGS, ...change}; };
const ts = () => boxes["ts-offer"];
"""


def run(body):
    """Runs `body` under node after page.html's offer functions; -> what it logs, parsed."""
    script = "\n".join([DOM, function(PAGE, "metaIcon"), OFFERS, "const offerState = {};",
                        function(PAGE, "paintOffers"), function(PAGE, "paintOffer"), function(PAGE, "takeOffer"),
                        function(PAGE, "tabStatusNote"), body])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_hand_over_is_offered_only_while_iterm2_holds_claude_tabs_and_until_declined():
    assert run("""
        const seen = [];
        paintOffers({tab_status: "contested"}); seen.push([ts().hidden, ts().text()]);
        ts().find("Not now").click(); paintOffers({tab_status: "contested"}); seen.push(ts().hidden);
        SETTINGS.offer_tab_status = true; paintOffers({}); seen.push(ts().hidden);
        paintOffers({tab_status: "unavailable"}); seen.push(ts().hidden);
        console.log(JSON.stringify([seen, pushed]));
    """) == [[[False, "iTerm2 writes the Claude tabs | Remove iTerm2 hooks | Not now | iTerm2's Claude Code integration "
                      "writes the status under Claude tabs from its cc-status hooks in ~/.claude/settings.json, so the "
                      "panel leaves those tabs alone. Removing the hooks lets the panel write every agent's tab, with the "
                      "question and done-while-away. A copy of the file is kept first."],
              True, True, True],
             [{"offer_tab_status": False}]]


def test_hand_over_posts_to_the_daemon_and_says_what_came_of_it():
    assert run("""
        (async () => {
          LATEST = {tab_status: "contested"};
          paintOffers(LATEST);
          ts().find("Remove iTerm2 hooks").click();
          const during = ts().text();
          await new Promise(r => setTimeout(r, 0));
          const after = ts().text();
          answer = {ok: false, status: 409, json: async () => ({error: "settings.json is not valid JSON; left unchanged"})};
          offerState["ts-offer"] = null;
          paintOffers(LATEST);
          ts().find("Remove iTerm2 hooks").click();
          await new Promise(r => setTimeout(r, 0));
          console.log(JSON.stringify([posted, during.split(" | ")[1], after, ts().text().split(" | ").pop()]));
          process.exit(0);
        })();
    """) == [[["/tab-status?token=t0k", "POST"], ["/tab-status?token=t0k", "POST"]], "Removing…",
             "iTerm2 hooks removed | A copy is in ~/.claude/settings.json.before-tab-status. Claude sessions open "
             "now keep the hooks until they restart.",
             "settings.json is not valid JSON; left unchanged"]


def test_the_setting_says_when_iterm2_is_too_old_and_nothing_otherwise():
    assert run("""
        const note = {};
        const seen = [];
        tabStatusNote(note, {tab_status: "unavailable"}); seen.push([note.hidden, note.textContent]);
        tabStatusNote(note, {tab_status: "contested"}); seen.push(note.hidden);
        tabStatusNote(note, {}); seen.push(note.hidden);
        console.log(JSON.stringify(seen));
    """) == [[False, "Needs iTerm2 3.7.6"], True, True]
