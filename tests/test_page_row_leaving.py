# ABOUTME: Guards what a card leaves behind in the real panel: WebKit loads page.html from a real daemon and repaints it.
# ABOUTME: A shell hidden by the setting never reads as finished, Details goes with its session, and a late read does not fade in.
"""The line, the card and the breakdown are all built by the page's own
paint, so the page runs as a Toolbelt runs it: a WKWebView over a real daemon
serving one frame. Later frames go through onSnapshot, as the socket's do."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sidebar import Server, Sidebar  # noqa: E402
from test_page_serenity import probe_path  # noqa: E402,F401

TOKEN = "row-leaving-token-not-a-real-secret"
SHELL = {"command": "npm run dev", "label": "npm run dev"}
CONTEXT = {"categories": [{"name": "Messages", "tokens": 1000}], "used": 1000, "window": 200000, "items": {}}


def agent(session_id, label, **more):
    return {"session_id": session_id, "label": label, "state": "idle", "idle_since": time.time() - 60, "model": "opus",
            "context_readable": True, **more}


SCRIPT = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (what, done) => {
    for (let i = 0; !done(); i++) {
      if (i > 150) throw new Error(`${what} never came`);
      await pause(20);
    }
  };
  const li = sid => document.querySelector(`#groups li.line.card[data-key="${sid}"]`);
  const frameWith = (...rows) => ({...LATEST, groups: [{name: "AGENTS", rows}]});
  const arrive = frame => onSnapshot(JSON.stringify(frame));
  // The card's own lines: one that left fades in a holder beneath them. The running line's sweep repeats its words,
  // so it is read by its label; the finished line has none.
  const shellLine = sid => [...li(sid).querySelectorAll(":scope > .shell-sum")].map(s => s.getAttribute("aria-label") ?? s.textContent);
  const details = sid => {
    closeMenu();
    hideCard();
    document.querySelector(`#groups button.row[data-session-id="${sid}"]`)
      .dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: 40, clientY: 40}));
    [...openMenu.querySelectorAll('[role="menuitem"]')].find(item => item.textContent === "Details").click();
  };
  try {
    await until("the first paint", () => SETTINGS && li("a1") && li("b1"));
    BODY
  } catch (err) {
    post("ERROR " + err.message);
  }
  post("DONE");
})(); undefined;"""


@pytest.fixture
def drive(probe_path, tmp_path):  # noqa: F811
    def run(body):
        """Loads the panel on two agents, a1 with a shell, and runs body, which posts one JSON reading."""
        (tmp_path / "settings.json").write_text(json.dumps({"card_anatomy": "name", "card_style": "cards"}))
        payload = {"groups": [{"name": "AGENTS", "rows": [agent("a1", "alpha", shells=[SHELL]), agent("b1", "bravo")]}]}

        async def look():
            sidebar = Sidebar(token=TOKEN, page_path=ROOT / "page.html", snapshot_fn=lambda: payload,
                              action_fn=lambda *a: None, settings_path=tmp_path / "settings.json",
                              context_fn=lambda session_id: CONTEXT)
            port = await Server(sidebar).start()
            probe = await asyncio.create_subprocess_exec(
                str(probe_path), f"http://127.0.0.1:{port}/?token={TOKEN}", "1", SCRIPT.replace("BODY", body),
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
        readings = [line for line in lines if line.startswith(("{", "["))]
        assert len(readings) == 1, lines
        return json.loads(readings[0])

    return run


def test_turning_background_shells_off_does_not_read_as_the_shell_finishing(drive):
    assert drive("""
        const a1 = LATEST.groups[0].rows[0], b1 = LATEST.groups[0].rows[1];
        const running = shellLine("a1");
        SETTINGS = {...SETTINGS, show_shells: false};
        render(LATEST, false, true);
        post(JSON.stringify([running, shellLine("a1"), paintFailure]));
    """) == [["1 background shell in alpha"], [], None]


def test_a_shell_that_ends_while_the_setting_is_off_says_nothing(drive):
    assert drive("""
        const [a1, b1] = LATEST.groups[0].rows;
        SETTINGS = {...SETTINGS, show_shells: false};
        render(LATEST, false, true);
        arrive(frameWith({...a1, shells: []}, b1));
        post(JSON.stringify([shellLine("a1"), paintFailure]));
    """) == [[], None]


def test_a_shell_that_ends_with_the_setting_on_lingers_as_finished(drive):
    assert drive("""
        const [a1, b1] = LATEST.groups[0].rows;
        arrive(frameWith({...a1, shells: []}, b1));
        post(JSON.stringify([shellLine("a1"), paintFailure]));
    """) == [["1 command finished"], None]


def test_details_closes_when_its_session_leaves_the_list(drive):
    assert drive("""
        const [a1, b1] = LATEST.groups[0].rows;
        details("b1");
        const open = [card.hidden, card.dataset.row];
        arrive(frameWith(a1));
        post(JSON.stringify([open, card.hidden, paintFailure]));
    """) == [[False, "b1"], True, None]


def test_details_stays_open_while_its_session_is_still_listed(drive):
    assert drive("""
        const [a1, b1] = LATEST.groups[0].rows;
        details("b1");
        arrive(frameWith({...a1}, {...b1}));
        post(JSON.stringify([card.hidden, card.classList.contains("pinned"), paintFailure]));
    """) == [False, True, None]


def test_a_read_that_lands_while_details_is_closed_shows_at_once_on_opening(drive):
    assert drive("""
        readContext("b1");
        await until("the read", () => contextReads.get("b1")?.context);
        details("b1");
        post(JSON.stringify([card.querySelectorAll(".ctx-head").length, card.querySelectorAll(".ctx-landed").length]));
    """) == [1, 0]


def test_a_read_that_lands_while_details_is_open_fades_in(drive):
    assert drive("""
        details("b1");
        readContext("b1");
        await until("the read", () => contextReads.get("b1")?.context && card.querySelector(".ctx-head"));
        post(JSON.stringify([card.querySelector(".ctx-head").classList.contains("ctx-landed")]));
    """) == [True]
