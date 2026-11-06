# ABOUTME: Checks the Activity fold in the panel foot: its head line and split, the day bars, the project rows and
# ABOUTME: their names, a day picked by a click and what opening it reads. Runs the page's own functions under Node.
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

# Elements as plain objects: enough for the builders to set text, classes,
# data and attributes and append children and text, and for `lines` and
# `bars` to read back what shows.
DOM = """
function node(tag) {
  return {tag, className: "", textContent: "", title: "", type: "", innerHTML: "", dataset: {}, children: [], attrs: {},
          append(...kids) { this.children.push(...kids); },
          focus() { document.activeElement = this; },
          setAttribute(name, value) { this.attrs[name] = value; }};
}
const document = {createElement: node, createElementNS: (ns, tag) => node(tag)};
function on(el, type, handler) { (el._on ||= {})[type] = handler; }
const text = n => typeof n === "string" ? n : n.children.length ? n.children.map(text).join("") : n.textContent;
const words = n => typeof n === "string" ? [n] : n.children.length ? n.children.flatMap(words) : (n.textContent ? [n.textContent] : []);
// Each row, head and status line as the words it shows, in order; the head line as its text.
function lines(el, out = []) {
  if (typeof el === "string") return out;
  if (/act-head/.test(el.className)) out.push(text(el));
  else if (/act-(split|row|rest|nums|days)|lim-toggle|acct-status/.test(el.className)) out.push(words(el));
  else el.children.forEach(child => lines(child, out));
  return out;
}
// A bar box as each bar's class and percent of the busiest day.
const bars = box => box.children.map(bar => [bar.className, bar.dataset.pct ?? null]);
// The fold's rows, and each one's name as its parts' classes and text.
const rowsOf = fold => fold.children[1].children.find(c => c.attrs.role === "list").children;
const named = row => row.children[0].children.map(part => [part.className, part.textContent]);
const every = n => typeof n === "string" ? [] : [n, ...n.children.flatMap(every)];
"""

NAMES = ("shortCount", "activitySummary", "activityView", "activityHead", "activitySplit", "activityNames",
         "activityName", "activityRow", "activityRest", "activityBars", "activityFold", "readActivity")


def run(body, state=""):
    for name in NAMES:
        assert f"\nfunction {name}(" in PAGE, f"page.html defines no {name}"
    setup = f"""{DOM}
const TOKEN = "t";
let lastSnapshot = {{groups: []}};
let painted = 0;
function paintBudget() {{ painted++; }}
{state}
"""
    # The weekday under each bar is in the machine's locale.
    page = [re.search(rf"\nconst {name} = .*;\n", PAGE).group(0) for name in ("ACTIVITY_ROWS",)]
    result = subprocess.run(["node", "-e", "\n".join([setup, *page, *(function(PAGE, name) for name in NAMES), body])],
                            capture_output=True, text=True, check=True, timeout=10,
                            env={**os.environ, "LC_ALL": "en_US.UTF-8"})
    return json.loads(result.stdout)


def claude(project, prompts, input=0, output=0, cache_read=0, cache_write=0, entrypoint="cli", scratch=False):
    return {"project": project, "scratch": scratch, "entrypoint": entrypoint, "conversations": 1, "prompts": prompts,
            "tokens": {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write}}


def codex(project, turns, total, cached_input=0, scratch=False):
    """A Codex row, its total all input: cached input is inside it, as Codex counts."""
    return {"project": project, "scratch": scratch, "originator": "codex_exec", "rollouts": 1, "turns": turns,
            "tokens": {"input": total, "cached_input": cached_input, "output": 0, "reasoning_output": 0,
                       "total": total}}


def day(date, claude_rows=(), codex_rows=()):
    return {"date": date, "claude": list(claude_rows), "codex": list(codex_rows)}


