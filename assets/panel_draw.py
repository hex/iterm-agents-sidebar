# ABOUTME: What the README's drawings share: the panel's dark-theme colours and marks,
# ABOUTME: read out of page.html, and the primitives that draw a card the way the panel does.
"""The marks and the colours are read out of page.html, so a drawing cannot
drift from the panel it advertises. Each drawing script appends to `out`
through `A` and writes the file itself.
"""
import json, pathlib, re

PAGE = pathlib.Path(__file__).resolve().parent.parent / "page.html"

# The panel's dark-theme tokens, from page.html: it follows macOS appearance,
# so beside a dark terminal it is dark too.
BG, FG, DIM, RULE = "#1c1c1e", "#f2f2f7", "#98989d", "#3a3a3c"
CARD, CARD_BORDER = "#2c2c2e", "#3a3a3c"
BLOCKED_BG, BLOCKED_BORDER, BADGE_INK = "#3a2500", "#ff9f0a", "#3a2500"
BLOCKED_TEXT = "#ffd60a"
LIT, LIT_INK, ALERT = "#8ec07c", "#8ec07c", "#fb8b5e"
TERM_BG, TERM_FG, TERM_DIM = "#141416", "#e5e5ea", "#8e8e93"
CLAUDE_MARK = "#d97757"
POINTER_FILL, POINTER_EDGE = "#1c1c1e", "#ffffff"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"

out = []
A = out.append


def marks():
    """The icon paths page.html draws, by name, with the viewBox they assume."""
    page = PAGE.read_text()
    found = {}
    for name in ("branch", "clock", "computer", "cpu", "model", "gauge", "shells",
                 "switch", "warning", "check", "tasks", "memory", "reload", "gear", "cost"):
        m = re.search(r"^  %s: '(.+)',?$" % name, page, re.M)
        if m:
            found[name] = (m.group(1), 256)
    for name in ("claude", "openai", "omp"):
        m = re.search(r"^  %s: '(.+)',$" % name, page, re.M)
        if m:
            found[name] = (m.group(1), 24)
    return found


MARK = marks()


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, fill=FG, size=13, weight=400, family=SANS, extra=""):
    A(f'  <text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" '
      f'font-family="{family}"{extra}>{esc(s)}</text>')


def mark(name, x, y, size, fill):
    """One of the panel's own marks, its top-left at (x, y)."""
    path, box = MARK[name]
    A(f'  <g transform="translate({x},{y}) scale({size/box:.4f})" fill="{fill}">{path}</g>')



#: Rendered widths at 12.5px in the sans face, measured in Chrome with canvas
#: measureText. A per-character guess put the middots visibly off-centre.
#: Widths below are measured in Chrome, as MEASURED is: names at 600 15px, tag
#: words at 600 11px.
#: The agents a card can run, as page.html's AGENT_KINDS and its dark-theme
#: --ink tokens have them: (name on the tag, glyph colour, the words' ink).
AGENTS = {"claude": ("Claude", "#d97757", "#e08f75"), "openai": ("Codex", "#10a37f", "#3bb496"),
          "omp": ("omp", "#6d5ae6", "#9f92ee")}
TAG_TEXT = {"Claude": 38.2, "Codex": 34.6, "omp": 23.9}
NAME_W = {"atlas": 34.6, "beacon": 52.7, "ember": 46.1, "harbor": 47.8}


def tag(x, baseline, kind):
    """The pill after a session's name that says which agent runs in it; x is
    where the pill starts, past the name."""
    word, colour, ink = AGENTS[kind]
    w = 10 + 4 + TAG_TEXT[word] + 12
    A(f'  <rect x="{x}" y="{baseline-13}" width="{w:.1f}" height="17" rx="5" fill="{colour}" opacity="0.16"/>')
    mark(kind, x + 5, baseline - 10, 11, colour)
    text(x + 19, baseline - 0.5, word, fill=ink, size=11, weight=600)



MEASURED = {"main": 28.0, "Fable 5.1": 51.2, "feat/cache": 61.7, "gpt-6-astra": 68.5,
            "CPU": 26.0, "Writing tests": 74.2, "Choosing a store": 99.0, "gpt-5.6-luna": 74.0, "31%": 25.1,
            "Reading code": 80.0, "40s": 22.4, "2m": 18.3, "12m": 24.1, "3m": 18.6,
            "Done": 30.8, "stale": 28.0, "Opus 5": 42.1, "Mem": 28.8, "82%": 27.0,
            "94%": 27.5, "$0.42": 34.0, "feat/search": 65.7, "release": 42.3,
            "1h 12m": 40.7, "25m": 26.0, "feat/auth": 52.4, "Running the suite": 102.0,
            "Reviewing the diff": 104.9, "1h 2m": 34.9, "5m": 18.5, "8m": 18.8, "32%": 26.8,
            "$0.18": 32.2, "$0.07": 33.0}
