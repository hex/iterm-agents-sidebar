# ABOUTME: Guards the panel's colours following the terminal: each dark block's two ways in carry the same declarations,
# ABOUTME: and the page picks its theme from the terminal colour's lightness and drops it when there is none.
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")


def run(body):
    """Runs `body` under node after page.html's theme functions, over a root
    element that keeps what is written to it; -> what `body` logs, parsed."""
    script = "\n".join([
        "const ROOT = {dataset: {}, style: {props: {},",
        "  setProperty(k, v) { this.props[k] = v; }, removeProperty(k) { delete this.props[k]; },",
        "  getPropertyValue(k) { return this.props[k] ?? ''; }}};",
        "const document = {documentElement: ROOT, getElementById: () => null};",
        "let SETTINGS = null;",
        function(PAGE, "termTheme"),
        function(PAGE, "applyTerminalBackground"),
        function(PAGE, "terminalBackgroundNote"),
        "const root = () => ({theme: ROOT.dataset.termTheme ?? null, bg: ROOT.style.props['--term-bg'] ?? null});",
        body,
    ])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_terminal_colour_darker_than_a_luminance_of_four_tenths_is_dark():
    """WCAG relative luminance: #a9a9a9 is .397 and #aaaaaa .402."""
    colours = ["#282a36", "#151728", "#000000", "#a9a9a9", "#aaaaaa", "#fdf6e3", "#ffffff"]
    assert run(f"console.log(JSON.stringify({json.dumps(colours)}.map(termTheme)))") == \
        ["dark", "dark", "dark", "dark", "light", "light", "light"]


def test_the_page_follows_a_terminal_colour_and_returns_to_its_own_without_one():
    """No colour, whether unread or with the setting off, leaves no attribute
    and no --term-bg on the root: the page is as macOS's theme paints it."""
    assert run("""
        const seen = [];
        applyTerminalBackground({terminal_background: "#fdf6e3"}); seen.push(root());
        applyTerminalBackground({terminal_background: "#282a36"}); seen.push(root());
        applyTerminalBackground({terminal_background: null}); seen.push(root());
        applyTerminalBackground({terminal_background: "#282a36"});
        SETTINGS = {follow_terminal: false};
        applyTerminalBackground({terminal_background: "#282a36"}); seen.push(root());
        SETTINGS = {follow_terminal: true};
        applyTerminalBackground({}); seen.push(root());
        console.log(JSON.stringify(seen));
    """) == [{"theme": "light", "bg": "#fdf6e3"}, {"theme": "dark", "bg": "#282a36"},
             {"theme": None, "bg": None}, {"theme": None, "bg": None}, {"theme": None, "bg": None}]


def test_the_settings_line_says_the_colour_read_or_that_it_was_not():
    assert run("""
        const note = {};
        const seen = [];
        terminalBackgroundNote(note, {terminal_background: "#282a36"}); seen.push([note.textContent, note.hidden]);
        terminalBackgroundNote(note, {terminal_background: null}); seen.push([note.textContent, note.hidden]);
        SETTINGS = {follow_terminal: false};
        terminalBackgroundNote(note, {terminal_background: null}); seen.push(note.hidden);
        console.log(JSON.stringify(seen));
    """) == [["Terminal background #282a36", False], ["Terminal background (not read)", False], True]


MEDIA = '@media (prefers-color-scheme: dark) { :root:not([data-term-theme="light"])'
TERM = ':root[data-term-theme="dark"]'


def dark_blocks():
    """Each dark block as its two copies: (declarations under the media query
    while no terminal colour says light, declarations under the terminal's
    dark), whitespace folded."""
    fold = lambda text: " ".join(text.split())
    css = fold(PAGE)
    media = re.findall(re.escape(MEDIA) + r"( #\w+)? \{ (.*?) \} \}", css)
    term = re.findall(re.escape(TERM) + r"( #\w+)? \{ (.*?) \}", css)
    return media, term


def test_each_dark_block_says_the_same_under_macos_dark_and_under_a_dark_terminal():
    """A media query cannot share a selector list, so the dark tokens stand
    twice; a value changed in one copy and not the other would make the panel
    differ between macOS's dark and a dark terminal colour. The terminal's
    dark has rules of its own besides (its color-scheme, its derived surfaces)."""
    media, term = dark_blocks()
    assert [sel for sel, _ in media] == ["", "", " #scrim"]
    assert [block for block in media if block not in term] == []
    assert "--bg: #1c1c1e;" in media[0][1] and "--effort-low: #bb9f6d;" in media[1][1]


def test_on_a_dark_terminal_a_cards_name_and_report_take_the_hue_of_their_ground_and_a_subagents_name_a_warm_white():
    """Softer than white, the same on every card: a session's name and its
    report's title are a pale tint of the hue of the ground they sit on, the
    card's own (the terminal's hue) or, for a finished card's report, its
    green wash, and never more saturated than that ground, so a grey or black
    terminal leaves them neutral instead of the red its powerless hue reads
    as. A subagent's or teammate's name is a warm paper white a step below. A
    resting name keeps its grey and a waiting card its own colours."""
    rules = {sel.strip(): body.strip() for sel, body in re.findall(r"\n  (:root\[data-term-theme=\"dark\"\][^{]+)\{([^}]*)\}", PAGE)}
    assert rules[':root[data-term-theme="dark"] li.line.card'] == "--ink-ground: var(--card);"
    assert rules[':root[data-term-theme="dark"] li.line.card.finished'] == "--ink-ground: var(--finished-bg);"
    assert rules[':root[data-term-theme="dark"] li.line.card:not(.blocked) > button.row:not(.quiet) :is(.label, .label .run)'] == \
        "color: oklch(from var(--ink-ground) .86 min(.035, c) h);"
    assert rules[':root[data-term-theme="dark"] li.line.card:not(.blocked) .task .task-title'] == \
        "color: oklch(from var(--ink-ground) .72 min(.03, c) h); opacity: 1;"
    assert rules[':root[data-term-theme="dark"] .children button.row:not(.quiet) :is(.label, .label .run)'] == \
        "color: oklch(.74 .02 75);"
