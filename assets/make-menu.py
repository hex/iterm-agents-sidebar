# ABOUTME: Draws assets/menu.svg for the README: a card with its right-click menu open, the
# ABOUTME: items read out of page.html's HOUSEKEEPING and CLOSE. The session name is invented.
import pathlib, re, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 196
CX, CW, CT = 24, 404, 22
TX = CX + 44
LX = CX + CW + 40
MENU_BG, MENU_EDGE = "#232325", "#3c3c3f"


def menu_items():
    """The labels page.html offers, in its order, and which are destructive."""
    page = PAGE.read_text()
    block = re.search(r"^const HOUSEKEEPING = \[\n(.*?)^\];", page, re.S | re.M).group(1)
    items = [(m.group(1), "destructive: true" in m.group(0))
             for m in re.finditer(r'\{label: "([^"]+)".*?\}(?=,?\n)', block, re.S)]
    close = re.search(r'^const CLOSE = \{label: "([^"]+)"', page, re.M).group(1)
    return items, close


NOTES = Notes(LX)
note = NOTES.add


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="An idle card with its right-click menu open: /compact, /rotate, /clear, then Close">')
A('  <title>The row menu</title>')
A(f'''  <defs>
    <filter id="drop" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000000" flood-opacity="0.45"/>
    </filter>
  </defs>''')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')

card(CX, CW, CT, 80)
swatch(CX + 18, CT + 20, "#8e8e93")
text(TX, CT + 31, "ember", fill=DIM, size=15, weight=500)
tag(TX + NAME_W["ember"] + 9, CT + 31, "claude")
mark("check", TX, CT + 52 - 10, 11, LIT_INK)
text(TX + 15, CT + 52, "Done", fill=LIT_INK, size=12.5, weight=600)
chips(TX, CT + 69, [("branch", "main", None), ("model", "Fable 5.1", None), ("gauge", "82%", ALERT)])
badge(CX + CW - 16, CT + 14, "IDLE")
note(CX + CW + 8, CT + 26, "Right-click a row, or Shift+F10 on a selected one")

# The menu, unfolded from the pointer.
items, close = menu_items()
mx, my, mw = CX + 150, CT + 48, 116
rows = [(label, danger, False) for label, danger in items] + [(close, True, True)]
mh = 4 + 24 * len(rows) + 7 + 4
A(f'  <g filter="url(#drop)"><rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="10" fill="{MENU_BG}" '
  f'stroke="{MENU_EDGE}" stroke-width="0.5"/></g>')
y = my + 4
for label, danger, sep in rows:
    if sep:
        A(f'  <line x1="{mx+6}" y1="{y+1.5}" x2="{mx+mw-6}" y2="{y+1.5}" stroke="{FG}" opacity="0.13" stroke-width="0.5"/>')
        y += 7
    armed = label == "/clear"
    text(mx + 9, y + 16, label, fill=ALERT if armed else FG, size=12.5, weight=700 if armed else 500,
         extra=' letter-spacing="-0.25"')
    y += 24
A(f'  <path d="M0,0 L0,17 L4.1,13.1 L6.8,19 L9.5,17.8 L6.9,12 L12.3,11.6Z" '
  f'transform="translate({mx + 60},{my + 4 + 24 * 2 + 5})" fill="{POINTER_FILL}" stroke="{POINTER_EDGE}" '
  f'stroke-width="1.4" stroke-linejoin="round"/>')
note(mx + mw + 12, my + 16, "/compact for every agent; the rest only where the agent has them")
note(mx + mw + 12, my + 4 + 24 * 2 + 12, "/clear and Close ask for a second click; the first turns them red")
note(mx + mw + 12, my + 4 + 24 * 3 + 7 + 12, "Close shuts the pane, agent or not")

NOTES.draw()
A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "menu.svg").write_text("\n".join(out) + "\n")
