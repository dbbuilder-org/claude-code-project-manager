"""Tests for the pm.docgen module."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from pm.docgen.templates import (
    DocTemplate,
    BUILTIN_TEMPLATES,
    get_template,
    READ_ONLY_TOOLS,
)
from pm.docgen.context import ProjectContext, build_context
from pm.docgen.executor import run_doc_generation, run_batch_generation, DocResult
from pm.database.models import Project, DocGeneration, get_session, init_db


# --- Template Tests ---


class TestDocTemplate:
    """Tests for DocTemplate dataclass."""

    def test_builtin_templates_exist(self):
        """All 7 built-in templates should be registered."""
        expected_ids = [
            "roadmap", "architecture", "code-review",
            "test-coverage", "next-phase", "status-report",
            "weekly-summary",
        ]
        for tid in expected_ids:
            assert tid in BUILTIN_TEMPLATES, f"Missing template: {tid}"

    def test_builtin_template_count(self):
        """Should have exactly 7 built-in templates."""
        assert len(BUILTIN_TEMPLATES) == 7

    def test_get_template_found(self):
        """get_template should return template for valid ID."""
        tmpl = get_template("roadmap")
        assert tmpl is not None
        assert tmpl.id == "roadmap"
        assert tmpl.name == "Roadmap & TODO"

    def test_get_template_not_found(self):
        """get_template should return None for invalid ID."""
        assert get_template("nonexistent") is None

    def test_template_output_path(self):
        """output_path property should combine dir and filename."""
        tmpl = get_template("roadmap")
        assert tmpl.output_path == "docs/ROADMAP.md"

    def test_template_output_path_root_dir(self):
        """output_path with '.' dir should be filename only."""
        tmpl = DocTemplate(
            id="test",
            name="Test",
            description="Test template",
            output_filename="TEST.md",
            output_dir=".",
            max_budget_usd=0.25,
        )
        assert tmpl.output_path == "TEST.md"

    def test_template_render(self):
        """render() should substitute context values into prompt."""
        tmpl = get_template("roadmap")
        ctx = ProjectContext(
            name="my-project",
            path=Path("/test/my-project"),
            project_type="python",
            category="internal",
            completion_pct=45.0,
            current_phase="Phase 2",
            next_action="Write tests",
            git_branch="main",
            git_dirty=False,
            last_commit_msg="Fix bug",
            has_claude_md=True,
            has_todo=True,
            has_progress=True,
            health_score=70,
            urgency_score=30,
            priority=2,
            deadline="2026-03-01",
            tags=["python", "cli"],
            notes="Some notes",
        )

        rendered = tmpl.render(ctx)
        assert "my-project" in rendered
        assert "python" in rendered
        assert "Phase 2" in rendered
        assert "45%" in rendered
        assert "Write tests" in rendered
        assert "2026-03-01" in rendered

    def test_template_render_empty_tags(self):
        """render() should handle empty tags list."""
        tmpl = get_template("status-report")
        ctx = ProjectContext(
            name="proj",
            path=Path("/test"),
            project_type="node",
            category="client",
            completion_pct=0.0,
            current_phase="",
            next_action="",
            git_branch="main",
            git_dirty=False,
            last_commit_msg="",
            has_claude_md=False,
            has_todo=False,
            has_progress=False,
            health_score=0,
            urgency_score=0,
            priority=3,
            tags=[],
            notes="",
        )
        rendered = tmpl.render(ctx)
        assert "None" in rendered  # Tags should show "None"

    def test_template_render_no_deadline(self):
        """render() should handle None deadline."""
        tmpl = get_template("roadmap")
        ctx = ProjectContext(
            name="proj",
            path=Path("/test"),
            project_type="node",
            category="internal",
            completion_pct=50.0,
            current_phase="Phase 1",
            next_action="Do stuff",
            git_branch="dev",
            git_dirty=True,
            last_commit_msg="WIP",
            has_claude_md=True,
            has_todo=True,
            has_progress=False,
            health_score=50,
            urgency_score=10,
            priority=3,
            deadline=None,
            tags=["test"],
        )
        rendered = tmpl.render(ctx)
        assert "None set" in rendered

    def test_all_templates_have_required_fields(self):
        """All templates should have non-empty required fields."""
        for tid, tmpl in BUILTIN_TEMPLATES.items():
            assert tmpl.id, f"{tid} missing id"
            assert tmpl.name, f"{tid} missing name"
            assert tmpl.description, f"{tid} missing description"
            assert tmpl.output_filename, f"{tid} missing output_filename"
            assert tmpl.output_dir, f"{tid} missing output_dir"
            assert tmpl.max_budget_usd > 0, f"{tid} has invalid budget"
            assert tmpl.prompt_template, f"{tid} missing prompt_template"
            assert tmpl.allowed_tools, f"{tid} missing allowed_tools"

    def test_templates_use_read_only_tools(self):
        """All templates should use read-only tools (no Write/Edit/Bash)."""
        dangerous_tools = {"Write", "Edit", "Bash", "NotebookEdit"}
        for tid, tmpl in BUILTIN_TEMPLATES.items():
            for tool in tmpl.allowed_tools:
                assert tool not in dangerous_tools, (
                    f"Template {tid} uses dangerous tool: {tool}"
                )


# --- Context Tests ---


class TestProjectContext:
    """Tests for ProjectContext building."""

    def test_build_context_from_project(self, db_session):
        """build_context should populate all fields from Project model."""
        project = Project(
            id="/test/my-proj",
            path="/test/my-proj",
            name="my-proj",
            project_type="python",
            category="internal",
            completion_pct=65.0,
            current_phase="Phase 3",
            next_action="Deploy to prod",
            git_branch="main",
            git_dirty=True,
            last_commit_msg="Add feature X",
            has_claude_md=True,
            has_todo=True,
            has_progress=True,
            priority=2,
            deadline=datetime(2026, 3, 15),
            tags=json.dumps(["python", "api"]),
            notes="Important project",
        )
        db_session.add(project)
        db_session.commit()

        ctx = build_context(project)

        assert ctx.name == "my-proj"
        assert ctx.path == Path("/test/my-proj")
        assert ctx.project_type == "python"
        assert ctx.category == "internal"
        assert ctx.completion_pct == 65.0
        assert ctx.current_phase == "Phase 3"
        assert ctx.next_action == "Deploy to prod"
        assert ctx.git_branch == "main"
        assert ctx.git_dirty is True
        assert ctx.last_commit_msg == "Add feature X"
        assert ctx.has_claude_md is True
        assert ctx.priority == 2
        assert ctx.deadline == "2026-03-15"
        assert ctx.tags == ["python", "api"]
        assert ctx.notes == "Important project"
        assert ctx.health_score >= 0
        assert ctx.urgency_score >= 0

    def test_build_context_handles_nulls(self, db_session):
        """build_context should handle None/missing fields gracefully."""
        project = Project(
            id="/test/empty",
            path="/test/empty",
            name="empty",
        )
        db_session.add(project)
        db_session.commit()

        ctx = build_context(project)

        assert ctx.name == "empty"
        assert ctx.project_type == "unknown"
        assert ctx.category == "internal"
        assert ctx.completion_pct == 0.0
        assert ctx.current_phase == ""
        assert ctx.next_action == ""
        assert ctx.git_branch == "main"
        assert ctx.git_dirty is False
        assert ctx.deadline is None
        assert ctx.tags == []
        assert ctx.notes == ""

    def test_build_context_invalid_json_tags(self, db_session):
        """build_context should handle invalid JSON in tags field."""
        project = Project(
            id="/test/bad-tags",
            path="/test/bad-tags",
            name="bad-tags",
            tags="not valid json",
        )
        db_session.add(project)
        db_session.commit()

        ctx = build_context(project)
        assert ctx.tags == []


# --- Executor Tests ---


class TestDocResult:
    """Tests for DocResult dataclass."""

    def test_doc_result_success(self):
        """DocResult should hold success data."""
        result = DocResult(
            project_name="myproj",
            template_id="roadmap",
            output_path=Path("/test/docs/ROADMAP.md"),
            status="success",
            duration_secs=12.5,
            file_size_bytes=4096,
        )
        assert result.status == "success"
        assert result.duration_secs == 12.5
        assert result.file_size_bytes == 4096

    def test_doc_result_error(self):
        """DocResult should hold error data."""
        result = DocResult(
            project_name="myproj",
            template_id="roadmap",
            output_path=None,
            status="error",
            error_message="Something failed",
        )
        assert result.status == "error"
        assert result.error_message == "Something failed"


class TestRunDocGeneration:
    """Tests for run_doc_generation with mocked subprocess."""

    @patch("pm.docgen.executor.subprocess.run")
    def test_successful_generation(self, mock_run, temp_dir):
        """Successful generation should write file and return success."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="# Roadmap\n\nThis is the generated roadmap.",
            stderr="",
        )

        output_file = temp_dir / "docs" / "ROADMAP.md"

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate a roadmap",
            output_file=output_file,
            max_budget_usd=0.50,
            allowed_tools=["Read", "Glob", "Grep"],
        )

        assert result.status == "success"
        assert result.output_path == output_file
        assert result.file_size_bytes > 0
        assert result.duration_secs >= 0
        assert output_file.exists()
        assert "Roadmap" in output_file.read_text()

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_builds_correct_command(self, mock_run, temp_dir):
        """Should build the correct claude CLI command."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="# Output",
            stderr="",
        )

        output_file = temp_dir / "docs" / "TEST.md"

        run_doc_generation(
            project_path=temp_dir,
            prompt="Test prompt",
            output_file=output_file,
            max_budget_usd=0.75,
            allowed_tools=["Read", "Glob"],
        )

        mock_run.assert_called_once()
        call_args = mock_run.call_args

        cmd = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "Test prompt" in cmd
        assert "--output-format" in cmd
        assert "text" in cmd
        assert "--permission-mode" in cmd
        assert "--max-budget-usd" in cmd
        assert "0.75" in cmd
        assert "--allowedTools" in cmd
        assert "Read,Glob" in cmd
        assert str(call_args[1].get("cwd", call_args.kwargs.get("cwd"))) == str(temp_dir)

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_error_nonzero_exit(self, mock_run, temp_dir):
        """Non-zero exit code should return error status."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="API key invalid",
        )

        output_file = temp_dir / "docs" / "ROADMAP.md"

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate",
            output_file=output_file,
        )

        assert result.status == "error"
        assert "API key invalid" in result.error_message
        assert not output_file.exists()

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_empty_output(self, mock_run, temp_dir):
        """Empty stdout should return error."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

        output_file = temp_dir / "docs" / "ROADMAP.md"

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate",
            output_file=output_file,
        )

        assert result.status == "error"
        assert "empty" in result.error_message.lower()

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_timeout(self, mock_run, temp_dir):
        """TimeoutExpired should return timeout status."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)

        output_file = temp_dir / "docs" / "ROADMAP.md"

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate",
            output_file=output_file,
            timeout=300,
        )

        assert result.status == "timeout"
        assert "300" in result.error_message

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_claude_not_found(self, mock_run, temp_dir):
        """FileNotFoundError should return error about missing CLI."""
        mock_run.side_effect = FileNotFoundError("No such file: 'claude'")

        output_file = temp_dir / "docs" / "ROADMAP.md"

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate",
            output_file=output_file,
        )

        assert result.status == "error"
        assert "not found" in result.error_message.lower()

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_creates_output_directory(self, mock_run, temp_dir):
        """Should create parent directories for output file."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="# Content",
            stderr="",
        )

        output_file = temp_dir / "deep" / "nested" / "docs" / "ROADMAP.md"
        assert not output_file.parent.exists()

        result = run_doc_generation(
            project_path=temp_dir,
            prompt="Generate",
            output_file=output_file,
        )

        assert result.status == "success"
        assert output_file.parent.exists()
        assert output_file.exists()

    @patch("pm.docgen.executor.subprocess.run")
    def test_generation_no_allowed_tools(self, mock_run, temp_dir):
        """Should work without allowed_tools (omit flag)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="# Output",
            stderr="",
        )

        output_file = temp_dir / "docs" / "OUT.md"

        run_doc_generation(
            project_path=temp_dir,
            prompt="Test",
            output_file=output_file,
            allowed_tools=None,
        )

        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" not in cmd


