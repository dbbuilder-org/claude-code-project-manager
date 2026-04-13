"""SQLAlchemy models for project tracking."""

import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, Column, String, Float, Boolean, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

Base = declarative_base()


def _utcnow() -> datetime:
    """Naive UTC datetime — timezone.utc stripped for SQLite compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Canonical priority label mapping — import this instead of redefining locally
PRIORITY_LABELS: dict[int, str] = {
    1: "Critical",
    2: "High",
    3: "Normal",
    4: "Low",
    5: "Someday",
}


class Project(Base):
    """Project entity."""
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    path = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    project_type = Column(String)  # 'node', 'python', 'rust', etc.
    category = Column(String)  # 'client', 'internal', 'tool'

    # Scan metadata
    last_scanned = Column(DateTime)
    last_activity = Column(DateTime)

    # Parsed progress state
    completion_pct = Column(Float)
    current_phase = Column(String)
    current_status = Column(String)
    current_focus = Column(Text)
    next_action = Column(Text)
    has_pending_decision = Column(Boolean, default=False)

    # Git state
    git_branch = Column(String)
    git_dirty = Column(Boolean, default=False)
    last_commit_date = Column(DateTime)
    last_commit_msg = Column(Text)

    # Files found
    has_claude_md = Column(Boolean, default=False)
    has_readme = Column(Boolean, default=False)
    has_todo = Column(Boolean, default=False)
    has_progress = Column(Boolean, default=False)
    progress_files = Column(Text)  # JSON list

    # PM metadata (user-editable)
    notes = Column(Text)  # Free-form commentary
    deadline = Column(DateTime)  # Hard deadline
    target_date = Column(DateTime)  # Target completion date
    priority = Column(Integer, default=3)  # 1=critical, 2=high, 3=normal, 4=low, 5=someday
    tags = Column(Text)  # JSON list of tags
    client_name = Column(String)  # Client attribution
    budget_hours = Column(Float)  # Estimated hours
    hours_logged = Column(Float, default=0)  # Hours spent
    archived = Column(Boolean, default=False)  # Hide from active lists

    # Relationships
    items = relationship("ProgressItem", back_populates="project", cascade="all, delete-orphan")
    history = relationship("ScanHistory", back_populates="project", cascade="all, delete-orphan")
    doc_generations = relationship("DocGeneration", back_populates="project", cascade="all, delete-orphan")

    @property
    def days_until_deadline(self) -> Optional[int]:
        """Days until deadline (negative if overdue)."""
        if self.deadline:
            return (self.deadline - _utcnow()).days
        return None

    @property
    def days_until_target(self) -> Optional[int]:
        """Days until target date (negative if past)."""
        if self.target_date:
            return (self.target_date - _utcnow()).days
        return None

    @property
    def is_overdue(self) -> bool:
        """Check if project is past deadline."""
        return self.days_until_deadline is not None and self.days_until_deadline < 0

    @property
    def urgency_score(self) -> int:
        """Calculate urgency based on deadline/priority (0-100, higher = more urgent)."""
        score = 0

        # Priority boost (1=critical adds 40, 5=someday adds 0)
        if self.priority:
            score += max(0, (6 - self.priority) * 10)

        # Deadline urgency
        days = self.days_until_deadline
        if days is not None:
            if days < 0:  # Overdue
                score += 50
            elif days <= 3:
                score += 40
            elif days <= 7:
                score += 30
            elif days <= 14:
                score += 20
            elif days <= 30:
                score += 10

        # Target date urgency (softer)
        target_days = self.days_until_target
        if target_days is not None and days is None:  # Only if no deadline
            if target_days < 0:
                score += 20
            elif target_days <= 7:
                score += 15
            elif target_days <= 14:
                score += 10

        return min(score, 100)

    @property
    def health_score(self) -> int:
        """Calculate project health score (0-100).

        Factors:
        - Completion progress (0-25 pts)
        - Has CLAUDE.md (10 pts)
        - Has README.md (5 pts)
        - Has progress tracking files (10 pts)
        - Recent activity (0-20 pts)
        - No pending decisions (10 pts)
        - Clean git state (10 pts)
        - Known project type (10 pts)
        """
        score = 0

        # Completion (0-25 pts)
        if self.completion_pct is not None:
            score += int(self.completion_pct * 0.25)

        # Has CLAUDE.md (10 pts)
        if self.has_claude_md:
            score += 10

        # Has README.md (5 pts)
        if self.has_readme:
            score += 5

        # Has progress files (10 pts)
        if self.has_todo or self.has_progress:
            score += 10

        # Recent activity (0-20 pts)
        if self.last_activity:
            days_ago = (_utcnow() - self.last_activity).days
            if days_ago <= 7:
                score += 20
            elif days_ago <= 14:
                score += 15
            elif days_ago <= 30:
                score += 10
            elif days_ago <= 60:
                score += 5

        # No pending decisions (10 pts)
        if not self.has_pending_decision:
            score += 10

        # Clean git state (10 pts)
        if not self.git_dirty:
            score += 10

        # Known project type (10 pts)
        if self.project_type and self.project_type != 'generic':
            score += 10

        return min(score, 100)

    @property
    def priority_label(self) -> str:
        """Human-readable priority label."""
        return PRIORITY_LABELS.get(self.priority, "Normal")

    @property
    def tags_list(self) -> list[str]:
        """Parse tags JSON to list."""
        if self.tags:
            try:
                return json.loads(self.tags)
            except json.JSONDecodeError:
                return []
        return []

    def add_tag(self, tag: str) -> None:
        """Add a tag (no-op if already present)."""
        import json
        tags = self.tags_list
        if tag not in tags:
            tags.append(tag)
            self.tags = json.dumps(tags)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag (no-op if not present)."""
        import json
        tags = self.tags_list
        if tag in tags:
            tags.remove(tag)
            self.tags = json.dumps(tags)

    @staticmethod
    def all_tags(session) -> list[str]:
        """Get all unique tags across all projects, sorted."""
        projects = session.query(Project).filter(Project.tags.isnot(None)).all()
        all_t = set()
        for p in projects:
            all_t.update(p.tags_list)
        return sorted(all_t)

    @property
    def is_stale(self) -> bool:
        """Check if project is stale (inactive 30+ days, not archived, not someday)."""
        if self.archived:
            return False
        if self.priority == 5:
            return False
        if self.last_activity is None:
            return True
        return (_utcnow() - self.last_activity).days >= 30


