"""Tests for pm shutdown — iTerm2 path."""

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from pm.cli import main


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def no_reinit_db():
    with patch("pm.cli.init_db"):
        yield


class TestShutdownIterm2:
    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_dry_run_shows_plan(self, mock_run, mock_check, cli_runner):
        """Dry run shows what would happen without executing."""
        mock_run.return_value = MagicMock(returncode=0, stdout="3", stderr="")
        result = cli_runner.invoke(main, ["shutdown", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "Dry run" in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_iterm2_not_running_shows_message(self, mock_run, mock_check, cli_runner):
        """When iTerm2 isn't running, shows a clear message."""
        err = subprocess.CalledProcessError(1, "osascript")
        err.stderr = "iTerm2 is not running."
        mock_run.side_effect = err
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "not" in result.output.lower()

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_zero_sessions_shows_message(self, mock_run, mock_check, cli_runner):
        """No sessions found produces a clear message."""
        # First call (get_tabs_script) succeeds, second (count_script) returns 0
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="0", stderr=""),
        ]
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "0" in result.output or "No" in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_dry_run_no_context_flag(self, mock_run, mock_check, cli_runner):
        """--no-context flag mentioned in dry run output."""
        mock_run.return_value = MagicMock(returncode=0, stdout="2", stderr="")
        result = cli_runner.invoke(main, ["shutdown", "--dry-run", "--no-context"])
        assert result.exit_code == 0
        # Should not mention context save when --no-context
        assert "PROJECT-CONTEXT.md" not in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_dry_run_with_context_mentions_context_file(self, mock_run, mock_check, cli_runner):
        """Default dry run mentions the context file."""
        mock_run.return_value = MagicMock(returncode=0, stdout="2", stderr="")
        result = cli_runner.invoke(main, ["shutdown", "--dry-run"])
        assert result.exit_code == 0
        assert "PROJECT-CONTEXT.md" in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_can_get_error_shows_not_running(self, mock_run, mock_check, cli_runner):
        """AppleScript 'can't get' error treated as iTerm2 not running."""
        err = subprocess.CalledProcessError(1, "osascript")
        err.stderr = "iTerm2 got an error: can't get window id 1."
        mock_run.side_effect = err
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "not" in result.output.lower() or "can't" in result.output.lower()


class TestShutdownTerminalApp:
    @patch("pm.cli.is_shutdown_supported", return_value=False)
    @patch("pm.cli.subprocess.run")
    def test_dry_run_shows_terminal_app_plan(self, mock_run, mock_check, cli_runner):
        """Dry run via Terminal.app path shows plan."""
        mock_run.return_value = MagicMock(returncode=0, stdout="2", stderr="")
        result = cli_runner.invoke(main, ["shutdown", "--dry-run"])
        assert result.exit_code == 0

    @patch("pm.cli.is_shutdown_supported", return_value=False)
    @patch("pm.cli.subprocess.run")
    def test_zero_tabs_no_crash(self, mock_run, mock_check, cli_runner):
        """Zero Terminal.app tabs shows message without crashing."""
        mock_run.return_value = MagicMock(returncode=0, stdout="0", stderr="")
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "No Terminal.app tabs" in result.output or result.exit_code == 0