class TestBatchGeneration:
    """Tests for run_batch_generation."""

    @patch("pm.docgen.executor.run_doc_generation")
    def test_batch_runs_all_tasks(self, mock_gen, temp_dir):
        """Batch should run all tasks and return results."""
        mock_gen.return_value = DocResult(
            project_name="proj",
            template_id="roadmap",
            output_path=temp_dir / "docs" / "ROADMAP.md",
            status="success",
            duration_secs=5.0,
            file_size_bytes=1024,
        )

        tasks = [
            {
                "project_path": temp_dir / "proj1",
                "prompt": "Prompt 1",
                "output_file": temp_dir / "proj1" / "docs" / "ROADMAP.md",
            },
            {
                "project_path": temp_dir / "proj2",
                "prompt": "Prompt 2",
                "output_file": temp_dir / "proj2" / "docs" / "ROADMAP.md",
            },
        ]

        results = run_batch_generation(tasks, max_workers=2)

        assert len(results) == 2
        assert all(r.status == "success" for r in results)
        assert mock_gen.call_count == 2

    @patch("pm.docgen.executor.run_doc_generation")
    def test_batch_calls_progress_callback(self, mock_gen, temp_dir):
        """Batch should call progress_callback for each result."""
        mock_gen.return_value = DocResult(
            project_name="proj",
            template_id="roadmap",
            output_path=None,
            status="success",
        )

        callback_calls = []

        tasks = [
            {
                "project_path": temp_dir,
                "prompt": "P1",
                "output_file": temp_dir / "out1.md",
            },
        ]

        run_batch_generation(
            tasks,
            max_workers=1,
            progress_callback=lambda r: callback_calls.append(r),
        )

        assert len(callback_calls) == 1

    @patch("pm.docgen.executor.run_doc_generation")
    def test_batch_empty_tasks(self, mock_gen, temp_dir):
        """Batch with empty task list should return empty results."""
        results = run_batch_generation([], max_workers=1)
        assert results == []
        assert mock_gen.call_count == 0


