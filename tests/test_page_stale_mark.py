# ABOUTME: Guards the STALE mark across a paint that failed and then recovered: page.html's own onSnapshot, render
# ABOUTME: and markFresh run under node, so a frame that paints again clears the mark at once rather than at a heartbeat.
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from page_source import function  # noqa: E402

PAGE = (Path(__file__).resolve().parent.parent / "page.html").read_text(encoding="utf-8")

#: The page beneath a frame's arrival: a body whose classes are a set, a paint that fails while `breaking` is set,
#: and no drag, hold or refused frame in the way.
STUBS = """
const classes = new Set();
const document = {body: {classList: {add: c => classes.add(c), remove: c => classes.delete(c)}}};
const fetch = () => Promise.resolve();
const TOKEN = "t0k";
const STALE_AFTER_MS = 9000, STALE_FRAME_MS = 0;
let staleTimer = null, LATEST = {groups: []};
let paintFailure = null, heldFrame = null, heldArrived = false, dragging = null, droppedAt = 0, refusedFrame = null;
let sortedBeforeDrop = false;
const frameIsStale = () => sortedBeforeDrop;
const holdsBack = () => false;
const announce = () => {};
let breaking = false;
const paintAll = () => { if (breaking) throw new Error("boom"); };
"""


def run(body):
    """Runs `body` under node after page.html's frame functions; -> what it logs, parsed."""
    script = "\n".join([STUBS, *(function(PAGE, name) for name in ("markFresh", "render", "onSnapshot", "paintRefused")),
                        body, "clearTimeout(staleTimer);"])
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_a_frame_that_paints_after_a_failed_one_clears_the_stale_mark():
    assert run("""
        breaking = true;
        onSnapshot(JSON.stringify({groups: []}));
        const failed = [classes.has("stale"), paintFailure];
        breaking = false;
        onSnapshot(JSON.stringify({groups: []}));
        console.log(JSON.stringify([failed, [classes.has("stale"), paintFailure]]));
    """) == [[True, "Error: boom"], [False, None]]


def test_a_frame_that_fails_again_keeps_the_stale_mark():
    assert run("""
        breaking = true;
        onSnapshot(JSON.stringify({groups: []}));
        onSnapshot(JSON.stringify({groups: []}));
        console.log(JSON.stringify([classes.has("stale"), paintFailure]));
    """) == [True, "Error: boom"]


def test_a_refused_frame_that_paints_after_a_failed_one_clears_the_stale_mark():
    """A frame sorted before the last drop waits; when it paints, it is the frame that recovered."""
    assert run("""
        breaking = true;
        onSnapshot(JSON.stringify({groups: []}));
        breaking = false;
        sortedBeforeDrop = true;
        onSnapshot(JSON.stringify({groups: []}));
        const waiting = classes.has("stale");
        sortedBeforeDrop = false;
        paintRefused();
        console.log(JSON.stringify([waiting, classes.has("stale"), paintFailure]));
    """) == [True, False, None]
