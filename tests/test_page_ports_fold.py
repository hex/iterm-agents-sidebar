# ABOUTME: Checks the Ports fold in the panel foot: its head, a row's text and hover, the folded other
# ABOUTME: listeners and what Stop sends. Runs the page's own functions under Node over a stand-in DOM.
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
NOW = 1789646400

# Elements as plain objects: enough for the builders to set text, classes and
# attributes and append children, and for `lines` to read back what shows.
DOM = """
function node(tag) {
  return {tag, className: "", textContent: "", title: "", type: "", disabled: false, children: [], attrs: {},
          append(...kids) { this.children.push(...kids); },
          setAttribute(name, value) { this.attrs[name] = value; }};
}
const document = {createElement: node};
function on(el, type, handler) { (el._on ||= {})[type] = handler; }
// Each row, head and status line as the words it shows, in order.
function lines(el, out = []) {
  const words = n => n.children.length ? n.children.flatMap(words) : (n.textContent ? [n.textContent] : []);
  if (/past-row|lim-toggle|acct-status|fold-note/.test(el.className)) out.push(words(el));
  else el.children.forEach(child => lines(child, out));
  return out;
}
"""


def run(body, state):
    page = "\n".join([re.search(r"\nconst PORT_STOP_HOLD = .*;\n", PAGE).group(0),
                     re.search(r"\nconst clock = .*?\n\};\n", PAGE, re.S).group(0)]
                     + [function(PAGE, name) for name in ("forHumans", "portLine", "portsFold", "stopPort", "readPorts")])
    setup = f"""{DOM}
Date.now = () => {NOW * 1000};
const TOKEN = "t";
let lastSnapshot = {{groups: []}};
let painted = 0;
function paintBudget() {{ painted++; }}
{state}
"""
    result = subprocess.run(["node", "-e", "\n".join([setup, page, body])],
                            capture_output=True, text=True, check=True, timeout=10, env={**os.environ, "TZ": "Europe/Bucharest"})
    return json.loads(result.stdout)


ROWS = [
    {"port": 3000, "addresses": ["127.0.0.1"], "pid": 4300, "program": "server.js", "command": "node /work/api/server.js",
     "started_at": NOW - 3600, "session_id": "pane-b", "session": "beta"},
    {"port": 5173, "addresses": ["*", "[::1]"], "pid": 4100, "program": "vite",
     "command": "node /work/app/node_modules/.bin/vite --port 5173 --token ***",
     "started_at": NOW - 12000, "session_id": "pane-a", "session": "alpha"},
    {"port": 7000, "addresses": ["*"], "pid": 900, "program": "ControlCenter", "command": "/x/ControlCenter",
     "started_at": NOW - 2 * 86400, "session_id": None, "session": None},
    {"port": 8787, "addresses": ["127.0.0.1"], "pid": 4200, "program": "serve.py", "command": "python3 serve.py",
     "started_at": NOW - 60, "session_id": None, "session": None},
]


def state(open=True, others=False, rows=ROWS, error=None, stopping="[]", reading=False):
    return (f"let portOpen = {json.dumps(open)}; let portOthersOpen = {json.dumps(others)};"
            f" let portRows = {json.dumps(rows)}; let portError = {json.dumps(error)};"
            f" let portReadAt = {NOW};"
            f" let portReads = {int(reading)};"
            f" const portStopping = new Map({stopping});")


SHOW = "console.log(JSON.stringify(lines(portsFold())));"


def test_the_closed_fold_is_its_head_alone():
    assert run(SHOW, state(open=False)) == [["›", "Ports"]]


def test_the_ports_head_has_an_accessible_description_without_a_system_tooltip():
    assert run("""
const head = portsFold().children[0];
console.log(JSON.stringify([head.title, head.attrs["aria-label"]]));
""", state(open=False)) == ["", "Ports: what listens on this Mac, the panel's sessions' first, and Stop"]


def test_the_open_fold_lists_the_sessions_listeners_and_folds_the_rest_under_one_line():
    assert run(SHOW, state()) == [
        ["›", "Ports"],
        [":3000", "server.js", "beta", "1h", "Stop"],
        [":5173", "vite", "alpha", "3h 20m", "Stop"],
        ["›", "2 other listeners"],
    ]


