#!/bin/bash
# Cut a release: number it YYYY.M.BUILD, commit it on main, and publish it
# to the public mirror as one squashed, tagged commit.
#
# main carries the .cs/ session files and is never pushed. The mirror is a
# separate lineage on the local branch `public`: each release adds one commit
# there whose tree is main's tree minus .cs/, under the public identity. BUILD
# counts releases within the month, from the tags already on the mirror, so
# the number never needs a hand.
#
#   ./release.sh "What changed, in one line"
#
# It ends with a GitHub release page carrying that line and a compare link,
# made with gh; edit the page afterwards for longer notes.
#
# RELEASE_SCRUB, when set, is a space-separated list of words the public tree
# must not contain (names, hostnames); the release stops on a hit.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo"
summary="${1:-}"
[ -n "$summary" ] || { echo "usage: ./release.sh \"one-line summary\"" >&2; exit 1; }

public_name="hex"
public_email="88922+hex@users.noreply.github.com"
remote="github"

[ "$(git branch --show-current)" = "main" ] || { echo "error: release from main" >&2; exit 1; }
[ -z "$(git status --porcelain -- . ':!.cs')" ] || { echo "error: uncommitted changes" >&2; exit 1; }
git rev-parse -q --verify public >/dev/null || { echo "error: no local branch 'public'" >&2; exit 1; }

# The number: this month's count of tags on the mirror, plus one. The month
# has no leading zero; tags before 2026.9.43 had one, so both are counted.
month="$(date +%Y).$(( 10#$(date +%m) ))"
padded="$(date +%Y.%m)"
last="$( { git tag -l "v$month.*" | sed "s/^v$month\.//"
          git tag -l "v$padded.*" | sed "s/^v$padded\.//"; } | sort -n | tail -1)"
version="$month.$(( ${last:-0} + 1 ))"

echo "release $version"
python3 -m pytest -q

# The bump on main.
echo "$version" > VERSION
python3 - "$version" <<'PY'
import json, sys
path = "plugin/.claude-plugin/plugin.json"
manifest = json.load(open(path))
manifest["version"] = sys.argv[1]
json.dump(manifest, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY
git add VERSION plugin/.claude-plugin/plugin.json
git commit -q -m "Release $version

$summary"

# The public tree: main's, minus the session files, with the mirror's own
# .gitignore (which ignores .cs/ rather than carrying it).
index="$(mktemp)"
rm -f "$index"
export GIT_INDEX_FILE="$index"
git read-tree main
git rm -q --cached -r .cs
git update-index --cacheinfo "100644,$(git rev-parse public:.gitignore),.gitignore"
tree="$(git write-tree)"
unset GIT_INDEX_FILE
rm -f "$index"

# Nothing personal leaves the machine: real addresses (a domain, so that
# icon_16x16@2x.png passes), and the words the release runner names
# (fixtures use jane, john and x, so home paths pass).
leaks="$(git grep -n -I -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|org|net|io|dev|me|ro|eu|co|ai)\b' "$tree" -- . \
  | grep -v -E 'users\.noreply\.github\.com|example\.com' || true)"
for word in ${RELEASE_SCRUB:-}; do
  hits="$(git grep -n -I -i -w "$word" "$tree" -- . || true)"
  [ -z "$hits" ] || leaks="$leaks${leaks:+$'\n'}$hits"
done
if [ -n "$leaks" ]; then
  echo "error: the public tree carries something personal; fix on main and re-run:" >&2
  echo "$leaks" | sed "s|^$tree:|  |" >&2
  git reset -q --hard HEAD~1
  exit 1
fi

# The squashed commit, tested as the mirror will see it.
commit="$(GIT_AUTHOR_NAME="$public_name" GIT_AUTHOR_EMAIL="$public_email" \
          GIT_COMMITTER_NAME="$public_name" GIT_COMMITTER_EMAIL="$public_email" \
          git commit-tree "$tree" -p public -m "$version: $summary")"
check="$(mktemp -d)"
git worktree add -q --detach "$check" "$commit"
git -C "$check" checkout -q -b "release-check-$version"
( cd "$check" && python3 -m pytest -q )
git worktree remove --force "$check"
git branch -q -D "release-check-$version"

git branch -f public "$commit"
git tag -a "v$version" -m "$summary" "$commit"
git push -q "$remote" public:main "v$version"
echo "published $version as $(git rev-parse --short "$commit") -> $remote"

# The release page: the summary, and what changed since the release before.
# The tag is already public, so a page that fails says how to make it by hand.
previous="$(git describe --tags --abbrev=0 "$commit^")"
url="$(git remote get-url "$remote" | sed -e 's|\.git$||' -e 's|^git@github.com:|https://github.com/|')"
notes="$summary

**Full changelog**: $url/compare/$previous...v$version"
gh release create "v$version" --repo "$url" --verify-tag --title "$version" --notes "$notes" >/dev/null || {
  echo "error: v$version is pushed but has no release page; make it with:" >&2
  echo "  gh release create v$version --repo $url --verify-tag --title $version --notes-file <notes>" >&2
  exit 1
}
echo "release page: $url/releases/tag/v$version"
