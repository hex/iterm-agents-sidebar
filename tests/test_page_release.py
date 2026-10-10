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


def test_the_version_opens_the_release_notes_only_when_the_checkout_is_on_github():
    body = function(PAGE.read_text(encoding="utf-8"), "paintVersion")
    branch = re.search(r"if \(LATEST\.repository\) \{(.*?)\n  \} else bar\.append\(label\);", body, re.S)
    assert branch, "the version is plain text unless the daemon sent a repository page"
    assert 'className: "notes", type: "button"' in branch.group(1)
    assert 'addEventListener("click", () => openGithub("releases"))' in branch.group(1)


def test_github_pages_are_opened_by_the_daemon_by_name_not_by_url():
    body = function(PAGE.read_text(encoding="utf-8"), "openGithub")
    assert re.search(r'fetch\(`/github\?token=\$\{encodeURIComponent\(TOKEN\)\}`, \{method: "POST", body: JSON\.stringify\(\{page\}\)\}\)', body)
    assert "LATEST" not in body


def test_settings_end_on_a_repository_card_built_with_the_rest():
    body = function(PAGE.read_text(encoding="utf-8"), "settingsBody")
    assert re.search(r"box\.append\(repositoryCard\(\)\);\n  syncSettings\(\);\n\}", body)


def test_the_repository_card_names_the_repository_and_opens_it_and_its_release_notes():
    page = PAGE.read_text(encoding="utf-8")
    card = function(page, "repositoryCard")
    assert 'settingCard("Repository")' in card
    assert 'githubRow("repository")' in card and 'githubRow("releases")' in card
    paint = function(page, "paintRepository")
    assert 'card.hidden = !LATEST.repository;' in paint
    assert r'LATEST.repository.replace(/^https:\/\//, "")' in paint
    assert '"Release notes"' in paint


def test_the_repository_card_is_kept_current_on_every_paint():
    assert "  paintRepository();\n" in function(PAGE.read_text(encoding="utf-8"), "paintAll")
