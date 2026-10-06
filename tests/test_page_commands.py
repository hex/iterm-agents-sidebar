# ABOUTME: Guards which slash commands page.html offers on an agent's row.
# ABOUTME: A command is typed into the pane as it stands, so a row is offered only what its agent has.
import re
from pathlib import Path

from page_source import function

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def offered():
    """{label: the providers it is offered to}, read from the HOUSEKEEPING list."""
    source = PAGE.read_text(encoding="utf-8")
    listed = re.search(r"const HOUSEKEEPING = \[(.*?)\n\];", source, re.S).group(1)
    return {label: re.findall(r'"([^"]+)"', agents)
            for label, agents in re.findall(r'label: "([^"]+)".*?agents: \[([^\]]*)\]', listed, re.S)}


def test_each_command_names_the_agents_that_have_it():
    """Codex has /compact. /rotate is a Claude Code skill, and Codex starts
    over with /new where Claude has /clear. omp has /compact and /clear
    (omp 18.2.5, src/slash-commands/builtin-lifecycle.ts)."""
    assert offered() == {"/compact": ["claude", "openai", "omp"], "/rotate": ["claude"],
                         "/clear": ["claude", "omp"]}


def test_a_command_goes_as_a_prompt_the_daemon_may_refuse():
    """Not raw keys: typed into a waiting prompt, "/compact" would be its answer."""
    source = PAGE.read_text(encoding="utf-8")
    assert re.search(r"const typed = cmd => row => (\w+)\(", source).group(1) == "prompt"
    assert 'verb: "prompt"' in function(source, "prompt")


def test_the_daemons_refusal_is_kept_with_its_reason_for_the_card():
    """The daemon answers a refused prompt 409 with the reason; any other
    answer, a 400 for an empty prompt included, leaves the card as it was."""
    body = function(PAGE.read_text(encoding="utf-8"), "prompt")
    assert ".then(r => r.status === 409 ? r.json() : null)" in body
    assert "refusedPrompts.set(sessionId, {text: `not sent: ${reply.error}`, until: Date.now() + REFUSAL_SHOWN_MS});" in body


def test_the_reason_shows_for_a_few_seconds_and_is_then_painted_away():
    page = PAGE.read_text(encoding="utf-8")
    assert "const REFUSAL_SHOWN_MS = 4000;" in page
    assert "setTimeout(() => render(LATEST), REFUSAL_SHOWN_MS + 50);" in function(page, "prompt")
    lapsed = function(page, "refusalLine").split("if (refusal.until <= Date.now()) {", 1)[1]
    assert lapsed.startswith("\n    refusedPrompts.delete(sessionId);\n    return null;\n  }")


def test_the_reason_shows_under_the_card_or_the_teammates_line_it_was_meant_for():
    """A teammate is one line inside its parent's card, so its reason goes
    right after that line, not at the foot of the parent's card."""
    body = function(PAGE.read_text(encoding="utf-8"), "paint")
    after = body.split("const refusal = refusalLine(row.session_id);\n", 1)[1]
    teammate, card = after.split("        continue;\n      }\n", 1)
    assert teammate.startswith("      if (row.depth && li === card) {")
    assert "if (refusal) b.after(refusal);" in teammate
    assert "if (refusal) li.append(refusal);" in card.split("      ul.append(li);\n", 1)[0]


def test_the_menu_offers_a_row_only_its_own_agents_commands():
    source = PAGE.read_text(encoding="utf-8")
    assert 'HOUSEKEEPING.filter(item => item.agents.includes(row.provider || "claude"))' in source
