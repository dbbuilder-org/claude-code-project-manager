"""Unit tests for pm.generator.prompts module."""

import pytest
from pathlib import Path

from pm.generator.prompts import (
    ContinuePromptGenerator, ContinuePrompt, PromptMode,
    generate_continue_prompt
)
from pm.scanner.parser import (
    ProjectProgress, ProgressItem, DecisionPoint, ItemStatus
)


class TestContinuePromptGenerator:
    """Tests for ContinuePromptGenerator class."""

    @pytest.fixture
    def generator(self):
        return ContinuePromptGenerator()

    @pytest.fixture
    def basic_progress(self):
        """Create basic progress without decision points."""
        return ProjectProgress(
            completion_pct=50.0,
            current_phase="Phase 2: Implementation",
            current_status="Active",
            current_focus="Building the API",
            next_action="Complete endpoint implementation",
        )

    @pytest.fixture
    def progress_with_items(self):
        """Create progress with task items."""
        return ProjectProgress(
            completion_pct=60.0,
            current_phase="Phase 2",
            items=[
                ProgressItem(
                    content="Implement user auth",
                    status=ItemStatus.COMPLETE,
                    source_file="TODO.md",
                ),
                ProgressItem(
                    content="Add API endpoints",
                    status=ItemStatus.IN_PROGRESS,
                    source_file="TODO.md",
                ),
                ProgressItem(
                    content="Write tests",
                    status=ItemStatus.PENDING,
                    source_file="TODO.md",
                ),
            ]
        )

    @pytest.fixture
    def progress_with_decision(self):
        """Create progress with a pending decision."""
        return ProjectProgress(
            completion_pct=40.0,
            has_pending_decision=True,
            decisions=[
                DecisionPoint(
                    question="Which database to use?",
                    options=["Option A: PostgreSQL", "Option B: SQLite"],
                    recommendation="PostgreSQL for production",
                )
            ]
        )

    def test_generate_simple_mode(self, generator):
        """Test generating simple resume command."""
        project_path = Path("/test/project")
        progress = ProjectProgress()

        prompt = generator.generate(
            project_path, "test-project", progress, PromptMode.SIMPLE
        )

        assert prompt.mode == PromptMode.SIMPLE
        assert "cd /test/project" in prompt.command
        assert "claude --resume" in prompt.command
        assert prompt.prompt_text is None

    def test_generate_context_mode(self, generator, basic_progress):
        """Test generating context-aware prompt."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", basic_progress, PromptMode.CONTEXT
        )

        assert prompt.mode == PromptMode.CONTEXT
        assert prompt.prompt_text is not None
        assert "test-project" in prompt.prompt_text
        assert "Phase 2" in prompt.prompt_text
        assert "50%" in prompt.prompt_text
        assert "Building the API" in prompt.prompt_text

    def test_generate_includes_next_action(self, generator, basic_progress):
        """Test that next action is included in prompt."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", basic_progress, PromptMode.CONTEXT
        )

        assert "Complete endpoint implementation" in prompt.prompt_text

    def test_generate_includes_next_steps(self, generator):
        """Test that next steps are included when no next_action."""
        progress = ProjectProgress(
            next_steps=["Step 1", "Step 2", "Step 3"]
        )
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress, PromptMode.CONTEXT
        )

        assert "Next steps:" in prompt.prompt_text
        assert "Step 1" in prompt.prompt_text

    def test_generate_includes_in_progress_items(self, generator, progress_with_items):
        """Test that in-progress items are shown."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress_with_items, PromptMode.CONTEXT
        )

        assert "In progress:" in prompt.prompt_text
        assert "Add API endpoints" in prompt.prompt_text

    def test_generate_includes_source_files(self, generator, progress_with_items):
        """Test that source files are referenced."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress_with_items, PromptMode.CONTEXT
        )

        assert "TODO.md" in prompt.prompt_text

    def test_generate_decision_mode_auto_trigger(self, generator, progress_with_decision):
        """Test that decision mode is auto-triggered when decisions exist."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress_with_decision, PromptMode.CONTEXT
        )

        # Should auto-switch to decision mode
        assert prompt.mode == PromptMode.DECISION
        assert prompt.has_decision is True
        assert prompt.decision is not None

    def test_decision_prompt_content(self, generator, progress_with_decision):
        """Test decision prompt includes all decision details."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress_with_decision, PromptMode.DECISION
        )

        assert "DECISION REQUIRED" in prompt.prompt_text
        assert "Which database to use?" in prompt.prompt_text
        assert "PostgreSQL" in prompt.prompt_text
        assert "SQLite" in prompt.prompt_text
        assert "Recommendation" in prompt.prompt_text

    def test_decision_prompt_options_listed(self, generator, progress_with_decision):
        """Test that all decision options are listed."""
        project_path = Path("/test/project")

        prompt = generator.generate(
            project_path, "test-project", progress_with_decision, PromptMode.DECISION
        )

        assert "Option A: PostgreSQL" in prompt.prompt_text
        assert "Option B: SQLite" in prompt.prompt_text

    def test_command_includes_project_path(self, generator, basic_progress):
        """Test that command includes correct project path."""
        project_path = Path("/home/user/projects/my-app")

        prompt = generator.generate(
            project_path, "my-app", basic_progress, PromptMode.CONTEXT
        )

        assert str(project_path) in prompt.command

    def test_empty_progress(self, generator):
        """Test handling of empty progress object."""
        project_path = Path("/test/project")
        progress = ProjectProgress()

        prompt = generator.generate(
            project_path, "test-project", progress, PromptMode.CONTEXT
        )

        assert prompt.mode == PromptMode.CONTEXT
        assert "test-project" in prompt.prompt_text


