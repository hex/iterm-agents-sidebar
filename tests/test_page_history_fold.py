# ABOUTME: Checks the History fold in the panel foot: its head, its Sessions and Activity tabs, which log each reads
# ABOUTME: and when, the tab it remembers, and the keys. Runs the page's own functions under Node over a stand-in DOM.
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
NOW = 1789656000

# Elements as plain objects: enough for the builders to set text, classes,
# ids, attributes and the tab order and append children and text, and for the
# tests to read back what shows. As in the DOM, `children` holds the elements
# alone and `childNodes` the text too. `budget` is the fold as last painted,
# which querySelector searches by attribute, as the page's does under #budget.
DOM = """
function node(tag) {
  return {tag, tagName: tag.toUpperCase(), className: "", textContent: "", title: "", type: "", id: "", disabled: false,
          innerHTML: "", childNodes: [], attrs: {}, dataset: {},
          get children() { return this.childNodes.filter(n => typeof n !== "string"); },
          append(...kids) { this.childNodes.push(...kids); },
          focus() { document.activeElement = this; },
          setAttribute(name, value) { this.attrs[name] = value; }};
}
const every = n => typeof n === "string" ? [] : [n, ...n.childNodes.flatMap(every)];
const text = n => typeof n === "string" ? n : n.childNodes.length ? n.childNodes.map(text).join("") : n.textContent;
const shape = n => typeof n === "string" ? n : n.childNodes.length ? [n.className, ...n.childNodes.map(shape)] : [n.className, n.textContent];
let budget = null;
const document = {createElement: node, createElementNS: (ns, tag) => node(tag), activeElement: null,
  querySelector(selector) {
    const wants = [...selector.matchAll(/\\[([\\w-]+)="([^"]*)"\\]/g)].map(([, name, value]) => [name, value]);
    if (!selector.startsWith("#budget ") || !wants.length) throw new Error(`the stand-in cannot find ${selector}`);
    const has = (n, [name, value]) => (name.startsWith("data-") ? n.dataset[name.slice(5)] : n.attrs[name]) === value;
    return every(budget).find(n => wants.every(want => has(n, want))) ?? null;
  }};
function on(el, type, handler) { (el._on ||= {})[type] = handler; }
let painted = 0;
function paintBudget() { painted++; budget = historyFold(); }
const pushed = [];
function push(change) { pushed.push(change); SETTINGS = {...SETTINGS, ...change}; }
const head = () => budget.children[0];
const tab = id => budget.children[1].children.find(t => t.dataset.tab === id);
const panel = () => budget.children[2];
const press = key => {
  const event = {key, prevented: false, preventDefault() { this.prevented = true; }};
  document.activeElement._on.keydown(event, document.activeElement);
  return event.prevented;
};
"""

PANEL = ("waited", "pastDayHead", "pastEntry", "pastPanel", "reopenPast", "readPast",
         "shortCount", "activitySummary", "activityView", "activityHead", "activitySplit", "activityNames",
         "activityName", "activityRow", "activityRest", "activityBars", "activityPanel", "readActivity")
HISTORY = ("historyTab", "showHistory", "historyKeys", "historyFold")


