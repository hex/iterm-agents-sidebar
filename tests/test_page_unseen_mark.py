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
