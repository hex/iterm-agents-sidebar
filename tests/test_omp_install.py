# ABOUTME: Installing the omp extension into omp's agent directory, under a spare HOME.
# ABOUTME: The directory follows omp's own profile rules, and a file the panel did not write is never touched.
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "omp-extension.sh"
SOURCE = REPO / "plugin" / "omp" / "agents-sidebar.ts"
LINE_ONE = SOURCE.read_text(encoding="utf-8").splitlines()[0]


def run(home, *args, **env):
    clean = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", str(SCRIPT), *args], env={**clean, **env},
                          capture_output=True, text=True, cwd=home)


def handler_in(home):
    handler = home / ".claude" / "skills" / "agents-sidebar" / "hooks-handlers" / "emit-state.py"
    handler.parent.mkdir(parents=True, exist_ok=True)
    handler.write_text("")
    return handler


def install(home, **env):
    return run(home, str(SOURCE), str(handler_in(home)), "/usr/bin/python3", **env)


def test_it_writes_the_extension_into_omps_agent_directory_with_the_hook_filled_in(tmp_path):
    result = install(tmp_path)
    written = tmp_path / ".omp" / "agent" / "extensions" / "agents-sidebar.ts"
    assert (result.returncode, result.stdout.strip()) == (0, str(written))
    text = written.read_text(encoding="utf-8")
    handler = handler_in(tmp_path)
    assert text.splitlines()[0] == LINE_ONE
    assert f"const HANDLER = {json.dumps(str(handler))};" in text
    assert 'const PYTHON = "/usr/bin/python3";' in text
    assert "@AGENTS_SIDEBAR_" not in text
    assert text.replace(json.dumps(str(handler)), '"@AGENTS_SIDEBAR_HANDLER@"').replace(
        '"/usr/bin/python3"', '"@AGENTS_SIDEBAR_PYTHON@"') == SOURCE.read_text(encoding="utf-8")


def where(home, **env):
    result = run(home, "--where", **env)
    return result.stdout.strip() if result.returncode == 0 else ("refused", result.stderr.strip())


def test_the_directory_is_the_one_omp_reads(tmp_path):
    """pi-utils/src/dirs.ts in omp 18.2.11: a profile wins, OMP_PROFILE
    before PI_PROFILE; then PI_CODING_AGENT_DIR; then the config root."""
    home = str(tmp_path)
    assert where(tmp_path) == f"{home}/.omp/agent"
    assert where(tmp_path, PI_CONFIG_DIR=".pi") == f"{home}/.pi/agent"
    assert where(tmp_path, OMP_PROFILE="work") == f"{home}/.omp/profiles/work/agent"
    assert where(tmp_path, PI_PROFILE="work") == f"{home}/.omp/profiles/work/agent"
    assert where(tmp_path, OMP_PROFILE="work", PI_PROFILE="play") == f"{home}/.omp/profiles/work/agent"
    assert where(tmp_path, OMP_PROFILE=" work ") == f"{home}/.omp/profiles/work/agent"
    assert where(tmp_path, OMP_PROFILE="", PI_PROFILE="play") == f"{home}/.omp/agent"
    assert where(tmp_path, OMP_PROFILE="default") == f"{home}/.omp/agent"
    assert where(tmp_path, OMP_PROFILE="work", PI_CODING_AGENT_DIR="/opt/agent") == f"{home}/.omp/profiles/work/agent"
    assert where(tmp_path, PI_CODING_AGENT_DIR="/opt/agent") == "/opt/agent"
    (tmp_path / "custom").mkdir()
    assert where(tmp_path, PI_CODING_AGENT_DIR="custom/agent") == f"{home}/custom/agent"


def test_a_profile_omp_would_refuse_writes_nothing(tmp_path):
    for name in ("Work", "../x", "a.", "-a", "a" * 65):
        assert where(tmp_path, OMP_PROFILE=name) == (
            "refused", f'error: "{name}" is not a profile name omp accepts; nothing written.')
        assert install(tmp_path, OMP_PROFILE=name).returncode == 1
    assert not (tmp_path / ".omp").exists()


def test_installing_again_replaces_its_own_file(tmp_path):
    install(tmp_path)
    written = tmp_path / ".omp" / "agent" / "extensions" / "agents-sidebar.ts"
    first = written.read_text(encoding="utf-8")
    written.write_text(first + "// an older version\n")
    older = written.stat().st_ino
    assert install(tmp_path).returncode == 0
    assert written.read_text(encoding="utf-8") == first
    assert sorted(p.name for p in written.parent.iterdir()) == ["agents-sidebar.ts"]
    # A rename puts a whole new file in place, so omp never reads half of one.
    assert written.stat().st_ino != older


