# ABOUTME: Draws assets/card-anatomy.svg for the README: one card carrying everything a
# ABOUTME: card can, each part joined by a leader to what it means. Names are invented.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 462
CX, CW, CT = 24, 404, 22
TX = CX + 44
LX = CX + CW + 40   # where the leaders' words start
EFFORT_HIGH = "#929efa"


def meta(x, baseline, items, ink=DIM):
    """A child row's facts line, in the panel's 10px mono face, middots between.
    An item is (mark, words, colour), the mark None for words alone."""
    for i, (name, words, colour) in enumerate(items):
        if i:
            text(x + 4, baseline, "·", fill=DIM, size=10, family=MONO, extra=' opacity="0.6"')
            x += 4 + 6 + 4
        if name:
            mark(name, x, baseline - 8.5, 9, colour or ink)
            x += 12
        text(x, baseline, words, fill=colour or ink, size=10, family=MONO)
        x += width_of(words, 10, MONO)
    return x


def trunk(x, top, mids):
    """The line the children hang from: down from x through the last child's
    middle, with an elbow into each. Rows sit flush, so the panel's per-row
    elbows join into one line, and this draws that line."""
    A(f'  <path d="M{x} {top} v{mids[-1] - top}" fill="none" stroke="{RULE}" stroke-width="1"/>')
    for mid in mids:
        A(f'  <path d="M{x} {mid} h8" fill="none" stroke="{RULE}" stroke-width="1"/>')


def stacked_dots(x, mid, hue):
    for i in range(3):
        A(f'  <circle cx="{x+4}" cy="{mid-4+i*4}" r="1.5" fill="{hue}" opacity="{(0.35, 1, 0.35)[i]}"/>')


NOTES = Notes(LX)
note = NOTES.add


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="One card, each of its parts joined by a line to what it means: the name and the agent, '
  f'the task and what it is doing now, the ticks, the branch, model, context and CPU, then a teammate, '
  f'running and finished subagents, a Codex job, the open tasks and the background shells">')
A('  <title>What a card carries</title>')
A(f'''  <defs>
    <pattern id="tickmask" width="9" height="5" patternUnits="userSpaceOnUse">
      <rect width="5" height="5" fill="#ffffff"/>
    </pattern>
    <mask id="tick"><rect width="{W}" height="{H}" fill="url(#tickmask)"/></mask>
  </defs>''')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')

# The card and its own lines.
card(CX, CW, CT, H - 2 * CT)
working_dots(CX + 18, CT + 20, "#e8833a")
text(TX, CT + 31, "atlas", fill=FG, size=15, weight=600)
tag(TX + NAME_W["atlas"] + 9, CT + 31, "claude")
note(TX + NAME_W["atlas"] + 9 + 74, CT + 26, "The session's name, and which agent runs in it")

text(TX, CT + 52, "Refactor the token parser", fill=DIM, size=12.5)
note(TX + width_of("Refactor the token parser", 12.5) + 14, CT + 48, "The task it reports, in its own words")

text(TX, CT + 72, "Reading code", fill=LIT_INK, size=12.5)
x = middot(TX + width_of("Reading code", 12.5), CT + 72)
mark("clock", x, CT + 62, 12, DIM)
text(x + 16, CT + 72, "40s", fill=DIM, size=12.5)
note(x + 16 + width_of("40s", 12.5) + 14, CT + 68, "What it is doing now, and how old that report is")
A(f'  <g mask="url(#tick)">'
  f'<rect x="{TX}" y="{CT+80}" width="{CW - 60}" height="5" fill="{FG}" opacity="0.16"/>'
  f'<rect x="{TX}" y="{CT+80}" width="140" height="5" fill="{LIT}"/></g>')
note(TX + CW - 60 + 14, CT + 83, "Its own estimate of how far it has got")

fy = CT + 102
x = chips(TX, fy, [("branch", "main", None), ("model", "Fable 5.1", None)])
text(x + 5, fy, "[", fill=DIM, size=12.5, family=MONO)
text(x + 12, fy, "h", fill=EFFORT_HIGH, size=12.5, weight=600, family=MONO)
text(x + 20, fy, "]", fill=DIM, size=12.5, family=MONO)
x = middot(x + 27, fy)
mark("gauge", x, fy - 11, 13, ALERT)
text(x + 17, fy, "82%", fill=ALERT, size=12.5)
x = middot(x + 17 + width_of("82%", 12.5), fy)
mark("cpu", x, fy - 11, 13, ALERT)
text(x + 17, fy, "CPU", fill=ALERT, size=12.5)
x = middot(x + 17 + width_of("CPU", 12.5), fy)
for i in range(3):
    A(f'  <circle cx="{x+2+i*5}" cy="{fy-4}" r="2" fill="{DIM}" opacity="0.75"/>')
