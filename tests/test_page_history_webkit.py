# ABOUTME: Drives the History fold in the real panel: WebKit loads page.html from a real daemon, as a Toolbelt does.
# ABOUTME: Focus outlives a repaint, a held arrow moves once, and the open fold keeps one height; Sessions scrolls in it.
"""Where the focus goes is the DOM's to say, from the nodes the page's morph
keeps or replaces, so these run the page itself in a WKWebView, the probe
tests/test_panel_webkit.py builds, against a daemon with a settings file of
its own. The script holds the daemon's answers to /past and /activity until
it releases them, so a tab can be caught while it reads; another window is
the daemon's /settings written to directly."""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sidebar import Server, Sidebar  # noqa: E402
from test_page_history_fold import REPORT  # noqa: E402
from test_page_serenity import probe_path  # noqa: E402,F401

TOKEN = "history-token-not-a-real-secret"

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
  const real = window.fetch;
  const calls = [], held = [];
  window.fetch = (url, init) => {
    const path = String(url).split("?")[0];
    const answer = real.call(window, url, init);
    if (init?.method === "POST" && path === "/settings") calls.push(`${path} ${init.body}`);
    if (path !== "/past" && path !== "/activity") return answer;
    calls.push(path);
    return new Promise(resolve => held.push(() => resolve(answer)));
  };
  const release = () => held.splice(0).forEach(go => go());
  const elsewhere = change => real.call(window, `/settings?token=${encodeURIComponent(TOKEN)}`,
                                        {method: "POST", body: JSON.stringify(change)});
  try {
    await until("the first paint", () => SETTINGS && q("#budget .past > .lim-toggle"));
    BODY
  } catch (err) {
    post("ERROR " + err.message);
  }
  post("DONE");
})(); undefined;"""


def drive(probe_path, folder, body, rows=None, report=REPORT):
    """Loads the panel with History remembering Sessions and runs body, which
    posts one JSON reading; returns it and the settings the daemon kept."""
    (folder / "settings.json").write_text(json.dumps({"history_tab": "sessions"}))
    rows = rows or [{"kind": "cs", "name": "notes", "path": "/work/notes", "conversation": None, "title": None,
                     "at": int(time.time()) - 3600}]

    async def run():
        sidebar = Sidebar(token=TOKEN, page_path=ROOT / "page.html", snapshot_fn=lambda: {"groups": []},
                          action_fn=lambda *a: None, settings_path=folder / "settings.json",
                          past_fn=lambda: rows, activity_fn=lambda days: report)
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
    readings = [line for line in lines if line.startswith("{")]
    assert len(readings) == 1, lines
    return json.loads(readings[0]), json.loads((folder / "settings.json").read_text())


def test_the_head_keeps_the_focus_when_another_windows_tab_comes_back_with_the_settings(probe_path, tmp_path):
    """Another window picks a tab; this panel saves a setting of its own and the daemon's reply
    carries that tab, open while the shown tab reads and folded."""
    seen, kept = drive(probe_path, tmp_path, """
    const head = q("#budget .past > .lim-toggle");
    const seen = [];
    const look = name => {
      const now = q("#budget .past > .lim-toggle");
      seen.push([name, now === head, document.activeElement === head, now.dataset.wait, now.className,
                 now.getAttribute("aria-expanded")]);
    };
    const comesBack = async tab => {
      await elsewhere({history_tab: tab});
      push({limits_folded: SETTINGS.limits_folded});
      await until(`the daemon's ${tab}`, () => SETTINGS.history_tab === tab);
      await pause(150);
    };
    head.focus();
    head.click();
    look("open on Sessions");
    await comesBack("activity");
    look("Activity from another window, open");
    q("#budget .past > .lim-toggle").click();
    look("folded");
    await comesBack("sessions");
    look("Sessions from another window, folded");
    post(JSON.stringify({seen, calls}));
    """)
    assert seen == {"seen": [
        ["open on Sessions", True, True, "sessions", "lim-toggle reading", "true"],
        ["Activity from another window, open", True, True, "activity", "lim-toggle reading", "true"],
        ["folded", True, True, "activity", "lim-toggle", "false"],
        ["Sessions from another window, folded", True, True, "sessions", "lim-toggle", "false"],
    ], "calls": ["/past", '/settings {"limits_folded":false}', "/activity", '/settings {"limits_folded":false}']}
    assert kept["history_tab"] == "sessions"


def test_a_held_arrow_shows_the_next_tab_once_and_saves_it_once(probe_path, tmp_path):
    """The key repeats while held; only a fresh press moves, and a repeat still keeps the key from
    scrolling. The daemon ends up with the tab the panel shows."""
    seen, kept = drive(probe_path, tmp_path, """
    q("#budget .past > .lim-toggle").click();
    release();
    await until("the rows", () => q("#history-panel .past-entry"));
    q('#budget [role="tab"][data-tab="sessions"]').focus();
    const seen = [];
    const press = (key, repeat) => {
      const event = new KeyboardEvent("keydown", {key, repeat, bubbles: true, cancelable: true});
      document.activeElement.dispatchEvent(event);
      seen.push([key, repeat, event.defaultPrevented, SETTINGS.history_tab, document.activeElement.dataset.tab]);
    };
    press("ArrowRight", false);
    press("ArrowRight", true);
    press("ArrowRight", true);
    press("ArrowRight", true);
    press("ArrowLeft", false);
    press("ArrowLeft", true);
    release();
    await pause(300);
    post(JSON.stringify({seen, calls, shown: SETTINGS.history_tab}));
    """)
    assert seen == {"seen": [
        ["ArrowRight", False, True, "activity", "activity"],
        ["ArrowRight", True, True, "activity", "activity"],
        ["ArrowRight", True, True, "activity", "activity"],
        ["ArrowRight", True, True, "activity", "activity"],
        ["ArrowLeft", False, True, "sessions", "sessions"],
        ["ArrowLeft", True, True, "sessions", "sessions"],
    ], "calls": ["/past", "/activity", '/settings {"history_tab":"activity"}', '/settings {"history_tab":"sessions"}'],
        "shown": "sessions"}
    assert kept["history_tab"] == "sessions"


def test_a_focused_sessions_panel_keeps_the_focus_when_its_rows_arrive(probe_path, tmp_path):
    """While Sessions reads, nothing in its panel takes the focus, so the panel does. Rows arriving
    under a focused panel leave the focus there rather than moving it: the next Tab reaches the first
    entry. Once the focus has gone elsewhere, the next paint leaves the entries the panel's stop."""
    seen, _ = drive(probe_path, tmp_path, """
    q("#budget .past > .lim-toggle").click();
    await until("the placeholders", () => q("#history-panel .unlit"));
    const panel = q("#history-panel");
    panel.focus();
    const seen = [];
    const look = name => {
      const now = q("#history-panel");
      seen.push([name, now === panel, document.activeElement === panel, now.getAttribute("tabindex"),
                 now.querySelectorAll(".past-entry").length]);
    };
    look("reading");
    release();
    await until("the rows", () => q("#history-panel .past-entry"));
    await pause(150);
    look("rows arrived");
    const entry = q("#history-panel .past-entry");
    entry.focus();
    paintBudget(lastSnapshot);
    await pause(150);
    look("an entry focused");
    seen.push(["the entry holds the focus", document.activeElement === entry]);
    post(JSON.stringify({seen}));
    """)
    assert seen == {"seen": [
        ["reading", True, True, "0", 0],
        ["rows arrived", True, True, "0", 1],
        ["an entry focused", True, False, None, 1],
        ["the entry holds the focus", True],
    ]}


