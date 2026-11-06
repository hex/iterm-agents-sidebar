# ABOUTME: Guards which cards page.html draws answer buttons on.
# ABOUTME: A button the daemon would refuse is a click that does nothing, so the two lists must agree.
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "page.html"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402
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


def test_checkboxes_are_drawn_only_for_the_agents_whose_ticks_the_daemon_types():
    """Codex's multi-select keys were never measured: its pick-any card shows
    the options and leaves the answer to the terminal."""
    source = PAGE.read_text(encoding="utf-8")
    drawn = json.loads(re.search(r"const TICKED_ON_CARD = (\[[^\]]*\]);", source).group(1))
    pick_any = dict(ASKED, multi=True)
    click = json.dumps({"pick": [1], "question": ASKED["question"]})
    answered = [provider for provider in PROVIDER_ORDER if answer_keys(click, pick_any, None, provider)]
    assert drawn == answered == ["claude"]
    assert 'asked.multi && TICKED_ON_CARD.includes(row.provider || "claude")' in source


#: Just enough of the DOM for a card's answers: nodes that keep their children, text and classes.
DOM = """
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.classes = []; this.textContent = "";
                     this.classList = {add: name => this.classes.push(name)}; }
  append(...kids) { this.children.push(...kids); }
  setAttribute() {}
  text() { return [this.textContent, ...this.children.map(c => c.text())].filter(Boolean).join(" "); }
  buttons() { return [...(this.tag === "button" ? [this.text()] : []), ...this.children.flatMap(c => c.buttons())]; }
}
const document = {createElement: tag => new Node(tag)};
"""


def under_card(row):
    """What page.html puts under a full-width card for `row` -> {asking, text, buttons}."""
    page = PAGE.read_text(encoding="utf-8")
    names = re.findall(r"^const (?:pickedAnswers|PICKED_ON_CARD|TICKED_ON_CARD|GATE_YES_KEY) = .*;$", page, re.M)
    script = "\n".join([DOM, *names, *(function(page, name) for name in (
        "statusLine", "remoteRefusalLine", "cardQuestion", "answerParts", "on", "answerRows", "offerAnswers")),
        f"const li = new Node('li'); offerAnswers(li, {json.dumps(row)}, false);",
        "console.log(JSON.stringify({asking: li.classes.includes('asking'), text: li.text(), buttons: li.buttons()}));"])
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


REMOTE_ROW = {"session_id": "s1", "state": "blocked", "host": "box", "provider": "claude",
              "question": {"question": "Which one?", "options": ["This", "That"], "multi": False, "more": 0}}


def test_a_remote_card_the_daemon_would_type_no_key_into_says_why_in_place_of_its_buttons():
    """A question whose options show previews is one: its pick takes Enter, which a remote pane is never sent."""
    previewed = dict(REMOTE_ROW, question=dict(REMOTE_ROW["question"], preview=True),
                     remote_refusal="a pick beside previews takes Enter")
    assert under_card(previewed) == {"asking": False, "text": "Answer in the pane: a pick beside previews takes Enter",
                                     "buttons": []}
    assert under_card(REMOTE_ROW) == {"asking": True, "text": "1 This 2 That", "buttons": ["1 This", "2 That"]}
