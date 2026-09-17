# ABOUTME: Draws assets/banner.svg, the README banner: an iTerm2 window with Claude Code
# ABOUTME: on the left and the Agents panel docked on the right, looping two story beats.
"""The marks and the colours are read out of page.html, so the drawing cannot
drift from the panel it advertises. Session names are invented.
"""
import pathlib, re, sys

PAGE = pathlib.Path(__file__).resolve().parent.parent / "page.html"
W, H = 1536, 614
CYCLE = "11s"

# The panel's dark-theme tokens, from page.html: it follows macOS appearance,
# so beside a dark terminal it is dark too.
BG, FG, DIM, RULE = "#1c1c1e", "#f2f2f7", "#98989d", "#3a3a3c"
CARD, CARD_BORDER = "#2c2c2e", "#3a3a3c"
BLOCKED_BG, BLOCKED_BORDER, BADGE_INK = "#3a2500", "#ff9f0a", "#3a2500"
LIT, LIT_INK, ALERT = "#8ec07c", "#8ec07c", "#fb8b5e"
TERM_BG, TERM_FG, TERM_DIM = "#141416", "#e5e5ea", "#8e8e93"
CLAUDE_MARK = "#d97757"
POINTER_FILL, POINTER_EDGE = "#1c1c1e", "#ffffff"

SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"

# The window nearly fills the frame: what is left is room for its shadow,
# because the transparent margin reads as a white border on GitHub.
WX, WY, WW, WH = 16, 12, 1504, 578
BAR = 44
PANEL_W = 430
PX = WX + WW - PANEL_W
CARD_X, CARD_W = PX + 14, PANEL_W - 28

out = []
A = out.append


def marks():
    """The icon paths page.html draws, by name, with the viewBox they assume."""
    page = PAGE.read_text()
    found = {}
    for name in ("branch", "clock", "computer", "cpu"):
        m = re.search(r"^  %s: '(.+)',?$" % name, page, re.M)
        if m:
            found[name] = (m.group(1), 256)
    for name in ("claude", "openai"):
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


def cycle(attr, values, key_times, **kw):
    """One SMIL animation over the whole loop, so every beat stays in step."""
    bits = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
    return (f'<animate attributeName="{attr}" dur="{CYCLE}" repeatCount="indefinite" '
            f'values="{values}" keyTimes="{key_times}" {bits}/>')


#: Rendered widths at 12.5px in the sans face, measured in Chrome with canvas
#: measureText. A per-character guess put the middots visibly off-centre.
MEASURED = {"main": 28.0, "Fable 5.1": 51.2, "feat/cache": 61.7, "gpt-6-astra": 68.5,
            "CPU": 26.0, "Writing tests": 74.2}
DOT_W, DOT_GAP = 3.7, 7


def width_of(s, size):
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


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
  f'role="img" aria-label="An iTerm2 window with the Agents sidebar docked on the right: one card '
  f'per session, with the one waiting on a question turning amber">')
A('  <title>Agents sidebar</title>')
A(f'''  <defs>
    <filter id="drop" x="-6%" y="-14%" width="112%" height="140%">
      <feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#1c1c1e" flood-opacity="0.22"/>
    </filter>
    <pattern id="tickmask" width="9" height="5" patternUnits="userSpaceOnUse">
      <rect width="5" height="5" fill="#ffffff"/>
    </pattern>
    <mask id="tick"><rect width="{W}" height="{H}" fill="url(#tickmask)"/></mask>
    <clipPath id="window"><rect x="{WX}" y="{WY}" width="{WW}" height="{WH}" rx="16"/></clipPath>
  </defs>''')

A(f'  <g filter="url(#drop)"><rect x="{WX}" y="{WY}" width="{WW}" height="{WH}" rx="16" '
  f'fill="{TERM_BG}"/></g>')
