# Notification actions

The panel posts a macOS notice when a session asks a question or finishes a
turn (shipped 2026-09-16 through a copy of terminal-notifier). This design
replaces that sender with one of our own so the notice can carry the
question's options as buttons and a reply field, and so a click lands on the
exact session. Approved on 2026-09-16.

## What the user sees

A session asks a question (Claude Code's `AskUserQuestion`):

    ┌ [icon] noter                                    ┐
    │ Question banner: what should the banner offer?  │
    │                    [Show only] [Allow / Deny] … │
    └─────────────────────────────────────────────────┘

- Title: the session's name as the card shows it.
- Body: the question text, one line. A payload with several questions shows
  the first and appends `(+2 more)`.
- Buttons: the question's option labels, up to four (macOS's limit), then
  `Other…`, a text field. Multi-select questions get no option buttons.
- Any other tool's permission gate: body `wants to run: <first line of the
  command>` (or the tool name), one `Allow` button that sends `1`, the Yes
  of every Claude Code permission prompt. No Deny: macOS shows one action
  flat and folds two or more into an Options menu, and Allow is the one
  worth a click.

A session finishes a turn: title, body `finished a turn`, one `Reply…` text
field whose text becomes the session's next prompt.

Clicking the notice itself brings that session forward. macOS shows a single
action flat on hover; two or more, with or without the text field, sit
under an Options menu (measured 2026-09-16), so a question is always a menu
and only the approval's lone Allow is flat.

## Where the question comes from

`PermissionRequest` carries `tool_name` and `tool_input`. For
`AskUserQuestion`, `tool_input.questions[]` has `question`, `header`,
`multiSelect` and `options[].label`. The hook (`emit-state.py`) publishes on
the state variable, beside `blocked_since`:

    "question": {"header": "Question banner",
                 "question": "What should the banner offer?",
                 "options": ["Show only", "Allow / Deny", "Reply field too"],
                 "multi": false, "more": 0}

For any other gated tool: `{"tool": "Bash", "summary": "git push origin main"}`.
Cleared with the gates. The daemon copies it onto the row as `question`; the
page passes it through to the notify call unchanged.

Codex has no `AskUserQuestion`; its gates carry `tool` and `summary` only.

## The sender

`assets/notifier.swift`, compiled by `install.sh` with `swiftc` into
`~/.local/share/agents-sidebar/Agents.app/Contents/MacOS/agents-notifier`.
The bundle keeps its id (`com.hex.agents-sidebar.notifier`), so the permission
already granted carries over; `LSUIElement` keeps it out of the Dock.
`UNUserNotificationCenter` refuses to run outside a bundle, which is the other
reason the bundle exists. Homebrew's terminal-notifier drops out.

    agents-notifier post --id ID --title T --body B
                         [--button KEY=LABEL]... [--reply PLACEHOLDER]
    agents-notifier remove --id ID

`post` registers a category for exactly these buttons, posts, then stays alive
until the notice is acted on or an hour passes. It then prints one JSON line
on stdout and exits:

    {"action": "default"}                      click on the notice
    {"action": "<KEY>"}                        a button
    {"action": "reply", "text": "…"}           the text field
    {"action": "dismiss"}                      closed, or timed out

On SIGTERM it removes its own delivered notice and exits without printing.
No sound is attached; the sound switches in settings stay a separate choice.

## The daemon

`Bridge.notices: {session_id: Process}`. A new notice for a session terminates
the previous process (its notice goes with it); `clear` terminates it; a
process that exits on its own is forgotten. So a session has at most one
standing notice, a click always reaches a daemon that still remembers the
session, and no port or token is ever written into a notification.

Response handling, `notify_response(line, kind, question) -> (verb, text)`:

| action    | kind    | verb   | text                                   |
| --------- | ------- | ------ | -------------------------------------- |
| default   | any     | bring  |                                        |
| option N  | blocked | send   | the keystrokes that pick option N      |
| reply     | blocked | send   | keystrokes for `Other`, then the text  |
| reply     | done    | send   | the text, then Enter                   |
| dismiss   | any     | none   |                                        |

The keystrokes that pick an option are a constant, `OPTION_KEYS`, confirmed
against the live Claude Code prompt before the buttons send anything; until
then a button only brings the session forward. `send` already exists; the
page's `bring` is reused, so the return trip works as it does for
`focus_blocked`.

Suppression is unchanged: nothing posts for the session in front while
iTerm2 is frontmost. A reply typed into a banner goes to a session the user is
not looking at, which is the point, and also the risk: it is sent only where
the row's `question` still stands at the time of the response, so a session
that moved on gets nothing.

## Settings

Unchanged: `notify`, `notify_blocked`, `notify_done`.

## Tests

Pure functions get tests: `question_from(payload)` in the hook,
`notify_argv` (buttons and reply from a question), `notify_response`, and the
one-process-per-session rule on a fake process table. The Swift side has no
harness and is verified by running it; it stays under 200 lines.

## Out of scope

Collapsing several sessions into one notice; a notice for Codex questions
beyond the tool name; keystroke mappings for Codex's approval prompt.
