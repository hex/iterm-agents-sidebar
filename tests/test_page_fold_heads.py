# ABOUTME: Checks the foot folds' full-row targets, focus rings and reading geometry.
# ABOUTME: Keeps the compact foot separate and verifies the finite motion rules in page.html.
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")


def declarations(selector):
    css = re.sub(r"/\*.*?\*/", "", PAGE, flags=re.S)
    return " ".join(body for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
                    if selector in [part.strip() for part in selectors.split(",")])


def test_fold_heads_cover_the_row_and_its_gutters():
    rule = declarations("#budget .past > .lim-toggle")
    assert "width: calc(100% + 12px)" in rule
    focus = declarations("#budget .past > .lim-toggle:focus-visible")
    assert "outline: 1px solid var(--hot)" in focus
    assert "outline-offset: -1px" in focus
    assert "box-shadow: 0 0 0 3px color-mix(in srgb, var(--hot) 22%, transparent)" in focus
    # A fold head's tint fills the 24px band between the hairlines, its
    # margins giving back what it adds, so the foot keeps its height.
    head = declarations("#budget .past > .lim-toggle")
    for value in ("height: 24px", "margin: -6px", "padding: 7px 6px"):
        assert value in head
    assert "height: 12px" not in head
    assert "width: calc(100% + 12px)" not in declarations("#budget .lim-toggle")
    assert "outline-offset: -1px" in declarations("#budget .lim-head > .lim-toggle:focus-visible::before")
    # The Accounts head's tint is the same band: the head is 18px, so its tint
    # reaches 3px past it above and below, with the fold heads' corners.
    limits = declarations("#budget .lim-head > .lim-toggle::before")
    for value in ("inset: -3px 0", "border-radius: 6px"):
        assert value in limits


def test_history_tabs_keep_the_arrow_and_take_the_heads_focus_ring():
    assert "cursor: default" in declarations("#budget .hist-tab")
    focus = declarations("#budget .hist-tab:focus-visible")
    assert "outline: 1px solid var(--hot)" in focus
    assert "box-shadow: 0 0 0 3px color-mix(in srgb, var(--hot) 22%, transparent)" in focus


def test_reading_placeholders_reserve_the_picked_entry_height():
    assert "min-height: 24px" in declarations("#budget .unlit .u-entry")


def test_activity_placeholders_keep_the_chart_slots_and_the_name_and_figure_rows():
    assert "height: 100%" in declarations("#budget .unlit .act-week i")
    assert "min-height: 0" in declarations("#budget .unlit .act-week i")
    assert "grid-template-columns: minmax(0, 1fr) 5ch" in declarations("#budget .act-row")
    assert "min-height: 20px" in declarations("#budget .act-row")
    assert "width: 5ch" in declarations("#budget .unlit .act-row .tok")
    assert "cursor: default" in declarations("#budget .unlit .act-week > *")


def test_the_reading_gauge_is_finite_and_absent_under_reduced_motion():
    motion = []
    for start in re.finditer(r"@media \(prefers-reduced-motion: no-preference\)\s*\{", PAGE):
        depth, end = 1, start.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(PAGE[end], 0)
            end += 1
        motion.append(PAGE[start.end():end - 1])
    gauge = next((part for part in motion if "gauge-fill" in part), "")
    assert "#budget .past > .lim-toggle.reading::after" in gauge
    for value in ("animation: gauge-fill 1.6s cubic-bezier(.2,.6,.4,1) .18s both",
                  "from { transform: scaleX(0); } to { transform: scaleX(.88); }"):
        assert value in gauge
    # Activity's fill has a name of its own: the head stays one element across the tabs, and only a
    # change of name, not of duration, starts a running gauge again from the left.
    assert ('#budget .past > .lim-toggle[data-wait="activity"]::after'
            ' { animation-name: gauge-fill-week; animation-duration: 7s; }') in gauge
    assert "@keyframes gauge-fill-week { from { transform: scaleX(0); } to { transform: scaleX(.88); } }" in gauge
    assert "animation: unlit-in 0s linear .18s both" in declarations("#budget .unlit")
    assert "#budget .unlit { animation-duration: .2s; animation-timing-function: ease-out; }" in gauge
    assert PAGE.count("@keyframes gauge-fill ") == 1
    assert PAGE.count("@keyframes gauge-fill-week ") == 1
    assert PAGE.count("@keyframes unlit-in") == 1
    assert "infinite" not in gauge
    assert PAGE.count(".lim-toggle.reading::after") == 1


def test_usage_names_the_picked_empty_copy():
    usage = " ".join((Path(__file__).resolve().parent.parent / "docs/usage.md").read_text(encoding="utf-8").split())
    for words in ("Nothing to resume from the last 7 days; the ones open now are on their cards.",
                  "No prompts or tokens in `~/.claude/projects` or `~/.codex/sessions` over the last 7 days.",
                  "Nothing on Tuesday · Show the week"):
        assert words in usage


def test_empty_fold_notes_set_log_paths_in_the_foot_mono_with_the_picked_ink():
    rule = declarations("#budget .fold-note code")
    assert "ui-monospace, Menlo, monospace" in rule
    assert "color: var(--fg)" in rule
    assert "opacity: .8" in rule
