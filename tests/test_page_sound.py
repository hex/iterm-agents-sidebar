"""The page asks for no alerts; the daemon decides them (tests/test_alerts.py).

Ways it could go wrong: the page still plays through WebAudio, which WebKit
keeps silent until a click after every reload; the page still asks the daemon
for a sound, a banner or a focus move, so a page that fell behind announces
its backlog again; a card that turns blocked below the fold stays out of view.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_the_page_makes_no_sound_of_its_own():
    page = PAGE.read_text(encoding="utf-8")
    assert "AudioContext" not in page
    assert "createOscillator" not in page


def test_the_page_asks_the_daemon_for_no_alert():
    page = PAGE.read_text(encoding="utf-8")
    asked = re.findall(r'act\([^,]+,\s*"(\w+)"', page)
    assert asked, "found no act() calls to check"
    assert not {"sound", "notify", "bring", "return"} & set(asked)


def test_a_card_that_turns_blocked_or_asks_anew_is_brought_into_view():
    """Asked 2026-09-29: a card that had waited five minutes sat half off the
    bottom; its second prompt had come while the first was open, so it never
    turned blocked again. Each new prompt reveals the card, not only the turn."""
    page = PAGE.read_text(encoding="utf-8")
    body = re.search(r"\nfunction announce\(snapshot\) \{\n(.*?)\n\}\n", page, re.S).group(1)
    assert "waitKey(r)" in body
    assert 'if (key.startsWith("blocked") && lastStates.get(id) !== key) revealAfterPaint(id);' in body
    key = re.search(r"\nfunction waitKey\(row\) \{\n(.*?)\n\}\n", page, re.S).group(1)
    assert "JSON.stringify(row.question" in key


def test_a_queue_row_click_brings_its_card_into_view():
    body = re.search(r"\nfunction paintQueue\(snapshot\) \{\n(.*?)\n\}\n",
                     PAGE.read_text(encoding="utf-8"), re.S).group(1)
    assert 'b.addEventListener("click", () => { revealAfterPaint(row.session_id); act(row.session_id, "focus"); });' in body
