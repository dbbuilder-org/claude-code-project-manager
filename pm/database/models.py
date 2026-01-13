"""SQLAlchemy models for project tracking."""

from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, Column, String, Float, Boolean, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

Base = declarative_base()


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
    has_todo = Column(Boolean, default=False)
    has_progress = Column(Boolean, default=False)
    progress_files = Column(Text)  # JSON list

    # Relationships
    items = relationship("ProgressItem", back_populates="project", cascade="all, delete-orphan")
    history = relationship("ScanHistory", back_populates="project", cascade="all, delete-orphan")

    @property
    def health_score(self) -> int:
        """Calculate project health score (0-100).

        Factors:
        - Completion progress (0-30 pts)
        - Has CLAUDE.md (10 pts)
        - Has progress tracking files (10 pts)
        - Recent activity (0-20 pts)
        - No pending decisions (10 pts)
        - Clean git state (10 pts)
        - Known project type (10 pts)
        """
        score = 0

        # Completion (0-30 pts)
        if self.completion_pct is not None:
            score += int(self.completion_pct * 0.3)

        # Has CLAUDE.md (10 pts)
        if self.has_claude_md:
            score += 10

        # Has progress files (10 pts)
        if self.has_todo or self.has_progress:
            score += 10

        # Recent activity (0-20 pts)
        if self.last_activity:
            from datetime import timedelta
            days_ago = (datetime.utcnow() - self.last_activity).days
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

    scanned_at = Column(DateTime, default=datetime.utcnow)
    completion_pct = Column(Float)
    items_total = Column(Integer)
    items_complete = Column(Integer)
    items_in_progress = Column(Integer)
    items_pending = Column(Integer)

    project = relationship("Project", back_populates="history")


# Database connection
_engine = None
_SessionLocal = None


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize the database."""
    global _engine, _SessionLocal

    if db_path is None:
        db_path = Path(__file__).parent.parent.parent / "data" / "projects.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)


def get_session() -> Session:
    """Get a database session."""
    global _SessionLocal

    if _SessionLocal is None:
        init_db()

    return _SessionLocal()
