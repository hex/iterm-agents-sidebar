"""The README's drawings are what their scripts draw.

Each script reads its marks and colours out of page.html, so a committed SVG
that its script no longer reproduces is one that has drifted from the panel.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def drawn(script, out):
    # BANNER_H in the caller's shell would draw the tall cut, not the README's.
    env = {k: v for k, v in os.environ.items() if k != "BANNER_H"}
    subprocess.run([sys.executable, str(ASSETS / script), str(out)], check=True,
                   capture_output=True, env=env)
    return out.read_text()


FIGURES = ["banner", "card-states", "card-anatomy", "foot", "settings", "menu"]


@pytest.mark.parametrize("name", FIGURES)
def test_a_figure_is_what_its_script_draws(tmp_path, name):
    assert drawn(f"make-{name}.py", tmp_path / "x.svg") == (ASSETS / f"{name}.svg").read_text()


def test_the_settings_figure_lists_every_setting_the_sheet_has():
    """The sheet's rows are read out of page.html at draw time, so a row
    added to the page is missing from the figure only until it is redrawn,
    and this says so."""
    sys.path.insert(0, str(ASSETS))
    from panel_draw import setting_rows
    svg = (ASSETS / "settings.svg").read_text()
    labels = [row["label"] for row in setting_rows() if "label" in row]
    assert len(labels) == 25
    for label in labels:
        assert f">{label}<" in svg, label


def test_the_menu_figure_lists_every_item_the_menu_has():
    svg = (ASSETS / "menu.svg").read_text()
    for label in ("/compact", "/rotate", "/clear", "Close"):
        assert f">{label}<" in svg, label