class TestBatchScript:
    """Tests for batch script generation."""

    @pytest.fixture
    def generator(self):
        return ContinuePromptGenerator()

    def test_generate_batch_script_single(self, generator):
        """Test batch script with single project."""
        projects = [
            (Path("/test/project1"), "project1", ProjectProgress(current_phase="Phase 1"))
        ]

        script = generator.generate_batch_script(projects)

        assert "#!/bin/bash" in script
        assert "project1" in script
        assert "cd /test/project1" in script

    def test_generate_batch_script_multiple(self, generator):
        """Test batch script with multiple projects."""
        projects = [
            (Path("/test/project1"), "project1", ProjectProgress()),
            (Path("/test/project2"), "project2", ProjectProgress()),
            (Path("/test/project3"), "project3", ProjectProgress()),
        ]

        script = generator.generate_batch_script(projects)

        assert "project1" in script
        assert "project2" in script
        assert "project3" in script

    def test_generate_batch_script_parallel(self, generator):
        """Test batch script with parallel execution."""
        projects = [
            (Path("/test/p1"), "p1", ProjectProgress()),
            (Path("/test/p2"), "p2", ProjectProgress()),
        ]

        script = generator.generate_batch_script(projects, parallel=2)

        # Should run in background and have wait
        assert "& " in script or ") &" in script
        assert "wait" in script

    def test_generate_batch_script_parallel_chunks(self, generator):
        """Test parallel execution with chunk waits."""
        projects = [
            (Path(f"/test/p{i}"), f"p{i}", ProjectProgress())
            for i in range(4)
        ]

        script = generator.generate_batch_script(projects, parallel=2)

        # Should have multiple waits (after every 2 projects)
        wait_count = script.count("wait")
        assert wait_count >= 2


