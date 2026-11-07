# ABOUTME: Puts back the line iTerm2's Minimal theme draws under the selected tab where tab-underline.json says the
# ABOUTME: panel set it to 0, unless the user changed it since, then takes the record away.

import asyncio
import json
import os
import re
from dataclasses import dataclass

#: iTerm2's settings as `defaults` names them. iTerm2 reloads an advanced setting the moment it changes there.
DOMAIN = "com.googlecode.iterm2"
#: The advanced setting the line is drawn from: 1 while unset, 0 hides it.
KEY = "MinimalSelectedTabUnderlineProminence"
DEFAULTS = "/usr/bin/defaults"
#: `defaults read-type`'s word -> the flag `defaults write` stores a value of that type under.
FLAGS = {"float": "-float", "string": "-string", "integer": "-int", "boolean": "-bool"}


class Failed(Exception):
    """A step that could not finish, said in words the log can carry."""


@dataclass(frozen=True)
class Value:
    """A setting as `defaults` gives it."""
    #: The word `defaults read-type` says, as "float" or "string".
    type: str
    #: What `defaults read` printed, its last newline dropped.
    text: str

    @property
    def zero(self):
        """Equal to 0 as a number, whatever type it is stored as."""
        try:
            return float(self.text) == 0
        except ValueError:
            return False


@dataclass(frozen=True)
class Held:
    """The panel set the line to 0. `kept` is what was there, None when the setting was unset."""
    kept: Value | None


@dataclass(frozen=True)
class Aside:
    """The line is the user's: the panel left it as they set it."""


async def defaults(*words):
    """-> what `defaults <words>` printed. Raises Failed with what it said when it exits non-zero."""
    process = await asyncio.create_subprocess_exec(DEFAULTS, *words, stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.PIPE)
    out, err = await process.communicate()
    if process.returncode:
        raise Failed(f"defaults {words[0]} said {said(err.decode())}")
    return out.decode()


def said(stderr):
    """`defaults`'s complaint on one line, without the time and process NSLog puts before it."""
    text = " ".join(line.strip() for line in stderr.splitlines() if line.strip())
    return re.sub(r"^\S+ \S+ defaults\[[\d:]+\]\s*", "", text) or "nothing"


def written(value):
    """The text `defaults write` takes `value` back from: it prints a boolean as 1 or 0 and reads only words."""
    if value.type == "boolean":
        return {"1": "true", "0": "false"}[value.text]
    return value.text


async def read(key=KEY):
    """-> the setting's Value, or None while it is unset. Raises Failed."""
    try:
        word = await defaults("read-type", DOMAIN, key)
    except Failed as error:
        if str(error).endswith("does not exist"):
            return None
        raise
    return Value(word.strip().removeprefix("Type is "), (await defaults("read", DOMAIN, key)).removesuffix("\n"))


def parse(record):
    """The record's JSON -> Held or Aside. Raises ValueError, naming what is wrong, for any other shape."""
    if record == {"aside": True}:
        return Aside()
    if not isinstance(record, dict) or record.keys() != {"kept"}:
        raise ValueError(f"neither held nor aside: {record!r}")
    kept = record["kept"]
    if kept is None:
        return Held(None)
    if not isinstance(kept, dict) or kept.keys() != {"type", "value"} or kept["type"] not in FLAGS \
            or not isinstance(kept["value"], str) or (kept["type"] == "boolean" and kept["value"] not in ("0", "1")):
        raise ValueError(f"kept is no value this module writes back: {kept!r}")
    return Held(Value(kept["type"], kept["value"]))


def load(path):
    """-> the state the record at `path` holds, None without one. Raises Failed for one this module did not write."""
    try:
        with open(path, encoding="utf-8") as record:
            return parse(json.load(record))
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise Failed(f"{path} unreadable: {error}") from error


async def put_back(path, log):
    """Put back what the record at `path` holds while the line still reads 0, then remove the record. A step that
    fails is logged and leaves the record for the next try. `log` takes one line."""
    path = str(path)
    try:
        state = load(path)
        if state is None:
            return
        if isinstance(state, Held):
            now = await read()
            if now is None or not now.zero:
                log("tab underline taken back")
            elif state.kept is None:
                await defaults("delete", DOMAIN, KEY)
                log("tab underline put back")
            else:
                await defaults("write", DOMAIN, KEY, FLAGS[state.kept.type], written(state.kept))
                log("tab underline put back")
        os.remove(path)
    except (Failed, OSError) as error:
        log(f"tab underline: {error}")