A('  <g clip-path="url(#window)">')
A(f'  <rect x="{PX}" y="{WY}" width="{PANEL_W}" height="{WH}" fill="{BG}"/>')
# iTerm2's Minimal theme: the tabs share the title bar's row and the terminal's
# own colour, the one in front a shade lighter, each tab named by its session
# with its Cmd-number at the right.
TAB_BG, TAB_EDGE = "#0a0a0b", "#26262a"
A(f'  <rect x="{WX}" y="{WY}" width="{WW}" height="{BAR}" fill="{TAB_BG}"/>')
A(f'  <line x1="{WX}" y1="{WY+BAR}" x2="{WX+WW}" y2="{WY+BAR}" stroke="{TAB_EDGE}"/>')
A(f'  <line x1="{PX}" y1="{WY+BAR}" x2="{PX}" y2="{WY+WH}" stroke="{TAB_EDGE}"/>')
for i, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
    A(f'  <circle cx="{WX + 26 + i*20}" cy="{WY + BAR//2}" r="6" fill="{colour}"/>')

TABS = ["\u2733 atlas", "\u2733 beacon", "\u2733 ember", "~/src/website"]
TAB_X0, TAB_X1 = WX + 92, WX + WW - 40
TAB_W = (TAB_X1 - TAB_X0) / len(TABS)
IN_FRONT = {0: cycle("opacity", "1;1;0;0;1;1", "0;0.53;0.55;0.86;0.88;1"),
            1: cycle("opacity", "0;0;1;1;0;0", "0;0.53;0.55;0.86;0.88;1")}
BEHIND = {0: IN_FRONT[1], 1: IN_FRONT[0]}


def tab_label(x, title, colour, weight):
    A(f'<text x="{x + TAB_W/2:.1f}" y="{WY+27}" fill="{colour}" font-size="13" '
      f'font-weight="{weight}" text-anchor="middle" font-family="{SANS}">{title}</text>')


for i, title in enumerate(TABS):
    x = TAB_X0 + i * TAB_W
    if i:
        A(f'  <line x1="{x:.1f}" y1="{WY+12}" x2="{x:.1f}" y2="{WY+BAR-12}" stroke="{TAB_EDGE}"/>')
    if i in IN_FRONT:
        # In front: the terminal's own colour from the top edge down through the
        # rule, so the tab and the terminal read as one surface.
        A(f'  <g opacity="{1 if i == 0 else 0}">{IN_FRONT[i]}'
          f'<rect x="{x:.1f}" y="{WY}" width="{TAB_W:.1f}" height="{BAR+1}" fill="{TERM_BG}"/>')
        tab_label(x, title, "#e5e5ea", 500)
        A('</g>')
        A(f'  <g opacity="{0 if i == 0 else 1}">{BEHIND[i]}')
        tab_label(x, title, "#8e8e93", 400)
        A('</g>')
    else:
        tab_label(x, title, "#8e8e93", 400)
    text(round(x + TAB_W - 30), WY + 27, f"\u2318{i+1}", fill="#636366", size=11.5)
text(TAB_X1 + 14, WY + 28, "+", fill="#8e8e93", size=18)

# A tab whose session has something new wears iTerm2's activity dot until it
# is in front.
A(f'  <g opacity="0">{cycle("opacity", "0;0;1;1;0;0", "0;0.22;0.26;0.53;0.55;1")}'
  f'<circle cx="{TAB_X0 + TAB_W + 22:.1f}" cy="{WY + BAR//2}" r="3.5" fill="{BLOCKED_BORDER}"/></g>')

# ---------------------------------------------------------------- terminal
# Claude Code's own shape: a tool call is a dot and its name, its result hangs
# under a corner; the input sits between two rules, the session named in the
# upper one, and the permission mode under it.
TERM_W = WW - PANEL_W
SPIN = "#d97757"
LH = 25


def term(x, y, spans, size=14.5):
    """One terminal line from (text, colour[, weight]) spans laid end to end."""
    parts = []
    for span in spans:
        body, colour = span[0], span[1]
        weight = span[2] if len(span) > 2 else 400
        parts.append(f'<tspan fill="{colour}" font-weight="{weight}">{esc(body)}</tspan>')
    A(f'  <text x="{x}" y="{y}" font-size="{size}" font-family="{MONO}" '
      f'xml:space="preserve">{"".join(parts)}</text>')


