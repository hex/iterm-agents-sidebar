# ABOUTME: Guards the Serenity card style in the real panel: WebKit loads page.html from a real daemon serving one frame.
# ABOUTME: A Serenity agent card keeps only what changes what you do; the same frame under Cards keeps everything.
"""buildGroups needs a DOM a node stub cannot carry without becoming the thing
under test, so this drives the page as a Toolbelt does: a WKWebView, the
probe tests/test_panel_webkit.py builds, a daemon serving the frame and the
settings file. The script flips the look in the page and reads each card."""
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sidebar import Server, Sidebar  # noqa: E402
from test_panel_webkit import PROBE, window_server  # noqa: E402

TOKEN = "serenity-token-not-a-real-secret"


def frame(now):
    """Three agent cards and a plain terminal. alpha carries every fact a card
    can and a teammate an hour into its turn, with a worktree docked under it;
    bravo is mid-report with a teammate behind an editor, so a prompt to it is
    refused; charlie rests on words that hand you the move, with a teammate
    waiting on you."""
    alpha = {"session_id": "a1", "label": "alpha", "state": "working", "working_since": now - 120,
             "branch": "feature/quiet", "model": "opus", "effort": "high", "host": "build-box",
             "context": 74, "heavy": ["cpu"], "busy_kids": 1,
             "subagents": [{"type": "Explore", "name": "finder", "since": now - 60},
                           {"type": "Explore", "name": "reader", "since": now - 300, "ended": now - 200}],
             "tasks": [{"id": "1", "subject": "Write the test", "status": "in_progress"}],
             "crons": [{"id": "c1", "prompt": "check the build", "when": "every 5 m", "recurring": True,
                        "next": now + 300}],
             "shells": [{"command": "npm run dev", "label": "npm run dev"}],
             "task": {"title": "Ship the change", "done": True, "reported_at": now - 30}}
    helper = {"session_id": "a1m", "label": "helper", "depth": 1, "state": "working", "working_since": now - 3700}
    fork = {"session_id": "a2", "label": "alpha-fork", "state": "idle", "idle_since": now - 60, "worktree_of": "a1"}
    bravo = {"session_id": "b1", "label": "bravo", "state": "working", "working_since": now - 60,
             "branch": "main", "model": "sonnet", "context": 60,
             "task": {"title": "Run the suite", "activity": "Running tests", "percent": 40, "reported_at": now - 30}}
    scribe = {"session_id": "b1m", "label": "scribe", "depth": 1, "state": "idle", "idle_since": now - 60,
              "in_front": "vim"}
    charlie = {"session_id": "c1", "label": "charlie", "state": "idle", "idle_since": now - 60,
               "task": {"title": "Pick a name", "activity": "Waiting for you to choose", "reported_at": now - 30}}
    asker = {"session_id": "c1m", "label": "asker", "depth": 1, "state": "blocked", "blocked_since": now - 10,
             "question": {"tool": "Bash", "summary": "rm -rf build", "id": "q-1"}}
    shell = {"session_id": "s1", "label": "zsh", "title": "notes.md", "branch": "main"}
    return {"groups": [{"name": "AGENTS", "rows": [alpha, helper, fork, bravo, scribe, charlie, asker]},
                       {"name": "SESSIONS", "rows": [shell]}]}


SETTINGS = {"card_style": "serenity", "card_anatomy": "name", "provider_mark": "corner", "context_threshold": 40}

# Every card's reading in one look, keyed by session. The facts are the card's
# own row's facts line, children the rows inside it; the refusals say whether a
# refusal sits on the card itself or inside its children. The ground is how the
# card stands on the canvas as WebKit computes it: its fill, its shadow, the
# rule painted along its top, the gap under it and whether it draws a cluster's
# outline; the pill and the bar are a working card's.
READ = """
const read = () => {
  const out = {};
  for (const li of document.querySelectorAll("#groups li.line.card")) {
    const own = li.querySelector(":scope > button.row");
    const all = selector => [...li.querySelectorAll(selector)];
    const style = getComputedStyle(li);
    const pill = own.querySelector(".word.working");
    const bar = own.querySelector(".task-bar");
    out[li.dataset.key] = {
      ground: {fill: style.backgroundColor, shadow: style.boxShadow,
               rule: style.backgroundImage === "none" ? null : [style.backgroundPosition, style.backgroundSize],
               gap: style.marginBottom, outline: !["none", "normal"].includes(getComputedStyle(li, "::after").content)},
      pill: pill && [getComputedStyle(pill).fontWeight, getComputedStyle(pill).backgroundColor],
      bar: bar && [getComputedStyle(bar).height, getComputedStyle(bar).opacity],
      facts: [...(own.querySelector(":scope > .stack > .model")?.children || [])].map(c => c.className),
      children: all(".children button.row").map(b => b.dataset.sessionId + (b.querySelector(".asks") ? " asks" : "")),
      sums: all(".shell-sum").map(s => s.className),
      notes: all(".serene-note").map(n => n.textContent),
      marks: own.querySelectorAll(".pcorner, .ptag").length,
      ages: all(".task-age").length,
      done: all(".task-done").length,
      activity: all(".task-activity").map(a => `${a.className}: ${a.textContent}`),
      recency: all(".card-recency").length,
      status: all(".task-status").map(s => s.textContent),
      bars: all(".task-bar").length,
      refusals: all(".refusal").map(p => [p.parentElement === li ? "card" : p.parentElement.className, p.textContent]),
    };
  }
  return {style: document.documentElement.dataset.cardStyle, failure: paintFailure, cards: out};
};
"""

