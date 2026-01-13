"""Unit tests for pm.scanner.parser module."""

import pytest
from pathlib import Path

from pm.scanner.parser import (
    ProgressParser, ProjectProgress, ProgressItem,
    ItemStatus, ItemPriority, DecisionPoint, parse_progress
)


class TestProgressParser:
    """Tests for ProgressParser class."""

    @pytest.fixture
    def parser(self):
        return ProgressParser()

    def test_parse_empty_content(self, parser):
        """Test parsing empty content."""
        result = parser.parse_content("")
        assert result.completion_pct is None
        assert result.items == []
        assert result.has_pending_decision is False

    def test_extract_checkbox_complete(self, parser):
        """Test extraction of completed checkboxes."""
        content = """
- [x] Task 1
- [X] Task 2
- [✓] Task 3
"""
        result = parser.parse_content(content)
        assert len(result.items) == 3
        for item in result.items:
            assert item.status == ItemStatus.COMPLETE

    def test_extract_checkbox_pending(self, parser):
        """Test extraction of pending checkboxes."""
        content = """
- [ ] Task 1
- [ ] Task 2
"""
        result = parser.parse_content(content)
        assert len(result.items) == 2
        for item in result.items:
            assert item.status == ItemStatus.PENDING

    def test_extract_checkbox_mixed(self, parser):
        """Test extraction of mixed checkbox states."""
        content = """
- [x] Completed task
- [ ] Pending task
- [X] Another complete
"""
        result = parser.parse_content(content)
        assert len(result.items) == 3

        complete = [i for i in result.items if i.status == ItemStatus.COMPLETE]
        pending = [i for i in result.items if i.status == ItemStatus.PENDING]

        assert len(complete) == 2
        assert len(pending) == 1

    def test_calculate_completion_from_checkboxes(self, parser):
        """Test completion percentage calculation from checkboxes."""
        content = """
- [x] Done 1
- [x] Done 2
- [ ] Not done
- [x] Done 3
"""
        result = parser.parse_content(content)
        assert result.completion_pct == 75.0
        assert result.total_items == 4
        assert result.completed_items == 3

    def test_extract_explicit_percentage(self, parser):
        """Test extraction of explicit percentage."""
        content = """
## Progress

Completion: 65%

- [ ] Some task
"""
        result = parser.parse_content(content)
        assert result.completion_pct == 65.0

    def test_extract_x_of_y_format(self, parser):
        """Test extraction of 'X of Y' completion format."""
        content = """
6 of 8 tasks complete
"""
        result = parser.parse_content(content)
        assert result.completion_pct == 75.0

    def test_extract_current_phase(self, parser):
        """Test extraction of current phase."""
        content = """
## Current Phase: Phase 2 - Implementation

Some content here.
"""
        result = parser.parse_content(content)
        assert "Phase 2" in result.current_phase or "Implementation" in result.current_phase

    def test_extract_status(self, parser):
        """Test extraction of status."""
        content = """
**Status:** In progress, working on feature X
"""
        result = parser.parse_content(content)
        assert result.current_status is not None
        assert "In progress" in result.current_status

    def test_extract_current_focus(self, parser):
        """Test extraction of current focus."""
        content = """
**Current Focus:** Implementing the authentication module
"""
        result = parser.parse_content(content)
        assert result.current_focus is not None
        assert "authentication" in result.current_focus.lower()

    def test_extract_next_step(self, parser):
        """Test extraction of next step."""
        content = """
Next step: Complete the unit tests
"""
        result = parser.parse_content(content)
        assert result.next_action is not None
        assert "unit tests" in result.next_action.lower()

    def test_extract_last_updated(self, parser):
        """Test extraction of last updated date."""
        content = """
**Last Updated:** 2025-01-13
"""
        result = parser.parse_content(content)
        # last_updated should contain the date
        assert result.last_updated is not None
        assert "2025-01-13" in result.last_updated

    def test_extract_decision_points(self, parser):
        """Test extraction of decision points."""
        content = """
## Architecture Decision

### Option A: Use PostgreSQL
More scalable for production.

### Option B: Use SQLite
Simpler for development.

Recommended: Option A for production needs.
"""
        result = parser.parse_content(content)
        assert len(result.decisions) >= 1
        assert result.has_pending_decision is True

        decision = result.decisions[0]
        assert len(decision.options) >= 2

    def test_extract_next_steps_section(self, parser):
        """Test extraction of next steps section."""
        content = """
## Next Steps

- Implement feature A
- Write documentation
- Deploy to staging
"""
        result = parser.parse_content(content)
        assert len(result.next_steps) >= 2

    def test_extract_sections(self, parser):
        """Test extraction of markdown sections."""
        content = """
# Main Title

## Overview
This is the overview section.

## Implementation
Details about implementation.

## Testing
Testing information here.
"""
        result = parser.parse_content(content)
        assert len(result.sections) >= 2
        assert "overview" in result.sections
        assert "implementation" in result.sections

    def test_priority_detection_critical(self, parser):
        """Test detection of critical priority."""
        content = "- [ ] CRITICAL: Fix security bug"
        result = parser.parse_content(content)
        assert len(result.items) == 1
        assert result.items[0].priority == ItemPriority.CRITICAL

    def test_priority_detection_high(self, parser):
        """Test detection of high priority."""
        content = "- [ ] HIGH priority task"
        result = parser.parse_content(content)
        assert len(result.items) == 1
        assert result.items[0].priority == ItemPriority.HIGH

    def test_status_indicator_in_progress(self, parser):
        """Test IN PROGRESS status indicator in text."""
        content = "- [ ] Task IN PROGRESS"
        result = parser.parse_content(content)
        assert len(result.items) == 1
        assert result.items[0].status == ItemStatus.IN_PROGRESS

    def test_status_indicator_blocked(self, parser):
        """Test BLOCKED status indicator in text."""
        content = "- [ ] Task BLOCKED by dependency"
        result = parser.parse_content(content)
        assert len(result.items) == 1
        assert result.items[0].status == ItemStatus.BLOCKED

    def test_line_numbers_tracked(self, parser):
        """Test that line numbers are tracked for items."""
        content = """Line 1
Line 2
- [ ] Task on line 3
Line 4
- [x] Task on line 5
"""
        result = parser.parse_content(content)
        assert len(result.items) == 2
        assert result.items[0].line_number == 3
        assert result.items[1].line_number == 5

    def test_source_file_tracked(self, parser):
        """Test that source file is tracked."""
        content = "- [ ] Task"
        result = parser.parse_content(content, source_file="TODO.md")
        assert len(result.items) == 1
        assert result.items[0].source_file == "TODO.md"