def rule(y, label=None):
    x1, x2 = WX + 24, WX + TERM_W - 24
    if label:
        width = len(label) * 8.7 + 16
        A(f'  <line x1="{x1}" y1="{y}" x2="{x2 - width - 12}" y2="{y}" stroke="{TERM_DIM}" opacity="0.5"/>')
        term(x2 - width, y + 5, [(label, TERM_DIM)])
        A(f'  <line x1="{x2 - 8}" y1="{y}" x2="{x2}" y2="{y}" stroke="{TERM_DIM}" opacity="0.5"/>')
    else:
        A(f'  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{TERM_DIM}" opacity="0.5"/>')


def input_box(top, name, mode):
    rule(top, name)
    term(tx, top + 25, [("\u276f ", TERM_DIM)])
    rule(top + 40)
    term(tx, top + 64, [("  \u23f5\u23f5 ", TERM_DIM), (mode, TERM_DIM)], size=13)


tx, ty = WX + 36, WY + BAR + 40
DOT = "\u23fa "
HANG = "  \u23bf  "

# First: the session in front is atlas, at work.
A(f'  <g>{cycle("opacity", "1;1;0;0;1;1", "0;0.53;0.55;0.86;0.88;1")}')
term(tx, ty, [("\u276f ", TERM_DIM), ("Make the token parser stream instead of buffering", TERM_FG)])
term(tx, ty + LH*2, [(DOT, TERM_FG), ("Read", TERM_FG, 700), ("(src/parser.ts)", TERM_FG)])
term(tx, ty + LH*3, [(HANG, TERM_DIM), ("Read 214 lines", TERM_DIM)])
term(tx, ty + LH*5, [(DOT, LIT), ("Update", TERM_FG, 700), ("(src/lexer.ts)", TERM_FG)])
term(tx, ty + LH*6, [(HANG, TERM_DIM), ("Updated src/lexer.ts with 18 additions and 6 removals", TERM_DIM)])
term(tx, ty + LH*8, [(DOT, LIT), ("Bash", TERM_FG, 700), ("(npm test)", TERM_FG)])
term(tx, ty + LH*9, [(HANG, TERM_DIM), ("42 passed (1.8s)", TERM_DIM)])
term(tx, ty + LH*11, [("\u273b ", SPIN), ("Writing tests\u2026 ", SPIN), ("(2m \u00b7 \u2193 4.1k tokens)", TERM_DIM)])
input_box(ty + LH*12 + 4, "atlas", "accept edits on (shift+tab to cycle)")
A('  </g>')

# Second: beacon is clicked in the panel, and its question is what shows.
A(f'  <g opacity="0">{cycle("opacity", "0;0;1;1;0;0", "0;0.53;0.55;0.86;0.88;1")}')
A(f'  <rect x="{WX}" y="{WY+BAR}" width="{TERM_W}" height="{WH-BAR}" fill="{TERM_BG}"/>')
term(tx, ty, [("\u276f ", TERM_DIM), ("Put a cache in front of the pricing lookup", TERM_FG)])
term(tx, ty + LH*2, [(DOT, TERM_FG), ("It needs a store, and two fit this codebase.", TERM_FG)])
rule(ty + LH*3 + 2)
A(f'  <rect x="{tx}" y="{ty + LH*4 - 16}" width="86" height="22" rx="3" fill="{SPIN}" opacity="0.9"/>')
term(tx + 8, ty + LH*4, [("\u2610 Store", "#1c1c1e", 700)])
term(tx, ty + LH*5 + 8, [("Which store should the cache use?", TERM_FG, 700)])
term(tx, ty + LH*6 + 16, [("\u276f ", SPIN), ("1. Postgres", SPIN)])
term(tx, ty + LH*7 + 16, [("     Alongside the primary database", TERM_DIM)])
term(tx, ty + LH*8 + 16, [("  2. SQLite", TERM_FG)])
term(tx, ty + LH*9 + 16, [("     A file next to the service", TERM_DIM)])
term(tx, ty + LH*10 + 16, [("  3. Type something.", TERM_FG)])
term(tx, ty + LH*12 + 8, [("Enter to select \u00b7 \u2191/\u2193 to navigate \u00b7 Esc to cancel", TERM_DIM)], size=13)
A('  </g>')

