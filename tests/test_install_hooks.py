# ABOUTME: Checks how install.sh replaces the hook folder live Claude Code sessions run their hooks from,
# ABOUTME: under an isolated HOME: the installed hooks stay in place while the next copy is unpacked.
from pathlib import Path

from test_uninstall import run

REPO = Path(__file__).resolve().parent.parent


def test_a_reinstall_unpacks_the_hooks_beside_the_live_ones_and_swaps_them_in(tmp_path):
    home = tmp_path / "home"
    handler = home / ".claude" / "skills" / "agents-sidebar" / "hooks-handlers" / "emit-state.py"
    handler.parent.mkdir(parents=True)
    handler.write_text("# the hook a running session calls\n")
    # Unpacking is the one step that takes a while; it records whether the
    # installed hook was still there to run while it did.
    seen = tmp_path / "seen.log"
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "tar").write_text(f'''#!/bin/bash
if [ -f "{handler}" ]; then echo present >> "{seen}"; else echo missing >> "{seen}"; fi
exec /usr/bin/tar "$@"
''')
    (commands / "tar").chmod(0o755)

    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp")

    assert result.returncode == 0, result.stderr
    assert seen.read_text() == "present\n"
    assert handler.read_text() == (REPO / "plugin" / "hooks-handlers" / "emit-state.py").read_text()
    assert not (home / ".claude" / "skills" / "agents-sidebar" / "omp").exists()
    assert sorted(p.name for p in (home / ".claude" / "skills").iterdir()) == ["agents-sidebar"]
    assert sorted(p.name for p in (home / ".claude").iterdir() if "agents-sidebar." in p.name) == []
