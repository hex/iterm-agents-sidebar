#!/bin/bash
# ABOUTME: Registers the Agents panel state hook in a Codex hooks.json.
# ABOUTME: Usage: codex-hooks.sh <hooks.json> <emit-state.py>; keeps every entry it did not write.
#
# Other tools write this file too (herdr registers its own SessionStart entry),
# so entries are replaced only when their command runs this handler, and a
# file that is not valid JSON is never overwritten.
set -euo pipefail

hooks="$1"
handler="$2"

command -v jq >/dev/null 2>&1 || { echo "error: registering Codex hooks needs jq." >&2; exit 1; }

if [ -f "$hooks" ]; then
  if ! jq -e 'type == "object"' "$hooks" >/dev/null 2>&1; then
    echo "error: $hooks is not valid JSON; left unchanged." >&2
    exit 1
  fi
  current=$(cat "$hooks")
else
  current='{}'
fi

tmp=$(mktemp)
jq --arg handler "$handler" --arg quote "'" '
  def ours: .hooks | any(.command | contains($handler));
  reduce ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
          "PostToolUse", "Stop", "SessionEnd") as $event
    (.;
     .hooks[$event] = ([(.hooks[$event] // [])[] | select(ours | not)]
                       + [{hooks: [{type: "command", timeout: 10,
                                    command: "python3 \($quote)\($handler)\($quote) \($event) --codex"}]}]))
' <<<"$current" > "$tmp"
mv "$tmp" "$hooks"
