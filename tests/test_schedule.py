"""Tests for pm schedule commands (launchd install/uninstall/status)."""

import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner
from pm.cli import main, _PLIST_PATH, _SCHEDULE_LABEL, _build_plist


@pytest.fixture
def cli_runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# _build_plist
# ---------------------------------------------------------------------------

class TestBuildPlist:
    def test_contains_label(self):
        plist = _build_plist(2, 5, 1.0, 3, False)
        assert _SCHEDULE_LABEL in plist

    def test_contains_hour(self):
        plist = _build_plist(3, 5, 1.0, 3, False)
        assert "<integer>3</integer>" in plist

    def test_contains_limit(self):
        plist = _build_plist(2, 10, 1.0, 3, False)
        assert "<string>10</string>" in plist

    def test_dry_run_flag_included(self):
        plist = _build_plist(2, 5, 1.0, 3, True)
        assert "--dry-run" in plist

    def test_no_dry_run_flag_excluded(self):
        plist = _build_plist(2, 5, 1.0, 3, False)
        assert "--dry-run" not in plist

    def test_valid_xml_structure(self):
        plist = _build_plist(2, 5, 1.0, 3, False)
        assert plist.startswith("<?xml")
        assert "<plist" in plist
        assert "</plist>" in plist


# ---------------------------------------------------------------------------
# pm schedule install
# ---------------------------------------------------------------------------

class TestScheduleInstall:
    @patch("pm.cli.subprocess.run")
    def test_install_writes_plist(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        plist_dest = tmp_path / "test.plist"

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "install"])

        assert plist_dest.exists()

    @patch("pm.cli.subprocess.run")
    def test_install_success_message(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        plist_dest = tmp_path / "test.plist"

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "install"])

        assert "Installed" in result.output or "loaded" in result.output.lower()

    @patch("pm.cli.subprocess.run")
    def test_install_launchctl_failure_shows_hint(self, mock_run, cli_runner, tmp_path):
        err = subprocess.CalledProcessError(1, "launchctl")
        err.stderr = b"already loaded"
        mock_run.side_effect = err
        plist_dest = tmp_path / "test.plist"

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "install"])

        # Should not crash — show hint
        assert result.exit_code == 0
        assert "launchctl load" in result.output

    @patch("pm.cli.subprocess.run")
    def test_install_custom_hour(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        plist_dest = tmp_path / "test.plist"

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "install", "--hour", "4"])

        assert "04:00" in result.output


# ---------------------------------------------------------------------------
# pm schedule uninstall
# ---------------------------------------------------------------------------

class TestScheduleUninstall:
    @patch("pm.cli.subprocess.run")
    def test_uninstall_deletes_plist(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        plist_dest = tmp_path / "test.plist"
        plist_dest.write_text("<plist/>")  # Simulate installed

        with patch("pm.cli._PLIST_PATH", plist_dest):
            result = cli_runner.invoke(main, ["schedule", "uninstall"])

        assert not plist_dest.exists()
        assert "Uninstalled" in result.output

    def test_uninstall_not_installed_graceful(self, cli_runner, tmp_path):
        plist_dest = tmp_path / "missing.plist"

        with patch("pm.cli._PLIST_PATH", plist_dest):
            result = cli_runner.invoke(main, ["schedule", "uninstall"])

        assert result.exit_code == 0
        assert "Not installed" in result.output


# ---------------------------------------------------------------------------
# pm schedule status
# ---------------------------------------------------------------------------

class TestScheduleStatus:
    def test_status_not_installed(self, cli_runner, tmp_path):
        plist_dest = tmp_path / "missing.plist"
        with patch("pm.cli._PLIST_PATH", plist_dest):
            result = cli_runner.invoke(main, ["schedule", "status"])
        assert result.exit_code == 0
        assert "pm schedule install" in result.output

    @patch("pm.cli.subprocess.run")
    def test_status_loaded(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        plist_dest = tmp_path / "test.plist"
        plist_dest.write_text("<plist/>")

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "status"])

        assert "loaded" in result.output.lower()

    @patch("pm.cli.subprocess.run")
    def test_status_not_loaded(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        plist_dest = tmp_path / "test.plist"
        plist_dest.write_text("<plist/>")

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "status"])

        assert "not loaded" in result.output.lower() or "exists" in result.output.lower()

    @patch("pm.cli.subprocess.run")
    def test_status_shows_last_log_line(self, mock_run, cli_runner, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        plist_dest = tmp_path / "test.plist"
        plist_dest.write_text("<plist/>")
        log_file = tmp_path / "agent-batch.log"
        log_file.write_text("line1\nline2\nMost recent log line")

        with patch("pm.cli._PLIST_PATH", plist_dest), \
             patch("pm.cli._LOG_DIR", tmp_path):
            result = cli_runner.invoke(main, ["schedule", "status"])

        assert "Most recent log line" in result.output
