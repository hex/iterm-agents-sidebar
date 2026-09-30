#!/bin/bash
# Installs the Agents sidebar in one line: clones the repository, then runs
# its install.sh. Arguments go to install.sh. An existing install is updated
# from the panel's Update button, which takes only signed releases; this
# script is fetched unsigned, so it never updates one.
#
#   curl -fsSL https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/get.sh | bash
#   curl -fsSL .../get.sh | bash -s -- --statusline
#
# AGENTS_SIDEBAR_DIR sets where the clone lives; AGENTS_SIDEBAR_REPO what it
# clones from.
set -euo pipefail

repo="${AGENTS_SIDEBAR_REPO:-https://github.com/hex/iterm-agents-sidebar.git}"
dir="${AGENTS_SIDEBAR_DIR:-$HOME/.local/share/agents-sidebar/src}"

command -v git >/dev/null || { echo "error: git is needed (xcode-select --install)" >&2; exit 1; }

if [ -d "$dir/.git" ]; then
  echo "error: already installed in $dir; update it with the panel's Update button," >&2
  echo "  or rerun its installer: $dir/install.sh" >&2
  exit 1
fi
echo "cloning into $dir"
git clone -q "$repo" "$dir"
exec "$dir/install.sh" "$@"
