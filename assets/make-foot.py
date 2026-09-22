# ABOUTME: Draws assets/foot.svg for the README: the panel's foot, with who is waiting, the
# ABOUTME: account meters, auto-switch, a second account and Codex's limits. Figures invented.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403

W, H = 880, 484
PX, PW = 24, 430
IX, IW = PX + 20, PW - 40      # the content's edges inside the panel
LX = PX + PW + 40
BLOCKED_TEXT, WARN = "#ffd60a", "#de935f"
SEV_OK, SEV_WARN, SEV_CRIT = "#87af87", "#d7af5f", "#d75f5f"
ACCENT = "#3478f6"


def hairline(y, dotted=False):
    dash = ' stroke-dasharray="1 2"' if dotted else ""
    A(f'  <line x1="{IX}" y1="{y}" x2="{IX+IW}" y2="{y}" stroke="{FG}" opacity="0.14"{dash}/>')


NOTES = Notes(LX)
note = NOTES.add


def mono(x, baseline, s, fill=DIM, size=10, weight=400, anchor=None):
    extra = f' text-anchor="{anchor}"' if anchor else ""
    text(x, baseline, s, fill=fill, size=size, weight=weight, family=MONO, extra=extra)


def meter(y, label, used, at, tick=None, ahead=False, faded=False):
    """One window: label, track and fill, the figure, the time to its reset."""
    band = SEV_CRIT if used >= 90 else SEV_WARN if used >= 70 else SEV_OK
    tx = IX + 44
    tw = IW - 44 - 34 - 40
    A(f'  <g opacity="{0.75 if faded else 1}">')
    mono(IX, y + 4, label)
    A(f'  <rect x="{tx}" y="{y-1.5}" width="{tw}" height="3" rx="1.5" fill="{FG}" opacity="0.12"/>')
    A(f'  <rect x="{tx}" y="{y-1.5}" width="{tw*used/100:.1f}" height="3" rx="1.5" fill="{band}"/>')
    if tick is not None:
        A(f'  <rect x="{tx + tw*tick/100 - 0.5:.1f}" y="{y-3.5}" width="1" height="6" fill="{FG}" opacity="0.45"/>')
    ink, weight = (SEV_CRIT, 600) if used >= 90 else (WARN, 600) if ahead else (DIM, 400)
    mono(IX + IW - 40, y + 4, f"{used}%", fill=ink, weight=weight, anchor="end")
    mono(IX + IW, y + 4, at, anchor="end")
    A('  </g>')


def switch(x, y, on, w=20, h=12):
    A(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{LIT if on else FG}" '
      f'opacity="{1 if on else 0.18}"/>')
    kx = x + w - h + 1.5 if on else x + 1.5
    A(f'  <circle cx="{kx + (h-3)/2}" cy="{y + h/2}" r="{(h-3)/2}" fill="#ffffff"/>')


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="The panel\'s foot: two sessions waiting, the Auto-switch control, the active account\'s '
  f'5-hour, weekly and Fable meters, the last switch, a second account with its Switch button, '
  f'Codex\'s own limits, and the bar with the release, reload and the gear">')
A('  <title>The foot of the panel</title>')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{BG}"/>')
A(f'  <rect x="{PX}" y="0" width="{PW}" height="{H}" fill="{BG}"/>')

# Who is waiting, oldest first.
y = 22
hairline(y)
text(IX, y + 18, "Waiting on you", fill=FG, size=11.5, weight=600)
text(IX + 90, y + 18, "2", fill=BLOCKED_TEXT, size=11.5, weight=500)
for i, (name, hue, ago) in enumerate((("beacon", "#2a9d8f", "4m"), ("delta", "#c4508f", "12s"))):
    ry = y + 30 + i * 24
    A(f'  <rect x="{IX+2}" y="{ry+4}" width="9" height="9" rx="2.5" fill="{hue}"/>')
    text(IX + 19, ry + 13, name, fill=FG, size=12, weight=500)
    mono(IX + IW, ry + 13, ago, anchor="end")
note(IX + IW + 12, y + 43, "Who is waiting, oldest first; a click brings one forward")

# The budget: auto-switch, then the account the sessions run on.
y += 84
hairline(y)
text(IX + IW - 28, y + 17, "Auto-switch", fill=DIM, size=10.5, extra=' text-anchor="end"')
switch(IX + IW - 20, y + 8, True)
# The chip that stands while a switch is near, in the alert colour; the
# reason is its tooltip, so the figure names only the target.
A(f'  <rect x="{IX}" y="{y + 5}" width="82" height="15" rx="5" fill="{ALERT}" fill-opacity="0.12"/>')
text(IX + 6, y + 16, "→ spare soon", fill=ALERT, size=10, weight=600)
note(IX + IW + 12, y + 14, "Auto-switch: leave an account before a limit stops it")
note(IX + IW + 12, y + 30, "While a switch is near: where it would go; hover for why")

