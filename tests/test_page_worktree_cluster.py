# ABOUTME: Guards how page.html draws a session card and the worktree cards docked under it as one cluster.
# ABOUTME: One edge cut at the joins, a hairline past the mark column, and a waiting or finished worktree marked on its own face.
import re
from pathlib import Path

from page_source import function

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def css():
    return re.search(r"<style>(.*?)</style>", PAGE.read_text(encoding="utf-8"), re.S).group(1)


def rule(selector):
    """The declarations of the one rule page.html writes for `selector` alone, not as part of a list."""
    found = re.findall(r"(?<!,)\n  " + re.escape(selector) + r" \{([^}]*)\}", css())
    assert len(found) == 1, f"{selector}: {len(found)} rules"
    return dict(re.findall(r"([\w-]+):\s*([^;]+?)\s*(?:;|$)", found[0].strip()))


HEAD = ":where(#groups) li.line.card:has(+ li.line.card.worktree)"
DOCKED = ":where(#groups) li.line.card.worktree"
MIDDLE = ":where(#groups) li.line.card.worktree:has(+ li.line.card.worktree)"


def test_a_cluster_card_leaves_its_edge_to_the_cluster():
    """A card in a cluster draws no edge of its own, so no shadow crosses a join;
    the selector carries no weight, so a waiting card's ring still lands."""
    assert rule(":where(#groups) li.line.card:where(.worktree, :has(+ li.line.card.worktree))") == {"box-shadow": "none"}


def test_the_cluster_edge_is_the_cards_own_edge_cut_open_at_each_join():
    shared = re.search(re.escape(HEAD + "::after,") + r"\s*" + re.escape(DOCKED + "::after") + r" \{([^}]*)\}", css()).group(1)
    assert dict(re.findall(r"([\w-]+):\s*([^;]+?)\s*(?:;|$)", shared.strip())) == {
        "content": '""', "position": "absolute", "inset": "0", "border-radius": "inherit", "pointer-events": "none",
        "box-shadow": "var(--card-edge)"}
    assert rule(HEAD + "::after") == {"clip-path": "inset(-16px -16px 0)"}
    assert rule(DOCKED + "::after") == {"clip-path": "inset(0 -16px -16px)"}
    assert rule(MIDDLE + "::after") == {"clip-path": "inset(0 -16px)"}


def test_only_the_last_card_of_a_cluster_keeps_its_bottom_corners():
    assert rule("li.line.card:has(+ li.line.card.worktree)") == {
        "margin-bottom": "0", "border-bottom-left-radius": "0", "border-bottom-right-radius": "0"}
    assert rule("li.line.card.worktree") == {"border-top-left-radius": "0", "border-top-right-radius": "0"}


def test_the_hairline_between_faces_starts_after_the_mark_column_and_stops_short_of_the_edge():
    assert rule("li.line.card.worktree::before") == {
        "content": '""', "position": "absolute", "top": "0", "height": "1px", "pointer-events": "none",
        "left": "calc(var(--row-pad) + var(--mark) + var(--row-gap))", "right": "10px",
        "background": "var(--card-border)"}
    # Where a narrow card pads its row by hand, the hairline follows the row it sits over; a tiny row has no rings,
    # so there the hairline is the line between rows whatever their state.
    assert rule("html.compact li.line.card.worktree::before") == {"left": "calc(9px + var(--mark) + var(--row-gap))"}
    # A tiny row's hairline is the same hair as the line between any two of its rows.
    assert rule("html.tiny #groups li.line.card.worktree::before") == {
        "content": '""', "left": "calc(4px + var(--mark) + 5px)",
        "height": "var(--hair)", "background": "color-mix(in srgb, var(--fg) 11%, transparent)"}


def test_a_ringed_face_draws_its_own_line_and_takes_no_hairline():
    """A waiting or finished face's ring is the line between it and its neighbour, above or below."""
    pair = re.search(r"\n  (li\.line\.card\.worktree:is[^{]*?)::before,\s*\n  ([^{]*?)::before \{([^}]*)\}", css())
    assert pair.groups() == ("li.line.card.worktree:is(.blocked, .finished)",
                             "li.line.card:is(.blocked, .finished) + li.line.card.worktree", " content: none; ")