# Newest first, as the daemon answers: Thursday 5 November back to Friday 30 October. Cache reads and
# cached input are most of each busy row, as they are on a real week, and none of them counts: Thursday's
# 4.5B is 3B and 1B of Claude's and Codex's 800M less its 300M cached.
WEEK = {"generated_at": 1793880000, "conversations": [], "unread": [], "days": [
    day("2026-11-05",
        [claude("/work/shop/app", 500, input=10, output=990, cache_read=90_000_000_000, cache_write=2_999_999_000),
         claude("/work/shop/app", 100, output=1_000_000_000, cache_read=40_000_000_000, entrypoint="sdk-cli"),
         claude("/work/site", 0)],
        [codex("/work/shop/app", 100, 800_000_000, cached_input=300_000_000)]),
    day("2026-11-04", [claude("/work/tools/cli", 400, input=1_500_000_000, cache_read=60_000_000_000,
                              cache_write=500_000_000)]),
    day("2026-11-03"),
    day("2026-11-02"),
    day("2026-11-01", codex_rows=[codex("/work/site", 200, 1_600_000_000, cached_input=600_000_000)]),
    day("2026-10-31"),
    day("2026-10-30"),
]}


def state(open=True, report=WEEK, error=None, day=None, reads=0):
    return (f"let activityOpen = {json.dumps(open)}; let activityReport = {json.dumps(report)}; let activityDay = {json.dumps(day)};"
            f" let activityError = {json.dumps(error)}; let activityReads = {reads};")


SHOW = "console.log(JSON.stringify(lines(activityFold())));"


def test_a_count_is_shortened_to_a_decimal_under_ten_and_none_above_in_the_next_unit_up():
    counts = [0, 7, 999, 1000, 1049, 1234, 9949, 9950, 12_345, 999_499, 999_500, 84_000_000, 572_300_000,
              7_512_345_678, 1_000_000_000_000]
    assert run(f"console.log(JSON.stringify({json.dumps(counts)}.map(shortCount)));") == [
        "0", "7", "999", "1k", "1k", "1.2k", "9.9k", "10k", "12k", "999k", "1M", "84M", "572M", "7.5B", "1000B"]


def test_the_head_line_says_the_days_and_both_providers_prompts_and_tokens_with_the_numbers_bold():
    assert run("""
const head = activityHead(activityView(activitySummary(activityReport), activityDay));
console.log(JSON.stringify([text(head), head.children.filter(c => c.tag === "b").map(text)]));
""", state()) == ["7 days · 1.3k prompts · 7.5B tokens", ["7 days", "1.3k", "7.5B"]]


def test_one_of_each_is_said_in_the_singular():
    one = {"generated_at": 1, "conversations": [], "unread": [],
           "days": [day("2026-11-05", [claude("/work/app", 1, output=1)])]}
    assert run("console.log(JSON.stringify(text(activityHead(activityView(activitySummary(activityReport), activityDay)))));",
               state(report=one)) == "1 day · 1 prompt · 1 token"


def test_a_days_tokens_are_claudes_input_output_and_cache_writes_and_codexs_total_less_its_cached_input():
    """Cache reads, the conversation so far read again, are left out: 1 + 10 + 500 of Claude's and 200 - 50
    of Codex's."""
    both = {"generated_at": 1, "conversations": [], "unread": [], "days": [day(
        "2026-11-05", [claude("/work/app", 1, input=1, output=10, cache_read=100, cache_write=500)],
        [codex("/work/app", 1, 200, cached_input=50)])]}
    assert run("console.log(JSON.stringify(text(activityHead(activityView(activitySummary(activityReport), activityDay)))));",
               state(report=both)) == "1 day · 2 prompts · 661 tokens"


def test_the_open_fold_is_the_head_the_split_a_bar_a_day_oldest_first_then_the_projects_by_tokens():
    assert run(SHOW, state()) == [
        ["›", "Activity"],
        "7 days · 1.3k prompts · 7.5B tokens",
        ["Claude ", "6B", "Codex ", "1.5B"],
        ["0", "0", "1B", "0", "0", "2B", "4.5B"],
        ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"],
        ["app", "4.5B"],
        ["cli", "2B"],
        ["site", "1B"],
    ]