class TestContinuePromptDataclass:
    """Tests for ContinuePrompt dataclass."""

    def test_default_values(self):
        """Test default values for ContinuePrompt."""
        prompt = ContinuePrompt(
            mode=PromptMode.SIMPLE,
            command="claude --resume"
        )

        assert prompt.prompt_text is None
        assert prompt.has_decision is False
        assert prompt.decision is None

    def test_with_all_values(self):
        """Test ContinuePrompt with all values set."""
        decision = DecisionPoint(question="Test?")
        prompt = ContinuePrompt(
            mode=PromptMode.DECISION,
            command="cd /test && claude --resume",
            prompt_text="Decision needed",
            has_decision=True,
            decision=decision,
        )

        assert prompt.mode == PromptMode.DECISION
        assert prompt.has_decision is True
        assert prompt.decision is decision


class TestPromptMode:
    """Tests for PromptMode enum."""

    def test_mode_values(self):
        """Test PromptMode enum values."""
        assert PromptMode.SIMPLE.value == "simple"
        assert PromptMode.CONTEXT.value == "context"
        assert PromptMode.DECISION.value == "decision"

    def test_mode_from_string(self):
        """Test creating PromptMode from string."""
        assert PromptMode("simple") == PromptMode.SIMPLE
        assert PromptMode("context") == PromptMode.CONTEXT
        assert PromptMode("decision") == PromptMode.DECISION


class TestConvenienceFunction:
    """Tests for generate_continue_prompt function."""

    def test_convenience_function(self):
        """Test the convenience function."""
        prompt = generate_continue_prompt(
            Path("/test/project"),
            "test-project",
            ProjectProgress(completion_pct=50.0),
            PromptMode.CONTEXT
        )

        assert prompt.mode == PromptMode.CONTEXT
        assert "50%" in prompt.prompt_text

    def test_convenience_function_default_mode(self):
        """Test convenience function with default mode."""
        prompt = generate_continue_prompt(
            Path("/test/project"),
            "test-project",
            ProjectProgress()
        )

        # Default mode is CONTEXT
        assert prompt.mode == PromptMode.CONTEXT


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def generator(self):
        return ContinuePromptGenerator()

    def test_very_long_phase_name(self, generator):
        """Test handling of very long phase names."""
        progress = ProjectProgress(
            current_phase="A" * 500
        )

        prompt = generator.generate(
            Path("/test"), "test", progress, PromptMode.CONTEXT
        )

        assert prompt.prompt_text is not None

    def test_special_characters_in_name(self, generator):
        """Test handling of special characters in project name."""
        prompt = generator.generate(
            Path("/test/my-project's-name (v2)"),
            "my-project's-name (v2)",
            ProjectProgress(),
            PromptMode.CONTEXT
        )

        assert "my-project's-name" in prompt.prompt_text

    def test_many_items(self, generator):
        """Test handling of many progress items."""
        items = [
            ProgressItem(
                content=f"Task {i}",
                status=ItemStatus.IN_PROGRESS if i < 5 else ItemStatus.PENDING,
            )
            for i in range(100)
        ]
        progress = ProjectProgress(items=items)

        prompt = generator.generate(
            Path("/test"), "test", progress, PromptMode.CONTEXT
        )

        # Should limit items shown
        assert prompt.prompt_text is not None
        # Should not have all 100 items
        assert prompt.prompt_text.count("Task") < 10

    def test_decision_without_recommendation(self, generator):
        """Test decision without recommendation."""
        progress = ProjectProgress(
            has_pending_decision=True,
            decisions=[
                DecisionPoint(
                    question="What approach?",
                    options=["A", "B"],
                    recommendation=None,
                )
            ]
        )

        prompt = generator.generate(
            Path("/test"), "test", progress, PromptMode.DECISION
        )

        assert prompt.has_decision is True
        # Should still work without recommendation
        assert "What approach?" in prompt.prompt_text

    def test_empty_next_steps(self, generator):
        """Test with empty next_steps list."""
        progress = ProjectProgress(
            next_steps=[]
        )

        prompt = generator.generate(
            Path("/test"), "test", progress, PromptMode.CONTEXT
        )

        assert "Next steps:" not in prompt.prompt_text