SCRIPT = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  %s
  // A card eases its fill to a new ground, which the probe's window was seen to
  // hold at its start, so each reading is taken with every ease run to its end.
  const settled = () => {
    for (const ease of document.getAnimations()) if (ease instanceof CSSTransition) ease.finish();
    return read();
  };
  const look = (card_style, card_anatomy, provider_mark) => {
    SETTINGS = {...SETTINGS, card_style, card_anatomy, provider_mark};
    render(LATEST, false, true);
    return settled();
  };
  try {
    for (let i = 0; !(SETTINGS && document.querySelector("#groups li.line.card")); i++) {
      if (i > 200) throw new Error("the panel never painted");
      await pause(50);
    }
    const seen = {first: settled()};
    seen.serenityTag = look("serenity", "name", "tag");
    seen.serenityTask = look("serenity", "task", "corner");
    seen.cardsTask = look("cards", "task", "corner");
    seen.cardsTag = look("cards", "name", "tag");
    seen.cardsName = look("cards", "name", "corner");
    look("serenity", "name", "corner");
    prompt("b1m", "hello");
    for (let i = 0; !document.querySelector("#groups .refusal"); i++) {
      if (i > 100) throw new Error("the refusal never showed");
      await pause(50);
    }
    seen.refusedSerenity = settled();
    seen.refusedCards = look("cards", "name", "corner");
    post(JSON.stringify(seen));
  } catch (err) {
    post("ERROR " + err.message);
  }
  post("DONE");
})(); undefined;""" % READ


@pytest.fixture(scope="module")
def probe_path(tmp_path_factory):
    if sys.platform != "darwin":
        pytest.skip("WKWebView is macOS only")
    if shutil.which("clang") is None:
        pytest.skip("no clang to build the probe")
    if not window_server():
        pytest.skip("no window server for the panel")
    folder = tmp_path_factory.mktemp("probe")
    (folder / "probe.m").write_text(PROBE)
    built = subprocess.run(["clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "WebKit",
                            str(folder / "probe.m"), "-o", str(folder / "probe")], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return folder / "probe"


@pytest.fixture(scope="module")
def seen(probe_path, tmp_path_factory):
    """What the panel showed, once per module: the probe takes a few seconds."""
    folder = tmp_path_factory.mktemp("serenity")
    (folder / "settings.json").write_text(json.dumps(SETTINGS))
    payload = frame(time.time())

    async def look():
        sidebar = Sidebar(token=TOKEN, page_path=ROOT / "page.html", snapshot_fn=lambda: payload,
                          action_fn=lambda *a: None, settings_path=folder / "settings.json")
        port = await Server(sidebar).start()
        probe = await asyncio.create_subprocess_exec(
            str(probe_path), f"http://127.0.0.1:{port}/?token={TOKEN}", "1", SCRIPT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(probe.communicate(), timeout=30)
        finally:
            if probe.returncode is None:
                probe.kill()
                await probe.wait()
        return probe.returncode, out.decode().splitlines(), err.decode()

    code, lines, err = asyncio.run(look())
    assert code == 0, (lines, err[-2000:])
    readings = [line for line in lines if line.startswith("{")]
    assert len(readings) == 1, lines
    return json.loads(readings[0])


def card(**reading):
    """A name-first card's reading with nothing on it but what is named."""
    return {"facts": [], "children": [], "sums": [], "notes": [], "marks": 0, "ages": 0, "done": 0,
            "activity": [], "recency": 0, "bars": 0, "refusals": [], **reading}


def name_first(look):
    """What each card says in a name-first look. Its status line runs the
    activity into the report's age, so the parts are read one by one instead."""
    said = lambda c: {field: value for field, value in c.items() if field not in ("status", "ground", "pill", "bar")}
    return {key: said(c) for key, c in look["cards"].items()}


def test_the_daemon_keeps_serenity_and_the_page_paints_without_a_failure(seen):
    assert (seen["first"]["style"], seen["first"]["failure"]) == ("serenity", None)
    assert [look["failure"] for look in seen.values()] == [None] * len(seen)


