# ABOUTME: Checks the bar the Accounts foot draws for each account, folded and at compact width, and the chips in its head.
# ABOUTME: Runs page.html's Accounts functions under Node over a stand-in DOM, fed an accounts store the daemon's own code shapes.
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from accounts import exhausted_models, meters_snapshot, pace, switch_outlook  # noqa: E402
from page_source import function  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")
NOW = 1793880000
H, D = 3600, 86400

# Elements as plain objects: enough for the Accounts builders to set text,
# classes, data and attributes, find a child by its class and append or
# prepend, and for `words` to read back what shows.
DOM = """
class Node {
  constructor(tag) {
    Object.assign(this, {tag, className: "", textContent: "", title: "", type: "", dataset: {}, children: [], attrs: {}});
    this.classList = {add: (...names) => { this.className = [this.className, ...names].filter(Boolean).join(" "); },
                      contains: name => this.className.split(" ").includes(name)};
  }
  append(...kids) { this.children.push(...kids); }
  prepend(...kids) { this.children.unshift(...kids); }
  setAttribute(name, value) { this.attrs[name] = value; }
  removeAttribute(name) { delete this.attrs[name]; }
  querySelector(selector) {
    for (const kid of this.children) {
      if (kid.classList.contains(selector.slice(1))) return kid;
      const deeper = kid.querySelector(selector);
      if (deeper) return deeper;
    }
    return null;
  }
}
const document = {createElement: tag => new Node(tag)};
function metaIcon(kind) { return new Node("svg"); }
function providerIcon(kind, label) { return new Node("svg"); }
function on(el, type, handler) {}
function push(change) {}
function paintBudget() {}
let lastSnapshot = null;
const words = n => n.children.length ? n.children.flatMap(words) : (n.textContent ? [String(n.textContent)] : []);
"""

# From the auto-switch row to the folded Codex tile: the head, its chips, the
# folded tiles and the compact foot, with whatever helpers sit among them.
LIMITS = re.search(r"\n// The auto-switch setting, above the accounts it acts on\.\n.*?(?=\nfunction paintAccounts\()",
                   PAGE, re.S).group(0)
HELPERS = [re.search(r"\nconst clock = .*?\n\};\n", PAGE, re.S).group(0),
           *(function(PAGE, name) for name in ("duration", "untilReset", "tickSaid", "meterRow", "accountStatus",
                                               "forHumans"))]


def run(body, store, auto=True, compact=False, tiny=False):
    setup = f"""{DOM}
Date.now = () => {NOW * 1000};
let SETTINGS = {{auto_switch: {json.dumps(auto)}, limits_folded: true}};
let compact = {json.dumps(compact)}, tiny = {json.dumps(tiny)};
const STORE = {json.dumps(store)};
const CODEX = {json.dumps(CODEX)};
"""
    result = subprocess.run(["node", "-e", "\n".join([setup, *HELPERS, LIMITS, body])],
                            capture_output=True, text=True, check=True, timeout=10, env={**os.environ, "TZ": "UTC"})
    return json.loads(result.stdout)


ACCOUNTS = [{"id": "acct-1", "alias": "work"}, {"id": "acct-2", "alias": "home"}, {"id": "acct-3", "alias": "spare"}]
RESETS = [NOW + D + 2 * H, NOW + 15 * H + 10 * 60, NOW + 5 * D + 3 * H]
FIVE_HOUR_RESET = NOW + 3 * H + 20 * 60
CODEX = {"windows": [{"label": "Weekly", "used": 88.0, "resets_at": NOW + 18 * H + 20 * 60, "minutes": 10080,
                      "pace": pace(88.0, NOW + 18 * H + 20 * 60, NOW)}]}


def reading(five, weekly, fable, resets_at):
    return {"usage": {"five_hour": None if five is None else {"used": five, "resets_at": FIVE_HOUR_RESET},
                      "seven_day": None if weekly is None else {"used": weekly, "resets_at": resets_at},
                      "models": [{"name": "Fable", "used": fable, "resets_at": resets_at}]},
            "fetched_at": NOW - 60, "outcome": "ok", "earlier_usage": None, "earlier_at": None,
            "tried_at": NOW - 60, "next_at": NOW + 120}


def store(*figures):
    """The accounts store as the daemon's tick shapes it, work active, from
    (5-hour, weekly, Fable) per account, a None for a window it lacks."""
    states = {a["id"]: reading(*f, r) for a, f, r in zip(ACCOUNTS, figures, RESETS)}
    return meters_snapshot(ACCOUNTS, states, "acct-1",
                           next_switch=switch_outlook("acct-1", states, ACCOUNTS, NOW),
                           exhausted=exhausted_models(states, ACCOUNTS, NOW))


