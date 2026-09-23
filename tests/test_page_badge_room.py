"""A card's name stops short of the badge in its corner.

The label clips with overflow: hidden, whose edge is the padding box, so
room reserved with padding-right is room the text still draws into: a long
name ran under the IDLE badge. The room is taken off max-width instead.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_no_label_reserves_badge_room_with_padding():
    css = PAGE.read_text(encoding="utf-8")
    rules = re.findall(r"([^{}]*\.label[^{}]*)\{([^}]*)\}", css)
    padded = [selector.strip() for selector, body in rules if "padding-right" in body]
    assert padded == []


def test_the_label_is_narrowed_by_the_room_each_badge_needs():
    css = PAGE.read_text(encoding="utf-8")
    assert re.search(r"\.label \{\s*max-width: calc\(100% - var\(--badge-room, 0px\)\)", css)
    for state in ("hot", "resting", "long-turn", "cornered"):
        assert re.search(rf"button\.row\.{state} \{{ --badge-room:", css), state