def test_the_other_listeners_open_under_their_line():
    assert run(SHOW, state(others=True)) == [
        ["›", "Ports"],
        [":3000", "server.js", "beta", "1h", "Stop"],
        [":5173", "vite", "alpha", "3h 20m", "Stop"],
        ["›", "2 other listeners"],
        [":7000", "ControlCenter", "2d", "Stop"],
        [":8787", "serve.py", "1m", "Stop"],
    ]


def test_listeners_outside_agents_say_so_in_the_folded_line_with_the_count():
    assert run(SHOW, state(rows=ROWS[3:])) == [["›", "Ports"], ["›", "1 listener, none under an agent"]]
    assert run(SHOW, state(rows=ROWS[2:])) == [["›", "Ports"], ["›", "2 listeners, none under an agent"]]


def test_a_rows_hover_gives_each_address_with_its_port_the_pid_and_the_command():
    assert run("console.log(JSON.stringify(portsFold().children[1].children.map(c => c.title)));", state()) == [
        "127.0.0.1:3000\npid 4300\nnode /work/api/server.js",
        "*:5173, [::1]:5173\npid 4100\nnode /work/app/node_modules/.bin/vite --port 5173 --token ***",
        "",
    ]


def test_the_fold_shows_nothing_while_it_reads_and_says_when_the_reading_failed_and_when_nothing_listens():
    assert [run(SHOW, s) for s in (state(rows=None), state(rows=None, error="could not run lsof: gone"),
                                   state(rows=[]))] == [
        [["›", "Ports"]],
        [["›", "Ports"], ["could not run lsof: gone"]],
        [["›", "Ports"], ["No listener found at ", "15:00", " · ", "Look again"]],
    ]


def test_the_first_ports_read_reserves_three_rows_with_a_port_pill_and_a_reading_head():
    assert run("""
const fold = portsFold();
const placeholder = fold.children[1].children[0];
console.log(JSON.stringify([fold.children[0].className, placeholder?.className, placeholder?.attrs["aria-hidden"],
  placeholder?.children.map(row => [row.className, row.children.map(bar => [bar.tag, bar.className])])]));
""", state(rows=None, reading=True)) == [
        "lim-toggle reading", "unlit", "true",
        [["u-row", [["i", "pill"], ["i", "prog"], ["i", "sess"], ["i", "age"]]] for _ in range(3)],
    ]


def test_a_ports_reread_keeps_cached_rows_and_stops_reading_after_a_refusal():
    for rows in ([], ROWS[:1]):
        assert run("""
let answer;
function fetch() { return new Promise(resolve => { answer = resolve; }); }
readPorts();
const during = portsFold();
const pending = [portReads > 0, painted, lines(during), during.children[1].children.some(n => n.className === "unlit")];
answer({ok: false, status: 503, json: async () => ({error: "ports unavailable"})});
setImmediate(() => console.log(JSON.stringify([pending, portReads > 0, portReadAt, lines(portsFold())])));
""", state(rows=rows)) == [
            [True, 1, [["›", "Ports"], *([["No listener found at ", "15:00", " · ", "Look again"]] if not rows else
                                      [[":3000", "server.js", "beta", "1h", "Stop"]])], False],
            False, NOW, [["›", "Ports"], ["ports unavailable"], *([] if not rows else
                       [[":3000", "server.js", "beta", "1h", "Stop"]])],
        ]


def test_overlapping_ports_reads_keep_the_gauge_until_both_requests_finish():
    assert run("""
const answers = [];
function fetch() { return new Promise(resolve => answers.push(resolve)); }
readPorts();
readPorts();
answers[0]({ok: true, json: async () => ({rows: []})});
setImmediate(() => {
  const midway = portsFold().children[0].className;
  answers[1]({ok: true, json: async () => ({rows: []})});
  setImmediate(() => console.log(JSON.stringify([answers.length, midway, portsFold().children[0].className])));
});
""", state(rows=[])) == [2, "lim-toggle reading", "lim-toggle"]