text(x + 18, fy, "1", fill=DIM, size=12.5)
note(x + 18 + width_of("1", 12.5) + 14, fy - 4, "Branch, model and effort, then context and CPU once they matter")

# A teammate, with the elbow the panel draws.
ry = fy + 12
kids_top, mids = ry, [ry + 13]
stacked_dots(CX + 48, ry + 13, LIT)
text(CX + 66, ry + 17, "reviewer", fill=DIM, size=13, weight=500)
note(CX + 66 + width_of("reviewer", 13) + 16, ry + 13, "A teammate, running in a pane of its own")

# Subagents: one running, one it started, one finished.
ry += 30
mids.append(ry + 13)
stacked_dots(CX + 48, ry + 13, LIT)
text(CX + 66, ry + 17, "explorer", fill=DIM, size=13, weight=500)
meta(CX + 66, ry + 31, [("claude", "Opus 5", None), (None, "3m", None)])
text(CX + 66, ry + 45, "Reading code", fill=LIT_INK, size=11)
note(CX + 66 + width_of("explorer", 13) + 16, ry + 13, "A running subagent: its model, how long, and what for")

ry += 50
trunk(CX + 54, ry - 4, [ry + 13])
stacked_dots(CX + 66, ry + 13, LIT)
text(CX + 84, ry + 17, "tests", fill=DIM, size=13, weight=500)
meta(CX + 84, ry + 31, [("claude", "Opus 5", None), (None, "40s", None)])
note(CX + 84 + width_of("tests", 13) + 16, ry + 13, "One a subagent started, a step in")

ry += 36
mids.append(ry + 13)
mark("check", CX + 48, ry + 8, 10, LIT)
A('  <g opacity="0.5">')
text(CX + 66, ry + 17, "indexer", fill=DIM, size=13, weight=500)
meta(CX + 66, ry + 31, [("claude", "Opus 5", None), (None, "12m", None)])
A('  </g>')
note(CX + 66 + width_of("indexer", 13) + 16, ry + 13, "A finished one, kept until your next prompt")

# A Codex job started through the codex plugin.
ry += 36
mids.append(ry + 13)
trunk(CX + 36, kids_top, mids)
stacked_dots(CX + 48, ry + 13, LIT)
text(CX + 66, ry + 17, "Codex review", fill=DIM, size=13, weight=500)
meta(CX + 66, ry + 31, [("openai", "reviewing", None), (None, "5m", None)])
note(CX + 66 + width_of("Codex review", 13) + 16, ry + 13, "A Codex job the session started, with its phase")

# The session's open tasks, folded into one line.
ty = ry + 44
A(f'  <line x1="{CX+10}" y1="{ty}" x2="{CX+CW-10}" y2="{ty}" stroke="{CARD_BORDER}" '
  f'stroke-dasharray="1 2"/>')
mark("tasks", CX + 12, ty + 8, 10, DIM)
text(CX + 28, ty + 17, "4", fill=FG, size=11, weight=500)
text(CX + 28 + width_of("4 ", 11), ty + 17, "tasks · 1 in progress", fill=DIM, size=11)
text(CX + CW - 18, ty + 18, "›", fill=DIM, size=13)
note(CX + 28 + width_of("4 tasks · 1 in progress", 11) + 16, ty + 13, "Its open tasks, folded; a click lists them")

# Background shells, folded into one line and opened.
sy = ty + 26
A(f'  <line x1="{CX+10}" y1="{sy}" x2="{CX+CW-10}" y2="{sy}" stroke="{CARD_BORDER}" '
  f'stroke-dasharray="1 2"/>')
mark("shells", CX + 12, sy + 8, 10, DIM)
text(CX + 28, sy + 17, "2 commands running", fill=DIM, size=11)
text(CX + CW - 18, sy + 18, "›", fill=DIM, size=13, extra=f' transform="rotate(90 {CX + CW - 15} {sy + 13})"')
note(CX + 28 + width_of("2 commands running", 11) + 16, sy + 13, "Background shells, folded; a click opens them")
trunk(CX + 17, sy + 22, [sy + 26 + i * 22 + 11 for i in range(2)])
for i, cmd in enumerate(("npm run dev", "pytest -x tests/")):
    y = sy + 26 + i * 22
    mark("shells", CX + 29, y + 5, 11, DIM)
    text(CX + 45, y + 14, cmd, fill=FG, size=10, family=MONO, extra=' opacity="0.72"')
note(CX + 45 + width_of("pytest -x tests/", 10, MONO) + 16, sy + 26 + 22 + 11, "A command; a click shows the whole of it, with Copy")

NOTES.draw()
A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "card-anatomy.svg").write_text("\n".join(out) + "\n")
