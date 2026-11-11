# ABOUTME: Draws assets/settings.svg for the README: the settings drawer, every row read out
# ABOUTME: of page.html's SETTING_ROWS and every default out of sidebar.py, as the panel shows it.
import pathlib, sys
from panel_draw import *  # noqa: F401,F403
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from sidebar import DEFAULT_SETTINGS  # noqa: E402
from update import repository_page  # noqa: E402

W = 880
GUT, COL_W = 24, (W - 3 * 24) // 2
COLS = (GUT, GUT + COL_W + GUT)
SHEET = "#242426"          # color-mix(--fg 4%, --bg)
GUIDE = "#3e3e41"          # color-mix(--fg 14%, transparent) over the card
TITLE_H, PLAIN_H, CHILD_H = 33, 31, 27
# A row's note: 11px type in lines 15px apart, under the row's name and across the card.
NOTE_SIZE, NOTE_LINE = 11, 15


def note_lines(row):
    """The row's note, broken into lines that fit the card, or none."""
    lines = []
    for word in row.get("note", "").split():
        if lines and width_of(lines[-1] + " " + word, NOTE_SIZE) <= COL_W - 20:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def row_height(row):
    """The row's name and control, and under them its note if it has one."""
    notes = note_lines(row)
    return (CHILD_H if row.get("needs") else PLAIN_H) + (len(notes) * NOTE_LINE + 4 if notes else 0)


def switch(right, mid, on):
    """The 28x17 pill, green when on."""
    x, y = right - 28, mid - 8.5
    bg = LIT if on else FG
    A(f'  <rect x="{x}" y="{y}" width="28" height="17" rx="8.5" fill="{bg}" opacity="{1 if on else 0.18}"/>')
    kx = x + 13 if on else x + 2
    A(f'  <circle cx="{kx + 6.5}" cy="{mid}" r="6.5" fill="#ffffff"/>')


def ticks(right, mid, p, words):
    """The slider: the task bar's ticks, lit up to p, and its read-out."""
    vx = right - 26
    text(right, mid + 3.5, words, fill=DIM, size=10, weight=600, family=MONO, extra=' text-anchor="end"')
    x = vx - 8 - 108
    A(f'  <g mask="url(#tick)">'
      f'<rect x="{x}" y="{mid-2}" width="108" height="4" fill="{FG}" opacity="0.16"/>'
      f'<rect x="{x}" y="{mid-2}" width="{108*p:.1f}" height="4" fill="{LIT}"/></g>')


def pick(right, mid, words):
    w = width_of(words, 11) * 1.02 + 30
    x = right - w
    A(f'  <rect x="{x}" y="{mid-12}" width="{w:.1f}" height="24" rx="7" fill="{FG}" opacity="0.05"/>')
    A(f'  <rect x="{x}" y="{mid-12}" width="{w:.1f}" height="24" rx="7" fill="none" stroke="{FG}" opacity="0.16" stroke-width="0.5"/>')
    text(x + 8, mid + 4, words, fill=FG, size=11, weight=500)
    A(f'  <path d="M{right-14} {mid-3} l3 3 l3 -3 M{right-14} {mid+1} l3 -3 l3 3" fill="none" '
      f'stroke="{DIM}" stroke-width="1.2" transform="translate(0,-0.5)"/>')


def step(right, mid, words):
    w = 24 + 34 + 24
    x = right - w
    A(f'  <rect x="{x}" y="{mid-12}" width="{w}" height="24" rx="7" fill="{FG}" opacity="0.05"/>')
    A(f'  <rect x="{x}" y="{mid-12}" width="{w}" height="24" rx="7" fill="none" stroke="{FG}" opacity="0.16" stroke-width="0.5"/>')
    for lx in (x + 24, x + 58):
        A(f'  <line x1="{lx}" y1="{mid-12}" x2="{lx}" y2="{mid+12}" stroke="{FG}" opacity="0.12" stroke-width="0.5"/>')
    text(x + 12, mid + 4.5, "−", fill=FG, size=13, weight=500, extra=' text-anchor="middle"')
    text(x + 41, mid + 3.5, words, fill=FG, size=11, weight=600, family=MONO, extra=' text-anchor="middle"')
    text(x + 70, mid + 4.5, "+", fill=FG, size=13, weight=500, extra=' text-anchor="middle"')


def reading(row):
    """The value the control shows for the default, as the sheet words it."""
    v = DEFAULT_SETTINGS[row["k"]]
    if "range" in row:
        lo, hi, _ = row["range"]
        words = f"{round(v * (100 if hi <= 1 else 1))}%" if row.get("pct") else f"{v:g}{row.get('unit', '')}"
        return (v - lo) / (hi - lo), words
    if "steps" in row:
        # As the drawer writes it: two decimals, one trailing zero dropped.
        return None, f"{v:.2f}"[:-1] + "×"
    if "choices" in row:
        return None, dict(row["choices"])[v]
    return None, bool(v)


def control(row, right, mid, kind):
    if "action" in row:
        return
    p, words = reading(row)
    if "range" in row:
        ticks(right, mid, p, words)
    elif "steps" in row:
        step(right, mid, words)
    elif "choices" in row:
        pick(right, mid, words)
    else:
        switch(right, mid, words)