# --- Database Model Tests ---


class TestDocGenerationModel:
    """Tests for DocGeneration database model."""

    def test_create_doc_generation(self, db_session):
        """Should create and query DocGeneration records."""
        # Create a project first
        project = Project(
            id="/test/proj",
            path="/test/proj",
            name="proj",
        )
        db_session.add(project)
        db_session.commit()

        doc = DocGeneration(
            project_id="/test/proj",
            template_id="roadmap",
            output_path="docs/ROADMAP.md",
            generated_at=datetime.utcnow(),
            duration_secs=15.2,
            status="success",
            file_size_bytes=2048,
        )
        db_session.add(doc)
        db_session.commit()

        # Query it back
        result = db_session.query(DocGeneration).filter_by(
            project_id="/test/proj",
            template_id="roadmap",
        ).first()

        assert result is not None
        assert result.status == "success"
        assert result.duration_secs == 15.2
        assert result.file_size_bytes == 2048
        assert result.output_path == "docs/ROADMAP.md"

    def test_doc_generation_project_relationship(self, db_session):
        """DocGeneration should link back to Project."""
        project = Project(
            id="/test/linked",
            path="/test/linked",
            name="linked",
        )
        db_session.add(project)
        db_session.commit()

        doc = DocGeneration(
            project_id="/test/linked",
            template_id="architecture",
            status="success",
        )
        db_session.add(doc)
        db_session.commit()

        # Access via relationship
        assert len(project.doc_generations) == 1
        assert project.doc_generations[0].template_id == "architecture"

    def test_doc_generation_error_record(self, db_session):
        """Should store error details."""
        project = Project(
            id="/test/err",
            path="/test/err",
            name="err",
        )
        db_session.add(project)
        db_session.commit()

        doc = DocGeneration(
            project_id="/test/err",
            template_id="code-review",
            status="error",
            error_message="API rate limited",
            duration_secs=2.1,
        )
        db_session.add(doc)
        db_session.commit()

        result = db_session.query(DocGeneration).filter_by(
            project_id="/test/err"
        ).first()

        assert result.status == "error"
        assert result.error_message == "API rate limited"

    def test_cascade_delete(self, db_session):
        """Deleting project should cascade to doc_generations."""
        project = Project(
            id="/test/cascade",
            path="/test/cascade",
            name="cascade",
        )
        db_session.add(project)
        db_session.commit()

        doc = DocGeneration(
            project_id="/test/cascade",
            template_id="roadmap",
            status="success",
        )
        db_session.add(doc)
        db_session.commit()

        # Delete project
        db_session.delete(project)
        db_session.commit()

        # DocGeneration should be gone too
        remaining = db_session.query(DocGeneration).filter_by(
            project_id="/test/cascade"
        ).all()
        assert len(remaining) == 0


