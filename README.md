<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/banner.svg" width="100%" alt="An iTerm2 window with the Agents sidebar docked on the right: a card per session, and the one waiting on a question turning amber">

# Agents sidebar

A tool for the iTerm2 Toolbelt that lists every terminal session in every
window and tab, with the Claude Code and Codex ones at the top, each showing what it's doing and whether it needs you. Click a row to focus that session.

## Install

```sh
git clone https://github.com/hex/iterm-agents-sidebar.git
cd iterm-agents-sidebar
./install.sh
```

The clone is the install, so leave the directory in place and update it with
`git pull`. It needs nothing else: one iTerm2 Basic script, no pip, no
virtualenv, nothing beyond the standard library.

1. Scripts, AutoLaunch, `agents_sidebar` starts it without restarting iTerm2.
2. View, Toolbelt, Agents opens the panel.

Two things are opt-in, because each edits a file another tool owns:

```sh
./install.sh --statusline   # rows get a context percentage
./install.sh --codex        # Codex CLI sessions get cards too
```

`--statusline` points `statusLine.command` in `~/.claude/settings.json` at
`plugin/statusline-bridge.sh`, which publishes the payload and then renders the
statusline you had. `--codex` adds the state hook to `~/.codex/hooks.json` and
a writable directory to `~/.codex/config.toml`; Codex asks once to trust it.
Both back the file up first. See
[docs/integrations.md](docs/integrations.md) for the detail and how to undo
either.

Notifications need `swiftc`, from the Xcode Command Line Tools
(`xcode-select --install`). Without it the panel works as usual and posts
nothing. With it, `install.sh` builds
`~/.local/share/agents-sidebar/Agents.app`, macOS asks once to allow its
notifications, and the app gets its own entry in System Settings where you set
its sound and banner style.

## Using it

| Key | What it does |
| --- | --- |
| Down | Move to the next session |
| Up | Move to the previous session |
| Enter or Space | Focus the selected session |
| Cmd+Enter or Ctrl+Enter | Send a newline, to unblock an agent sitting at a prompt |

Click an empty part of the panel first to give it keyboard focus. Arrow keys
only; iTerm2 keeps the other combinations for itself.

### What a card says

| State | How it looks |
| --- | --- |
| Waiting on you | The whole card amber, with a WAITING badge |
| Working | Dark name, working dots |
| Idle | Grey name, IDLE outline |
| Working 20 minutes or more | A warm `long 25m` outline, in case it has stalled |

Under the name, an agent reports its own task: a title, then
`Reading code · 40s`, then ticks for how far it says it has got. The
percentage is the model's estimate, not a measurement, so a report older than
five minutes reads `stale`, and a finished one reads `Done`.

The line below carries the branch, the model with its effort letter (`[l]`,
`[m]`, `[h]`, `[xh]`, `[mx]`), the context percentage, and a `CPU` or `Mem`
chip when the session's process tree is using a lot of the machine. A Codex
card wears the OpenAI mark instead of the Claude one, and has no teammates and
no background-shell line.

Teammates nest inside the card. Running subagents get a row each, with the
model they reply with and how long they have run. A subagent started by another
subagent sits one step in, under the one that started it. A Codex job started
through the codex plugin (a rescue or a review) gets a row too, with its phase.
Background shells fold into
one line ("2 commands running") that opens on a click, and clicking a shell
shows the whole command with a Copy button.

### Answering from a banner

The banner can answer for you, so a session in another tab doesn't wait.

| On the banner | What it does |
| --- | --- |
| A click | Brings that session forward, tab and all |
| A question's option button | Sends that option's number into the prompt |
| Other | Picks that option, then types your text |
| Allow, on a permission gate | Answers Yes. It shows the command's first line and approves the whole command, so No stays in the terminal |
| Reply, on a finished turn | Your text becomes the session's next prompt |

### Settings

| Setting | Default |
| --- | --- |
| Show macOS notifications, for questions and finished turns | On |
| Sounds, for questions and finished turns | On |
| Bring a blocked session forward, and go back once it resumes | Off, then on |
| Sort cards by name, instead of the terminals' own order | Off |
| CPU heavy at | 100%, one full core |
| Memory heavy at | 2 GB |
| Show task, with its activity, age and ticks | On |
| Show subagents, show background shells, start expanded | On, on, off |

The foot lists the sessions waiting on you, oldest first, and under them your
Claude account limits: 5-hour, weekly, and per-model weekly, with the time left
until each resets. Store a login with **Add this account** and you can switch
between accounts from there. Codex's own limits sit under them, read from its
session log. See [docs/accounts.md](docs/accounts.md).

The bar at the bottom shows what the running sessions report having spent at
API prices, how many sessions report it, and two buttons: reload and the gear.

Right-click an agent row, or press Shift+F10 on a selected one, for
`/compact`, `/rotate`, `/clear` and Close. Close and `/clear` ask for a second
click.

## More

- [docs/usage.md](docs/usage.md): what every part of a card means
- [docs/accounts.md](docs/accounts.md): accounts, switching, the meters
- [docs/integrations.md](docs/integrations.md): the two opt-in installs
- [docs/troubleshooting.md](docs/troubleshooting.md): `STALE`, `?`, a white panel
- [docs/development.md](docs/development.md): how it works, tests, releases

The panel would rather show nothing than a believable wrong answer. Every row
dims behind a `STALE` banner when the list is no longer known to be true, and a
session iTerm2 can't report shows `?` rather than a guess.
