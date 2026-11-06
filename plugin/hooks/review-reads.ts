// ABOUTME: The git reads a review's turn may run in the asker's folder, with no engine calls: one git command whose
// ABOUTME: subcommand only reads, with no shell syntax and no path out of that folder. Imported by link.tsx.

const READS = new Set(['status', 'diff', 'log', 'show', 'ls-files', 'rev-parse', 'branch'])
// `git branch` only lists with these; a name, or any other flag, makes, moves or deletes a branch.
const BRANCH_LISTS = new Set(['-a', '--all', '-r', '--remotes', '-v', '-vv', '--verbose', '--list', '--show-current'])
// A folder the shell reads bare, as Python's shlex leaves one unquoted: nothing in it splits, globs or expands.
const BARE = /^[A-Za-z0-9_@%+=:,./-]+$/
// One argument: bare characters and single-quoted runs, which may hold a space. Nothing else, so no second command,
// substitution, redirect or escape gets past it.
const ARG = "(?:[A-Za-z0-9._/=@:^~-]|'[A-Za-z0-9._/=@:^~ -]*')+"
const CALL = new RegExp(`^([a-z-]+)((?: ${ARG})*)$`)
const ARGS = new RegExp(ARG, 'g')

// Refused in an argument, as it writes a file or names a path out of the folder: an output file, a diff of any two
// paths, an absolute or home path (or zsh's `=command`), a `..` segment. A `..` between revisions, as in
// HEAD~3..HEAD, is a range and stays.
const stays = (arg: string): boolean =>
  arg !== '-o' && !arg.startsWith('--output') && arg !== '--no-index' && !/^[/~=]/.test(arg)
  && !arg.split(/[/=:]/).includes('..')

// Whether `command` is exactly one git read of `folder`: `git -C <folder> <subcommand> [args]`, the folder in single
// quotes as the review's brief writes it, or bare when the shell would read it so.
export function isGitRead(command: string, folder: string | null): boolean {
  if (folder === null) return false
  const forms = [`'${folder.replaceAll("'", `'"'"'`)}'`, ...(BARE.test(folder) ? [folder] : [])]
  const prefix = forms.map(form => `git -C ${form} `).find(start => command.startsWith(start))
  if (prefix === undefined) return false
  const call = CALL.exec(command.slice(prefix.length))
  // Both groups take part in every match, the arguments' perhaps empty.
  if (!call || !READS.has(call[1]!)) return false
  const args = [...call[2]!.matchAll(ARGS)].map(match => match[0].replaceAll("'", ''))
  return call[1] === 'branch' ? args.every(arg => BRANCH_LISTS.has(arg)) : args.every(stays)
}
