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


def test_a_card_that_turns_blocked_is_still_brought_into_view():
    body = re.search(r"\nfunction announce\(snapshot\) \{\n(.*?)\n\}\n",
                     PAGE.read_text(encoding="utf-8"), re.S).group(1)
    assert 'if (state === "blocked" && lastStates.get(id) !== "blocked") revealAfterPaint(id);' in body
