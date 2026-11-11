# ABOUTME: Guards the foot's account lines under node: a switch this page made hands over to the daemon's record of it,
# ABOUTME: or of any later switch, and a refused switch and an add or rename notice lapse after a few seconds.
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")

#: The page beneath the foot: nodes that keep their children, text and classes; on() keeps the click handler; the page
#: clock is the test's; timers are recorded to be run by hand; a repaint records what the switch line says.
STUBS = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.classes = new Set(); this.textContent = ""; this.title = "";
    this.classList = {add: c => this.classes.add(c), toggle: (c, on) => on ? this.classes.add(c) : this.classes.delete(c)}; }
  append(...kids) { this.children.push(...kids); }
  setAttribute() {}
}
const document = {createElement: tag => new Node(tag), createTextNode: text => ({textContent: text, children: []})};
const metaIcon = () => new Node("svg");
const reportAge = at => `age ${at}`;
const clock = at => `clock ${at}`;
const TOKEN = "t0k";
const REFUSAL_SHOWN_MS = 4000;
let clicked = null;
const on = (node, kind, fn) => { if (kind === "click") clicked = fn; };
let pageNow = 2000000;
Date.now = () => pageNow;
const timers = [];
const setTimeout = (fn, ms) => timers.push({fn, ms});
const clearTimeout = id => { if (id) timers[id - 1].fn = null; };
const runTimers = () => timers.splice(0).forEach(t => t.fn && t.fn());
let answer;
const fetch = () => Promise.resolve({json: async () => answer});
const settle = () => new Promise(resolve => setImmediate(resolve));
let armedSwitch = null, disarmTimer = null, localSwitch = null, renamingAccount = null, accountNotice = "";
let accountNoticeTimer = null;
const words = node => [node.textContent, ...node.children.flatMap(words)].filter(Boolean);
const said = node => node && [[node.className, ...node.classes].join(" "), words(node).join(" ")];
let lastSnapshot = {accounts: {last_switch: null}};
const painted = [];
const paintBudget = snapshot => { lastSnapshot = snapshot; painted.push(said(switchLine(snapshot.accounts.last_switch))); };
const BOB = {id: "acct-2", name: "bob@example.com"};
const daemonSays = last_switch => paintBudget({accounts: {last_switch}});
const confirm = async () => { switchButton(BOB); clicked(); clicked(); await settle(); };
"""


def run(body):
    """Runs `body` under node after page.html's account functions; -> what it logs, parsed."""
    names = ("switchButton", "switchLine", "addAccount", "renameAccount")
    script = "\n".join([STUBS, *(function(PAGE, name) for name in names), body])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_switch_this_page_made_hands_over_to_the_daemons_record_of_it():
    """The daemon stamps its record before the switch; the page stamps its own after the reply, on its own clock."""
    assert run("""
        (async () => {
          daemonSays({at: 1000, to: "alice@example.com", why: null, auto: false});
          answer = {ok: true, account: BOB};
          await confirm();
          daemonSays({at: 1500, to: "bob@example.com", why: null, auto: false});
          console.log(JSON.stringify([painted.at(-1), localSwitch]));
        })();
    """) == [["switched", "Switched to bob@example.com by hand age 1500"], None]


def test_the_page_keeps_its_line_while_the_daemon_still_shows_the_record_it_had_at_the_click():
    assert run("""
        (async () => {
          daemonSays({at: 1000, to: "bob@example.com", why: null, auto: false});
          answer = {ok: true, account: BOB};
          await confirm();
          console.log(JSON.stringify(painted.at(-1)));
        })();
    """) == ["switched", "Switched to bob@example.com by hand age 2000"]


def test_a_later_switch_by_the_daemon_to_another_account_takes_the_line():
    assert run("""
        (async () => {
          daemonSays({at: 1000, to: "alice@example.com", why: null, auto: false});
          answer = {ok: true, account: BOB};
          await confirm();
          daemonSays({at: 1800, to: "carol@example.com", why: "Fable at 98%", auto: true});
          console.log(JSON.stringify([painted.at(-1), localSwitch]));
        })();
    """) == [["switched", "Switched to carol@example.com Fable at 98% auto age 1800"], None]


def test_a_refused_switch_says_why_and_then_gives_the_line_back_to_the_daemon():
    assert run("""
        (async () => {
          daemonSays({at: 1000, to: "alice@example.com", why: null, auto: false});
          answer = {error: "the Keychain is locked"};
          await confirm();
          const refused = painted.at(-1);
          pageNow += 4000;
          runTimers();
          console.log(JSON.stringify([refused, painted.at(-1), localSwitch]));
        })();
    """) == [["switched refused", "not switched: the Keychain is locked"],
             ["switched", "Switched to alice@example.com by hand age 1000"], None]


def test_a_rename_notice_lapses_and_the_foot_is_painted_without_it():
    assert run("""
        (async () => {
          answer = {account: {id: "acct-2", name: "bob"}};
          renameAccount(BOB, "bob");
          await settle();
          const shown = accountNotice;
          const paints = painted.length;
          runTimers();
          console.log(JSON.stringify([shown, accountNotice, painted.length - paints]));
        })();
    """) == ["renamed to bob", "", 1]


def test_an_add_notice_lapses_but_a_later_operation_keeps_its_own():
    assert run("""
        (async () => {
          answer = {account: {id: "acct-3", name: "carol@example.com"}};
          addAccount();
          await settle();
          const added = accountNotice;
          answer = {error: "no stored account acct-9"};
          renameAccount({id: "acct-9"}, "x");
          const pending = accountNotice;
          runTimers();
          const during = accountNotice;
          await settle();
          runTimers();
          console.log(JSON.stringify([added, pending, during, accountNotice]));
        })();
    """) == ["added carol@example.com", "renaming...", "renaming...", ""]