def test_a_stop_under_way_waits_and_a_refused_one_says_why_under_its_row():
    stopping = json.dumps([["4300:3000:" + str(NOW - 3600), {"at": NOW * 1000 - 2000, "error": None}],
                           ["4100:5173:" + str(NOW - 12000), {"at": NOW * 1000 - 2000, "error": "already gone"}]])
    shown = run("""
const fold = portsFold();
console.log(JSON.stringify([lines(fold), fold.children[1].children[0].children.at(-1).disabled]));
""", state(stopping=stopping))
    assert shown == [[
        ["›", "Ports"],
        [":3000", "server.js", "beta", "1h", "stopping…"],
        [":5173", "vite", "alpha", "3h 20m", "Stop"],
        ["already gone"],
        ["›", "2 other listeners"],
    ], True]


def test_look_again_is_a_button_and_dates_the_reading_when_it_lands():
    assert run("""
const asked = [];
let answer;
function fetch(url) { asked.push(url); return new Promise(resolve => { answer = resolve; }); }
const button = portsFold().children[1].children[0].children.at(-1);
button._on.click();
const before = [portReadAt, portReads > 0];
Date.now = () => 1789646525000;
answer({ok: true, json: async () => ({rows: []})});
setImmediate(() => console.log(JSON.stringify([button.tag, button.type, asked, before, portReadAt, portReads > 0, lines(portsFold())])));
""", state(rows=[])) == [
        "button", "button", ["/ports?token=t"], [NOW, True], 1789646525, False,
        [["›", "Ports"], ["No listener found at ", "15:02", " · ", "Look again"]],
    ]


def test_a_stop_from_fifteen_seconds_ago_offers_stop_again():
    stopping = json.dumps([["4300:3000:" + str(NOW - 3600), {"at": NOW * 1000 - 15000, "error": None}]])
    shown = run("""
const fold = portsFold();
console.log(JSON.stringify([lines(fold)[1], fold.children[1].children[0].children.at(-1).disabled]));
""", state(stopping=stopping))
    assert shown == [[":3000", "server.js", "beta", "1h", "Stop"], False]


FETCH = """
const asked = [];
const timers = [];
function setTimeout(fn, ms) { timers.push(ms); if (ms === 1000) fn(); }
function fetch(url, init) {
  asked.push([url, init?.method || "GET", init?.body || null]);
  const answer = url.startsWith("/stop-port") ? STOP_ANSWER : {status: 200, body: {rows: []}};
  return Promise.resolve({ok: answer.status === 200, status: answer.status, json: async () => answer.body});
}
"""


def test_stop_sends_the_rows_pid_port_and_start_and_reads_the_ports_again_a_second_later():
    shown = run(FETCH + """
stopPort(portRows[0]);
setImmediate(() => setImmediate(() => console.log(JSON.stringify(
  [asked, timers, [...portStopping.entries()]]))));
""", state() + 'const STOP_ANSWER = {status: 200, body: {ok: true}};')
    assert shown == [
        [["/stop-port?token=t", "POST", '{"pid":4300,"port":3000,"started_at":1789642800}'],
         ["/ports?token=t", "GET", None]],
        [15000, 1000],
        [["4300:3000:1789642800", {"at": NOW * 1000, "error": None}]],
    ]


def test_a_stop_the_daemon_refuses_keeps_its_reason_for_the_row():
    shown = run(FETCH + """
stopPort(portRows[0]);
setImmediate(() => setImmediate(() => console.log(JSON.stringify([asked.length, [...portStopping.entries()]]))));
""", state() + 'const STOP_ANSWER = {status: 409, body: {error: "pid 4300 is another program now"}};')
    assert shown == [1, [["4300:3000:1789642800", {"at": NOW * 1000, "error": "pid 4300 is another program now"}]]]


def test_a_port_row_wears_the_panels_pill_on_its_port_and_shows_stop_only_under_the_pointer():
    """The port is the state pill's shape; Stop stays hidden until the pointer or focus is on
    the row, or while a stop is under way, so twenty listeners are not twenty buttons."""
    assert run("""
const rows = portsFold().children[1].children.filter(r => /past-row/.test(r.className));
console.log(JSON.stringify(rows.map(r => [r.className, r.children[0].className])));
""", state()) == [["past-row port", "word port-no"], ["past-row port", "word port-no"]]
    assert "#budget .past-row.port .past-go { visibility: hidden; }" in PAGE
    assert ("#budget .past-row.port:hover .past-go, #budget .past-row.port:focus-within .past-go,\n"
            "  #budget .past-row.port .past-go:disabled { visibility: visible; }") in PAGE
