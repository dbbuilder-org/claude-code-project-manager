"""Unit tests for pm.scanner.detector module."""

import pytest
from pathlib import Path

from pm.scanner.detector import ProjectDetector, ProjectInfo, scan_projects


class TestProjectDetector:
    """Tests for ProjectDetector class."""

    def test_init(self, temp_dir: Path):
        """Test detector initialization."""
        detector = ProjectDetector(temp_dir)
        assert detector.base_path == temp_dir.resolve()

    def test_detect_node_project(self, sample_project_dir: Path):
        """Test detection of Node.js project by package.json."""
        detector = ProjectDetector(sample_project_dir.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].name == "sample-project"
        assert projects[0].project_type == "node"

    def test_detect_python_project(self, sample_python_project: Path):
        """Test detection of Python project by pyproject.toml."""
        detector = ProjectDetector(sample_python_project.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].name == "python-project"
        assert projects[0].project_type == "python"

    def test_detect_rust_project(self, sample_rust_project: Path):
        """Test detection of Rust project by Cargo.toml."""
        detector = ProjectDetector(sample_rust_project.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].name == "rust-project"
        assert projects[0].project_type == "rust"

    def test_detect_container_folder(self, clients_container: Path):
        """Test detection of projects in container folders like clients/."""
        detector = ProjectDetector(clients_container.parent)
        projects = detector.scan()

        # Should find client-alpha and client-beta, not client-gamma (no markers)
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert "client-alpha" in names
        assert "client-beta" in names
        assert "client-gamma" not in names

        # All should be categorized as client
        for p in projects:
            assert p.category == "client"

    def test_has_claude_md_detection(self, sample_project_dir: Path):
        """Test CLAUDE.md file detection."""
        detector = ProjectDetector(sample_project_dir.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].has_claude_md is True

    def test_has_todo_detection(self, sample_project_dir: Path):
        """Test TODO.md file detection."""
        detector = ProjectDetector(sample_project_dir.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].has_todo is True

    def test_has_progress_detection(self, sample_project_dir: Path):
        """Test PROGRESS.md file detection."""
        detector = ProjectDetector(sample_project_dir.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].has_progress is True

    def test_progress_files_list(self, sample_project_dir: Path):
        """Test that all progress files are listed."""
        detector = ProjectDetector(sample_project_dir.parent)
        projects = detector.scan()

        assert len(projects) == 1
        assert "TODO.md" in projects[0].progress_files
        assert "PROGRESS.md" in projects[0].progress_files

    def test_skip_hidden_directories(self, temp_dir: Path):
        """Test that hidden directories are skipped."""
        # Create a hidden project
        hidden = temp_dir / ".hidden-project"
        hidden.mkdir()
        (hidden / "package.json").write_text('{"name": "hidden"}')

        # Create a visible project
        visible = temp_dir / "visible-project"
        visible.mkdir()
        (visible / "package.json").write_text('{"name": "visible"}')

        detector = ProjectDetector(temp_dir)
        projects = detector.scan()

        assert len(projects) == 1
        assert projects[0].name == "visible-project"

    def test_skip_node_modules(self, temp_dir: Path):
        """Test that node_modules is skipped."""
        project = temp_dir / "project"
        project.mkdir()
        (project / "package.json").write_text('{"name": "project"}')

        # Create a nested package in node_modules
        node_modules = project / "node_modules" / "some-package"
        node_modules.mkdir(parents=True)
        (node_modules / "package.json").write_text('{"name": "some-package"}')

        detector = ProjectDetector(temp_dir)
        projects = detector.scan()

        # Should only find the main project, not the one in node_modules
        assert len(projects) == 1
        assert projects[0].name == "project"

    def test_empty_directory(self, temp_dir: Path):
        """Test scanning empty directory returns no projects."""
        detector = ProjectDetector(temp_dir)
        projects = detector.scan()
        assert len(projects) == 0

    def test_no_marker_files(self, temp_dir: Path):
        """Test directory without marker files is not detected."""
        no_markers = temp_dir / "no-markers"
        no_markers.mkdir()
        (no_markers / "random.txt").write_text("Just a random file")

        detector = ProjectDetector(temp_dir)
        projects = detector.scan()
        assert len(projects) == 0

    def test_category_detection_tool(self, temp_dir: Path):
        """Test tool category detection by name heuristics."""
        tool_names = ["my-cli-tool", "helper-mcp", "data-scanner"]

        for name in tool_names:
            tool_dir = temp_dir / name
            tool_dir.mkdir()
            (tool_dir / "package.json").write_text(f'{{"name": "{name}"}}')

        detector = ProjectDetector(temp_dir)
        projects = detector.scan()

        for p in projects:
            assert p.category == "tool", f"{p.name} should be categorized as tool"


class TestScanProjects:
    """Tests for the convenience scan_projects function."""

    def test_scan_projects_function(self, sample_project_dir: Path):
        """Test the scan_projects convenience function."""
        projects = scan_projects(sample_project_dir.parent)

        assert len(projects) == 1
        assert projects[0].name == "sample-project"

    def test_scan_projects_sorted_by_name(self, temp_dir: Path):
        """Test that projects are sorted alphabetically by name."""
        for name in ["zebra", "alpha", "mango"]:
            proj_dir = temp_dir / name
            proj_dir.mkdir()
            (proj_dir / "package.json").write_text(f'{{"name": "{name}"}}')

        projects = scan_projects(temp_dir)
        names = [p.name for p in projects]
        assert names == ["alpha", "mango", "zebra"]


class TestProjectInfo:
    """Tests for ProjectInfo dataclass."""

    def test_project_info_defaults(self):
        """Test ProjectInfo default values."""
        info = ProjectInfo(
            path=Path("/test"),
            name="test",
            project_type="node",
            category="internal",
        )

        assert info.has_claude_md is False
        assert info.has_readme is False
        assert info.has_todo is False
        assert info.has_progress is False
        assert info.git_initialized is False
        assert info.git_branch is None
        assert info.git_dirty is False
        assert info.progress_files == []

    def test_project_info_with_values(self, project_info: ProjectInfo):
        """Test ProjectInfo with populated values."""
        assert project_info.name == "sample"
        assert project_info.project_type == "node"
        assert project_info.has_claude_md is True
        assert project_info.git_branch == "main"
        assert len(project_info.progress_files) == 2
