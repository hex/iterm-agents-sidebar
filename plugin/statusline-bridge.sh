#!/bin/bash
# ABOUTME: Publishes Claude Code's statusline payload to a per-pid file for the
# ABOUTME: Agents sidebar, then renders the statusline the user actually configured.
#
# Claude Code hands this script its session JSON on stdin every render. That
# payload is the only place it publishes the size of the context window: the
# "[1m]" suffix is stripped from the model id before the request goes out, so
# 143k tokens could be 14% of one window or 71% of another and nothing in the
# transcript says which. Reading it here is the only way to show a percentage
# that agrees with the one Claude Code draws.
#
# The correlation key is free. This script is a direct child of the claude
# process, so $PPID is the pid the sidebar already resolved from its hook.
#
# Rendering the user's own statusline is the first responsibility, not the
# second. Every failure path below still runs it.

set -u

STATUS_DIR="$HOME/.claude/agents-sidebar-status"
ORIGINAL="$STATUS_DIR/original-statusline"

input=$(cat)

# Publish, but never at the cost of the statusline. An unwritable directory
# or a full disk must still end with the user's statusline on screen.
#
# The payload goes down whole, as it came: the daemon reads the fields it
# wants. Cheap on purpose. Claude Code runs this once a second in every
# session, kills a render that overruns, and a new session shows nothing
# until one render completes; with eight sessions a jq per render was
# enough to make every render overrun.
STATUS_TMP=""
cleanup() { [ -n "$STATUS_TMP" ] && rm -f "$STATUS_TMP" 2>/dev/null; }
trap cleanup EXIT TERM INT HUP

publish() {
    local pid="$PPID"
    case "$pid" in ''|*[!0-9]*) return 0 ;; esac
    case "$input" in "{"*) ;; *) return 0 ;; esac
    mkdir -p "$STATUS_DIR" 2>/dev/null || return 0

    # Written whole and moved into place: the sidebar reads this file on a
    # timer and must never catch a half-written one.
    STATUS_TMP="$STATUS_DIR/$pid.json.$$"
    if printf '%s' "$input" > "$STATUS_TMP" 2>/dev/null; then
        mv -f "$STATUS_TMP" "$STATUS_DIR/$pid.json" 2>/dev/null || rm -f "$STATUS_TMP" 2>/dev/null
    else
        rm -f "$STATUS_TMP" 2>/dev/null
    fi
    STATUS_TMP=""
}

publish

# Hand stdin to whatever was configured before the sidebar took this slot. An
# empty file means there was nothing to displace, and the statusline is ours
# alone to leave blank.
#
# Claude Code runs this once a second and kills a render still going when
# the next tick comes. A statusline that takes most of a second, in eight
# sessions at once, then never completes, and a new session never gets a
# line at all. So the line rendered last is printed at once, and the next
# one is rendered in the background where the kill does not reach it. The
# line shown is one tick behind, which nobody can see.
[ -s "$ORIGINAL" ] || exit 0
LINE="$STATUS_DIR/$PPID.line"
LOCK="$STATUS_DIR/$PPID.rendering"

# cs-statusline keys its per-conversation caches (tmux ancestry, the tmux
# client's theme and tty) on its parent pid, since Claude Code is the same
# parent for every render. Here its parent is this bridge, a new process
# each tick, so it is told the pid this bridge is the child of. Set per run
# on purpose: exported from a profile it would let any process claim the key.
export CS_STATUSLINE_PARENT="$PPID"

# Claude Code sends the bridge SIGTERM when the tick moves on, and nothing
# after it. Ignored, so a render in progress keeps its parent, and with it
# the parent chain the statusline reads its terminal's theme from.
trap '' TERM HUP INT

# The lock grants one writer, so the temp file needs no pid in its name:
# a render killed outright (something SIGKILLs every session's render in
# flight every 30 to 60 s, traced live 2026-09-16) leaves it behind, and
# the next render overwrites it instead of adding one more.
render_to_line() {
    printf '%s' "$input" | sh -c "$(cat "$ORIGINAL")" > "$LINE.tmp" 2>/dev/null \
        && mv -f "$LINE.tmp" "$LINE" 2>/dev/null || rm -f "$LINE.tmp" 2>/dev/null
    rmdir "$LOCK" 2>/dev/null
}

# One render at a time per session, and as few forks as possible on the
# way: under the load that makes renders overrun, each fork is a tenth of
# a second or more.
if [ -s "$LINE" ]; then
    # The last line at once, so this tick completes; then the next line,
    # if no other tick is already rendering it.
    cat "$LINE"
    if mkdir "$LOCK" 2>/dev/null; then
        render_to_line
    elif [ -n "$(find "$LOCK" -maxdepth 0 -mtime +10s 2>/dev/null)" ]; then
        # A render takes a second or two; a lock ten seconds old was left by
        # one that died. Without this the line would stay as it is for good.
        rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null && render_to_line
    fi
else
    # Nothing to show yet. A lock older than any render should take was
    # left by a process that died without cleaning up.
    if [ -d "$LOCK" ]; then
        now=$(date +%s); then_=$(stat -f %m "$LOCK" 2>/dev/null || echo 0)
        [ $((now - then_)) -gt 10 ] && rmdir "$LOCK" 2>/dev/null
    fi
    # Render, and show it. A tick that finds a render already going prints
    # nothing; the next one will have the line.
    if mkdir "$LOCK" 2>/dev/null; then
        render_to_line
        [ -s "$LINE" ] && cat "$LINE"
    fi
fi
