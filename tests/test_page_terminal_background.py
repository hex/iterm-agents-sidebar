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
