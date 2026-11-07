# ABOUTME: Drives a card's port pill and its popover in the real panel: WebKit loads page.html from a real daemon, as a
# ABOUTME: Toolbelt does, whose Stop and Open record what reaches them and refuse what the test names.
"""Where the pill sits, where the focus goes and what reaches the daemon are
the page's DOM and its fetches to say, so these run the page itself in a
WKWebView, the probe tests/test_panel_webkit.py builds, against a Sidebar
serving one frame. A synthetic key runs the page's own handlers but moves no
focus, so Tab's path is read from the order of the focusable nodes; the
render harness drives real keys in Chrome."""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ports  # noqa: E402
from sidebar import Server, Sidebar  # noqa: E402
from test_page_serenity import probe_path  # noqa: E402,F401

TOKEN = "port-chip-token-not-a-real-secret"


def listener(port, program, kind, pid, up, now, addresses=("127.0.0.1",)):
    return {"port": port, "addresses": list(addresses), "pid": pid, "program": program, "kind": kind,
            "started_at": now - up}


def frame(now):
    """alpha reports a task and holds two servers, its teammate a third; alpha2 and its
    teammate are the two without them; bravo reports nothing and holds one; charlie holds none."""
    report = {"title": "Ship the refund flow", "activity": "Running the suite", "reported_at": now - 30}
    alpha = {"session_id": "a1", "label": "alpha", "state": "working", "working_since": now - 120,
             "branch": "main", "model": "opus", "task": report,
             "ports": [listener(3000, "server.js", "js", 43000, 7170, now),
                       listener(5173, "vite", "js", 41730, 3570, now, ("*", "[::1]"))]}
    helper = {"session_id": "a1m", "label": "helper", "depth": 1, "state": "working", "working_since": now - 60,
              "ports": [listener(6006, "storybook", "js", 43006, 5400, now, ("*",))]}
    alpha2 = {key: value for key, value in alpha.items() if key != "ports"} | {"session_id": "a2", "label": "alpha2"}
    helper2 = {key: value for key, value in helper.items() if key != "ports"} | {"session_id": "a2m"}
    bravo = {"session_id": "b1", "label": "bravo", "state": "idle", "idle_since": now - 60, "branch": "main",
             "model": "sonnet", "ports": [listener(8080, "serve.py", "python", 42080, 1500, now)]}
    charlie = {"session_id": "c1", "label": "charlie", "state": "idle", "idle_since": now - 60, "model": "opus"}
    return {"groups": [{"name": "AGENTS", "rows": [alpha, helper, alpha2, helper2, bravo, charlie]}]}


