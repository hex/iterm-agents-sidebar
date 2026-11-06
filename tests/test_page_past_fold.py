# ABOUTME: Checks the Past sessions fold in the panel foot: a head per day, an entry per row that resumes,
# ABOUTME: its opening and refusal, and the fold's states. Runs the page's own functions under Node over a stand-in DOM.
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")
# Thu 17 Sep 2026 17:40 in Bucharest (EEST, UTC+3), and that day's midnight.
NOW = 1789656000
TODAY = 1789592400
# The day heads and clock times are the page's local ones, so the zone is pinned.
ZONE = "Europe/Bucharest"

# Elements as plain objects: enough for the builders to set text, classes and
# attributes and append children, and for `shape` to read back what shows.
DOM = """
function node(tag) {
  return {tag, className: "", textContent: "", title: "", type: "", disabled: false, children: [], attrs: {}, dataset: {},
          append(...kids) { this.children.push(...kids); },
          setAttribute(name, value) { this.attrs[name] = value; }};
}
const document = {createElement: node};
function on(el, type, handler) { (el._on ||= {})[type] = handler; }
// An element as its class and either its text or its children, in order.
const shape = n => n.children.length ? [n.className, ...n.children.map(shape)] : [n.className, n.textContent];
const log = () => pastFold().children[1];
// Every entry button in the open fold, in order.
const entries = () => log().children.filter(n => n.className === "past-entries")
  .flatMap(list => list.children.map(item => item.children[0]));
const every = n => [n, ...n.children.flatMap(every)];
"""


