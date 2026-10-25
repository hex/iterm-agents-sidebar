# ABOUTME: Manual live check, not collected by pytest: the tab status writer against a real iTerm2.
# ABOUTME: Opens a throwaway window, writes each word, reads each back, shoots the tab bar, closes it.
"""Run with iTerm2's own python and its cookie:

    export ITERM2_COOKIE=$(osascript -e 'tell application "iTerm2" to request cookie')
    ~/.config/iterm2/AppSupport/uv/venvs/3.10/bin/python tests/live/tab_status_check.py OUT_DIR

The writer sees only the throwaway window's sessions, so it never reads or
clears a tab of yours. Prints a PASS or FAIL line per expectation and writes
OUT_DIR/needs-you.png and OUT_DIR/done.png, the window with its tab bar.
"""
import asyncio
import functools
import subprocess
import types
import sys
from pathlib import Path

import AppKit
import iterm2
import Quartz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import sidebar  # noqa: E402
import tabstatus  # noqa: E402

OUT = sys.argv[1]
ON = {"tab_status": True, "offer_tab_status": True}
QUESTION = 'Say "yes" or C:\\path\\(session.name)?'
failures = []


def plain_shell():
    """A pane that runs a bare shell, whatever the default profile's command is:
    a profile that attaches tmux would raise iTerm2's Cannot Attach dialog on
    every throwaway window."""
    p = iterm2.LocalWriteOnlyProfile()
    p.set_use_custom_command("Yes")
    p.set_command("/bin/zsh")
    return p


class Mine:
    """The app as the writer sees it: the throwaway window's sessions and nothing else."""
    def __init__(self, window):
        self.terminal_windows = [window]
        self.sessions = {s.session_id: s for tab in window.tabs for s in tab.sessions}

    def get_session_by_id(self, sid):
        return self.sessions.get(sid)


def expect(what, seen, wanted):
    ok = seen == wanted
    print(f"{'PASS' if ok else 'FAIL'} {what}: {seen!r}" + ("" if ok else f" != {wanted!r}"), flush=True)
    if not ok:
        failures.append(what)


async def main(connection):
    # The daemon's own call, so the check covers how it encodes and sends.
    invoke = functools.partial(sidebar.Bridge.invoke_function, types.SimpleNamespace(connection=connection))

    app = await iterm2.async_get_app(connection)
    win = await iterm2.Window.async_create(connection, profile_customizations=plain_shell())
    await asyncio.sleep(1.0)
    await win.async_create_tab(profile_customizations=plain_shell())
    await asyncio.sleep(1.0)
    await app.async_refresh()
    win = app.get_window_by_id(win.window_id)
    a = win.tabs[0].current_session
    await win.tabs[0].async_activate()
    sid, mine, logged = a.session_id, Mine(win), []

    async def status():
        got = await invoke("iterm2.get_session_status", {"session_id": sid})
        return {k: got.get(k) for k in ("status", "detail", "dot_color", "text_color", "background_tasks")}

    async def shot(name):
        # By window id, not by screen region: a window in front of this one
        # (yours, while you type) never lands in the shot, and nothing has to
        # take the focus. The frame is in points from the bottom-left; the
        # window list measures from the top-left.
        await asyncio.sleep(0.8)
        frame = await win.async_get_frame()
        x, y, w, h = int(frame.origin.x), int(frame.origin.y), int(frame.size.width), int(frame.size.height)
        top = int(AppKit.NSScreen.mainScreen().frame().size.height) - y - h
        windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
        ids = [int(info["kCGWindowNumber"]) for info in windows
               if info.get("kCGWindowOwnerName") == "iTerm2" and info.get("kCGWindowLayer") == 0
               and (int(info["kCGWindowBounds"]["X"]), int(info["kCGWindowBounds"]["Y"]),
                    int(info["kCGWindowBounds"]["Width"]), int(info["kCGWindowBounds"]["Height"])) == (x, top, w, h)]
        if len(ids) != 1:
            expect(f"one iTerm2 window at the throwaway window's frame for {name}", len(ids), 1)
            return
        subprocess.run(["screencapture", "-x", "-o", "-l", str(ids[0]), f"{OUT}/{name}.png"], check=True)
        print(f"{OUT}/{name}.png", flush=True)

    try:
        writer = tabstatus.Writer(invoke=invoke)
        row = {"session_id": sid, "depth": 0, "provider": "openai"}
        await writer.step(mine, [dict(row, state="working", doing="Running the live check", agents=1,
                                      shells=[{"command": "sleep 60"}])], set(), ON, "absent", logged.append)
        expect("working", await status(), {"status": "working", "detail": "Running the live check",
                                           "dot_color": "#ff9501", "text_color": "#ff9501", "background_tasks": 2})
        await writer.step(mine, [dict(row, state="blocked", question={"question": QUESTION, "options": ["Yes", "No"]})],
                          set(), ON, "absent", logged.append)
        expect("needs you, quote and backslash kept", await status(),
               {"status": "needs you", "detail": QUESTION, "dot_color": "#ff9f0a", "text_color": "#ff9f0a",
                "background_tasks": 0})
        await shot("needs-you")
        await writer.step(mine, [dict(row, state="idle")], {sid}, ON, "absent", logged.append)
        expect("done", await status(), {"status": "done", "detail": None, "dot_color": "#30d158",
                                        "text_color": "#30d158", "background_tasks": 0})
        await shot("done")
        blank = {"status": None, "detail": None, "dot_color": None, "text_color": None, "background_tasks": 0}
        await writer.step(mine, [dict(row, state="idle")], set(), ON, "absent", logged.append)
        expect("idle clears every field", await status(), blank)

        await writer.step(mine, [dict(row, state="working")], set(), ON, "absent", logged.append)
        await writer.clear_all(logged.append)
        expect("stopping clears every field", await status(), blank)

        await writer.step(mine, [dict(row, state="working")], set(), ON, "absent", logged.append)
        fresh = tabstatus.Writer(invoke=invoke)
        await fresh.step(mine, [], set(), ON, "absent", logged.append)
        expect("a dead writer's word is cleared by the next one's start", await status(), blank)
        expect("nothing logged", logged, [])
    finally:
        await win.async_close(force=True)
    print("FAILED: " + ", ".join(failures) if failures else "ALL PASS", flush=True)


iterm2.run_until_complete(main)
