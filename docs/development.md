# Development

How the panel works, and the parts that only matter when you change
it.

## The install and the port

`./install.sh` writes a stub into
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/`, and the stub loads
`sidebar.py` from the checkout. The daemon reads `page.html` again on every
request, but the panel fetches the page only once, when it connects, so a UI
change needs the script restarted from the Scripts menu. The new run takes a
port the OS picks, and the panel follows the re-registered URL.

The daemon binds `127.0.0.1` and checks a token of 24 random bytes on every
request, including the event stream. Focus, send and close are the only three
things the panel can do to a session, and no endpoint runs arbitrary code.

## Releases

The version sits in `VERSION`, in the plugin manifest, at the foot of the
settings and on a `v` tag. `./release.sh "summary"` bumps it, runs the tests
on main and again on the public tree, and pushes one squashed commit to the
mirror. `RELEASE_SCRUB="word word"` fails the release if the public tree
contains any of those words.

## The tool identifier

`com.hexul.agents-sidebar` is permanent. `iterm2.tool` has only
`async_register_web_view_tool` and no way to unregister, so an identifier stays
in the Toolbelt once anything registers it. Registering it again with a new URL
does work, which is why an ephemeral port is fine. See
`docs/troubleshooting.md` for what happens when two identifiers share a
display name.

## Keys

iTerm2 sends printable characters to the terminal and keeps Shift+Enter for
itself, so a `j` and `k` binding or a Shift+Enter one would never fire. Enter,
Space, and Enter with Cmd, Ctrl or Option all reach the panel. Clicking a row
activates that terminal and takes the focus with it, which is why the panel
needs a click on an empty part of itself first.

Option-right-click on a row opens the web view's own menu, with Reload and
Inspect Element.

## Where each fact comes from

- **Shells:** the process tree, because Claude Code publishes them nowhere. The
  panel's own task report (`task.py`, run when the prompt hook asks) is
  filtered out, and a home directory in a command reads as `~`.
- **Teammates:** the lead's session id in the teammate's
  `--parent-session-id`, matched against the lead's own id from its statusline
  payload, so nesting needs the statusline bridge. The badge colour comes from
  `--agent-color` on the same command line, the only place it lives.
- **Subagents:** the name from the subagent's meta file, the model from its
  transcript. Until those exist, the row shows the subagent's type.
- **Plain terminals inside tmux:** iTerm2 doesn't reliably report a pane's
  command or directory, so the panel asks tmux for the pane's tty and
  directory and names the tty's foreground process. A script run by an
  interpreter shows under the script's name: `node .../bin/codex` shows as
  `codex`.
- **CPU and memory:** one `ps` listing per rebuild, summed over each session's
  process tree by parent pid, stopping at any pid that is another card so a
  teammate is not counted twice. CPU is `ps %cpu` summed. Only the verdict
  reaches the page, not the figures, so usage moving below the threshold
  repaints nothing. A chip holds for 15 seconds after its last high reading,
  because a busy process reads anywhere from a quarter to most of a core from
  one refresh to the next.

## State and the permission badge

The hook keeps a record per session of which subagents are alive and which
tools are waiting on you, and a session's state comes from that record, not
from the last event that fired. It has to, because a parent and all its
subagents write to the same terminal. Only the tool that opened a gate closes it, or your next prompt does.

The state reaches the daemon as an iTerm2 user variable, written to the pane on
every hook event. The hook keeps it under 4096 bytes of base64. A state past
that, which a workflow with dozens of subagents produces, goes whole into
`~/.claude/agents-sidebar-subagents/<session id>.published`, and the variable
carries the state, the ids and the times with `detail: true`. The daemon reads
the file back on each rebuild. If the hook can't write the file, the variable says
`detail: false` and the card shows its state without its subagents.

A session whose working directory or job iTerm2 can't report shows `?` instead
of a guess.

## Tests

```sh
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

The daemon needs neither; both are for tests only. `tests/test_integration.py`
runs a real listener over real sockets.

`Bridge` is the only part that talks to iTerm2, and its tests pin how it takes
its readings (`tests/test_rebuild.py`: one process listing per rebuild, read in
a thread, a burst of layout events folded into one more rebuild, a session's
variables fetched together). The rest of `Bridge` gets a manual check against a
live iTerm2.

## Measuring what the machine executes

```sh
sudo ./measure-load.sh 10
```

It watches ten seconds with `fs_usage` and reports execs per second, what ran,
who ran it, PATH misses kept apart, and the load average before and after. The
raw lines stay under `$TMPDIR`.

On a managed Mac, endpoint agents inspect every exec, so the exec rate decides
whether the panel's helpers weigh on the machine, more than CPU time does. The
daemon execs `ps` and `tmux` once per rebuild, in a thread. The statusline
bridge execs four times per render.

## The banner

```sh
python3 assets/make-banner.py
BANNER_H=864 python3 assets/make-banner.py /tmp/banner-16x9.svg   # a taller cut, for a post
```

It redraws `assets/banner.svg`, the image at the top of the README, reading the
marks and colours from `page.html` so the drawing can't drift from the real
panel. I made the session names up. Any new label needs its width
measured and added to `MEASURED` in that script, because that table places the middots. GitHub plays the animation only from the raw file URL.
