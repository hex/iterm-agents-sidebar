# Troubleshooting

| Symptom | What it means | What to do |
| --- | --- | --- |
| Every row dims, `STALE` banner | The daemon missed two heartbeats, or a heartbeat says it can't read iTerm2 | Restart the script from the Scripts menu |
| A row shows `?` for its directory or job | iTerm2 can't report that one session | Nothing; one session costs its own row, not the list |
| The panel is white and nothing loads | Two tool identifiers named "Agents", and the menu opened the dead one | Rename the stale entry, below |
| Codex cards stop appearing | A herdr update rewrote `~/.codex/hooks.json` | `./install.sh --codex` |
| Rows show no context percentage | The statusline bridge is not installed, or `cs -statusline enable` replaced it | `./install.sh --statusline` |

## The white panel

iTerm2 keeps every tool identifier it has seen in its `NoSyncDynamicTools`
preference, and the Toolbelt menu picks a tool by its display name. Two
identifiers both named "Agents" open whichever one iTerm2 finds first, which
can be a dead port. Rename the stale entry to bring the live one back:

```sh
defaults write com.googlecode.iterm2 NoSyncDynamicTools -dict-add <old id> \
  '{ URL = "http://127.0.0.1:1/"; name = "OLD-Agents"; }'
```

## Why STALE exists

A heartbeat only proves the daemon is answering, so it carries the result of
its last read of iTerm2 as well. Without that, a stuck refresh would leave
every row and every permission badge looking current forever.
