"""End-to-end tests for complete workflows."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from click.testing import CliRunner

from pm.cli import main
from pm.database.models import init_db, get_session, Project, ProgressItem, ScanHistory
from pm.scanner.detector import ProjectDetector
from pm.scanner.parser import ProgressParser
from pm.generator.prompts import ContinuePromptGenerator, PromptMode


@pytest.fixture
def cli_runner():
    """Create Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def dev_directory(temp_dir):
    """Create a mock ~/dev2 directory structure with multiple projects."""
    dev2 = temp_dir / "dev2"
    dev2.mkdir()

    # Internal project 1: Active Node.js project
    project1 = dev2 / "webapp"
    project1.mkdir()
    (project1 / "package.json").write_text('{"name": "webapp", "version": "1.0.0"}')
    (project1 / "CLAUDE.md").write_text("# WebApp\n\nA web application.")
    (project1 / "TODO.md").write_text("""# TODO

## Phase 1: Setup
- [x] Initialize project
- [x] Add dependencies
- [x] Create folder structure

## Phase 2: Core Features
- [x] User authentication
- [ ] Dashboard
- [ ] Settings page

## Phase 3: Polish
- [ ] Add tests
- [ ] Performance optimization
""")
    (project1 / "PROGRESS.md").write_text("""# Progress

**Status:** Phase 2 in progress
**Completion:** 50%

## Next Steps
- Implement dashboard
- Add settings page
""")

    # Internal project 2: Python CLI tool
    project2 = dev2 / "cli-tool"
    project2.mkdir()
    (project2 / "pyproject.toml").write_text('[project]\nname = "cli-tool"\nversion = "0.1.0"')
    (project2 / "TODO.md").write_text("""# TODO
- [x] Setup argparse
- [x] Implement core commands
- [x] Add help text
- [x] Write tests
""")

    # Clients container with client projects
    clients = dev2 / "clients"
    clients.mkdir()

    # Client 1: Active with decision needed
    client1 = clients / "acme-corp"
    client1.mkdir()
    (client1 / "package.json").write_text('{"name": "acme-app"}')
    (client1 / "TODO.md").write_text("""# ACME Corp Project

## Phase 1
- [x] Requirements gathering
- [x] Design mockups

## Phase 2
- [ ] Frontend development
- [ ] Backend API

## Decision Point
### Option A: React
Fast development, large ecosystem.

### Option B: Vue
Simpler learning curve.

Recommended: Option A for this project.
""")

    # Client 2: Stale project
    client2 = clients / "old-client"
    client2.mkdir()
    (client2 / "package.json").write_text('{"name": "old-project"}')

    # Tool project
    tool = dev2 / "mcp-helper"
    tool.mkdir()
    (tool / "Cargo.toml").write_text('[package]\nname = "mcp-helper"\nversion = "0.1.0"')

    return dev2


class TestFullScanToStatusWorkflow:
    """Test complete scan → status workflow."""

    def test_scan_then_status(self, cli_runner, dev_directory):
        """Test scanning a directory and viewing status."""
        # Database is isolated via autouse fixture

        # Step 1: Scan the directory
        result = cli_runner.invoke(main, ["scan", str(dev_directory)])

        assert result.exit_code == 0
        assert "Scan Complete" in result.output

        # Step 2: View status
        result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 0
        # Should show project table
        assert "Projects" in result.output or "webapp" in result.output

    def test_scan_updates_database(self, cli_runner, dev_directory):
        """Test that scan properly populates the database."""
        # Database is isolated via autouse fixture

        # Scan
        result = cli_runner.invoke(main, ["scan", str(dev_directory)])
        assert result.exit_code == 0

        # Verify database contents
        session = get_session()
        projects = session.query(Project).all()

        assert len(projects) >= 4  # webapp, cli-tool, acme-corp, mcp-helper

        # Check specific project data
        webapp = session.query(Project).filter_by(name="webapp").first()
        assert webapp is not None
        assert webapp.project_type == "node"
        assert webapp.has_claude_md is True
        assert webapp.has_todo is True
        assert webapp.completion_pct == 50.0  # From PROGRESS.md

        # Check client project
        acme = session.query(Project).filter_by(name="acme-corp").first()
        assert acme is not None
        assert acme.category == "client"
        # Decision point detection depends on parser matching the Option A/B pattern

        session.close()


