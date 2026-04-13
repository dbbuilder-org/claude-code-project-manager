"""Morning briefing and anomaly detection for project manager."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .database.models import Project, ScanHistory


def _days_inactive(project: Project) -> Optional[int]:
    if project.last_activity:
        return (datetime.utcnow() - project.last_activity).days
    return None


def build_brief(session: Session, lookback_days: int = 7) -> dict:
    """Build a structured morning brief with anomaly detection.

    Returns a dict with sections:
        deadlines       — overdue or due within 7 days
        high_priority   — priority 1/2 projects needing attention
        newly_stale     — went stale (30+ days) within the lookback window
        anomalies       — completion drops, decisions, deadline + inactive
        wins            — 100% completions or large jumps in lookback window
        summary         — one-line overview
    """
    now = datetime.utcnow()
    stale_threshold = now - timedelta(days=30)
    newly_stale_threshold = now - timedelta(days=30 + lookback_days)
    lookback_start = now - timedelta(days=lookback_days)

    active = session.query(Project).filter(
        (Project.archived == False) | (Project.archived == None),
        Project.priority != 5,
    ).all()

    # ── Deadlines ────────────────────────────────────────────────────────────
    deadlines = []
    for p in active:
        days = p.days_until_deadline
        if days is not None and days <= 7:
            deadlines.append({
                "name": p.name,
                "days": days,
                "overdue": days < 0,
                "completion": p.completion_pct or 0,
                "priority": p.priority_label,
            })
    deadlines.sort(key=lambda x: x["days"])

    # ── High priority ─────────────────────────────────────────────────────────
    high_priority = []
    for p in active:
        if p.priority and p.priority <= 2:
            inactive = _days_inactive(p)
            high_priority.append({
                "name": p.name,
                "priority": p.priority_label,
                "completion": p.completion_pct or 0,
                "days_inactive": inactive,
                "next_action": p.next_action or "",
                "has_decision": p.has_pending_decision or False,
            })
    high_priority.sort(key=lambda x: (x["days_inactive"] or 0), reverse=True)

    # ── Newly stale ───────────────────────────────────────────────────────────
    newly_stale = []
    for p in active:
        if p.last_activity:
            days_inactive = _days_inactive(p)
            if days_inactive is not None and days_inactive >= 30:
                # Only "newly" stale if they crossed 30 days within the lookback window
                crossed_threshold = p.last_activity < stale_threshold and p.last_activity >= newly_stale_threshold
                if crossed_threshold:
                    newly_stale.append({
                        "name": p.name,
                        "days_inactive": days_inactive,
                        "completion": p.completion_pct or 0,
                        "category": p.category or "internal",
                    })
        elif p.priority and p.priority <= 3:
            # Never had activity — include if normal priority or higher
            newly_stale.append({
                "name": p.name,
                "days_inactive": None,
                "completion": p.completion_pct or 0,
                "category": p.category or "internal",
            })

    # Limit to most interesting
    newly_stale = newly_stale[:10]

    # ── Anomalies ─────────────────────────────────────────────────────────────
    anomalies = []

    # Completion regressions: compare latest scan history to one before lookback
    project_ids = [p.id for p in active]
    if project_ids:
        recent_scans = session.query(ScanHistory).filter(
            ScanHistory.project_id.in_(project_ids),
            ScanHistory.scanned_at >= lookback_start,
        ).order_by(ScanHistory.project_id, ScanHistory.scanned_at).all()

        before_scans = session.query(ScanHistory).filter(
            ScanHistory.project_id.in_(project_ids),
            ScanHistory.scanned_at < lookback_start,
        ).order_by(ScanHistory.project_id, ScanHistory.scanned_at.desc()).all()

        # latest scan before lookback per project
        before_map = {}
        for s in before_scans:
            if s.project_id not in before_map:
                before_map[s.project_id] = s.completion_pct or 0

        # latest scan in lookback per project
        recent_map = {}
        for s in recent_scans:
            recent_map[s.project_id] = s.completion_pct or 0

        for p in active:
            if p.id in before_map and p.id in recent_map:
                delta = recent_map[p.id] - before_map[p.id]
                if delta < -5:  # Completion dropped by more than 5%
                    anomalies.append({
                        "type": "regression",
                        "name": p.name,
                        "detail": f"completion dropped {abs(delta):.0f}% (now {recent_map[p.id]:.0f}%)",
                    })

    # High-priority with deadline but no recent activity
    for p in active:
        if p.deadline and p.priority and p.priority <= 2:
            inactive = _days_inactive(p)
            if inactive is not None and inactive >= 7:
                days = p.days_until_deadline
                if days is not None and days <= 14:
                    anomalies.append({
                        "type": "deadline_inactive",
                        "name": p.name,
                        "detail": f"deadline in {days}d, inactive {inactive}d",
                    })

    # Pending decisions on high-priority projects
    decision_count = sum(
        1 for p in active
        if p.has_pending_decision and p.priority and p.priority <= 2
    )
    if decision_count > 0:
        anomalies.append({
            "type": "decisions",
            "name": f"{decision_count} high-priority project{'s' if decision_count > 1 else ''}",
            "detail": "pending decisions blocking progress",
        })

    # ── Wins ─────────────────────────────────────────────────────────────────
    wins = []
    for p in active:
        if p.id in recent_map and p.id in before_map:
            delta = recent_map[p.id] - before_map[p.id]
            if delta >= 20 or (recent_map[p.id] >= 100 and before_map[p.id] < 100):
                wins.append({
                    "name": p.name,
                    "delta": delta,
                    "current": recent_map[p.id],
                })
    wins.sort(key=lambda x: x["delta"], reverse=True)
    wins = wins[:5]

    # ── Summary ───────────────────────────────────────────────────────────────
    parts = []
    if deadlines:
        overdue_count = sum(1 for d in deadlines if d["overdue"])
        upcoming_count = len(deadlines) - overdue_count
        if overdue_count:
            parts.append(f"{overdue_count} overdue")
        if upcoming_count:
            parts.append(f"{upcoming_count} due this week")
    if len(high_priority) > 0:
        parts.append(f"{len(high_priority)} high-priority")
    if newly_stale:
        parts.append(f"{len(newly_stale)} newly stale")
    if anomalies:
        parts.append(f"{len(anomalies)} anomalies")
    if wins:
        parts.append(f"{len(wins)} wins")

    total_active = len(active)
    avg_health = sum(p.health_score for p in active) / total_active if total_active else 0
    summary = f"{total_active} active projects, avg health {avg_health:.0f}/100"
    if parts:
        summary += f" | {', '.join(parts)}"

    return {
        "deadlines": deadlines,
        "high_priority": high_priority,
        "newly_stale": newly_stale,
        "anomalies": anomalies,
        "wins": wins,
        "summary": summary,
        "total_active": total_active,
        "avg_health": avg_health,
        "generated_at": now,
    }


def format_brief_text(brief: dict, verbose: bool = False) -> str:
    """Format the brief as a human-readable text string (suitable for CLI or iMessage)."""
    lines = []
    now = brief["generated_at"]
    lines.append(f"PM Brief — {now.strftime('%A %b %d %Y')}")
    lines.append(brief["summary"])

    if brief["deadlines"]:
        lines.append("")
        lines.append("DEADLINES")
        for d in brief["deadlines"]:
            if d["overdue"]:
                lines.append(f"  ⏰ {d['name']} — OVERDUE {abs(d['days'])}d ({d['completion']:.0f}% done)")
            else:
                lines.append(f"  📅 {d['name']} — {d['days']}d left ({d['completion']:.0f}% done)")

    if brief["high_priority"]:
        lines.append("")
        lines.append("HIGH PRIORITY")
        for p in brief["high_priority"]:
            inactive_str = f", {p['days_inactive']}d inactive" if p['days_inactive'] else ""
            decision_str = " ⚠️ decision pending" if p["has_decision"] else ""
            action_str = f"\n    → {p['next_action']}" if p["next_action"] and verbose else ""
            lines.append(f"  🔴 {p['name']} ({p['priority']}{inactive_str}{decision_str}){action_str}")

    if brief["anomalies"]:
        lines.append("")
        lines.append("ANOMALIES")
        for a in brief["anomalies"]:
            lines.append(f"  ⚠️  {a['name']} — {a['detail']}")

    if brief["newly_stale"]:
        lines.append("")
        lines.append(f"NEWLY STALE ({len(brief['newly_stale'])})")
        for p in brief["newly_stale"]:
            inactive = f"{p['days_inactive']}d" if p['days_inactive'] else "never active"
            lines.append(f"  💤 {p['name']} ({inactive}, {p['completion']:.0f}%)")

    if brief["wins"]:
        lines.append("")
        lines.append("WINS")
        for w in brief["wins"]:
            if w["current"] >= 100:
                lines.append(f"  ✅ {w['name']} — COMPLETE")
            else:
                lines.append(f"  ✅ {w['name']} — +{w['delta']:.0f}% → {w['current']:.0f}%")

    return "\n".join(lines)


def format_brief_imessage(brief: dict) -> str:
    """Format the brief as a short iMessage-friendly text (under 500 chars per section)."""
    now = brief["generated_at"]
    parts = [f"📊 PM Brief {now.strftime('%a %b %d')}"]
    parts.append(f"  {brief['summary']}")

    if brief["deadlines"]:
        items = []
        for d in brief["deadlines"][:3]:
            if d["overdue"]:
                items.append(f"⏰{d['name']}(OVERDUE {abs(d['days'])}d)")
            else:
                items.append(f"📅{d['name']}({d['days']}d)")
        parts.append("Deadlines: " + ", ".join(items))

    if brief["anomalies"]:
        items = [f"{a['name']}: {a['detail']}" for a in brief["anomalies"][:3]]
        parts.append("⚠️  " + " | ".join(items))

    if brief["wins"]:
        names = [w["name"] for w in brief["wins"][:3]]
        parts.append("✅ Wins: " + ", ".join(names))

    if not brief["deadlines"] and not brief["anomalies"] and not brief["wins"]:
        parts.append("No urgent items. All clear.")

    return "\n".join(parts)
