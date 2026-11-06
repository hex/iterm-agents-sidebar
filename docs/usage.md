# Using the panel

The reference for what each part of a card means. The README covers the parts
you need on day one.

The install starts the panel when iTerm2 is running. If it already runs,
the install prints a restart command and leaves it running. Open it through
View > Toolbelt > Agents. With iTerm2 closed during install, start it from
Scripts > AutoLaunch > `agents_sidebar` after opening iTerm2.

## Which group a session lands in

A session running Claude Code, Codex or omp goes in `AGENTS`. The panel
knows one by the agent's mark in the tab title, the state it reports, or its
process. A terminal that only sits in a `cs` session directory is not enough.
Everything else goes in `SESSIONS`. A Codex
terminal counts from the moment it opens, which the panel reads from the
foreground process, since Codex itself says nothing until the first prompt.

A screen reader reads a row's position out with its name: `t3` for the third
tab, `t3·2` for the second pane of a split tab, and `w2·t3` once there is a
second window. The row itself does not show it. The number is a position you
can count to, not iTerm2's internal tab id.

## What keeps a session working

A session whose turn has ended stays working while a background shell,
subagent or workflow it started is still running, because that task's end wakes it. A background command that never ends keeps it working until
your next prompt. A monitor does not: it only waits for something outside to
happen, and the watcher Claude Code arms when a session publishes an Artifact
stays open for as long as the session does. A teammate is listed until it is
shut down, idle or not, so a lead that only its teammates hold reads idle on
the panel once every teammate it counts is carded under it and idle; one
still working, waiting on you, or not carded at all keeps the lead working.

The hook stamps the time your prompt started the turn, which is what the
`Long 25m` pill counts from.

## Order

Order, under Rows in settings, picks how the cards are arranged, inside each
agent's group while cards are grouped by provider (the default):

| Choice | What you get |
|---|---|
| Follow the terminals | iTerm2's own order of windows, tabs and panes. A card sits where its tab does and nothing a session does moves it, with one exception: while Lift its card first is on (see [A finish you have not seen](#a-finish-you-have-not-seen)) a card that waits on you or finished unseen is lifted to the top of its group until you answer or look. The default |
| By name | Alphabetical |
| By attention | The working cards first, the longest turn at the top, under a `Working` head; then every other card (at rest, exited, or not yet heard from), the longest rest at the top and the ones without a time last, under `Idle`. A card at rest for ten minutes is washed toward the background, and more after thirty: the sessions that slipped your mind. The heads appear only while a group holds both kinds |
| By hand | The order you dragged the cards into. A new session goes to the bottom of its group, and a closed one keeps its place for when it comes back |