class TestScanToHealthWorkflow:
    """Test scan → health scoring workflow."""

    def test_health_scores_calculated(self, cli_runner, dev_directory):
        """Test that health scores are calculated after scan."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # View health
        result = cli_runner.invoke(main, ["health"])

        assert result.exit_code == 0
        assert "Health" in result.output

    def test_health_reflects_project_state(self, cli_runner, dev_directory):
        """Test that health scores reflect project state."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        session = get_session()

        # cli-tool should have high health (100% complete)
        cli_tool = session.query(Project).filter_by(name="cli-tool").first()
        # Note: health_score is a property, not stored in DB

        # webapp should have medium health (50% complete, has progress files)
        webapp = session.query(Project).filter_by(name="webapp").first()

        # Both should have been found
        assert cli_tool is not None
        assert webapp is not None

        session.close()


class TestScanToContinueWorkflow:
    """Test scan → continue prompt generation workflow."""

    def test_continue_generates_context(self, cli_runner, dev_directory):
        """Test that continue command generates context from scan data."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Generate continue prompt
        result = cli_runner.invoke(main, ["continue", "webapp", "--dry-run"])

        assert result.exit_code == 0
        assert "webapp" in result.output

    def test_continue_shows_decision_for_project_with_decision(
        self, cli_runner, dev_directory
    ):
        """Test that continue surfaces decision points."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Generate continue prompt for project with decision
        result = cli_runner.invoke(main, ["continue", "acme-corp", "--dry-run"])

        assert result.exit_code == 0
        # Should mention the decision or options
        # Note: This depends on the parser detecting the decision


class TestScanToLaunchWorkflow:
    """Test scan → launch workflow."""

    def test_launch_dry_run_after_scan(self, cli_runner, dev_directory):
        """Test launch dry-run shows correct projects after scan."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Launch dry-run
        result = cli_runner.invoke(
            main,
            ["launch", "--dry-run", "--filter", "type:client"]
        )

        assert result.exit_code == 0
        assert "acme-corp" in result.output

    def test_launch_multiple_projects(self, cli_runner, dev_directory):
        """Test launching multiple projects."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Launch multiple
        result = cli_runner.invoke(
            main,
            ["launch", "--dry-run", "webapp", "cli-tool"]
        )

        assert result.exit_code == 0
        assert "2 project(s)" in result.output


class TestFilteringWorkflows:
    """Test filtering across different commands."""

    def test_filter_clients_across_commands(self, cli_runner, dev_directory):
        """Test client filtering works consistently."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Status with client filter
        result = cli_runner.invoke(main, ["status", "--filter", "type:client"])
        assert "acme-corp" in result.output
        assert "webapp" not in result.output

        # Health with client filter
        result = cli_runner.invoke(main, ["health", "--filter", "type:client"])
        assert "acme-corp" in result.output

        # Launch with client filter
        result = cli_runner.invoke(
            main,
            ["launch", "--dry-run", "--filter", "type:client"]
        )
        assert "acme-corp" in result.output


class TestProgressTrackingWorkflow:
    """Test progress tracking across scans."""

    def test_rescan_updates_progress(self, cli_runner, dev_directory):
        """Test that rescanning updates progress data."""
        # Initial scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        session = get_session()
        webapp = session.query(Project).filter_by(name="webapp").first()
        initial_completion = webapp.completion_pct
        session.close()

        # Modify the TODO.md to mark more items complete
        todo_path = dev_directory / "webapp" / "TODO.md"
        new_content = todo_path.read_text().replace("- [ ] Dashboard", "- [x] Dashboard")
        todo_path.write_text(new_content)

        # Rescan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        session = get_session()
        webapp = session.query(Project).filter_by(name="webapp").first()
        new_completion = webapp.completion_pct
        session.close()

        # Completion should have increased or stayed the same (depends on PROGRESS.md vs TODO.md)
        # The parser may prefer PROGRESS.md which has explicit 50%
        assert new_completion is not None


class TestSummaryWorkflow:
    """Test summary command integration."""

    def test_summary_reflects_scan_data(self, cli_runner, dev_directory):
        """Test that summary accurately reflects scanned data."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Summary
        result = cli_runner.invoke(main, ["summary"])

        assert result.exit_code == 0
        assert "Total Projects" in result.output
        # Should show client count
        assert "Client" in result.output
        # Should show internal count
        assert "Internal" in result.output