class ProgressItem(Base):
    """Individual progress/todo item."""
    __tablename__ = "progress_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)

    item_type = Column(String)  # 'task', 'phase', 'milestone', 'decision'
    content = Column(Text)
    status = Column(String)  # 'pending', 'in_progress', 'complete', 'blocked'
    priority = Column(String)  # 'critical', 'high', 'medium', 'low'
    source_file = Column(String)
    line_number = Column(Integer)

    project = relationship("Project", back_populates="items")


class ScanHistory(Base):
    """Historical scan data for tracking progress over time."""
    __tablename__ = "scan_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)

    scanned_at = Column(DateTime, default=_utcnow)
    completion_pct = Column(Float)
    items_total = Column(Integer)
    items_complete = Column(Integer)
    items_in_progress = Column(Integer)
    items_pending = Column(Integer)

    project = relationship("Project", back_populates="history")


class DocGeneration(Base):
    """Record of a document generation run."""
    __tablename__ = "doc_generations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    template_id = Column(String, nullable=False)  # "roadmap", "architecture", etc.
    output_path = Column(String)  # Relative path from project root
    generated_at = Column(DateTime, default=_utcnow)
    duration_secs = Column(Float)
    status = Column(String)  # "success", "error", "timeout"
    error_message = Column(Text)
    file_size_bytes = Column(Integer)

    project = relationship("Project", back_populates="doc_generations")


class AgentRun(Base):
    """Record of an agent assess/execute/escalate run."""
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)

    # Timing
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime)
    duration_secs = Column(Float)

    # Assess phase
    confidence = Column(Integer)               # 0-100
    proposed_action = Column(Text)
    proposed_prompt = Column(Text)
    reasoning = Column(Text)
    risk_level = Column(String)                # "safe", "moderate", "risky"
    assess_duration_secs = Column(Float)

    # Execute phase
    status = Column(String)                    # "auto_executed", "escalated", "dry_run", "error"
    output = Column(Text)
    error_message = Column(Text)
    cost_usd = Column(Float)                   # Estimated cost of this run in USD

    project = relationship("Project", backref="agent_runs")