def test_each_day_bar_stands_to_the_tallest_day_and_todays_is_marked():
    shown = run("""
const list = activityFold().children[1];
console.log(JSON.stringify(bars(list.children.find(c => c.className === "act-week"))));
""", state())
    assert shown == [["zero", None], ["zero", None], ["", "22"], ["zero", None], ["zero", None],
                     ["", "44"], ["today", "100"]]


def test_a_day_with_any_tokens_keeps_a_bar_however_busy_the_rest_and_only_an_empty_one_is_a_hairline():
    assert run('console.log(JSON.stringify(bars(activityBars([0, 1, 500, 1000], "act-week"))));') == [
        ["zero", None], ["", "0"], ["", "50"], ["today", "100"]]


def test_a_project_row_is_its_name_and_its_total_alone_its_whole_path_said_not_shown():
    """No provider marks and no bar: the split under the head says whose tokens they are, and the
    rows' order and figures say how they compare. The whole path is the row's label for a screen
    reader, never a tooltip."""
    shown = run("""
console.log(JSON.stringify(rowsOf(activityFold()).map(row => [
  row.className, row.children.map(c => [c.className, words(c)]), row.attrs["aria-label"], row.title])));
""", state())
    assert shown == [
        ["act-row", [["act-name", ["app"]], ["act-tok", ["4.5B"]]], "/work/shop/app, 4.5B tokens", ""],
        ["act-row", [["act-name", ["cli"]], ["act-tok", ["2B"]]], "/work/tools/cli, 2B tokens", ""],
        ["act-row", [["act-name", ["site"]], ["act-tok", ["1B"]]], "/work/site, 1B tokens", ""],
    ]


def test_the_activity_toggle_says_what_it_reads_without_any_hover_tooltip():
    unread = dict(WEEK, unread=[{"path": "/logs/a.jsonl", "error": "line 4 cannot be read"}])
    assert run("""
const fold = activityFold();
console.log(JSON.stringify([every(fold).filter(n => n.title).map(n => n.className),
  fold.children[0].attrs["aria-label"]]));
""", state(report=unread)) == [[], "Activity: the last week's prompts and tokens, Claude Code's and Codex's, by day and by project"]


def test_an_empty_week_names_the_log_folders_and_keeps_any_uncounted_log_below_it():
    empty = {"generated_at": 1, "conversations": [],
             "unread": [{"path": "/logs/a.jsonl", "error": "line 4 cannot be read"}],
             "days": [day(d["date"]) for d in WEEK["days"]]}
    empty["days"][0]["claude"].append(claude("/work/cached", 0, cache_read=5000))
    empty["days"][0]["codex"].append(codex("/work/cached", 0, 300, cached_input=300))
    shown = run("""
const list = activityFold().children[1];
console.log(JSON.stringify([list.children.map(n => [n.className, text(n)]),
  every(list).filter(n => n.tag === "code").map(text)]));
""", state(report=empty))
    assert shown == [[
        ["fold-note", "No prompts or tokens in ~/.claude/projects or ~/.codex/sessions over the last 7 days."],
        ["acct-status past-error", "1 log not counted in full"]], ["~/.claude/projects", "~/.codex/sessions"]]


def _projects(n):
    return {"generated_at": 1, "conversations": [], "unread": [],
            "days": [day("2026-11-05", [claude(f"/work/p{i:02}", 1, output=100 - i) for i in range(n)])]}


def test_ten_projects_show_and_the_rest_are_one_quiet_line_with_their_tokens():
    shown = run(SHOW, state(report=_projects(12)))
    assert [line[0] for line in shown[4:]] == [f"p{i:02}" for i in range(10)] + ["+2 more projects"]
    assert shown[-1] == ["+2 more projects", "179"]
    assert run(SHOW, state(report=_projects(11)))[-1] == ["+1 more project", "90"]
    assert run(SHOW, state(report=_projects(10)))[-1] == ["p09", "91"]


def test_a_row_whose_log_names_no_directory_says_so_and_one_run_at_the_root_is_called_by_it():
    nowhere = {"generated_at": 1, "conversations": [], "unread": [],
               "days": [day("2026-11-05", [claude(None, 3, output=40), claude("/", 1, output=9)])]}
    shown = run("""
console.log(JSON.stringify(rowsOf(activityFold()).map(row => [words(row), row.attrs["aria-label"], row.title])));
""", state(report=nowhere))
    assert shown == [[["(no directory)", "40"], "no directory in the log, 40 tokens", ""],
                     [["/", "9"], "/, 9 tokens", ""]]


