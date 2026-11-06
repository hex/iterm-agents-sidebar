// ABOUTME: Tests for the git reads a review's turn may run against the asker's folder: the brief's own commands,
// ABOUTME: the folder quoted or bare, and every shape of call that is not one read of that folder.
import { expect, test } from 'claude-code/testing'
import { isGitRead } from './review-reads'

const cases: [string, string | null, string, boolean][] = [
  ['the brief’s status', '/work/a', "git -C '/work/a' status", true],
  ['the brief’s diff', '/work/a', "git -C '/work/a' diff HEAD", true],
  ['the brief’s log', '/work/a', "git -C '/work/a' log --oneline -10", true],
  ['the brief’s status, a folder with a space', '/work/my app', "git -C '/work/my app' status", true],
  ['the brief’s diff, a folder with a space', '/work/my app', "git -C '/work/my app' diff HEAD", true],
  ['the brief’s log, a folder with a space', '/work/my app', "git -C '/work/my app' log --oneline -10", true],
  ['a folder with a quote, quoted as the brief quotes it', "/work/it's", `git -C '/work/it'"'"'s' status`, true],
  ['a bare folder with no space', '/work/a', 'git -C /work/a status', true],
  ['a bare folder with a space', '/work/my app', 'git -C /work/my app status', false],
  ['a bare folder that would glob', '/work/a*', 'git -C /work/a* status', false],
  ['a quoted path after --', '/work/a', "git -C '/work/a' diff HEAD -- 'a b.txt'", true],
  ['a revision range', '/work/a', "git -C '/work/a' log --oneline HEAD~3..HEAD", true],
  ['a file at a commit', '/work/a', "git -C '/work/a' show HEAD:src/a.ts", true],
  ['each other read', '/work/a', "git -C '/work/a' ls-files", true],
  ['rev-parse', '/work/a', "git -C '/work/a' rev-parse --abbrev-ref HEAD", true],
  ['a branch listing', '/work/a', "git -C '/work/a' branch -a -v", true],
  ['the current branch', '/work/a', "git -C '/work/a' branch --show-current", true],
  ['another folder', '/work/a', "git -C '/work/other' status", false],
  ['a folder that starts with the asker’s', '/work/a', "git -C '/work/ab' status", false],
  ['a subfolder of the asker’s', '/work/a', "git -C '/work/a'/sub status", false],
  ['no folder known', null, "git -C '/work/a' status", false],
  ['a push', '/work/a', "git -C '/work/a' push", false],
  ['a commit', '/work/a', "git -C '/work/a' commit -m x", false],
  ['a branch made', '/work/a', "git -C '/work/a' branch fix", false],
  ['a branch deleted', '/work/a', "git -C '/work/a' branch -D main", false],
  ['a second command after ;', '/work/a', "git -C '/work/a' status; rm -rf x", false],
  ['a second command after &&', '/work/a', "git -C '/work/a' status && rm -rf x", false],
  ['a second command on a new line', '/work/a', "git -C '/work/a' status\nrm -rf x", false],
  ['a pipe', '/work/a', "git -C '/work/a' log | tee x", false],
  ['a redirect', '/work/a', "git -C '/work/a' diff HEAD > x", false],
  ['a substitution', '/work/a', "git -C '/work/a' show $(rm x)", false],
  ['a cd into the folder', '/work/a', "cd '/work/a' && git status", false],
  ['a bare cd into the folder', '/work/a', 'cd /work/a && git status', false],
  ['git without -C', '/work/a', 'git status', false],
  ['a pager option before the subcommand', '/work/a', "git -C '/work/a' --no-pager diff HEAD", false],
  ['a diff written to a file', '/work/a', "git -C '/work/a' diff --output=x HEAD", false],
  ['a log written to a file', '/work/a', "git -C '/work/a' log -p --output x", false],
  ['an output option in quotes', '/work/a', "git -C '/work/a' show '--output=x'", false],
  ['-o', '/work/a', "git -C '/work/a' ls-files -o", false],
  ['a path up out of the folder', '/work/a', "git -C '/work/a' diff HEAD -- ../x", false],
  ['a path up out of the folder, after =', '/work/a', "git -C '/work/a' diff --relative=../b", false],
  ['a diff of two paths outside any repository', '/work/a', "git -C '/work/a' diff --no-index a b", false],
  ['an absolute path', '/work/a', "git -C '/work/a' diff /etc/hosts /dev/null", false],
  ['a path under home', '/work/a', "git -C '/work/a' diff ~/x y", false],
  ['a quote left open', '/work/a', "git -C '/work/a' diff 'a b", false],
  ['a double quote', '/work/a', `git -C '/work/a' diff "a b"`, false],
  ['a format with %', '/work/a', "git -C '/work/a' log --format=%h", false],
]

for (const [name, folder, command, reads] of cases) {
  test(`${reads ? 'a read' : 'not a read'}: ${name}`, () => {
    expect(isGitRead(command, folder)).toBe(reads)
  })
}
