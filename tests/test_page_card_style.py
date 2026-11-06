# ABOUTME: Guards the card style setting: the page names the chosen style on its root, the sheet offers every style the
# ABOUTME: daemon accepts, and the sheet groups its controls by event and appearance.
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "assets"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sidebar  # noqa: E402
from page_source import function  # noqa: E402
from panel_draw import setting_rows  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")


def run_node(script):
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(out.stdout)


ELEMENTS = """
const document = {createElement: tag => ({tag, children: [], attrs: {}, listeners: {}, dataset: {},
  get firstChild() { return this.children[0]; },
  get lastChild() { return this.children[this.children.length - 1]; },
  append(...children) { this.children.push(...children); },
  replaceChildren(...nodes) { this.children = nodes; },
  insertAdjacentHTML(where, html) { this.innerHTML = html; },
  setAttribute(k, v) { this.attrs[k] = v; },
  addEventListener(k, fn) { this.listeners[k] = fn; }
})};
"""


def root_styles(settings_seen):
    """Runs applyCardStyle under node once per SETTINGS value; -> the root's
    data-card-style after each."""
    script = "\n".join([
        "const ROOT = {dataset: {}};",
        "const document = {documentElement: ROOT};",
        "let SETTINGS = null;",
        function(PAGE, "applyCardStyle"),
        "const seen = [];",
        f"for (const s of {json.dumps(settings_seen)}) {{ SETTINGS = s; applyCardStyle(); seen.push(ROOT.dataset.cardStyle); }}",
        "console.log(JSON.stringify(seen));",
    ])
    return run_node(script)


def test_the_root_names_the_chosen_style_and_cards_before_settings_arrive():
    assert root_styles([None, {"card_style": "hairlines"}, {"card_style": "air"}, {"card_style": "inset"},
                        {"card_style": "outlines"}, {"card_style": "serenity"}, {"card_style": "cards"}]) == \
        ["cards", "hairlines", "air", "inset", "outlines", "serenity", "cards"]


def test_the_sheet_offers_every_style_the_daemon_accepts_by_its_name():
    row = next(r for r in setting_rows() if r.get("k") == "card_style")
    assert row["label"] == "Card style"
    assert row["choices"] == [["cards", "Cards"], ["hairlines", "Hairlines"], ["air", "Air"],
                              ["inset", "Inset rules"], ["outlines", "Outlines"], ["serenity", "Serenity"]]
    assert tuple(value for value, _ in row["choices"]) == sidebar.SETTING_CHOICES["card_style"]
    anatomy = next((r for r in setting_rows() if r.get("k") == "card_anatomy"), None)
    assert anatomy is not None, "Card anatomy is missing from the settings sheet"
    assert anatomy["label"] == "Card anatomy"
    assert anatomy["choices"] == [["task", "Task first"], ["name", "Name first"]]
    assert tuple(value for value, _ in anatomy["choices"]) == sidebar.SETTING_CHOICES["card_anatomy"]


def test_cards_is_the_page_as_it_was_and_every_other_style_has_its_rules():
    """No rule is keyed to cards, so choosing it leaves the stylesheet alone."""
    css = re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)
    keyed = set(re.findall(r'\[data-card-style="(\w+)"\]', css))
    assert keyed == {"hairlines", "air", "inset", "outlines", "serenity"}


def heads():
    """{head: [row keys under it, in order]}."""
    out, head = {}, None
    for row in setting_rows():
        if "head" in row:
            head = row["head"]
            out[head] = []
        else:
            out[head].append(row.get("k", row.get("action")))
    return out


@pytest.mark.parametrize("head, keys", [
    ("Alerts", ["sound", "volume", "notify"]),
    ("When a session waits for you", ["sound_blocked", "notify_blocked", "focus_blocked", "return_after_blocked"]),
    ("When one finishes", ["sound_done", "notify_done", "finished_first", "finished_wash", "mark_badge", "tab_status"]),
    ("Look", ["card_style", "card_anatomy", "follow_terminal", "tab_colour", "ui_scale", "shell_font", "provider_mark"]),
    ("On a card", ["show_branch", "show_task", "show_task_activity", "show_task_age", "show_task_bar", "show_task_list",
                   "show_model", "show_agents", "show_shells", "expand_shells"]),
    ("Rows", ["context_threshold", "cpu_threshold", "memory_threshold", "order", "offers"]),
    ("Experimental", ["links", "keep_remote", "commit_heatmap", "codex_memory_note"]),
])
def test_each_head_holds_its_settings_in_order(head, keys):
    assert heads().get(head) == keys


