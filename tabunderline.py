# ABOUTME: Hides the line iTerm2's Minimal theme draws under the selected tab while the tab tint is on, puts back what
# ABOUTME: was there once it goes off unless the user changed it since, and reads where iTerm2 shares its settings from.

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
#: `defaults read-type`'s word -> the flag `defaults write` stores a value of that type under. What `defaults read`
#: prints for a dictionary, an array, data or a date does not write back as it was, so none of those is held.
FLAGS = {"float": "-float", "string": "-string", "integer": "-int", "boolean": "-bool"}
#: iTerm2's save modes for a settings folder that save to it (iTermPreferences.h iTermPreferenceSavePrefsMode);
#: 1 is never.
SAVES_ON_QUIT, SAVES_AT_ONCE = "0", "2"


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
    """The tint is on and the line is the user's. Left alone until the tint goes off, across restarts too."""


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


async def settings_folder():
    """-> the folder iTerm2 loads its settings from and saves them back to, when it quits or at once; None while it
    keeps its own, reads them from a URL, or never saves to the folder, which is its mode until one is picked. Raises
    Failed."""
    if not truthy(await read("LoadPrefsFromCustomFolder")) \
            or not truthy(await read("NoSyncNeverRemindPrefsChangesLostForFile")):
        return None
    mode = await read("NoSyncNeverRemindPrefsChangesLostForFile_selection")
    if mode is None or mode.text not in (SAVES_ON_QUIT, SAVES_AT_ONCE):
        return None
    folder = await read("PrefsCustomFolder")
    if folder is None or not folder.text.startswith(("/", "~")):
        return None
    return os.path.expanduser(folder.text)


def truthy(value):
    return value is not None and not value.zero and value.text.strip().lower() not in ("", "no", "false")


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


class Underline:
    """Holds the line at 0 while the tint is on. Acts only when the setting changes and once at the first step of a
    daemon's life, so a rebuild makes no `defaults` call. What it holds is a record beside the status files, which a
    restarted daemon and the uninstall read. It is written before the line goes to 0: a 0 without it is the user's
    own and never comes back. A step that fails is logged and leaves the record as it was; the rebuild goes on."""

    def __init__(self, path):
        self.path = str(path)
        #: The tint setting last acted on; None before the first step.
        self.on = None

    async def step(self, on, log):
        """Bring the line into line with the tint setting `on`. `log` takes one line."""
        if on == self.on:
            return
        self.on = on
        try:
            state = self.load()
            if on and state is None:
                await self.hide(log)
            elif on and isinstance(state, Held):
                await self.check(log)
            elif not on and isinstance(state, Held):
                await self.put_back(state, log)
            elif not on and isinstance(state, Aside):
                self.drop()
        except (Failed, OSError) as error:
            log(f"tab underline: {error}")

    async def hide(self, log):
        now = await read()
        if now is not None and now.zero:
            self.keep(Aside())
            log("tab underline own")
            return
        if now is not None and now.type not in FLAGS:
            self.keep(Aside())
            log(f"tab underline: holds a {now.type}, which cannot be put back; left as it is")
            return
        self.keep(Held(now))
        try:
            await defaults("write", DOMAIN, KEY, "-float", "0")
        except Failed:
            self.drop()
            raise

    async def check(self, log):
        """The tint on over a line the record holds, at a daemon's start or after a put back that failed: one the
        user showed again meanwhile is theirs."""
        now = await read()
        if now is None or not now.zero:
            self.keep(Aside())
            log("tab underline taken back")

    async def put_back(self, state, log):
        now = await read()
        if now is None or not now.zero:
            log("tab underline taken back")
        elif state.kept is None:
            await defaults("delete", DOMAIN, KEY)
        else:
            await defaults("write", DOMAIN, KEY, FLAGS[state.kept.type], written(state.kept))
        self.drop()

    def load(self):
        """-> the state the record holds, None without one. Raises Failed for one this module did not write."""
        try:
            with open(self.path, encoding="utf-8") as record:
                return parse(json.load(record))
        except FileNotFoundError:
            return None
        except ValueError as error:
            raise Failed(f"{self.path} unreadable: {error}") from error

    def drop(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass

    def keep(self, state):
        if isinstance(state, Aside):
            record = {"aside": True}
        else:
            record = {"kept": None if state.kept is None else {"type": state.kept.type, "value": state.kept.text}}
        with open(self.path + ".tmp", "w", encoding="utf-8") as out:
            json.dump(record, out)
        os.replace(self.path + ".tmp", self.path)
