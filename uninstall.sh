#!/bin/bash
# Take the sidebar out again: everything install.sh put in place, and the
# panel's own data. The Claude logins the panel copied go with it; a login
# store with nothing reading it is a liability, not a convenience. What is
# left: the .before-agents-sidebar backups, and the writable_roots line in
# Codex's config.toml, which is the same TOML edit we refuse to guess at on
# the way in.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -eq 0 ] || { echo "usage: ./uninstall.sh" >&2; exit 1; }

if [ -t 1 ]; then green=$'\e[32m'; yellow=$'\e[33m'; dim=$'\e[2m'; off=$'\e[0m'; else green=""; yellow=""; dim=""; off=""; fi
tilde() { printf '%s' "${1/#$HOME/~}"; }
line() { printf '  %s %s%-11s%s %s\n' "$1" "$dim" "$2" "$off" "$3"; }
ok()   { line "${green}✓${off}" "$1" "$2"; }
skip() { line "${dim}-${off}" "$1" "$2"; }
warn() { line "${yellow}!${off}" "$1" "$2" >&2; }
next=()

printf '\n%sAgents sidebar%s removing%s\n\n' "$off" "$dim" "$off"

# The daemon: nothing relaunches it, so stopping the python process is the end
# of it. Only the process running our stub, never the wrapper iTerm2 put
# around it (the wrapper exits with its child).
stub="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/agents_sidebar.py"
stopped=0
for pid in $(pgrep -f "$stub" || true); do
  case "$(ps -o comm= -p "$pid" 2>/dev/null)" in
    *python*) kill "$pid" 2>/dev/null && stopped=1 ;;
  esac
done
if [ -f "$stub" ]; then
  rm -f "$stub"
  ok script "$(tilde "$stub") removed$([ $stopped = 1 ] && echo ', daemon stopped')"
else
  skip script "not installed"
fi
next+=("Close the panel: View > Toolbelt > Agents, or restart iTerm2 to drop the tool.")

plugin_dir="$HOME/.claude/skills/agents-sidebar"
if [ -d "$plugin_dir" ]; then
  rm -rf "$plugin_dir"
  if command -v claude >/dev/null 2>&1; then
    claude plugin disable agents-sidebar@skills-dir >/dev/null 2>&1 || true
  fi
  ok hook "$(tilde "$plugin_dir") removed"
else
  skip hook "not installed"
fi

# Only the statusLine key goes back to what it was; the rest of settings.json
# is whatever it is now, edits since the install included.
settings="$HOME/.claude/settings.json"
status_dir="$HOME/.claude/agents-sidebar-status"
bridge="$repo/plugin/statusline-bridge.sh"
if [ -f "$settings" ]; then
  restored=$(python3 - "$settings" "$bridge" "$status_dir/original-statusline" <<'PY'
import json, os, sys
path, bridge, original = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    settings = json.load(open(path))
except ValueError:
    sys.exit("not valid JSON; left unchanged")
line = settings.get("statusLine") or {}
if line.get("command") != bridge:
    print("not ours; left alone")
    sys.exit(0)
previous = open(original).read() if os.path.exists(original) else ""
if previous:
    line["command"] = previous
    settings["statusLine"] = line
    print("your statusline is back: " + previous)
else:
    del settings["statusLine"]
    print("statusLine removed; there was none before")
with open(path, "w") as out:
    json.dump(settings, out, indent=2)
    out.write("\n")
PY
  ) && ok statusline "$restored" || warn statusline "$restored"
else
  skip statusline "no settings.json"
fi

codex_hooks="$HOME/.codex/hooks.json"
if [ -f "$codex_hooks" ]; then
  bash "$repo/codex-hooks.sh" --remove "$codex_hooks" "$plugin_dir/hooks-handlers/emit-state.py"
  ok codex "our entries out of $(tilde "$codex_hooks")"
  if grep -q "agents-sidebar-tasks" "$HOME/.codex/config.toml" 2>/dev/null; then
    next+=("Codex's config.toml still lists ~/.claude/agents-sidebar-tasks under writable_roots; harmless, remove it by hand if you like.")
  fi
else
  skip codex "nothing registered"
fi

notifier="$HOME/.local/share/agents-sidebar/Agents.app"
if [ -d "$notifier" ]; then
  rm -rf "$notifier"
  ok notifier "$(tilde "$notifier") removed"
else
  skip notifier "not installed"
fi

# The panel's own data: settings, the state the hooks kept, and the account
# store with the Keychain items behind it.
store="$HOME/.config/agents-sidebar/accounts.json"
items=0
if [ -f "$store" ]; then
  items=$(python3 - "$store" <<'PY'
import json, subprocess, sys
try:
    accounts = json.load(open(sys.argv[1])).get("accounts", [])
except (ValueError, AttributeError):
    accounts = []
removed = 0
for account in accounts:
    for item in (account["id"], account["id"] + ".login"):
        gone = subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", item,
                               "-s", "agents-sidebar-accounts"], capture_output=True)
        removed += gone.returncode == 0
print(removed)
PY
  )
fi
# Not ~/.local/share/agents-sidebar itself: the one-line install keeps its
# checkout in there, and this script may be running from it.
rm -rf "$HOME/.config/agents-sidebar" "$status_dir" "$HOME/.claude/agents-sidebar-subagents" \
       "$HOME/.claude/agents-sidebar-tasks"
rm -f "$HOME/.claude/agents-sidebar-settings.json"
ok data "settings, state and the account store removed$([ "$items" -gt 0 ] && echo ", $items Keychain items with them")"

printf '\nNext\n'
for item in "${next[@]}"; do printf '  %s\n' "$item"; done
printf '  The checkout at %s is yours to delete.\n' "$(tilde "$repo")"
[ -f "$settings.before-agents-sidebar" ] && printf '  %s\n' "Kept: $(tilde "$settings").before-agents-sidebar and $(tilde "$codex_hooks").before-agents-sidebar, the files as they were before the first install."
exit 0