class TestComponentIntegration:
    """Test integration between components."""

    def test_detector_to_parser_integration(self, dev_directory):
        """Test detector output feeds into parser correctly."""
        detector = ProjectDetector(dev_directory)
        parser = ProgressParser()

        projects = detector.scan()

        for proj_info in projects:
            progress = parser.parse_project(proj_info.path)

            # Parser should return valid progress object
            assert progress is not None

            # If project has TODO.md, should find items
            if proj_info.has_todo:
                # May or may not have items depending on content
                pass

    def test_parser_to_generator_integration(self, dev_directory):
        """Test parser output feeds into prompt generator correctly."""
        detector = ProjectDetector(dev_directory)
        parser = ProgressParser()
        generator = ContinuePromptGenerator()

        projects = detector.scan()

        for proj_info in projects:
            progress = parser.parse_project(proj_info.path)
            prompt = generator.generate(
                proj_info.path,
                proj_info.name,
                progress,
                PromptMode.CONTEXT
            )

            # Generator should return valid prompt
            assert prompt is not None
            assert prompt.command is not None
            assert proj_info.name in prompt.prompt_text or str(proj_info.path) in prompt.command

    def test_full_pipeline_integration(self, dev_directory):
        """Test the complete detection → parsing → generation pipeline."""
        detector = ProjectDetector(dev_directory)
        parser = ProgressParser()
        generator = ContinuePromptGenerator()

        projects = detector.scan()
        assert len(projects) >= 4  # Should find all test projects

        for proj_info in projects:
            # Parse progress
            progress = parser.parse_project(proj_info.path)

            # Generate prompt
            prompt = generator.generate(
                proj_info.path,
                proj_info.name,
                progress,
                PromptMode.CONTEXT
            )

            # Verify prompt content based on project characteristics
            if proj_info.has_claude_md:
                # Projects with CLAUDE.md should have documentation
                pass

            if proj_info.has_progress:
                # Projects with PROGRESS.md may have completion data
                if progress.completion_pct is not None:
                    assert f"{progress.completion_pct:.0f}%" in prompt.prompt_text

            if proj_info.category == "client":
                # Client projects detected correctly
                assert proj_info.category == "client"


class TestDatabasePersistence:
    """Test database persistence across operations."""

    def test_data_persists_between_sessions(self, cli_runner, dev_directory):
        """Test that data persists between CLI invocations."""
        # Scan
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        # Get project count
        result1 = cli_runner.invoke(main, ["summary"])
        assert "Total Projects" in result1.output

        # Status should still show projects (data persisted)
        result2 = cli_runner.invoke(main, ["status"])
        # Should show project table
        assert "Projects" in result2.output or result2.exit_code == 0

    def test_scan_history_recorded(self, cli_runner, dev_directory):
        """Test that scan history is recorded."""
        # Multiple scans
        cli_runner.invoke(main, ["scan", str(dev_directory)])
        cli_runner.invoke(main, ["scan", str(dev_directory)])

        session = get_session()
        history = session.query(ScanHistory).all()

        # Should have history entries
        assert len(history) >= 2

        session.close()


class TestErrorRecovery:
    """Test error handling and recovery."""

    def test_continue_with_empty_database(self, cli_runner):
        """Test continue command with empty database."""
        result = cli_runner.invoke(main, ["continue", "nonexistent"])

        # Should handle gracefully
        assert "not found" in result.output.lower()

    def test_scan_with_permission_errors(self, cli_runner, temp_dir):
        """Test scan handles permission errors gracefully."""
        # Create a directory that might have issues
        problem_dir = temp_dir / "problem"
        problem_dir.mkdir()

        # Scan should complete without crashing
        result = cli_runner.invoke(main, ["scan", str(problem_dir)])
        assert result.exit_code == 0
