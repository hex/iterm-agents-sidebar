# ABOUTME: Guards the panel's GPU cost at the source: endless motion moves only transform or opacity and rests
# ABOUTME: when unseen, and every blur or filter in page.html is one on a pinned list, measured when it was added.
"""The panel stays open all day, so whatever moves without end decides what it
costs. Measured 2026-10-08 with powermetrics: a shimmer that repainted its text
every frame held the GPU at 95% and WebKit's GPU process at 40% CPU; moved by
transform alone and paused when unseen, the same panel measured 0-0.6%. A GPU
reading needs sudo and is shared with every other app, so the release suite
guards the causes instead, and a powermetrics reading follows any change this
file has to be told about.

Failure modes, written before the code: a CSS animation that runs without end
over a property other than transform or opacity; the same started from script
with `iterations: Infinity`; an endless CSS animation with no rule pausing it
while the page is hidden, or none pausing it while its row is out of the
list's view; an endless scripted animation, which CSS play states never reach,
left running in either case; a blur, backdrop blur or SVG filter added
anywhere in the page without being measured.
"""
import re
from pathlib import Path

from page_source import function

PAGE = Path(__file__).resolve().parent.parent / "page.html"
CHEAP = {"transform", "opacity"}


def page():
    return PAGE.read_text(encoding="utf-8")


def stylesheet():
    css = "\n".join(re.findall(r"<style>(.*?)</style>", page(), re.S))
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def keyframes(css):
    """-> ({name: properties its frames set}, the stylesheet without them)."""
    found, rest, at = {}, [], 0
    for head in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", css):
        depth, end = 1, head.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        found[head[1]] = set(re.findall(r"([\w-]+)\s*:", css[head.end():end - 1]))
        rest.append(css[at:head.start()])
        at = end
    return found, "".join(rest) + css[at:]


def rules(css):
    """-> [(selector, declarations)] for every rule that holds declarations."""
    return [(selector.strip(), body) for selector, body in re.findall(r"([^{};]+)\{([^{}]*)\}", css)]


