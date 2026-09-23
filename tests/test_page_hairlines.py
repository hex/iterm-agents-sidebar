"""A line drawn thinner than a device pixel stays whole on a 1x screen.

WebKit rounds a border under 1px up to one device pixel, but draws a
box-shadow's spread as given: on a 1x screen a .5px outline comes apart into
broken fragments (the IDLE badge lost its sides). So every sub-pixel shadow
spread goes through --hair, which is .5px where a pixel is small and 1px
where it is not.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_no_shadow_has_a_literal_length_under_a_pixel():
    css = PAGE.read_text(encoding="utf-8")
    shadows = re.findall(r"box-shadow:([^;]*);", css)
    literal = [s.strip() for s in shadows if re.search(r"(?<![\d.])\.\d+px", s)]
    assert literal == []


def test_a_hair_is_one_whole_pixel_on_a_1x_screen():
    css = PAGE.read_text(encoding="utf-8")
    assert re.search(r"--hair:\s*\.5px", css)
    block = re.search(r"@media \(max-resolution: 1\.5dppx\)\s*\{(.*?)\n  \}", css, re.S)
    assert block and re.search(r"--hair:\s*1px", block.group(1))