#: The same table for the names, at 600 15px.
NAME_W.update({"cinder": 45.3, "delta": 36.1})
DOT_W, DOT_GAP = 3.7, 7


def width_of(s, size, family=SANS):
    if family == MONO:
        # The mono face is 0.602em a character, measured at 10 and 11px.
        return len(s) * size * 0.602
    if size == 12.5 and s in MEASURED:
        return MEASURED[s]
    return len(s) * size * 0.55


def middot(x, baseline, fill=DIM, size=12.5):
    """A separator with the same air on both sides. -> where the next item starts."""
    text(x + DOT_GAP, baseline, "\u00b7", fill=fill, size=size)
    return x + DOT_GAP + DOT_W + DOT_GAP


def chips(x, baseline, items, fill=DIM, size=12.5):
    """The facts line: a mark and its value, middots between. -> where it ends."""
    for i, (name, label, colour) in enumerate(items):
        if i:
            x = middot(x, baseline, fill, size)
        mark(name, x, baseline - 11, 13, colour or fill)
        text(x + 17, baseline, label, fill=colour or fill, size=size)
        x += 17 + width_of(label, size)
    return x




def card(x, w, top, height):
    A(f'  <rect x="{x}" y="{top}" width="{w}" height="{height}" rx="10" fill="{CARD}" '
      f'stroke="{CARD_BORDER}"/>')


def swatch(x, top, hue, hollow=False):
    """A resting session's square, its left edge at x."""
    if hollow:
        A(f'  <rect x="{x}" y="{top}" width="11" height="11" rx="3" fill="none" '
          f'stroke="{DIM}" stroke-width="1.6"/>')
    else:
        A(f'  <rect x="{x}" y="{top}" width="11" height="11" rx="3" fill="{hue}"/>')


def working_dots(x, top, hue):
    """What a session at work wears where a resting one wears its square."""
    for i in range(3):
        A(f'  <circle cx="{x+1+i*5}" cy="{top+6}" r="2" fill="{hue}">'
          f'<animate attributeName="opacity" values="0.25;1;0.25" dur="1.4s" '
          f'begin="{i*0.18:.2f}s" repeatCount="indefinite"/></circle>')


def badge(right, top, word, filled=False, animation=""):
    """The state word in a card's top corner, its right edge at `right`."""
    w = 70 if len(word) > 4 else 52
    x = right - w
    fill = BLOCKED_BORDER if filled else "none"
    ink = BADGE_INK if filled else DIM
    A(f'  <g>{animation}<rect x="{x}" y="{top}" width="{w}" height="21" rx="4" fill="{fill}" '
      f'stroke="{"none" if filled else DIM}"/>'
      f'<text x="{x + w/2}" y="{top+15}" fill="{ink}" font-size="10" font-weight="700" '
      f'letter-spacing="1" text-anchor="middle" font-family="{SANS}">{word}</text></g>')


def setting_rows():
    """page.html's SETTING_ROWS, one dict a row, so a drawing of the sheet
    lists what the sheet lists. A head is {"head": ...}; a row has k and
    label, and any of master, needs, range, pct, unit, choices, steps."""
    block = re.search(r"^const SETTING_ROWS = \[\n(.*?)^\];", PAGE.read_text(), re.S | re.M).group(1)
    rows = []
    for m in re.finditer(r"\{(.*?)\}(?=,\n|\n)", block, re.S):
        row = {}
        for key, value in re.findall(r'(\w+):\s*("[^"]*"|\[.*?\]\]|\[[^\]]*\]|true|[\d.]+)', m.group(1)):
            # JS writes .05 where JSON wants 0.05.
            row[key] = json.loads(re.sub(r"(?<![\d.])\.(\d)", r"0.\1", value))
        rows.append(row)
    return rows


#: The notes' ink: a step above the panel's dim grey, so they read beside it.
NOTE_INK = "#aeaeb2"


class Notes:
    """Words about the parts of a drawing, kept out of its way: each part
    gets one line of small grey type at the right, joined by a hairline that
    starts where the part ends."""
    def __init__(self, x_words):
        self.x = x_words
        self.rows = []

    def add(self, x, y, words):
        self.rows.append((x, y, words))

    def draw(self):
        for x, y, words in self.rows:
            A(f'  <line x1="{x}" y1="{y}" x2="{self.x - 8}" y2="{y}" stroke="{NOTE_INK}" '
              f'stroke-width="0.8" opacity="0.45" stroke-dasharray="2 3"/>')
            text(self.x, y + 4, words, fill=NOTE_INK, size=12)
