# ABOUTME: Guards the Details card under Serenity in the real panel: WebKit opens it from a row's menu over a real daemon.
# ABOUTME: Serenity's Details carries what its card leaves out; every other style's Details stays as it was.
"""Details is opened as a user opens it, right-click and Details, in the
WKWebView the Serenity card test builds, and read as figures, words and the
icon each one wears."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT =Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sidebar import Server, Sidebar  # noqa: E402
from test_page_serenity import probe_path  # noqa: E402,F401

TOKEN = "serenity-details-token-not-a-real-secret"


def frame(now):
    """delta carries every list Details can hold, each but the shells past
    four, a report in progress and two teammates at work; echo is a Codex card
    whose report is done; zsh is a plain terminal."""
    delta = {"session_id": "d1", "label": "delta", "state": "working", "working_since": now - 120,
             "started_at": now - 7200, "branch": "feature/quiet", "agents": 3,
             "busy_kids": 2,
             "task": {"title": "Ship the change", "activity": "Running tests", "reported_at": now - 300},
             "subagents": [{"type": "Explore", "name": "finder", "since": now - 60},
                           {"type": "Explore", "name": "reader", "since": now - 300, "ended": now - 200},
                           {"provider": "codex", "id": "job-1", "type": "rescue", "phase": "failed",
                            "since": now - 400, "ended": now - 350},
                           {"type": "general-purpose", "since": now - 30},
                           {"provider": "codex", "id": "job-2", "type": "review", "phase": "running",
                            "since": now - 20}],
             "tasks": [{"id": "1", "subject": "Write the test", "status": "pending"},
                       {"id": "2", "subject": "Watch it fail", "status": "in_progress"},
                       {"id": "3", "subject": "Build the card", "status": "pending"},
                       {"id": "4", "subject": "Shoot both themes", "status": "in_progress"},
                       {"id": "5", "subject": "Update the docs", "status": "pending"},
                       {"id": "6", "subject": "Run the suite", "status": "pending"}],
             "shells": [{"command": "npm run dev", "label": "npm run dev"},
                        {"command": "tail -f build.log", "label": "tail -f build.log"}]}
    echo = {"session_id": "e1", "label": "echo", "provider": "openai", "state": "idle", "idle_since": now - 60,
            "started_at": now - 600, "task": {"title": "Pick a name", "done": True, "reported_at": now - 30}}
    shell = {"session_id": "s1", "label": "zsh", "title": "notes.md", "branch": "main"}
    return {"groups": [{"name": "AGENTS", "rows": [delta, echo]}, {"name": "SESSIONS", "rows": [shell]}]}


SETTINGS = {"card_style": "serenity", "card_anatomy": "name", "provider_mark": "corner", "context_threshold": 40}

# The open card as it reads: the class of each part in order, the line under
# the state, each figure in the counts row and each list. An icon is named by
# the META_ICONS key that draws it.
SCRIPT = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const iconOf = svg => svg ? Object.keys(META_ICONS).find(k => metaIcon(k).innerHTML === svg.innerHTML) : null;
  // A mark is its glyph, or the class of the mark the card draws itself.
  const markOf = mk => mk ? mk.textContent || mk.classList[0] : null;
  const read = () => {
    if (card.hidden) return null;
    const where = card.querySelector(".where");
    return {
      parts: [...card.children].map(part => part.className),
      where: where && {text: where.textContent, title: where.title,
                       bits: [...where.querySelectorAll(".wbit")].map(b => [iconOf(b.querySelector("svg")), b.textContent])},
      counts: [...card.querySelectorAll(".count")].map(c => [iconOf(c.querySelector("svg")), c.querySelector("span").textContent,
                                                             c.querySelector("b").textContent, c.title]),
      lists: [...card.querySelectorAll(".dlist")].map(list => {
        const head = list.querySelector(".dhead");
        return {head: [iconOf(head.querySelector("svg")), head.querySelector("b").textContent, head.lastChild.textContent],
                face: getComputedStyle(list.querySelector(".drow")).fontFamily,
                rows: [...list.querySelectorAll(".drow")].map(r => [markOf(r.querySelector(".mk")),
                                                                    r.lastChild.textContent, r.title])};
      }),
    };
  };
  const menuOf = key => {
    closeMenu();
    hideCard();
    const row = document.querySelector(`#groups button.row[data-session-id="${key}"]`);
    row.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: 40, clientY: 40}));
    return [...openMenu.querySelectorAll('[role="menuitem"]')];
  };
  const details = key => {
    menuOf(key).find(item => item.textContent === "Details").click();
    return read();
  };
  const look = card_style => {
    SETTINGS = {...SETTINGS, card_style};
    render(LATEST, false, true);
    return {d1: details("d1"), e1: details("e1")};
  };
  try {
    for (let i = 0; !(SETTINGS && document.querySelector("#groups li.line.card")); i++) {
      if (i > 200) throw new Error("the panel never painted");
      await pause(50);
    }
    const seen = {serenity: look("serenity")};
    // A panel under the compact line, as syncCompact reads the window's width.
    const width = Object.getOwnPropertyDescriptor(window, "innerWidth");
    Object.defineProperty(window, "innerWidth", {value: 180, configurable: true});
    syncCompact();
    seen.narrow = {compact: document.documentElement.classList.contains("compact"), d1: details("d1")};
    Object.defineProperty(window, "innerWidth", width);
    syncCompact();
    seen.narrow.wideAgain = !document.documentElement.classList.contains("compact") && window.innerWidth;
    seen.sessionMenu = menuOf("s1").map(item => item.textContent);
    closeMenu();
    showCard(LATEST.groups.find(g => g.name === "SESSIONS").rows[0]);
    seen.sessionCard = read();
    for (const style of ["cards", "hairlines", "air", "inset", "outlines"]) seen[style] = look(style);
    seen.failure = paintFailure;
    post(JSON.stringify(seen));
  } catch (err) {
    post("ERROR " + err.message);
  }
  post("DONE");
})(); undefined;"""


