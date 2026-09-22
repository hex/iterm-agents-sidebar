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

python3 - "$hooks" "$handler" <<'PY'
import json, os, sys
path, handler = sys.argv[1], sys.argv[2]
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
          "PostToolUse", "Stop", "SessionEnd")
if os.path.exists(path):
    try:
        current = json.load(open(path))
    except ValueError:
        current = None
    if not isinstance(current, dict):
        sys.exit(f"error: {path} is not valid JSON; left unchanged.")
else:
    current = {}
before = json.dumps(current, indent=2)
hooks = current.setdefault("hooks", {})
ours = lambda h: handler in h.get("command", "")
for event in EVENTS:
    kept = []
    for entry in hooks.get(event, []):
        # Only our command leaves an entry; whatever else it holds stays.
        rest = [h for h in entry.get("hooks", []) if not ours(h)]
        if rest:
            kept.append({**entry, "hooks": rest})
    kept.append({"hooks": [{"type": "command", "timeout": 10,
                            "command": f"python3 '{handler}' {event} --codex"}]})
    hooks[event] = kept
after = json.dumps(current, indent=2)
if after != before or not os.path.exists(path):
    with open(path, "w") as out:
        out.write(after + "\n")
PY