def run(body, state):
    for name in PANEL + HISTORY:
        assert f"\nfunction {name}(" in PAGE, f"page.html defines no {name}"
    consts = [re.search(r"\nconst clock = .*?\n\};\n", PAGE, re.S).group(0),
              re.search(r"\nconst ACTIVITY_ROWS = .*;\n", PAGE).group(0),
              re.search(r"\nconst HISTORY_TABS = \[.*?\n\];\n", PAGE, re.S).group(0)]
    setup = f"""{DOM}
Date.now = () => {NOW * 1000};
const TOKEN = "t";
let lastSnapshot = {{groups: []}};
{state}
"""
    result = subprocess.run(["node", "-e", "\n".join([setup, *consts, *(function(PAGE, name) for name in PANEL + HISTORY),
                                                      "budget = historyFold();", body])],
                            env={**os.environ, "TZ": "Europe/Bucharest", "LC_ALL": "en_US.UTF-8"},
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


NOTES = {"kind": "cs", "name": "notes", "path": "/work/notes", "conversation": None, "title": None, "at": NOW - 3600}


def day(date, claude_rows=()):
    return {"date": date, "claude": list(claude_rows), "codex": []}


APP = {"project": "/work/app", "scratch": False, "entrypoint": "cli", "conversations": 1, "prompts": 1,
       "tokens": {"input": 0, "output": 10, "cache_read": 0, "cache_write": 0}}
# Newest first, as the daemon answers: Thursday with one prompt, Wednesday with nothing.
REPORT = {"generated_at": 1, "conversations": [], "unread": [], "days": [day("2026-11-05", [APP]), day("2026-11-04")]}


def state(tab=None, open=False, read=(), rows=None, report=None, day=None, past_reads=0, activity_reads=0,
          past_error=None):
    settings = "null" if tab is None else json.dumps({"history_tab": tab})
    return (f"let SETTINGS = {settings}; let historyOpen = {json.dumps(open)};"
            f" const historyRead = new Set({json.dumps(list(read))});"
            f" let pastRows = {json.dumps(rows)}; let pastError = {json.dumps(past_error)}; let pastReads = {past_reads};"
            f" const pastOpening = new Map();"
            f" let activityReport = {json.dumps(report)}; let activityError = null; let activityReads = {activity_reads};"
            f" let activityDay = {json.dumps(day)};")


HEAD = ["lim-toggle", ["chev", "›"], ["", "History"]]
LABEL = ("History: the last week's sessions with no card, and the prompts and tokens of Claude Code and Codex"
         " by day and by project")
# Every read goes out and none comes back, unless a test answers it.
ASKED = "const asked = []; function fetch(url) { asked.push(url); return new Promise(() => {}); }\n"


def test_folded_it_is_its_head_alone_that_reads_history_with_no_figures_whichever_tab_it_remembers():
    shown = [run("console.log(JSON.stringify([shape(budget), head().attrs, head().dataset]));",
                 state(tab=tab)) for tab in ("sessions", "activity")]
    assert shown == [
        [["past", HEAD], {"aria-expanded": "false", "aria-label": LABEL}, {"wait": "sessions"}],
        [["past", HEAD], {"aria-expanded": "false", "aria-label": LABEL}, {"wait": "activity"}],
    ]


def test_opening_shows_two_tabs_with_the_remembered_one_selected_and_its_panel_labelled_by_it():
    """Before the settings arrive there is nothing to remember, and it opens on Sessions."""
    shown = run(ASKED + """
head()._on.click();
const tabs = budget.children[1];
console.log(JSON.stringify([asked, pushed, painted, head().className, head().attrs["aria-expanded"],
  tabs.className, tabs.attrs,
  tabs.children.map(t => [t.tag, t.type, t.className, t.textContent, t.id, t.dataset.tab, t.attrs, t.tabIndex]),
  panel().id, panel().attrs]));
""", state())
    assert shown == [
        ["/past?token=t"], [], 1, "lim-toggle reading", "true",
        "hist-tabs", {"role": "tablist", "aria-label": "History"},
        [["button", "button", "hist-tab", "Sessions", "history-tab-sessions", "sessions",
          {"role": "tab", "aria-selected": "true", "aria-controls": "history-panel"}, 0],
         ["button", "button", "hist-tab", "Activity", "history-tab-activity", "activity",
          {"role": "tab", "aria-selected": "false"}, -1]],
        "history-panel", {"role": "tabpanel", "aria-labelledby": "history-tab-sessions"},
    ]


def test_a_tab_reads_its_log_the_first_time_it_shows_and_going_back_to_it_reads_nothing():
    shown = run(ASKED + """
const seen = [];
const step = name => seen.push([name, asked.length, pushed.length, SETTINGS.history_tab, head().dataset.wait,
  head().className, panel().attrs["aria-labelledby"], tab("activity").attrs["aria-selected"]]);
head()._on.click(); step("open");
tab("activity")._on.click(); step("Activity");
tab("sessions")._on.click(); step("Sessions");
tab("activity")._on.click(); step("Activity again");
tab("activity")._on.click(); step("Activity, already shown");
console.log(JSON.stringify([seen, asked, pushed]));
""", state(tab="sessions"))
    assert shown == [[
        ["open", 1, 0, "sessions", "sessions", "lim-toggle reading", "history-tab-sessions", "false"],
        ["Activity", 2, 1, "activity", "activity", "lim-toggle reading", "history-tab-activity", "true"],
        ["Sessions", 2, 2, "sessions", "sessions", "lim-toggle reading", "history-tab-sessions", "false"],
        ["Activity again", 2, 3, "activity", "activity", "lim-toggle reading", "history-tab-activity", "true"],
        ["Activity, already shown", 2, 3, "activity", "activity", "lim-toggle reading", "history-tab-activity", "true"],
    ], ["/past?token=t", "/activity?days=7&token=t"],
        [{"history_tab": "activity"}, {"history_tab": "sessions"}, {"history_tab": "activity"}]]


def test_a_tab_the_settings_come_back_with_reads_its_log_as_one_picked_here_does():
    """The daemon's reply to any setting saved, or the first settings to arrive, carries the tab
    another panel showed last, and History shows it from then on."""
    shown = run(ASKED + """
head()._on.click();
SETTINGS = {...SETTINGS, history_tab: "activity"};
paintBudget();
paintBudget();
console.log(JSON.stringify([asked, pushed, head().className, panel().attrs["aria-labelledby"],
  every(panel()).filter(n => /unlit/.test(n.className)).length]));
""", state(tab="sessions"))
    assert shown == [["/past?token=t", "/activity?days=7&token=t"], [], "lim-toggle reading", "history-tab-activity", 1]


def test_the_heads_gauge_runs_while_the_shown_tab_reads_and_not_for_the_other():
    """The head names the tab it waits on, which gives Activity's gauge an animation of its own name,
    so it starts again from the left (test_page_fold_heads, and the motion render); the head stays one
    element across tabs, which test_page_history_webkit checks in the real panel."""
    shown = run("""
const answers = {};
function fetch(url) { return new Promise(resolve => { answers[url.split("?")[0]] = resolve; }); }
const seen = [];
const step = name => seen.push([name, SETTINGS.history_tab, pastReads, activityReads, head().className, head().id,
  head().dataset.wait]);
head()._on.click(); step("open on Sessions");
tab("activity")._on.click(); step("Activity");
answers["/activity"]({ok: true, json: async () => REPORT});
setImmediate(() => {
  step("Activity answered");
  tab("sessions")._on.click(); step("back to Sessions");
  console.log(JSON.stringify(seen));
});
""", state(tab="sessions") + f"const REPORT = {json.dumps(REPORT)};")
    assert shown == [
        ["open on Sessions", "sessions", 1, 0, "lim-toggle reading", "", "sessions"],
        ["Activity", "activity", 1, 1, "lim-toggle reading", "", "activity"],
        ["Activity answered", "activity", 1, 0, "lim-toggle", "", "activity"],
        ["back to Sessions", "sessions", 1, 0, "lim-toggle reading", "", "sessions"],
    ]


def test_opening_again_reads_only_the_shown_tab_and_keeps_what_each_read_without_placeholders():
    shown = run(ASKED + """
const seen = [];
const unlit = () => every(budget).filter(n => /unlit/.test(n.className)).length;
const step = name => seen.push([name, asked.length, budget.children.length,
  budget.children.length > 1 ? text(every(panel()).find(n => /act-head|past-where/.test(n.className))) : null, unlit()]);
head()._on.click(); step("open on Activity");
head()._on.click(); step("folded");
head()._on.click(); step("open again");
tab("sessions")._on.click(); step("Sessions");
console.log(JSON.stringify([seen, asked]));
""", state(tab="activity", rows=[NOTES], report=REPORT))
    assert shown == [[
        ["open on Activity", 1, 3, "2 days · 1 prompt · 10 tokens", 0],
        ["folded", 1, 1, None, 0],
        ["open again", 2, 3, "2 days · 1 prompt · 10 tokens", 0],
        ["Sessions", 3, 3, "notes", 0],
    ], ["/activity?days=7&token=t", "/activity?days=7&token=t", "/past?token=t"]]


def test_the_arrows_show_the_next_tab_round_the_ends_and_home_and_end_the_first_and_last():
    shown = run(ASKED + """
tab("sessions").focus();
const seen = [];
for (const key of ["ArrowRight", "ArrowRight", "ArrowLeft", "ArrowLeft", "End", "Home", "ArrowDown", "a"]) {
  const prevented = press(key);
  seen.push([key, prevented, SETTINGS.history_tab, document.activeElement.dataset.tab,
             document.activeElement === tab(SETTINGS.history_tab), document.activeElement.tabIndex]);
}
console.log(JSON.stringify([seen, asked]));
""", state(tab="sessions", open=True, read=["sessions"], rows=[NOTES], report=REPORT))
    assert shown == [[
        ["ArrowRight", True, "activity", "activity", True, 0],
        ["ArrowRight", True, "sessions", "sessions", True, 0],
        ["ArrowLeft", True, "activity", "activity", True, 0],
        ["ArrowLeft", True, "sessions", "sessions", True, 0],
        ["End", True, "activity", "activity", True, 0],
        ["Home", True, "sessions", "sessions", True, 0],
        ["ArrowDown", False, "sessions", "sessions", True, 0],
        ["a", False, "sessions", "sessions", True, 0],
    ], ["/activity?days=7&token=t"]]


def test_a_panel_takes_the_focus_itself_while_nothing_in_it_can():
    """Activity's chart holds nothing that takes the focus, so its panel does, Show the week or not.
    Sessions' entries take it when it lists any; while it reads, has none or says why it could not
    read, the panel does, so the next Tab reaches what it says. test_page_history_webkit checks that
    a focused panel keeps the focus when its rows arrive."""
    cases = [state(tab="sessions", open=True, read=["sessions"], rows=[NOTES]),
             state(tab="sessions", open=True, read=["sessions"], rows=[]),
             state(tab="sessions", open=True, read=["sessions"], past_reads=1),
             state(tab="sessions", open=True, read=["sessions"], past_error="Error: offline"),
             state(tab="activity", open=True, read=["activity"], report=REPORT),
             state(tab="activity", open=True, read=["activity"], report=REPORT, day="2026-11-04"),
             state(tab="activity", open=True, read=["activity"], activity_reads=1)]
    assert [run("console.log(JSON.stringify(panel().tabIndex ?? null));", s) for s in cases] == [
        None, 0, 0, 0, 0, 0, 0]


def test_nothing_in_the_open_fold_has_a_title_on_either_tab():
    titled = "console.log(JSON.stringify(every(budget).filter(n => n.title).map(n => n.className)));"
    assert [run(titled, state(tab=tab, open=True, read=[tab], rows=[NOTES], report=REPORT))
            for tab in ("sessions", "activity")] == [[], []]


def test_show_the_week_returns_to_the_week_without_reading_and_puts_the_focus_on_the_activity_tab():
    shown = run("""
let reads = 0;
function fetch() { reads++; throw new Error("unexpected read"); }
const button = every(panel()).find(n => n.className === "fold-act");
const before = [text(button), text(every(panel()).find(n => n.className === "act-head"))];
button.focus();
button._on.click();
console.log(JSON.stringify([before, activityDay, painted, reads, text(every(panel()).find(n => n.className === "act-head")),
  document.activeElement.attrs.role, document.activeElement.dataset.tab, document.activeElement === tab("activity")]));
""", state(tab="activity", open=True, read=["activity"], report=REPORT, day="2026-11-04"))
    assert shown == [["Show the week", "Wed, Nov 4 · 0 prompts · 0 tokens"], None, 1, 0, "2 days · 1 prompt · 10 tokens", "tab", "activity", True]


def test_folding_while_a_tab_reads_hides_the_gauge_without_cancelling_the_read():
    assert run(ASKED + """
head()._on.click();
head()._on.click();
console.log(JSON.stringify([historyOpen, activityReads, head().className, budget.children.length]));
""", state(tab="activity")) == [False, 1, "lim-toggle", 1]


def test_reopening_sessions_reads_again_keeps_cached_entries_and_waits_for_both_reads():
    assert run("""
const asked = [];
const answers = [];
function fetch(url) { asked.push(url); return new Promise(resolve => answers.push(resolve)); }
head()._on.click();
head()._on.click();
head()._on.click();
const during = [head().className, panel().children[0].children[0].className, text(every(panel()).find(n => n.className === "past-where"))];
answers[0]({ok: true, json: async () => ({rows: []})});
setImmediate(() => {
  const midway = head().className;
  answers.at(-1)({ok: true, json: async () => ({rows: []})});
  setImmediate(() => { paintBudget(); console.log(JSON.stringify([asked, during, midway, pastReads, head().className,
    shape(panel())])); });
});
""", state(tab="sessions", rows=[NOTES])) == [
        ["/past?token=t", "/past?token=t"], ["lim-toggle reading", "past-log", "notes"], "lim-toggle reading", 0,
        "lim-toggle",
        ["hist-panel", ["hist-body", ["past-list", ["fold-note",
                                                    "Nothing to resume from the last 7 days; the ones open now are on their cards."]]]],
    ]


def test_overlapping_activity_rereads_keep_the_report_and_the_gauge_even_after_a_failed_read():
    replacement = {"generated_at": 1, "conversations": [], "unread": [],
                   "days": [day("2026-11-06", [dict(APP, prompts=1)])]}
    shown = run("""
const pending = [];
function fetch(url) { return new Promise((resolve, reject) => pending.push({url, resolve, reject})); }
const click = () => head()._on.click();
const settle = () => new Promise(resolve => setImmediate(() => setImmediate(resolve)));
const seen = () => {
  paintBudget();
  return [activityReads, head().className, text(every(panel()).find(n => n.className === "act-head")),
          every(panel()).filter(n => /unlit/.test(n.className)).length,
          panel().children[0].children[0].children.filter(n => n.className === "acct-status").map(text)];
};
(async () => {
  click(); click(); click();
  const shown = [seen()];
  pending[0].resolve({ok: true, json: async () => activityReport});
  await settle(); shown.push(seen());
  pending[1].reject(new Error("offline"));
  await settle(); shown.push(seen());
  click(); click(); shown.push(seen());
  pending[2].resolve({ok: true, json: async () => REPLACEMENT});
  await settle(); shown.push(seen());
  console.log(JSON.stringify([pending.map(p => p.url), shown]));
})();
""", state(tab="activity", report=REPORT, day="2026-11-04") + f"const REPLACEMENT = {json.dumps(replacement)};")
    empty_head = "Wed, Nov 4 · 0 prompts · 0 tokens"
    assert shown == [["/activity?days=7&token=t"] * 3, [
        [2, "lim-toggle reading", empty_head, 0, []],
        [1, "lim-toggle reading", empty_head, 0, []],
        [0, "lim-toggle", empty_head, 0, ["Error: offline"]],
        [1, "lim-toggle reading", empty_head, 0, ["Error: offline"]],
        [0, "lim-toggle", "1 day · 1 prompt · 10 tokens", 0, []]]]