FABLE_FULL_EVERYWHERE = store((12, 67, 100), (None, 83, 100), (3, 72, 100))

FOLDED = """
const head = limitsHead(STORE);
const tiles = [...foldedAccountTiles(STORE), foldedCodexTile(CODEX)];
console.log(JSON.stringify({head: words(head), tiles: tiles.map(words), titles: tiles.map(t => t.title)}));
"""
COMPACT = """
const lines = compactFoot(STORE, CODEX).children;
console.log(JSON.stringify({lines: lines.map(words), titles: lines.map(l => l.title)}));
"""
SET_ASIDE = "Fable is at 100% on every account; back when home resets in 15h 10m"


def test_a_model_full_on_every_account_leaves_each_bar_to_the_next_limit_with_room_and_the_head_to_auto_switch():
    shown = run(FOLDED, FABLE_FULL_EVERYWHERE)
    assert shown["head"] == ["›", "Accounts", "Auto-switch"]
    assert shown["tiles"] == [["work", "67%", "wk 1d"], ["home", "83%", "wk 15h"], ["spare", "72%", "wk 5d"],
                              ["Codex", "88%", "wk 18h"]]


def test_a_tile_whose_bar_passed_over_a_full_model_says_so_on_hover_beside_every_window():
    assert run(FOLDED, FABLE_FULL_EVERYWHERE)["titles"] == [
        f"work · 5-hour 12% · Weekly 67% · Fable 100%\n{SET_ASIDE}",
        f"home · Weekly 83% · Fable 100%\n{SET_ASIDE}",
        f"spare · 5-hour 3% · Weekly 72% · Fable 100%\n{SET_ASIDE}",
        "Codex · Weekly 88%",
    ]


def test_with_auto_switch_off_the_bars_set_the_same_limit_aside():
    shown = run(FOLDED, FABLE_FULL_EVERYWHERE, auto=False)
    assert shown["head"] == ["›", "Accounts", "Auto-switch"]
    assert shown["tiles"] == [["work", "67%", "wk 1d"], ["home", "83%", "wk 15h"], ["spare", "72%", "wk 5d"],
                              ["Codex", "88%", "wk 18h"]]


def test_the_auto_switch_word_labels_the_native_switch_button():
    assert run("""
const row = limitsHead(STORE).querySelector(".autosw");
const [label, sw] = row.children;
console.log(JSON.stringify([label.tag, label.textContent, label.htmlFor, sw.tag, sw.id, sw.attrs.role]));
""", FABLE_FULL_EVERYWHERE) == ["label", "Auto-switch", "limits-auto-switch", "button", "limits-auto-switch", "switch"]


def test_limits_toggles_have_no_system_tooltip():
    assert run("""
console.log(JSON.stringify([limitsHead(STORE).children[0].title,
  compactFoot(STORE, CODEX).querySelector(".lim-toggle").title]));
""", FABLE_FULL_EVERYWHERE, compact=True) == ["", ""]


def test_the_compact_limits_toggle_names_the_active_account_before_its_action():
    assert run("""
STORE.accounts.find(account => account.active).name = "studio";
const toggle = compactFoot(STORE, CODEX).querySelector(".lim-toggle");
console.log(JSON.stringify([words(toggle), toggle.attrs["aria-label"]]));
""", FABLE_FULL_EVERYWHERE, compact=True) == [["›", "studio"], "studio limits: every window and account"]


def test_a_model_full_on_one_account_only_still_shows_on_that_accounts_bar():
    shown = run(FOLDED, store((12, 67, 100), (None, 83, 40), (3, 72, 55)))
    assert shown["tiles"] == [["work", "100%", "fab 1d"], ["home", "83%", "wk 15h"], ["spare", "72%", "wk 5d"],
                              ["Codex", "88%", "wk 18h"]]
    assert shown["titles"][0] == "work · 5-hour 12% · Weekly 67% · Fable 100%"


def test_an_account_with_no_other_limit_left_shows_the_full_one():
    shown = run(FOLDED, store((12, 67, 100), (None, 83, 100), (None, None, 100)))
    assert shown["tiles"][2] == ["spare", "100%", "fab 5d"]
    assert shown["titles"][2] == "spare · Fable 100%"


