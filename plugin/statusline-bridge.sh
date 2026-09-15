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

# Publish, but never at the cost of the statusline. A missing jq, an unwritable
# directory or a full disk must all end with the user's statusline on screen.
publish() {
    local pid="$PPID"
    case "$pid" in ''|*[!0-9]*) return 0 ;; esac
    command -v jq >/dev/null 2>&1 || return 0
    mkdir -p "$STATUS_DIR" 2>/dev/null || return 0

    # Written whole and moved into place: the sidebar reads this file on a
    # timer and must never catch a half-written one.
    local tmp="$STATUS_DIR/$pid.json.$$"
    # Kept rather than the whole payload. transcript_path earns its place: a
    # subagent's pane title carries its type, and the name Claude Code shows
    # for it lives only in its own transcript.
    if printf '%s' "$input" | jq -c '{
            context_window: (.context_window // {}),
            model: (.model // {}),
            effort: (.effort // {}),
            cost: (.cost // {}),
            rate_limits: (.rate_limits // {}),
            prompt_cache: (.prompt_cache // {}),
            thinking: (.thinking // {}),
            output_style: (.output_style // {}),
            fast_mode: .fast_mode,
            exceeds_200k_tokens: .exceeds_200k_tokens,
            version: .version,
            session_id: (.session_id // null),
            session_name: (.session_name // null),
            transcript_path: (.transcript_path // null),
            cwd: (.workspace.current_dir // .cwd // null)
        }' > "$tmp" 2>/dev/null; then
        mv -f "$tmp" "$STATUS_DIR/$pid.json" 2>/dev/null || rm -f "$tmp" 2>/dev/null
    else
        rm -f "$tmp" 2>/dev/null
    fi
}

publish

# Hand stdin to whatever was configured before the sidebar took this slot. An
# empty file means there was nothing to displace, and the statusline is ours
# alone to leave blank.
if [ -s "$ORIGINAL" ]; then
    printf '%s' "$input" | exec sh -c "$(cat "$ORIGINAL")"
fi