Drag an agent card up or down to put it there; its teammates and docked
worktree cards come with it, and while cards are grouped by provider it stays
inside its agent's group. While you drag, a see-through copy of the card
follows the pointer anywhere in the list, and the card itself waits, faded, in
the place it would drop. A card steps aside once the pointer has passed over
it. With Link cards on, hold the copy still over another card and the two
link instead (see [Linking two sessions](#linking-two-sessions)). The first drop switches Order
to By hand, starting from the order on screen, so only the card you dragged
moves. A press that moves 5 px or less up
or down is still a click, and a Control-press opens the menu as a right click
does. Escape, or letting go outside the panel, puts the card back. The panel
remembers a card by its name, so the order survives an iTerm2 restart; two
cards with one name share a place, so dragging one past the other changes
nothing. Shell cards, worktree cards and teammate lines do not drag on their
own.

By attention moves a card only once its new state has held for thirty
seconds: a tool pause that reads as idle, or a turn that just ended, leaves it
where it was, and a turn or a rest shorter than that never moves it at all. A
card waiting on a prompt counts as working and goes there at once, without the
wait; the foot's Waiting on you is where the ask itself shows. omp without its extension publishes no times, so the panel times those cards from when it
saw each state begin. Whatever the order, a teammate stays under its
lead and a worktree card stays docked to its session, because each card
travels with the rows under it.

## Linking two sessions

Linking is experimental and starts off: turn on Link cards under Experimental
in settings. While off, a card held over another only moves, no card links,
and the panel refuses a link asked for any other way. Turning it off unties
every pair of partners and ends every hand-off still open. A task a partner
had then answers `could not finish the task: linking was turned off`.

Drag an agent card, hold it still over another agent card for 0.4 s, and let
go. Two Claude Code cards become [partners](#partners) until you untie them.
Any other two, a Claude Code card with a Codex or omp one, or two of those, get
a one-shot hand-off: the first session writes up its latest result for the
second one, and the second one starts working on it. You type nothing in
either terminal.

As you drag a card toward another, the two reach for each other like two
drops of water, and a link badge on the dragged card's leading edge grows as
the card goes deeper over the other, full once it covers half the shorter
card. Once the link is ready they fuse into one card, its outline shading
from one card's colour to the other's. Let go and the badge bounces once
while two quiet rings in the dragged card's colour leave it. Move off the
card and they spring apart, and the drag goes on as a reorder. Escape, or letting go outside the panel, cancels it. A link puts the list back in its old order
and saves no order.

The first session's agent writes the message; the panel only asks it to. It
asks for the latest result, written for the other session to act on, as the
whole reply. If a Stop hook sends that turn on after it replied (a notes
check, say), the reply it stopped with is what goes, not its answer to the
hook. The second session gets that reply in a fenced block, after a
line that calls it a report from another session and not an instruction from
you. It acts on it with its own permissions, the same as if you had pasted the
first session's output into it yourself.

When each end acts depends on its agent:

| Agent | Writes its result | Gets the other's result |
|---|---|---|
| Claude Code | at once when idle, else when its turn ends | at once when idle, else when its turn ends |
| Codex, omp | with your next prompt in that session | with your next prompt in that session |

A hand-off waits for your next prompt in its Codex or omp session.

The cards say how it goes. The first card shows `Asked to send to “bravo”`,
then `Sent`, then `Delivered to “bravo”`, and the second one shows
`From “alpha”` once it has started. Right after you let go, the second card
shows `Sent · from “alpha”` for 2 s. A line waiting on a Codex or omp prompt
says so (`Sent; waits for your next prompt in “bravo”`). A link that fails
shows `Refused:` and the reason. One that the waiting session has not picked
up 30 minutes after the ask shows `Expired`. The lines go 10 s after the link ends.

In a Claude Code terminal, both sessions also show the link in a band on the
right above the prompt: each session's name on a chip in its panel colour
(grey when it has none), joined by a link mark, then the state. While the first session writes, the link flows
and a spinner turns; it locks with a tick at `sent`, or `delivered` in the
second session. The band goes 10 s after the link ends. The VS Code chat
panel and `claude -p` draw no band, so there the cards are the only place to
look.

Each Claude Code session also shows a toast as the link moves on: the first
session when it starts writing and when it has sent, the second when the
hand-off starts there, and either one with the reason when its part fails.
Codex and omp sessions show no toast.

A prompt you type in the first Claude Code session while it writes the
hand-off goes back into the prompt box, with a note to send it when the
hand-off ends. It never mixes into the reply and keeps its `@` mentions. The
box takes text alone, so you add an attached image again, and the note says
so.

A card that cannot link says why under the pointer and never lights up:

| Reason | When |
|---|---|
| `only Claude, Codex and omp sessions can link` | a shell card |
| `“bravo” is not known to the panel yet` | an agent that has not reported its session yet |
| `“bravo” can’t link yet: run /reload-plugins there` | a Claude Code session started before the install; also Claude Code older than 2.1.287, or mods turned off (`disableAllHooks`, `--safe-mode`, an organization's `allowManagedModsOnly`) |
| `“bravo” has exited` | its agent has exited |
| `“bravo” is linked with “alpha”: untie it first` | the card is already one of two partners |

A worktree card never lights up, and over a teammate line the card it sits in
is the one you hold over.

When you let go, the panel checks both sessions once more, and the dragged
card shows `not linked:` and the reason for 4 s. For a hand-off: the first
session waits on you, a program is in front of it, or it already has a
hand-off open. For either kind: its agent has exited, or the two cards are
panes showing one session (`a card cannot link to itself`). A session sends
one hand-off at a time, from any of its panes.

Linking needs nothing set up. The Claude Code side is a mod inside the panel's
plugin, so it runs in every Claude Code 2.1.287 or newer (2.1.286 in the
desktop app) where mods are on.

### Partners

Two Claude Code cards linked this way stay linked: they draw as one card
where the card you dropped on was, the dragged card on top and no other card
moved, with a link badge on the join whose ring is half in
each session's colour. Each session knows who the other is and what it is
doing, can read the other's recent conversation, and can hand the other a
task and get the answer back. The agents decide on their own when to read
or hand over.

Each session hears of its partner on its next prompt, typed or a partner's
task. That prompt carries an introduction with what the panel knows of the
other (name, model,
folder and branch, whether it is working, idle or waiting on you, its task
line and open task list, how full its context is, and the first 300
characters of its last reply to you, marked as its words and not an
instruction). After that, a prompt carries the profile again only when it has
changed; time passing alone is not a change. A `/clear` starts a new
conversation, which gets the introduction again. Nothing goes into the system
prompt.

The two tools, which the model loads with ToolSearch:

| Tool | What it does |
|---|---|
| `mcp__agents-sidebar__partner_read` | the partner's last few exchanges (3 by default, at most 10), at most 16 000 characters, read from the last 2 MB of its transcript |
| `mcp__agents-sidebar__partner_delegate` | hands the partner a task and waits for its answer, which comes back as the tool's result |

While linking is off, either tool answers that it is off and where to turn it
on. Only the main conversation can use either tool; a subagent gets a
refusal.

Claude Code runs a plugin's tool without asking in any mode, and the panel
adds no question of its own: either tool runs when the model calls it,
whatever the session's permission mode.

A task waits behind whatever the partner is doing; if the partner waits on
you, the task is not handed over. The asking session's turn runs while it
waits, as for any long tool call. A toast says when the
partner is busy. Past ten minutes the tool gives up waiting and the answer
comes later as a message; Escape does the same, and the task goes on in the
partner. The answer is the partner's reply at its first Stop, never its
answer to a Stop hook that sent the turn on. One task is open between two
partners at a time, either way, so the two can never hand work back and
forth in a loop. A task the partner has not started in 30 minutes comes back
as not started. One it took comes back as not finished once the partner has
sat idle for a minute without answering, as when a plugin reload cut its
turn. A prompt you type in the partner during its task
goes back to the prompt box, as during a hand-off.

The card that asked shows `Asked “bravo”: …` while the task is open, then
`“bravo” answered` or `“bravo” could not finish:` and the reason, or
`Not handed over:` and the reason when the panel refused it; the line goes 10 s
after. While a task is open the badge breathes; when it lands in the partner,
and when the answer lands back, the ring turns half way so the sender's
colour lands on the receiver's side, two quiet rings leave it, and it turns
home. Both sessions show a toast at each hand-off, and the band above the
prompt shows `“alpha” 🔗 “bravo” · asked`, then `answered`.

To have a partner look over your change, pick `Ask “bravo” to review` from
the card's menu, beside Untie. The menu shows it only while no task is open
between the two and the session is not working. The partner gets a task
that names the session's folder, branch and commit, and the `git status`,
`git diff HEAD` and `git log` commands that show what is not committed or not
pushed yet. The change itself never goes with it, so the partner reads it as
it stands. In that turn the partner's own session refuses every call that
Claude Code does not mark as a read, every subagent and every task handed
back, so the review changes nothing; only the panel's own tools for reading
the partner and reporting the task line still run. Of the commands Claude
Code does not mark as a read, the partner may run only a git read of the
session's folder written as the task writes it, such as
`git -C '/work/app' diff HEAD`. The card shows
`Asked “bravo”: “review of main”` while it runs. The reply comes back to the
session as a prompt that starts `“bravo”'s review of main:`, or says why the
review did not finish, and the turn that prompt starts cannot hand the
partner a task. A review the panel refuses shows `not asked:` and the reason
on the card, for example when the partner waits on you or the folder is not
in a git repository. An earlier release of the panel cannot read the
partnership record while any task is open, and starts with no partners.

The review's read-only guard and the answer turn's ban on handing back a task
survive a plugin reload. An unknown turn keeps those restrictions in place.
A failed read-only check denies the tool call.

Untie from either card's menu (`Untie from “bravo”`), or drag one card out
of the pair and drop it anywhere else; Escape, or letting go where it was,
keeps the pair. A partnership survives `/clear`, a resume and a panel
restart, and ends when a pane closes or its agent exits. A panel restart
answers an open task as cut off.

What a partner whose model picked up hostile text (a README, a web page, a
tool output) can do through this, and could not before:

- make the other session act, unattended: each task runs at once with the
  partner's permissions, so a default-mode session can drive a bypass-mode
  partner in another repository, and nothing asks you first. The fence
  around a task frames it as the partner's request, not yours; it is not a
  boundary. The toasts show each hand-off, and untie stops it.
- reach the other's context when the profile changes: the partner's last
  reply rides in it, fenced and marked as its words.
- read the other's recent conversation, which may hold pasted secrets or
  command output. Nothing asks you first, in any mode.
- pass injected text both ways: a task's answer returns to the asker.

Partners are Claude Code with Claude Code only, and a worktree card cannot be
partnered: it stays docked inside its session's card.

## Remote control

A Claude Code card whose session has Remote Control on shows a small
broadcast glyph after its name. The panel reads that from the session's own
state file, so the glyph shows whatever turned Remote Control on, and goes
away with it.

Switching accounts drops Remote Control in every Claude Code session that
had it: Claude Code turns it off when the login changes. Keep remote control
after a switch, under Experimental in settings, turns it back on for you. It
starts off. With it on, after a switch the panel makes, by hand or on its
own, each session that had Remote Control on just before gets it back at its
next idle moment, never during a turn or while a prompt waits. The glyph shows
dimmed until then. It comes back under the account switched to, so
the session then shows in that account's sessions, on the web and on its
phones, and no longer in the old one's.

If it does not come back, the card says `Remote control did not come back:
run /remote-control` for up to ten minutes, and `daemon.log` says why: the
session stayed busy for five minutes, it never found its own state file in
that time, the plugin is not loaded there, the session took the request and
never answered, Claude Code refused the command (with its message), or the
command ran and did not connect. The panel leaves alone a session you
disconnected yourself before the switch. One you disconnect in the two
minutes after a switch that Claude Code did not drop it for, the panel turns
back on, since it cannot tell that apart from a drop.

## Commit heatmap

Commit heatmap, under Experimental in settings, adds a calendar of the
project's commits to an agent card's Details (right-click the card, then
Details): twelve weeks drawn as GitHub draws a year, a column a week with
Sunday at the top and today the last day drawn, in its weekday's row of the
last column, under the line `Commits, 12 weeks` and the total. A day's green says how many commits the
project got that day: none, 1 to 4, 5 to 14, 15 to 39, or 40 and more. The
steps are the same on every card, so two cards compare. Hover a day for its
date and count. The card itself shows nothing of it.

Every commit reachable from a branch, a remote branch or a tag counts,
whoever wrote it, on its author's date in this Mac's time; a stash does not. The panel asks git at most once a minute per project folder, and not at
all while the setting is off, which is how it starts. A card on another
machine, a card whose folder is in no repository, and a teammate nested
under its lead have no calendar.

## Claude's memory index in Codex

Hand Codex Claude's memory index, under Experimental in settings, gives a new
Codex session the index of what Claude Code remembers about the same project:
`MEMORY.md`, one line for each memory note. Codex gets it when a session starts
and after `/clear`, under a first line that names the file, its last change and
its size. A resumed session, a Codex subagent and Claude Code itself get
nothing from it.

The Codex hook looks for the file where Claude Code keeps the project's memory.
The project is the main checkout, so a worktree reads the memory of the
checkout it belongs to. The folder is the one `autoMemoryDirectory` names in the
checkout's `.claude/settings.local.json`, then its `.claude/settings.json`, then
`~/.claude/settings.json`. With none of them set, the folder is
`~/.claude/projects/<project>/memory`, where Claude Code keeps memory by
default. The hook sends nothing when the setting names a relative folder, or
when the file is missing, is a link or is over 256 KB.

Codex keeps a hook's text whole up to 10,000 bytes and cuts the middle out of
anything longer. The hook sends the index's first lines up to that, and a last
line that says how many it left out. The first line names the file, so Codex
can read the rest of it, and the notes it lists, with its own tools. On Codex
0.166 it ran `cat` on the file to quote a line the hook left out. What Codex
reads goes to OpenAI with the rest of the session, so the setting starts off.

## Sessions on another machine

A pane that runs `ssh host` or `et host` (Eternal Terminal) gets a card for
the Claude Code session running on that host, once the hooks are installed
there ([docs/integrations.md](integrations.md#hooks-on-a-second-machine)).
tmux on the other machine works too, plain or `tmux -CC`. mosh does not: it
redraws the screen itself and the state never arrives.

The card shows what the session's own state says and nothing this machine
would have to look up:

- its state and timers, and how many subagents are running
- the host, as a small computer glyph and the host's name on the facts line
- its name, from the title Claude Code gives the session, as on a local
  card; the folder's name when the pane carries no such title
- a question it is waiting on, with the same answer buttons a local card has

Model, context, cost, the task line, tasks, the branch, CPU and memory, the
remote control glyph and links are missing on a remote card: they are read
from files on the machine the session runs on. A Codex session on another
machine shows no card in most cases: Codex runs its hooks without a
terminal to report through.

Claude Code on a Mac reached over ssh can say `Not logged in` until the
login keychain is unlocked in that ssh session (`security unlock-keychain`).
The card then stays on `working` after a prompt, since the turn never ends.

You can focus a remote card and answer its question. An answer types one
key into the pane, a digit, `y` or Escape, never Enter, and only while all
of this holds:

1. `ssh` or `et` is what runs in the pane here, so the key goes to the
   other machine.
2. The agent held its terminal when it last reported, with no editor or
   pager in front of it.
3. The pane's title still carries Claude Code's mark. A shell prompt
   repaints the title once the agent is gone.
4. The session is waiting on you.
5. The question's options show no previews, since beside them a number only
   moves the cursor and Enter is never typed.

Otherwise the card shows no buttons and says `Answer in the pane:` with the
reason, a banner posted then has none either, and nothing is typed: a
banner's button that arrives after the checks stop holding is logged in
`daemon.log` as `typing refused`. The third check needs
the other machine's prompt to set a title. On a shell that sets none the
mark stays after the agent dies, and an answer's key can then land on that
shell's prompt line: a single key with no Enter, so nothing runs.

A reply and a slash command from the card's menu are refused on a remote
card: `replies do not reach a remote session yet`. Resume is never offered
there. A banner for a remote session has no reply field. A
remote card cannot be linked or partnered.

A set of questions, a multi-select, or a question too long to send
shows `A question is waiting in the pane` with no buttons; answer it in the
terminal.

When the connection drops and the pane is back at a local shell, the card's
state goes unknown and it takes no answer. Under Eternal Terminal a pane
closed here can leave the session running on the other machine, where the
panel no longer sees it.

While a pane reaches another machine, a row under the **Limits** head names
each machine: this Mac first, then the others in the order the panel lists
their first pane. A chip shows the machine's name and how many agents run
there. A dot on another machine's chip means at
least one pane here runs `ssh` or `et` to it in the foreground. A ring means
no pane does, and the tooltip then gives the card's reason, `the connection
to <host> is not in front here`. The tooltip also gives the age of the
machine's last event, by that machine's clock. The row shows only in the
open foot of a full-width panel: folded Limits and the compact panel leave
it out.

A machine gets a chip only from what a pane already carries: an agent's
state published there, or a `tmux -CC` connection to it. A pane at a shell
over a plain `ssh host`, with no agent state and no `tmux -CC`, adds no chip.

## Card style

The settings sheet has cards for Alerts, When a session waits for you,
When one finishes, Look, On a card, Rows, Experimental and Repository.
On a card starts folded and remembers whether you open it. Settings > Rows >
Show the foot's offers again restores both dismissed offers; the button
appears only while at least one offer stays dismissed.

The Look card holds Card style, Card anatomy, Follow the terminal's background,
Session colour on the tab ([The session's colour on its
tab](#the-sessions-colour-on-its-tab)), Text size, Shell names and Provider
badge. Card style picks how a session stands on the panel's background:

| Choice | What you get |
|---|---|
| Cards | Each session on a card of its own, with a gap between cards. The default |
| Hairlines | No card. A line the panel's full width runs between two sessions, and a session that waits on you or finished unseen is a band of amber or green across that width |
| Air | No card and no lines, and more room between sessions. A session that waits on you or finished unseen gets a rounded card of its own, with its ring |
| Inset rules | No card. The line between two sessions starts where the names start, and a session that waits on you or finished unseen is a rounded wash with no ring |
| Outlines | The card's outline only, a hairline, with the panel's background as its fill. A session that waits on you or finished unseen keeps its full card |
| Serenity | No card, 10 px between sessions and a faint inset line between two of them. A session waiting for input or finished unseen keeps its full card. At full width, an agent card shows its name, state, task title and progress bar. Activity shows only when it asks for input. Its facts are a remote host, high CPU or memory, and context from 70%, or from Rows > Warn above if that is higher. A teammate on a long turn is one line on its card, and one waiting for input keeps its own line. The card leaves out the branch, model and effort, tab title, working-teammate count, provider badge, report age, `Complete`, `Updated` time, and the subagent, task, scheduled and shell lists, whatever On a card and Provider badge say. Details gives the model, effort, context, scheduled prompts and how many subagents run. At full width, Details also shows the provider and branch, report age, working-teammate count, and subagent, task and shell lists of up to four rows each. Compact Serenity uses the ordinary compact Details. A plain terminal under Sessions keeps its tab title, branch and host |

Hovering a session tints it in every style. In Hairlines, Air, Inset rules,
Outlines and Serenity, a session at rest in the By attention order fades instead of
sinking toward the background. A worktree keeps its fork and its stem in every
style. Cards, Outlines and Serenity draw one outline round a worktree and its session;
in the other styles the hairline after the mark column is the only line
between them. A card you drag lifts as
a card in every style. Below 120 px a session is a row in every style ([A
narrow panel](#a-narrow-panel)). Details and the settings drawer keep their
own card.

Card anatomy chooses which title leads a full-width agent card:

| Choice | What you get |
|---|---|
| Task first | The active task title under the folder and state pill. The default for a new install |
| Name first | The session name above its task report. Saved settings keep this choice until you change it |

Task first shows the folder, the state pill, up to two lines of task title,
the question when waiting, the facts, and the reported percent and activity,
leaving the activity out when it repeats the pill's word.
Working and waiting cards also show `Updated 10 s ago`, using the newer of
the state change and task report. The folder tooltip holds the path and
session name, and on a worktree card what the fork means first.
An empty or finished task falls back to the name omp gave the conversation,
then the session name, and a Codex card leads with the name Codex gave it;
a finished task shows 100%. Done still means the session
finished while you were elsewhere. Narrow cards keep their layout.

In both anatomies a full-width agent card has no colour square or working
dots, only a worktree's fork, and Name first wears the same tinted `Working`
and `No report` pills as Task first.

Hovering a mark on a card explains it. The state pill gives the state in
words, with how long it has held while working, waiting or idle, and a `Long`
pill how long the turn has run. The provider tag and the corner mark name the
agent. The branch, model and tab title chips name what they show, as in `On
branch main`, and the effort letter names the reasoning effort. The worktree
fork says its repository's card sits above, and the tasks head repeats its
counts. Under Name first the session name adds its path.

## Which agent a card runs

Provider badge, under Look in settings, picks how a card says whether it runs
Claude Code, Codex or omp:

| Choice | What you get |
|---|---|
| Tag by the name | A small pill after the session name (on the folder line under Task first, its glyph and name in grey), tinted in the agent's colour, with its glyph and its name |
| Icon in the corner | The glyph alone in the card's top corner. The state badge moves over for it |
| Group by provider | Cards gathered under a head for each agent, Claude first. The Order choice applies inside each group. With one agent running there are no heads. The default |
| Off | The glyph stays before the model name, as the only sign of the agent |

With a tag or a corner mark the glyph leaves the facts line, so a card says it
once. The Order choice still applies inside each group.

## Shell names

Shell names, under Look in settings, picks the face of a shell card's name
in the Sessions group, which is a path or a command:

| Choice | What you get |
|---|---|
| System | The panel's own face, as agent names have. The default |
| SF Mono | SF Mono, a size smaller, since its letters run wider |
| Terminal font | The font of your default iTerm2 profile, at the panel's size. The daemon reads it when it starts, so a profile font you change later shows after the next iTerm2 start, or a [daemon restart](development.md#the-install-and-the-port). When the panel could not read it, the choice reads `Terminal font (not read)` and the names use SF Mono |

Agent names and the rows under a card keep their face whichever you pick.

## The terminal's background

Follow the terminal's background, under Look in settings and on by default,
paints the panel in the background colour of the pane in front of iTerm2's
key window. The daemon reads that pane's profile on every refresh, so the
panel changes colour as you move between panes. A profile with separate
colours for light and dark mode gives the one for iTerm2's current theme.

Every surface comes from that colour. The panel's canvas sits .03 darker than
the terminal in oklch lightness, so the panel reads as its own plane beside
it. On a dark colour the cards sit .03 lighter than the canvas; on a light one
they sit .015 lighter than the terminal with 60% of its tint. A card at rest takes a smaller step and the lines a
larger one, and the waiting, warning and finished
washes mix into the card's colour. A colour whose relative luminance, as the
Web Content Accessibility Guidelines define it, is under .4 gets the dark theme
and any other the light one, whatever the macOS appearance is.

On a dark colour the names soften too. A session's name and its report's
title are a pale tint of the terminal colour's own hue, and on a finished
card the title takes the green wash's hue instead. A grey or black
terminal colour has no hue, so there they are a plain soft white. A subagent's
or teammate's name is a warm paper white a step below. The inks never vary by
session, a resting name stays grey, and a card waiting on you keeps its
colours.

With no pane in front, the panel keeps the last colour it read. The line under
the switch names the colour, as `Terminal background #282a36`. When the daemon
could not read it, the line reads `Terminal background (not read)` and the
panel uses its own colours in the macOS theme. Turned off, the daemon does not
read the profile and the panel uses its own colours.

## The session's colour on its tab

Session colour on the tab, under Look in settings and on by default, tints
the iTerm2 tab of every card that wears a colour, as cs gives one to a
session. The colour is Claude Code's own for that name, the one cs draws in
its session pill, at 35% over the pane's background, so the tab stays a shade
of the terminal: orange over a `#fdf6e3` background is `#f0cab2`. A profile
with separate colours for light and dark mode gets a tint over each of its
two backgrounds, and the tab shows the one for iTerm2's theme.

iTerm2 colours a tab from its active pane alone, so a tab split into panes
shows the colour of the pane you are in. A teammate nested under its lead's
card, a card with no colour or with one outside Claude Code's eight, and a
session on another machine leave their tabs alone. When one pane holds more
than one card, as inside plain tmux, its tab takes their colour only when
they all share it.

The tint goes through the session's own profile, so your saved profile never
changes. A pane whose profile already shows a tab colour of its own keeps it,
and the daemon log says `tab colour own` once. A tab you recolour or clear
after the panel tinted it, from the tab's menu or by switching its profile,
stays as you left it while its card lasts: the panel neither paints over it
nor puts anything back, and the log says `tab colour recoloured` once. A
profile that keeps separate light and dark colours but has no background for
one of them gets no tint, and the log says `tab colour no background`.

Turning the setting off, or the card leaving the panel while its pane stays
open, as after `/exit`, puts back what the tint replaced. An agent that is
killed or crashes leaves an Exited card, and its tab keeps the tint while
that card shows. A new colour for the session repaints the
tab, and what comes back later is still the profile's own. A stopped daemon
leaves the tabs as they are; the next one finds its own tints by their
colours and keeps them, repaints them or turns them off.

While the setting is on, the panel also hides the white line iTerm2's Minimal
theme draws under the selected tab. It sets iTerm2's advanced setting
`MinimalSelectedTabUnderlineProminence` to 0, which iTerm2 applies at once.
The note under the switch, on or off, says `Also hides
iTerm2's line under the selected tab.` This is an iTerm2 setting, not a
profile one. When iTerm2 loads its settings from a custom folder and saves
changes to it, at once or when it quits, this change goes there too, so
every Mac that loads them from that folder loses the line as well, and gets
it back when the setting goes off or you uninstall the panel. The note
under the switch then names the folder, with a folder in iCloud Drive shown
as `iCloud Drive/...`. The daemon reads where iTerm2 saves its settings when
it starts, so after you change that in iTerm2, the note catches up when the
panel restarts.

Turning the setting off puts back what was there: the value you had, in the
type `defaults` kept it in, or no value at all. Uninstall does the same. A value
you change while the panel holds the line at 0 is yours: the panel leaves it,
even after the setting goes off, and the log says `tab underline taken back`
once. A line you had already hidden yourself is yours: the log says
`tab underline own` when the setting comes on, and the line stays hidden
after it goes off. The panel acts only when the
setting changes and when its daemon starts, and it keeps what it replaced in
`~/.claude/agents-sidebar-status/tab-underline.json`, so a restarted daemon
neither hides the line again nor loses what goes back.

## A long name

A card name too long for its row fades out at the edge. Every few seconds it
slides left to show its end, and its start comes back in from the right. It
stays still when Reduce motion is on in macOS accessibility settings.
In the narrowest panel it shows its end after an ellipsis instead ([A narrow
panel](#a-narrow-panel)).

Every other line a card cuts at its edge, the task, the last report, the
branch line, a shell's command, a teammate's line, moves the same way while
the pointer rests on that line: after a short pause it slides to its end at
the same pace, rests, slides back, and goes round until the pointer leaves
it, when it slides home from wherever it was. Its fade lifts while it moves,
so the end reads whole. Off under Reduce motion too.

## Teammates and worktrees

A teammate sits under the lead that spawned it, wherever it runs, and takes the
name and badge colour Claude Code gave it. Its line has no corner for a pill:
a turn past 20 minutes puts a warm `Long 25m` at the end of its facts line
instead, and the row says so aloud.

A session in a linked git worktree of another open session's repo (a cs feature
session in `<repo>@worktree`, for example) keeps its own card, right after that
session's card, and the two draw as one: one outline round both, square
corners where they meet, and a hairline between them that starts after the
mark column. The worktree card's mark is a fork in the main session's colour,
hung from the card above by a short line. It stays a fork while the session
works, and its state shows on the badge. Every worktree of one session stacks
under it inside the same outline, a hairline before each unless that card or
the one above it wears a ring, which is then the line between them. A worktree that
waits on you, or finished while you looked elsewhere, turns amber or green on
its own part of the outline only. Its name is the
feature, the part after the `@`, since the branch has its own chip. A worktree
directory without an `@` takes its branch as its name. A directory named
`<base>@<feature>` beside a session directory `<base>` docks there by name
alone, when git cannot tie the two (a symlinked home, a main shell parked in a
subdirectory). When the main session is not open, the card stays put, under
its own name.

## A waiting card

A card that starts waiting on you, for a question or a permission prompt,
while it sits past the top or bottom edge of the list scrolls into view,
whole, with its answer buttons. A card taller than the list shows from its top.
One already fully in view stays put.

A waiting card says what it waits on, under the title: the first question of an
AskUserQuestion (three lines at most, with "+1 more" when it asked several), or
the tool a permission prompt is for and the first line of what it would run,
under the reason the agent gave for it when it gave one (Codex's escalation
reason, Claude's command description). The line goes when the prompt is answered. An omp card shows its
question, or the tool and the command, the same way, through omp's extension,
but no buttons under them: omp draws its own prompts, so you answer in omp.
An omp session without the extension reports only that it waits, so its card
shows no question.

A Codex session with Auto-review on (`approvals_reviewer = "auto_review"`)
does not wait on you while its reviewer rules on a shell command: the card
stays working. A request for any other tool shows as waiting there too, even
when the reviewer answers it.

Under a question the card lists its options, a button each. The one the agent
suggests, whose label ends in "(Recommended)", is tinted green. Clicking one types
that option's number into the prompt, as if you had pressed it there. The
daemon types it only while that same question still stands, and only once.
Where the options show previews, the number only moves to that option, so
the daemon presses Enter after it.

When the agent asks more than one question at once, each click moves the card to
the next question, and after the last it shows Submit answers; Cancel stays
in the terminal. The daemon types each step once, in order. Claude Code says
nothing as it moves from one question to the next, so on a Claude card each
click first moves the prompt back to the question the card shows, with the
arrow keys, and then picks. A question you answered in the terminal is then
answered again by the card's click. On a Codex card the card counts only its
own clicks: answer a question in the terminal and the card's next click
answers the question after it. Answer a set in one place.

Under a permission prompt the card shows Yes and No, each marked with the key
it types: Yes is `y` on Codex and `1` on Claude Code, No is Esc on both. Neither
agent tells the panel which options its prompt lists, and Codex's vary from one
prompt to the next, so the rest, such as "don't ask again", stay in the
terminal. The daemon types the key only while that same command still waits,
and only once.

A question that takes more than one answer shows a box before each option.
Tick the ones you want, then click Submit. A tick types nothing. Submit types
the ticked numbers into the prompt and submits them, once, while that same
question still stands. Inside a set the button reads Next, and the set ends
with its own Submit answers step. The card can't see boxes you tick in the
terminal, and its numbers would flip them, so tick in one place. A Codex card
shows these options without boxes; answer it in the terminal. Under Name first, a
card that asks drops its task line, model line and folds, so its height barely
moves; under Task first only the folds go. They come back once you answer.

A card that asks holds still under the pointer. An update that would move it,
a card above it growing or the order changing, waits until the pointer leaves
the card, you answer the question, on the card or in the terminal, another
question replaces it, or the panel goes out of sight. The card ignores a click on an
answer, Yes or No in the 0.7 seconds after it moved, so the option that slid
under the pointer is never the one that counts.

## A narrow panel

Below 192 px the panel turns compact, and it turns back above 208 px, so a
panel dragged across the line does not flip on every pixel. The width is the
panel's over Text size, so a larger text size turns it on in a wider panel.
No setting turns it on or off.

A compact agent card is its name, then a line with its state badge, `+2`
for two running subagents, and one alarm word at most: `cpu` or `mem` while
its processes are heavy, else `ctx 87%` once the context reaches 85%. Under
that line it shows only what the state needs:

| State | Under the badge line |
| --- | --- |
| Waiting | The question, or the tool and its whole command over three lines at most, then the answers stacked, each the card's full width. The suggested answer stays green and drops "(Recommended)" |
| Working | A green `Working` outline, what the session is doing over two lines at most, and a thin bar from its own percentage. Past 20 minutes the badge reads `Long 25m` |
| Silent | A working session whose report has gone stale: a grey `Silent 6m` outline and its last words after `Last:`. No bar |
| Done, Idle, Exited | Nothing more. An exited card keeps its Resume button |

Teammates get no lines. One waiting on you puts its gate on its lead's card,
under its colour and name, with its own answers, and the lead's badge reads
Waiting while it does. The arrows and Cmd+Enter reach that gate as they reach
a teammate's line. The facts line, the agent's tag or corner mark, the
subagent rows, the task list and the background shells stay off the card.

Waiting on you goes from the foot, since each waiting card carries its own
question. Limits is one line: the account your sessions run on, its fullest
window as a bar and a figure, and the time to its reset once that window is
tight, at 80% or within 30 minutes of the reset. Like a folded tile, it passes
over a model limit full on every account for the next limit with room. Hover
the line for every window, and for when a model passed over returns. A switch Auto-switch would make soon gets a line of its own, and Codex
gets a line of the same shape only while its own fullest window is tight. The
chevron opens the whole Limits. Clicking Limits or the free space in the Limits head folds it back to one line,
and so does the panel narrowing again after it has widened. Without an active
account, or when the account store fails, the foot keeps its full layout.

The Limits head takes the hover tint and keyboard focus ring across the row
on the same 24 px band as the fold heads, 3 px above and below its 18 px head.
Its switch and chip stay separate from the fold target. The tint drops over
the switch, and clicking **Auto-switch** changes the switch too.

Below 120 px, and back above 136 px, a session is a row, not a card, with a
hairline between rows: its colour square and its name, the badge across the
row, then what the session is doing or asks. A session in no known state reads `No
report`. A long name keeps its end after an ellipsis, since names that share
a start differ at the end. Two sessions under one name show an ellipsis and
the last four characters of their branches after it, or `·1` and `·2` when the branches
don't tell them apart. The subagent count and the Remote Control glyph go. A
row has no answers: a click brings its pane forward, and you answer there.
The foot is the chevron and a hairline for the window the one-line foot shows, with its
figure only once the window is tight. The bar drops the release number and
keeps reload and the gear; an update on offer still shows, its Update button
on a line of its own above them.

Details, from the right-click menu, works at every width and still shows the
model, the context and the CPU or memory figure. The branch, the subagent
rows, the task list and the background shells come back once the panel is
wider. In Serenity, these return in Details rather than on the card.

## What fills the context

Pick Details from a Claude card's right-click menu: its details card opens
and stays until Escape or a click elsewhere. Every row on it explains itself
on hover: a gauge says what its figure measures and when the window resets,
CPU and Memory name the program using the most, and each flag says what it
stands for. Context breakdown then runs Claude Code's own
`/context` on a throwaway fork of that conversation: hooks off, nothing saved,
no model call. It takes a few seconds, and the result stays in the card until
you read it again. It needs Claude Code 2.1.299 or newer: an older one prints
a list the panel does not read, and the card says `claude printed no JSON
object`.

The bar is the whole window: the conversation, system and tools, memory, and
agents and skills in their own colours, then the reserve kept free for
compaction, hatched. Under it every category has a row with its own bar. The
deferred tool rows sit apart, since Claude Code loads them only when a tool
runs and does not count them. Only the conversation's rows are this
session's own; the rest are what a new session in the same directory would
load now. The figures are `/context`'s estimate, so they can differ from the
Context percentage above them, which Claude Code measures on each turn.

Custom agents, Memory files and Skills open on a click to show what is in
them, biggest first: each memory file by its path, each agent and skill by
name, eight of them with a bar each and one line for the rest (`358 more,
5k, 292 under 20 each`). MCP tools in the line about what loads on use opens
the same way, one row per server with its tool count, since that is where
`/context` counts them. The other rows have no parts to show. A list
`/context` prints in a shape the panel cannot read still opens, and says why
in its place; the rest of the breakdown stands. A row stays open through a
fresh read, and a card grown taller than the panel scrolls inside.

## Sounds

Settings > Alerts holds Play sounds and Volume. The Sound switches under
When a session waits for you and When one finishes choose which events play
a sound. They hide while Play sounds is off.

The daemon notices each change as it reads the sessions and plays the sound
itself, so sounds, banners and the focus move come whether or not the panel is
open in any window, and each moment plays once, even for a session shown in
two panes (two tmux clients on it). A setting takes effect on the
next change, in every window. At most two sounds play at a time. Each alert,
and any problem playing one, is written to `daemon.log` in
`~/.claude/agents-sidebar-status`.

## Banners

Settings > Alerts > Show macOS notifications enables banners. Each event card,
When a session waits for you and When one finishes, has a Notification switch.
Those switches hide while Show macOS notifications is off.

The banner carries the question or the permission as the agent wrote it, as does the line under the tab; only a token, key or password in a command is masked. The banner uses the session's name as the card shows it. The panel posts nothing for the session you are looking at, meaning the session in front of its window
while iTerm2 is the frontmost app. A session in another tab of the same window
still gets one, since that is exactly when you can't see it.

A session has one banner at most, and going back to work takes it down, as
does closing the session. A click brings the session forward; when it sits in
a hotkey window that has rolled away, the panel presses that window's hotkey
first, read from the profile that owns it (System Events needs leave to send
keys). A hotkey that is a double-tapped modifier alone has no key to press,
and the log says so. Banners need the app that `install.sh` builds. A
banner plays no sound of its own; the sound switches are separate. A session
waiting on something other than a question or a tool it wants to run says it
"needs you".

macOS shows a single action inline and folds two or more into an Options menu,
so a question is always a menu. The banner sends keystrokes only while its question is still open, so a prompt you already answered in the
terminal gets nothing. A Reply to a finished turn types nothing once the
session waits on you, its agent has exited, or another program is in front of
its agent. omp sessions get
no banner from the panel, since omp posts its own.

## A finish you have not seen

A banner lasts five seconds. A card whose turn ended while you were not
looking at that session wears a green Done badge in place of Idle until you do.
Looking means the same as for banners: the session is in front of its window
while iTerm2 is the frontmost app. The sound and banner switches don't change
it, and omp cards get it too.

The When one finishes card in settings adds three marks to that badge,
each its own switch, and the tab says `done` under its title
([The status under a tab](#the-status-under-a-tab)):

| Setting | What you get | Default |
|---|---|---|
| Lift its card first | In every order, the cards that wait on you come first, then the ones that finished unseen, then the rest, each run in the order it had. A card moves only when its state changes, and a lead brings its teammates and worktrees with it; a docked worktree or a linked partner that finished lifts the block it sits in | On |
| Green wash | The whole card in the panel's green, its name in the full ink, under the amber of a question in weight | On |
| Done as the pane's badge | The word Done as iTerm2's badge in that session's pane, in the panel's green at about a third, large and faded. Its size, font and position are your profile's Badge settings: iTerm2 lets a session change only the text and colour. A pane whose badge already says something keeps it, and the daemon log says `badge busy` once | On |

The badge goes through the session's own profile, so your saved profile
never changes; what it replaced comes back when it clears. Inside
iTerm2's tmux integration every tmux pane is its own session and the mark
lands on the right one; inside plain tmux one pane hosts several, and the
mark covers the whole pane. A daemon that starts finds a badge reading
exactly `Done` left by the daemon before it and clears it.

Going to the session from its card, or a banner or a block bringing it
forward, takes the mark off at once. Moving to the session inside iTerm2 takes it off at the next
reading, within two seconds. A new prompt takes it off, and so do a block, an
exit and closing the session. A Stop hook that runs a command and briefly
flips the session back to working does not, since that is not a new turn.

The marks live in the daemon's memory, so a daemon restart clears them. A
turn that went unknown before it ended is not counted as finished. Two panes
showing one conversation each keep their own mark.

## The status under a tab

An agent's tab shows what its session is doing under the title, in the
panel's words:

| The card says | Under the tab | Dot and text | Detail |
|---|---|---|---|
| Working | `working` | iTerm2's own working orange | What the agent says it is doing, when it says |
| Waiting on you | `needs you` | The panel's amber | The question, or the tool asking for permission and what it wants, else what it was doing |
| Done (finished while you looked elsewhere) | `done` | The panel's done green | Nothing |
| Idle | `idle` | The panel's grey | Nothing |
| Exited, no report | Nothing | Nothing | Nothing |

The number beside the word counts running subagents and background shells. A
teammate's pane shows working and needs you but never done or idle, as on the panel.
The panel writes remote sessions' tabs as it writes local ones. When one pane
holds more than one agent, as inside plain tmux, its tab shows the one that
most needs you.

Settings > When one finishes > **Status under the tab title** turns this on and off
(default on). With it off, or when the panel stops, the words come off the
tabs. A daemon that died without taking them back finds its own words at its
next start, by their colours, and corrects them.

iTerm2's Claude Code integration writes the same line from hooks of its own,
`cc-status` in `~/.claude/settings.json`. While those hooks are there, the
panel leaves Claude tabs to them and writes only Codex, omp and remote tabs,
and the foot offers **Remove iTerm2 hooks**, which deletes only the
`cc-status` entries from the file (it keeps a copy beside it as
`settings.json.before-tab-status`), or **Not now**. The button's tooltip names
the file, the copy and the restart. Settings > Rows > **Show the foot's offers again**
brings the offer back. Once the hooks leave the file, the panel takes over the words
iTerm2 left on Claude tabs. A Claude session already open when the hooks go
keeps running them until it restarts, so its tab can flip between iTerm2's
words and the panel's until then. To put iTerm2's hooks back, restore the copy
or run iTerm2's Claude Code integration setup again.

The line needs iTerm2 3.7.6 or later. On an older iTerm2 the setting says
"Needs iTerm2 3.7.6" and the panel writes nothing.

## Focus

Settings > When a session waits for you > Bring it forward enables the focus
move. Go back once it resumes sits under it and hides while Bring it forward
is off.
It only goes back if you are still on the session it brought you to. If you
moved somewhere yourself, you stay there. Blocks in a row unwind in order.

## Plain terminals

A plain terminal takes its path as its name, as its prompt writes it. Its tab's
title sits on the line below, before the branch, and the panel leaves out a
default title: the shell's name or `user@host:path`.

At its prompt it shows a shell mark in its session colour where a narrow agent card shows
its square. While it runs a command it shows the working dots and the command's
name, and it goes quiet when it's back at its prompt.

## The task line

The session writes its own report: a task title, what it's doing now, and a rough percentage. Under Name first, a report older than five minutes fades and puts `Last:`
before what it said, with its age beside it. A hundred percent shows `Complete` with a green tick and stays until a new
request starts a new task.

The ticks show the estimate as a count you can glance at. They are not the
solid bars of the limit meters in the foot, on purpose: those go green, amber
and red, and that would make being nearly done look like a warning. Task
first's bar is solid, and a finished task reads `100% · Complete`, with no
tick.

A Claude session reports through two tools the plugin registers,
`task_begin` and `task_report`; a Codex session runs the plugin's `task.py`.
`docs/task-line-design.md` has the hook cadence and the note format.

## Tasks

Claude Code keeps a session's task list under `~/.claude/tasks/<list>/`, one
file per task, named by `CLAUDE_CODE_TASK_LIST_ID` or `session-` plus the
first eight characters of the session id. The hook reads the list on every
event, since the tool calls that change it are the events, and hands the
panel the pending and started items plus a count of completed tasks.
The fold's head can read "27 open · 11 started · 40 done"; zero counts stay
out, and without both a started and a done count it reads "5 tasks · 3 done". Opening it shows the open items only, started ones first, then
pending, each run in the list's own order. A started task wears a
half-filled circle in the dim ink and a pending one an empty ring of the
same size; neither moves, since a status is what the session set, not
proof of work on that item. A subject is clipped to 240 characters and the whole of
what the panel got sits in the row's tooltip.

Codex keeps its plan in its `update_plan` tool instead. Each call carries the
whole plan, so the hook keeps the pending and running steps of the latest one
and shows them in the same fold until the next call replaces them; a plan
with every step completed leaves no fold. Codex publishes no done count:
its head can read "3 tasks · 2 started". Codex 0.160 ships the tool off, so
its sessions make no plan until `~/.codex/config.toml` has:

```toml
[tools.update_plan]
enabled = true
```

Settings > On a card > Task > Task list turns the fold off; that switch hides while
Task is off.

## Scheduled prompts

The prompts a Claude session has scheduled with `/loop`, CronCreate or
ScheduleWakeup fold into one line under its tasks ("2 scheduled"). Each row
has the prompt and when it runs, in local time: a recurring one reads
"every 10 min", "every 2 h at :30", "daily at 09:00" or "next Mon 09:00", and
a one-shot "once at 13:31" or "once Fri 13:31". Claude Code lists them only
when the session's turn ends, so a one-shot that has fired reads "due" until
the turn it started ends, and a resumed session can show its old list until
its first turn ends. An expression the panel can't read shows as written,
and a token, key or password in a prompt shows as `***`. Details has the
same list in one Scheduled row.

## Background shells

When the last shell ends, the line stays for a few seconds, dimmed, as
"1 command finished", so a run of short commands doesn't grow and shrink the
card each time. A shell whose command the panel can't parse shows `?`.

## Rebuilding the panel

Right-click reload and choose **Rebuild the panel** if the panel stops drawing
or responding to the pointer. This opens a fresh view in every window.
For a `STALE` banner or a blank panel after Update, see
[Troubleshooting](troubleshooting.md).

## Updating

The bar's left end names the release the panel runs, or reads
`unreleased checkout` in a checkout with no `VERSION` file. Clicking it opens
the releases page of the GitHub repository you cloned the checkout from in
your browser, or of the public mirror for a checkout with no `origin`
remote; a checkout cloned from anywhere else shows the number as plain
text. The last card in Settings, Repository, names that same repository and
opens it or its Release notes; a checkout cloned from anywhere else has no
such card. Once a day, once at
start, and on every press of the reload button, the daemon lists the tags on
the repository the checkout was cloned from; when one is newer, the
line adds an Update button, which names the new release in its tooltip. Pressing it fetches that
release into the checkout the daemon runs from, checks it, runs `install.sh`
again and restarts the daemon. The port changes with the restart, so the bar reads
`restarting, reopen the panel` and the panel goes blank: reopen it from
View > Toolbelt > Agents.

Update takes a release only when all of these hold, and otherwise refuses
with the reason beside the button, leaving the checkout and the daemon as
they were:

- git is 2.34 or newer, the first that checks SSH signatures
- no tracked file in the checkout has local edits, which would run unsigned
- the new commits continue the checkout's history in a straight line, with
  no merge commits, and every one carries an SSH signature by a key the
  commit before it lists in `release-signers` and does not list in
  `release-revoked`
- or, when the mirror's history was rewritten and continues nothing in the
  checkout, its newest commit carries an SSH signature by a key the
  installed release lists and does not revoke, it revokes every key the
  installed release revoked, and it adds no file that sits untracked in the
  checkout. The checkout must itself be a signed release, so commits of
  your own are never dropped. The checkout then moves to that commit
  instead of fast-forwarding
- the new `VERSION` is newer than the installed one. It is read from the
  signed commit, not from the tag that offered it, so a stray tag cannot hold
  a release back

An install that fails after that also puts its last line beside the button,
and puts the checkout back on the release that runs, so the offer stays and
the next press tries again.
The whole message is in the daemon's log under Scripts > Manage > Console.

## Uninstalling

Choose **Uninstall the panel…** at the bottom of Settings. It names the
panel, hooks, settings and state it removes; the checkout stays. It also
counts the saved account logins it deletes, including those that need a new
login. **Keep my account logins** starts off. Turn it on to keep
`~/.config/agents-sidebar/accounts.json` and its Keychain items; the message
changes to say the logins stay. The other panel data still goes.
Choose **Uninstall** to confirm, or **Cancel** to return. Escape or a
click outside the confirmation also cancels before you submit.

After acceptance, the card reads **Uninstalling the panel**, says the panel
stops once the uninstall finishes, and shows the uninstall log's path. A refused or failed request keeps the
confirmation open, keeps your choice and shows the reason. Cancel and reopen
to start with **Keep my account logins** off again.

You can also run `agents-sidebar uninstall`. Running the command confirms
the removal; it asks nothing else and works without a running daemon.
It deletes saved logins by default. Run `agents-sidebar uninstall --keep-accounts`
to keep them, or `./uninstall.sh --keep-accounts` from the checkout.
It prints the checkout path and a quoted command to delete it. See
[what uninstall removes and keeps](integrations.md#uninstall).

Your saved statusline comes back unless its absolute script path is missing;
then uninstall removes `statusLine` and warns with the path. iTerm2's line
under the selected tab comes back too, unless you hid it yourself or changed
its setting after the panel hid it ([The session's colour on its tab](#the-sessions-colour-on-its-tab)). With the bridge
installed, a command that exits 127 displays
`status line: <command or script> not found`. Other failures keep its last line.

## Resuming an exited agent

When an agent's process dies (killed, or crashed) and its pane drops back to a
shell prompt, the card stays, faded, with an Exited pill. Resume types the
command that reopens the same conversation at that prompt and brings the pane
forward:

| Session | What Resume types |
| --- | --- |
| A cs session (the directory has `.cs/`) | `cs . --resume`, which reopens the recorded conversation without asking |
| Claude Code | `claude --resume <conversation id>` |
| Codex | `codex resume <conversation id>` |

A cs session needs a cs with `--resume`, which `cs --help` lists. A cs
without it prints `Unknown session command: --resume` and opens nothing.
Type `cs .` at that prompt instead. It asks whether to continue, and Enter
resumes.

The button shows only while that is safe: the pane is at a shell prompt, its
directory still exists, the conversation saved a transcript (an agent killed
before its first reply has nothing to resume), and it is not open in another pane. After
a click it stays away until the agent reports again, or for a minute if the
pane comes back to its prompt without one. An agent
that ends with `/exit` leaves no card behind, and omp sessions have no Resume.

## Past sessions

The heads of **Past sessions**, **Ports**, and **Activity** take clicks on a
24 px band across the whole row, 6 px into each gutter and 6 px above and
below the head's line. The hover tint and keyboard focus ring cover that
band; the compact foot keeps its smaller targets.

Above the limits, **Past sessions** folds open a log of the conversations written to
in the last week that have no card now: a cs session as one entry, named after
itself, at its newest conversation; any other directory as one entry per
conversation, its first prompt in dim text after the directory's name. Each
day has a head that names it **Today**, **Yesterday** or by its weekday, and
each entry starts with the local time, hours and minutes, that its
conversation was last written to. The daemon reads
Claude Code's transcripts under `~/.claude/projects` when the fold opens, not
with every frame, and leaves out what is open now, what ran in a directory
that is gone, and what ran inside Claude Code's subagent worktrees or a
session's own `.cs` folder. The list holds the newest thirty.

An empty reading says "Nothing to resume from the last 7 days; the ones open
now are on their cards." A failed reading keeps its reason on a separate line.

On the first read, space for a day head and six 24 px entries is present at
once. The placeholder rows fade in after 180 ms and stay still. A hairline
under the head fills from the left to 88% once over 1.6 seconds, then waits.
The rows replace the placeholders when the reading arrives. Reopening reads
again, with the cached rows under the gauge and no placeholders. With reduced
motion, the placeholders appear after the same delay without a fade or gauge.

The whole entry is the button that resumes it, and **Resume** shows over its
right end while the pointer or the keyboard focus is on it. While the tab opens, the
entry reads "opening…" and takes no click for fifteen seconds, or until the
daemon refuses; a refusal shows on its own line under the entry.

Resume opens a new tab in the entry's directory and, once its shell is up, types
`cs . --resume` for a cs session or `claude --resume <conversation id>` for
anything else. `cs . --resume` reopens the session's recorded conversation
without asking, and needs a cs with the flag, as on a card (see [Resuming an
exited agent](#resuming-an-exited-agent)).
A shell that takes more than ten seconds to appear gets nothing typed,
and the daemon's log says so. Codex and omp conversations are not listed.

## Ports

Under **Past sessions**, **Ports** folds open a list of the TCP ports
listening on this Mac and what holds each one. The daemon reads them with
`lsof` when the fold opens, never on a timer. Listeners under one of the
panel's sessions come first, by port: each row is the port, the program, the
card it runs under, how long it has run, and Stop, which shows while the
pointer is on the row. Every other listener folds
under one line, **N other listeners**, which opens them below it. When none
belongs to an agent, that line reads **N listeners, none under an agent**,
or **1 listener, none under an agent** for one. The whole line takes clicks,
the hover tint, and the keyboard focus ring. Hover a row
for its addresses, its pid and its command, with a token, key or password in
the command shown as `***`.

An empty reading says **No listener found at HH:MM**, using the local time
the reading arrived, followed by **Look again**. That button reads the ports
again. Its text uses the action ink and shows a ring on keyboard focus.

The first read reserves three 19 px rows with port pills. The placeholders
and head gauge use the same delay and motion as Past sessions. A reread keeps
the cached rows until its answer arrives. A failed reread keeps those rows
and shows the reason above them.

A row's session is the card whose process tree holds the listener: its agent
and everything below it, and any Codex job that card's Claude session started
through the codex plugin, which runs outside that tree. A row names a program
an interpreter runs by its script, so `python3 serve.py` reads `serve.py`.

Some listeners never show. The fold leaves out the agents' own ports, since
Claude Code and Codex each listen on a loopback port of their own and stopping
one ends its session. It leaves out the panel's own server for the same
reason. `lsof` run as you cannot see a process run as root or as another user,
so their listeners never show either. A Claude Code or Codex with no card,
such as one run outside iTerm2 or a Codex that has not taken its first prompt,
has no agent to leave out, so its own port shows with the other listeners.

Stop sends `SIGTERM` to the row's process after four checks that the process
is the one the list showed: the row is in the last reading, its process has
not become a card's agent since, it still listens on that port, and it started
at the second the reading gave, since another program can take over a freed
pid. The daemon refuses anything else, and the reason shows under the row.
Stop sends `SIGTERM` alone, to that one process: it never follows with
`SIGKILL` and never signals the process group. The fold reads the ports again
a second after a Stop. A program that ignores `SIGTERM` stays listed, and its
Stop comes back after 15 seconds. The daemon's log records each Stop it sends.

## Activity

Under **Ports**, **Activity** folds open what Claude Code and Codex did on
this Mac over the last seven days, read from their own logs. The head line
gives the days, the prompts and the tokens: a prompt is one typed into Claude
Code or a Codex turn, and the tokens are both programs' together. When both
worked in the span, one bar under the head splits the tokens between them, the
larger part from the left, with each program's name and figure at its own end.
A bar a day follows, oldest first, as tall as that day's tokens against the
busiest day's, with the day's total and its weekday under it; today's bar is
in the text colour. Then come the ten projects with the most tokens, each with
its folder's own name and its total. Where two of the week's projects end in
the same folder name, case aside, each name starts with the parent folders
that tell them apart, in grey, as in `kiln/repo` and `moss/repo`, even when
only one of them has a row. A cs session's `@variant` follows the name in
grey. A name too long for the row loses its parent folders first, and never
its variant. The whole path is in the row's label for assistive tech; the fold
shows no tooltip. **+N more projects** counts the rest, with their tokens, and
does not expand. A project in or under `/tmp`, `/private/tmp`, `/var/folders`
or `/private/var/folders` is a scratch dir: it gets no row, and one grey line,
**N scratch dirs**, counts them with their tokens; the head, the split and the
day bars still count them. A project whose week was cache reads alone has no
tokens here, so the fold leaves it out of the rows and both lines, as a picked
day leaves out a project with none that day; the head still counts its
prompts. Work in a worktree under `.claude/worktrees/` counts to the checkout
it came from. Click a day's bar, figure or name and the fold shows that day
alone: the head names the day with its prompts and tokens, its bar takes the
ink and its name an underline, and the rows are the projects that worked that
day, by that day's tokens, each named as in the week. Click it again for the
week.

If the whole week has no prompts or tokens, the fold says **No prompts or
tokens in `~/.claude/projects` or `~/.codex/sessions` over the last 7 days.**
A warning about logs it could not count in full stays below that note. Picking
an empty day keeps the week's chart and shows **Nothing on Tuesday · Show the
week** below it. The weekday is the one you picked. **Show the week** returns
to the week's figures without reading the logs again and puts the keyboard
focus on the Activity head.

While the first read runs, the fold holds space for its head, split, seven
weekday slots and three project rows. After 180 ms the still placeholders
fade in, and a hairline under the head fills to 88% over seven seconds and
stays there until the read ends. Later opens keep the previous report visible
while the hairline runs. If a later read fails, its reason appears below the
kept report. With reduced motion, the placeholders appear after the same
delay, with no fade or hairline.

The daemon reads the logs when the fold opens, never on a timer, and again
each time it opens. The first open reads every log written in the week, which
took about nine seconds of CPU on one machine; later opens read only the logs
written since. The daemon keeps what it read of each log in a small file,
`~/.claude/agents-sidebar-status/activity.json`, so the fold reads fast after
a restart too. An update that changes how the daemon reads the logs, a move to
another time zone or a damaged file makes the next open read every log again.
The narrow panel's one-line foot leaves the fold out, as it does Past sessions
and Ports.

Claude's tokens are its input, output and cache-write counts, and Codex's are
its total less its cached input. The fold leaves out cache reads, each
program reading the conversation so far again: on one machine's week they
were about 98% of all tokens. It shows no dollars. Claude Code's logs carry
a conversation's cost as one running figure, on lines with no time, so they
hold no cost for a day, and Codex's logs carry token counts and no cost at
all. A log the report could not read in full shows as **N logs not counted in
full**, in the warning colour; its label for assistive tech gives each file
and the reason.

## From a script

`install.sh` links the `agents-sidebar` command into `~/.local/bin`. Its
`status` and `wait` commands read from the daemon, so the panel has to be running.
`uninstall` runs the removal script from the command's checkout without a daemon.

```sh
agents-sidebar status                 # one line per agent
agents-sidebar status --json          # the rows as the panel has them
agents-sidebar wait atlas             # until atlas waits on you or is idle
agents-sidebar wait current --until done --timeout 600
```

`status` prints each agent as its session id, label, provider and state,
separated by tabs. A Claude agent's provider is `claude`, and an agent whose
state the panel cannot read shows `unknown`. When the daemon says its reading
is stale (the panel's `STALE` banner), `status` still prints the rows, says on
stderr that they may be out of date, and exits 1.

`wait` returns once the session is in one of the states you ask for and prints
its row as JSON. `--until` takes `working`, `blocked`, `idle`, `done`,
`unknown` or `exited`, once or more; without it the wait is for `blocked` or
`idle`. `done` is a turn that ended while you were not looking at that
session, the card's unseen mark. `idle` matches it too.

The target says which session:

| Target | Which session |
| --- | --- |
| An iTerm2 session id | That one, as `status` prints it |
| A label | The one agent with that label. Two tabs on the same repo share one, so when two agents carry it the command lists both and stops |
| `current` | The pane the command runs in, found by its terminal |

`current` goes by the terminal, not by `$ITERM_SESSION_ID`. Inside tmux that
variable comes from whichever pane started the tmux server. Codex runs its
hooks in one process shared by every Codex pane, and there it names the pane
that started that process. Either way it can name another pane that is still
open, so a command with no terminal anywhere above it stops with exit 1
rather than wait on the wrong agent. A command an agent runs has no terminal
of its own, so the terminal of the nearest process above it counts, which is
the agent's pane. Two agents on that one terminal stop it the way a shared
label does.

A state that already holds returns at once. While the daemon says its reading
is stale (the panel's `STALE` banner), nothing matches until the reading is
fresh again, and that holds from the moment the wait connects. If the daemon restarts, for an update say, the wait connects to
the new one when it answers within 10 s and carries on. The wait settles on a
session at the start, so a label that later moves to another pane does not
move the wait.

| Exit | When |
| --- | --- |
| 0 | The session is in a state asked for |
| 1 | The timeout passed, the session closed, nothing answers to the target, the daemon is not running, or `status` printed a stale reading; stderr says which |
| 2 | An argument it cannot use, a label more than one agent carries, or two agents on the terminal `current` names |