def run(body, state):
    page = "\n".join([re.search(r"\nconst clock = .*?\n\};\n", PAGE, re.S).group(0)]
                     + [function(PAGE, name) for name in ("waited", "pastDayHead", "pastEntry", "pastFold", "reopenPast", "readPast")])
    setup = f"""{DOM}
Date.now = () => {NOW * 1000};
const TOKEN = "t";
let lastSnapshot = {{groups: []}};
let painted = 0;
function paintBudget() {{ painted++; }}
{state}
"""
    result = subprocess.run(["node", "-e", "\n".join([setup, page, body])], env={**os.environ, "TZ": ZONE},
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


PROMPT = "make the checkout page keep the cart when the session token expires mid-payment"
SHOP = {"kind": "claude", "name": "shop", "path": "/work/shop", "conversation": "c-shop", "title": PROMPT,
        "at": TODAY + 17 * 3600 + 12 * 60}
NOTES = {"kind": "cs", "name": "notes", "path": "/work/notes", "conversation": None, "title": None,
         "at": TODAY + 16 * 3600 + 31 * 60}
SITE = {"kind": "claude", "name": "site", "path": "/work/site", "conversation": "c-site", "title": None,
        "at": TODAY}
DOCS = {"kind": "claude", "name": "docs", "path": "/work/docs", "conversation": "c-docs",
        "title": "rewrite the install page", "at": TODAY - 60}
API = {"kind": "claude", "name": "api", "path": "/work/api", "conversation": "c-api", "title": "add a refund test",
       "at": TODAY - 2 * 86400 + 10 * 3600 + 12 * 60}
# Thu 10 Sep 21:40: six days and twenty hours back, on today's weekday.
LAB = {"kind": "claude", "name": "lab", "path": "/work/lab", "conversation": "c-lab", "title": "plot the latency",
       "at": NOW - (6 * 86400 + 20 * 3600)}
ROWS = [SHOP, NOTES, SITE, DOCS, API, LAB]


def state(rows=ROWS, opening="[]", open=True, error=None, reading=False):
    return (f"let pastOpen = {json.dumps(open)}; let pastRows = {json.dumps(rows)}; let pastError = {json.dumps(error)};"
            f" let pastReads = {int(reading)}; const pastOpening = new Map({opening});")


TOGGLE = ["lim-toggle", ["chev", "›"], ["", "Past sessions"]]


def test_each_day_has_a_head_and_under_it_each_row_is_its_local_time_its_name_and_its_prompt():
    assert run("console.log(JSON.stringify(shape(log())));", state()) == [
        "past-log",
        ["past-day", "Today"],
        ["past-entries",
         ["past-item", ["past-entry", ["past-when", "17:12"], ["past-where", "shop"], ["past-what", PROMPT],
                        ["past-resume", "Resume"]]],
         ["past-item", ["past-entry", ["past-when", "16:31"], ["past-where", "notes"], ["past-resume", "Resume"]]],
         ["past-item", ["past-entry", ["past-when", "00:00"], ["past-where", "site"], ["past-resume", "Resume"]]]],
        ["past-day", "Yesterday"],
        ["past-entries",
         ["past-item", ["past-entry", ["past-when", "23:59"], ["past-where", "docs"],
                        ["past-what", "rewrite the install page"], ["past-resume", "Resume"]]]],
        ["past-day", "Tuesday"],
        ["past-entries",
         ["past-item", ["past-entry", ["past-when", "10:12"], ["past-where", "api"], ["past-what", "add a refund test"],
                        ["past-resume", "Resume"]]]],
        ["past-day", "Thursday"],
        ["past-entries",
         ["past-item", ["past-entry", ["past-when", "21:40"], ["past-where", "lab"], ["past-what", "plot the latency"],
                        ["past-resume", "Resume"]]]],
    ]


def test_a_row_with_no_prompt_and_a_cs_session_are_their_time_and_name_with_nothing_for_the_prompt():
    shown = run("console.log(JSON.stringify(entries().map(shape)));", state([NOTES, SITE]))
    assert shown == [
        ["past-entry", ["past-when", "16:31"], ["past-where", "notes"], ["past-resume", "Resume"]],
        ["past-entry", ["past-when", "00:00"], ["past-where", "site"], ["past-resume", "Resume"]],
    ]


def test_a_row_six_days_and_twenty_hours_back_heads_under_its_weekday_even_when_that_is_todays():
    shown = run("console.log(JSON.stringify(log().children.filter(n => n.className === 'past-day')"
                ".map(n => n.textContent)));", state([LAB]))
    assert shown == ["Thursday"]


def test_an_opening_entry_says_so_with_no_resume_and_waits_until_fifteen_seconds_pass_or_a_refusal_comes():
    opening = json.dumps([["/work/shop\nc-shop", {"at": NOW * 1000 - 2000, "error": None}],
                          ["/work/site\nc-site", {"at": NOW * 1000 - 16000, "error": None}],
                          ["/work/notes\n", {"at": NOW * 1000 - 1000,
                                             "error": "the tab did not open: no window to open it in"}]])
    shown = run("""
const items = log().children[1].children;
console.log(JSON.stringify([items.map(shape), items.map(n => n.children[0].disabled)]));
""", state([SHOP, NOTES, SITE], opening))
    assert shown == [[
        ["past-item", ["past-entry", ["past-when", "17:12"], ["past-where", "shop"], ["past-what", PROMPT],
                       ["past-opening", "opening…"]]],
        ["past-item", ["past-entry", ["past-when", "16:31"], ["past-where", "notes"], ["past-resume", "Resume"]],
         ["past-refusal", "the tab did not open: no window to open it in"]],
        ["past-item", ["past-entry", ["past-when", "00:00"], ["past-where", "site"], ["past-resume", "Resume"]]],
    ], [True, False, False]]


def test_an_entry_is_one_button_in_a_list_a_day_named_for_what_it_resumes_and_how_long_ago():
    opening = json.dumps([["/work/docs\nc-docs", {"at": NOW * 1000 - 2000, "error": None}]])
    shown = run("""
const lists = log().children.filter(n => n.className === "past-entries");
console.log(JSON.stringify([lists.map(l => [l.attrs.role, ...l.children.map(i => i.attrs.role)]),
                            entries().map(b => [b.type, b.attrs["aria-label"]])]));
""", state([SHOP, NOTES, SITE, DOCS], opening))
    assert shown == [
        [["list", "listitem", "listitem", "listitem"], ["list", "listitem"]],
        [["button", f"resume {PROMPT}, in shop, 28m ago"],
         ["button", "resume session notes, 1h ago"],
         ["button", "resume conversation in site, 17h ago"],
         ["button", "opening rewrite the install page, in docs, 17h ago"]],
    ]


def test_clicking_an_entry_asks_the_daemon_to_reopen_that_row_and_the_entry_then_says_opening():
    shown = run("""
const asked = [];
function fetch(url, init) { asked.push([url, init.method, init.body]); return new Promise(() => {}); }
entries()[1]._on.click();
const after = entries();
console.log(JSON.stringify([asked, painted, after.map(shape), after.map(b => b.disabled)]));
""", state([SHOP, NOTES]))
    assert shown == [
        [["/reopen?token=t", "POST", '{"kind":"cs","path":"/work/notes","conversation":null}']],
        1,
        [["past-entry", ["past-when", "17:12"], ["past-where", "shop"], ["past-what", PROMPT], ["past-resume", "Resume"]],
         ["past-entry", ["past-when", "16:31"], ["past-where", "notes"], ["past-opening", "opening…"]]],
        [False, True],
    ]


def test_the_folded_fold_is_its_head_alone_and_opening_it_reads_the_past():
    shown = run("""
const fold = pastFold();
const asked = [];
function fetch(url) { asked.push(url); return new Promise(() => {}); }
fold.children[0]._on.click();
console.log(JSON.stringify([shape(fold), fold.children[0].attrs["aria-expanded"], pastOpen, asked, painted]));
""", state(open=False))
    assert shown == [["past", TOGGLE], "false", True, ["/past?token=t"], 1]


def test_the_open_fold_reserves_reading_rows_and_says_why_it_failed_or_that_there_is_nothing():
    show = "console.log(JSON.stringify(shape(pastFold())));"
    assert run(show, state(rows=None, reading=True)) == [
        "past", ["lim-toggle reading", ["chev", "›"], ["", "Past sessions"]],
        ["past-log unlit", ["u-day", ["", ""]],
         *[["u-entry", ["w", ""], ["n", ""], ["p", ""]] for _ in range(6)]]]
    assert run(show, state(rows=None)) == ["past", TOGGLE]
    assert run(show, state(rows=None, error="read failed (500)")) == [
        "past", TOGGLE, ["past-list", ["acct-status", "read failed (500)"]]]
    assert run(show, state(rows=[])) == [
        "past", TOGGLE, ["past-list", ["fold-note", "Nothing to resume from the last 7 days; the ones open now are on their cards."]]]


def test_a_read_that_fails_after_one_that_listed_says_why_over_the_rows_it_listed():
    assert run("console.log(JSON.stringify(shape(pastFold())));", state(rows=[NOTES], error="read failed (500)")) == [
        "past", TOGGLE, ["past-list", ["acct-status", "read failed (500)"]],
        ["past-log", ["past-day", "Today"],
         ["past-entries",
          ["past-item", ["past-entry", ["past-when", "16:31"], ["past-where", "notes"], ["past-resume", "Resume"]]]]],
    ]


def test_past_reopening_reads_again_keeps_cached_entries_and_waits_for_both_reads():
    assert run("""
const asked = [];
const answers = [];
function fetch(url) { asked.push(url); return new Promise(resolve => answers.push(resolve)); }
const closed = pastFold();
const before = asked.length;
closed.children[0]._on.click();
pastFold().children[0]._on.click();
pastFold().children[0]._on.click();
const during = pastFold();
answers[0]({ok: true, json: async () => ({rows: []})});
setImmediate(() => {
  const midway = pastFold().children[0].className;
  answers.at(-1)({ok: true, json: async () => ({rows: []})});
  setImmediate(() => console.log(JSON.stringify([before, asked, during.children[0].className,
    during.children[1].className, during.children[1].children[1].children[0].children[0].children[1].textContent,
    midway, pastReads > 0, shape(pastFold())])));
});
""", state(rows=[NOTES], open=False)) == [
        0, ["/past?token=t", "/past?token=t"], "lim-toggle reading", "past-log", "notes", "lim-toggle reading", False,
        ["past", TOGGLE, ["past-list", ["fold-note", "Nothing to resume from the last 7 days; the ones open now are on their cards."]]],
    ]


def test_nothing_in_the_fold_has_a_title_and_the_head_says_what_the_fold_holds_to_a_screen_reader():
    opening = json.dumps([["/work/shop\nc-shop", {"at": NOW * 1000 - 2000, "error": None}],
                          ["/work/notes\n", {"at": NOW * 1000 - 1000, "error": "the tab did not open"}]])
    shown = run("""
const fold = pastFold();
console.log(JSON.stringify([every(fold).filter(n => n.title).map(n => [n.className, n.title]),
                            fold.children[0].attrs["aria-label"]]));
""", state(opening=opening))
    assert shown == [[], "Past sessions: the last week's with no card"]