# A busy week: thirty conversations to resume, the most the daemon lists, newest first, five hours apart; and twelve projects with two
# scratch dirs, all of them on every day but the oldest, which has two, and Codex in one of them every day; so
# Activity shows Claude's and Codex's split, ten rows, "+2 more projects" and "2 scratch dirs" for the week, and
# two rows for that day.
FOLDERS = ["atlas", "borealis", "cinder", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper",
           "kestrel", "lumen"]


def week_rows():
    now = int(time.time())
    return [{"kind": "claude", "name": FOLDERS[i % 12], "path": f"/work/{FOLDERS[i % 12]}", "conversation": f"c{i}",
             "title": f"Look into the {FOLDERS[(i + 5) % 12]} build", "at": now - 600 - i * 5 * 3600}
            for i in range(30)]


def week_report():
    def used(project, scratch, n):
        return {"project": project, "scratch": scratch, "entrypoint": "cli", "conversations": 1, "prompts": n,
                "tokens": {"input": 1000 * n, "output": 500 * n, "cache_read": 0, "cache_write": 0}}
    everyone = [used(f"/work/{name}", False, 12 - i) for i, name in enumerate(FOLDERS)]
    everyone += [used("/tmp/scratch-a", True, 1), used("/tmp/scratch-b", True, 1)]
    codex = [{"project": "/work/atlas", "scratch": False, "originator": "codex_cli_rs", "rollouts": 1, "turns": 3,
              "tokens": {"input": 9000, "cached_input": 0, "output": 3000, "reasoning_output": 0, "total": 12000}}]
    days = [{"date": f"2026-11-0{7 - back}", "claude": everyone if back < 6 else everyone[:2], "codex": codex}
            for back in range(7)]
    return {"generated_at": 1, "conversations": [], "unread": [], "days": days}