SCRIPT = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const until = async (what, done) => {
    for (let i = 0; !done(); i++) {
      if (i > 150) throw new Error(`${what} never came`);
      await pause(20);
    }
  };
  const q = selector => document.querySelector(selector);
  const li = sid => q(`#groups li.line.card[data-key="${sid}"]`);
  const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height].map(Math.round); };
  const active = () => { const a = document.activeElement;
    return [a.className, a.textContent, a.closest(".port-entry")?.querySelector(".port-head .port-pill")?.textContent ?? null]; };
  // An icon by its name in the page's icon table; in an entry's words, as <name>.
  const drawn = svg => Object.keys(META_ICONS).find(name =>
    META_ICONS[name].match(/ d="([^"]+)"/)[1] === svg.querySelector("path").getAttribute("d"));
  const entries = () => [...document.querySelectorAll(".port-pop .port-entry")].map(e =>
    [...e.querySelectorAll(".port-head > *, .port-foot > *, .port-refusal")]
      .map(n => n instanceof SVGElement ? `<${drawn(n)}>` : n.textContent));
  const foot = port => [...document.querySelectorAll(".port-pop .port-entry")]
    .find(e => e.querySelector(".port-head .port-pill").textContent === ":" + port);
  const button = (port, word) => [...foot(port).querySelectorAll("button")].find(b => b.textContent === word);
  // A pill's ink and wash, each by the token it is; a wash is that token under an alpha, so its rgb alone names it.
  const rgb = c => { const n = c.match(/[0-9.]+/g).map(Number).slice(0, 3); return c.startsWith("color(") ? n.map(v => Math.round(v * 255)) : n; };
  const token = name => { const el = document.createElement("i"); el.style.color = `var(${name})`; document.body.append(el);
    const c = getComputedStyle(el).color; el.remove(); return rgb(c); };
  const named = c => ["--dim", "--fg", "--kind-js", "--kind-python", "--kind-ruby", "--exposed-ink"]
    .find(name => token(name).every((v, i) => Math.abs(v - rgb(c)[i]) <= 1))?.slice(2) ?? c;
  const tint = pill => [pill.textContent, named(getComputedStyle(pill).color), named(getComputedStyle(pill).backgroundColor)];
  try {
    await until("the first paint", () => SETTINGS && li("a1"));
    BODY
  } catch (err) {
    post("ERROR " + err.message);
  }
  post("DONE");
})(); undefined;"""


def drive(probe_path, folder, body, now, anatomy="name", style="cards", payload=None):
    """Loads the panel on `payload`, frame(now) by default, and runs body, which posts one JSON
    reading; returns it and what reached the daemon's Stop and Open."""
    (folder / "settings.json").write_text(json.dumps({"card_anatomy": anatomy, "card_style": style}))
    payload, acted = payload or frame(now), []

    def act(verb, refuse):
        def run(pid, port, started_at):
            acted.append([verb, pid, port, started_at])
            if port == refuse[0]:
                raise ports.Refused(refuse[1])
        return run

    async def run():
        sidebar = Sidebar(token=TOKEN, page_path=ROOT / "page.html", snapshot_fn=lambda: payload,
                          action_fn=lambda *a: None, settings_path=folder / "settings.json",
                          stop_port_fn=act("stop", (6006, "no longer listening on :6006")),
                          open_port_fn=act("open", (5173, "could not open http://localhost:5173: refused")))
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

    code, lines, err = asyncio.run(run())
    assert code == 0, (lines, err[-2000:])
    readings = [line for line in lines if line.startswith(("{", "["))]
    assert len(readings) == 1, lines
    return json.loads(readings[0]), acted


REST = """
const seen = {};
for (const sid of ["a1", "b1", "c1"]) {
  const card = li(sid), row = card.querySelector(":scope > button.row"), chip = card.querySelector(":scope > .port-chip");
  const slot = row.querySelector(".port-slot");
  seen[sid] = chip && {
    pills: [...chip.querySelectorAll(".port-pill")].map(tint),
    said: chip.getAttribute("aria-label"), title: chip.getAttribute("title"), cursor: getComputedStyle(chip).cursor,
    overCopy: JSON.stringify(box(chip)) === JSON.stringify(box(slot)),
    copy: [slot.parentElement.className, slot.getAttribute("aria-hidden"), getComputedStyle(slot).opacity,
           getComputedStyle(slot).visibility, [...slot.children].map(p => p.textContent)],
    insideCard: box(chip)[0] + box(chip)[2] <= box(card)[0] + box(card)[2],
    nextAfterRow: row.nextElementSibling === chip,
  };
}
// The task anatomy names the card by its report's title; the name anatomy puts it under the name.
const title = sid => li(sid).querySelector(":scope > button.row .task-title") ?? li(sid).querySelector(":scope > button.row .label");
seen.sameAsWithout = [box(li("a1"))[3] === box(li("a2"))[3], title("a1").clientWidth === title("a2").clientWidth];
post(JSON.stringify(seen));
"""


# Serenity keeps neither the activity nor the facts of a card at rest, so the pill takes a facts
# line of its own there, and that card is a line taller than its twin without one.
@pytest.mark.parametrize("anatomy, style, line, grows", [("name", "cards", "task-status", False),
                                                         ("task", "cards", "task-status", False),
                                                         ("name", "serenity", "model", True),
                                                         ("task", "serenity", "model", True)])