def card_height(kids):
    return TITLE_H + sum(row_height(r) for r in kids) + (8 if kids and kids[-1].get("needs") else 0)


def sheet_card(x, y, head, master, kids):
    """One topic as a card: the title with its switch, then its rows."""
    h = card_height(kids)
    A(f'  <rect x="{x}" y="{y}" width="{COL_W}" height="{h}" rx="8" fill="{CARD}" stroke="{CARD_BORDER}"/>')
    text(x + 10, y + 21, master["label"] if master else head["head"], fill=FG, size=12.5, weight=600)
    right = x + COL_W - 10
    if head.get("fold"):
        A(f'  <path d="M{right-8} {y+14} l4 4 l4 -4" fill="none" stroke="{FG}" stroke-width="1.2"/>')
    if master:
        switch(right, y + 16.5, bool(DEFAULT_SETTINGS[master["k"]]))
    ry = y + TITLE_H
    for i, row in enumerate(kids):
        child = bool(row.get("needs"))
        rh = row_height(row)
        line_h = CHILD_H if child else PLAIN_H
        if not child:
            A(f'  <line x1="{x}" y1="{ry}" x2="{x+COL_W}" y2="{ry}" stroke="{FG}" opacity="0.14" stroke-dasharray="1 2"/>')
        mid = ry + line_h / 2
        if child:
            # The guide: down from the title, an elbow into each option.
            last = i + 1 == len(kids) or not kids[i + 1].get("needs")
            A(f'  <line x1="{x+12}" y1="{ry}" x2="{x+12}" y2="{mid if last else ry + rh}" stroke="{GUIDE}"/>')
            A(f'  <line x1="{x+12}" y1="{mid}" x2="{x+18}" y2="{mid}" stroke="{GUIDE}"/>')
        # An option whose governing switch is off is greyed: the sheet hides it,
        # and the figure shows every setting.
        dimmed = child and not DEFAULT_SETTINGS[row["needs"]]
        if dimmed:
            A('  <g opacity="0.4">')
        text(x + (22 if child else 10), mid + 4, row["label"], fill=FG, size=12)
        control(row, right, mid, "child" if child else "plain")
        for k, words in enumerate(note_lines(row)):
            text(x + (22 if child else 10), ry + line_h - 4 + NOTE_SIZE + k * NOTE_LINE, words, fill=DIM, size=NOTE_SIZE)
        if dimmed:
            A('  </g>')
        ry += rh
    return h


# The drawer's last card: where the install comes from, two rows that each
# open a page on GitHub, an arrow where a control would sit. The figure shows
# the public mirror, which an install with no origin of its own leads to.
REPOSITORY_ROWS = [repository_page(None).removeprefix("https://"), "Release notes"]
REPOSITORY_H = TITLE_H + PLAIN_H * len(REPOSITORY_ROWS)


def repository_card(x, y):
    A(f'  <rect x="{x}" y="{y}" width="{COL_W}" height="{REPOSITORY_H}" rx="8" fill="{CARD}" stroke="{CARD_BORDER}"/>')
    text(x + 10, y + 21, "Repository", fill=FG, size=12.5, weight=600)
    ry = y + TITLE_H
    for label in REPOSITORY_ROWS:
        A(f'  <line x1="{x}" y1="{ry}" x2="{x+COL_W}" y2="{ry}" stroke="{FG}" opacity="0.14" stroke-dasharray="1 2"/>')
        mid = ry + PLAIN_H / 2
        text(x + 10, mid + 4, label, fill=FG, size=12)
        # The page's 256-unit arrow, drawn 12 px wide at the row's right end.
        A(f'  <path transform="translate({x + COL_W - 22} {mid - 6}) scale(0.046875)" fill="{DIM}" '
          f'd="M200,64V168a8,8,0,0,1-16,0V83.31L69.66,197.66a8,8,0,0,1-11.32-11.32L172.69,72H88a8,8,0,0,1,0-16H192A8,8,0,0,1,200,64Z"/>')
        ry += PLAIN_H
    return REPOSITORY_H


# The API fallback's card, above Repository: its switch, then the key table, a
# header and a row per stored account, here one account with no key yet, so its
# field spans Key, Spent and Cap and its Save is the floppy disk.
ACCOUNTS_NOTE = ("While every account is full, puts apiKeyHelper in ~/.claude/settings.json. "
                 "If that file syncs to other machines, they get the line too. "
                 "Needs an API key on an account first.")
ACCOUNTS_ROW = {"label": "When every account is full, use API credits", "note": ACCOUNTS_NOTE}
ACCOUNT_NAMES = ["Account 1"]
# The table's columns as page.html's colgroup sizes them, the name's taking the rest.
KEY_COLS = {"lamp": 22, "key": 40, "spent": 56, "cap": 44, "act": 28}
KEY_HEAD_H, KEY_ROW_H = 21, 30
ACCOUNTS_H = TITLE_H + row_height(ACCOUNTS_ROW) + KEY_HEAD_H + KEY_ROW_H * len(ACCOUNT_NAMES)


