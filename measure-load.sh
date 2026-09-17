#!/bin/bash
# ABOUTME: Counts what the machine executes over a few seconds: execs per second, by what ran
# ABOUTME: and by who ran it, with the load average and open sessions. Needs sudo for fs_usage.
#
# Usage: sudo ./measure-load.sh [seconds]      (10 by default)
#
# Every exec on this machine is inspected by the endpoint agents, so the exec
# rate is the figure that decides whether the panel's helpers are a burden:
# eight sessions at a one-second statusline tick reached ~200 execs/s and a
# load average of 48 on 2026-09-16. Run it with the sessions you usually keep
# open; the raw fs_usage lines are kept beside the report for a closer look.
set -euo pipefail

SECONDS_TO_WATCH="${1:-10}"
if [ "$(id -u)" -ne 0 ]; then
  echo "fs_usage needs root: sudo $0 $*" >&2
  exit 1
fi

REPORT_DIR="${TMPDIR:-/tmp}/agents-sidebar-load"
mkdir -p "$REPORT_DIR"
RAW="$REPORT_DIR/execs-$(date +%H%M%S).txt"

before=$(sysctl -n vm.loadavg | tr -d '{}' | awk '{print $1}')
sessions=$(pgrep -f '^[^ ]*/claude( |$)' | wc -l | tr -d ' ' || true)
codex=$(pgrep -f 'codex' | wc -l | tr -d ' ' || true)
echo "watching execs for ${SECONDS_TO_WATCH}s with $sessions claude and $codex codex processes; load $before"

# -w: the wide layout, which ends each line with the calling process and its
# pid. -f exec: exec and spawn events only. -t: stop by itself.
fs_usage -w -f exec -t "$SECONDS_TO_WATCH" > "$RAW" 2>/dev/null || true
after=$(sysctl -n vm.loadavg | tr -d '{}' | awk '{print $1}')

# A failed exec (a shell walking PATH for `git`) gets an errno column,
# `[  2]`, before the path. The kernel refuses those before a process
# exists, so they are counted apart from the execs that ran something.
failed() { grep -E '^\S+ +(execve|posix_spawn) +\[' "$RAW"; }
ran() { grep -E '^\S+ +(execve|posix_spawn) +[^[ ]' "$RAW"; }
total=$(ran | wc -l | tr -d ' ')
misses=$(failed | wc -l | tr -d ' ')
echo "execs: $total in ${SECONDS_TO_WATCH}s = $((total / SECONDS_TO_WATCH))/s, plus $misses PATH misses; load $before -> $after"
echo
echo "what ran (top 15, by the executed path's name):"
ran | sed -E 's/^[0-9:.]+ +(execve|posix_spawn) +//; s/ {2,}.*//' | awk -F/ '{print $NF}' | sort | uniq -c | sort -rn | head -15
echo
echo "who ran it (top 15, the calling process):"
ran | awk '{print $NF}' | sed -E 's/\.[0-9]+$//' | sort | uniq -c | sort -rn | head -15
echo
echo "who missed (top 5, callers whose PATH walk failed):"
failed | awk '{print $NF}' | sed -E 's/\.[0-9]+$//' | sort | uniq -c | sort -rn | head -5
echo
echo "raw lines: $RAW"
