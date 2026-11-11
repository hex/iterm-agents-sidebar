# ABOUTME: Claude Code's settings.json for the panel: puts the statusline bridge in, keeping the user's own
# ABOUTME: line, hands iTerm2's status hook over, and puts the API fallback's apiKeyHelper in and out.
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
import shlex
import shutil
import stat
import sys
from pathlib import Path

import accounts

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


def helper_command(helper_path, account_id):
    """The apiKeyHelper command that runs the script at `helper_path` for one
    account's key: quoted, because Claude Code runs it through a shell and a
    checkout's path may hold a space. Raises ValueError for an account id not in
    the store's format, which never reaches the shell."""
    if not accounts.is_account_id(account_id):
        raise ValueError(f"{account_id!r} is not an account id")
    return f"{shlex.quote(str(helper_path))} {shlex.quote(account_id)}"


def _helper_of(settings):
    """settings.json's apiKeyHelper, or None; anything but text is someone else's."""
    command = settings.get("apiKeyHelper")
    return command if command is None or isinstance(command, str) else repr(command)


def api_key_helper(settings_path, ours):
    """-> (state, command): "ours" with the command when apiKeyHelper is exactly one
    of the commands in `ours`; otherwise "absent", "foreign" when anything else is
    set, or "unreadable" when settings.json is not a JSON object, each with None,
    so another tool's command is never handed on."""
    try:
        command = _helper_of(_read(settings_path))
    except ValueError:
        return "unreadable", None
    if command is None:
        return "absent", None
    return ("ours", command) if command in ours else ("foreign", None)


def api_key_helper_state(settings_path, ours):
    """api_key_helper's state alone."""
    return api_key_helper(settings_path, ours)[0]


def _text(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _edit_helper(settings_path, change):
    """Read settings.json, apply `change` (settings -> the settings to write, or
    None for nothing to write), and replace the file, changing no other key.

    settings.json has no lock and other tools rewrite it, so the file is read
    again just before the replace and once after it: a change from anyone
    else at either point runs the step once more from a fresh read, and a
    second one stops it, leaving the file as that writer left it. The write
    keeps the file's shape for whoever else reads it: a symlink's target is
    what gets replaced, its mode stays, and non-ASCII text stays as text.
    """
    settings_path = Path(os.path.realpath(settings_path))
    for _ in range(2):
        before = _text(settings_path)
        settings = _read(settings_path) if before is not None else {}
        intended = change(settings)
        if intended is None:
            return
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        # Its own name per process: helpers in several sessions may drop at once.
        staged = settings_path.with_name(f"{settings_path.name}.agents-sidebar.{os.getpid()}.tmp")
        with open(staged, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(intended, indent=2, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if before is not None:
            os.chmod(staged, stat.S_IMODE(settings_path.stat().st_mode))
        if _text(settings_path) != before:
            staged.unlink()
            continue
        os.replace(staged, settings_path)
        try:
            if _read(settings_path) == intended:
                return
        except ValueError:
            pass
    raise ValueError(f"{settings_path} changed while the panel wrote it, twice; left as it is")


def _refuse_foreign(settings_path, settings, ours):
    command = _helper_of(settings)
    if command is not None and command not in ours:
        raise ValueError(f"{settings_path} sets another tool's apiKeyHelper; left unchanged")
    return command


def set_api_key_helper(settings_path, command, ours):
    """Point apiKeyHelper at `command`. Raises ValueError, writing nothing, when a
    helper other than `command` or one of `ours` is set, or settings.json is not a
    JSON object."""
    def change(settings):
        if _refuse_foreign(settings_path, settings, {*ours, command}) == command:
            return None
        return {**settings, "apiKeyHelper": command}
    _edit_helper(settings_path, change)


def drop_api_key_helper(settings_path, ours):
    """Take apiKeyHelper out when it is one of `ours`; with none set, nothing is
    written. Raises ValueError, writing nothing, when any other helper is set or
    settings.json is not a JSON object."""
    def change(settings):
        if _refuse_foreign(settings_path, settings, ours) is None:
            return None
        return {key: value for key, value in settings.items() if key != "apiKeyHelper"}
    _edit_helper(settings_path, change)


if __name__ == "__main__":
    try:
        displaced = install(*sys.argv[1:4])
    except ValueError as refusal:
        sys.exit(f"error: {refusal}")
    print("already" if displaced is None else f"set\n{displaced}")
