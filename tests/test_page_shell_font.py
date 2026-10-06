# ABOUTME: Guards the face a shell card's name wears: the settings choice the page offers and the terminal font the daemon passes it.
# ABOUTME: Source-shape assertions for the page, plain calls for the daemon's parsing.
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sidebar

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")


def test_the_settings_sheet_offers_every_face_the_daemon_accepts():
    row = re.search(r'\{k: "shell_font",.*?choices: \[(.*?)\]\},', PAGE, re.S).group(1)
    assert tuple(re.findall(r'\["(\w+)", "[^"]+"\]', row)) == sidebar.SETTING_CHOICES["shell_font"]


def test_the_terminal_font_is_the_profile_fonts_name_without_its_size():
    """iTerm2 stores a profile's font as its PostScript name and a size."""
    assert sidebar.terminal_font("PragmataProMono-Regular 16") == "PragmataProMono-Regular"
    assert sidebar.terminal_font("Menlo-Regular 12.5") == "Menlo-Regular"
    assert sidebar.terminal_font("SFMono-Regular") == "SFMono-Regular"


def test_a_font_name_that_could_break_out_of_the_stylesheet_is_dropped():
    """The name lands in a CSS value; anything past letters, digits, dot,
    underscore and hyphen is refused rather than escaped."""
    for junk in ('Evil"; } body { display: none 12', "Menlo\\22 12", "a(b) 12", "", "   ", None, 12):
        assert sidebar.terminal_font(junk) is None
