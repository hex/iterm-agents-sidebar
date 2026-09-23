<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/banner.svg" width="100%" alt="An iTerm2 window with the Agents sidebar docked on the right: a card per session, and the one waiting on a question turning amber">

# Agents sidebar

A tool for the iTerm2 Toolbelt that lists every terminal session in every
window and tab, with the Claude Code, Codex and omp ones at the top, each showing what it's doing and whether it needs you. Click a row to focus that session.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/get.sh | bash
```

That clones the repository to `~/.local/share/agents-sidebar/src` and runs
`install.sh` there. The bar at the foot names the release you run and, once
a newer one is out, offers it with an Update button. Running the same line
again pulls the latest too. Or clone it anywhere yourself and run `./install.sh`: the
clone is the install, so leave it in place and update it with `git pull`. It needs nothing else: one iTerm2 Basic
script, no pip, no virtualenv, nothing beyond the standard library.

1. Scripts, AutoLaunch, `agents_sidebar` starts it without restarting iTerm2.
2. View, Toolbelt, Agents opens the panel.

The install also points `statusLine.command` in `~/.claude/settings.json` at
`plugin/statusline-bridge.sh`, because that payload is the only place Claude
Code says how full the context is; the bridge publishes it and then renders
the statusline you had, so your line stays. The install backs the file up first.
Without it, cards show no context %, model or effort, and the hover no cost,
limits or cache. Whenever `settings.json` lacks the bridge (installed with
`--no-statusline`, or replaced by another tool), the foot of the panel says so
and offers Install, which does the same step, or Not now; Settings > Offer the
statusline bridge brings a dismissed offer back.

If Codex CLI is on the machine, the install also adds the state hook to
`~/.codex/hooks.json`, keeping whatever other tools put there, and names a
writable directory in `~/.codex/config.toml`; Codex asks once to trust the
hook. Without Codex, nothing of that happens.

```sh
./install.sh --no-statusline   # leave settings.json alone; cards show no context figure
./install.sh --no-codex        # leave Codex's files alone
./install.sh --codex           # insist, and fail if Codex is not there
```

Through the one-liner, a flag goes after `bash -s --`. See
[docs/integrations.md](docs/integrations.md) for the detail and how to undo
any of it. `./uninstall.sh` takes it out again: the script, the hook,
your own statusline back, our entries out of Codex's hooks, the notifier,
and the panel's settings, state and account store with the Keychain items
behind it. It leaves the checkout, the `.before-agents-sidebar` backups and
the writable directory line in `~/.codex/config.toml`.

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

A card that starts waiting on you while it sits out of sight scrolls into
view.

### What a card says

<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/card-states.svg" width="100%" alt="Four cards: one amber with a WAITING badge, its question and a button per answer, one at work with a report and ticks, one grey with an IDLE outline, and one at work for 25 minutes with a warm long badge">

| State | How it looks |
| --- | --- |
| Waiting on you | The whole card amber, with a WAITING badge and what it asks: the question with a button per answer (a question that takes more than one answer lists them without buttons), or the tool and the command it wants to run |
| Working | Dark name, working dots |
| Idle | Grey name, IDLE outline |
| Working 20 minutes or more | A warm `long 25m` outline, in case it has stalled |
| Exited | Faded, with an EXITED outline and a Resume button: the agent's process died and the pane is back at its shell prompt |
| Unknown | A hollow square: a turn silent for five minutes with no command running under it |

<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/card-anatomy.svg" width="100%" alt="One card, each part joined by a line to what it means: the name and the agent, the task and what it is doing now, the ticks, the branch, model, context and CPU, then a teammate, running and finished subagents, a Codex job, the open tasks and the background shells">

Under the name, an agent reports its own task: a title, then
`Reading code · 40s`, then ticks for how far it says it has got. The
percentage is the model's estimate, not a measurement, so a report older than
five minutes reads `stale`, and a finished one reads `Done`.

The line below carries the branch, the model with its effort letter (`[l]`,
`[m]`, `[h]`, `[xh]`, `[mx]`), the context percentage, and a `CPU` or `Mem`
chip when the session's process tree is using a lot of the machine. While a
chip shows, the hover card adds a `CPU` or `Memory` row with the figure and the
name of the program using the most of it. Rest the pointer on a Claude card
and its hover card offers Context breakdown, `/context` for that session
drawn as a bar ([usage](docs/usage.md#what-fills-the-context)). A Codex
card wears the OpenAI mark instead of the Claude one, and has no teammates and
no background-shell line. Codex opens its session at your first prompt, so
until then its card shows the name, the branch and a `Codex` mark, and no
state.

An omp session needs nothing installed. omp writes its state into its own tab
title: `π >` at your turn, `π !` while an approval or a question waits, and a
spinner while it works. The panel reads that, and takes the rest from omp's own
files under `~/.omp`: the model, the effort, the context figure and what the
session has cost. The name omp gave the session sits under the card's name, and
while omp works, what it says the running tool is for sits under that. Commands
omp sent to the background show as running commands do on a Claude Code card.
Subagents omp spawns with its `task` tool get a row each, under the name omp
gave them, with their model, context, spend, how long they have run and,
while they run, what their running tool is for. A finished one keeps its row
until your next prompt. The card has no task line, and a waiting
question shows as blocked without its text. Inside plain tmux the title never
reaches iTerm2, so the row stays a plain terminal. omp posts its own
notifications, so the panel adds none for it.

Teammates nest inside the card, and while one of them is working the lead's
line carries the busy dots and a count, since a teammate runs in its own pane
and the lead's own badge stays about the lead. Running subagents get a row each, with the
model they reply with and how long they have run. A subagent started by another
subagent sits one step in, under the one that started it. A Codex job started
through the codex plugin (a rescue or a review) gets a row too, with its phase.
A finished subagent keeps its row until your next prompt, and one still
running in the background stays through it. Past three of them,
they fold into one line ("30 finished") that opens on a click, and the ones
still running stay in sight.
A session's open tasks, the checklist it keeps
with TaskCreate, fold into one line ("6 tasks · 1 in progress") that opens
to a row per task, the running ones with the dots and what is being done.
Background shells fold into
one line ("2 commands running") that opens on a click, and clicking a shell
shows the whole command with a Copy button.

### Answering from a banner

The banner can answer for you, so a session in another tab doesn't wait.

| On the banner | What it does |
| --- | --- |
| A click | Brings that session forward, tab and all |
| A question's option button | Sends that option's number into the prompt. A question that takes more than one answer gets no buttons and no Other |
| Other | Picks that option, then types your text |
| Allow, on a permission gate | Answers Yes. It shows the command's first line and approves the whole command, so No stays in the terminal |
| Reply, on a finished turn | Your text becomes the session's next prompt |

### Settings

<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/settings.svg" width="100%" alt="The settings drawer: a card each for sounds, notifications, focus and the rows, every setting with its default">

The gear opens the drawer; every setting is there with its default, as above.
A setting indented under another works only while that one is on.

| Card | Settings |
| --- | --- |
| Sound | Play sounds; under it When a session is blocked, When one finishes, Volume |
| Notifications | Show macOS notifications; under it When a session asks a question, When one finishes |
| Focus | Bring a blocked session forward; under it Go back once it resumes |
| Rows | Warn above, CPU heavy at, Memory heavy at, Sort cards by name, Provider badge, Branch, Task (under it What it is doing, How old the report is, Progress bar, Task list), Model, Subagents, Background shells (under it Start expanded), Text size, Offer the statusline bridge |

Some have limits the picture doesn't show:

| Setting | Range |
| --- | --- |
| Warn above, the context figure a row starts to show | 0 to 100% |
| CPU heavy at | 25 to 400%, of one core |
| Memory heavy at | 0.5 to 8 GB |
| Text size | Minus and plus buttons over nine sizes, 0.8 to 1.6 times the size as designed |

<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/foot.svg" width="100%" alt="The panel's foot: two sessions waiting, the Auto-switch control with a chip naming the account it would switch to soon, the active account's 5-hour, weekly and Fable meters, the last switch, a second account with its Switch button, the Add button, Codex's own limits, and the bar with the release, the newer one on offer with its Update button, reload and the gear">

The foot lists the sessions waiting on you, oldest first, and under them your
Claude account limits: 5-hour, weekly, and per-model weekly, with the time left
until each resets. Store a login with **Add <your email>** and you can switch
between accounts from there. Auto-switch, off by default, spends first the
quota that resets soonest and leaves an account before a limit stops your
sessions. Only the limits of the models your sessions run count, and a model
limit full on every account is set aside with a `Fable full everywhere` chip.
While Auto-switch is on, you have two or more accounts and a switch is near,
a chip reads the account's name and `soon`, and gives the reason on hover. Codex's own limits sit under them, read from
its session log: a 5-hour and a weekly window, or weekly alone, depending on
the plan. See [docs/accounts.md](docs/accounts.md).

The bar at the bottom names the release you run, and two buttons: reload and
the gear. At start, once a day and on every reload press, the daemon lists
the releases on GitHub; when one is
newer, the bar adds its number and an Update button. Pressing it pulls that
release, runs `install.sh` and restarts the daemon, after which the panel
needs reopening from View > Toolbelt. See
[docs/usage.md](docs/usage.md#updating).

<img src="https://raw.githubusercontent.com/hex/iterm-agents-sidebar/main/assets/menu.svg" width="100%" alt="An idle card with its right-click menu open: /compact, /rotate, /clear, then Close">

Right-click an agent row, or press Shift+F10 on a selected one, for
`/compact`, `/rotate`, `/clear` and Close. Close and `/clear` ask for a second
click. A Codex row gets `/compact` and Close, since Codex has no `/rotate` or
`/clear`. An omp row gets `/compact`, `/clear` and Close. A plain terminal's
row gets Close alone.

## More

- [docs/usage.md](docs/usage.md): what every part of a card means
- [docs/accounts.md](docs/accounts.md): accounts, switching, the meters
- [docs/integrations.md](docs/integrations.md): the statusline bridge and Codex hooks, and how to opt out
- [docs/troubleshooting.md](docs/troubleshooting.md): `STALE`, `?`, a white panel,
  tracing the statusline bridge
- [docs/development.md](docs/development.md): how it works, tests, releases

The panel would rather show nothing than a believable wrong answer. Every row
dims behind a `STALE` banner when the list is no longer known to be true, and a
session iTerm2 can't report shows `?` rather than a guess.

## Licence

[MIT](LICENSE). The icons are others' work, credited in
[THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).