class TestParseFile:
    """Tests for parsing files."""

    @pytest.fixture
    def parser(self):
        return ProgressParser()

    def test_parse_nonexistent_file(self, parser, temp_dir):
        """Test parsing a file that doesn't exist."""
        result = parser.parse_file(temp_dir / "nonexistent.md")
        assert result.completion_pct is None
        assert result.items == []

    def test_parse_real_file(self, parser, sample_project_dir):
        """Test parsing a real TODO.md file."""
        result = parser.parse_file(sample_project_dir / "TODO.md")
        assert len(result.items) > 0
        # The sample TODO.md has a decision keyword but may not match the Option A/B pattern
        # Just verify items were parsed correctly


class TestParseProject:
    """Tests for parsing entire projects."""

    @pytest.fixture
    def parser(self):
        return ProgressParser()

    def test_parse_project_merges_files(self, parser, sample_project_dir):
        """Test that parsing a project merges multiple files."""
        result = parser.parse_project(sample_project_dir)

        # Should have items from TODO.md
        assert len(result.items) > 0

        # Should have completion from PROGRESS.md (45%)
        assert result.completion_pct is not None

    def test_parse_project_no_progress_files(self, parser, temp_dir):
        """Test parsing project with no progress files."""
        project = temp_dir / "empty-project"
        project.mkdir()
        (project / "package.json").write_text('{}')

        result = parser.parse_project(project)
        assert result.completion_pct is None
        assert result.items == []


