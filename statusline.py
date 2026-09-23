# ABOUTME: Puts the statusline bridge into Claude Code's settings.json, keeping the user's own line.
# ABOUTME: Shared by install.sh (as a command) and the panel's Install button (imported).
"""The statusline payload is the only place Claude Code publishes a session's
context window, model, effort, cost and limits, and the bridge is what copies
it out for the panel. The user's own statusline goes on running inside it,
from original-statusline.

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
    temporary = settings_path.with_name(settings_path.name + ".agents-sidebar.tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, settings_path)
    return displaced


if __name__ == "__main__":
    try:
        displaced = install(*sys.argv[1:4])
    except ValueError as refusal:
        sys.exit(f"error: {refusal}")
    print("already" if displaced is None else f"set\n{displaced}")
