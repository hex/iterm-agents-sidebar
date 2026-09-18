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

# Diagnosis only, and off unless a path is set: what a tick did and when.
# The question it exists to answer is whether a render that never finished
# was killed or was merely slow -- a render-start with no render-end is a
# render that died. Tracing forks a date per event, which is why it is not
# the normal path; compare two arms both traced, never a traced arm against
# an untraced one.
TRACE="${AGENTS_SIDEBAR_BRIDGE_TRACE:-}"
if [ -n "$TRACE" ]; then
    trace() {
        printf '%s pid=%s ppid=%s %s %s\n' \
            "$(date +%s.%N 2>/dev/null || date +%s)" "$$" "$PPID" "$1" "${2:-}" \
            >> "$TRACE" 2>/dev/null
    }
else
    # No fork, no file, no test per event: the cost of tracing when it is off
    # is this definition and nothing else.
    trace() { :; }
fi

# Builtins wherever a builtin will do. Traced 2026-09-17 with eight sessions
# rendering once a second: the bridge's own forks per tick, before the user's
# statusline ran, were most of ~200 execs a second, each inspected by an
# endpoint agent, and the machine saturated on that alone.
IFS= read -r -d '' input
trace entry

# Publish, but never at the cost of the statusline. An unwritable directory
# or a full disk must still end with the user's statusline on screen.
#
# The payload goes down whole, as it came: the daemon reads the fields it
# wants. Cheap on purpose. Claude Code runs this every tick in every
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
    [ -d "$STATUS_DIR" ] || mkdir -p "$STATUS_DIR" 2>/dev/null || return 0

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
# Claude Code runs this every tick and kills a render still going when the
# next tick comes. A statusline that takes most of a tick, in eight
# sessions at once, then never completes, and a new session never gets a
# line at all. So the line rendered last is printed at once and the next one
# is rendered after it, by this process, which ignores the TERM above and so
# outlives the tick. The line shown is one tick behind, which nobody can see.
#
# This process waits for every render it starts and never walks away from
# one. cs-statusline chooses its light or dark palette by walking its parent
# pids up to the tmux server; a render started and left is orphaned to
# launchd when the bridge exits, fails that walk, and paints the dark palette
# against a light terminal. Tried 2026-09-18 for the faster tick it buys, and
# reverted the same day when the statusline came back dark.
[ -s "$ORIGINAL" ] || exit 0
IFS= read -r -d '' command < "$ORIGINAL"
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
    trace render-start
    # The status is taken here and nowhere else: read after the move it is
    # the move's, or the removal's, and a render that died reads as rc=0.
    local rc=0
    printf '%s' "$input" | sh -c "$command" > "$LINE.tmp" 2>/dev/null || rc=$?
    if [ "$rc" -eq 0 ]; then
        mv -f "$LINE.tmp" "$LINE" 2>/dev/null || rm -f "$LINE.tmp" 2>/dev/null
    else
        rm -f "$LINE.tmp" 2>/dev/null
    fi
    # A render-start with no render-end after it was killed outright.
    trace render-end "rc=$rc"
    rmdir "$LOCK" 2>/dev/null
}

# The render, in a process group of its own, with this tick waiting on it.
#
# Both halves matter. Traced live on Claude Code 2.1.276, 2026-09-18: a run
# still going about two seconds after it began is SIGKILLed, group and all.
# TERM is ignored above but nothing ignores KILL, so a render slower than
# that died with the bridge, its line never landed, and the lock it left
# stopped every other render for ten seconds: 4 renders of 12 lost, and the
# line 24 and then 39 seconds stale, on an idle machine. In its own group
# the render is out of the kill's reach. It lands its line and gives the
# lock back whether or not this process lives to see it.
#
# And the tick waits, rather than walking away, because cs-statusline picks
# its palette by walking its parent pids up to the tmux server as it starts.
# While this process waits that chain is whole. A render started and left is
# orphaned to launchd at once, fails the walk and paints dark; by the time a
# kill orphans this one, the walk is long done. `set -m` is what gives a
# background job its own group, with no fork to pay for it.
render_in_own_group() {
    set -m
    ( render_to_line ) </dev/null >/dev/null 2>&1 &
    set +m
    wait $!
    # Reached only by a bridge that was not killed while it waited.
    trace tick-end
}

# One render at a time per session, and as few forks as possible on the
# way: under the load that makes renders overrun, each fork is a tenth of
# a second or more.
if [ -s "$LINE" ]; then
    # The last line at once, so this tick completes; then the next line,
    # if no other tick is already rendering it.
    IFS= read -r -d '' line < "$LINE"
    printf '%s' "$line"
    trace warm-printed
    if mkdir "$LOCK" 2>/dev/null; then
        trace lock-taken
        render_in_own_group
    elif [ -n "$(find "$LOCK" -maxdepth 0 -mtime +10s 2>/dev/null)" ]; then
        trace lock-stale
        # A render takes a second or two; a lock ten seconds old was left by
        # one that died. Without this the line would stay as it is for good.
        rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null && render_in_own_group
    else
        trace lock-held
    fi
else
    # Nothing to show yet. A lock older than any render should take was
    # left by a process that died without cleaning up.
    trace cold
    if [ -d "$LOCK" ]; then
        now=$(date +%s); then_=$(stat -f %m "$LOCK" 2>/dev/null || echo 0)
        trace cold-lock-age "age=$((now - then_))"
        [ $((now - then_)) -gt 10 ] && rmdir "$LOCK" 2>/dev/null
    fi
    # Render, and show it. A tick that finds a render already going prints
    # nothing; the next one will have the line.
    #
    # This one waits, where the tick above does not, and that asymmetry is
    # deliberate. The trap above means this bridge is not killed while it
    # renders, so waiting costs this session nothing it would not pay
    # anyway; and a session whose settings leave refreshInterval alone is
    # rendered on events, not on a timer, so a tick that showed nothing
    # here would leave the bar blank until the user typed.
    if mkdir "$LOCK" 2>/dev/null; then
        trace lock-taken
        render_in_own_group
        if [ -s "$LINE" ]; then
            IFS= read -r -d '' line < "$LINE"; printf '%s' "$line"
            trace cold-printed
        else
            trace cold-blank
        fi
    else
        trace cold-lock-held
    fi
fi