def test_a_near_switch_keeps_its_chip_beside_a_model_full_everywhere():
    near = store((92, 67, 100), (None, 83, 100), (3, 72, 100))
    assert (near["next_switch"]["near"], near["next_switch"]["to"]) == (True, "spare")
    shown = run(FOLDED, near)
    assert shown["head"] == ["›", "Accounts", "→ spare soon", "Auto-switch"]
    assert shown["tiles"][0] == ["work", "92%", "5h 3h"]


def test_the_compact_foot_shows_the_next_limit_with_room_and_no_chip_line():
    assert run(COMPACT, FABLE_FULL_EVERYWHERE, compact=True) == {
        "lines": [["›", "work", "wk", "67%"], ["Codex", "wk", "88%", "18h"]],
        "titles": ["work · 5-hour 12%, resets in 3h · Weekly 67%, resets in 1d 2h · Fable 100%, resets in 1d 2h"
                   f"\n{SET_ASIDE}",
                   "Codex · Weekly 88%, resets in 18h"],
    }


def test_the_compact_foot_keeps_a_near_switch_on_its_own_line():
    shown = run(COMPACT, store((92, 67, 100), (None, 83, 100), (3, 72, 100)), compact=True)
    assert shown["lines"] == [["›", "work", "5h", "92%", "3h"], ["→ spare soon"], ["Codex", "wk", "88%", "18h"]]


def test_the_tiny_foot_draws_the_next_limit_with_room_and_says_why_on_hover():
    assert run(COMPACT, FABLE_FULL_EVERYWHERE, compact=True, tiny=True) == {
        "lines": [["›"]],
        "titles": ["work · 5-hour 12%, resets in 3h · Weekly 67%, resets in 1d 2h · Fable 100%, resets in 1d 2h"
                   f"\n{SET_ASIDE}\nCodex · Weekly 88%, resets in 18h\nAccounts: every account and its windows"],
    }


def account_status(account):
    script = "\n".join([HELPERS[0], function(PAGE, "accountStatus"),
                        f"console.log(JSON.stringify(accountStatus({json.dumps(account)})));"])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=10,
                            env={**os.environ, "TZ": "UTC"})
    return json.loads(result.stdout)


def test_an_account_whose_login_cannot_be_refreshed_says_so_rather_than_waiting():
    assert account_status({"name": "work", "outcome": "refresh_failed", "fetched_at": None}) == "can't refresh its login"
    assert account_status({"name": "work", "outcome": "refresh_failed", "fetched_at": NOW - 600}) == \
        "as of 11:50, can't refresh its login"
    assert account_status({"name": "work", "outcome": "rate_limited", "fetched_at": None}) == "no reading yet"


CHIP = """
const chip = nextSwitchChip(STORE.next_switch);
console.log(JSON.stringify({text: chip.textContent, title: chip.title}));
"""
REASONING = "A switch drops the earlier reasoning of sessions on Fable 5.2, Sonnet 5.5 and Haiku 5.5."


def test_a_near_switch_says_on_hover_what_it_costs_those_models():
    assert run(CHIP, store((92, 67, 30), (None, 83, 40), (3, 72, 55))) == {
        "text": "→ spare soon",
        "title": f"5-hour at 92%; switches at 90% or when a window is on course for 100%. {REASONING}"}


def test_with_every_account_over_the_line_the_chip_names_where_it_goes_once_this_one_is_about_to_fill():
    assert run(CHIP, store((10, 94, 10), (None, 91, 10), (10, 96, 10))) == {
        "text": "→ home near 100%",
        "title": "weekly at 94%; every other account is over 90% too, so this one stays until it is about to "
                 f"fill, then moves to home. {REASONING}"}


def test_with_nowhere_emptier_the_chip_says_so_and_names_no_cost():
    assert run(CHIP, store((10, 94, 10), (None, 95, 10), (10, 96, 10))) == {
        "text": "no better account",
        "title": "weekly at 94%; no other account is at least 3 points emptier, so this one stays until one is"}


def test_a_full_window_carries_its_tier_onto_the_folded_tile_and_the_compact_line():
    """A tile and a compact line wear the meter's tiers; from a shown 98% that is full."""
    figures = store((12, 67, 98), (None, 83, 97.4), (3, 72, 55))
    tiers = """
const tiers = el => ["climbing", "near", "full"].filter(kind => el.classList.contains(kind));
"""
    assert run(tiers + """
console.log(JSON.stringify(foldedAccountTiles(STORE).map(tiers)));
""", figures) == [["near", "full"], ["near"], ["climbing"]]
    assert run(tiers + """
console.log(JSON.stringify(tiers(compactFoot(STORE, CODEX).children[0])));
""", figures, compact=True) == ["near", "full"]
