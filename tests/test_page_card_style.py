# ABOUTME: Guards the card style setting: the page names the chosen style on its root, the sheet offers every style the
# ABOUTME: daemon accepts, and the Style head holds the look of the rows in its set order while Rows keeps the rest.
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "assets"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sidebar  # noqa: E402
from page_source import function  # noqa: E402
from panel_draw import setting_rows  # noqa: E402

PAGE = (ROOT / "page.html").read_text(encoding="utf-8")


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
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_root_names_the_chosen_style_and_cards_before_settings_arrive():
    assert root_styles([None, {"card_style": "hairlines"}, {"card_style": "air"}, {"card_style": "inset"},
                        {"card_style": "outlines"}, {"card_style": "cards"}]) == \
        ["cards", "hairlines", "air", "inset", "outlines", "cards"]


def test_the_sheet_offers_every_style_the_daemon_accepts_by_its_name():
    row = next(r for r in setting_rows() if r.get("k") == "card_style")
    assert row["label"] == "Card style"
    assert row["choices"] == [["cards", "Cards"], ["hairlines", "Hairlines"], ["air", "Air"],
                              ["inset", "Inset rules"], ["outlines", "Outlines"]]
    assert tuple(value for value, _ in row["choices"]) == sidebar.SETTING_CHOICES["card_style"]


def test_cards_is_the_page_as_it_was_and_every_other_style_has_its_rules():
    """No rule is keyed to cards, so choosing it leaves the stylesheet alone."""
    css = re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)
    keyed = set(re.findall(r'\[data-card-style="(\w+)"\]', css))
    assert keyed == {"hairlines", "air", "inset", "outlines"}


def heads():
    """{head: [row keys under it, in order]}."""
    out, head = {}, None
    for row in setting_rows():
        if "head" in row:
            head = row["head"]
            out[head] = []
        else:
            out[head].append(row["k"])
    return out


def test_the_style_head_holds_the_look_of_the_rows_in_order():
    assert heads()["Style"] == [
        "card_style", "follow_terminal", "ui_scale", "shell_font", "provider_mark", "finished_wash",
        "show_branch", "show_task", "show_task_activity", "show_task_age", "show_task_bar", "show_task_list",
        "show_model", "show_agents", "show_shells", "expand_shells"]


def test_rows_keeps_the_thresholds_the_order_and_the_two_offers():
    assert heads()["Rows"] == ["context_threshold", "cpu_threshold", "memory_threshold", "order",
                               "offer_statusline", "offer_tab_status"]


def test_every_setting_sits_under_one_head_only():
    keys = [k for rows in heads().values() for k in rows]
    assert len(keys) == len(set(keys))
