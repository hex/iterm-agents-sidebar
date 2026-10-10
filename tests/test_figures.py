"""The README's drawings are what their scripts draw.

Each script reads its marks and colours out of page.html, so a committed SVG
that its script no longer reproduces is one that has drifted from the panel.
"""
import html
import os
import re
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
    assert len(labels) == 28
    for label in labels:
        assert f">{label}<" in svg, label


def test_the_menu_figure_lists_every_item_the_menu_has():
    svg = (ASSETS / "menu.svg").read_text()
    for label in ("Details", "/compact", "/rotate", "/clear", "Close"):
        assert f">{label}<" in svg, label


def test_the_card_states_figure_shows_an_unseen_finish_in_the_panels_green():
    """DONE on a fill of the dark theme's --sev-ok, as the panel paints it."""
    css = (ASSETS.parent / "page.html").read_text()
    dark = css[css.index("@media (prefers-color-scheme: dark)"):]
    green = dark[dark.index("--sev-ok:"):].split(";")[0].split(":")[1].strip()
    svg = (ASSETS / "card-states.svg").read_text()
    assert re.search(rf'<rect [^>]*fill="{green}"[^>]*/><text [^>]*>DONE</text>', svg)


@pytest.mark.parametrize("name", FIGURES)
def test_the_readme_describes_a_figure_as_the_figure_describes_itself(name):
    """A reader without the picture gets the README's alt text, a screen
    reader on the SVG its aria-label: both say the same thing."""
    readme = (ASSETS.parent / "README.md").read_text()
    alt = re.search(rf'assets/{name}\.svg" width="100%" alt="([^"]*)"', readme).group(1)
    label = re.search(r'aria-label="([^"]*)"', (ASSETS / f"{name}.svg").read_text()).group(1)
    assert alt == html.unescape(label)
