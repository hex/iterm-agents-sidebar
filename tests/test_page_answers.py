# ABOUTME: Guards which cards page.html draws answer buttons on.
# ABOUTME: A button the daemon would refuse is a click that does nothing, so the two lists must agree.
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "page.html"
sys.path.insert(0, str(ROOT))

from sidebar import PROVIDER_ORDER, answer_keys  # noqa: E402

ASKED = {"header": "Scope", "question": "Which branch?", "options": ["main", "dev"], "multi": False, "more": 0}


def test_option_buttons_are_drawn_only_for_the_agents_the_daemon_answers():
    """omp draws its own ask dialog: its card shows the question and leaves the
    answer to the terminal."""
    source = PAGE.read_text(encoding="utf-8")
    drawn = json.loads(re.search(r"const PICKED_ON_CARD = (\[[^\]]*\]);", source).group(1))
    click = json.dumps({"pick": 1, "question": ASKED["question"]})
    answered = [provider for provider in PROVIDER_ORDER if answer_keys(click, ASKED, None, provider)]
    assert drawn == answered == ["claude", "openai"]
    assert 'row.question?.options?.length && PICKED_ON_CARD.includes(row.provider || "claude")' in source
