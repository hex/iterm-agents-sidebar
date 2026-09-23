"""The docs point at things that exist, and name what the code offers.

release.sh runs the suite, so these hold at every release. They check what a
script can check; whether a sentence is still true is the release audit's job
(docs/development.md, "Releases").

Ways the docs go wrong that a script can catch, and the test for each:
- a link to a file that was renamed or removed;
- a link to a heading that was renamed;
- a doc nothing links to, so no reader finds it;
- an action the panel can take that the developer docs don't list;
- an install flag the install docs don't mention;
- a setting in the Settings sheet no doc names.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)")


def links(doc):
    """(target path, anchor or None) for each relative link in one doc."""
    for target in LINK.findall(doc.read_text(encoding="utf-8")):
        if re.match(r"[a-z]+:", target):
            continue
        path, _, anchor = target.partition("#")
        yield (doc.parent / path).resolve() if path else doc, anchor or None


def slugs(doc):
    """GitHub's anchors for a doc's headings."""
    for heading in re.findall(r"^#+ (.+)$", doc.read_text(encoding="utf-8"), re.M):
        text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
        yield text.replace(" ", "-")


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: str(d.relative_to(ROOT)))
def test_every_link_reaches_a_file_and_a_heading(doc):
    for target, anchor in links(doc):
        assert target.exists(), f"{doc.name} links to missing {target.relative_to(ROOT)}"
        if anchor and target.suffix == ".md":
            assert anchor in set(slugs(target)), f"{doc.name} links to missing #{anchor} in {target.name}"


def test_every_doc_is_linked_from_another():
    reached = {target for doc in DOCS for target, _ in links(doc) if target != doc}
    unlinked = [str(d.relative_to(ROOT)) for d in DOCS[1:] if d.resolve() not in reached]
    assert unlinked == []


def test_the_developer_docs_name_every_action_the_panel_takes():
    sys.path.insert(0, str(ROOT))
    from sidebar import VERBS
    text = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    assert [verb for verb in VERBS if verb not in text] == []


def test_the_install_docs_name_every_install_flag():
    flags = re.findall(r"^\s+(--[a-z-]+)\)", (ROOT / "install.sh").read_text(), re.M)
    assert flags, "install.sh parses no flags this test can read"
    text = (ROOT / "docs" / "integrations.md").read_text(encoding="utf-8")
    assert [flag for flag in flags if flag not in text] == []


def test_every_setting_is_named_in_the_docs():
    sys.path.insert(0, str(ROOT / "assets"))
    from panel_draw import setting_rows
    text = "\n".join(d.read_text(encoding="utf-8") for d in DOCS)
    labels = [row["label"] for row in setting_rows() if "label" in row]
    assert [label for label in labels if label not in text] == []
