"""Unit tests for pm.database.models module."""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pm.database.models import (
    Base, Project, ProgressItem, ScanHistory,
    init_db, get_session
)


class TestProject:
    """Tests for Project model."""

    def test_project_creation(self, db_session):
        """Test basic project creation."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="test-project",
            project_type="node",
            category="internal",
        )
        db_session.add(project)
        db_session.commit()

        retrieved = db_session.query(Project).filter_by(name="test-project").first()
        assert retrieved is not None
        assert retrieved.path == "/test/path"
        assert retrieved.project_type == "node"

    def test_project_defaults(self, db_session):
        """Test project default values."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="test-project",
        )
        db_session.add(project)
        db_session.commit()

        assert project.has_pending_decision is False
        assert project.git_dirty is False
        assert project.has_claude_md is False
        assert project.has_todo is False
        assert project.has_progress is False

    def test_unique_path_constraint(self, db_session):
        """Test that path must be unique."""
        project1 = Project(id="/test/path1", path="/test/path", name="project1")
        project2 = Project(id="/test/path2", path="/test/path", name="project2")

        db_session.add(project1)
        db_session.commit()

        db_session.add(project2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


class TestHealthScore:
    """Tests for Project.health_score property."""

    def test_health_score_minimum(self, db_session):
        """Test minimum health score for bare project."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="bare-project",
            project_type="generic",
            has_pending_decision=True,
            git_dirty=True,
        )
        db_session.add(project)
        db_session.commit()

        # Should have low score:
        # - No completion
        # - No CLAUDE.md (0)
        # - No progress files (0)
        # - No activity (0)
        # - Has pending decision (0)
        # - Git dirty (0)
        # - Generic type (0)
        assert project.health_score <= 10

    def test_health_score_maximum(self, db_session):
        """Test maximum health score for healthy project."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="healthy-project",
            project_type="node",
            completion_pct=100.0,
            has_claude_md=True,
            has_todo=True,
            last_activity=datetime.utcnow(),
            has_pending_decision=False,
            git_dirty=False,
        )
        db_session.add(project)
        db_session.commit()

        # Should have high score:
        # - 100% completion = 30 pts
        # - Has CLAUDE.md = 10 pts
        # - Has progress files = 10 pts
        # - Recent activity = 20 pts
        # - No pending decisions = 10 pts
        # - Clean git = 10 pts
        # - Known type = 10 pts
        # Total = 100
        assert project.health_score >= 90

    def test_health_score_completion_contribution(self, db_session):
        """Test completion percentage contribution to health score."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="project",
            project_type="node",
            completion_pct=50.0,
        )
        db_session.add(project)
        db_session.commit()

        # 50% completion should contribute 15 points (50 * 0.3)
        base_score = project.health_score

        project.completion_pct = 100.0
        # 100% should contribute 30 points
        assert project.health_score > base_score

    def test_health_score_activity_decay(self, db_session):
        """Test that health score decays with inactivity."""
        base_project = Project(
            id="/test/active",
            path="/test/active",
            name="active-project",
            last_activity=datetime.utcnow(),
        )

        old_project = Project(
            id="/test/old",
            path="/test/old",
            name="old-project",
            last_activity=datetime.utcnow() - timedelta(days=90),
        )

        db_session.add_all([base_project, old_project])
        db_session.commit()

        # Active project should have higher score
        assert base_project.health_score > old_project.health_score

    def test_health_score_claude_md_bonus(self, db_session):
        """Test CLAUDE.md file contributes to health score."""
        without = Project(id="/test/1", path="/test/1", name="without", has_claude_md=False)
        with_claude = Project(id="/test/2", path="/test/2", name="with", has_claude_md=True)

        db_session.add_all([without, with_claude])
        db_session.commit()

        assert with_claude.health_score == without.health_score + 10

    def test_health_score_git_penalty(self, db_session):
        """Test dirty git state reduces health score."""
        clean = Project(id="/test/1", path="/test/1", name="clean", git_dirty=False)
        dirty = Project(id="/test/2", path="/test/2", name="dirty", git_dirty=True)

        db_session.add_all([clean, dirty])
        db_session.commit()

        assert clean.health_score == dirty.health_score + 10

    def test_health_score_decision_penalty(self, db_session):
        """Test pending decision reduces health score."""
        no_decision = Project(
            id="/test/1", path="/test/1", name="no-decision",
            has_pending_decision=False
        )
        has_decision = Project(
            id="/test/2", path="/test/2", name="has-decision",
            has_pending_decision=True
        )

        db_session.add_all([no_decision, has_decision])
        db_session.commit()

        assert no_decision.health_score == has_decision.health_score + 10

    def test_health_score_capped_at_100(self, db_session):
        """Test that health score never exceeds 100."""
        project = Project(
            id="/test/path",
            path="/test/path",
            name="super-healthy",
            project_type="node",
            completion_pct=200.0,  # Invalid but let's test cap
            has_claude_md=True,
            has_todo=True,
            has_progress=True,
            last_activity=datetime.utcnow(),
            has_pending_decision=False,
            git_dirty=False,
        )
        db_session.add(project)
        db_session.commit()

        assert project.health_score <= 100


class TestProgressItem:
    """Tests for ProgressItem model."""

    def test_progress_item_creation(self, db_session, sample_project_record):
        """Test progress item creation linked to project."""
        item = ProgressItem(
            project_id=sample_project_record.id,
            item_type="task",
            content="Implement feature X",
            status="pending",
            priority="high",
        )
        db_session.add(item)
        db_session.commit()

        assert item.id is not None
        assert item.project_id == sample_project_record.id

    def test_progress_item_relationship(self, db_session, sample_project_record):
        """Test bidirectional relationship with Project."""
        item = ProgressItem(
            project_id=sample_project_record.id,
            item_type="task",
            content="Test task",
            status="pending",
        )
        db_session.add(item)
        db_session.commit()

        # Access via project relationship
        assert len(sample_project_record.items) == 1
        assert sample_project_record.items[0].content == "Test task"

    def test_cascade_delete(self, db_session, sample_project_record):
        """Test that deleting project deletes items."""
        item = ProgressItem(
            project_id=sample_project_record.id,
            item_type="task",
            content="Test task",
            status="pending",
        )
        db_session.add(item)
        db_session.commit()

        item_id = item.id
        db_session.delete(sample_project_record)
        db_session.commit()

        assert db_session.query(ProgressItem).filter_by(id=item_id).first() is None


class TestScanHistory:
    """Tests for ScanHistory model."""

    def test_scan_history_creation(self, db_session, sample_project_record):
        """Test scan history creation."""
        history = ScanHistory(
            project_id=sample_project_record.id,
            completion_pct=45.0,
            items_total=10,
            items_complete=4,
            items_in_progress=2,
            items_pending=4,
        )
        db_session.add(history)
        db_session.commit()

        assert history.id is not None
        assert history.scanned_at is not None

    def test_scan_history_relationship(self, db_session, sample_project_record):
        """Test bidirectional relationship with Project."""
        history = ScanHistory(
            project_id=sample_project_record.id,
            completion_pct=45.0,
        )
        db_session.add(history)
        db_session.commit()

        assert len(sample_project_record.history) == 1

    def test_multiple_history_entries(self, db_session, sample_project_record):
        """Test multiple history entries for tracking progress over time."""
        for i in range(3):
            history = ScanHistory(
                project_id=sample_project_record.id,
                completion_pct=30.0 + (i * 20),
                scanned_at=datetime.utcnow() - timedelta(days=i),
            )
            db_session.add(history)

        db_session.commit()

        assert len(sample_project_record.history) == 3


class TestDatabaseInit:
    """Tests for database initialization functions."""

    def test_init_db_creates_tables(self, temp_dir):
        """Test that init_db creates database tables."""
        db_path = temp_dir / "test.db"
        init_db(db_path)

        assert db_path.exists()

    def test_get_session_after_init(self, temp_dir):
        """Test that get_session returns valid session after init."""
        db_path = temp_dir / "test.db"
        init_db(db_path)
        session = get_session()

        # Should be able to query
        projects = session.query(Project).all()
        assert projects == []

        session.close()

    def test_get_session_auto_init(self):
        """Test that get_session auto-initializes if not initialized."""
        # This uses the default path
        session = get_session()
        assert session is not None
        session.close()


class TestProjectQueries:
    """Tests for common query patterns."""

    def test_filter_by_category(self, db_session, multiple_projects):
        """Test filtering projects by category."""
        clients = db_session.query(Project).filter_by(category="client").all()
        assert len(clients) == 2

        internal = db_session.query(Project).filter_by(category="internal").all()
        assert len(internal) == 1

    def test_filter_by_project_type(self, db_session, multiple_projects):
        """Test filtering projects by type."""
        python_projects = db_session.query(Project).filter_by(project_type="python").all()
        assert len(python_projects) == 2

    def test_filter_by_pending_decision(self, db_session, multiple_projects):
        """Test filtering projects with pending decisions."""
        with_decisions = db_session.query(Project).filter_by(
            has_pending_decision=True
        ).all()
        assert len(with_decisions) == 1
        assert with_decisions[0].name == "client-beta"

    def test_filter_by_git_dirty(self, db_session, multiple_projects):
        """Test filtering projects with uncommitted changes."""
        dirty = db_session.query(Project).filter_by(git_dirty=True).all()
        assert len(dirty) == 1
        assert dirty[0].name == "client-beta"

    def test_order_by_completion(self, db_session, multiple_projects):
        """Test ordering projects by completion percentage."""
        projects = db_session.query(Project).order_by(
            Project.completion_pct.desc()
        ).all()

        # Should be ordered: internal-tool (95), client-alpha (80), cli-helper (60), client-beta (30)
        assert projects[0].name == "internal-tool"
        assert projects[-1].name == "client-beta"

    def test_order_by_last_activity(self, db_session, multiple_projects):
        """Test ordering projects by last activity."""
        projects = db_session.query(Project).order_by(
            Project.last_activity.desc()
        ).all()

        # Most recent first
        assert projects[0].name == "internal-tool"

    def test_filter_stale_projects(self, db_session, multiple_projects):
        """Test filtering projects inactive for 30+ days."""
        threshold = datetime.utcnow() - timedelta(days=30)
        stale = db_session.query(Project).filter(
            Project.last_activity < threshold
        ).all()

        assert len(stale) == 1
        assert stale[0].name == "client-beta"

    def test_search_by_name(self, db_session, multiple_projects):
        """Test searching projects by name pattern."""
        results = db_session.query(Project).filter(
            Project.name.ilike("%client%")
        ).all()

        assert len(results) == 2
