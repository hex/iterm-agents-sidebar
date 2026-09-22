# ABOUTME: Draws assets/card-states.svg for the README: the four states a card can be
# ABOUTME: in, one card each, captioned. Session names are invented.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 330
GUT, CARD_W = 24, (W - 3 * 24) // 2
COLS = (GUT, GUT + CARD_W + GUT)
TOP = 44
WARN = "#de935f"  # --warn, dark theme


def caption(x, baseline, words):
    text(x + 4, baseline, words, fill=DIM, size=11, weight=700, extra=' letter-spacing="1.3"')


def facts(x, baseline, branch, model):
    chips(x, baseline, [("branch", branch, None), ("model", model, None)])


def report(x, top, activity, age, done):
    """The live line of a report and the ticks under it."""
    text(x, top, activity, fill=LIT_INK, size=12.5)
    nx = middot(x + width_of(activity, 12.5), top)
    mark("clock", nx, top - 10, 12, DIM)
    text(nx + 16, top, age, fill=DIM, size=12.5)
    A(f'  <g mask="url(#tick)">'
      f'<rect x="{x}" y="{top+8}" width="{CARD_W - 60}" height="5" fill="{FG}" opacity="0.16"/>'
      f'<rect x="{x}" y="{top+8}" width="{done}" height="5" fill="{LIT}"/></g>')


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="Four cards: one amber with a WAITING badge, one at work with a report and ticks, '
  f'one grey with an IDLE outline, and one at work for 25 minutes with a warm long badge">')
A('  <title>What a card says</title>')
A(f'''  <defs>
    <pattern id="tickmask" width="9" height="5" patternUnits="userSpaceOnUse">
      <rect width="5" height="5" fill="#ffffff"/>
    </pattern>
    <mask id="tick"><rect width="{W}" height="{H}" fill="url(#tickmask)"/></mask>
  </defs>''')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')

# Waiting on you: the whole card amber, the badge filled.
x, c = COLS[0], TOP
caption(x, c - 14, "WAITING ON YOU")
tx = x + 44
A(f'  <rect x="{x}" y="{c}" width="{CARD_W}" height="80" rx="10" fill="{BLOCKED_BG}" '
  f'stroke="{BLOCKED_BORDER}" stroke-width="3"/>')
working_dots(x + 18, c + 20, "#2a9d8f")
text(tx, c + 31, "beacon", fill=FG, size=15, weight=600)
tag(tx + NAME_W["beacon"] + 9, c + 31, "claude")
text(tx, c + 52, "Pick the cache store", fill=DIM, size=12.5)
facts(tx, c + 69, "feat/cache", "Fable 5.1")
badge(x + CARD_W - 16, c + 14, "WAITING", filled=True)

# Working: a dark name, the dots, and its own report.
x = COLS[1]
caption(x, c - 14, "WORKING")
tx = x + 44
card(x, CARD_W, c, 114)
working_dots(x + 18, c + 20, "#e8833a")
text(tx, c + 31, "atlas", fill=FG, size=15, weight=600)
tag(tx + NAME_W["atlas"] + 9, c + 31, "claude")
text(tx, c + 52, "Refactor the token parser", fill=DIM, size=12.5)
report(tx, c + 72, "Writing tests", "2m", 150)
facts(tx, c + 102, "main", "Fable 5.1")

# Idle: a grey name, its square, and the outline badge.
x, c = COLS[0], TOP + 150
caption(x, c - 14, "IDLE")
tx = x + 44
card(x, CARD_W, c, 80)
swatch(x + 18, c + 20, "#8e8e93")
text(tx, c + 31, "ember", fill=DIM, size=15, weight=500)
tag(tx + NAME_W["ember"] + 9, c + 31, "openai")
mark("check", tx, c + 52 - 10, 11, LIT_INK)
text(tx + 15, c + 52, "Done", fill=LIT_INK, size=12.5, weight=600)
facts(tx, c + 69, "main", "gpt-6-astra")
badge(x + CARD_W - 16, c + 14, "IDLE")

# Working 20 minutes or more: the same card at work, with a warm outline in
# the corner saying how long, in case it has stalled.
x = COLS[1]
caption(x, c - 14, "WORKING 20 MINUTES OR MORE")
tx = x + 44
card(x, CARD_W, c, 114)
working_dots(x + 18, c + 20, "#c4508f")
text(tx, c + 31, "harbor", fill=FG, size=15, weight=600)
tag(tx + NAME_W["harbor"] + 9, c + 31, "claude")
text(tx, c + 52, "Migrate the auth tables", fill=DIM, size=12.5)
report(tx, c + 72, "Running the suite", "25m", 270)
facts(tx, c + 102, "feat/auth", "Fable 5.1")
bw, bx = 70, x + CARD_W - 16 - 70
A(f'  <rect x="{bx}" y="{c+14}" width="{bw}" height="21" rx="4" fill="none" stroke="{WARN}"/>')
A(f'  <text x="{bx + bw/2}" y="{c+29}" fill="{WARN}" font-size="10" font-weight="700" '
  f'letter-spacing="1" text-anchor="middle" font-family="{SANS}">LONG 25M</text>')

A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "card-states.svg").write_text("\n".join(out) + "\n")
