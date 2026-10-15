# ABOUTME: Draws assets/card-states.svg for the README: the five looks a card can
# ABOUTME: wear, one card each, captioned. Session names are invented.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 448
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
    text(x, top, activity, fill=DIM, size=12.5)
    nx = middot(x + width_of(activity, 12.5), top)
    mark("clock", nx, top - 10, 12, DIM)
    text(nx + 16, top, age, fill=DIM, size=12.5)
    A(f'  <g mask="url(#tick)">'
      f'<rect x="{x}" y="{top+8}" width="{CARD_W - 60}" height="5" fill="{FG}" opacity="0.16"/>'
      f'<rect x="{x}" y="{top+8}" width="{done}" height="5" fill="{LIT}"/></g>')


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="Five cards: one amber with a Waiting badge, its question and a button per answer, one at work with a report and ticks, '
  f'one grey with an Idle outline, one grey with a green Done badge, and one at work for 25 minutes with a warm Long outline">')
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
A(f'  <rect x="{x}" y="{c}" width="{CARD_W}" height="114" rx="10" fill="{BLOCKED_BG}" '
  f'stroke="{BLOCKED_BORDER}" stroke-width="3"/>')
working_dots(x + 18, c + 20, "#2a9d8f")
text(tx, c + 31, "beacon", fill=FG, size=15, weight=600)
tag(tx + NAME_W["beacon"] + 9, c + 31, "claude")
text(tx, c + 52, "Redis or SQLite for the cache?", fill=BLOCKED_TEXT, size=12.5)
# A button per answer; the model line and the report hide while it asks.
for i, answer in enumerate(("Redis", "SQLite")):
    y = c + 61 + i * 23
    A(f'  <rect x="{tx}" y="{y}" width="{CARD_W - (tx - x) - 16}" height="19" rx="6" '
      f'fill="{BLOCKED_TEXT}" fill-opacity=".14"/>')
    text(tx + 9, y + 13.5, str(i + 1), fill=BLOCKED_TEXT, size=11.5, weight=500)
    text(tx + 22, y + 13.5, answer, fill=FG, size=11.5, weight=500)
badge(x + CARD_W - 16, c + 15.5, "Waiting", ink=BADGE_INK, fill=BLOCKED_BORDER)

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
mark("checked", tx, c + 52 - 10, 11, LIT)
text(tx + 15, c + 52, "Complete", fill=SEV_OK, size=12.5, weight=600)
facts(tx, c + 69, "main", "gpt-6-astra")
badge(x + CARD_W - 16, c + 15.5, "Idle")

# Finished while you looked elsewhere: the idle card, its badge filled green
# with Done until you look at that session.
x = COLS[1]
caption(x, c - 14, "FINISHED WHILE YOU LOOKED ELSEWHERE")
tx = x + 44
card(x, CARD_W, c, 80)
swatch(x + 18, c + 20, "#6d9eeb")
text(tx, c + 31, "cinder", fill=DIM, size=15, weight=500)
tag(tx + NAME_W["cinder"] + 9, c + 31, "claude")
mark("checked", tx, c + 52 - 10, 11, LIT)
text(tx + 15, c + 52, "Complete", fill=SEV_OK, size=12.5, weight=600)
facts(tx, c + 69, "feat/cache", "Fable 5.1")
badge(x + CARD_W - 16, c + 15.5, "Done", ink=ACCENT_INK, fill=SEV_OK)

# Working 20 minutes or more: the same card at work, with a warm outline in
# the corner saying how long, in case it has stalled.
x, c = COLS[0], c + 116
caption(x, c - 14, "WORKING 20 MINUTES OR MORE")
tx = x + 44
card(x, CARD_W, c, 114)
working_dots(x + 18, c + 20, "#c4508f")
text(tx, c + 31, "harbor", fill=FG, size=15, weight=600)
tag(tx + NAME_W["harbor"] + 9, c + 31, "claude")
text(tx, c + 52, "Migrate the auth tables", fill=DIM, size=12.5)
report(tx, c + 72, "Running the suite", "25m", 270)
facts(tx, c + 102, "feat/auth", "Fable 5.1")
badge(x + CARD_W - 16, c + 15.5, "Long 25m", ink=WARN)

A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "card-states.svg").write_text("\n".join(out) + "\n")