def test_logs_the_report_could_not_read_in_full_are_counted_by_file_with_each_reason_said_to_a_screen_reader():
    unread = dict(WEEK, unread=[{"path": "/logs/a.jsonl", "error": "line 4 cannot be read"},
                                {"path": "/logs/a.jsonl", "error": "its token totals fell at line 9"},
                                {"path": "/logs/b", "error": "[Errno 13] Permission denied"}])
    shown = run("""
const last = activityFold().children[1].children.at(-1);
console.log(JSON.stringify([words(last), last.className, last.attrs["aria-label"], last.title]));
""", state(report=unread))
    assert shown == [["2 logs not counted in full"], "acct-status past-error",
                     "/logs/a.jsonl: line 4 cannot be read\n/logs/a.jsonl: its token totals fell at line 9\n"
                     "/logs/b: [Errno 13] Permission denied", ""]


def test_the_fold_is_its_head_alone_when_closed_and_says_when_it_could_not_read():
    assert [run(SHOW, s) for s in (state(open=False), state(report=None, error="days must be a whole number"))] == [
        [["›", "Activity"]],
        [["›", "Activity"], ["days must be a whole number"]],
    ]


def test_the_first_read_reserves_the_head_split_week_and_three_project_rows_without_inventing_figures():
    for now, weekdays in [("2026-10-26T00:30:00Z", ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]),
                          ("2026-11-01T22:30:00Z", ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"])]:
        shown = run("""
process.env.TZ = "Europe/Bucharest";
Date.now = () => Date.parse(NOW);
const asked = [];
function fetch(url) { asked.push(url); return new Promise(() => {}); }
activityFold().children[0]._on.click();
const fold = activityFold();
const placeholder = fold.children[1].children[0];
const parts = placeholder?.children ?? [];
console.log(JSON.stringify([asked, activityReads, fold.children[0].className, placeholder?.attrs,
  parts.map(n => [n.className, n.children.length]),
  parts.find(n => n.className === "act-days")?.children.map(text),
  parts.find(n => n.className === "act-rows")?.children.map(n => n.children.map(c => c.className)),
  placeholder ? every(placeholder).filter(n => Object.keys(n.dataset).length || n._on || /zero|today|marks|spark/.test(n.className)).length : null,
  placeholder ? text(placeholder) : null]));
""", state(open=False, report=None) + f"const NOW = {json.dumps(now)};")
        assert shown == [["/activity?days=7&token=t"], 1, "lim-toggle reading", {"aria-hidden": "true"},
                         [["u-head", 1], ["act-split", 1], ["act-week", 7], ["act-nums", 7], ["act-days", 7],
                          ["act-rows", 3]], weekdays, [["name", "tok"]] * 3, 0, "".join(weekdays)]


FETCH = """
const asked = [];
function fetch(url) {
  asked.push(url);
  if (ANSWER === "offline") return Promise.reject(new Error("offline"));
  return Promise.resolve({ok: ANSWER.status === 200, status: ANSWER.status, json: async () => ANSWER.body});
}
const click = () => activityFold().children[0]._on.click();
const settle = then => setImmediate(() => setImmediate(then));
"""


def test_opening_reads_the_week_closing_reads_nothing_and_opening_again_reads_it_again():
    shown = run(FETCH + """
click();
const first = [asked.length, activityOpen];
settle(() => {
  const read = [activityReport, painted];
  click();
  const closed = [asked.length, activityOpen];
  click();
  console.log(JSON.stringify([first, read, closed, asked, activityOpen]));
});
""", state(open=False, report=None) + "const ANSWER = {status: 200, body: {days: [], unread: []}};")
    assert shown == [[1, True], [{"days": [], "unread": []}, 2], [1, False],
                     ["/activity?days=7&token=t", "/activity?days=7&token=t"], True]


def test_a_read_the_daemon_refuses_or_that_never_arrives_says_why():
    refused = run(FETCH + "click(); settle(() => console.log(JSON.stringify([activityError, activityReport])));",
                  state(open=False, report=None) + 'const ANSWER = {status: 400, body: {error: "days must be a whole number"}};')
    silent = run(FETCH + "click(); settle(() => console.log(JSON.stringify(activityError)));",
                 state(open=False, report=None) + "const ANSWER = {status: 502, body: {}};")
    offline = run(FETCH + "click(); settle(() => console.log(JSON.stringify(activityError)));",
                  state(open=False, report=None) + 'const ANSWER = "offline";')
    assert (refused, silent, offline) == (["days must be a whole number", None], "read failed (502)",
                                          "Error: offline")


def test_closing_activity_hides_the_pending_gauge_without_cancelling_the_read():
    assert run("""
function fetch() { return new Promise(() => {}); }
activityFold().children[0]._on.click();
activityFold().children[0]._on.click();
const fold = activityFold();
console.log(JSON.stringify([activityOpen, activityReads, fold.children[0].className, fold.children.length]));
""", state(open=False, report=None)) == [False, 1, "lim-toggle", 1]


def test_overlapping_rereads_keep_the_report_and_pending_gauge_even_after_a_failed_read():
    replacement = {"generated_at": 1, "conversations": [], "unread": [],
                   "days": [day("2026-11-06", [claude("/work/app", 1, output=10)])]}
    shown = run("""
const pending = [];
function fetch(url) { return new Promise((resolve, reject) => pending.push({url, resolve, reject})); }
const click = () => activityFold().children[0]._on.click();
const settle = () => new Promise(resolve => setImmediate(() => setImmediate(resolve)));
const seen = () => {
  const fold = activityFold();
  return [activityReads, fold.children[0].className, lines(fold)[1],
          every(fold).filter(n => n.className === "unlit").length,
          fold.children[1].children.filter(n => n.className === "acct-status").map(text)];
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
  console.log(JSON.stringify([pending.map(p => p.url), shown, painted]));
})();
""", state(open=False, day="2026-11-03") + f"const REPLACEMENT = {json.dumps(replacement)};")
    empty_head = "Tue, Nov 3 · 0 prompts · 0 tokens"
    assert shown == [["/activity?days=7&token=t"] * 3, [
        [2, "lim-toggle reading", empty_head, 0, []],
        [1, "lim-toggle reading", empty_head, 0, []],
        [0, "lim-toggle", empty_head, 0, ["Error: offline"]],
        [1, "lim-toggle reading", empty_head, 0, ["Error: offline"]],
        [0, "lim-toggle", "1 day · 1 prompt · 10 tokens", 0, []]], 8]


def test_a_picked_day_is_the_head_its_projects_alone_by_its_tokens_and_its_bars_marked_in_place_of_todays():
    shown = run("""
const list = activityFold().children[1];
const week = list.children.find(c => c.className === "act-week");
const marked = cls => list.children.find(c => c.className === cls).children.map(s => s.className);
const rows = list.children.find(c => c.attrs.role === "list").children;
console.log(JSON.stringify([lines(activityFold()), bars(week), marked("act-nums"), marked("act-days"),
                            rows.map(row => row.children.map(c => [c.className, words(c)]))]));
""", state(day="2026-11-04"))
    hair = ["zero", None]
    assert shown == [
        [["›", "Activity"], "Wed, Nov 4 · 400 prompts · 2B tokens",
         ["0", "0", "1B", "0", "0", "2B", "4.5B"], ["Fri", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"],
         ["cli", "2B"]],
        [hair, hair, ["", "22"], hair, hair, ["sel", "44"], ["", "100"]],
        ["", "", "", "", "", "sel", ""],
        ["", "", "", "", "", "sel", ""],
        [[["act-name", ["cli"]], ["act-tok", ["2B"]]]],
    ]


def test_an_empty_picked_day_names_the_weekday_and_returns_to_the_week_without_reading():
    shown = run("""
let reads = 0;
function fetch() { reads++; throw new Error("unexpected read"); }
let budget = activityFold();
document.body = node("body");
document.querySelector = selector => {
  const [, cls, key, value] = selector.match(/^#budget \\.([\\w-]+)\\[data-([\\w-]+)="([^"]+)"\\]$/);
  return every(budget).find(n => n.className.split(" ").includes(cls) && n.dataset[key] === value);
};
paintBudget = () => { painted++; budget = activityFold(); document.activeElement = document.body; };
const list = budget.children[1];
const note = list.children.find(n => n.className === "fold-note");
const button = note?.children.find(n => n.tag === "button");
const before = [text(list.children[0]), list.children.indexOf(note), note ? text(note) : null,
                button ? [button.tag, button.type, button.className] : null];
button.focus();
button._on.click();
console.log(JSON.stringify([before, activityDay, painted, reads, lines(budget)[1],
                            document.activeElement === budget.children[0]]));
""", state(day="2026-11-03"))
    assert shown == [["Tue, Nov 3 · 0 prompts · 0 tokens", 4, "Nothing on Tuesday · Show the week",
                      ["button", "button", "fold-act"]], None, 1, 0, "7 days · 1.3k prompts · 7.5B tokens", True]
    for prompts, tokens, head in [(1, 0, "Tue, Nov 3 · 1 prompt · 0 tokens"),
                                 (0, 1, "Tue, Nov 3 · 0 prompts · 1 token")]:
        report = dict(WEEK, days=[day("2026-11-03", [claude("/work/app", prompts, output=tokens)])])
        assert run("""
const list = activityFold().children[1];
console.log(JSON.stringify([text(list.children[0]), list.children.filter(n => n.className === "fold-note").map(text)]));
""", state(report=report, day="2026-11-03")) == [head, []]


def test_a_picked_day_with_more_projects_than_show_folds_the_rest_as_the_week_does():
    many = _projects(12)
    many["days"][0]["claude"].append(claude("/work/alone", 1, output=5))
    assert run(SHOW, state(report=many, day=many["days"][0]["date"]))[-1] == ["+3 more projects", "184"]


def test_a_click_on_a_days_bar_number_or_name_picks_it_a_second_click_lets_it_go_and_each_repaints():
    assert run("""
const column = cls => activityFold().children[1].children.find(c => c.className === cls).children[5];
const picks = [];
for (const cls of ["act-week", "act-nums", "act-days"]) {
  column(cls)._on.click();
  picks.push([activityDay, painted]);
  column(cls)._on.click();
  picks.push([activityDay, painted]);
}
console.log(JSON.stringify(picks));
""", state()) == [["2026-11-04", 1], [None, 2], ["2026-11-04", 3], [None, 4], ["2026-11-04", 5], [None, 6]]


def test_a_picked_day_that_the_next_report_no_longer_holds_reads_as_the_week():
    assert run(SHOW, state(day="2026-10-20"))[1] == "7 days · 1.3k prompts · 7.5B tokens"


def _report(*rows):
    """One day's report of Claude rows, each (project, tokens), or with a third item True for a Codex row."""
    return {"generated_at": 1, "conversations": [], "unread": [], "days": [day(
        "2026-11-05", [claude(row[0], 1, output=row[1]) for row in rows if len(row) == 2],
        [codex(row[0], 1, row[1]) for row in rows if len(row) == 3])]}


SPLIT = """
const split = fold => fold.children[1].children.filter(c => c.className === "act-split").map(line => {
  const bar = line.children[1];
  return [words(line), bar.attrs.role, bar.attrs["aria-label"], bars(bar)];
});
"""


def test_a_span_both_providers_worked_in_is_split_between_them_the_larger_from_the_left_each_named_at_its_end():
    shown = run(SPLIT + "console.log(JSON.stringify(split(activityFold())));",
                state(report=_report(("/work/app", 100), ("/work/app", 300, True))))
    assert shown == [[["Codex ", "300", "Claude ", "100"], "img", "Codex 300 tokens, Claude 100 tokens",
                      [["by-codex", "75"], ["by-claude", "25"]]]]


def test_a_picked_day_is_split_by_its_own_tokens_and_a_span_only_one_provider_worked_in_has_no_split():
    shown = run(SPLIT + """
const picked = date => { activityDay = date; return split(activityFold()).map(line => line[0]); };
console.log(JSON.stringify(["2026-11-05", "2026-11-04", "2026-11-01"].map(picked)));
""", state())
    assert shown == [[["Claude ", "4B", "Codex ", "500M"]], [], []]


def test_a_project_is_its_folders_name_and_two_whose_names_match_case_aside_get_the_parents_that_tell_them_apart():
    shown = run("console.log(JSON.stringify(rowsOf(activityFold()).map(named)));", state(report=_report(
        ("/work/kiln/repo", 500), ("/work/moss/repo", 400), ("/u/.claude-sessions/ocean", 300),
        ("/u/.claude-sessions/ocean/Ocean", 200), ("/work/tools/cli", 100))))
    assert shown == [
        [["act-lead", "kiln/"], ["act-base", "repo"]],
        [["act-lead", "moss/"], ["act-base", "repo"]],
        [["act-lead", ".claude-sessions/"], ["act-base", "ocean"]],
        [["act-lead", "ocean/"], ["act-base", "Ocean"]],
        [["act-base", "cli"]],
    ]


def test_three_names_that_match_take_as_many_parents_as_tell_each_from_every_other():
    shown = run("console.log(JSON.stringify(rowsOf(activityFold()).map(named)));", state(report=_report(
        ("/a/ash/apps/web", 300), ("/b/clay/apps/web", 200), ("/c/web", 100))))
    assert shown == [
        [["act-lead", "ash/apps/"], ["act-base", "web"]],
        [["act-lead", "clay/apps/"], ["act-base", "web"]],
        [["act-lead", "c/"], ["act-base", "web"]],
    ]


def test_a_name_that_matches_only_a_project_off_the_rows_still_takes_its_parents():
    report = _report(("/work/kiln/repo", 1000), *((f"/work/p{i:02}", 100 - i) for i in range(10)),
                     ("/work/moss/repo", 1))
    shown = run("console.log(JSON.stringify([named(rowsOf(activityFold())[0]), lines(activityFold()).at(-1)]));",
                state(report=report))
    assert shown == [[["act-lead", "kiln/"], ["act-base", "repo"]], ["+2 more projects", "92"]]


def test_a_picked_day_keeps_the_names_the_week_gives_its_projects():
    report = {"generated_at": 1, "conversations": [], "unread": [], "days": [
        day("2026-11-05", [claude("/work/kiln/repo", 1, output=50)]),
        day("2026-11-04", [claude("/work/moss/repo", 1, output=70)])]}
    shown = run("""
const week = rowsOf(activityFold()).map(named);
activityDay = "2026-11-05";
console.log(JSON.stringify([week, rowsOf(activityFold()).map(named)]));
""", state(report=report))
    assert shown == [[[["act-lead", "moss/"], ["act-base", "repo"]], [["act-lead", "kiln/"], ["act-base", "repo"]]],
                     [[["act-lead", "kiln/"], ["act-base", "repo"]]]]


def test_a_cs_variant_follows_the_name_and_a_scratch_dir_never_makes_a_name_match():
    report = _report(("/u/.claude-sessions/tundra@clean", 600), ("/u/.claude-sessions/tundra", 500),
                     ("/x/one/app@remote", 400), ("/x/two/app@remote", 300), ("/work/kiln/repo", 200))
    report["days"][0]["claude"].append(claude("/tmp/e2e/repo", 1, output=900, scratch=True))
    shown = run("console.log(JSON.stringify(rowsOf(activityFold()).map(named)));", state(report=report))
    assert shown == [
        [["act-base", "tundra"], ["act-variant", "@clean"]],
        [["act-base", "tundra"]],
        [["act-lead", "one/"], ["act-base", "app"], ["act-variant", "@remote"]],
        [["act-lead", "two/"], ["act-base", "app"], ["act-variant", "@remote"]],
        [["act-base", "repo"]],
    ]


def test_scratch_dirs_get_no_row_but_one_dim_line_with_their_tokens_and_the_head_still_counts_them():
    """Eleven projects and two scratch dirs: ten rows, one more project of 90 tokens, and the scratch
    dirs' 7 and 5 as 12; the head's 1.1k is all 1057 of them."""
    report = _report(*((f"/work/p{i:02}", 100 - i) for i in range(11)))
    report["days"][0]["claude"].append(claude("/tmp/e2e", 1, output=7, scratch=True))
    report["days"][0]["codex"].append(codex("/private/var/folders/jw/x1/T/probe", 1, 5, scratch=True))
    shown = run("""
const fold = activityFold();
const rests = fold.children[1].children.filter(c => c.className === "act-rest");
const paths = rowsOf(fold).map(row => row.attrs["aria-label"].split(",")[0]);
console.log(JSON.stringify([lines(fold), rests.length, paths]));
""", state(report=report))
    assert shown == [
        [["›", "Activity"], "1 day · 13 prompts · 1.1k tokens", ["Claude ", "1.1k", "Codex ", "5"],
         ["1.1k"], ["Thu"],
         *([f"p{i:02}", str(100 - i)] for i in range(10)), ["+1 more project", "90"], ["2 scratch dirs", "12"]],
        2, [f"/work/p{i:02}" for i in range(10)]]


def test_one_scratch_dir_alone_is_said_in_the_singular_under_no_rows():
    report = _report()
    report["days"][0]["claude"].append(claude("/tmp", 1, output=7, scratch=True))
    assert run(SHOW, state(report=report))[1:] == [
        "1 day · 1 prompt · 7 tokens", ["7"], ["Thu"], ["1 scratch dir", "7"]]


def test_naming_a_weeks_projects_takes_little_cpu_since_the_open_fold_draws_again_on_every_frame():
    """Three thousand projects, each of a thousand names three times over: two under parents
    that share their last part and one that does not. Naming them all takes well under the
    100 ms of CPU a frame could spare, and names them as the clash rule says."""
    shown = run("""
const paths = [];
for (let i = 0; i < 1000; i++) paths.push(`/a${i}/x/name${i}`, `/b${i}/x/name${i}`, `/c/name${i}`);
activityNames(paths);
const began = process.cpuUsage();
const names = activityNames(paths);
const spent = process.cpuUsage(began);
const ms = (spent.user + spent.system) / 1000;
console.log(JSON.stringify([ms < 100 || ms, names.size, ["/a7/x/name7", "/b7/x/name7", "/c/name7"].map(p => names.get(p))]));
""")
    assert shown == [True, 3001, [{"parents": "a7/x/", "name": "name7"}, {"parents": "b7/x/", "name": "name7"},
                                  {"parents": "c/", "name": "name7"}]]


def test_a_project_whose_week_is_cache_reads_alone_is_left_out_as_a_picked_day_leaves_it_out():
    """Eleven projects with tokens, one whose week is Claude cache reads alone, a Codex one whose
    total is all cached input, and two scratch dirs, one of them cache reads alone. The empty
    ones get no row, no place in +N more or the scratch line, and tell no name apart; their
    prompts still count in the head: 15 prompts, and 1000, 955 and 7 tokens."""
    report = _report(("/work/moss/repo", 1000), *((f"/work/p{i:02}", 100 - i) for i in range(10)))
    report["days"][0]["claude"] += [claude("/work/cached", 1, cache_read=5000),
                                    claude("/tmp/run", 1, output=7, scratch=True),
                                    claude("/tmp/cached", 1, cache_read=900, scratch=True)]
    report["days"][0]["codex"].append(codex("/work/kiln/repo", 1, 300, cached_input=300))
    shown = run("""
const fold = activityFold();
console.log(JSON.stringify([lines(fold), named(rowsOf(fold)[0])]));
""", state(report=report))
    assert shown == [
        [["›", "Activity"], "1 day · 15 prompts · 2k tokens", ["2k"], ["Thu"], ["repo", "1k"],
         *([f"p{i:02}", str(100 - i)] for i in range(9)), ["+1 more project", "91"], ["1 scratch dir", "7"]],
        [["act-base", "repo"]]]
