"""Project context builder for document generation."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ProjectContext:
    """Context data passed to document templates for rendering."""

    name: str
    path: Path
    project_type: str
    category: str
    completion_pct: float
    current_phase: str
    next_action: str
    git_branch: str
    git_dirty: bool
    last_commit_msg: str
    has_claude_md: bool
    has_todo: bool
    has_progress: bool
    health_score: int
    urgency_score: int
    priority: int
    deadline: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""


def build_context(project) -> ProjectContext:
    """Build a ProjectContext from a database Project model.

    Args:
        project: A pm.database.models.Project instance.

    Returns:
        ProjectContext with fields populated from the project record.
    """
    # Parse tags from JSON
    tags = []
    if project.tags:
        try:
            tags = json.loads(project.tags)
        except (json.JSONDecodeError, TypeError):
            pass

    # Format deadline as string
    deadline_str = None
    if project.deadline:
        deadline_str = project.deadline.strftime("%Y-%m-%d")

    return ProjectContext(
        name=project.name,
        path=Path(project.path),
        project_type=project.project_type or "unknown",
        category=project.category or "internal",
        completion_pct=project.completion_pct or 0.0,
        current_phase=project.current_phase or "",
        next_action=project.next_action or "",
        git_branch=project.git_branch or "main",
        git_dirty=project.git_dirty or False,
        last_commit_msg=project.last_commit_msg or "",
        has_claude_md=project.has_claude_md or False,
        has_todo=project.has_todo or False,
        has_progress=project.has_progress or False,
        health_score=project.health_score,
        urgency_score=project.urgency_score,
        priority=project.priority or 3,
        deadline=deadline_str,
        tags=tags,
        notes=project.notes or "",
    )
