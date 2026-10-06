# ABOUTME: Runs the omp extension's own bun tests, so the suite and release.sh run them too.
# ABOUTME: Skipped only on a machine without bun; a failure there fails here with bun's report.
import os
import shutil
import subprocess
from pathlib import Path

import pytest

EXTENSION_DIR = Path(__file__).resolve().parent.parent / "plugin" / "omp"


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun is not installed")
def test_the_omp_extension_passes_its_bun_tests(tmp_path):
    done = subprocess.run(["bun", "test"], cwd=EXTENSION_DIR, capture_output=True, text=True, timeout=120,
                          env={"HOME": str(tmp_path), "PATH": os.environ["PATH"], "TMPDIR": str(tmp_path),
                               "NO_COLOR": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(path.name for path in EXTENSION_DIR.iterdir()) == ["agents-sidebar.test.ts", "agents-sidebar.ts"]
