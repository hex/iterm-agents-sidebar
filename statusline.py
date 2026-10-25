# ABOUTME: Claude Code's settings.json for the panel: puts the statusline bridge in, keeping the user's
# ABOUTME: own line, and hands iTerm2's status hook over; shared by install.sh and the panel's buttons.
"""The statusline payload is the only place Claude Code publishes a session's
context window, model, effort, cost and limits, and the bridge is what copies
it out for the panel. The user's own statusline goes on running inside it,
from original-statusline.

iTerm2's Claude Code integration writes the status under a tab from a hook of
its own, cc-status. While it is in settings.json the panel leaves Claude tabs
to it; the hand-over takes it out, so the panel is the one writer.

As a command: python3 statusline.py <settings.json> <bridge> <status dir>
prints "already", or "set" and then the command it displaced (maybe empty).
"""
import json
import os
import shutil
import sys
from pathlib import Path

#: The bridge's own file name, whichever checkout it lives in.
BRIDGE_NAME = "statusline-bridge.sh"


def _read(settings_path):
    """settings.json as a dict; {} when there is none. ValueError when it is not JSON."""
    try:
        text = Path(settings_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        settings = json.loads(text)
    except ValueError:
        raise ValueError(f"{settings_path} is not valid JSON; left unchanged") from None
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} is not a JSON object; left unchanged")
    return settings


def _command(settings):
    line = settings.get("statusLine")
    return line.get("command", "") if isinstance(line, dict) else ""


def state(settings_path, bridge):
    """"installed", "missing", or "unreadable" when settings.json is not JSON."""
    try:
        settings = _read(settings_path)
    except ValueError:
        return "unreadable"
    return "installed" if _command(settings) == str(bridge) else "missing"


def install(settings_path, bridge, status_dir):
    """Point statusLine.command at the bridge.

    Returns None when it already was, and nothing was written; otherwise the
    command it displaced, which the bridge now runs, or "" when there was none
    of the user's own. Raises ValueError, writing nothing, when settings.json
    is not a JSON object.
    """
    settings_path, status_dir = Path(settings_path), Path(status_dir)
    settings = _read(settings_path)
    current = _command(settings)
    if current == str(bridge):
        return None
    status_dir.mkdir(parents=True, exist_ok=True)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        shutil.copyfile(settings_path, str(settings_path) + ".before-agents-sidebar")
    # Another checkout's bridge is not the user's line: kept as the original,
    # the bridge would run itself on every render. The original already saved
    # stays.
    displaced = "" if current.endswith("/" + BRIDGE_NAME) else current
    if displaced or not current:
        (status_dir / "original-statusline").write_text(displaced, encoding="utf-8")
    line = settings.get("statusLine") if isinstance(settings.get("statusLine"), dict) else {}
    line.update({"type": "command", "command": str(bridge)})
    settings["statusLine"] = line
    _write(settings_path, settings)
    return displaced


def _write(settings_path, settings):
    """Replace settings.json whole, so Claude Code never reads half a file."""
    temporary = settings_path.with_name(settings_path.name + ".agents-sidebar.tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, settings_path)


#: iTerm2's status hook, known by the command's file name: the path is a
#: per-machine symlink into iTerm.app.
CC_STATUS = "cc-status"


def _is_cc_status(hook):
    command = hook.get("command") if isinstance(hook, dict) else None
    words = command.split() if isinstance(command, str) else []
    return bool(words) and os.path.basename(words[0]) == CC_STATUS


def _hook_lists(settings):
    """Each matcher group's list of hooks, whatever shape the rest of the file has."""
    hooks = settings.get("hooks")
    for groups in hooks.values() if isinstance(hooks, dict) else ():
        for group in groups if isinstance(groups, list) else ():
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                yield group["hooks"]


def cc_status(settings_path):
    """"present" while any hook runs cc-status, "absent", or "unreadable"
    when settings.json is not JSON: no proof the hook is gone."""
    try:
        settings = _read(settings_path)
    except ValueError:
        return "unreadable"
    return "present" if any(map(_is_cc_status, (hook for hooks in _hook_lists(settings) for hook in hooks))) else "absent"


def drop_cc_status(settings_path):
    """Take every cc-status hook out of settings.json, and the matcher groups
    and events that held nothing else. The file as it was is kept beside it
    as settings.json.before-tab-status. -> how many hooks went; with none to
    take, nothing is written, so a second hand-over keeps the first backup.
    Raises ValueError, writing nothing, when settings.json is not a JSON object."""
    settings_path = Path(settings_path)
    settings = _read(settings_path)
    hooks = settings.get("hooks")
    removed = 0
    for event, groups in list(hooks.items()) if isinstance(hooks, dict) else ():
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list):
                kept = [hook for hook in inner if not _is_cc_status(hook)]
                removed += len(inner) - len(kept)
                if inner and not kept:
                    continue
                group["hooks"] = kept
            kept_groups.append(group)
        if groups and not kept_groups:
            del hooks[event]
        else:
            hooks[event] = kept_groups
    if not removed:
        return 0
    shutil.copyfile(settings_path, str(settings_path) + ".before-tab-status")
    _write(settings_path, settings)
    return removed


if __name__ == "__main__":
    try:
        displaced = install(*sys.argv[1:4])
    except ValueError as refusal:
        sys.exit(f"error: {refusal}")
    print("already" if displaced is None else f"set\n{displaced}")