def test_a_release_that_rewrites_the_aboutme_lines_still_replaces_and_removes_the_installed_file(tmp_path):
    install(tmp_path)
    written = tmp_path / ".omp" / "agent" / "extensions" / "agents-sidebar.ts"
    lines = SOURCE.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[0] = "// ABOUTME: Something else entirely.\n"
    lines[1] = "// ABOUTME: And a second line that says nothing of the first.\n"
    newer = tmp_path / "agents-sidebar.ts"
    newer.write_text("".join(lines), encoding="utf-8")
    result = run(tmp_path, str(newer), str(handler_in(tmp_path)), "/usr/bin/python3")
    assert (result.returncode, result.stderr) == (0, "")
    assert written.read_text(encoding="utf-8").splitlines()[:2] == [
        "// ABOUTME: Something else entirely.", "// ABOUTME: And a second line that says nothing of the first."]
    result = run(tmp_path, "--remove")
    assert (result.returncode, result.stdout.strip()) == (0, str(written))
    assert not written.exists()


def test_a_source_without_the_marker_writes_nothing_over_the_installed_file(tmp_path):
    install(tmp_path)
    written = tmp_path / ".omp" / "agent" / "extensions" / "agents-sidebar.ts"
    installed = written.read_text(encoding="utf-8")
    unmarked = tmp_path / "agents-sidebar.ts"
    unmarked.write_text("// ABOUTME: An extension for omp.\n" + SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    result = run(tmp_path, str(unmarked), str(handler_in(tmp_path)), "/usr/bin/python3")
    assert (result.returncode, result.stderr.strip()) == (
        1, f"error: line 3 of {unmarked} is not the marker "
           "// agents-sidebar-omp-extension: written by the Agents panel's install.sh, which owns this file.; "
           "nothing written.")
    assert written.read_text(encoding="utf-8") == installed


def test_a_file_of_that_name_it_did_not_write_is_left_alone(tmp_path):
    extensions = tmp_path / ".omp" / "agent" / "extensions"
    extensions.mkdir(parents=True)
    theirs = extensions / "agents-sidebar.ts"
    theirs.write_text("// somebody else's extension\n")
    result = install(tmp_path)
    assert (result.returncode, result.stderr.strip()) == (
        1, f"error: {theirs} was not written by the Agents panel; left unchanged.")
    assert theirs.read_text() == "// somebody else's extension\n"
    result = run(tmp_path, "--remove")
    assert (result.returncode, result.stderr.strip()) == (
        1, f"error: {theirs} was not written by the Agents panel; left in place.")
    assert theirs.exists()


def test_a_link_in_its_place_is_left_alone_even_to_a_file_of_ours(tmp_path):
    install(tmp_path)
    extensions = tmp_path / ".omp" / "agent" / "extensions"
    (extensions / "agents-sidebar.ts").rename(tmp_path / "elsewhere.ts")
    (extensions / "agents-sidebar.ts").symlink_to(tmp_path / "elsewhere.ts")
    assert install(tmp_path).returncode == 1
    assert run(tmp_path, "--remove").returncode == 1
    assert (extensions / "agents-sidebar.ts").is_symlink()


def test_a_link_planted_where_it_could_stage_the_file_is_never_written_through(tmp_path):
    """omp's agent directory can be one another process writes to. A link
    named for the installer's own pid, the name a guess would reach for,
    leads to a file outside it, which stays as it was."""
    extensions = tmp_path / ".omp" / "agent" / "extensions"
    extensions.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_text("not the installer's\n")

    def plant():
        os.symlink(victim, extensions / f".agents-sidebar.{os.getpid()}.tmp")

    handler = handler_in(tmp_path)
    result = subprocess.run(["bash", str(SCRIPT), str(SOURCE), str(handler), "/usr/bin/python3"],
                            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True, cwd=tmp_path, preexec_fn=plant)

    assert (result.returncode, result.stderr) == (0, "")
    assert victim.read_text() == "not the installer's\n"
    assert (extensions / "agents-sidebar.ts").read_text(encoding="utf-8").splitlines()[0] == LINE_ONE
    assert sorted(p.name for p in extensions.iterdir() if not p.is_symlink()) == ["agents-sidebar.ts"]


def test_remove_takes_out_its_own_file_and_nothing_beside_it(tmp_path):
    install(tmp_path)
    extensions = tmp_path / ".omp" / "agent" / "extensions"
    (extensions / "mine.ts").write_text("// another extension\n")
    result = run(tmp_path, "--remove")
    assert (result.returncode, result.stdout.strip()) == (0, str(extensions / "agents-sidebar.ts"))
    assert sorted(p.name for p in extensions.iterdir()) == ["mine.ts"]
    assert run(tmp_path, "--remove").returncode == 0


def test_it_writes_nothing_without_the_hook_it_would_run(tmp_path):
    result = run(tmp_path, str(SOURCE), str(tmp_path / "missing.py"), "/usr/bin/python3")
    assert (result.returncode, result.stderr.strip()) == (
        1, f"error: no state hook at {tmp_path / 'missing.py'}; nothing written.")
    assert not (tmp_path / ".omp").exists()
