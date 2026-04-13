"""Project filter helpers — shared by CLI and future consumers."""

from datetime import datetime, timezone
from typing import Optional


def apply_project_filter(query, filter_str: Optional[str]):
    """Apply a filter string to a SQLAlchemy Project query.

    Supported filters:
        type:<category>    e.g. type:client
        priority:<1-5>     e.g. priority:1
        overdue            projects past their deadline
        tagged:<tag>       projects with a specific tag
        status:active      completion < 100
        status:complete    completion >= 100
    """
    if not filter_str:
        return query

    from .database.models import Project as _Project

    if filter_str.startswith("type:"):
        category = filter_str.split(":", 1)[1]
        query = query.filter(_Project.category == category)
    elif filter_str.startswith("priority:"):
        try:
            p = int(filter_str.split(":", 1)[1])
            query = query.filter(_Project.priority == p)
        except ValueError:
            pass
    elif filter_str == "overdue":
        query = query.filter(
            _Project.deadline < datetime.now(timezone.utc).replace(tzinfo=None)
        )
    elif filter_str.startswith("tagged:"):
        tag = filter_str.split(":", 1)[1]
        query = query.filter(_Project.tags.ilike(f"%{tag}%"))
    elif filter_str.startswith("status:"):
        s = filter_str.split(":", 1)[1]
        if s == "active":
            query = query.filter(_Project.completion_pct < 100)
        elif s == "complete":
            query = query.filter(_Project.completion_pct >= 100)

    return query