ay = y + 48
mark("claude", IX, ay + 1, 12, CLAUDE_MARK)
text(IX + 18, ay + 11, "work", fill=FG, size=10, weight=600, family=MONO, extra=' opacity="0.85"')
mark("check", IX + 50, ay + 1, 12, LIT)
note(IX + IW + 12, ay + 7, "The account your sessions run on")
meter(ay + 28, "5-hour", 42, "2h")
meter(ay + 43, "Weekly", 71, "3d", tick=60)
meter(ay + 58, "Fable", 91, "3d", tick=60, ahead=True)
note(IX + IW + 12, ay + 28, "Its 5-hour limit, then each weekly one, with the time to reset")
note(IX + IW + 12, ay + 58, "Amber from 70%, red from 90%; the tick is an even pace")

sy = ay + 78
mark("switch", IX, sy + 1, 12, FG)
text(IX + 18, sy + 11, "Switched to work", fill=FG, size=11)
text(IX + 18 + 99, sy + 11, "·", fill=DIM, size=11)
text(IX + 18 + 107, sy + 11, "Fable at 91%", fill=DIM, size=11)
cx = IX + IW - 56
A(f'  <rect x="{cx - 34}" y="{sy}" width="30" height="13" rx="4" fill="none" stroke="{DIM}" stroke-width="0.5"/>')
A(f'  <text x="{cx - 19}" y="{sy+10}" fill="{DIM}" font-size="9" letter-spacing="0.4" '
  f'text-anchor="middle" font-family="{SANS}">AUTO</text>')
mark("clock", cx + 4, sy + 1, 11, DIM)
mono(IX + IW, sy + 11, "12m", anchor="end")
note(IX + IW + 12, sy + 7, "The last switch: where, why, and a chip when the panel chose")

# Another stored account, its Switch out because the pointer is on it.
oy = sy + 30
hairline(oy, dotted=True)
oy += 10
A('  <g opacity="0.75">')
mark("claude", IX, oy + 1, 12, CLAUDE_MARK)
text(IX + 18, oy + 11, "spare", fill=FG, size=10, weight=600, family=MONO)
A('  </g>')
bx, bw = IX + IW - 66, 66
A(f'  <rect x="{bx}" y="{oy-3}" width="{bw}" height="19" rx="5" fill="{ACCENT}" stroke="#1d4fa8" stroke-width="0.5"/>')
mark("switch", bx + 8, oy + 1, 11, "#ffffff")
text(bx + 23, oy + 11, "Switch", fill="#ffffff", size=11, weight=500)
note(IX + IW + 12, oy + 7, "Another account: point at it for Switch, then Confirm")
meter(oy + 30, "5-hour", 18, "1h", faded=True)
meter(oy + 45, "Weekly", 34, "5d", tick=60, faded=True)
meter(oy + 60, "Fable", 22, "5d", tick=60, faded=True)
by = oy + 74
A(f'  <rect x="{IX}" y="{by}" width="130" height="19" rx="4" fill="none" stroke="{FG}" opacity="0.22" stroke-width="0.5"/>')
mono(IX + 7, by + 13, "Add you@example.com", fill=FG)
note(IX + IW + 12, by + 9, "Store the login Claude Code is using now")

# Codex's own limits, under their own mark.
cy = by + 32
hairline(cy, dotted=True)
cy += 10
mark("openai", IX, cy + 1, 12, FG)
text(IX + 18, cy + 11, "Codex", fill=FG, size=10, weight=600, family=MONO, extra=' opacity="0.85"')
meter(cy + 28, "5-hour", 64, "1h")
meter(cy + 43, "Weekly", 38, "5d", tick=60)
note(IX + IW + 12, cy + 7, "Codex's limits, read from its session log")

# The bar.
by = cy + 62
hairline(by)
# The release line as the panel draws it the day after a release: the one it
# runs, the one it could, and the button that takes it.
mono(IX, by + 16, "2026.09.19")
mono(IX + 63, by + 16, "·", size=10, fill=DIM)
mono(IX + 70, by + 16, "2026.09.20 available")
A(f'  <rect x="{IX + 194}" y="{by + 5}" width="42" height="18" rx="5" fill="{ACCENT}"/>')
text(IX + 215, by + 17, "Update", fill="#ffffff", size=10, weight=500, extra=' text-anchor="middle"')
mark("reload", IX + IW - 46, by + 5, 14, DIM)
mark("gear", IX + IW - 18, by + 5, 14, DIM)
note(IX + IW + 12, by + 12, "The release running, and the one on the mirror until it is taken")

NOTES.draw()
A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "foot.svg").write_text("\n".join(out) + "\n")
