#!/bin/bash
# ABOUTME: Removes the panel's installed files and its own settings and data.
# ABOUTME: Drops a saved statusline when its absolute script path is missing.
# Take the sidebar out again: everything install.sh put in place, and the
# panel's own data. The Claude logins the panel copied go with it unless
# --keep-accounts keeps the store and its Keychain items. What is
# left: the .before-agents-sidebar backups, and the writable_roots line in
# Codex's config.toml, which is the same TOML edit we refuse to guess at on
# the way in.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
keep_accounts=0
if [ $# -eq 1 ] && [ "$1" = --keep-accounts ]; then
  keep_accounts=1
elif [ $# -ne 0 ]; then
  echo "usage: ./uninstall.sh [--keep-accounts]" >&2
  exit 1
fi

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
import json, os, re, shlex, sys
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
missing = None
if previous:
    try:
        words = shlex.split(previous, comments=True)
    except ValueError as error:
        sys.exit(f"cannot read saved statusline: {error}; left unchanged")
    script = words[0] if words else ""
    interpreter = (len(words) > 1 and
                   re.fullmatch(r"(?:ba|z)?sh|python[0-9.]*|node|ruby|perl", os.path.basename(script)) and
                   not words[1].startswith("-"))
    if interpreter:
        script = words[1]
    expanded = os.path.expandvars(os.path.expanduser(script))
    if os.path.isabs(expanded) and not os.path.exists(script) and not os.path.exists(expanded):
        missing = script
        del settings["statusLine"]
        print("statusLine removed; missing script: " + missing)
    else:
        line["command"] = previous
        settings["statusLine"] = line
        print("your statusline is back: " + previous)
else:
    del settings["statusLine"]
    print("statusLine removed; there was none before")
with open(path, "w") as out:
    json.dump(settings, out, indent=2)
    out.write("\n")
sys.exit(1 if missing else 0)
PY
  ) && ok statusline "$restored" || warn statusline "$restored"
else
  skip statusline "no settings.json"
fi

# The API fallback's apiKeyHelper, only while it is exactly the command this
# checkout runs for one of the stored accounts, or the one the fallback's
# record says the daemon wrote.
if [ -f "$settings" ]; then
  said=$(python3 -I -c '
import json
import sys
sys.path.insert(0, sys.argv[1])
import accounts
import statusline
path, helper, record, store = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
try:
    ids = [account["id"] for account in accounts.load_store(store)]
except accounts.StoreError:
    ids = []
ours = {statusline.helper_command(helper, ident) for ident in ids if accounts.is_account_id(ident)}
try:
    written = json.load(open(record, encoding="utf-8")).get("command")
except (OSError, ValueError, AttributeError):
    written = None
if isinstance(written, str):
    ours.add(written)
state = statusline.api_key_helper_state(path, ours)
if state == "ours":
    try:
        statusline.drop_api_key_helper(path, ours)
    except ValueError as refusal:
        print(refusal)
        sys.exit(2)
    print("apiKeyHelper taken out of ~/.claude/settings.json")
    sys.exit(0)
print("apiKeyHelper is not the panel'"'"'s; left alone" if state == "foreign" else
      "settings.json unreadable; apiKeyHelper left alone" if state == "unreadable" else "no apiKeyHelper set")
sys.exit(3 if state != "unreadable" else 2)
' "$repo" "$settings" "$repo/api-key-helper.sh" "$HOME/.claude/agents-sidebar-status/api-fallback.json" \
    "$HOME/.config/agents-sidebar/accounts.json" 2>&1) && outcome=0 || outcome=$?
  case "$outcome" in
    0) ok "api key" "$said" ;;
    3) skip "api key" "$said" ;;
    *) warn "api key" "$said" ;;
  esac
fi

# iTerm2's line under the selected tab, where tab-underline.json says the panel
# set it to 0: back to what was there, unless it changed since. `defaults`
# ignores HOME, so AGENTS_SIDEBAR_ITERM_PREFS names another domain for tests.
underline="$status_dir/tab-underline.json"
iterm_prefs="${AGENTS_SIDEBAR_ITERM_PREFS:-com.googlecode.iterm2}"
# The record survives a refused put back: it alone holds what goes back, and
# it is where another uninstall, or a reinstalled daemon, looks for it.
keep_underline=0
if [ -f "$underline" ]; then
  said=$(python3 - "$underline" "$iterm_prefs" <<'PY'
import json, re, subprocess, sys
path, domain = sys.argv[1], sys.argv[2]
key = "MinimalSelectedTabUnderlineProminence"
flags = {"float": "-float", "string": "-string", "integer": "-int", "boolean": "-bool"}
def leave(text, code):
    print(text)
    sys.exit(code)
def defaults(*words):
    done = subprocess.run(["/usr/bin/defaults", *words], capture_output=True, text=True)
    text = " ".join(line.strip() for line in done.stderr.splitlines() if line.strip())
    complaint = re.sub(r"^\S+ \S+ defaults\[[\d:]+\]\s*", "", text) or "nothing"
    return done.returncode, done.stdout[:-1] if done.stdout.endswith("\n") else done.stdout, complaint
try:
    record = json.load(open(path))
    kept = None if record == {"aside": True} else record["kept"]
    if kept is not None and (kept.get("type") not in flags or not isinstance(kept.get("value"), str)):
        raise ValueError(f"kept {kept!r}")
except (ValueError, KeyError, TypeError, AttributeError) as error:
    leave(f"{path} unreadable: {error}; left as it is", 1)
if record == {"aside": True}:
    leave("yours while the tab tint was on; left as it is", 3)
code, now, _ = defaults("read", domain, key)
try:
    zero = code == 0 and float(now) == 0
except ValueError:
    zero = False
if not zero:
    leave("changed since the panel hid it; left as it is", 3)
if kept is None:
    verb, code, _, complaint = "delete", *defaults("delete", domain, key)
else:
    value = {"1": "true", "0": "false"}.get(kept["value"], kept["value"]) if kept["type"] == "boolean" else kept["value"]
    verb, code, _, complaint = "write", *defaults("write", domain, key, flags[kept["type"]], value)
if code:
    leave(f"defaults {verb} said {complaint}", 2)
leave("iTerm2's line under the selected tab is back", 0)
PY
  ) && outcome=0 || outcome=$?
  case "$outcome" in
    0) ok underline "$said" ;;
    2) keep_underline=1
       warn underline "still hidden, and $(tilde "$underline") kept, so running uninstall again tries again; $said" ;;
    3) skip underline "$said" ;;
    *) warn underline "$said" ;;
  esac
