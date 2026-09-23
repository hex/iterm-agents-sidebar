"""Every ink the page puts on a ground reads at WCAG AA in both themes.

The tokens are parsed out of page.html's `:root` blocks so the numbers
here are the ones the panel paints with, not a copy that can drift.
"""
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parent.parent / "page.html"
AA = 4.5

#: (ink, ground) pairs the page relies on, by token name.
PAIRS = [
    ("--dim", "--card"),
    ("--dim", "--bg"),
    ("--fg", "--card"),
    ("--blocked-text", "--blocked-bg"),
    # A waiting card's "+1 more" after its question.
    ("--dim", "--blocked-bg"),
    ("--badge-ink", "--blocked-border"),
    ("--accent-ink", "--switch-bg"),
    ("--accent-ink", "--hot"),
    ("--accent-ink", "--alert"),
    # The report's live words are green; the ticks beside them are a graphic
    # and need no ratio, but the words do.
    ("--lit-ink", "--card"),
    # The refused-switch line, on the strip's ground.
    ("--warn", "--bg"),
]


def tokens(theme):
    """The custom properties of one theme, {name: hex}."""
    css = PAGE.read_text(encoding="utf-8")
    light, dark = re.findall(r":root\s*\{(.*?)\}", css, re.S)[:2]
    block = light if theme == "light" else dict_merge(light, dark)
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b", block))


def dict_merge(light, dark):
    return light + "\n" + dark


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(ink, ground):
    a, b = luminance(ink), luminance(ground)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def test_a_known_pair_measures_as_wcag_says():
    # Black on white is 21:1 by definition; a published mid-grey pair is 4.54.
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0
    assert round(contrast("#767676", "#ffffff"), 2) == 4.54


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("ink,ground", PAIRS)
def test_ink_reads_on_its_ground(theme, ink, ground):
    palette = tokens(theme)
    assert ink in palette and ground in palette, f"{theme} lacks {ink} or {ground}"
    ratio = contrast(palette[ink], palette[ground])
    assert ratio >= AA, f"{theme}: {ink} {palette[ink]} on {ground} {palette[ground]} = {ratio:.2f}"
