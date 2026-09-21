# ABOUTME: Guards how page.html says which agent runs in a card: a tag, a corner mark, group heads, or nothing extra.
# ABOUTME: Source-shape assertions; the tree has no JS runtime.
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sidebar

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")


def test_the_settings_sheet_offers_every_way_the_daemon_accepts():
    row = re.search(r'\{k: "provider_mark",.*?choices: \[(.*?)\]\},', PAGE, re.S).group(1)
    assert tuple(re.findall(r'\["(\w+)", "[^"]+"\]', row)) == sidebar.SETTING_CHOICES["provider_mark"]


def test_every_agent_the_daemon_orders_has_a_name_and_a_colour():
    listed = re.search(r"const AGENT_KINDS = \{(.*?)\n\};", PAGE, re.S).group(1)
    assert tuple(re.findall(r'^\s*(\w+): \{name: "[^"]+", colour: "#[0-9a-f]{6}"\}', listed, re.M)) == sidebar.PROVIDER_ORDER


def test_a_mark_is_named_after_its_own_agent():
    """The omp glyph was once labelled Claude: the label came from a two-way test."""
    assert 'row.provider === "openai" ? "OpenAI" : "Claude"' not in PAGE


def _over(colour, ground, share):
    mix = [round(int(colour[i:i + 2], 16) * share + int(ground[i:i + 2], 16) * (1 - share)) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(mix)


def test_a_tags_words_read_on_the_tint_they_sit_on_in_both_themes():
    """The tag is a pill tinted with the agent's colour. The brand orange and
    green are near 3:1 on a white card, so the words take a deeper ink of the
    same hue, one per theme, and the glyph keeps the colour itself."""
    from test_page_contrast import AA, contrast, tokens
    listed = re.search(r"const AGENT_KINDS = \{(.*?)\n\};", PAGE, re.S).group(1)
    colours = dict(re.findall(r'^\s*(\w+): \{name: "[^"]+", colour: "(#[0-9a-f]{6})"\}', listed, re.M))
    share = int(re.search(r"\n  \.ptag \{[^}]*color-mix\(in srgb, var\(--agent\) (\d+)%, transparent\)", PAGE).group(1)) / 100
    for theme in ("light", "dark"):
        found = tokens(theme)
        for kind, colour in colours.items():
            ground = _over(colour, found["--card"], share)
            assert contrast(found[f"--ink-{kind}"], ground) >= AA, (theme, kind)
    assert int(re.search(r"\n  \.ptag \{[^}]*font: \d+ (\d+)px", PAGE).group(1)) >= 10


def test_every_card_is_spoken_with_its_agents_name():
    """The glyphs are hidden from a screen reader; the row's one label names the agent."""
    assert '[row.label, group.name === "AGENTS" ? agentKind(row).name : null, row.position, said,' in PAGE


def test_the_choice_menu_is_as_wide_as_its_words():
    """A percentage width on it resolves against its own auto-sized grid
    track, which then shrinks to that share of the words and clips them."""
    pick = re.search(r"\n  \.pick \{(.*?)\}", PAGE, re.S).group(1)
    assert "max-width" not in pick and "%" not in pick.split("border:")[0]


def test_a_subagents_model_wears_the_mark_of_the_agent_it_runs_under():
    """An omp subagent's model is no Claude model; the mark is its card's."""
    chip = re.search(r"if \(sub\.model && SETTINGS\?\.show_model !== false\) \{(.*?)\n        \}", PAGE, re.S).group(1)
    assert 'providerIcon("claude"' not in chip
    assert "providerIcon(agentKindOf(row), agentKind(row).name)" in chip
