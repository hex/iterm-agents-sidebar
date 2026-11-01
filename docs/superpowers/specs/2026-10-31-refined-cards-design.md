# Refined cards: the task first, the session's state as a pill

Designed 2026-10-31 on `main`, from a mockup round. Two mockups were drawn
by another tool, then both were rendered on the real `page.html` at 380 px
in a lab (dark and light, with measured ink bands), and the refined-card
one was picked from those renders, over a grouped-by-status one and over
the card as it is today.

Decided (2026-10-31):

- **The task leads the card** (picked: "task title where the name is" over
  the name first). A session with a task line shows the task's title large.
  A session with none shows its name there, as today.
- **The folder names the session above the title**, in the dim ink, with
  the state pill at its right (picked: "folder line plus pill" over the
  name in the facts line). The folder is the path's last component; the
  whole path is the tooltip.
- **The state is a pill** (picked: a filled amber pill for Waiting for
  you, an outlined green one for Working, an outlined grey one for Idle,
  and the Done badge the page already draws). One dominant status per
  card, so the activity word under the title is dropped when it repeats
  the state.
- **A recency line** reads "Updated 10 s ago" from the freshest of the
  state's clock and the task line's report (picked over no recency line).
- **A finished card keeps its marks** (kept: the Done band and the green
  wash, decided 2026-10-18). **No left accent border** (kept, 2026-09-16).
- **The identity square goes** from the card face (picked: the folder
  line names the session; the square stays in Details and in the queue).

Kept: one badge style at every width, names in the state's ink, plain tint
hover, no motion on resting chrome, decoration in Details.

## Decided after the spec's first draft (2026-10-31)

1. **A setting, not a replacement.** `card_anatomy` holds `task` or
   `name`, shown in the Style card as Card anatomy with the choices Task
   first and Name first. The default is `task` for an install that never
   saved settings; a saved sheet keeps `name` until the choice is made
   there (picked over replacing the card for everyone: the lab measured a
   Working card about 2.7 times taller, four cards per 380 px of panel
   height where eight fit).
2. **No Open session button.** The whole card focuses its pane on click,
   as today (picked over the mockup's button).
3. **The recency line shows on working and waiting cards only.** An idle
   or finished card's age states a resting fact (picked over every card).
4. **The task bar is the request's progress, not a completion count.** The
   session reports a percent through its task line; the words under the
   bar are that percent and the activity, never "N of M tasks complete",
   which the lab's fixture invented and no row carries.

## 1. What is known before the build

- A card's row carries `label` (the session's name), `path`, `state`,
  `working_since`, `blocked_since`, `idle_since`, `task` (`title`,
  `activity`, `percent`, `done`, `reported_at`), `tasks` (open checklist
  items), the facts (`branch`, `model`, context), `question` and its
  answers, `subagents` and `shells`. Nothing new is needed from the daemon
  for the folder line, the pill, the title or the recency line.
- The lab transform (`lab/variants/mockup-a.js` in the lab worktree) built
  every element from those fields and threw on a missing one; its CSS is
  the starting point for the page's rules.
- Measured in the lab at 380 px: the title at 17 px wraps to two lines and
  clips after them; the folder clips at 272 px beside the pill; question
  options, child rows and shells fit unchanged.
- The compact and tiny tiers (`html.compact`, `html.tiny`) have their own
  layouts and are not touched by this design.

## 2. The page (`page.html`)

- Root key `data-card-anatomy` with `task` or `name`, from the setting;
  every rule of the refined look sits under `html[data-card-anatomy="task"]`
  so the name-first card paints as before with no rule of its own.
- The agent row's stack, in order: folder line with the pill at its right;
  the title (task title when a task line exists and is not done, else the
  session name); the question's text when waiting; the recency line; the
  facts line; the task bar; then the existing folds (subagents, shells,
  open tasks).
- The pill is the existing `.word` badge, restyled under the key: filled
  for Waiting for you, outlined otherwise. Done keeps its badge.
- The recency line repaints on the page's 30 s tick, from the clocks the
  row already carries, and never pushes a frame.
- The title glides when clipped, as a long name does today (the `.run`
  element stays the glide's subject).
- The queue, the past sessions fold and the foot are unchanged.

## 3. Settings

`card_anatomy` in `save_settings`, `"task"` or `"name"`, default `"task"`,
shown in the Style card as "Card anatomy" with the two choices.
Settings defaults reach only installs that never saved; an install with a
saved sheet keeps "name" until the choice is made there.

## 4. Failure modes, written before the code

1. **A task line with no title.** The title is the session's name; the
   pill and recency stay.
2. **A finished task line** (`done`). The title goes back to the name and
   the bar shows full; the Done badge is the state's, not the task's.
3. **No path** (a row with no folder). The folder line holds the name
   instead and the title is the task's.
4. **Two sessions in one folder.** Two cards with one folder line; the
   title tells them apart when each has a task, the name does when not.
   The tooltip carries the whole path and the session's name.
5. **A long title.** Two lines, then clipped, the whole in the tooltip.
6. **A remote card.** The host chip stays in the facts line; the pill
   reads the remote state's word.
7. **A card under the compact tiers.** Untouched: the key's rules are
   scoped to the full-width layout.
8. **The clocks disagree.** The recency line takes the freshest; a report
   older than the state's clock does not move it back.
9. **The setting flips while cards are painted.** The root key changes and
   the next paint re-lays the stack; no animation runs.

## 5. Tests

- `tests/test_page_*`: the stack's order under the key; the title choice
  for a task line present, absent and done; the pill class per state; the
  recency text per clock pair; the name-first card unchanged without the
  key.
- Settings: `card_anatomy` saved and read, default `task`.
- The lab's render script, run against the built page, is the visual
  check: control and task-first shots at 380 px, dark and light.

## 6. Docs

README card figures (`assets/card-anatomy.svg`, `assets/card-states.svg`)
redrawn by their scripts for the task-first card, the default;
`docs/usage.md` "Card style" gains the anatomy choice and what each shows;
the card anatomy section names the folder line, the pill and the recency
line.

## Not in this design

- Grouping heads over status runs: the attention order draws them today.
- A tasks-complete count from finished checklist items.
- Any change to the compact and tiny tiers.
