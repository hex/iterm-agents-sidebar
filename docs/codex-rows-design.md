# Codex sessions as panel rows

Status: approved 2026-09-15; `PermissionRequest` confirmed by probe.

## The request

A Codex CLI session running in a terminal gets a row in AGENTS, marked with the
OpenAI logo, carrying what a Claude row carries: the state badges (working,
idle, waiting, long), model and effort, context %, branch and directory.

## Facts this rests on

Measured on this machine against Codex 0.154.0.

- **Codex has hooks shaped like Claude Code's.** `~/.codex/hooks.json` uses the
  same `{"hooks": {Event: [{"hooks": [{type, command, timeout}]}]}}` layout,
  `[features] hooks = true` is on, and herdr already owns one `SessionStart`
  entry there. Codex records trust per hook in `config.toml`
  (`[hooks.state."<file>:<event>:i:j"] trusted_hash`), so a new hook is approved
  once in Codex before it runs.
- **A probe hook on a live interactive session fired** `SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` and `SessionEnd`.
  Payload keys match Claude Code's: `session_id`, `turn_id`, `cwd`, `model`,
  `permission_mode`, `transcript_path`, `tool_name`, `tool_use_id`,
  `stop_hook_active`, `source`, `reason`.
- **`PermissionRequest` fires on a real approval prompt.** A write to `~`
  (read-only in Codex's workspace sandbox) went PreToolUse, PermissionRequest
  (same second), PostToolUse 6 s later once approved, then Stop. Commands the
  sandbox allows (`ls`, a write to `/tmp`) raise no prompt and no event. As in
  Claude Code, `PermissionRequest` carries no `tool_use_id`.
- **The hook reaches the pane.** Its ancestors sit on the pane's tty
  (`ttys000`: python, codex, node, zsh) and `TMUX_PANE` is set, so
  `emit-state.py`'s `find_tty()` and tmux passthrough work unchanged.
- **The rollout is the status source.** Codex has no statusline to bridge.
  `transcript_path` is the rollout; its last `turn_context` carries `model` and
  `effort`, and its last `event_msg/token_count` carries
  `info.last_token_usage.total_tokens` and `info.model_context_window`.
  `total_token_usage` is cumulative over the session (6 M on a 258 k window),
  so it cannot give context %.
- **Rollouts alone cannot make rows.** Most of today's rollouts are
  `codex exec` runs from the codex plugin with no terminal. A row needs a pane,
  which is why the hook, not a rollout scan, is what makes a Codex agent.

## Design

### Hook: `emit-state.py`, told which agent it serves

One handler, not a sibling. The event names Codex sends are the ones
`state_for` already reads, and the state machine (per-session doc, gate,
working_since) is the part worth not duplicating.

- A `--codex` argument (after the event name) switches three things:
  the user variable becomes `codexState`, the pid lookup looks for `codex` on
  the tty instead of `claude` (`claude_pid(tty)` becomes
  `agent_pid(tty, name)`), and the published JSON adds `transcript_path` and
  `model`, which every Codex payload carries.
- The pid is the vendor binary (`.../vendor/.../bin/codex`), not the node
  launcher tmux reports as the foreground job: `"codex" in comm` matches only
  the binary, and the commands Codex runs are its children, so background
  shells and uptime key on it.
- Without `--codex` nothing changes for Claude Code.
- The binary names `PreCompact` and `SubagentStop` but not `SubagentStart` or
  `Notification`, and the probe saw none of the four. Codex rows are
  registered only for the seven events under Install.

### Install

`install.sh --codex` (opt-in, like `--statusline`, because the file is shared) merges seven entries into `~/.codex/hooks.json` (the probe's
events, pointing at the installed copy with `--codex`), keeping every entry it
did not write, herdr's included. It skips the step when `~/.codex` does not
exist. Codex then asks once to trust the hooks.

### Daemon: `sidebar.py`

- `SESSION_VARIABLES` gains `user.codexState`.
- Per session the existing `parse_*` readers run on whichever variable is set;
  a session with `codexState` gets `provider: "openai"`, otherwise `"claude"`.
  When both are set (a crashed Claude left its variable, then Codex started in
  the same pane) the one with the newer `ts` wins.
- `classify` treats either state as an agent.
- Model comes from the variable. Effort and context come from
  `codex.read_session(transcript_path)`:
  the 256 KB tail of the rollout, reusing `limits_from_lines`' tail reading.
  Model shown as-is (`gpt-6-astra`), no prefix stripping.
- Branch, directory and uptime work as they do for Claude rows (tmux path,
  process tree by pid). The background-shell line does not: it finds shells by
  Claude Code's shell-snapshot marker, which Codex's commands do not carry.

### Page: `page.html`

- The row draws `providerIcon("openai")` before the label when
  `provider === "openai"`. Claude rows stay unmarked, as today.
- Badges, long-turn, shimmer and waiting queue need nothing new: they read
  `state`, `blocked_since` and `working_since`, which the Codex variable carries.

## What a Codex row does not show

- Subagents: without a `SubagentStart` there is nothing to count from.
- Anything from Codex's `/status` that is not in the rollout (account,
  collaboration mode).

## Open

- **herdr owns `hooks.json` too.** A herdr update may rewrite the file and drop
  these entries; rerunning `install.sh` restores them. Codex keys trust by
  position (`<file>:<event>:i:j`), so any reorder asks for approval again.
- **Context % baseline.** Codex's `/status` leaves a fixed 12,000 tokens out of
  both used and window: 27,371 of 258,400 reads "94% left", where the plain
  ratio gives 89%. Fitted to that one reading.

## Testing

- `emit-state.py --codex`: real-shaped Codex payloads (the probe's key sets) in,
  `codexState` JSON out; Claude path unchanged.
- `codex.read_session`: fixture rollout tail -> effort, context %.
- `snapshot`: a session with `codexState` becomes an AGENTS row with
  `provider: "openai"`.
- Install merge: a hooks.json with herdr's entry keeps it; running twice adds
  nothing.
- Live: one Codex turn in a tmux pane shows working, then idle, in the panel.