@pytest.fixture(scope="module")
def seen(probe_path, tmp_path_factory):  # noqa: F811
    """What Details showed, once per module: the probe takes a few seconds."""
    folder = tmp_path_factory.mktemp("serenity-details")
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


SANS = "-apple-system, sans-serif"
MONO = "ui-monospace, Menlo, monospace"
UP = ["uptime", "Up", "2h", "Its process started 2h ago"]
AGENTS = ["model", "Agents", "3", "3 subagents running now"]
TODAY = {"d1": {"parts": ["who", "sub", "counts"], "where": None, "counts": [UP, AGENTS], "lists": []},
         "e1": {"parts": ["who", "sub", "counts"], "where": None,
                "counts": [["uptime", "Up", "10m", "Its process started 10m ago"]], "lists": []}}


def test_the_page_paints_every_look_without_a_failure(seen):
    assert seen["failure"] is None


def test_serenity_details_says_which_agent_on_which_branch_under_the_state(seen):
    """Each piece only when the row has it: a Codex card with no branch says
    only Codex."""
    delta, echo = seen["serenity"]["d1"], seen["serenity"]["e1"]
    assert delta["where"] == {"text": "Claude · feature/quiet", "title": "Claude · feature/quiet",
                              "bits": [[None, "Claude"], ["branch", "feature/quiet"]]}
    assert echo["where"] == {"text": "Codex", "title": "Codex", "bits": [[None, "Codex"]]}
    assert delta["parts"][:3] == ["who", "sub", "where"]


def test_serenity_details_counts_the_report_age_and_working_teammates_after_the_others(seen):
    """No Report once the report is done, and no Teammates with none at work."""
    assert seen["serenity"]["d1"]["counts"] == [
        UP, AGENTS,
        ["clock", "Report", "5m", "The session reported on its task 5m ago"],
        ["model", "Teammates", "2", "2 teammates are working"]]
    assert seen["serenity"]["e1"]["counts"] == TODAY["e1"]["counts"]


def test_serenity_details_lists_subagents_tasks_and_shells_four_each_after_the_counts(seen):
    """Subagents named as the card names them, a failed Codex job marked as
    failed and not finished; tasks started first; shells in the mono face."""
    delta = seen["serenity"]["d1"]
    assert delta["parts"] == ["who", "sub", "where", "counts", "dlist", "dlist", "dlist"]
    assert delta["lists"] == [
        {"head": ["model", "5", "Subagents"], "face": SANS,
         "rows": [["●", "finder", "finder"], ["✓", "reader", "reader"],
                  ["✕", "Codex rescue · failed", "Codex rescue · failed"],
                  ["●", "general-purpose", "general-purpose"], [None, "+1 more", ""]]},
        {"head": ["checked", "6", "Tasks"], "face": SANS,
         "rows": [["started-mark", "Watch it fail", "Watch it fail"],
                  ["started-mark", "Shoot both themes", "Shoot both themes"],
                  ["todo-mark", "Write the test", "Write the test"], ["todo-mark", "Build the card", "Build the card"],
                  [None, "+2 more", ""]]},
        {"head": ["shells", "2", "Shells"], "face": MONO,
         "rows": [["$", "npm run dev", "npm run dev"], ["$", "tail -f build.log", "tail -f build.log"]]}]
    assert seen["serenity"]["e1"]["lists"] == []


def test_every_other_style_keeps_todays_details(seen):
    """No line under the state, no Report or Teammates, no lists."""
    assert {style: seen[style] for style in ("cards", "hairlines", "air", "inset", "outlines")} == \
        {style: TODAY for style in ("cards", "hairlines", "air", "inset", "outlines")}


def test_a_narrow_panel_keeps_todays_details_under_serenity(seen):
    """At compact width a Serenity card is Cards' compact card, so Details is too."""
    assert seen["narrow"] == {"compact": True, "d1": TODAY["d1"], "wideAgain": 380}


def test_a_plain_terminal_has_no_details_under_serenity(seen):
    """Its menu offers no Details, and the card stays shut when asked for one."""
    assert (seen["sessionMenu"], seen["sessionCard"]) == (["Close"], None)
