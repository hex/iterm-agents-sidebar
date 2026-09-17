# iTerm2's own Claude Code integration, compared

Measured 2026-09-16 on iTerm2 3.7.1, which ships the integration
(`iTerm2 > Install Claude Code Integration`). It was not installed on this
machine; the Session Status tool was enabled by hand and fed through `it2`.

## What theirs is

- A **Session Status** Toolbelt tool: one row per session with a coloured
  dot and a label, `working`, `waiting` or `idle`, an optional detail line
  (the tool a permission request is for, or a snippet of the last message),
  sorted so waiting rises, click to jump.
- A `cc-status` hook (a Mach-O binary under `iTerm.app/Contents/Resources/
  utilities/`) added to `~/.claude/settings.json`. It runs `it2 session
  set-status --status … --detail … --background-tasks N`, so the state goes
  in over the Python API, not the terminal. A session stays `working` while
  background agents it launched are still running.
- A **Workgroup** preset (Chat, Diff, Code Review peers) with Enter/Exit
  triggers on chosen profiles, and Code Review findings into Clippings.
- A health monitor: if the hook goes missing it offers to reinstall, and a
  one-time banner offers the Workgroup when `claude` is seen running.

## The three questions

**Which version.** 3.7.1, installed here. The state is not a session
variable: `it2 session set-status` writes into iTerm2 and nothing appears
under `user.*`, so ours cannot read theirs and theirs cannot read ours. The
tool accepts any status from any caller, which is how this comparison was
made without installing the hook.

**Both at once.** Yes. The Toolbelt is a list; ours and Session Status
showed together (`ToolbeltTools = (Agents, "Session Status")`). Their hook
and our plugin hook are independent `settings.json` entries reacting to the
same events, with no shared state. Cost: one more process per hook event.

**The settings.json collision.** Real, and on this machine it is chezmoi:
`~/.claude/settings.json` is a managed file, so `chezmoi apply` restores the
template and drops their hook unless it is added to the chezmoi source. Their
docs already admit Claude Code itself drops it sometimes and the monitor will
then prompt "Claude Code Integration Looks Broken" on every recurrence. Ours
is a plugin precisely to stay out of that file.

## What ours does that theirs does not

Context percentage, git branch, model, cost, accounts with limit meters and
switching, Codex sessions, shell rows and running commands, subagents and
teammates nested under their lead, the hover card, the task line (title,
percent, activity, age), and macOS notices with the question's options as
buttons, a reply field, and Allow on a tool gate.

What theirs does that ours does not: the Workgroup (Diff and Code Review
peers), Clippings, the "background tasks still running" hold on `working`,
and being first-party, so it survives iTerm2 upgrades without a daemon.

## Decision

Keep ours. Theirs is a status dot; ours is the reason to look. One thing
borrowed since: the `working` hold while background tasks run. Workgroups
were looked at on 2026-09-17 and skipped: the Python API has no workgroup
calls, only the menu items reach one, and a pane layout around a session is
what cs already arranges with tmux.
