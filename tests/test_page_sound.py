"""The page reports the moments a sound marks; the daemon decides and plays.

Ways it could go wrong: the page still plays through WebAudio, which WebKit
keeps silent until a click after every reload; the page drops a moment
because its copy of the settings has not arrived yet; a Stop hook that flips
a finished session back to working for a moment makes it sound finished twice.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def announce_body():
    page = PAGE.read_text(encoding="utf-8")
    return re.search(r"\nfunction announce\(snapshot\) \{\n(.*?)\n\}\n", page, re.S).group(1)


def test_the_page_makes_no_sound_of_its_own():
    page = PAGE.read_text(encoding="utf-8")
    assert "AudioContext" not in page
    assert "createOscillator" not in page


def test_every_blocked_moment_goes_to_the_daemon_whatever_the_page_settings():
    body = announce_body()
    assert 'if (state === "blocked") act(id, "sound", "blocked");' in body
    assert not re.search(r'act\(id, "sound"[^;]*\);[^\n]*SETTINGS', body)
    assert "sound_blocked" not in body and "sound_done" not in body


def test_a_finished_turn_sounds_once_however_often_it_flips_back():
    body = announce_body()
    assert ('else if (state === "idle" && before === "working" && '
            '(turn === undefined || turn !== soundedTurns.get(id))) {\n'
            '        act(id, "sound", "done");\n'
            '        if (turn !== undefined) soundedTurns.set(id, turn);') in body
