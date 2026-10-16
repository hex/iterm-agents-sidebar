# ABOUTME: Guards the rules that keep page.html's card list, queue and foot painted in place: a per-frame builder writes
# ABOUTME: no inline style and attaches no listener of its own, since a node made and dropped per frame is what WebKit never frees.
"""The card list, the queue and the foot are built detached every frame and
morphed onto the live ones, so a live node lives across frames. That only pays while two rules hold.
A builder never writes .style: an inline declaration on a kept node is the
measured 23 to 60 MB case, and the generated palette carries every value a
node can wear as a data attribute instead. A builder never calls
addEventListener: a handler goes through on(), whose bag travels to the live
node each frame, so a kept node runs this frame's closure and a dropped built
node never gets a listener.

Each rule is an allowlist of the top-level functions that may do the thing:
the ones whose nodes are never rebuilt (the document, the settings sheet, the
details card, the drag and its tether, the floating menu), the ones that write
on an event rather than a frame (a phase sync, a glide's start, the open
popover's place).
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "page.html"

STYLE_WRITERS = {
    # written on an event, never on a frame that kept the node
    "syncShimmer", "syncBreathe", "glide", "showOpenShell", "applyShellFont", "applyScale",
    # the floating menu, the details card and its context breakdown
    "openMenuAt", "showCard", "moveCard", "ctxItemList", "breakdownBar", "tinted",
    # FLIP's holders for what left, and the drag with its ghost, tether and landings
    "animateRows", "ghostOf", "moveDrag", "placeFixed", "placeRefusal", "drawTether", "seam", "unseam",
    "confirmLink", "stepLanding",
    # the settings sheet
    "settingRow",
}

LISTENER_OWNERS = {
    # the trampoline every built node's handlers run through
    "listen",
    # nodes made once, or on an event: the details card, the floating menu, the settings sheet, the offers
    "paintBreakdown", "ctxOpener", "ctxDeferred", "menuFor", "settingSwitch", "settingRow", "settingsBody", "githubRow",
    "paintVersion", "paintStatuslineOffer",
}


def script():
    return re.search(r"<script>(.*?)</script>", PAGE.read_text(encoding="utf-8"), re.S).group(1).split("\n")


def owners(pattern):
    """The top-level function each match of `pattern` sits in, "top level" for a statement outside any."""
    found, current = set(), "top level"
    for line in script():
        head = re.match(r"function (\w+)\(", line)
        if head:
            current = head.group(1)
        elif line.startswith("}"):
            current = "top level"
        if re.search(pattern, line):
            found.add(current)
    return found


def test_a_per_frame_builder_writes_no_inline_style():
    writers = owners(r"\.style(\.\w+|\[[^\]]+\])\s*=|\.style\.(setProperty|removeProperty)\(|Object\.assign\(\w+\.style")
    assert writers - STYLE_WRITERS - {"top level"} == set(), (
        "a per-frame builder writes .style; colour, depth and width are data attributes the palette reads, "
        "and only a function listed in STYLE_WRITERS, whose nodes are never rebuilt, may write a style")


def test_a_per_frame_builder_attaches_handlers_with_on():
    owners_found = owners(r"\.addEventListener\(")
    assert owners_found - LISTENER_OWNERS - {"top level"} == set(), (
        "per-frame builders attach handlers with on(); LISTENER_OWNERS allows only nodes never rebuilt")