def test_a_card_shows_its_first_port_as_a_pill_and_folds_the_rest_into_one(probe_path, tmp_path, anatomy, style, line,
                                                                           grows):
    seen, acted = drive(probe_path, tmp_path, REST, int(time.time()), anatomy, style)
    assert seen == {
        "a1": {"pills": [[":3000", "kind-js", "kind-js"], ["+2", "dim", "fg"]],
               "said": "listening: server.js on port 3000, vite on port 5173, storybook on port 6006",
               "title": None, "cursor": "default", "overCopy": True,
               "copy": [line, "true", "0", "visible", [":3000", "+2"]], "insideCard": True, "nextAfterRow": True},
        "b1": {"pills": [[":8080", "kind-python", "kind-python"]], "said": "listening: serve.py on port 8080",
               "title": None, "cursor": "default",
               "overCopy": True, "copy": ["model", "true", "0", "visible", [":8080"]], "insideCard": True,
               "nextAfterRow": True},
        "c1": None,
        "sameAsWithout": [not grows, True],
    }
    assert acted == []


def test_a_pill_wears_the_tint_of_its_listeners_language_and_the_count_and_other_stay_grey(probe_path, tmp_path):
    """The card's pill takes its first listener's tint and each popover pill its own. Open, the card's pills take
    the full ink over a deeper wash, the first still of its language."""
    now = int(time.time())
    payload = frame(now)
    alpha, helper, bravo = (payload["groups"][0]["rows"][i] for i in (0, 1, 4))
    alpha["ports"] = [listener(4000, "jekyll", "ruby", 44000, 600, now), listener(5432, "postgres", "other", 45432, 900, now),
                      listener(8000, "uvicorn", "python", 48000, 300, now)]
    helper["ports"] = [listener(9000, "vite", "js", 49000, 1200, now)]
    bravo["ports"] = [listener(5433, "postgres", "other", 45433, 900, now)]
    seen, _ = drive(probe_path, tmp_path, """
    const pills = sid => [...li(sid).querySelectorAll(":scope > .port-chip .port-pill")].map(tint);
    const seen = {rest: pills("a1"), other: pills("b1")};
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    seen.open = pills("a1");
    seen.popover = [...document.querySelectorAll(".port-pop .port-head .port-pill")].map(tint);
    post(JSON.stringify(seen));
    """, now, payload=payload)
    assert seen == {
        "rest": [[":4000", "kind-ruby", "kind-ruby"], ["+3", "dim", "fg"]],
        "other": [[":5433", "dim", "fg"]],
        "open": [[":4000", "fg", "kind-ruby"], ["+3", "fg", "fg"]],
        "popover": [[":4000", "kind-ruby", "kind-ruby"], [":5432", "dim", "fg"], [":8000", "kind-python", "kind-python"],
                    [":9000", "kind-js", "kind-js"]],
    }


