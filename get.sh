#!/bin/bash
# Installs the Agents sidebar in one line: clones the repository, or pulls it
# if it is already there, then runs its install.sh. Arguments go to install.sh.
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
  echo "updating $dir"
  git -C "$dir" pull -q --ff-only
else
  echo "cloning into $dir"
  git clone -q "$repo" "$dir"
fi
exec "$dir/install.sh" "$@"
