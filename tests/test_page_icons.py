# ABOUTME: Guards how page.html classes its SVG icons.
# ABOUTME: An SVG element's className is read-only, so assigning it throws and the panel paints no rows.
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_no_icon_is_classed_by_assigning_className():
    source = PAGE.read_text(encoding="utf-8")
    assigned = re.findall(r"Object\.assign\(\s*metaIcon\([^)]*\)\s*,\s*\{[^}]*className", source)
    assert assigned == []


def test_every_agent_the_daemon_names_has_a_mark():
    source = PAGE.read_text(encoding="utf-8")
    listed = re.search(r"const PROVIDER_ICONS = \{(.*?)\n\};", source, re.S).group(1)
    assert re.findall(r"^\s*(\w+): '", listed, re.M) == ["claude", "openai", "omp"]


def test_an_agent_without_a_mark_of_its_own_gets_the_plain_one():
    """innerHTML of a missing key writes the word "undefined" into the icon."""
    source = PAGE.read_text(encoding="utf-8")
    assert "svg.innerHTML = PROVIDER_ICONS[kind] || PLAIN_MARK;" in source


def test_a_row_with_no_model_yet_names_its_program_instead():
    """Codex before its first turn, and omp always: neither has a model to
    hang the mark on, and the card would not say which agent it is."""
    source = PAGE.read_text(encoding="utf-8")
    listed = re.search(r"const PROGRAMS = \{(.*?)\n\};", source, re.S).group(1)
    assert re.findall(r'^\s*(\w+): \{mark: "([^"]+)", name: "([^"]+)"\}', listed, re.M) == [
        ("openai", "OpenAI", "Codex"), ("omp", "omp", "omp")]


def test_a_sessions_topic_is_drawn_as_a_title_with_nothing_to_go_stale():
    """A topic is the agent's live word. Routed through the task line it would
    have no report stamp, and that line calls an unstamped note stale."""
    source = PAGE.read_text(encoding="utf-8")
    drawn = re.search(r"function topicLine\(topic, doing\) \{(.*?)\n\}", source, re.S).group(1)
    assert "task-title" in drawn and "task-activity" in drawn and "dataset.spoken" in drawn
    assert "stale" not in drawn and "taskLine" not in drawn
    assert re.search(r"else if \(\(row\.topic \|\| row\.doing\) && [^)]*\) \{\s*"
                     r"stack\.append\(topicLine\(row\.topic, row\.doing\)\);", source)


def test_a_short_branch_is_not_held_wider_than_its_name():
    """The floor that keeps a clipped branch readable is six characters; held
    flat, it left a hole after `main`."""
    source = PAGE.read_text(encoding="utf-8")
    assert "min-width: calc(var(--meta-icon) + 3px + var(--floor, 6) * 1ch);" in source
    assert 'if (kind === "branch") chip.style.setProperty("--floor", Math.min(value.length, 6));' in source