# ------------------------------------------------------------------ panel
def head(baseline, name):
    text(PX + 24, baseline, name, fill=DIM, size=11, weight=700, extra=' letter-spacing="1.3"')


def card(top, height):
    A(f'  <rect x="{CARD_X}" y="{top}" width="{CARD_W}" height="{height}" rx="10" fill="{CARD}" '
      f'stroke="{CARD_BORDER}"/>')


def swatch(top, hue, hollow=False):
    if hollow:
        A(f'  <rect x="{CARD_X+18}" y="{top}" width="11" height="11" rx="3" fill="none" '
          f'stroke="{DIM}" stroke-width="1.6"/>')
    else:
        A(f'  <rect x="{CARD_X+18}" y="{top}" width="11" height="11" rx="3" fill="{hue}"/>')


def working_dots(top, hue):
    """What a session at work wears where a resting one wears its square."""
    for i in range(3):
        A(f'  <circle cx="{CARD_X+19+i*5}" cy="{top+6}" r="2" fill="{hue}">'
          f'<animate attributeName="opacity" values="0.25;1;0.25" dur="1.4s" '
          f'begin="{i*0.18:.2f}s" repeatCount="indefinite"/></circle>')


def badge(top, word, filled=False, animation=""):
    w = 70 if len(word) > 4 else 52
    x = CARD_X + CARD_W - 16 - w
    fill = BLOCKED_BORDER if filled else "none"
    ink = BADGE_INK if filled else DIM
    A(f'  <g>{animation}<rect x="{x}" y="{top}" width="{w}" height="21" rx="4" fill="{fill}" '
      f'stroke="{"none" if filled else DIM}"/>'
      f'<text x="{x + w/2}" y="{top+15}" fill="{ink}" font-size="10" font-weight="700" '
      f'letter-spacing="1" text-anchor="middle" font-family="{SANS}">{word}</text></g>')


TEXT_X = CARD_X + 44

y = WY + BAR + 30
head(y, "AGENTS")

# A session at work, its own report under its name, and a teammate below it.
c1 = y + 20
card(c1, 114)
working_dots(c1 + 20, "#e8833a")
text(TEXT_X, c1 + 31, "atlas", fill=FG, size=15, weight=600)
text(TEXT_X, c1 + 52, "Refactor the token parser", fill=DIM, size=12.5)
text(TEXT_X, c1 + 72, "Writing tests", fill=LIT_INK, size=12.5)
x = middot(TEXT_X + width_of("Writing tests", 12.5), c1 + 72)
mark("clock", x, c1 + 62, 12, DIM)
text(x + 16, c1 + 72, "2m", fill=DIM, size=12.5)
A(f'  <g mask="url(#tick)">'
  f'<rect x="{TEXT_X}" y="{c1+80}" width="330" height="5" fill="{FG}" opacity="0.16"/>'
  f'<rect x="{TEXT_X}" y="{c1+80}" width="150" height="5" fill="{LIT}">'
  f'{cycle("width", "150;150;270;270", "0;0.60;0.78;1")}</rect></g>')
chips(TEXT_X, c1 + 102, [("branch", "main", None), ("claude", "Fable 5.1", None)])

t1 = c1 + 114
A(f'  <path d="M{CARD_X+36} {t1} v13 h11" fill="none" stroke="{RULE}" stroke-width="1.5"/>')
for i in range(3):
    A(f'  <circle cx="{CARD_X+60}" cy="{t1+9+i*7}" r="2.5" fill="{LIT}">'
      f'<animate attributeName="opacity" values="0.25;1;0.25" dur="1.4s" begin="{i*0.18:.2f}s" '
      f'repeatCount="indefinite"/></circle>')
