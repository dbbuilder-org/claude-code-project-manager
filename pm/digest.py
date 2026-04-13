"""Activity digest queries for project manager."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Optional

from sqlalchemy.orm import Session

from .database.models import Project, ScanHistory


def week_to_date_range() -> tuple[datetime, datetime]:
    """Return (last_sunday_midnight, today_end_of_day) as the default digest range."""
    today = date.today()
    days_since_sunday = (today.weekday() + 1) % 7
    last_sunday = today - timedelta(days=days_since_sunday)
    start_dt = datetime.combine(last_sunday, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())
    return start_dt, end_dt


def digest_by_project(
    session: Session,
    start_dt: datetime,
    end_dt: datetime,
    client_filter: Optional[str] = None,
) -> list[dict]:
    """Get activity digest grouped by project/client.

    Returns a list of dicts sorted by client_name then project name, each with:
        name, client, completion_delta, current_completion, last_commit_msg,
        current_status, health, scan_count
    """
    histories = (
        session.query(ScanHistory)
        .filter(ScanHistory.scanned_at.between(start_dt, end_dt))
        .order_by(ScanHistory.project_id, ScanHistory.scanned_at)
        .all()
    )

    # Group scan history by project
    grouped = {}
    for pid, group in groupby(histories, key=lambda h: h.project_id):
        entries = list(group)
        grouped[pid] = {
            "first_pct": entries[0].completion_pct,
            "last_pct": entries[-1].completion_pct,
            "scan_count": len(entries),
        }

    # Also include projects with commits in the range (even if no scan history)
    commit_projects = (
        session.query(Project)
        .filter(
            Project.last_commit_date.between(start_dt, end_dt),
            (Project.archived == False) | (Project.archived == None),
        )
        .all()
    )
    for p in commit_projects:
        if p.id not in grouped:
            grouped[p.id] = {
                "first_pct": p.completion_pct,
                "last_pct": p.completion_pct,
                "scan_count": 0,
            }

    if not grouped:
        return []

    projects = session.query(Project).filter(Project.id.in_(list(grouped.keys()))).all()

    if client_filter:
        projects = [p for p in projects if p.client_name and client_filter.lower() in p.client_name.lower()]

    results = []
    for p in projects:
        g = grouped[p.id]
        first = g["first_pct"] or 0
        last = g["last_pct"] or 0
        results.append({
            "name": p.name,
            "client": p.client_name or "",
            "completion_delta": last - first,
            "current_completion": p.completion_pct or 0,
            "last_commit_msg": p.last_commit_msg or "",
            "current_status": p.current_status or "",
            "health": p.health_score,
            "scan_count": g["scan_count"],
        })

    results.sort(key=lambda r: (r["client"] or "zzz", r["name"]))
    return results


def digest_by_day(
    session: Session,
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict]:
    """Get activity digest grouped by day.

    Returns a list of dicts sorted by date, each with:
        date, day_name, project_names, project_count
    """
    histories = (
        session.query(ScanHistory)
        .filter(ScanHistory.scanned_at.between(start_dt, end_dt))
        .order_by(ScanHistory.scanned_at)
        .all()
    )

    # Group by date
    days: dict[date, set[str]] = defaultdict(set)
    for h in histories:
        days[h.scanned_at.date()].add(h.project_id)

    # Also include projects with commits in the range
    commit_projects = (
        session.query(Project)
        .filter(
            Project.last_commit_date.between(start_dt, end_dt),
            (Project.archived == False) | (Project.archived == None),
        )
        .all()
    )
    for p in commit_projects:
        if p.last_commit_date:
            days[p.last_commit_date.date()].add(p.id)

    if not days:
        return []

    # Resolve project IDs to names
    all_ids = set()
    for ids in days.values():
        all_ids.update(ids)
    project_map = {
        p.id: p.name
        for p in session.query(Project).filter(Project.id.in_(list(all_ids))).all()
    }

    results = []
    for d in sorted(days.keys()):
        names = sorted(project_map.get(pid, pid) for pid in days[d])
        results.append({
            "date": d,
            "day_name": d.strftime("%A"),
            "project_names": names,
            "project_count": len(names),
        })

    return results
