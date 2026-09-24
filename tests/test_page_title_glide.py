"""A card's name too long for its room goes round now and then; nothing else moves.

The glide runs only for a name that overflows, never for someone who asked
for reduced motion, and its lap starts from the clock so a row rebuilt every
snapshot does not restart it. The copy that follows the name round is hidden
from a screen reader, which would otherwise read the name twice.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def glide_body(page):
    return re.search(r"\nfunction glide\(run, width\) \{\n(.*?)\n\}\n", page, re.S).group(1)


def test_only_a_name_with_more_text_than_room_is_given_a_width_to_glide():
    page = PAGE.read_text(encoding="utf-8")
    assert "const clipped = width > label.clientWidth + 1;" in page
    assert "if (run) glide(run, clipped ? width : 0);" in page


def test_no_glide_without_a_width_or_when_motion_is_reduced():
    page = PAGE.read_text(encoding="utf-8")
    assert 'const MOTION = window.matchMedia("(prefers-reduced-motion: no-preference)");' in page
    body = glide_body(page)
    stop = body.index("if (!width || !MOTION.matches) return;")
    # Whatever an earlier glide left is gone before the check, so a name that
    # fits again, or a viewer who turned motion off, is left still.
    assert body.index("a.cancel()") < stop
    assert body.index('.copy")?.remove()') < stop
    assert body.index(".animate(") > stop


def test_the_lap_starts_where_the_clock_says_it_has_reached():
    assert "motion.currentTime = Date.now() % total;" in glide_body(PAGE.read_text(encoding="utf-8"))


def test_the_copy_following_the_name_is_hidden_from_a_screen_reader():
    assert 'copy.setAttribute("aria-hidden", "true");' in glide_body(PAGE.read_text(encoding="utf-8"))