def test_the_pill_opens_its_cards_listeners_under_it_and_focuses_the_first_open(probe_path, tmp_path):
    now = int(time.time())
    seen, acted = drive(probe_path, tmp_path, """
    const chip = li("a1").querySelector(":scope > .port-chip");
    chip.click();
    await pause(50);
    // The slab unfolds as the menu does; its place is where the motion ends.
    const pop = q("#ports-a1");
    for (const motion of pop.getAnimations()) motion.finish();
    const at = box(pop), from = box(chip);
    post(JSON.stringify({entries: entries(), active: active(), expanded: chip.getAttribute("aria-expanded"),
                         controls: chip.getAttribute("aria-controls"), role: pop.getAttribute("role"),
                         position: getComputedStyle(pop).position, topLayer: pop.matches(":popover-open"),
                         under: at[1] - (from[1] + from[3]),
                         rightEdges: at[0] + at[2] - (from[0] + from[2]),
                         focusable: [...li("a1").querySelectorAll("button")].filter(b => !b.closest(".children"))
                           .map(b => b.classList.contains("row") ? "row" : b.className.split(" ")[0] + ":" + b.textContent)}));
    """, now)
    assert seen == {
        "entries": [[":3000", "server.js", "2h", "127.0.0.1", "Open", "Stop"],
                    [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stop"],
                    [":6006", "storybook", "1h 30m", "<globe>", "all interfaces", "Open", "Stop"]],
        "active": ["port-act", "Open", ":3000"], "expanded": "true", "controls": "ports-a1", "role": "dialog",
        "position": "fixed", "topLayer": True, "under": 4, "rightEdges": 0,
        "focusable": ["row", "port-chip::3000+2", "port-act:Open", "port-act:Stop", "port-act:Open",
                      "port-act:Stop", "port-act:Open", "port-act:Stop"],
    }
    assert acted == []


def test_a_globe_marks_an_address_the_network_reaches_and_its_entry_says_so(probe_path, tmp_path):
    """Every interface, or an address another machine can reach; loopback, 127.0.0.1 or [::1], stays plain."""
    now = int(time.time())
    payload = frame(now)
    alpha, helper = payload["groups"][0]["rows"][:2]
    alpha["ports"] = [listener(3000, "server.js", "js", 43000, 7170, now, ("127.0.0.1", "[::1]")),
                      listener(4000, "jekyll", "ruby", 44000, 600, now, ("[::1]",)),
                      listener(5173, "vite", "js", 41730, 3570, now, ("*",)),
                      listener(8000, "uvicorn", "python", 48000, 300, now, ("192.168.1.20",))]
    del helper["ports"]
    seen, _ = drive(probe_path, tmp_path, """
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    post(JSON.stringify([...document.querySelectorAll(".port-pop .port-entry")].map(e => [e.getAttribute("aria-label"),
      [...e.querySelectorAll("svg:not(button svg)")].map(svg => [drawn(svg), svg.getAttribute("aria-hidden"),
        named(getComputedStyle(svg).fill)]), entries().find(words => words[0] === e.querySelector(".port-pill").textContent)])));
    """, now, payload=payload)
    assert seen == [
        ["server.js on port 3000, on 127.0.0.1, [::1], up 2h", [],
         [":3000", "server.js", "2h", "127.0.0.1, [::1]", "Open", "Stop"]],
        ["jekyll on port 4000, on [::1], up 10m", [], [":4000", "jekyll", "10m", "[::1]", "Open", "Stop"]],
        ["vite on port 5173, on all interfaces, reachable from the network, up 1h", [["globe", "true", "exposed-ink"]],
         [":5173", "vite", "1h", "<globe>", "all interfaces", "Open", "Stop"]],
        ["uvicorn on port 8000, on 192.168.1.20, reachable from the network, up 5m", [["globe", "true", "exposed-ink"]],
         [":8000", "uvicorn", "5m", "<globe>", "192.168.1.20", "Open", "Stop"]],
    ]


def test_open_and_stop_carry_an_icon_in_their_own_ink_and_keep_their_words_as_names(probe_path, tmp_path):
    """Open an arrow out of a box, Stop a square, before the word; no reader hears either icon."""
    seen, _ = drive(probe_path, tmp_path, """
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    const acts = port => [...foot(port).querySelectorAll("button")].map(b => [b.textContent, b.getAttribute("aria-label"),
      [...b.querySelectorAll("svg")].map(svg => [drawn(svg), svg.getAttribute("aria-hidden"),
        getComputedStyle(svg).fill === getComputedStyle(b).color, getComputedStyle(svg).opacity])]);
    const seen = [acts(3000)];
    button(5173, "Stop").click();
    seen.push(acts(5173));
    post(JSON.stringify(seen));
    """, int(time.time()))
    assert seen == [
        [["Open", "open localhost:3000 in the browser", [["open", "true", True, "1"]]],
         ["Stop", "stop server.js on port 3000", [["stop", "true", True, "1"]]]],
        [["Stop", "stop vite on port 5173", [["stop", "true", True, "1"]]],
         ["Cancel", "keep it running", []]],
    ]


def test_under_300px_a_resting_open_and_stop_show_their_icon_alone_and_keep_their_word_as_name_and_tooltip(
        probe_path, tmp_path):
    """The probe's panel is 380px, so a larger text size narrows the page: 1.5x lays it out in 253px, 1.25x in 304.
    The Stop question and Stopping… keep their words, and the asked Stop drops its square so the question shows
    whole. Back past 316px the words return, not at every pixel."""
    now = int(time.time())
    seen, acted = drive(probe_path, tmp_path, """
    const acts = port => [...foot(port).querySelectorAll("button")].map(b => [b.textContent, b.getAttribute("aria-label"),
      b.title, [...b.querySelectorAll("svg")].map(drawn)]);
    const at = async scale => { applyScale(scale); await pause(50); return acts(3000); };
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    const seen = [["1.5x", await at(1.5)]];
    foot(5173).querySelector('button[aria-label^="stop "]').click();
    const ask = foot(5173).querySelector(".port-ask");
    seen.push(["asks", acts(5173), ask.textContent, ask.scrollWidth <= ask.clientWidth]);
    button(5173, "Stop").click();
    await until("the stop's answer", () => button(5173, "Stopping…"));
    seen.push(["stopping", acts(5173)]);
    seen.push(["1.25x on the way out", await at(1.25)], ["1x", await at(1)], ["1.25x on the way in", await at(1.25)]);
    post(JSON.stringify(seen));
    """, now)
    bare = [["", "open localhost:3000 in the browser", "Open", ["open"]],
            ["", "stop server.js on port 3000", "Stop", ["stop"]]]
    worded = [["Open", "open localhost:3000 in the browser", "", ["open"]],
              ["Stop", "stop server.js on port 3000", "", ["stop"]]]
    assert seen == [
        ["1.5x", bare],
        ["asks", [["Stop", "stop vite on port 5173", "", []], ["Cancel", "keep it running", "", []]], "Stop vite?", True],
        ["stopping", [["", "open localhost:5173 in the browser", "Open", ["open"]],
                      ["Stopping…", "stop vite on port 5173", "", ["stop"]]]],
        ["1.25x on the way out", bare], ["1x", worded], ["1.25x on the way in", worded],
    ]
    assert acted == [["stop", 41730, 5173, now - 3570]]


def test_the_popover_is_300px_wide_where_the_panel_has_room_so_an_exposed_address_shows_whole(probe_path, tmp_path):
    """Buttons with their words and a globe beside an address of every interface, in a 380px panel."""
    seen, _ = drive(probe_path, tmp_path, """
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    const pop = q("#ports-a1");
    for (const motion of pop.getAnimations()) motion.finish();
    post(JSON.stringify({width: box(pop)[2], whole: [...pop.querySelectorAll(".port-entry")].map(e => {
      const where = e.querySelector(".port-where");
      return [e.querySelector(".port-pill").textContent, where.textContent, where.scrollWidth <= where.clientWidth]; })}));
    """, int(time.time()))
    assert seen == {"width": 300, "whole": [[":3000", "127.0.0.1", True], [":5173", "all interfaces, [::1]", False],
                                            [":6006", "all interfaces", True]]}


def test_at_a_larger_text_size_the_popover_still_fits_inside_the_panel(probe_path, tmp_path):
    """Text size zooms the page, and the zoom renders a width the viewport gave: 1.5x in the probe's 380px panel lays
    the page out in 253px, and the popover keeps 6px clear of the panel's left edge and lines up with the pill."""
    seen, _ = drive(probe_path, tmp_path, """
    applyScale(1.5);
    await pause(50);
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    const pop = q("#ports-a1");
    for (const motion of pop.getAnimations()) motion.finish();
    const at = pop.getBoundingClientRect(), chip = li("a1").querySelector(":scope > .port-chip").getBoundingClientRect();
    post(JSON.stringify({left: Math.round(at.left), right: Math.round(at.right - chip.right), page: innerWidth}));
    """, int(time.time()))
    assert seen == {"left": 9, "right": 0, "page": 380}


def test_stop_asks_once_then_sends_the_listener_and_a_refusal_shows_under_its_entry(probe_path, tmp_path):
    now = int(time.time())
    seen, acted = drive(probe_path, tmp_path, """
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    const seen = [];
    button(5173, "Stop").click();
    seen.push(["asks", entries()[1], active()]);
    button(5173, "Cancel").click();
    seen.push(["cancelled", entries()[1], active()]);
    button(5173, "Stop").click();
    button(5173, "Stop").click();
    await until("the stop's answer", () => button(5173, "Stopping…"));
    seen.push(["sent", entries()[1], button(5173, "Stopping…").disabled, active()]);
    // A holder can ignore SIGTERM: fifteen seconds on, its Stop is offered again.
    portStopSent.set([...portStopSent.keys()][0], Date.now() - 15000);
    render(LATEST, false, true);
    seen.push(["held 15 s", entries()[1], button(5173, "Stop").disabled]);
    button(6006, "Stop").click();
    button(6006, "Stop").click();
    await until("the refusal", () => foot(6006).querySelector(".port-refusal"));
    seen.push(["refused", entries()[2], foot(6006).querySelector(".port-refusal").getAttribute("role")]);
    post(JSON.stringify(seen));
    """, now)
    assert seen == [
        ["asks", [":5173", "vite", "1h", "Stop vite?", "Stop", "Cancel"], ["port-act stop-now", "Stop", ":5173"]],
        ["cancelled", [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stop"], ["port-act", "Stop", ":5173"]],
        ["sent", [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stopping…"], True,
         ["port-act", "Open", ":5173"]],
        ["held 15 s", [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stop"], False],
        ["refused", [":6006", "storybook", "1h 30m", "<globe>", "all interfaces", "Open", "Stop", "no longer listening on :6006"],
         "status"],
    ]
    assert acted == [["stop", 41730, 5173, now - 3570], ["stop", 43006, 6006, now - 5400]]


def test_open_hands_the_daemon_the_listener_and_shows_why_it_could_not(probe_path, tmp_path):
    now = int(time.time())
    seen, acted = drive(probe_path, tmp_path, """
    li("a1").querySelector(":scope > .port-chip").click();
    await pause(50);
    button(3000, "Open").click();
    button(5173, "Open").click();
    await until("the refusal", () => foot(5173).querySelector(".port-refusal"));
    await pause(100);
    post(JSON.stringify({entries: entries()}));
    """, now)
    assert seen == {"entries": [
        [":3000", "server.js", "2h", "127.0.0.1", "Open", "Stop"],
        [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stop", "could not open http://localhost:5173: refused"],
        [":6006", "storybook", "1h 30m", "<globe>", "all interfaces", "Open", "Stop"]]}
    assert acted == [["open", 43000, 3000, now - 7170], ["open", 41730, 5173, now - 3570]]


def test_escape_or_a_press_elsewhere_closes_it_and_the_pill_or_the_row_keeps_the_focus(probe_path, tmp_path):
    seen, _ = drive(probe_path, tmp_path, """
    const chip = () => li("a1").querySelector(":scope > .port-chip");
    const seen = [];
    chip().click();
    await pause(50);
    button(5173, "Stop").click();
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true, cancelable: true}));
    await pause(50);
    seen.push(["escape", !!q(".port-pop"), chip().getAttribute("aria-expanded"), active()]);
    chip().click();
    await pause(50);
    seen.push(["open again, nothing asks", entries()[1]]);
    document.body.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true}));
    await pause(50);
    seen.push(["pressed elsewhere", !!q(".port-pop"), chip().getAttribute("aria-expanded")]);
    chip().click();
    await pause(50);
    const without = JSON.parse(JSON.stringify(LATEST));
    without.groups[0].rows.find(r => r.session_id === "a1").ports = undefined;
    without.groups[0].rows.find(r => r.session_id === "a1m").ports = undefined;
    LATEST = without;
    render(LATEST, false, true);
    await pause(50);
    seen.push(["its listeners gone", !!chip(), !!q(".port-pop"), document.activeElement === li("a1").querySelector(":scope > button.row")]);
    post(JSON.stringify(seen));
    """, int(time.time()))
    assert seen == [
        ["escape", False, "false", ["port-chip", ":3000+2", None]],
        ["open again, nothing asks", [":5173", "vite", "1h", "<globe>", "all interfaces, [::1]", "Open", "Stop"]],
        ["pressed elsewhere", False, "false"],
        ["its listeners gone", False, False, True],
    ]


def test_a_card_that_asks_shows_no_pill_till_it_is_answered_and_its_open_popover_gives_the_focus_to_its_row(
        probe_path, tmp_path):
    """A card asking a question shows only its name, the question and the answers."""
    seen, _ = drive(probe_path, tmp_path, """
    const chip = () => li("a1").querySelector(":scope > .port-chip");
    const look = name => [name, !!chip(), !!q(".port-pop"), !!li("a1").querySelector(".port-slot"),
                          li("a1").querySelectorAll(".answer").length,
                          document.activeElement === li("a1").querySelector(":scope > button.row")];
    const ask = question => {
      const next = JSON.parse(JSON.stringify(LATEST));
      Object.assign(next.groups[0].rows.find(r => r.session_id === "a1"),
                    question ? {state: "blocked", question} : {state: "working", question: undefined});
      LATEST = next;
      render(LATEST, false, true);
    };
    const seen = [];
    chip().click();
    await pause(50);
    ask({question: "Which one?", options: ["This", "That"], multi: false, more: 0});
    await pause(50);
    seen.push(look("asks while its popover is open"));
    ask(null);
    await pause(50);
    seen.push(look("answered"));
    post(JSON.stringify(seen));
    """, int(time.time()))
    assert seen == [
        ["asks while its popover is open", False, False, False, 2, True],
        ["answered", True, False, True, 0, True],
    ]


def test_a_pill_scrolled_under_the_lists_edge_closes_its_popover_and_keeps_the_focus(probe_path, tmp_path):
    """The popover floats in the top layer, past the list's clip and fade, and WebKit keeps such a box
    on screen once its anchor is clipped away, so a scroll that takes the pill out of view closes it;
    the list clips the pill itself. Neither then paints over the foot."""
    now = int(time.time())
    payload = frame(now)
    rows = payload["groups"][0]["rows"]
    fillers = [{"session_id": f"f{i}", "label": f"filler{i}", "state": "idle", "idle_since": now - 60,
                "model": "opus", "task": {"title": "Wait", "activity": "Waiting", "reported_at": now - 30}}
               for i in range(8)]
    payload["groups"][0]["rows"] = rows[:4] + fillers + rows[4:]
    seen, _ = drive(probe_path, tmp_path, """
    const list = q("#groups");
    const chip = () => li("b1").querySelector(":scope > .port-chip");
    const edge = () => list.getBoundingClientRect().bottom;
    list.scrollTop += li("b1").querySelector(".port-slot").getBoundingClientRect().top - (edge() - 60);
    await pause(100);
    chip().click();
    await pause(100);
    const pop = q("#ports-b1");
    // Hit-testing skips a box its anchor's visibility hides; opacity, which the slab's unfold moves, does not count.
    const shown = () => { const r = pop.getBoundingClientRect();
      return !!document.elementFromPoint(r.left + 20, r.top + 20)?.closest(".port-pop"); };
    const at = name => [name, chip().getBoundingClientRect().top < edge(), shown(), pop.matches(":popover-open"),
                        document.activeElement === chip(), list.contains(document.elementFromPoint(
                          chip().getBoundingClientRect().left + 4, chip().getBoundingClientRect().top + 4))];
    const seen = [at("in view")];
    list.scrollTop -= 100;
    await pause(300);
    seen.push(at("under the edge"));
    post(JSON.stringify(seen));
    """, now, payload=payload)
    assert seen == [["in view", True, True, True, False, True], ["under the edge", False, False, False, True, False]]
