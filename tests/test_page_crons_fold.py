# ABOUTME: Checks a card's scheduled-prompts fold: the head with its count, a row per prompt with its mark and
# ABOUTME: the daemon's words for its run, and what a click does. Runs page.html's builder under Node on a small DOM.
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")

#: Nodes that keep their children, classes, text, title and attributes, and
#: an icon that says which one it is; on() is the page's own.
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.attrs = {};
                     this.className = ""; this.textContent = ""; this.title = ""; this.id = "";
                     this.classList = {add: (...names) => { this.className = [this.className, ...names].filter(Boolean).join(" "); }}; }
  append(...kids) { this.children.push(...kids); }
  setAttribute(name, value) { this.attrs[name] = value; }
}
const document = {createElement: tag => new Node(tag)};
function metaIcon(kind) { return Object.assign(new Node("svg"), {className: "mi", icon: kind}); }
const dump = n => typeof n === "string" ? n : {
  tag: n.tag, ...(n.className && {class: n.className}), ...(n.icon && {icon: n.icon}), ...(n.id && {id: n.id}),
  ...(n.textContent && {text: n.textContent}), ...(n.title && {title: n.title}),
  ...(Object.keys(n.dataset).length && {data: n.dataset}), ...(Object.keys(n.attrs).length && {attrs: n.attrs}),
  ...(n.children.length && {kids: n.children.map(dump)})};
let LATEST = {groups: []};
const rendered = [], acted = [];
const render = snapshot => rendered.push(snapshot);
const act = (sessionId, verb) => acted.push([sessionId, verb]);
"""

CRONS = [
    {"id": "6ba43431", "schedule": "*/10 * * * *", "recurring": True, "prompt": "say hello",
     "next": 1793885400, "when": "every 10 min"},
    {"id": "20c147b9", "schedule": "31 13 * * *", "recurring": False, "prompt": "wake me",
     "next": 1793885460, "due": True, "when": "due"},
    {"id": "c0ffee00", "schedule": "every 5m", "recurring": True, "prompt": "check in", "next": None,
     "when": "every 5m"},
]
ROW = {"session_id": "s1", "label": "alpha", "crons": CRONS}


def run(body):
    script = "\n".join([DOM, "const openCrons = new Set();", function(PAGE, "on"), function(PAGE, "childRow"),
                        function(PAGE, "stackOf"), function(PAGE, "cronsFold"), f"const ROW = {json.dumps(ROW)};", body])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


HEAD = {"tag": "button", "class": "shell-sum crons-sum",
        "title": "3 scheduled: prompts the session set to run later, as listed when its last turn ended",
        "data": {"childKey": "crons"},
        "kids": [{"tag": "svg", "class": "mi", "icon": "clock"},
                 {"tag": "span", "kids": [{"tag": "span", "class": "n", "text": "3"}, " scheduled"]},
                 {"tag": "span", "class": "chev", "text": "›"}]}


def test_a_closed_fold_is_one_line_saying_how_many_prompts_are_scheduled():
    assert run("const li = new Node('li'); cronsFold(li, ROW); console.log(JSON.stringify(li.children.map(dump)));") == [
        dict(HEAD, attrs={"aria-expanded": "false", "aria-controls": "crons-s1",
                          "aria-label": "3 scheduled prompts in alpha"})]


def test_one_scheduled_prompt_is_said_in_the_singular():
    assert run("""
const li = new Node('li'); cronsFold(li, {...ROW, crons: ROW.crons.slice(0, 1)});
console.log(JSON.stringify(li.children[0].attrs["aria-label"]));
""") == "1 scheduled prompt in alpha"


def row(key, kind, mark, label, chip, said):
    return {"tag": "button", "class": "row agent child tail", "title": label,
            "data": {"childKey": f"cron\n{key}", "sessionId": "s1"},
            "attrs": {"aria-label": f"{kind} prompt, {said}: {label}"},
            "kids": [{"tag": "svg", "class": "mi cron-mark", "icon": mark},
                     {"tag": "span", "class": "stack", "kids": [{"tag": "span", "class": "label", "text": label}]},
                     {"tag": "span", "class": chip, "kids": [{"tag": "span", "class": "mtext", "text": said}]}]}


def test_an_open_fold_has_a_row_per_prompt_with_its_mark_its_words_and_its_whole_prompt_in_the_hover():
    """A recurring prompt wears the again mark and a one-shot the clock; a due
    one's words take the warning ink, and an expression the daemon could not
    read is shown as written, in the terminal's face."""
    assert run("""
openCrons.add("s1");
const li = new Node('li'); cronsFold(li, ROW);
console.log(JSON.stringify(li.children.map(dump)));
""") == [
        dict(HEAD, attrs={"aria-expanded": "true", "aria-controls": "crons-s1",
                          "aria-label": "3 scheduled prompts in alpha"}),
        {"tag": "div", "class": "children shell-rows", "id": "crons-s1", "kids": [
            row("6ba43431", "recurring", "again", "say hello", "mchip cron-when", "every 10 min"),
            row("20c147b9", "one-shot", "clock", "wake me", "mchip cron-when due", "due"),
            row("c0ffee00", "recurring", "again", "check in", "mchip cron-when raw", "every 5m"),
        ]},
    ]


def test_the_head_opens_and_closes_the_fold_and_a_row_brings_its_session_forward():
    assert run("""
const seen = [];
const li = new Node('li'); cronsFold(li, ROW);
li.children[0]._on.click(); seen.push([...openCrons], rendered.length);
li.children[0]._on.click(); seen.push([...openCrons], rendered.length);
openCrons.add("s1");
const open = new Node('li'); cronsFold(open, ROW);
open.children[1].children[1]._on.click();
console.log(JSON.stringify([seen, acted]));
""") == [[["s1"], 1, [], 2], [["s1", "focus"]]]