def rule(x, y):
    A(f'  <line x1="{x}" y1="{y}" x2="{x+COL_W}" y2="{y}" stroke="{FG}" opacity="0.14" stroke-dasharray="1 2"/>')


def accounts_card(x, y):
    A(f'  <rect x="{x}" y="{y}" width="{COL_W}" height="{ACCOUNTS_H}" rx="8" fill="{CARD}" stroke="{CARD_BORDER}"/>')
    text(x + 10, y + 21, "Accounts", fill=FG, size=12.5, weight=600)
    right = x + COL_W - 10
    ry = y + TITLE_H
    rule(x, ry)
    text(x + 10, ry + PLAIN_H / 2 + 4, ACCOUNTS_ROW["label"], fill=FG, size=12)
    # With no key on any account the switch is disabled, and the page draws it at .4.
    A('  <g opacity="0.4">')
    switch(right, ry + PLAIN_H / 2, DEFAULT_SETTINGS["api_fallback"])
    A('  </g>')
    for k, words in enumerate(note_lines(ACCOUNTS_ROW)):
        text(x + 10, ry + PLAIN_H - 4 + NOTE_SIZE + k * NOTE_LINE, words, fill=DIM, size=NOTE_SIZE)
    ry += row_height(ACCOUNTS_ROW)
    rule(x, ry)
    name_x = x + KEY_COLS["lamp"] + 3
    figures_x = x + COL_W - KEY_COLS["act"] - KEY_COLS["cap"] - KEY_COLS["spent"] - KEY_COLS["key"]
    text(name_x, ry + 15, "Account", fill=DIM, size=9.5, weight=500)
    edge = figures_x
    for word, col in (("Key", "key"), ("Spent", "spent"), ("Cap", "cap")):
        edge += KEY_COLS[col]
        text(edge - 2, ry + 15, word, fill=DIM, size=9.5, weight=500, extra=' text-anchor="end"')
    ry += KEY_HEAD_H
    for name in ACCOUNT_NAMES:
        A(f'  <line x1="{x}" y1="{ry}" x2="{x+COL_W}" y2="{ry}" stroke="{FG}" opacity="0.10" stroke-dasharray="1 2"/>')
        mid = ry + KEY_ROW_H / 2
        text(name_x, mid + 4, name, fill=FG, size=12)
        width = KEY_COLS["key"] + KEY_COLS["spent"] + KEY_COLS["cap"] - 4
        A(f'  <rect x="{figures_x + 2}" y="{mid-11}" width="{width}" height="22" rx="5" fill="{FG}" opacity="0.06"/>')
        A(f'  <rect x="{figures_x + 2}" y="{mid-11}" width="{width}" height="22" rx="5" fill="none" stroke="{FG}" opacity="0.22" stroke-width="0.5"/>')
        text(figures_x + 8, mid + 3.5, "sk-ant-\u2026", fill=DIM, size=11, family=MONO)
        mark("save", x + COL_W - 4 - 24 + 5, mid - 7, 14, DIM)
        ry += KEY_ROW_H
    return ACCOUNTS_H


# Group the rows as settingsBody does: a head opens a card, a master row sits
# in its title, and rows follow until the next head.
cards = []
rows = setting_rows()
i = 0
while i < len(rows):
    row = rows[i]; i += 1
    if "head" in row:
        master = rows[i] if i < len(rows) and rows[i].get("master") else None
        if master:
            i += 1
        cards.append([row, master, []])
    else:
        cards[-1][2].append(row)

# The tallest card on the right; every other card and Repository on the left.
tallest = max(cards, key=lambda card: card_height(card[2]))
left, right = [card for card in cards if card is not tallest], [tallest]
H = 24 + 20 + max(sum(card_height(kids) + 9 for _, _, kids in col)
                  + (ACCOUNTS_H + 9 + REPOSITORY_H + 9 if col is left else 0)
                  for col in (left, right)) + 30

A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" role="img" '
  f'aria-label="The settings drawer: Alerts, When a session waits for you, When one finishes, Look, On a card, Rows, Experimental, Accounts and Repository. '
  f'Every setting with its default, On a card expanded, and the button to show the foot\'s offers again">')
A('  <title>Settings</title>')
A(f'''  <defs>
    <pattern id="tickmask" width="6" height="4" patternUnits="userSpaceOnUse">
      <rect width="3" height="4" fill="#ffffff"/>
    </pattern>
    <mask id="tick"><rect width="{W}" height="{H}" fill="url(#tickmask)"/></mask>
  </defs>''')
A(f'  <rect width="{W}" height="{H}" rx="16" fill="{SHEET}"/>')
text(GUT + 2, 30, "Settings", fill=FG, size=11.5, weight=600)
for col, x in ((left, COLS[0]), (right, COLS[1])):
    y = 44
    for title, master, kids in col:
        y += sheet_card(x, y, title, master, kids) + 9
    if col is left:
        y += accounts_card(x, y) + 9
        repository_card(x, y)
A('</svg>')
pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
             pathlib.Path(__file__).resolve().parent / "settings.svg").write_text("\n".join(out) + "\n")