# Database connection
import threading as _threading
_engine = None
_SessionLocal = None
_db_lock = _threading.Lock()


# Migration registry: (version, description, list of (col_name, sql_type))
_MIGRATIONS = [
    (1, "PM metadata columns", [
        ("notes", "TEXT"),
        ("deadline", "DATETIME"),
        ("target_date", "DATETIME"),
        ("priority", "INTEGER DEFAULT 3"),
        ("tags", "TEXT"),
        ("client_name", "VARCHAR"),
        ("budget_hours", "FLOAT"),
        ("hours_logged", "FLOAT DEFAULT 0"),
        ("archived", "BOOLEAN DEFAULT 0"),
    ]),
    (2, "AgentRun cost tracking", []),  # New column added via table create; alter handled below
    (3, "has_readme column", [
        ("has_readme", "BOOLEAN DEFAULT 0"),
    ]),
]

# Column additions outside of 'projects' table (table_name, col_name, sql_type)
_TABLE_MIGRATIONS = [
    (2, "agent_runs", "cost_usd", "FLOAT"),
]


_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_SAFE_SQL_TYPE = re.compile(r'^[A-Z]+(\s+(DEFAULT\s+\S+|NOT\s+NULL|\d+))*$', re.IGNORECASE)


def _validate_sql_identifier(name: str) -> str:
    """Raise ValueError if name is not a safe SQL identifier."""
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    return name


def _migrate_db(engine) -> None:
    """Run schema migrations transactionally; skip already-applied versions."""
    from sqlalchemy import inspect, text

    with engine.connect() as conn:
        # Ensure migration tracking table exists
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        ))
        conn.commit()

        # Create new tables if needed (idempotent via checkfirst)
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        if "doc_generations" not in existing_tables:
            DocGeneration.__table__.create(engine, checkfirst=True)
        if "agent_runs" not in existing_tables:
            AgentRun.__table__.create(engine, checkfirst=True)

        for version, description, columns in _MIGRATIONS:
            row = conn.execute(
                text("SELECT version FROM schema_migrations WHERE version = :v"),
                {"v": version}
            ).fetchone()
            if row is not None:
                continue  # Already applied

            try:
                # Projects-table ALTER TABLEs
                if columns:
                    existing_columns = {
                        c['name'] for c in inspect(engine).get_columns('projects')
                    }
                    for col_name, col_type in columns:
                        if col_name not in existing_columns:
                            conn.execute(text(
                                f"ALTER TABLE projects ADD COLUMN {_validate_sql_identifier(col_name)} {col_type}"
                            ))

                # Other-table ALTER TABLEs for this version
                for mig_version, table_name, col_name, col_type in _TABLE_MIGRATIONS:
                    if mig_version != version:
                        continue
                    existing_tables = inspect(engine).get_table_names()
                    if table_name not in existing_tables:
                        continue
                    existing_cols = {
                        c['name'] for c in inspect(engine).get_columns(table_name)
                    }
                    if col_name not in existing_cols:
                        conn.execute(text(
                            f"ALTER TABLE {_validate_sql_identifier(table_name)} ADD COLUMN {_validate_sql_identifier(col_name)} {col_type}"
                        ))

                conn.execute(
                    text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :ts)"),
                    {"v": version, "ts": _utcnow().isoformat()}
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                if "duplicate column name" not in str(e).lower():
                    raise


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize the database (thread-safe, idempotent)."""
    global _engine, _SessionLocal

    with _db_lock:
        # Already initialized — skip unless a different path is requested
        if _engine is not None and db_path is None:
            return

        if db_path is None:
            env_path = os.environ.get("PM_DB_PATH")
            if env_path:
                db_path = Path(env_path).expanduser()
            else:
                db_path = Path.home() / ".pm" / "projects.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(_engine)
        _migrate_db(_engine)  # Add missing columns
        _SessionLocal = sessionmaker(bind=_engine)


def get_session() -> Session:
    """Get a database session."""
    global _SessionLocal

    if _SessionLocal is None:
        init_db()

    return _SessionLocal()


@contextmanager
def db_session():
    """Context manager that provides a session and guarantees close + rollback on error.

    Usage::

        with db_session() as session:
            project = session.query(Project).filter_by(name="foo").first()
            session.commit()
    """
    session = get_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
