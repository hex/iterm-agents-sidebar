"""A finished task's Done wears the same mark as the active account.

Ways it could go wrong: Done keeps the bare tick while the account shows the
filled circle, so the panel has two marks for "this is settled"; the account
badge carries its own copy of the path and the two drift apart.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"

# Phosphor's CheckCircle, fill weight: the active account's mark.
CHECKED = ("M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm45.66,85.66-56,56"
           "a8,8,0,0,1-11.32,0l-24-24a8,8,0,0,1,11.32-11.32L112,148.69l50.34-50.35"
           "a8,8,0,0,1,11.32,11.32Z")


def test_the_checked_mark_is_drawn_from_one_place():
    page = PAGE.read_text(encoding="utf-8")
    assert page.count(CHECKED) == 1
    assert re.search(r"^  checked: '<path d=\"" + re.escape(CHECKED) + "\"/>',$", page, re.M)


def test_done_and_the_active_account_both_wear_it():
    page = PAGE.read_text(encoding="utf-8")
    assert 'done.append(metaIcon("checked"), document.createTextNode("Done"));' in page
    assert 'const check = metaIcon("checked");' in page
