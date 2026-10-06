# ABOUTME: Reads one top-level JavaScript function out of page.html's source, for the page's tests.
# ABOUTME: The page has no JS harness, so its tests check the shape of the function that does the thing.
import re


def function(page, name):
    """The text of `function name(...) {...}`, from its line to the closing
    brace at the start of a line."""
    return re.search(rf"\nfunction {name}\(.*?\n\}}\n", page, re.S).group(0)
