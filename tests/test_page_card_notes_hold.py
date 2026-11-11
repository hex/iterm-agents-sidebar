# ABOUTME: Guards the timed notes a card gets from a refused prompt, link or review, and a sent link, against the
# ABOUTME: question hold: page.html's own posting functions and render run under node with the pointer on an asking card.
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")
QUOTED = next(line for line in PAGE.splitlines() if line.startswith("const quotedLabel = "))

#: The page beneath a note: the pointer rests on an asking card, so holdsBack holds every frame not painted now;
#: a paint records each card's note as it stands; fetch answers as the test says; timers run when the test says.
STUBS = """
const TOKEN = "t0k";
const REFUSAL_SHOWN_MS = 4000, LINK_SENT_MS = 2000;
const refusedPrompts = new Map(), linkSent = new Map();
let LATEST = {groups: []};
let paintFailure = null, heldFrame = null, heldArrived = false, dragging = null;
const document = {body: {classList: {add() {}}}};
const frameIsStale = () => false;
const holdsBack = () => true;
const announce = () => {};
const painted = [];
const paintAll = () => painted.push([refusedPrompts.get("p1")?.text ?? null, linkSent.get("p2")?.text ?? null]);
const timers = [];
const setTimeout = (fn, ms) => timers.push(fn);
const runTimers = () => timers.splice(0).forEach(fn => fn());
let answer;
const fetch = () => Promise.resolve(answer);
const settle = () => new Promise(resolve => setImmediate(resolve));
"""


def run(body):
    """Runs `body` under node after page.html's note posters and render; -> what it logs, parsed."""
    script = "\n".join([STUBS, QUOTED, *(function(PAGE, name) for name in ("render", "prompt", "postLink", "postReview")),
                        body])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_refused_prompt_paints_its_reason_while_the_pointer_holds_an_asking_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“alpha” is waiting on you"})};
          prompt("p1", "/compact");
          await settle();
          console.log(JSON.stringify(painted));
        })();
    """) == [["not sent: “alpha” is waiting on you", None]]


def test_a_refused_link_paints_its_reason_while_the_pointer_holds_an_asking_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“bravo” is waiting on you"})};
          postLink({session_id: "p1", label: "alpha"}, {session_id: "p2", label: "bravo"});
          await settle();
          console.log(JSON.stringify(painted));
        })();
    """) == [["not linked: “bravo” is waiting on you", None]]


def test_a_sent_link_paints_its_note_while_the_pointer_holds_an_asking_card():
    assert run("""
        (async () => {
          answer = {status: 200, json: async () => ({ok: true, link: {}})};
          postLink({session_id: "p1", label: "alpha"}, {session_id: "p2", label: "bravo"});
          await settle();
          console.log(JSON.stringify(painted));
        })();
    """) == [[None, "Sent · from “alpha”"]]


def test_a_refused_review_paints_its_reason_while_the_pointer_holds_an_asking_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“bravo” is waiting on you"})};
          postReview("p1");
          await settle();
          console.log(JSON.stringify(painted));
        })();
    """) == [["not asked: “bravo” is waiting on you", None]]


def test_a_refused_link_is_painted_away_while_the_pointer_still_holds_the_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“bravo” is waiting on you"})};
          postLink({session_id: "p1", label: "alpha"}, {session_id: "p2", label: "bravo"});
          await settle();
          const shown = painted.length;
          runTimers();
          console.log(JSON.stringify(painted.length - shown));
        })();
    """) == 1


def test_a_sent_link_note_is_painted_away_while_the_pointer_still_holds_the_card():
    assert run("""
        (async () => {
          answer = {status: 200, json: async () => ({ok: true, link: {}})};
          postLink({session_id: "p1", label: "alpha"}, {session_id: "p2", label: "bravo"});
          await settle();
          const shown = painted.length;
          runTimers();
          console.log(JSON.stringify(painted.length - shown));
        })();
    """) == 1


def test_a_refused_review_is_painted_away_while_the_pointer_still_holds_the_card():
    assert run("""
        (async () => {
          answer = {status: 409, json: async () => ({error: "“bravo” is waiting on you"})};
          postReview("p1");
          await settle();
          const shown = painted.length;
          runTimers();
          console.log(JSON.stringify(painted.length - shown));
        })();
    """) == 1
