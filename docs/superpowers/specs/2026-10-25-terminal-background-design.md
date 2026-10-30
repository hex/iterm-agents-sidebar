# The panel's background follows the terminal: design

Written 2026-10-25. Status: built.

## Problem

The panel paints its own greys, from macOS's light or dark theme, beside a
terminal of any colour. On a Dracula or Solarized terminal the Toolbelt reads
as a slab of another app. The panel should take the colour of the terminal
beside it and build every surface from that colour.

## Decisions

- **Source.** The background of the session in front of iTerm2's key window,
  read again on every rebuild, so the panel changes colour as focus moves
  between panes. With no session in front, the last colour read stands. A
  read that fails publishes no colour, never the colour before it.
- **Depth.** Every surface comes from the one colour: the canvas is the
  colour itself, and the cards, rests, rules and washes are steps from it.
- **Lift.** Variant B of a rendered round: a card sits .03 above the canvas in
  oklch lightness on a dark colour and .02 on a light one. Variant A (.055 and
  .04) read as too much.
- **Tone, revised 2026-10-25.** On the live panel the blend read as too
  strong. A second round over a dark #151728 and a Solarized #fdf6e3: on a
  dark colour the card now sinks .06 below the canvas (lighter cards were
  rejected: dark cards should be darker), on a light one it lifts .03 and
  keeps a quarter of the colour's chroma. The table below is the revised one.
- **Dark tone, revised 2026-10-30.** On the live panel the sunk cards read
  as too black against the terminal. Dark cards return to .03 above the
  canvas; the rest and the neglected wash scale with it. The light side is
  unchanged. The table below is the revised one.
- **Canvas, revised 2026-10-25.** With the canvas equal to the terminal
  colour, the panel and the terminal read as one surface with a hairline
  between them. Shown beside a terminal in both themes, the canvas moved .03
  darker than the terminal in both. Dark cards stay .06 below the new canvas;
  light cards, rests, the neglected wash and the rule stay derived from the
  terminal colour itself. On the live panel those near-white cards then read
  as too white; a round beside the terminal picked .015 lighter with 60% of
  the colour's chroma.
- **Theme.** A colour whose relative luminance, as the Web Content
  Accessibility Guidelines (WCAG) define it, is under .4 takes the dark
  theme, any other the light one, whatever macOS's appearance is. With no
  colour, read or wanted, macOS's theme decides, as before.
- **Switch.** `follow_terminal`, on by default, under Rows beside Shell names.
  Off, the daemon does not read the profile and the panel is as it was.

## The daemon

`terminal_background(profile, theme)` turns a profile into `"#rrggbb"`, each
channel rounded and clamped. `Bridge.read_terminal_background` runs in each
rebuild while the setting is on and publishes the result as
`terminal_background` in the snapshot, beside `terminal_font`.

A profile can carry separate colours for light and dark mode
(`use_separate_colors_for_light_and_dark_mode`). Its plain
`background_color` is then not what the terminal shows: on the build
machine, the plain colour was #282a36 while the pane showed its dark
colour, #151728. For such a profile the daemon asks iTerm2 for its theme
(`async_get_theme`) and takes the dark colour when the theme says `dark`, the
light one otherwise. That is a second iTerm2 call per rebuild for such a
profile; a profile with one colour costs one call.

The daemon logs each kind of failure (its `repr`) once, until a read succeeds. The
rebuild never raises for this read.

## The page

`applyTerminalBackground` runs in `paintAll` beside `applyShellFont`. With a
colour and the setting on, it sets `--term-bg` on the root and
`data-term-theme` to what `termTheme` says; otherwise it removes both. The
settings line under the switch reads `Terminal background #282a36`, or
`Terminal background (not read)`, and hides while the switch is off.

### Derivation

| Token | Dark (lift .03) | Light (lift .015, chroma x .6) |
| --- | --- | --- |
| `--bg` | the terminal's `l - .03` | the terminal's `l - .03` |
| `--card` | `l + .03` | `min(1, l + .015)`, `c * .6` |
| `--card-hover` | `l + .05` | the card's `l - .015` |
| `--rested-bg` | `l + .018` | `min(1, l + .0075)`, `c * .6` |
| `--neglected-bg` | `l + .009` | `l - .02` |
| `--rule`, `--card-border` | `l + .11` | the terminal's `l - .075` |
| `--finished-bg` | card 86%, `--sev-ok` 14% | card 88%, `--sev-ok` 12% |
| `--blocked-bg` | card 72%, `--blocked-border` 28% | card 80%, `--blocked-border` 20% |
| `--warn-bg` | card 85%, `--warn` 15% | card 88%, `--warn` 12% |
| `--accent-ink` | the terminal colour | the light theme's |

Lightness steps are `oklch(from ... )` with chroma and hue kept: the dark column steps from the canvas (`--bg`), the light column from the terminal colour (`--term-bg`) unless it says otherwise. The
washes mix in oklab. The round's mock mixed them in oklch, which travels the
hue circle: on a grey or white colour (hue 0, a red) the finished green came
out pink, and on Dracula's blue it came out teal. The round never showed a
washed card; shots of the build with one showed it. Every other
token (ink, accents, severities) is the theme's own.

### Theme blocks

The three dark blocks (the tokens, the effort colours, the scrim) apply under
`@media (prefers-color-scheme: dark)` to `:root:not([data-term-theme="light"])`,
and again outside it to `:root[data-term-theme="dark"]`. A media query cannot
join a selector list, so each block's declarations stand twice;
`tests/test_page_terminal_background.py` holds the copies equal. Two other
ways lost: `light-dark()` with `color-scheme` as the switch would keep
one copy, but rewrites every token, cannot carry `--card-edge` (a shadow), and
breaks the tests that read the two palettes; a script that mirrors macOS's
theme into the attribute would keep one copy, but makes the theme with no
terminal colour depend on script. `color-scheme` follows the attribute, so
the sheet's pickers match the theme the colour picked.

## Settings default

`load_settings` starts from `DEFAULT_SETTINGS` and copies only the keys the
file has, so an install whose saved file predates `follow_terminal` reads it
as on. `save_settings` writes every key, so the next save pins it in the file.

## Verification

Headless Chrome at 380px over one captured frame with seeded cards (finished
unseen, blocked on a Bash gate, working, stale, rested, exited) and a frozen
clock:

- With no colour, the page differs from the page before this work by 0
  pixels in macOS dark and in macOS light, against 1,076,990 between the two
  themes. Run to run, the same page varies by up to 4 pixels.
- Dracula #282a36, Solarized light #fdf6e3, black and white each take the
  expected theme under both macOS themes, with the canvas the exact colour
  (before the canvas moved .03 darker on 2026-10-25).
- With the switch off, a Dracula colour leaves the light canvas at #f2f2f7.

Not verified: the page in iTerm2's WKWebView. Relative colour syntax needs
WebKit 18; on an older WebKit the derived tokens would be invalid and the
cards would lose their fill.