else
  skip underline "not hidden by the panel"
fi

# omp's extension, only while it is the file we wrote.
if removed=$(bash "$repo/omp-extension.sh" --remove 2>&1); then
  if [ -n "$removed" ]; then ok omp "$(tilde "$removed") removed"; else skip omp "not installed"; fi
else
  warn omp "${removed#error: }"
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

# Only a link to this checkout's command: another checkout's, or a file of
# the same name, is not ours to take.
command_link="$HOME/.local/bin/agents-sidebar"
if [ -L "$command_link" ] && [ "$(readlink "$command_link")" = "$repo/agents-sidebar" ]; then
  rm -f "$command_link"
  ok command "$(tilde "$command_link") removed"
else
  skip command "not installed from here"
fi

notifier="$HOME/.local/share/agents-sidebar/Agents.app"
if [ -d "$notifier" ]; then
  rm -rf "$notifier"
  ok notifier "$(tilde "$notifier") removed"
else
  skip notifier "not installed"
fi

# The panel's own data: settings, the state the hooks kept, and the account
# store with the Keychain items behind it: each stored account's login, its
# `.login` block and its API key, api-key:<account id>. The item named plain
# api-key belongs to another launcher and stays. Every deletion names the
# keychain AGENTS_SIDEBAR_KEYCHAIN gives, the tests' own; `security` given a
# path that does not exist looks in the login keychain, so one that is named
# and missing deletes nothing at all.
store="$HOME/.config/agents-sidebar/accounts.json"
items=0
keychain=${AGENTS_SIDEBAR_KEYCHAIN:-}
if [ "$keep_accounts" = 0 ] && [ -f "$store" ]; then
  if [ -n "$keychain" ] && [ ! -f "$keychain" ]; then
    warn accounts "keychain not found at $keychain; logins and keys left alone"
  else
    items=$(python3 - "$store" "$keychain" <<'PY'
import json, subprocess, sys
try:
    accounts = json.load(open(sys.argv[1])).get("accounts", [])
except (ValueError, AttributeError):
    accounts = []
named = [sys.argv[2]] if sys.argv[2] else []
removed = 0
for account in accounts:
    for item in (account["id"], account["id"] + ".login"):
        gone = subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", item,
                               "-s", "agents-sidebar-accounts", *named], capture_output=True)
        removed += gone.returncode == 0
print(removed)
PY
    )
    keys=$(python3 -I - "$repo" "$store" "$keychain" <<'PY'
import subprocess, sys
sys.path.insert(0, sys.argv[1])
import accounts
try:
    ids = [account["id"] for account in accounts.load_store(sys.argv[2])]
except accounts.StoreError:
    ids = []
named = [sys.argv[3]] if sys.argv[3] else []
removed = 0
for ident in ids:
    if not accounts.is_account_id(ident):
        continue
    gone = subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", "api-key:" + ident,
                           "-s", "agents-sidebar-accounts", *named], capture_output=True)
    removed += gone.returncode == 0
print(removed)
PY
    )
    if [ "$keys" -gt 0 ]; then ok "api key" "$keys API keys deleted"; else skip "api key" "no API key stored"; fi
  fi
fi
# Not ~/.local/share/agents-sidebar itself: the one-line install keeps its
# checkout in there, and this script may be running from it.
if [ "$keep_accounts" = 1 ] && [ -f "$store" ]; then
  find "$HOME/.config/agents-sidebar" -mindepth 1 -maxdepth 1 ! -name accounts.json -exec rm -rf {} +
  ok accounts "logins kept in $(tilde "$store") and the Keychain"
else
  rm -rf "$HOME/.config/agents-sidebar"
  [ "$keep_accounts" = 0 ] || skip accounts "no logins stored at $(tilde "$store"); Keychain left alone"
fi
if [ "$keep_underline" = 1 ]; then
  find "$status_dir" -mindepth 1 -maxdepth 1 ! -name tab-underline.json -exec rm -rf {} +
else
  rm -rf "$status_dir"
fi
rm -rf "$HOME/.claude/agents-sidebar-subagents" \
       "$HOME/.claude/agents-sidebar-tasks" "$HOME/.claude/agents-sidebar-links"
rm -f "$HOME/.claude/agents-sidebar-settings.json" "$HOME/.local/share/agents-sidebar/endpoint.json"
if [ "$keep_accounts" = 1 ]; then
  ok data "settings and state removed"
else
  ok data "settings, state and the account store removed$([ "$items" -gt 0 ] && echo ", $items Keychain items with them")"
fi

printf '\nNext\n'
for item in "${next[@]}"; do printf '  %s\n' "$item"; done
printf '  The checkout at %s is yours to delete.\n' "$(tilde "$repo")"
[ -f "$settings.before-agents-sidebar" ] && printf '  %s\n' "Kept: $(tilde "$settings").before-agents-sidebar and $(tilde "$codex_hooks").before-agents-sidebar, the files as they were before the first install."
exit 0
