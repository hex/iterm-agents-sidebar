#!/bin/bash
# ABOUTME: Claude Code's apiKeyHelper while the panel runs sessions on API credits: prints the key kept in the
# ABOUTME: Keychain for the account it names, and takes itself out of settings.json when its daemon is gone or the key unreadable.
set -euo pipefail

# The account whose key to print, in the store's id format and nothing else: it
# names a Keychain item and is passed on as one word, never run.
if [[ $# -ne 1 || ! $1 =~ ^acct-[0-9]+$ ]]; then
  echo "api-key-helper.sh: expected one account id like acct-1" >&2
  exit 2
fi
account=$1

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# The tests name files of their own through these; unset, they are the real ones.
keychain=${AGENTS_SIDEBAR_KEYCHAIN:-}
endpoint=${AGENTS_SIDEBAR_ENDPOINT:-$HOME/.local/share/agents-sidebar/endpoint.json}
settings=${AGENTS_SIDEBAR_CLAUDE_SETTINGS:-$HOME/.claude/settings.json}
status_dir=${AGENTS_SIDEBAR_STATUS_DIR:-$HOME/.claude/agents-sidebar-status}
autolaunch=${AGENTS_SIDEBAR_AUTOLAUNCH:-$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/agents_sidebar.py}

# Whether `command`, a process's whole command line, ends in this checkout's
# daemon: its own sidebar.py, or the AutoLaunch stub that loads it. Compared as
# files, because iTerm2 names the stub by a path other than the one it has here.
runs_this_daemon() {
  local rest=$1
  while [[ $rest == *" "* ]]; do
    rest=${rest#* }
    [[ -f $rest ]] || continue
    [[ $rest -ef $here/sidebar.py ]] && return 0
    if [[ $rest -ef $autolaunch ]] &&
      grep -qxF "runpy.run_path(\"$here/sidebar.py\", run_name=\"__main__\")" "$autolaunch"; then
      return 0
    fi
  done
  return 1
}

# The daemon the endpoint names, alive and running this checkout. Only its
# pid is read from the file.
daemon_alive() {
  local pid
  pid=$(/usr/bin/plutil -extract pid raw -o - "$endpoint" 2>/dev/null) || return 1
  [[ $pid =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  runs_this_daemon "$(/bin/ps -p "$pid" -o command= 2>/dev/null)"
}

# Take this helper out of settings.json and leave the marker that tells the
# daemon's next start the helper did it, not another tool. Neither step may
# change how the turn in flight ends.
step_aside() {
  mkdir -p "$status_dir" && : > "$status_dir/api-fallback-orphaned" || true
  python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import statusline; statusline.drop_api_key_helper(sys.argv[2], [statusline.helper_command(sys.argv[3], sys.argv[4])])' \
    "$here" "$settings" "$here/api-key-helper.sh" "$account" || true
}

# With no key to print the turn fails either way; the next one runs on the subscription.
if ! key=$(/usr/bin/security find-generic-password -s agents-sidebar-accounts -a "api-key:$account" -w ${keychain:+"$keychain"}); then
  step_aside
  exit 1
fi

# Which account's key this Claude Code process took, and when: the daemon
# blames a key only for a failure in a session that took it. Claude Code runs
# the helper as its own child, so the parent's pid names the session. A note
# that cannot be written never stops the key from being handed out.
{ mkdir -p "$status_dir/api-key-fetches" &&
  printf '%s %s\n' "$(date +%s)" "$account" >> "$status_dir/api-key-fetches/$PPID"; } 2>/dev/null || true

printf '%s\n' "$key"
daemon_alive && exit 0

# With the daemon down nothing enforces the spend cap, so this is the last key
# handed out: the turn in flight completes, and the next fetch finds no helper
# and runs on the subscription.
step_aside
exit 0
