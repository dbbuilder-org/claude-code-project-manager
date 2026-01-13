"""Pytest fixtures for project-manager tests."""

import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pm.database.models import Base, Project, ProgressItem, ScanHistory
from pm.scanner.detector import ProjectInfo
import pm.database.models as models_module


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_project_dir(temp_dir: Path) -> Path:
    """Create a sample project directory with common files."""
    project_path = temp_dir / "sample-project"
    project_path.mkdir()

    # Create package.json (Node project marker)
    (project_path / "package.json").write_text(json.dumps({
        "name": "sample-project",
        "version": "1.0.0"
    }))

    # Create CLAUDE.md
    (project_path / "CLAUDE.md").write_text("""# Sample Project

This is a sample project for testing.

## Current Focus
- Testing the project manager
""")

    # Create README.md
    (project_path / "README.md").write_text("# Sample Project\n\nA test project.")

    # Create TODO.md with checkboxes
    (project_path / "TODO.md").write_text("""# TODO

## Phase 1: Setup
- [x] Create project structure
- [x] Add package.json
- [ ] Add tests

## Phase 2: Implementation
- [ ] Implement feature A
- [ ] Implement feature B
- [x] Add documentation

## Pending Decision
- [ ] **DECISION:** Choose database (PostgreSQL vs SQLite)
""")

    # Create PROGRESS.md
    (project_path / "PROGRESS.md").write_text("""# Progress

## Current Status
Phase 1 complete, starting Phase 2.

## Completion: 45%

## Next Steps
1. Implement feature A
2. Write tests
""")

    return project_path


@pytest.fixture
def sample_python_project(temp_dir: Path) -> Path:
    """Create a Python project with pyproject.toml."""
    project_path = temp_dir / "python-project"
    project_path.mkdir()

    (project_path / "pyproject.toml").write_text("""[project]
name = "python-project"
version = "0.1.0"
""")

    (project_path / "TODO.md").write_text("""# TODO
- [x] Setup project
- [x] Add pyproject.toml
- [ ] Implement main module
""")

    return project_path


@pytest.fixture
def sample_rust_project(temp_dir: Path) -> Path:
    """Create a Rust project with Cargo.toml."""
    project_path = temp_dir / "rust-project"
    project_path.mkdir()

    (project_path / "Cargo.toml").write_text("""[package]
name = "rust-project"
version = "0.1.0"
""")

    return project_path


@pytest.fixture
def clients_container(temp_dir: Path) -> Path:
    """Create a clients container folder with sub-projects."""
    clients_path = temp_dir / "clients"
    clients_path.mkdir()

    # Client 1
    client1 = clients_path / "client-alpha"
    client1.mkdir()
    (client1 / "package.json").write_text('{"name": "client-alpha"}')
    (client1 / "TODO.md").write_text("- [x] Done\n- [ ] Pending")

    # Client 2
    client2 = clients_path / "client-beta"
    client2.mkdir()
    (client2 / "pyproject.toml").write_text('[project]\nname = "client-beta"')

    # Client 3 (no markers - should not be detected)
    client3 = clients_path / "client-gamma"
    client3.mkdir()
    (client3 / "notes.txt").write_text("Just notes, not a project")

    return clients_path


@pytest.fixture
def db_session(temp_dir: Path):
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_project_record(db_session) -> Project:
    """Create a sample Project record in the database."""
    project = Project(
        id="/test/path/sample-project",
        path="/test/path/sample-project",
        name="sample-project",
        project_type="node",
        category="internal",
        last_scanned=datetime.utcnow(),
        last_activity=datetime.utcnow() - timedelta(days=5),
        completion_pct=45.0,
        current_phase="Phase 2: Implementation",
        current_status="In progress",
        next_action="Implement feature A",
        has_pending_decision=True,
        git_branch="main",
        git_dirty=False,
        has_claude_md=True,
        has_todo=True,
        has_progress=True,
    )
    db_session.add(project)
    db_session.commit()
    return project


@pytest.fixture
def multiple_projects(db_session) -> list[Project]:
    """Create multiple project records for testing filters and sorting."""
    projects = [
        Project(
            id="/test/client1",
            path="/test/client1",
            name="client-alpha",
            project_type="node",
            category="client",
            completion_pct=80.0,
            last_activity=datetime.utcnow() - timedelta(days=2),
            has_claude_md=True,
            has_todo=True,
        ),
        Project(
            id="/test/client2",
            path="/test/client2",
            name="client-beta",
            project_type="python",
            category="client",
            completion_pct=30.0,
            last_activity=datetime.utcnow() - timedelta(days=45),
            has_pending_decision=True,
            git_dirty=True,
        ),
        Project(
            id="/test/internal1",
            path="/test/internal1",
            name="internal-tool",
            project_type="python",
            category="internal",
            completion_pct=95.0,
            last_activity=datetime.utcnow(),
            has_claude_md=True,
        ),
        Project(
            id="/test/tool1",
            path="/test/tool1",
            name="cli-helper",
            project_type="rust",
            category="tool",
            completion_pct=60.0,
            last_activity=datetime.utcnow() - timedelta(days=10),
        ),
    ]
    for p in projects:
        db_session.add(p)
    db_session.commit()
    return projects


@pytest.fixture
def project_info() -> ProjectInfo:
    """Create a sample ProjectInfo object."""
    return ProjectInfo(
        path=Path("/test/sample"),
        name="sample",
        project_type="node",
        category="internal",
        has_claude_md=True,
        has_readme=True,
        has_todo=True,
        has_progress=True,
        git_initialized=True,
        git_branch="main",
        git_dirty=False,
        progress_files=["TODO.md", "PROGRESS.md"],
    )


@pytest.fixture(autouse=True)
def isolated_database(temp_dir):
    """Automatically isolate database for all tests.

    This fixture patches the database module to use a temp directory,
    ensuring tests don't affect the production database.
    """
    db_path = temp_dir / "test_projects.db"

    # Reset module-level globals
    models_module._engine = None
    models_module._SessionLocal = None

    # Initialize with temp path
    from pm.database.models import init_db
    init_db(db_path)

    yield db_path

    # Clean up
    models_module._engine = None
    models_module._SessionLocal = None