def test_a_worktree_face_wears_no_tint_of_its_family():
    """The family colour reaches a worktree card only through its mark: no rule
    reads data-family, and none paints a worktree face (the hairline and the
    stem are lines on it, not the face)."""
    assert "data-family" not in css()
    rules = re.findall(r"\n  ([^{}\n]*worktree[^{}\n]*) \{([^}]*)\}", css())
    painted = [s for s, body in rules if re.search(r"\bbackground(-color)?:", body)]
    assert painted == ["li.line.card.worktree::before", "li.line.card.worktree > .stem",
                       "html.tiny #groups li.line.card.worktree::before"]


def test_a_waiting_or_finished_card_in_a_cluster_marks_its_own_face_with_an_inset_ring():
    """Amber and green fill the one face; the ring is drawn inside it, so the
    cluster's outline stays one. The waiting card's ring is already inset."""
    blocked = rule("li.line.card.blocked")
    assert (blocked["--ring"], blocked["box-shadow"]) == ("2px", "inset 0 0 0 var(--ring) var(--blocked-border)")
    finished = rule("li.line.card.finished")
    assert finished["--finished-ring"] == "color-mix(in srgb, var(--sev-ok) 45%, var(--card-border))"
    assert finished["box-shadow"] == "0 0 0 1px var(--finished-ring)"
    assert rule("li.line.card.finished:where(.worktree, :has(+ li.line.card.worktree))") == {
        "--ring": "1px", "box-shadow": "inset 0 0 0 var(--ring) var(--finished-ring)"}
    sheet = css()
    assert sheet.index("li.line.card.finished:where(") > sheet.index("\n  li.line.card.finished {")


def test_a_cluster_card_easing_to_a_new_height_is_cut_only_along_its_foot():
    assert rule(":where(#groups) li.line.card.resizing:where(.worktree, :has(+ li.line.card.worktree))") == {
        "overflow": "visible", "clip-path": "inset(-16px -16px 0)"}


def test_the_ghost_of_a_cluster_is_cut_at_its_joins():
    assert rule(".drag-ghost li.line.card:has(+ li.line.card.worktree)") == {"clip-path": "inset(-40px -40px 0)"}
    # Each lower card overlaps the one above by a pixel, so two cuts never share the pixel the join falls in.
    assert rule(".drag-ghost li.line.card.worktree") == {"margin-top": "-1px", "clip-path": "inset(0 -40px -40px)"}
    assert rule(".drag-ghost li.line.card.worktree:has(+ li.line.card.worktree)") == {"clip-path": "inset(0 -40px)"}


def test_a_tiny_row_draws_no_cluster_edge():
    assert rule("html.tiny #groups li.line.card::after") == {"content": "none"}


# ------------------------------------------------- the fork and its stem

FORK = ("M224,64a32,32,0,1,0-40,31v17a8,8,0,0,1-8,8H80a8,8,0,0,1-8-8V95a32,32,0,1,0-16,0v17a24,24,0,0,0,24,24h40v25a32,"
        "32,0,1,0,16,0V136h40a24,24,0,0,0,24-24V95A32.06,32.06,0,0,0,224,64ZM48,64A16,16,0,1,1,64,80,16,16,0,0,1,48,64Zm96,"
        "128a16,16,0,1,1-16-16A16,16,0,0,1,144,192ZM192,80a16,16,0,1,1,16-16A16,16,0,0,1,192,80Z")


def source():
    return PAGE.read_text(encoding="utf-8")


def test_the_fork_is_phosphors_regular_git_fork():
    assert f"  fork: '<path d=\"{FORK}\"/>',\n" in source()


