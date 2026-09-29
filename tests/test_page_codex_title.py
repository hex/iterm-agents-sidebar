"""A Codex card's task line wears the title Codex gave the conversation.

Asked 2026-09-29: the title Codex's own status line shows is how the
conversation is known there; the task report keeps its activity, percent
and age beside it.
"""
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"


def test_a_codex_task_line_is_titled_as_codex_titled_the_conversation():
    page = PAGE.read_text(encoding="utf-8")
    assert ('stack.append(taskLine(row.provider === "openai" && row.topic'
            ' ? {...row.task, title: row.topic} : row.task));') in page
