# ABOUTME: Checks automatic launch and restart instructions under an isolated HOME.
# ABOUTME: Every process command is logged by the script runner, never sent to iTerm2.
from test_uninstall import run


LAUNCH = 'tell application "iTerm2" to launch API script named "agents_sidebar"'


def test_install_starts_the_panel_when_iterm_is_running(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp", TEST_ITERM="1")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert [line for line in calls if line.startswith("osascript\t")] == [f"osascript\t-e\t{LAUNCH}"]
    assert "  ✓ daemon      started in iTerm2\n" in result.stdout
    assert "Start it:" not in result.stdout


def test_install_leaves_a_running_daemon_and_prints_its_restart_command(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp",
                 TEST_ITERM="1", TEST_PIDS="4242")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert [line for line in calls if line.startswith(("osascript\t", "kill\t"))] == []
    assert f"Restart it: kill 4242; osascript -e '{LAUNCH}'\n" in result.stdout
    assert "Start it:" not in result.stdout


def test_iterms_python_wrapper_does_not_count_as_a_daemon(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp",
                 TEST_ITERM="1", TEST_PIDS="4242",
                 TEST_ARGS="python3 it2_api_wrapper.py AutoLaunch/agents_sidebar.py")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert [line for line in calls if line.startswith("osascript\t")] == [f"osascript\t-e\t{LAUNCH}"]


def test_a_launch_failure_warns_without_failing_the_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp",
                 TEST_ITERM="1", TEST_LAUNCH_ERROR="iTerm2 refused the API script")
    assert result.returncode == 0, result.stderr
    assert "  ! daemon      iTerm2 refused the API script\n" in result.stderr
    assert "Start it:   Scripts > AutoLaunch > agents_sidebar\n" in result.stdout


def test_an_install_without_iterm_prints_manual_start_instructions(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert [line for line in calls if line.startswith(("osascript\t", "kill\t"))] == []
    assert "Start it:   Scripts > AutoLaunch > agents_sidebar\n" in result.stdout


def test_a_non_python_process_with_the_stub_in_its_arguments_does_not_block_launch(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = run("install.sh", home, "--no-statusline", "--no-codex", "--no-omp",
                 TEST_ITERM="1", TEST_PIDS="4242", TEST_COMM="bash")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "commands.log").read_text().splitlines()
    assert [line for line in calls if line.startswith("osascript\t")] == [f"osascript\t-e\t{LAUNCH}"]
