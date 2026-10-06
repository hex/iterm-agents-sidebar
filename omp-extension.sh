#!/bin/bash
# ABOUTME: Installs or removes the Agents panel's extension in omp's agent directory, and says where that is.
# ABOUTME: Usage: omp-extension.sh <agents-sidebar.ts> <emit-state.py> <python3> | --remove | --where
#
# omp loads every .ts file in that directory into its own process, so this
# writes one file by its own name, by rename, and never a file whose third
# line is not the marker. The directory is the one omp itself reads
# (pi-utils/src/dirs.ts): a profile's when OMP_PROFILE (else PI_PROFILE)
# names one, else PI_CODING_AGENT_DIR, else ~/<PI_CONFIG_DIR or .omp>/agent.
set -euo pipefail

fail() { echo "error: $*" >&2; exit 1; }

# Line 3 of every installed extension is exactly this, and it is how a later
# install or --remove knows the file is ours, so it never changes: a different
# one would leave every installed file where it is. The ABOUTME lines above
# it may say anything.
MARKER="// agents-sidebar-omp-extension: written by the Agents panel's install.sh, which owns this file."

agent_dir() {
  local config="$HOME/${PI_CONFIG_DIR:-.omp}" profile
  # An OMP_PROFILE set but empty picks the default profile; it does not fall
  # through to PI_PROFILE.
  if [ "${OMP_PROFILE+set}" = set ]; then profile="$OMP_PROFILE"; else profile="${PI_PROFILE:-}"; fi
  profile="${profile#"${profile%%[![:space:]]*}"}"
  profile="${profile%"${profile##*[![:space:]]}"}"
  [ "$profile" = default ] && profile=""
  if [ -n "$profile" ]; then
    # omp refuses any other name, so no directory of ours could be the one it reads.
    if ! [[ "$profile" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || [[ "$profile" == *. ]]; then
      fail "\"$profile\" is not a profile name omp accepts; nothing written."
    fi
    printf '%s\n' "$config/profiles/$profile/agent"
  elif [ -n "${PI_CODING_AGENT_DIR:-}" ]; then
    (cd "$(dirname "$PI_CODING_AGENT_DIR")" 2>/dev/null && printf '%s/%s\n' "$(pwd)" "$(basename "$PI_CODING_AGENT_DIR")") \
      || printf '%s\n' "$PI_CODING_AGENT_DIR"
  else
    printf '%s\n' "$config/agent"
  fi
}

# Whether line 3 of the file at $1 is the marker; a link's never is.
marked() {
  [ -f "$1" ] && [ ! -L "$1" ] && [ "$(sed -n 3p "$1")" = "$MARKER" ]
}

case "${1:-}" in
  --where)
    agent_dir
    exit 0 ;;
  --remove)
    [ $# -eq 1 ] || fail "usage: omp-extension.sh --remove"
    target="$(agent_dir)/extensions/agents-sidebar.ts"
    if [ ! -e "$target" ] && [ ! -L "$target" ]; then exit 0; fi
    marked "$target" || fail "$target was not written by the Agents panel; left in place."
    rm -f "$target"
    printf '%s\n' "$target"
    exit 0 ;;
esac

[ $# -eq 3 ] || fail "usage: omp-extension.sh <agents-sidebar.ts> <emit-state.py> <python3>"
source_file="$1"; handler="$2"; python="$3"
[ -f "$handler" ] || fail "no state hook at $handler; nothing written."
[ -x "$python" ] || fail "$python cannot be run; nothing written."
marked "$source_file" || fail "line 3 of $source_file is not the marker $MARKER; nothing written."
dir="$(agent_dir)/extensions"
target="$dir/agents-sidebar.ts"
if [ -e "$target" ] || [ -L "$target" ]; then
  marked "$target" || fail "$target was not written by the Agents panel; left unchanged."
fi
mkdir -p "$dir"
python3 - "$source_file" "$dir" "$target" "$handler" "$python" <<'PY'
import json, os, sys, tempfile
source, directory, target, handler, python = sys.argv[1:]
text = open(source, encoding="utf-8").read()
# Filled in as JSON strings, so no path can end the literal it stands in.
for placeholder, value in (('"@AGENTS_SIDEBAR_HANDLER@"', handler), ('"@AGENTS_SIDEBAR_PYTHON@"', python)):
    if text.count(placeholder) != 1:
        sys.exit(f"error: {source} holds {placeholder} {text.count(placeholder)} times, not once; nothing written.")
    text = text.replace(placeholder, json.dumps(value))
# Staged under a name nobody can guess, created only if nothing holds it,
# so a link planted in the directory is never written through; and not
# named .ts, or omp would load a half-written one.
fd, temp = tempfile.mkstemp(prefix=".agents-sidebar.", suffix=".tmp", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(text)
    # mkstemp makes it 0600; the mode a plain write gives under this umask.
    umask = os.umask(0)
    os.umask(umask)
    os.chmod(temp, 0o666 & ~umask)
    os.replace(temp, target)
except BaseException:
    os.unlink(temp)
    raise
PY
printf '%s\n' "$target"
