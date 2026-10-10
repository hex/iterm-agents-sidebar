# ABOUTME: Runs the link mod's own kit tests (claude plugin test), so the suite and release.sh run them too.
# ABOUTME: On plugin/ as install.sh ships it, without omp/, whose test file is bun's; skipped only without claude.
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugin"


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_the_link_mod_passes_its_kit_tests(tmp_path):
    shipped = tmp_path / "plugin"
    shutil.copytree(PLUGIN_DIR, shipped, ignore=shutil.ignore_patterns("omp"))
    done = subprocess.run(["claude", "plugin", "test", str(shipped)], cwd=tmp_path, capture_output=True, text=True,
                          timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0 fail" in done.stdout + done.stderr, done.stdout + done.stderr
