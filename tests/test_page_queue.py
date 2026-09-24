"""A row under "Waiting on you" says what its session asks, and nothing it does not know.

Ways it could go wrong, each checked below: a row whose session sent no
question claims a kind of wait anyway; a permission prompt wears the
question mark; the kind icon turns amber and the count stops being the
section's one warm mark; a question set shows nothing because only its
first question carries text; a screen reader hears the name but not what
is asked, or hears the header and text run together.
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def function(page, name):
    return re.search(rf"\nfunction {name}\(.*?\n\}}\n", page, re.S).group(0)


def test_a_row_that_sent_no_question_keeps_its_colour_and_claims_no_kind():
    body = function(PAGE.read_text(encoding="utf-8"), "paintQueue")
    asked, plain = body.split("if (row.question) {", 1)[1].split("} else {", 1)
    assert "queueKind(row.question)" in asked
    plain = plain.split("\n    }\n", 1)[0]
    assert 'className: "swatch"' in plain
    assert "queueKind" not in plain and "qkind" not in plain


def test_a_tool_waits_behind_the_shell_mark_and_a_question_behind_the_question_mark():
    body = function(PAGE.read_text(encoding="utf-8"), "queueKind")
    assert 'metaIcon(asked.tool ? "shells" : "question")' in body


def test_the_kind_icon_stays_grey_so_the_count_is_the_one_warm_mark():
    css = PAGE.read_text(encoding="utf-8")
    rule = re.search(r"\.qrow > \.qkind \{([^}]*)\}", css).group(1)
    assert "color: var(--dim)" in rule
    assert not re.search(r"\.qkind[^{]*\{[^}]*--blocked-text", css)


def test_a_set_is_described_by_its_first_question():
    page = PAGE.read_text(encoding="utf-8")
    for name in ("queueText", "asksAloud"):
        assert "const first = asked.set ? asked.set[0] : asked;" in function(page, name), name


def test_a_screen_reader_hears_what_is_asked_with_its_parts_apart():
    page = PAGE.read_text(encoding="utf-8")
    assert '[asked.tool, asked.summary] : [first.header, first.question])\n    .filter(Boolean).join(": ")' \
        in function(page, "asksAloud")
    assert 'row.question ? `${said}, ${asksAloud(row.question)}` : said' in function(page, "paintQueue")