def test_the_tab_colour_switch_is_named_as_the_docs_name_it():
    """A plain switch: it needs no other setting and carries no note."""
    assert next(r for r in setting_rows() if r.get("k") == "tab_colour") == \
        {"k": "tab_colour", "label": "Session colour on the tab"}


def test_every_setting_sits_under_one_head_only():
    keys = [k for rows in heads().values() for k in rows]
    assert len(keys) == len(set(keys))


def test_on_a_card_is_a_remembered_fold():
    assert next(r for r in setting_rows() if r.get("head") == "On a card") == \
        {"head": "On a card", "fold": "on_card"}


def test_a_settings_fold_is_open_unless_its_id_is_closed():
    assert "\nfunction settingFoldOpen(" in PAGE, "Page does not define settingFoldOpen"
    script = "\n".join([
        "let SETTINGS = {sheet_folds: ['on_card']};",
        function(PAGE, "sheetFolds"),
        function(PAGE, "settingFoldOpen"),
        "const seen = [settingFoldOpen('on_card'), settingFoldOpen('alerts')];",
        "SETTINGS = {sheet_folds: []}; seen.push(settingFoldOpen('on_card'));",
        "SETTINGS = {}; seen.push(settingFoldOpen('on_card'));",
        "console.log(JSON.stringify(seen));",
    ])
    assert run_node(script) == [False, True, True, False]


def test_a_fold_title_controls_its_body_and_saves_each_toggle():
    script = "\n".join([
        ELEMENTS,
        """
let SETTINGS = {sheet_folds: ['on_card', 'another']};
let SETTING_SYNC = [];
let UNINSTALL = {state: "idle"};
const saved = [], LATEST = {repository: null};
const SETTING_ROWS = [{head: 'On a card', fold: 'on_card'}, {k: 'show_branch', label: 'Branch'}];
const drawer = document.createElement('div');
document.getElementById = () => drawer;
function push(value) { saved.push(value); Object.assign(SETTINGS, value); SETTING_SYNC.forEach(fn => fn()); }
""",
        function(PAGE, "sheetFolds"), function(PAGE, "settingFoldOpen"), function(PAGE, "settingCard"),
        function(PAGE, "settingRow"), function(PAGE, "settingSwitch"),
        function(PAGE, "settingsBody"), function(PAGE, "syncSettings"),
        function(PAGE, "repositoryCard"), function(PAGE, "githubRow"), function(PAGE, "paintRepository"),
        function(PAGE, "uninstallRow"), function(PAGE, "paintUninstall"),
        """
settingsBody();
const card = drawer.children[1].children[0];
const [title, body] = card.children;
SETTING_SYNC.forEach(fn => fn());
const seen = [[title.tag, title.type, title.attrs['aria-expanded'], title.attrs['aria-controls'], body?.id, body?.hidden]];
if (title.listeners.click) {
  title.listeners.click(); seen.push([title.attrs['aria-expanded'], body.hidden]);
  title.listeners.click(); seen.push([title.attrs['aria-expanded'], body.hidden]);
}
console.log(JSON.stringify({seen, saved}));
""",
    ])
    assert run_node(script) == {
        "seen": [["button", "button", "false", "set-fold-on_card", "set-fold-on_card", True],
                 ["true", False], ["false", True]],
        "saved": [{"sheet_folds": ["another"]}, {"sheet_folds": ["another", "on_card"]}],
    }


def test_the_offers_row_returns_both_offers_only_when_one_is_hidden():
    script = "\n".join([
        ELEMENTS,
        """
let SETTINGS = {offer_statusline: true, offer_tab_status: true};
const SETTING_SYNC = [], saved = [];
function push(value) { saved.push(value); Object.assign(SETTINGS, value); SETTING_SYNC.forEach(fn => fn()); }
""",
        function(PAGE, "settingSwitch"), function(PAGE, "settingRow"),
        """
const row = settingRow({action: 'offers', label: "Show the foot's offers again"}, 'plain');
const hidden = [];
for (const pair of [[true, true], [false, true], [true, false], [false, false]]) {
  [SETTINGS.offer_statusline, SETTINGS.offer_tab_status] = pair;
  SETTING_SYNC.forEach(fn => fn()); hidden.push(row.hidden ?? null);
}
if (row.listeners.click) row.listeners.click();
console.log(JSON.stringify({tag: row.tag, type: row.type, className: row.className,
  label: row.children[0].textContent, hidden, saved, after: row.hidden ?? null}));
""",
    ])
    assert run_node(script) == {
        "tag": "button", "type": "button", "className": "set plain out",
        "label": "Show the foot's offers again", "hidden": [True, False, False, False],
        "saved": [{"offer_statusline": True, "offer_tab_status": True}], "after": True,
    }
