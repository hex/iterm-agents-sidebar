# ABOUTME: Guards how page.html paints a card whose turn ended while you looked elsewhere.
# ABOUTME: An idle top-level row with unseen wears its own word in place of Idle; a subagent row never does.
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def corner_words():
    """paint()'s chain that picks the word in a card's corner, as
    (condition, body) pairs in the order the page tries them."""
    source = PAGE.read_text(encoding="utf-8")
    chain = re.search(r'\n      if \(hot\) \{\n(\s*const word = [^\n]*\n\s*word\.className = "word blocked";.*?)\n      \}\n\n',
                      source, re.S).group(1)
    return re.findall(r"else if \((.*?)\) \{\n(.*?)\n      \}", chain, re.S)


def test_an_unseen_idle_card_is_tried_before_the_plain_idle_one():
    conditions = [condition for condition, _ in corner_words()]
    unseen = conditions.index('row.state === "idle" && !row.depth && row.unseen')
    assert conditions[unseen + 1] == 'row.state === "idle" && !row.depth'


def test_an_unseen_idle_card_wears_the_unseen_word_and_class():
    [body] = [body for condition, body in corner_words() if condition.endswith("row.unseen")]
    assert 'word.className = "word unseen";' in body
    assert 'b.classList.add("unseen");' in body
    assert "idle" not in body


def test_an_unseen_idle_card_reads_done_where_an_idle_one_reads_idle():
    """The word the badge shows, in the sentence case every badge is set in,
    with no capitals from the rule they share: Done on an unseen idle card,
    Idle on one you have seen."""
    words = {condition: re.findall(r'word\.textContent = "([^"]*)";', body) for condition, body in corner_words()}
    assert words['row.state === "idle" && !row.depth && row.unseen'] == ["Done"]
    assert words['row.state === "idle" && !row.depth'] == ["Idle"]
    assert "text-transform" not in rule(".word")


def rule(selector):
    """The declarations of the first rule page.html writes for `selector`."""
    css = PAGE.read_text(encoding="utf-8")
    body = re.search(r"\n  " + re.escape(selector) + r" \{([^}]*)\}", css).group(1)
    return dict(re.findall(r"([\w-]+):\s*([^;]+?)\s*(?:;|$)", body.strip()))


def test_the_unseen_word_is_a_green_filled_badge_cut_like_idle():
    """The chosen look: the word on a fill of the panel's calm green, in the
    ink the page puts on its fills, cut as Idle's outline is: both take the
    border, padding and type every badge shares, and change only its colours."""
    word, unseen, idle = rule(".word"), rule(".word.unseen"), rule(".word.idle")
    assert word["border"] == "var(--hair) solid currentColor"
    assert word["padding"] == "0 4px"
    assert word["font"] == "600 10px/calc(16px - 2 * var(--hair)) -apple-system, sans-serif"
    assert unseen == {"color": "var(--accent-ink)", "background": "var(--sev-ok)", "border-color": "var(--sev-ok)"}
    assert idle == {"color": "var(--dim)"}


# ------------------------------------------------- the finished wash and band

def source():
    return PAGE.read_text(encoding="utf-8")


def theme_block(which):
    css = source()
    if which == "light":
        return re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    return re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}", css, re.S).group(1)


def test_an_unseen_finished_card_wears_the_finished_class_when_the_wash_is_on():
    body = re.search(r"\nfunction buildGroups\(.*?\n\}\n", source(), re.S).group(0)
    assert 'if (row.unseen && !row.depth && SETTINGS?.finished_wash !== false) li.classList.add("finished");' in body
    assert "row.bucket && !row.depth && !row.worktree_of && row.bucket !== lastBucket" in body


def test_the_finished_wash_outranks_rest_and_has_no_ring():
    """A card has no border; its edge is a box-shadow, a soft drop in the light
    theme. The washed card gets a one-pixel edge mixed toward the green in
    both themes, and never the two-pixel inset ring the amber card wears."""
    finished = rule("li.line.card.finished")
    assert finished["background"] == "var(--finished-bg)"
    assert finished["--finished-ring"] == "color-mix(in srgb, var(--sev-ok) 45%, var(--card-border))"
    assert finished["box-shadow"] == "0 0 0 1px var(--finished-ring)"
    assert "inset" not in finished["box-shadow"]
    css = source()
    assert css.index("li.line.card.finished {") > css.index("li.line.card.neglected {")


def test_a_docked_worktree_takes_the_wash_on_its_own_face():
    """A worktree face has no tint to outrank the plain finished rule, so it takes the wash as any card does; no
    worktree rule restates or overrides it."""
    assert rule("li.line.card.finished")["background"] == "var(--finished-bg)"
    restated = re.findall(r"\n  (li\.line\.card\.worktree\.finished[^{]*) \{([^}]*)\}", source())
    assert [selector for selector, body in restated if "background" in body] == []


def test_a_washed_cards_name_is_not_greyed():
    assert rule("li.line.card.finished > button.row.quiet .label") == {"color": "var(--fg)"}


def test_the_finished_tokens_are_the_specs_in_both_themes():
    assert "--finished-bg: #e8f5ec" in theme_block("light")
    assert "--finished-bg: #1f2e22" in theme_block("dark")


def drop_order(shown, remembered):
    """page.html's dropOrder() under node, with the cards on screen and the
    remembered hand order stubbed: `shown` is (name, band) pairs top first."""
    import json, subprocess
    page = source()
    limit = re.search(r"const HAND_ORDER_MAX = (\d+);", page).group(1)
    script = "\n".join([
        f"const HAND_ORDER_MAX = {limit};",
        f"const SHOWN = {json.dumps([{'label': name, 'band': band} for name, band in shown])};",
        f"const SETTINGS = {{hand_order: {json.dumps(remembered)}}};",
        "const topCards = () => SHOWN.map(row => ({row}));",
        "const cardRow = li => li.row;",
        re.search(r"\nconst shownNames = .*?;\n", page, re.S).group(0),
        re.search(r"\nfunction dropOrder\(.*?\n\}\n", page, re.S).group(0),
        "console.log(JSON.stringify(dropOrder()));",
    ])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_banded_card_keeps_its_remembered_index_in_the_drop_order():
    assert drop_order(shown=[("x", "finished"), ("a", None), ("b", None)], remembered=["a", "x", "b", "c"]) == ["a", "x", "b", "c"]
    assert drop_order(shown=[("x", "finished"), ("a", None)], remembered=[]) == ["a", "x"]
    assert drop_order(shown=[("a", None), ("b", None)], remembered=["b", "c"]) == ["a", "b", "c"]
    # A closed card remembered before the banded one must not push it past its neighbours.
    assert drop_order(shown=[("x", "finished"), ("a", None), ("b", None)], remembered=["c", "a", "x", "b"]) == ["a", "x", "b", "c"]
