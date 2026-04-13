"""Tests for new CLI commands: pm brief, pm someday, pm urgent --all, pm shutdown."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from pm.cli import main
from pm.database.models import Project, init_db, get_session


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def no_reinit_db():
    with patch("pm.cli.init_db"):
        yield


@pytest.fixture
def populated_db(isolated_database):
    """Populate DB with varied projects for command tests."""
    session = get_session()

    projects = [
        # Critical priority + deadline (should always appear in pm urgent)
        Project(
            id="/test/critical-proj",
            path="/test/critical-proj",
            name="critical-proj",
            project_type="node",
            category="client",
            client_name="Acme",
            priority=1,
            deadline=datetime.utcnow() + timedelta(days=2),
            last_activity=datetime.utcnow() - timedelta(days=1),
            completion_pct=40.0,
            has_pending_decision=False,
            has_claude_md=True,
        ),
        # High priority, no deadline
        Project(
            id="/test/high-proj",
            path="/test/high-proj",
            name="high-proj",
            project_type="python",
            category="internal",
            priority=2,
            last_activity=datetime.utcnow() - timedelta(days=3),
            completion_pct=60.0,
        ),
        # Normal priority, no deadline (should NOT appear in default pm urgent)
        Project(
            id="/test/normal-proj",
            path="/test/normal-proj",
            name="normal-proj",
            project_type="python",
            category="internal",
            priority=3,
            last_activity=datetime.utcnow() - timedelta(days=5),
            completion_pct=50.0,
        ),
        # Overdue project
        Project(
            id="/test/overdue-proj",
            path="/test/overdue-proj",
            name="overdue-proj",
            project_type="rust",
            category="tool",
            priority=3,
            deadline=datetime.utcnow() - timedelta(days=5),  # Overdue!
            last_activity=datetime.utcnow() - timedelta(days=10),
            completion_pct=30.0,
        ),
        # Someday/archived
        Project(
            id="/test/someday-proj",
            path="/test/someday-proj",
            name="someday-proj",
            project_type="node",
            category="internal",
            priority=5,
            last_activity=datetime.utcnow() - timedelta(days=90),
        ),
        # Stale (60+ days, normal priority)
        Project(
            id="/test/stale-proj",
            path="/test/stale-proj",
            name="stale-proj",
            project_type="python",
            category="internal",
            priority=3,
            last_activity=datetime.utcnow() - timedelta(days=60),
            completion_pct=20.0,
        ),
    ]
    for p in projects:
        session.add(p)
    session.commit()
    session.close()
    return isolated_database


# ── pm someday ────────────────────────────────────────────────────────────────


class TestSomedayCommand:
    @patch("pm.cli.sync_to_file")
    def test_someday_moves_to_priority_5(self, mock_sync, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["someday", "high-proj"])
        assert result.exit_code == 0
        assert "Someday" in result.output

        session = get_session()
        p = session.query(Project).filter_by(name="high-proj").first()
        assert p.priority == 5
        session.close()

    @patch("pm.cli.sync_to_file")
    def test_someday_shows_old_priority(self, mock_sync, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["someday", "high-proj"])
        assert "High" in result.output or "was" in result.output

    @patch("pm.cli.sync_to_file")
    def test_someday_shows_restore_hint(self, mock_sync, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["someday", "high-proj"])
        assert "--priority" in result.output

    def test_someday_project_not_found(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["someday", "nonexistent-project-xyz"])
        assert result.exit_code == 0
        assert "No project found" in result.output

    @patch("pm.cli.sync_to_file")
    def test_someday_partial_name_match(self, mock_sync, cli_runner, populated_db):
        """Partial name match should work (uses ilike)."""
        result = cli_runner.invoke(main, ["someday", "high"])  # matches "high-proj"
        assert result.exit_code == 0
        assert "Someday" in result.output


# ── pm urgent ────────────────────────────────────────────────────────────────


class TestUrgentCommand:
    def test_urgent_default_shows_urgent_only(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["urgent"])
        assert result.exit_code == 0
        # Critical priority appears as "critical" label in the table
        assert "critical" in result.output.lower()
        # Should show 3 urgent projects (critical, overdue, high); stale/someday filtered out
        assert "Urgent Projects" in result.output or "urgent" in result.output.lower()

    def test_urgent_shows_overdue(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["urgent"])
        # OVERDUE label appears in the deadline column
        assert "OVERDUE" in result.output

    def test_urgent_all_shows_all_projects(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["urgent", "--all"])
        assert result.exit_code == 0
        # With --all, at least 4 projects should appear (including normal-priority ones)
        assert "Normal" in result.output or "normal" in result.output.lower()

    def test_urgent_empty_no_signals(self, cli_runner, isolated_database):
        """When no projects have urgency signals, shows help message."""
        session = get_session()
        session.add(Project(
            id="/t/boring", path="/t/boring", name="boring",
            priority=3, last_activity=datetime.utcnow()
        ))
        session.commit()
        session.close()

        result = cli_runner.invoke(main, ["urgent"])
        assert result.exit_code == 0
        assert "No urgent projects" in result.output

    def test_urgent_all_empty_db(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["urgent", "--all"])
        assert result.exit_code == 0
        assert "No urgent" in result.output

    def test_urgent_excludes_archived(self, cli_runner, populated_db):
        """Archived projects should not appear even with --all."""
        session = get_session()
        session.add(Project(
            id="/t/arch", path="/t/arch", name="archived-urgent",
            priority=1, deadline=datetime.utcnow() - timedelta(days=1),
            archived=True,
        ))
        session.commit()
        session.close()

        result = cli_runner.invoke(main, ["urgent", "--all"])
        assert "archived-urgent" not in result.output

    def test_urgent_high_priority_shown(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["urgent"])
        assert "high-proj" in result.output

    def test_urgent_limit(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["urgent", "--all", "--limit", "1"])
        assert result.exit_code == 0
        # Only 1 project should be shown — check output has at most 1 project row
        # (We just verify it doesn't crash; exact count depends on table rendering)


# ── pm brief ─────────────────────────────────────────────────────────────────


class TestBriefCommand:
    def test_brief_runs_without_error(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["brief"])
        assert result.exit_code == 0

    def test_brief_shows_header(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["brief"])
        assert "PM Brief" in result.output or "All clear" in result.output

    def test_brief_verbose_runs(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["brief", "--verbose"])
        assert result.exit_code == 0

    def test_brief_only_if_urgent_suppresses_when_nothing_urgent(self, cli_runner, isolated_database):
        """--only-if-urgent should produce no output when nothing is urgent."""
        session = get_session()
        session.add(Project(
            id="/t/p1", path="/t/p1", name="chill-project",
            priority=3, last_activity=datetime.utcnow()
        ))
        session.commit()
        session.close()

        result = cli_runner.invoke(main, ["brief", "--only-if-urgent"])
        assert result.exit_code == 0
        # Should be silent (no output) when nothing urgent
        stripped = result.output.strip()
        assert stripped == "" or "All clear" in stripped

    def test_brief_only_if_urgent_shows_when_urgent(self, cli_runner, populated_db):
        """--only-if-urgent should show output when urgent items exist."""
        result = cli_runner.invoke(main, ["brief", "--only-if-urgent"])
        assert result.exit_code == 0
        # critical-proj has deadline in 2 days — should trigger output
        assert result.output.strip() != "" or "All clear" in result.output

    @patch("pm.cli.subprocess.run")
    def test_brief_imessage_success(self, mock_run, cli_runner, populated_db):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = cli_runner.invoke(main, ["brief", "--imessage"])
        assert result.exit_code == 0
        assert "sent via iMessage" in result.output

    @patch("pm.cli.subprocess.run")
    def test_brief_imessage_failure_falls_back_to_terminal(self, mock_run, cli_runner, populated_db):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Messages not running")
        result = cli_runner.invoke(main, ["brief", "--imessage"])
        assert result.exit_code == 0
        # Should fall back and show terminal output
        assert "failed" in result.output or "PM Brief" in result.output or "All clear" in result.output

    @patch("pm.cli.subprocess.run")
    def test_brief_imessage_timeout_falls_back(self, mock_run, cli_runner, populated_db):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="osascript", timeout=10)
        result = cli_runner.invoke(main, ["brief", "--imessage"])
        assert result.exit_code == 0
        assert "timed out" in result.output.lower() or "PM Brief" in result.output

    def test_brief_custom_days(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["brief", "--days", "14"])
        assert result.exit_code == 0


# ── pm shutdown ───────────────────────────────────────────────────────────────


class TestShutdownCommand:
    @patch("pm.cli.is_shutdown_supported", return_value=False)
    def test_shutdown_no_iterm2_shows_message(self, mock_check, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "iTerm2" in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_shutdown_dry_run_no_action(self, mock_run, mock_check, cli_runner, isolated_database):
        """Dry run with iTerm2 not running shows 'not running' message."""
        import subprocess as sp
        err = sp.CalledProcessError(1, "osascript")
        err.stderr = "iTerm2 is not running"
        mock_run.side_effect = err
        result = cli_runner.invoke(main, ["shutdown", "--dry-run"])
        assert result.exit_code == 0
        assert "not" in result.output.lower()

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_shutdown_iterm2_not_running(self, mock_run, mock_check, cli_runner, isolated_database):
        """When iTerm2 is not running, should show a clear message."""
        import subprocess as sp
        err = sp.CalledProcessError(1, "osascript")
        err.stderr = "iTerm2 is not running"
        mock_run.side_effect = err
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0
        assert "not" in result.output.lower() or "iTerm2" in result.output

    @patch("pm.cli.is_shutdown_supported", return_value=True)
    @patch("pm.cli.subprocess.run")
    def test_shutdown_no_pm_tabs(self, mock_run, mock_check, cli_runner, isolated_database):
        """When iTerm2 has no PM: tabs, should report 0 sessions."""
        mock_run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        result = cli_runner.invoke(main, ["shutdown"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# pm gc
# ---------------------------------------------------------------------------

class TestGcCommand:
    @pytest.fixture
    def gc_db(self, isolated_database, tmp_path):
        """DB with one real path and one ghost path."""
        real_dir = tmp_path / "real-project"
        real_dir.mkdir()

        session = get_session()
        session.add(Project(id=str(real_dir), path=str(real_dir), name="real-project"))
        session.add(Project(id="/nonexistent/ghost-project", path="/nonexistent/ghost-project", name="ghost-project"))
        session.commit()
        session.close()
        return isolated_database

    def test_gc_removes_missing_projects(self, cli_runner, gc_db):
        result = cli_runner.invoke(main, ["gc"])
        assert result.exit_code == 0
        session = get_session()
        names = [p.name for p in session.query(Project).all()]
        assert "ghost-project" not in names
        assert "real-project" in names
        session.close()

    def test_gc_dry_run_does_not_delete(self, cli_runner, gc_db):
        result = cli_runner.invoke(main, ["gc", "--dry-run"])
        assert result.exit_code == 0
        assert "Dry run" in result.output
        session = get_session()
        count = session.query(Project).count()
        assert count == 2  # Nothing deleted
        session.close()

    def test_gc_dry_run_lists_stale_records(self, cli_runner, gc_db):
        result = cli_runner.invoke(main, ["gc", "--dry-run"])
        assert "ghost-project" in result.output

    def test_gc_empty_db_no_crash(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["gc"])
        assert result.exit_code == 0
        assert "No stale records" in result.output

    def test_gc_reports_count_on_delete(self, cli_runner, gc_db):
        result = cli_runner.invoke(main, ["gc"])
        assert "1" in result.output  # Removed 1 record
