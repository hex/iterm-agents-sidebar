# ABOUTME: Manual live check, not collected by pytest: a turn that ends in a background split marks
# ABOUTME: its pane with Done and its card washed and banded, and focusing the pane clears both.
"""Needs the daemon running from this checkout. Run with iTerm2's own python and its cookie:

    export ITERM2_COOKIE=$(osascript -e 'tell application "iTerm2" to request cookie')
    ~/Library/Application\\ Support/iTerm2/iterm2env-*/versions/*/bin/python3 tests/live/finished_marks.py OUT_DIR

Opens a throwaway window with two splits, publishes a Claude state on the
background one that goes working then idle (no agent runs: the user variable
is the turn), reads the daemon's /events snapshot and the pane's profile, and
prints one PASS or FAIL line per expectation. Screenshots before and after
the clear land in OUT_DIR. Exit 0 only when every line passed.
"""
import asyncio
import importlib.machinery
import importlib.util
import json
import pathlib
import subprocess
import sys
import time

import AppKit
import iterm2

OUT = sys.argv[1]


def plain_shell():
    """A pane that runs a bare shell, whatever the default profile's command is:
    a profile that attaches tmux would raise iTerm2's Cannot Attach dialog on
    every throwaway window."""
    p = iterm2.LocalWriteOnlyProfile()
    p.set_use_custom_command("Yes")
    p.set_command("/bin/zsh")
    return p
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
WITHIN = 8.0
failed = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failed.append(name)


def cli():
    loader = importlib.machinery.SourceFileLoader("agents_sidebar_cli", str(REPO / "agents-sidebar"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def snapshot_row(session_id):
    """The daemon's current row for `session_id`, from a fresh /events connection."""
    tool = cli()
    connection, stream = tool.open_stream()
    try:
        for event, data in tool.frames(stream):
            if isinstance(data, dict) and "groups" in data:
                for group in data["groups"]:
                    for row in group["rows"]:
                        if row.get("session_id") == session_id:
                            return row
                return None
    finally:
        connection.close()


def wait_for(session_id, predicate, seconds=WITHIN):
    deadline = time.monotonic() + seconds
    row = None
    while time.monotonic() < deadline:
        row = snapshot_row(session_id)
        if predicate(row):
            return row, True
        time.sleep(0.5)
    return row, False


async def main(connection):
    app = await iterm2.async_get_app(connection)
    win = await iterm2.Window.async_create(connection, profile_customizations=plain_shell())
    await asyncio.sleep(1.0)
    await app.async_refresh()
    win = app.get_window_by_id(win.window_id)
    a = win.current_tab.current_session
    b = await a.async_split_pane(vertical=True, profile_customizations=plain_shell())
    await asyncio.sleep(1.0)
    await a.async_activate()
    await app.async_activate()

    async def shot(name):
        await asyncio.sleep(0.6)
        frame = await win.async_get_frame()
        x, y, w, h = int(frame.origin.x), int(frame.origin.y), int(frame.size.width), int(frame.size.height)
        screen_h = int(AppKit.NSScreen.mainScreen().frame().size.height)
        subprocess.run(["screencapture", "-x", "-R", f"{x},{screen_h - y - h},{w},{h}", f"{OUT}/{name}.png"], check=True)

    pid = int(await b.async_get_variable("pid"))
    sid = b.session_id

    async def publish(state):
        await b.async_set_variable("user.claudeState", json.dumps(
            {"state": state, "pid": pid, "ts": round(time.time(), 3), "session": "live-check"}))

    try:
        await publish("working")
        row, ok = await asyncio.to_thread(wait_for, sid, lambda r: r is not None and r.get("state") == "working")
        check("row working", ok, str(row and row.get("state")))
        await publish("idle")
        row, ok = await asyncio.to_thread(wait_for, sid, lambda r: r is not None and r.get("unseen") is True)
        check("card finished", ok, f"unseen={row and row.get('unseen')}")
        check("card banded", bool(row and row.get("band") == "finished"), f"band={row and row.get('band')}")
        profile = await b.async_get_profile()
        check("marked badge", profile.badge_text == "Done", repr(profile.badge_text))
        await shot("marked")

        # Looking means the pane is in front of the key window while iTerm2 is
        # the frontmost app, so the window comes forward before the pane.
        await app.async_activate()
        await win.async_activate()
        await b.async_activate()
        row, ok = await asyncio.to_thread(wait_for, sid, lambda r: r is not None and not r.get("unseen"))
        check("card plain", ok and not (row or {}).get("band"), f"unseen={row and row.get('unseen')} band={row and row.get('band')}")
        profile = await b.async_get_profile()
        check("cleared badge", profile.badge_text == "", repr(profile.badge_text))
        await shot("cleared")
    finally:
        await win.async_close(force=True)
    print("ALL PASS" if not failed else f"FAILED: {', '.join(failed)}", flush=True)
    sys.exit(0 if not failed else 1)


iterm2.run_until_complete(main)
