# ABOUTME: Guards which slash commands page.html offers on an agent's row.
# ABOUTME: A command is typed into the pane as it stands, so a row is offered only what its agent has.
import re
from pathlib import Path

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


def test_the_menu_offers_a_row_only_its_own_agents_commands():
    source = PAGE.read_text(encoding="utf-8")
    assert 'HOUSEKEEPING.filter(item => item.agents.includes(row.provider || "claude"))' in source
