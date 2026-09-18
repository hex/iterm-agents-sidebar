# ABOUTME: Guards how page.html classes its SVG icons.
# ABOUTME: An SVG element's className is read-only, so assigning it throws and the panel paints no rows.
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_no_icon_is_classed_by_assigning_className():
    source = PAGE.read_text(encoding="utf-8")
    assigned = re.findall(r"Object\.assign\(\s*metaIcon\([^)]*\)\s*,\s*\{[^}]*className", source)
    assert assigned == []