def test_a_serenity_card_shows_only_what_changes_what_you_do(seen):
    """The host, a heavy process tree and a context past 70% stay; the branch,
    the model and its effort, the busy teammates, the provider's corner mark,
    the report's age and Complete go; no list is drawn. A teammate an hour in
    is a note on its card, a teammate waiting on you keeps its row and its
    question, and owed words stay. A plain terminal keeps its tab title and
    branch: they are the only line it has."""
    assert name_first(seen["first"]) == {
        "a1": card(facts=["mchip host-mark", "mchip ctx", "mchip heavy"], notes=["helper · Long 1h"]),
        "a2": card(),
        "b1": card(bars=1),
        "c1": card(children=["c1m asks"], activity=["task-activity owed: Waiting for you to choose"]),
        "s1": card(facts=["mchip title", "mchip branch"]),
    }


def test_the_same_frame_under_cards_keeps_every_fact_and_list(seen):
    assert name_first(seen["cardsName"]) == {
        "a1": card(facts=["mchip host-mark", "mchip branch", "mchip model-name", "effort high", "mchip kids",
                          "mchip ctx", "mchip heavy"],
                   children=["a1m", "a1", "a1"], sums=["shell-sum tasks-sum", "shell-sum crons-sum", "shell-sum"],
                   marks=1, done=1),
        "a2": card(marks=1),
        "b1": card(facts=["mchip branch", "mchip model-name", "mchip ctx"], children=["b1m"], marks=1, ages=1,
                   activity=["task-activity: Running tests"], bars=1),
        "c1": card(children=["c1m asks"], marks=1, ages=1, activity=["task-activity owed: Waiting for you to choose"]),
        "s1": card(facts=["mchip title", "mchip branch"]),
    }


def test_serenity_drops_the_provider_tag_as_it_drops_the_corner_mark(seen):
    assert {key: c["marks"] for key, c in seen["serenityTag"]["cards"].items()} == \
        {"a1": 0, "a2": 0, "b1": 0, "c1": 0, "s1": 0}
    assert {key: c["marks"] for key, c in seen["cardsTag"]["cards"].items()} == \
        {"a1": 1, "a2": 1, "b1": 1, "c1": 1, "s1": 0}


def test_a_task_first_serenity_card_drops_its_clock_and_says_only_owed_words(seen):
    """The bar carries the percent, so the words under it go, but for the
    words that hand you the move."""
    pick = lambda look: {key: (c["recency"], c["status"], c["bars"]) for key, c in seen[look]["cards"].items()}
    assert pick("serenityTask") == {"a1": (0, [], 1), "a2": (0, [], 0), "b1": (0, [], 1),
                                    "c1": (0, ["Waiting for you to choose"], 0), "s1": (0, [], 0)}
    assert pick("cardsTask") == {"a1": (1, ["100%"], 1), "a2": (0, [], 0), "b1": (1, ["40% · Running tests"], 1),
                                 "c1": (0, ["Waiting for you to choose"], 0), "s1": (0, [], 0)}


def test_a_refused_prompt_to_an_undrawn_teammate_says_why_on_its_card(seen):
    """Under Cards the reason goes under the teammate's own line; under
    Serenity that line is not drawn, so it goes under the card."""
    refusal = "not sent: vim is in front"
    assert seen["refusedSerenity"]["cards"]["b1"]["refusals"] == [["card", refusal]]
    assert seen["refusedCards"]["cards"]["b1"]["refusals"] == [["children", refusal]]


CLEAR = "rgba(0, 0, 0, 0)"
RULE = ["12px 0px", "calc(100% - 24px) 1px"]


def test_a_serenity_session_stands_on_the_canvas_with_a_rule_between_plain_ones(seen):
    """No fill and no shadow; 10px under each session and none inside a
    worktree cluster, which keeps its outline; an inset rule over a plain
    session after a plain one or after a cluster, none over a cluster's own
    worktree. A waiting card keeps the whole card Cards gives it."""
    serene, cards = seen["first"]["cards"], seen["cardsName"]["cards"]
    plain = lambda **ground: {"fill": CLEAR, "shadow": "none", "rule": None, "gap": "10px", "outline": False, **ground}
    assert {key: c["ground"] for key, c in serene.items()} == {
        "a1": plain(gap="0px", outline=True), "a2": plain(outline=True), "b1": plain(rule=RULE),
        "c1": {**cards["c1"]["ground"], "gap": "10px"}, "s1": plain()}
    assert {key: (c["ground"]["rule"], c["ground"]["gap"], c["ground"]["outline"]) for key, c in cards.items()} == {
        "a1": (None, "0px", True), "a2": (None, "6px", True), "b1": (None, "6px", False), "c1": (None, "6px", False),
        "s1": (None, "6px", False)}
    assert CLEAR not in [cards[key]["ground"]["fill"] for key in ("a1", "a2", "b1", "s1")]


def test_working_reads_as_plain_words_and_the_bar_as_a_thin_line(seen):
    serene, cards = seen["first"]["cards"], seen["cardsName"]["cards"]
    assert (serene["b1"]["pill"], serene["b1"]["bar"]) == (["500", CLEAR], ["2px", "0.55"])
    assert (cards["b1"]["pill"][0], cards["b1"]["bar"]) == ("600", ["3px", "1"])
    assert cards["b1"]["pill"][1] != CLEAR
