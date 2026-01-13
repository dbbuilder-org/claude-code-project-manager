"""Project detection - identifies valid development projects."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import subprocess


@dataclass
class ProjectInfo:
    """Information about a detected project."""
    path: Path
    name: str
    project_type: str  # 'node', 'python', 'rust', 'go', 'dotnet', 'generic'
    category: str  # 'client', 'internal', 'tool'

    # Files found
    has_claude_md: bool = False
    has_readme: bool = False
    has_todo: bool = False
    has_progress: bool = False

    # Git info
    git_initialized: bool = False
    git_branch: Optional[str] = None
    git_dirty: bool = False
    last_commit_date: Optional[datetime] = None
    last_commit_msg: Optional[str] = None

    # Computed
    progress_files: list[str] = field(default_factory=list)


class ProjectDetector:
    """Detects valid projects in a directory tree."""

    # Files that indicate a project
    PROJECT_MARKERS = {
        'node': ['package.json'],
        'python': ['pyproject.toml', 'setup.py', 'requirements.txt'],
        'rust': ['Cargo.toml'],
        'go': ['go.mod'],
        'dotnet': ['*.csproj', '*.sln'],
        'generic': ['CLAUDE.md', 'README.md'],
    }

    # Progress tracking files to look for
    PROGRESS_FILES = [
        'TODO.md', 'PROGRESS.md', 'ROADMAP.md', 'STATUS.md',
        'DEVELOPMENT-STATUS.md', 'FUTURE.md', 'REQUIREMENTS.md'
    ]

    # Directories to skip
    SKIP_DIRS = {
        'node_modules', 'venv', '.venv', 'env', '.env',
        '__pycache__', '.git', '.svn', 'dist', 'build',
        'target', '.idea', '.vscode', '.archive'
    }

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()

    def scan(self, max_depth: int = 2) -> list[ProjectInfo]:
        """Scan for projects up to max_depth levels deep."""
        projects = []

        for item in self.base_path.iterdir():
            if item.is_dir() and item.name not in self.SKIP_DIRS and not item.name.startswith('.'):
                project = self._detect_project(item)
                if project:
                    projects.append(project)

        return sorted(projects, key=lambda p: p.name.lower())

    def _detect_project(self, path: Path) -> Optional[ProjectInfo]:
        """Detect if a directory is a valid project."""
        if not path.is_dir():
            return None

        # Determine project type
        project_type = self._detect_type(path)
        if not project_type:
            return None

        # Determine category (client vs internal)
        category = self._detect_category(path)

        # Create project info
        project = ProjectInfo(
            path=path,
            name=path.name,
            project_type=project_type,
            category=category,
        )

        # Check for common files
        project.has_claude_md = (path / 'CLAUDE.md').exists()
        project.has_readme = (path / 'README.md').exists()
        project.has_todo = (path / 'TODO.md').exists()
        project.has_progress = (path / 'PROGRESS.md').exists()

        # Find all progress files
        for pf in self.PROGRESS_FILES:
            if (path / pf).exists():
                project.progress_files.append(pf)

        # Get git info
        self._get_git_info(project)

        return project

    def _detect_type(self, path: Path) -> Optional[str]:
        """Detect the project type based on marker files."""
        for ptype, markers in self.PROJECT_MARKERS.items():
            for marker in markers:
                if '*' in marker:
                    # Glob pattern
                    if list(path.glob(marker)):
                        return ptype
                else:
                    if (path / marker).exists():
                        return ptype
        return None

    def _detect_category(self, path: Path) -> str:
        """Detect if project is client, internal, or tool."""
        # Check if under clients directory
        try:
            path.relative_to(self.base_path / 'clients')
            return 'client'
        except ValueError:
            pass

        # Heuristics for tools
        tool_indicators = ['mcp', 'cli', 'tool', 'helper', 'util', 'scanner', 'gen']
        name_lower = path.name.lower()
        for indicator in tool_indicators:
            if indicator in name_lower:
                return 'tool'

        return 'internal'

    def _get_git_info(self, project: ProjectInfo) -> None:
        """Get git repository information."""
        git_dir = project.path / '.git'
        if not git_dir.exists():
            return

        project.git_initialized = True

        try:
            # Get current branch
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=project.path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                project.git_branch = result.stdout.strip()

            # Check if dirty
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=project.path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                project.git_dirty = bool(result.stdout.strip())

            # Get last commit
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%ci|%s'],
                cwd=project.path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('|', 1)
                if len(parts) == 2:
                    from dateutil.parser import parse
                    project.last_commit_date = parse(parts[0])
                    project.last_commit_msg = parts[1][:100]  # Truncate

        except (subprocess.TimeoutExpired, Exception):
            pass  # Git info is optional


def scan_projects(base_path: str | Path, max_depth: int = 2) -> list[ProjectInfo]:
    """Convenience function to scan for projects."""
    detector = ProjectDetector(base_path)
    return detector.scan(max_depth=max_depth)