# --- CLI Integration Tests ---


class TestDocsCliCommands:
    """Tests for pm docs CLI command group."""

    @pytest.fixture
    def cli_runner(self):
        from click.testing import CliRunner
        return CliRunner()

    @pytest.fixture
    def _noop_init_db(self):
        """Prevent CLI commands from re-initializing the database.

        The isolated_database fixture sets up a temp DB. CLI commands call
        init_db() which would overwrite the connection to the default path.
        This fixture patches init_db to be a no-op so the test DB persists.
        """
        with patch("pm.cli.init_db"):
            yield

    def test_docs_list(self, cli_runner, isolated_database):
        """pm docs list should show all templates."""
        from pm.cli import main
        result = cli_runner.invoke(main, ["docs", "list"])

        assert result.exit_code == 0
        assert "roadmap" in result.output
        assert "architecture" in result.output
        assert "code-review" in result.output
        assert "test-coverage" in result.output
        assert "next-phase" in result.output
        assert "status-report" in result.output
        assert "weekly-summary" in result.output

    def test_docs_generate_dry_run(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs generate --dry-run should preview without executing."""
        from pm.cli import main

        # Create a project in the database
        session = get_session()
        project = Project(
            id="/test/dryrun",
            path="/test/dryrun",
            name="dryrun-project",
            project_type="python",
            category="internal",
        )
        session.add(project)
        session.commit()
        session.close()

        result = cli_runner.invoke(main, [
            "docs", "generate", "roadmap", "dryrun", "--dry-run",
        ])

        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        assert "dryrun" in result.output

    def test_docs_generate_unknown_template(self, cli_runner, isolated_database):
        """pm docs generate with invalid template should error."""
        from pm.cli import main
        result = cli_runner.invoke(main, [
            "docs", "generate", "nonexistent", "someproject",
        ])

        assert result.exit_code == 0
        assert "Unknown template" in result.output

    def test_docs_generate_no_target(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs generate without project or flags should show help."""
        from pm.cli import main
        result = cli_runner.invoke(main, [
            "docs", "generate", "roadmap",
        ])

        assert result.exit_code == 0
        assert "Specify" in result.output or "not found" in result.output.lower()

    def test_docs_history_empty(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs history with no records should show message."""
        from pm.cli import main
        result = cli_runner.invoke(main, ["docs", "history"])

        assert result.exit_code == 0
        assert "No generation history" in result.output

    def test_docs_history_with_records(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs history should show generation records."""
        from pm.cli import main

        session = get_session()
        project = Project(
            id="/test/hist",
            path="/test/hist",
            name="hist-project",
        )
        session.add(project)
        session.commit()

        doc = DocGeneration(
            project_id="/test/hist",
            template_id="roadmap",
            output_path="docs/ROADMAP.md",
            generated_at=datetime.utcnow(),
            duration_secs=10.0,
            status="success",
            file_size_bytes=2048,
        )
        session.add(doc)
        session.commit()
        session.close()

        result = cli_runner.invoke(main, ["docs", "history"])

        assert result.exit_code == 0
        assert "roadmap" in result.output
        assert "hist-project" in result.output

    def test_docs_status_no_projects(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs status with no projects should show message."""
        from pm.cli import main
        result = cli_runner.invoke(main, ["docs", "status"])

        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_docs_status_with_projects(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs status should show document grid."""
        from pm.cli import main

        session = get_session()
        project = Project(
            id="/test/docstatus",
            path="/test/docstatus",
            name="docstatus-project",
            project_type="python",
            category="internal",
        )
        session.add(project)
        session.commit()
        session.close()

        result = cli_runner.invoke(main, ["docs", "status"])

        assert result.exit_code == 0
        assert "docstatus" in result.output
        assert "Document Status" in result.output

    def test_docs_help(self, cli_runner, isolated_database):
        """pm docs --help should show subcommands."""
        from pm.cli import main
        result = cli_runner.invoke(main, ["docs", "--help"])

        assert result.exit_code == 0
        assert "generate" in result.output
        assert "list" in result.output
        assert "history" in result.output
        assert "status" in result.output

    def test_docs_generate_multiple_templates_dry_run(self, cli_runner, isolated_database, _noop_init_db):
        """pm docs generate with comma-separated templates should work."""
        from pm.cli import main

        session = get_session()
        project = Project(
            id="/test/multi",
            path="/test/multi",
            name="multi-project",
            project_type="node",
            category="client",
        )
        session.add(project)
        session.commit()
        session.close()

        result = cli_runner.invoke(main, [
            "docs", "generate", "roadmap,architecture", "multi", "--dry-run",
        ])

        assert result.exit_code == 0
        assert "roadmap" in result.output
        assert "architecture" in result.output
