"""Opening the task directory to Codex's sandbox in ~/.codex/config.toml,
without disturbing what the file already says.

Failure modes this covers, written before the script: no file yet; the table
absent; the table present with other roots on one line; ours already there;
the table present without the key; a layout the edit cannot read (an array
over several lines, or one with a trailing comment), which must leave the file
alone; the backup from the
first run, which a re-run must not overwrite.
"""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "codex-sandbox.py"
DIR = "/Users/jane/.claude/agents-sidebar-tasks"


def open_up(path):
    return subprocess.run(["python3", str(SCRIPT), str(path), DIR], capture_output=True, text=True)


def test_a_missing_config_gets_the_table(tmp_path):
    config = tmp_path / "config.toml"
    assert open_up(config).returncode == 0
    assert config.read_text() == f'[sandbox_workspace_write]\nwritable_roots = ["{DIR}"]\n'


def test_a_config_without_the_table_gets_it_appended(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5"\n')
    assert open_up(config).returncode == 0
    assert config.read_text() == f'model = "gpt-5"\n\n[sandbox_workspace_write]\nwritable_roots = ["{DIR}"]\n'


def test_other_roots_on_the_line_are_kept(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[sandbox_workspace_write]\nwritable_roots = ["/tmp/a", "/tmp/b"]\nnetwork_access = true\n')
    assert open_up(config).returncode == 0
    assert config.read_text() == f'[sandbox_workspace_write]\nwritable_roots = ["/tmp/a", "/tmp/b", "{DIR}"]\nnetwork_access = true\n'


def test_a_root_already_there_changes_nothing(tmp_path):
    config = tmp_path / "config.toml"
    before = f'[sandbox_workspace_write]\nwritable_roots = [ "{DIR}" ]\n'
    config.write_text(before)
    assert open_up(config).returncode == 0
    assert config.read_text() == before
    assert not (tmp_path / "config.toml.before-agents-sidebar").exists()


def test_a_table_without_the_key_gets_it(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[sandbox_workspace_write]\nnetwork_access = true\n\n[other]\nx = 1\n')
    assert open_up(config).returncode == 0
    assert config.read_text() == f'[sandbox_workspace_write]\nwritable_roots = ["{DIR}"]\nnetwork_access = true\n\n[other]\nx = 1\n'


def test_an_array_over_several_lines_is_left_alone(tmp_path):
    config = tmp_path / "config.toml"
    before = '[sandbox_workspace_write]\nwritable_roots = [\n  "/tmp/a",\n]\n'
    config.write_text(before)
    result = open_up(config)
    assert result.returncode == 2
    assert result.stderr == f"{config}: writable_roots spans several lines; add {DIR} to it by hand\n"
    assert config.read_text() == before


def test_a_one_line_array_with_a_trailing_comment_is_left_alone(tmp_path):
    """The key is there but not in a shape the edit reads; adding a second
    writable_roots would make the file invalid TOML."""
    config = tmp_path / "config.toml"
    before = '[sandbox_workspace_write]\nwritable_roots = ["/tmp/a"]  # mine\n'
    config.write_text(before)
    result = open_up(config)
    assert result.returncode == 2
    assert result.stderr == f"{config}: writable_roots is laid out in a way this edit cannot read; add {DIR} to it by hand\n"
    assert config.read_text() == before


def test_the_first_backup_survives_a_second_run(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[sandbox_workspace_write]\nwritable_roots = ["/tmp/a"]\n')
    assert open_up(config).returncode == 0
    backup = tmp_path / "config.toml.before-agents-sidebar"
    assert backup.read_text() == '[sandbox_workspace_write]\nwritable_roots = ["/tmp/a"]\n'
    config.write_text('[sandbox_workspace_write]\nwritable_roots = ["/tmp/b"]\n')
    assert open_up(config).returncode == 0
    assert backup.read_text() == '[sandbox_workspace_write]\nwritable_roots = ["/tmp/a"]\n'
