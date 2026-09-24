"""A note beside a card row's label stays inside the label's cell.

Ways it could go wrong: a long note (a program's name, or a flag standing in
for one) runs under the bar and the figure beside it; cut short, it can no
longer be read whole.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_a_long_note_is_cut_with_an_ellipsis_inside_its_cell():
    rule = re.search(r"#card \.grid \.note \{([^}]*)\}", PAGE.read_text(encoding="utf-8")).group(1)
    for part in ("min-width: 0", "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
        assert part in rule, part


def test_a_cut_note_can_still_be_read_whole():
    page = PAGE.read_text(encoding="utf-8")
    assert "note.textContent = note.title = value.note;" in page