def selectors(selector):
    """Split a selector list on its top-level commas."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(selector):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(selector[start:i].strip())
            start = i + 1
    return parts + [selector[start:].strip()]


def endless_css():
    """-> [(selector, keyframes name)] for each rule starting an animation without end."""
    frames, css = keyframes(stylesheet())
    found = []
    for selector, body in rules(css):
        for animation in re.findall(r"animation\s*:\s*([^;]+)", body):
            words = re.findall(r"[\w-]+", animation)
            if "infinite" in words:
                found += [(one, name) for one in selectors(selector) for name in words if name in frames]
    return found


def test_the_page_has_endless_css_animations_to_judge():
    assert {name for _, name in endless_css()} == {"bob", "sweep-across", "sweep-hold", "breathe", "pair-breathe"}


def test_every_endless_css_animation_moves_only_transform_or_opacity():
    frames, _ = keyframes(stylesheet())
    costly = {name: frames[name] - CHEAP for _, name in endless_css() if frames[name] - CHEAP}
    assert costly == {}


def paused():
    _, css = keyframes(stylesheet())
    return {one for selector, body in rules(css) if re.search(r"animation-play-state\s*:\s*paused", body)
            for one in selectors(selector)}


def test_every_endless_css_animation_pauses_while_the_page_is_hidden():
    missing = [selector for selector, _ in endless_css() if f"html.hidden-page {selector}" not in paused()]
    assert missing == []


def test_every_endless_css_animation_pauses_while_its_row_is_out_of_view():
    # `.busy.out-of-view i` pauses `.busy i`, `.out-of-view > .sweep` pauses `.sweep`.
    unmarked = {re.sub(r"\s+", " ", p.replace(".out-of-view > ", "").replace(".out-of-view", "")).strip()
                for p in paused() if ".out-of-view" in p}
    missing = [selector for selector, _ in endless_css() if selector not in unmarked]
    assert missing == []


def closing(text, at):
    """-> the index just past the bracket that closes the one at `at`."""
    depth, end = 0, at
    while True:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(text[end], 0)
        end += 1
        if depth == 0:
            return end


def endless_scripted():
    """-> [(the function starting it, keyframe properties)] for each `.animate()` without end."""
    text, found = page(), []
    for call in re.finditer(r"\.animate\(", text):
        args = text[call.end() - 1:closing(text, call.end() - 1)]
        if re.search(r"iterations\s*:\s*Infinity", args):
            frames = args[args.index("["):closing(args, args.index("["))]
            starts = text.rfind("\nfunction ", 0, call.start())
            name = re.match(r"\nfunction (\w+)", text[starts:])[1]
            found.append((name, set(re.findall(r"(\w+)\s*:", frames)) - {"offset", "easing", "composite"}))
    return found


def test_the_long_name_glide_is_the_endless_motion_started_from_script():
    assert [name for name, _ in endless_scripted()] == ["glide"]
    # Spelled anywhere else, in options kept in a constant, the guard would not see it.
    assert len(re.findall(r"iterations\s*:\s*Infinity", page())) == len(endless_scripted())


def test_every_endless_scripted_animation_moves_only_transform_or_opacity():
    assert {name: props - CHEAP for name, props in endless_scripted() if props - CHEAP} == {}


def test_every_endless_scripted_animation_is_steered_from_the_moment_it_starts():
    unsteered = [name for name, _ in endless_scripted() if "steerScripted(" not in function(page(), name)]
    assert unsteered == []


def test_scripted_motion_rests_while_the_page_is_hidden():
    assert "steerScripted(document.getAnimations())" in function(page(), "noteVisibility")


def test_scripted_motion_rests_while_its_element_is_out_of_view():
    watch = re.search(r"const outOfViewWatch = new IntersectionObserver\((.*?)\n\}, ", page(), re.S)[1]
    assert "steerScripted(entry.target.getAnimations())" in watch
    endless = re.search(r'const ENDLESS = "([^"]*)"', page())[1]
    assert ".label > .run" in selectors(endless), "the glide runs on a label's run, so the run is watched"


def test_steering_pauses_hidden_or_unseen_scripted_motion_and_leaves_css_motion_to_its_rules():
    body = function(page(), "steerScripted")
    assert "a instanceof CSSAnimation" in body
    assert "iterations !== Infinity" in body
    assert re.search(r'if \(hidden \|\| a\.effect\.target\.classList\.contains\("out-of-view"\)\) a\.pause\(\);'
                     r"\s*else a\.play\(\);", body)


# Each blur and filter in the page, with where it is. Adding one means taking a
# powermetrics reading with it on screen (and while it moves, if it does) and
# then adding it here; the blurs below were read at rest on 2026-10-08, the
# fused link's only as a still in WebKit, never while a card is dragged.
BLURS_AND_FILTERS = {
    ("#card", "backdrop-filter", "saturate(180%) blur(20px)"),
    ("#card", "-webkit-backdrop-filter", "saturate(180%) blur(20px)"),
    (".menu", "backdrop-filter", "saturate(180%) blur(20px)"),
    (".menu", "-webkit-backdrop-filter", "saturate(180%) blur(20px)"),
    ("#budget .acct-switch:hover", "filter", "brightness(1.06)"),
    ("#budget .acct-switch:active", "filter", "brightness(.92)"),
}
SVG_FILTER_PRIMITIVES = {"feGaussianBlur": 1, "feColorMatrix": 1}
SVG_FILTERED_GROUPS = 2


def test_every_css_blur_and_filter_is_one_measured_and_listed():
    _, css = keyframes(stylesheet())
    found = {(selector, prop, value.strip())
             for selector, body in rules(css)
             for prop, value in re.findall(r"(?<![\w-])(-webkit-backdrop-filter|backdrop-filter|filter)\s*:\s*([^;]+)", body)}
    assert found == BLURS_AND_FILTERS


def test_every_svg_filter_the_script_draws_is_one_measured_and_listed():
    script = page()
    primitives = {name: len(re.findall(rf'make\("{name}"', script))
                  for name in set(re.findall(r'make\("(fe\w+)"', script))}
    assert primitives == SVG_FILTER_PRIMITIVES
    assert len(re.findall(r'filter: "url\(#', script)) == SVG_FILTERED_GROUPS
