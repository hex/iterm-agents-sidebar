# ABOUTME: Runs the uninstall command through a symlink into a disposable checkout.
# ABOUTME: The checkout contains only the real CLI and a harmless uninstall script.
import os
import selectors
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("exit_status", [0, 7])
@pytest.mark.parametrize("keep_accounts", [False, True])
def test_uninstall_resolves_its_checkout_and_returns_the_scripts_status(tmp_path, exit_status, keep_accounts):
    checkout = tmp_path / "panel's checkout"
    checkout.mkdir()
    shutil.copy2(REPO / "agents-sidebar", checkout / "agents-sidebar")
    (checkout / "uninstall.sh").write_text(
        '#!/bin/bash\nfor arg in "$@"; do printf "%s\\n" "$arg"; done > "$HOME/uninstall-args"\n'
        f"printf 'removing panel\\n'\nprintf 'script warning\\n' >&2\nexit {exit_status}\n")
    link = tmp_path / "agents-sidebar"
    link.symlink_to(checkout / "agents-sidebar")
    home = tmp_path / "home"
    home.mkdir()
    arguments = ["--keep-accounts"] if keep_accounts else []
    result = subprocess.run([sys.executable, str(link), "uninstall", *arguments], capture_output=True, text=True,
                            env={**os.environ, "HOME": str(home)}, timeout=10)
    assert result.returncode == exit_status
    assert (home / "uninstall-args").read_text().splitlines() == arguments
    lines = result.stdout.splitlines()
    assert lines[:2] == ["removing panel", f"Checkout kept at {checkout}"]
    assert len(lines) == 3
    assert lines[2].startswith("Delete it with: ")
    assert shlex.split(lines[2].removeprefix("Delete it with: ")) == ["rm", "-rf", "--", str(checkout)]
    assert result.stderr == "script warning\n"
    assert checkout.is_dir()


def test_uninstall_streams_output_before_its_script_finishes(tmp_path):
    shutil.copy2(REPO / "agents-sidebar", tmp_path / "agents-sidebar")
    (tmp_path / "uninstall.sh").write_text("#!/bin/bash\nprintf 'removing panel\\n'\nread -r answer\n")
    process = subprocess.Popen([sys.executable, str(tmp_path / "agents-sidebar"), "uninstall"],
                               env={**os.environ, "HOME": str(tmp_path)}, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert len(selector.select(timeout=5)) == 1
            assert process.stdout.readline() == "removing panel\n"
        assert process.poll() is None
        out, err = process.communicate("continue\n", timeout=5)
        assert process.returncode == 0
        assert err == ""
        assert out.splitlines()[0] == f"Checkout kept at {tmp_path}"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_help_lists_uninstall(tmp_path):
    result = subprocess.run([sys.executable, str(REPO / "agents-sidebar"), "--help"],
                            env={**os.environ, "HOME": str(tmp_path)}, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert result.stderr == ""
    assert "    uninstall           remove the panel, its integrations and data; keep the\n" in result.stdout