def test_the_open_fold_keeps_one_height_whichever_tab_shows_and_whatever_it_holds(probe_path, tmp_path):
    """The fold is measured while each tab reads, with its rows, with the oldest day picked, with nothing to
    resume and after failed reads: its height never moves. At every text size the body under the tabs is as tall
    on both tabs, Activity's week fits it whole with both its edges crisp, and Sessions scrolls inside it."""
    seen, _ = drive(probe_path, tmp_path, """
    const body = () => q("#history-panel").firstElementChild;
    const scrolls = () => {
      body().scrollTop = 1e6;
      const moved = body().scrollTop > 0;
      body().scrollTop = 0;
      return moved;
    };
    const seen = [];
    const look = name => seen.push([name, q("#budget > .past").getBoundingClientRect().height, scrolls()]);
    q("#budget .past > .lim-toggle").click();
    await until("Sessions' placeholders", () => q("#history-panel .unlit"));
    look("Sessions reading");
    release();
    await until("the entries", () => q("#history-panel .past-entry"));
    look("Sessions");
    q('#budget [role="tab"][data-tab="activity"]').click();
    await until("Activity's placeholders", () => q("#history-panel .unlit"));
    look("Activity reading");
    release();
    await until("the projects", () => q("#history-panel .act-head"));
    look("Activity");
    q("#history-panel .act-days span").click();
    look("the oldest day picked");
    q('#budget [role="tab"][data-tab="sessions"]').click();
    const rows = pastRows;
    pastRows = [];
    paintBudget(lastSnapshot);
    look("Sessions with nothing to resume");
    pastError = "read failed (500)";
    paintBudget(lastSnapshot);
    look("Sessions after a failed read");
    q('#budget [role="tab"][data-tab="activity"]').click();
    const report = activityReport;
    activityReport = null;
    activityError = "read failed (500)";
    paintBudget(lastSnapshot);
    look("Activity after a failed read");
    pastRows = rows;
    pastError = null;
    activityReport = report;
    activityError = null;
    activityDay = null;
    paintBudget(lastSnapshot);
    const projects = q("#history-panel").querySelectorAll(".act-split, .act-row, .act-rest").length;
    const sizes = [];
    for (const scale of [0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6]) {
      applyScale(scale);
      const shown = [scale];
      for (const tab of ["sessions", "activity"]) {
        SETTINGS = {...SETTINGS, history_tab: tab};
        paintBudget(lastSnapshot);
        shown.push(body().clientHeight, scrolls());
      }
      await pause(300);
      const style = getComputedStyle(body());
      shown.push(style.getPropertyValue("--fade-top"), style.getPropertyValue("--fade-foot"));
      sizes.push(shown);
    }
    post(JSON.stringify({seen, projects, sizes}));
    """, rows=week_rows(), report=week_report())
    assert seen == {"seen": [
        ["Sessions reading", 401.5, False],
        ["Sessions", 401.5, True],
        ["Activity reading", 401.5, False],
        ["Activity", 401.5, False],
        ["the oldest day picked", 401.5, False],
        ["Sessions with nothing to resume", 401.5, False],
        ["Sessions after a failed read", 401.5, False],
        ["Activity after a failed read", 401.5, False],
    ], "projects": 13, "sizes": [[scale, 344, True, 344, False, "0px", "0px"]
                                 for scale in (0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6)]}


def test_sessions_scrolls_inside_the_body_keeping_its_place_and_showing_the_focused_entry(probe_path, tmp_path):
    """The log scrolls under the tabs and the fold stays put: a repaint keeps where the log was scrolled to, and
    an entry the focus reaches, stepping down from the top as Tab does, then the last and the first, scrolls
    into the body clear of its fades."""
    seen, _ = drive(probe_path, tmp_path, """
    const body = () => q("#history-panel").firstElementChild;
    q("#budget .past > .lim-toggle").click();
    release();
    await until("the entries", () => q("#history-panel .past-entry"));
    const seen = [];
    const look = name => {
      const b = body().getBoundingClientRect(), e = document.activeElement.getBoundingClientRect();
      const fade = side => parseFloat(getComputedStyle(body()).getPropertyValue(`--fade-${side}`)) || 0;
      seen.push([name, q("#budget > .past").getBoundingClientRect().top, body().scrollTop > 0,
                 document.activeElement.matches(".past-entry") && e.top >= b.top + fade("top")
                   && e.bottom <= b.bottom - fade("foot")]);
    };
    look("open");
    body().scrollTop = 200;
    paintBudget(lastSnapshot);
    seen.push(["scrolled and painted again", body().scrollTop]);
    body().scrollTop = 0;
    const entries = body().querySelectorAll(".past-entry");
    for (const i of [10, 11, 12, 29, 0]) {
      entries[i].focus();
      await pause(300);
      look(`entry ${i + 1} focused`);
    }
    post(JSON.stringify({seen}));
    """, rows=week_rows(), report=week_report())
    assert seen == {"seen": [
        ["open", 144, False, False],
        ["scrolled and painted again", 200],
        ["entry 11 focused", 144, True, True],
        ["entry 12 focused", 144, True, True],
        ["entry 13 focused", 144, True, True],
        ["entry 30 focused", 144, True, True],
        ["entry 1 focused", 144, False, True],
    ]}
