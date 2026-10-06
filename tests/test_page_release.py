"""The foot's bar offers a newer release as one Update button.

Asked 2026-09-28: at panel width "2026.9.47 · 2026.9.48 available" filled the
bar and pushed the button out of sight. The bar keeps the running version and
the button; the offered version moves into the button's tooltip.
"""
import re
from pathlib import Path

from page_source import function

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_the_offered_version_is_the_buttons_tooltip_not_words_on_the_bar():
    body = function(PAGE.read_text(encoding="utf-8"), "paintVersion")
    assert "available`)" not in body
    title = re.search(r"take\.title = `([^`]*)`", body).group(1)
    assert title.startswith("${LATEST.update} available")


def test_the_button_says_which_release_to_a_screen_reader():
    body = function(PAGE.read_text(encoding="utf-8"), "paintVersion")
    assert re.search(r'take\.setAttribute\("aria-label", `Update to \$\{LATEST\.update\}`\)', body)
