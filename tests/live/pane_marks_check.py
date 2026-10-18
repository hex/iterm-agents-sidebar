# ABOUTME: Manual live check, not collected by pytest: which per-session profile fields written
# ABOUTME: through the API show in a split pane. Opens a throwaway window, shoots it, closes it.
"""Run with iTerm2's own python and its cookie:

    export ITERM2_COOKIE=$(osascript -e 'tell application "iTerm2" to request cookie')
    ~/Library/Application\\ Support/iTerm2/iterm2env-*/versions/*/bin/python3 tests/live/pane_marks_check.py OUT_DIR

Writes OUT_DIR/subtitle.png (subtitle "Done" on the background split) and OUT_DIR/badge.png
(badge text "Done" on it). Measured 2026-10-18 on iTerm2 3.7.1: the subtitle shows nowhere,
neither in the tab nor in the pane's title bar; the badge shows in the pane.
"""
import asyncio, subprocess, sys
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

    async def shot(name):
        # In front first: the frame is in screen points from the bottom-left,
        # and a window behind another is not what the capture should show.
        await win.async_activate()
        await asyncio.sleep(0.8)
        frame = await win.async_get_frame()
        x, y, w, h = int(frame.origin.x), int(frame.origin.y), int(frame.size.width), int(frame.size.height)
        screen_h = int(AppKit.NSScreen.mainScreen().frame().size.height)
        subprocess.run(["screencapture", "-x", "-R", f"{x},{screen_h - y - h},{w},{h}", f"{OUT}/{name}.png"], check=True)
        print(f"{OUT}/{name}.png")

    profile = await b.async_get_profile()
    await profile.async_set_subtitle("Done")
    await asyncio.sleep(1.5)
    await shot("subtitle")
    await profile.async_set_subtitle("")
    await profile.async_set_badge_text("Done")
    await asyncio.sleep(1.5)
    await shot("badge")
    await win.async_close(force=True)


iterm2.run_until_complete(main)