text(CARD_X + 78, t1 + 22, "reviewer", fill=DIM, size=13)

# The session that needs you: beat one turns the whole card amber.
c2 = t1 + 42
card(c2, 80)
A(f'  <g opacity="0">{cycle("opacity", "0;0;1;1;0;0", "0;0.22;0.28;0.66;0.74;1")}'
  f'<rect x="{CARD_X}" y="{c2}" width="{CARD_W}" height="80" rx="10" fill="{BLOCKED_BG}" '
  f'stroke="{BLOCKED_BORDER}" stroke-width="3"/></g>')
working_dots(c2 + 20, "#2a9d8f")
text(TEXT_X, c2 + 31, "beacon", fill=FG, size=15, weight=600)
text(TEXT_X, c2 + 52, "Pick the cache store", fill=DIM, size=12.5)
chips(TEXT_X, c2 + 69, [("branch", "feat/cache", None), ("claude", "Fable 5.1", None)])
badge(c2 + 14, "WAITING", filled=True,
      animation=cycle("opacity", "0;0;1;1;0;0", "0;0.22;0.28;0.66;0.74;1"))

# One finished, and one whose tree is eating the machine.
c3 = c2 + 94
card(c3, 80)
swatch(c3 + 20, "#8e8e93")
text(TEXT_X, c3 + 31, "ember", fill=FG, size=15, weight=600)
text(TEXT_X, c3 + 52, "Done", fill=LIT_INK, size=12.5, weight=600)
x = chips(TEXT_X, c3 + 69, [("branch", "main", None), ("openai", "gpt-6-astra", None)])
A(f'  <g opacity="0">{cycle("opacity", "0;0;1;1", "0;0.32;0.40;1")}')
x = middot(x, c3 + 69)
mark("cpu", x, c3 + 58, 13, ALERT)
text(x + 17, c3 + 69, "CPU", fill=ALERT, size=12.5)
A('  </g>')
badge(c3 + 14, "IDLE")

# The plain terminals, under their own heading.
s1 = c3 + 88
head(s1 + 26, "SESSIONS")
card(s1 + 36, 50)
swatch(s1 + 55, None, hollow=True)
text(TEXT_X, s1 + 57, "~/src/website", fill=FG, size=13)
text(TEXT_X, s1 + 75, "vite dev", fill=DIM, size=11.5, family=MONO)

# The foot: what the day cost, and how many sessions are open.
rule_y = WY + WH - 34
A(f'  <line x1="{PX+14}" y1="{rule_y}" x2="{PX+PANEL_W-14}" y2="{rule_y}" stroke="{RULE}"/>')
text(PX + 24, rule_y + 22, "$4.82  ·  5 sessions", fill=DIM, size=12, family=MONO)
print(f"sessions card bottom {s1 + 86}, foot rule {rule_y}", file=sys.stderr)

# The pointer arrives on the waiting card and clicks it: the terminal follows.
A(f'  <g opacity="0">{cycle("opacity", "0;0;1;1;0;0", "0;0.38;0.44;0.72;0.78;1")}')
A(f'  <circle cx="{CARD_X+286}" cy="{c2+48}" r="4" fill="{BLOCKED_BORDER}" opacity="0">'
  f'{cycle("r", "4;4;4;40;40", "0;0.52;0.55;0.62;1")}'
  f'{cycle("opacity", "0;0;0.4;0;0", "0;0.52;0.55;0.62;1")}</circle>')
A(f'  <path d="M0,0 L0,19 L4.6,14.6 L7.6,21.2 L10.6,19.9 L7.7,13.4 L13.7,13Z" '
  f'transform="translate({CARD_X+286},{c2+48})" fill="{POINTER_FILL}" stroke="{POINTER_EDGE}" '
  f'stroke-width="1.6" stroke-linejoin="round"/>')
A('  </g>')

A('  </g>')
A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "banner.svg").write_text("\n".join(out) + "\n")