def test_a_worktree_cards_mark_is_the_fork_whatever_its_state():
    """The worktree card's own row takes the fork before any other mark is
    considered, so a working worktree shows no dots there."""
    body = function(source(), "buildGroups")
    marks = body[body.index('const mark = document.createElement("span");'):]
    first = re.search(r"\n      (if \([^\n]*\)) \{\n(.*?)\n      \} else if", marks, re.S)
    assert first.group(1) == 'if (card.classList.contains("worktree") && !row.depth)'
    assert first.group(2).split("\n") == ['        mark.className = "swatch fork";', '        mark.append(metaIcon("fork"));']


def test_the_fork_wears_the_main_sessions_colour_in_the_marks_slot():
    assert rule(".swatch.fork") == {"color": "var(--family, var(--dim))"}
    assert rule(".swatch.fork::before") == {"content": "none"}
    assert rule(":is(.shell-mark, .swatch.fork) .mi") == {
        "width": "calc(var(--mark) + 3px)", "height": "calc(var(--mark) + 3px)", "opacity": "1"}


def test_the_stem_is_a_neutral_line_from_the_card_above():
    # A ringed face hangs it from under its ring, as wide as the ring its state sets.
    assert rule("li.line.card.worktree > .stem") == {
        "position": "absolute", "top": "var(--ring, 0)", "width": "1px", "pointer-events": "none",
        "background": "color-mix(in srgb, var(--fg) 32%, transparent)"}
    # A tiny row draws no ring, so there every stem starts at the row's top.
    assert rule("html.tiny #groups li.line.card.worktree > .stem") == {"top": "0"}


def paint_stems(cards):
    """page.html's paintStems() under node, over stub cards. Each card gives
    its box (viewport pixels) and its offset size (the page's, rounded to whole
    pixels as the DOM rounds it), its glyph's box and its stem's offsetTop; it
    returns, per card, every style write in order."""
    import json, subprocess
    paint = function(source(), "paintStems")
    script = "\n".join([
        f"const CARDS = {json.dumps(cards)};",
        "const writes = CARDS.map(() => []);",
        "const lis = CARDS.map((c, i) => {",
        "  const style = new Proxy({}, {set(t, k, v) { writes[i].push([k, v]); t[k] = v; return true; }});",
        "  const stem = {offsetTop: c.stemTop, style};",
        "  const glyph = {getBoundingClientRect: () => c.glyph};",
        "  return {offsetWidth: c.offsetWidth, offsetHeight: c.offsetHeight, getBoundingClientRect: () => c.box,",
        "    querySelector: s => s === ':scope > .stem' ? stem : s === ':scope > button.row > .swatch.fork > svg' ? glyph : null};",
        "});",
        "const document = {querySelectorAll: s => s === '#groups li.line.card.worktree' ? lis : []};",
        paint,
        "paintStems(); paintStems();",
        "console.log(JSON.stringify(writes));",
    ])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_stem_runs_from_its_top_to_the_forks_top_down_the_forks_middle():
    """Measured, so a card whose glyph sits lower (a report under the name), a
    stem that starts lower, or a narrow card that pads its row differently
    still lands it; at a zoomed text size the viewport's pixels are turned
    back into the page's. A card a fraction of a pixel taller than its rounded
    offsetHeight is not read as zoomed. A second paint with nothing moved
    writes nothing."""
    plain = {"box": {"left": 8, "top": 100, "width": 364, "height": 51.19}, "offsetWidth": 364, "offsetHeight": 51,
             "glyph": {"left": 16.5, "top": 117.5, "width": 11, "height": 11}, "stemTop": 0}
    lower = dict(plain, glyph={"left": 16.5, "top": 121.5, "width": 11, "height": 11})
    started_lower = dict(plain, stemTop=2)
    zoomed = {"box": {"left": 10, "top": 200, "width": 455, "height": 125}, "offsetWidth": 364, "offsetHeight": 100,
              "glyph": {"left": 20.625, "top": 220, "width": 13.75, "height": 13.75}, "stemTop": 0}
    assert paint_stems([plain, lower, started_lower, zoomed]) == [
        [["left", "13.5px"], ["height", "17.5px"]],
        [["left", "13.5px"], ["height", "21.5px"]],
        [["left", "13.5px"], ["height", "15.5px"]],
        [["left", "13.5px"], ["height", "16px"]],
    ]
