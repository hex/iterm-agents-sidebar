# ABOUTME: Draws assets/card-states.svg for the README: the five looks a card can
# ABOUTME: wear, one card each, captioned. Session names are invented.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 574
GUT, CARD_W = 24, (W - 3 * 24) // 2
COLS = (GUT, GUT + CARD_W + GUT)
TOP = 44
PAD = 16
WARN = "#de935f"  # --warn, dark theme
WORKING_INK, WORKING_TINT = LIT, mix(LIT, CARD, .14)
REST_INK, REST_TINT = DIM, mix(FG, CARD, .08)
WAITING_INK, WAITING_TINT = WARN, mix("#d7af5f", BLOCKED_BG, .2)  # --sev-warn at 20%
LONG_TINT = mix(WARN, CARD, .16)


def caption(x, baseline, words):
    text(x + 4, baseline, words, fill=DIM, size=11, weight=700, extra=' letter-spacing="1.3"')


def facts(x, baseline, branch, model):
    chips(x, baseline, [("branch", branch, None), ("model", model, None)])


def progress(x, top, done, words):
    """The task bar and, under it, the percent with what the session is doing."""
    bar(x, top, CARD_W - 2 * PAD, done)
    text(x, top + 18, words, fill=DIM, size=10)


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="Five cards, each with its folder on the first line: one amber with a Waiting for you pill, its question and a button per answer, '
  f'one at work with a Working pill, its task as the title, how long since it reported and a bar with the percent, '
  f'one grey with an Idle pill, one washed green with a Done badge and a full bar, and one at work for 25 minutes with a warm Long pill">')
A('  <title>What a card says</title>')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')

# Waiting on you: the whole card amber, the pill in the warning ink, the
# question as the title.
x, c = COLS[0], TOP
caption(x, c - 14, "WAITING ON YOU")
tx = x + PAD
A(f'  <rect x="{x}" y="{c}" width="{CARD_W}" height="178" rx="10" fill="{BLOCKED_BG}" '
  f'stroke="{BLOCKED_BORDER}" stroke-width="3"/>')
folder_line(tx, c + 25, "cache-layer")
pill(x + CARD_W - PAD, c + 13, "Waiting for you", WAITING_INK, WAITING_TINT)
text(tx, c + 52, "Choose a cache store", fill=BLOCKED_TEXT, size=17, weight=600, extra=' letter-spacing="-0.4"')
text(tx, c + 72, "Redis or SQLite for the cache?", fill=BLOCKED_TEXT, size=12.5)
text(tx, c + 90, "Updated 10 s ago", fill=DIM, size=10)
facts(tx, c + 108, "feat/cache", "Fable 5.1")
# A button per answer.
for i, answer in enumerate(("Redis", "SQLite")):
    y = c + 118 + i * 23
    A(f'  <rect x="{tx}" y="{y}" width="{CARD_W - 2 * PAD}" height="19" rx="6" '
      f'fill="{BLOCKED_TEXT}" fill-opacity=".14"/>')
    text(tx + 9, y + 13.5, str(i + 1), fill=BLOCKED_TEXT, size=11.5, weight=500)
    text(tx + 22, y + 13.5, answer, fill=FG, size=11.5, weight=500)

# Working: the folder, a green pill, the task as the title, how long since
# it reported, and the bar with its own estimate.
x = COLS[1]
caption(x, c - 14, "WORKING")
tx = x + PAD
card(x, CARD_W, c, 132)
folder_line(tx, c + 25, "token-parser")
pill(x + CARD_W - PAD, c + 13, "Working", WORKING_INK, WORKING_TINT)
text(tx, c + 52, "Refactor the token parser", fill=FG, size=17, weight=600, extra=' letter-spacing="-0.4"')
text(tx, c + 70, "Updated 2 m ago", fill=DIM, size=10)
facts(tx, c + 90, "main", "Fable 5.1")
progress(tx, c + 100, 140, "38% · Writing tests")

# Idle: a grey pill, the session's name as the title in the resting grey.
x, c = COLS[0], TOP + 178 + 36
caption(x, c - 14, "IDLE")
tx = x + PAD
card(x, CARD_W, c, 92)
folder_line(tx, c + 25, "ember")
pill(x + CARD_W - PAD, c + 13, "Idle", REST_INK, REST_TINT)
text(tx, c + 52, "ember", fill=DIM, size=17, weight=600, extra=' letter-spacing="-0.4"')
facts(tx, c + 72, "main", "gpt-6-astra")

# Finished while you looked elsewhere: the whole card washed in the panel's
# green, the name in the full ink, the badge filled with Done until you look
# at that session, and the bar full.
x = COLS[1]
caption(x, c - 14, "FINISHED WHILE YOU LOOKED ELSEWHERE")
tx = x + PAD
card(x, CARD_W, c, 126, fill=FINISHED_BG, stroke=FINISHED_BORDER)
text(tx, c + 52, "cinder", fill=FG, size=17, weight=600, extra=' letter-spacing="-0.4"')
folder_line(tx, c + 25, "cinder")
solid_badge(x + CARD_W - PAD, c + 13, "Done", ACCENT_INK, SEV_OK)
facts(tx, c + 72, "feat/cache", "Fable 5.1")
progress(tx, c + 84, CARD_W - 2 * PAD, "100% · Complete")

# Working 20 minutes or more: the same card at work, the pill warm and saying
# how long, in case it has stalled.
x, c = COLS[0], c + 126 + 36
caption(x, c - 14, "WORKING 20 MINUTES OR MORE")
tx = x + PAD
card(x, CARD_W, c, 132)
folder_line(tx, c + 25, "auth")
pill(x + CARD_W - PAD, c + 13, "Long 25m", WARN, LONG_TINT)
text(tx, c + 52, "Migrate the auth tables", fill=FG, size=17, weight=600, extra=' letter-spacing="-0.4"')
text(tx, c + 70, "Updated 2 m ago", fill=DIM, size=10)
facts(tx, c + 90, "feat/auth", "Fable 5.1")
progress(tx, c + 100, 230, "62% · Running the suite")

A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "card-states.svg").write_text("\n".join(out) + "\n")