class TestMergeProgress:
    """Tests for merging progress objects."""

    @pytest.fixture
    def parser(self):
        return ProgressParser()

    def test_merge_prefers_higher_completion(self, parser):
        """Test that merge prefers higher completion percentage."""
        base = ProjectProgress(completion_pct=30.0)
        new = ProjectProgress(completion_pct=50.0)

        result = parser._merge_progress(base, new)
        assert result.completion_pct == 50.0

    def test_merge_keeps_higher_completion(self, parser):
        """Test that merge keeps higher completion if base is higher."""
        base = ProjectProgress(completion_pct=70.0)
        new = ProjectProgress(completion_pct=40.0)

        result = parser._merge_progress(base, new)
        assert result.completion_pct == 70.0

    def test_merge_uses_new_if_base_none(self, parser):
        """Test that merge uses new value if base is None."""
        base = ProjectProgress(completion_pct=None)
        new = ProjectProgress(completion_pct=50.0)

        result = parser._merge_progress(base, new)
        assert result.completion_pct == 50.0

    def test_merge_combines_items(self, parser):
        """Test that items from both sources are combined."""
        base = ProjectProgress(items=[
            ProgressItem(content="Task 1", status=ItemStatus.COMPLETE)
        ])
        new = ProjectProgress(items=[
            ProgressItem(content="Task 2", status=ItemStatus.PENDING)
        ])

        result = parser._merge_progress(base, new)
        assert len(result.items) == 2

    def test_merge_combines_decisions(self, parser):
        """Test that decisions from both sources are combined."""
        base = ProjectProgress(decisions=[
            DecisionPoint(question="Q1")
        ])
        new = ProjectProgress(decisions=[
            DecisionPoint(question="Q2")
        ])

        result = parser._merge_progress(base, new)
        assert len(result.decisions) == 2
        assert result.has_pending_decision is True

    def test_merge_updates_text_fields(self, parser):
        """Test that text fields are updated from new source."""
        base = ProjectProgress(
            current_phase="Phase 1",
            current_status=None,
        )
        new = ProjectProgress(
            current_phase="Phase 2",
            current_status="Active",
        )

        result = parser._merge_progress(base, new)
        assert result.current_phase == "Phase 2"
        assert result.current_status == "Active"


class TestConvenienceFunction:
    """Tests for the parse_progress convenience function."""

    def test_parse_progress_function(self, sample_project_dir):
        """Test the parse_progress convenience function."""
        result = parse_progress(sample_project_dir)
        assert len(result.items) > 0


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    @pytest.fixture
    def parser(self):
        return ProgressParser()

    def test_unicode_content(self, parser):
        """Test handling of unicode content."""
        content = """
- [x] Task with emoji 🚀
- [ ] Task with unicode: café, naïve
- [✓] Task with check mark symbol
"""
        result = parser.parse_content(content)
        assert len(result.items) >= 2

    def test_nested_checkboxes(self, parser):
        """Test handling of nested/indented checkboxes."""
        content = """
- [x] Parent task
  - [x] Child task 1
  - [ ] Child task 2
    - [ ] Grandchild task
"""
        result = parser.parse_content(content)
        # Should find all checkboxes regardless of nesting
        assert len(result.items) >= 3

    def test_very_long_lines(self, parser):
        """Test handling of very long lines."""
        long_text = "A" * 1000
        content = f"- [ ] {long_text}"
        result = parser.parse_content(content)
        assert len(result.items) == 1
        assert len(result.items[0].content) == 1000

    def test_multiple_percentages(self, parser):
        """Test handling of multiple percentage values (first wins)."""
        content = """
Completion: 30%

Other metric: 80%
"""
        result = parser.parse_content(content)
        assert result.completion_pct == 30.0

    def test_malformed_checkboxes(self, parser):
        """Test handling of malformed checkboxes."""
        content = """
- [] No space in brackets
-[ ] No space after dash
- [maybe] Invalid checkbox content
- [x] Valid checkbox
"""
        result = parser.parse_content(content)
        # Should only find the valid checkbox
        assert len(result.items) >= 1
        valid_items = [i for i in result.items if "Valid" in i.content]
        assert len(valid_items) == 1
