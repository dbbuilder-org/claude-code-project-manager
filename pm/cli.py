"""CLI interface for project manager."""

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import box

from .scanner.detector import ProjectDetector, ProjectInfo
from .scanner.parser import ProgressParser, ProjectProgress, ItemStatus
from .generator.prompts import ContinuePromptGenerator, PromptMode
from .database.models import init_db, get_session, Project, ProgressItem, ScanHistory
from .metadata import read_pm_status, sync_to_file, sync_project_to_file, PM_STATUS_FILENAME
from .digest import week_to_date_range, digest_by_project, digest_by_day
from .brief import build_brief, format_brief_text, format_brief_imessage
from .terminal import (
    TerminalApp,
    detect_terminal,
    launch_single as terminal_launch_single,
    launch_batch as terminal_launch_batch,
    build_command as terminal_build_command,
    is_shutdown_supported,
    _escape_applescript,
)


console = Console()


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
    from datetime import datetime as _dt

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
        query = query.filter(_Project.deadline < _dt.now(timezone.utc).replace(tzinfo=None))
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


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Project Manager - Multi-project Claude Code orchestration."""
    pass


@main.command()
@click.argument("base_path", type=click.Path(exists=True), default="~/dev2")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def scan(base_path: str, verbose: bool):
    """Scan directory for projects and update database."""
    base_path = Path(base_path).expanduser().resolve()

    console.print(f"[bold blue]Scanning[/bold blue] {base_path}")

    # Initialize database
    init_db()

    detector = ProjectDetector(base_path)
    parser = ProgressParser()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Detecting projects...", total=None)

        projects = detector.scan()
        progress.update(task, description=f"Found {len(projects)} projects")

        # Process each project
        session = get_session()
        stats = {"new": 0, "updated": 0, "client": 0, "internal": 0, "tool": 0}

        for proj_info in projects:
            progress.update(task, description=f"Processing {proj_info.name}...")

            # Parse progress
            proj_progress = parser.parse_project(proj_info.path)

            # Update database
            proj_id = str(proj_info.path)
            existing = session.query(Project).filter_by(id=proj_id).first()

            if existing:
                stats["updated"] += 1
                proj = existing
            else:
                stats["new"] += 1
                proj = Project(id=proj_id)
                session.add(proj)

            # Update project fields
            proj.path = str(proj_info.path)
            proj.name = proj_info.name
            proj.project_type = proj_info.project_type
            proj.category = proj_info.category
            proj.last_scanned = datetime.now(timezone.utc).replace(tzinfo=None)

            # Progress state
            proj.completion_pct = proj_progress.completion_pct
            proj.current_phase = proj_progress.current_phase
            proj.current_status = proj_progress.current_status
            proj.current_focus = proj_progress.current_focus
            proj.next_action = proj_progress.next_action
            proj.has_pending_decision = proj_progress.has_pending_decision

            # Git state
            proj.git_branch = proj_info.git_branch
            proj.git_dirty = proj_info.git_dirty
            proj.last_commit_date = proj_info.last_commit_date
            proj.last_commit_msg = proj_info.last_commit_msg
            proj.last_activity = proj_info.last_commit_date

            # Files
            proj.has_claude_md = proj_info.has_claude_md
            proj.has_readme = proj_info.has_readme
            proj.has_todo = proj_info.has_todo
            proj.has_progress = proj_info.has_progress
            proj.progress_files = json.dumps(proj_info.progress_files)

            # Read PM-STATUS.md metadata (if exists)
            pm_meta = read_pm_status(proj_info.path)
            if pm_meta:
                # Only update if values are set in file (don't overwrite with defaults)
                if pm_meta.priority != 3:  # Non-default priority
                    proj.priority = pm_meta.priority
                if pm_meta.deadline:
                    proj.deadline = pm_meta.deadline
                if pm_meta.target_date:
                    proj.target_date = pm_meta.target_date
                if pm_meta.tags:
                    proj.tags = json.dumps(pm_meta.tags)
                if pm_meta.client_name:
                    proj.client_name = pm_meta.client_name
                if pm_meta.budget_hours:
                    proj.budget_hours = pm_meta.budget_hours
                if pm_meta.hours_logged:
                    proj.hours_logged = pm_meta.hours_logged
                if pm_meta.archived:
                    proj.archived = pm_meta.archived
                if pm_meta.notes:
                    proj.notes = pm_meta.notes

            # Track category stats
            stats[proj_info.category] = stats.get(proj_info.category, 0) + 1

            # Update progress items
            session.query(ProgressItem).filter_by(project_id=proj_id).delete()
            for item in proj_progress.items[:50]:  # Limit items
                session.add(ProgressItem(
                    project_id=proj_id,
                    item_type=item.item_type,
                    content=item.content,
                    status=item.status.value,
                    priority=item.priority.value if item.priority else None,
                    source_file=item.source_file,
                    line_number=item.line_number,
                ))

            # Add history entry
            session.add(ScanHistory(
                project_id=proj_id,
                completion_pct=proj_progress.completion_pct,
                items_total=len(proj_progress.items),
                items_complete=sum(1 for i in proj_progress.items if i.status == ItemStatus.COMPLETE),
                items_in_progress=sum(1 for i in proj_progress.items if i.status == ItemStatus.IN_PROGRESS),
                items_pending=sum(1 for i in proj_progress.items if i.status == ItemStatus.PENDING),
            ))

        session.commit()
        session.close()

    # Print summary
    console.print()
    console.print(Panel(
        f"[green]✓[/green] Scanned {len(projects)} projects\n"
        f"  • New: {stats['new']}\n"
        f"  • Updated: {stats['updated']}\n"
        f"  • Client: {stats['client']}\n"
        f"  • Internal: {stats['internal']}\n"
        f"  • Tool: {stats['tool']}",
        title="Scan Complete",
        border_style="green",
    ))


@main.command()
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, status:active")
@click.option("--sort", "-s", default="name", help="Sort by: name, completion, activity")
@click.option("--limit", "-n", default=0, help="Limit results (0 = no limit)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(filter_str: Optional[str], sort: str, limit: int, as_json: bool):
    """Show project status summary."""
    init_db()
    session = get_session()

    # Build query
    query = session.query(Project)

    query = apply_project_filter(query, filter_str)

    # Apply sort
    if sort == "completion":
        query = query.order_by(Project.completion_pct.desc().nullslast())
    elif sort == "activity":
        query = query.order_by(Project.last_activity.desc().nullslast())
    else:
        query = query.order_by(Project.name)

    if limit > 0:
        query = query.limit(limit)
    projects = query.all()

    if as_json:
        data = [{
            "name": p.name,
            "path": p.path,
            "category": p.category,
            "completion": p.completion_pct,
            "phase": p.current_phase,
            "next_action": p.next_action,
            "has_decision": p.has_pending_decision,
            "git_dirty": p.git_dirty,
        } for p in projects]
        console.print_json(json.dumps(data, default=str))
        return

    # Build table
    table = Table(
        title=f"Projects ({len(projects)} shown)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        expand=True,
    )

    table.add_column("Project", style="bold", width=20, no_wrap=True)
    table.add_column("Cat", width=8)
    table.add_column("Progress", width=15)
    table.add_column("Phase/Status", min_width=20)
    table.add_column("Next Action", min_width=25)
    table.add_column("", width=8)  # Flags

    for p in projects:
        # Progress bar
        pct = p.completion_pct or 0
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        pct_str = f"{bar} {pct:.0f}%" if pct else "[dim]—[/dim]"

        # Flags
        flags = []
        if p.has_pending_decision:
            flags.append("⚠️")
        if p.git_dirty:
            flags.append("●")
        if p.has_claude_md:
            flags.append("📄")

        # Phase/Status
        phase = p.current_phase or p.current_status or "[dim]—[/dim]"
        if len(phase) > 25:
            phase = phase[:22] + "..."

        # Next action
        next_act = p.next_action or "[dim]—[/dim]"
        if len(next_act) > 30:
            next_act = next_act[:27] + "..."

        # Category color
        cat_colors = {"client": "green", "internal": "blue", "tool": "yellow"}
        cat_style = cat_colors.get(p.category, "white")

        table.add_row(
            p.name,
            f"[{cat_style}]{p.category}[/{cat_style}]",
            pct_str,
            phase,
            next_act,
            " ".join(flags),
        )

    console.print(table)

    # Summary stats
    total = len(projects)
    with_decisions = sum(1 for p in projects if p.has_pending_decision)
    dirty = sum(1 for p in projects if p.git_dirty)
    avg_completion = sum(p.completion_pct or 0 for p in projects) / total if total else 0

    console.print()
    console.print(f"[dim]Avg completion: {avg_completion:.0f}% | "
                  f"Pending decisions: {with_decisions} | "
                  f"Uncommitted changes: {dirty}[/dim]")

    session.close()


@main.command("continue")
@click.argument("project_name", required=False)
@click.option("--filter", "-f", "filter_str", help="Filter projects")
@click.option("--mode", "-m", default="context", type=click.Choice(["simple", "context", "decision"]))
@click.option("--parallel", "-p", default=1, help="Parallel terminals to launch")
@click.option("--dry-run", is_flag=True, help="Show command without executing")
def continue_project(
    project_name: Optional[str],
    filter_str: Optional[str],
    mode: str,
    parallel: int,
    dry_run: bool
):
    """Generate and optionally run continue command for a project."""
    init_db()
    session = get_session()
    parser = ProgressParser()
    generator = ContinuePromptGenerator()

    prompt_mode = PromptMode(mode)

    # Find project(s)
    if project_name:
        proj = session.query(Project).filter(
            Project.name.ilike(f"%{project_name}%")
        ).first()

        if not proj:
            console.print(f"[red]Project not found:[/red] {project_name}")
            return

        projects = [proj]
    elif filter_str:
        query = session.query(Project)
        if filter_str.startswith("type:"):
            category = filter_str.split(":")[1]
            query = query.filter(Project.category == category)
        projects = query.limit(10).all()
    else:
        console.print("[yellow]Specify project name or --filter[/yellow]")
        return

    # Generate prompts
    for proj in projects:
        project_path = Path(proj.path)
        progress = parser.parse_project(project_path)
        prompt = generator.generate(project_path, proj.name, progress, prompt_mode)

        console.print(Panel(
            f"[bold]{proj.name}[/bold]\n"
            f"Path: {proj.path}\n"
            f"Mode: {prompt.mode.value}\n\n"
            f"[cyan]Command:[/cyan]\n{prompt.command}",
            title="Continue Prompt",
            border_style="blue",
        ))

        if prompt.prompt_text:
            console.print(Panel(
                prompt.prompt_text,
                title="Context to send",
                border_style="dim",
            ))

        if not dry_run and click.confirm("Execute?"):
            # Copy context to clipboard
            if prompt.prompt_text:
                try:
                    subprocess.run(
                        ["pbcopy"],
                        input=prompt.prompt_text.encode(),
                        check=True
                    )
                    console.print("[green]Context copied to clipboard[/green]")
                except Exception:
                    pass

            # Open in terminal (iTerm2 or Terminal.app)
            used = terminal_launch_single(
                str(project_path), proj.name, prompt.command
            )
            console.print(f"[green]✓[/green] Launched {used.value} for {proj.name}")

    session.close()



@main.command()
@click.option("--port", "-p", default=8501, help="Dashboard port")
def dashboard(port: int):
    """Launch the Streamlit dashboard."""
    import sys
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "app.py"

    if not dashboard_path.exists():
        console.print("[red]Dashboard not found. Create dashboard/app.py first.[/red]")
        return

    console.print(f"[bold blue]Launching dashboard[/bold blue] on port {port}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path), "--server.port", str(port)])


@main.command()
def summary():
    """Quick summary of all projects."""
    init_db()
    session = get_session()

    total = session.query(Project).count()
    clients = session.query(Project).filter_by(category="client").count()
    internal = session.query(Project).filter_by(category="internal").count()
    tools = session.query(Project).filter_by(category="tool").count()

    decisions = session.query(Project).filter_by(has_pending_decision=True).count()
    dirty = session.query(Project).filter_by(git_dirty=True).count()

    # Completion buckets
    complete = session.query(Project).filter(Project.completion_pct >= 90).count()
    progress = session.query(Project).filter(
        Project.completion_pct >= 25,
        Project.completion_pct < 90
    ).count()
    early = session.query(Project).filter(Project.completion_pct < 25).count()
    unknown = session.query(Project).filter(Project.completion_pct.is_(None)).count()

    console.print(Panel(
        f"[bold]Total Projects:[/bold] {total}\n\n"
        f"[green]Client:[/green] {clients}  "
        f"[blue]Internal:[/blue] {internal}  "
        f"[yellow]Tools:[/yellow] {tools}\n\n"
        f"[bold]Completion:[/bold]\n"
        f"  ✅ Complete (90%+): {complete}\n"
        f"  🔄 In Progress (25-90%): {progress}\n"
        f"  🌱 Early (<25%): {early}\n"
        f"  ❓ Unknown: {unknown}\n\n"
        f"[bold]Flags:[/bold]\n"
        f"  ⚠️ Pending decisions: {decisions}\n"
        f"  ● Uncommitted changes: {dirty}",
        title="Project Portfolio Summary",
        border_style="cyan",
    ))

    session.close()


@main.command()
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, type:internal")
@click.option("--limit", "-n", default=0, help="Limit results (0 = no limit)")
@click.option("--asc", is_flag=True, help="Show lowest health first (needs attention)")
def health(filter_str: Optional[str], limit: int, asc: bool):
    """Show projects sorted by health score."""
    init_db()
    session = get_session()

    # Build query
    query = session.query(Project)

    query = apply_project_filter(query, filter_str)
    projects = query.all()

    # Calculate health scores and sort
    projects_with_health = [(p, p.health_score) for p in projects]
    projects_with_health.sort(key=lambda x: x[1], reverse=not asc)

    # Limit
    if limit > 0:
        projects_with_health = projects_with_health[:limit]

    # Build table
    table = Table(
        title=f"Project Health ({'Needs Attention' if asc else 'Healthiest'} First)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Project", style="bold", width=22)
    table.add_column("Cat", width=8)
    table.add_column("Health", width=12)
    table.add_column("Completion", width=12)
    table.add_column("Activity", width=12)
    table.add_column("Issues", min_width=20)

    for p, score in projects_with_health:
        # Health bar
        filled = int(score / 10)
        if score >= 70:
            color = "green"
        elif score >= 40:
            color = "yellow"
        else:
            color = "red"
        health_bar = f"[{color}]{'█' * filled}{'░' * (10 - filled)}[/{color}] {score}"

        # Completion
        comp = f"{p.completion_pct:.0f}%" if p.completion_pct else "—"

        # Last activity
        if p.last_activity:
            days = (datetime.now(timezone.utc).replace(tzinfo=None) - p.last_activity).days
            if days == 0:
                activity = "today"
            elif days == 1:
                activity = "yesterday"
            elif days < 7:
                activity = f"{days}d ago"
            elif days < 30:
                activity = f"{days // 7}w ago"
            else:
                activity = f"{days // 30}mo ago"
        else:
            activity = "—"

        # Issues
        issues = []
        if p.has_pending_decision:
            issues.append("⚠️ decision")
        if p.git_dirty:
            issues.append("● uncommitted")
        if not p.has_claude_md:
            issues.append("📄 no CLAUDE.md")
        if p.project_type == 'generic':
            issues.append("? generic type")

        cat_colors = {"client": "green", "internal": "blue", "tool": "yellow"}
        cat_style = cat_colors.get(p.category, "white")

        table.add_row(
            p.name,
            f"[{cat_style}]{p.category}[/{cat_style}]",
            health_bar,
            comp,
            activity,
            ", ".join(issues) if issues else "[green]✓[/green]",
        )

    console.print(table)

    # Summary
    avg_health = sum(h for _, h in projects_with_health) / len(projects_with_health) if projects_with_health else 0
    console.print(f"\n[dim]Average health: {avg_health:.0f}/100[/dim]")

    session.close()


@main.command()
@click.argument("project_name")
@click.option("--notes", "-n", help="Set project notes/commentary")
@click.option("--deadline", "-d", help="Set deadline (YYYY-MM-DD)")
@click.option("--target", "-t", help="Set target date (YYYY-MM-DD)")
@click.option("--priority", "-p", type=click.Choice(["1", "2", "3", "4", "5"]),
              help="Set priority: 1=critical, 2=high, 3=normal, 4=low, 5=someday")
@click.option("--tags", help="Set tags (comma-separated)")
@click.option("--client", help="Set client name")
@click.option("--budget", type=float, help="Set budget hours")
@click.option("--hours", type=float, help="Log hours spent")
@click.option("--archive/--unarchive", default=None, help="Archive/unarchive project")
@click.option("--show", "-s", is_flag=True, help="Show current metadata")
@click.option("--sync/--no-sync", default=True, help="Sync changes to PM-STATUS.md file")
def edit(project_name: str, notes: Optional[str], deadline: Optional[str],
         target: Optional[str], priority: Optional[str], tags: Optional[str],
         client: Optional[str], budget: Optional[float], hours: Optional[float],
         archive: Optional[bool], show: bool, sync: bool):
    """Edit project metadata (notes, deadlines, priority, etc.).

    Changes are synced to PM-STATUS.md in the project folder by default.
    Use --no-sync to only update the database.
    """
    init_db()
    session = get_session()

    # Find project
    project = session.query(Project).filter(
        Project.name.ilike(f"%{project_name}%")
    ).first()

    if not project:
        console.print(f"[red]Project '{project_name}' not found[/red]")
        session.close()
        return

    # Show current metadata
    if show or all(x is None for x in [notes, deadline, target, priority, tags, client, budget, hours, archive]):
        console.print(Panel(f"[bold]{project.name}[/bold]", subtitle=project.path))

        table = Table(box=box.SIMPLE)
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        table.add_row("Priority", f"{project.priority_label} ({project.priority})")
        table.add_row("Deadline", str(project.deadline.date()) if project.deadline else "—")
        table.add_row("Target Date", str(project.target_date.date()) if project.target_date else "—")
        table.add_row("Days to Deadline", str(project.days_until_deadline) if project.days_until_deadline else "—")
        table.add_row("Urgency Score", str(project.urgency_score))
        table.add_row("Client", project.client_name or "—")
        table.add_row("Budget Hours", f"{project.budget_hours:.1f}" if project.budget_hours else "—")
        table.add_row("Hours Logged", f"{project.hours_logged:.1f}" if project.hours_logged else "0")
        table.add_row("Tags", ", ".join(project.tags_list) if project.tags_list else "—")
        table.add_row("Archived", "Yes" if project.archived else "No")
        table.add_row("Notes", project.notes[:100] + "..." if project.notes and len(project.notes) > 100 else (project.notes or "—"))

        # Check for PM-STATUS.md file
        pm_file = Path(project.path) / PM_STATUS_FILENAME
        table.add_row("PM-STATUS.md", "[green]exists[/green]" if pm_file.exists() else "[dim]not created[/dim]")

        console.print(table)

        if not any([notes, deadline, target, priority, tags, client, budget, hours, archive is not None]):
            console.print("\n[dim]Use options to update: --notes, --deadline, --priority, etc.[/dim]")
            console.print(f"[dim]Changes sync to {PM_STATUS_FILENAME} by default (--no-sync to disable)[/dim]")
            session.close()
            return

    # Update fields
    updated = []

    if notes is not None:
        project.notes = notes
        updated.append("notes")

    if deadline is not None:
        try:
            project.deadline = datetime.strptime(deadline, "%Y-%m-%d")
            updated.append("deadline")
        except ValueError:
            console.print(f"[red]Invalid date format: {deadline}. Use YYYY-MM-DD[/red]")

    if target is not None:
        try:
            project.target_date = datetime.strptime(target, "%Y-%m-%d")
            updated.append("target_date")
        except ValueError:
            console.print(f"[red]Invalid date format: {target}. Use YYYY-MM-DD[/red]")

    if priority is not None:
        project.priority = int(priority)
        updated.append("priority")

    if tags is not None:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        project.tags = json.dumps(tag_list)
        updated.append("tags")

    if client is not None:
        project.client_name = client
        updated.append("client_name")

    if budget is not None:
        project.budget_hours = budget
        updated.append("budget_hours")

    if hours is not None:
        project.hours_logged = (project.hours_logged or 0) + hours
        updated.append(f"hours_logged (+{hours})")

    if archive is not None:
        project.archived = archive
        updated.append("archived" if archive else "unarchived")

    if updated:
        session.commit()
        console.print(f"[green]✓ Updated {project.name}:[/green] {', '.join(updated)}")

        # Sync to PM-STATUS.md file
        if sync:
            from .metadata import ProjectMetadata
            meta = ProjectMetadata(
                priority=project.priority or 3,
                deadline=project.deadline,
                target_date=project.target_date,
                tags=project.tags_list,
                client_name=project.client_name,
                budget_hours=project.budget_hours,
                hours_logged=project.hours_logged or 0,
                archived=project.archived or False,
                notes=project.notes or "",
            )
            if sync_to_file(Path(project.path), **vars(meta)):
                console.print(f"[green]✓ Synced to[/green] {PM_STATUS_FILENAME}")
            else:
                console.print(f"[yellow]⚠ Could not write {PM_STATUS_FILENAME}[/yellow]")

    session.close()


@main.command()
@click.argument("project_name")
def someday(project_name: str):
    """Move a project to the Someday/Maybe pile (priority 5).

    This is a quick way to park something without losing it.
    Use 'pm backlog' to see all someday and archived projects.
    Use 'pm edit <name> --priority 3' to pull it back to active.
    """
    init_db()
    session = get_session()

    project = session.query(Project).filter(
        Project.name.ilike(f"%{project_name}%")
    ).first()

    if not project:
        console.print(f"[red]No project found matching '{project_name}'[/red]")
        session.close()
        return

    old_label = project.priority_label
    project.priority = 5
    session.commit()

    sync_project_to_file(project)

    console.print(f"[green]Moved '{project.name}' to Someday[/green] (was {old_label})")
    console.print(f"[dim]View backlog: pm backlog | Restore: pm edit {project.name} --priority 3[/dim]")
    session.close()


@main.command()
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, priority:1, overdue, tagged:foo")
@click.option("--limit", "-n", default=20, help="Limit results")
@click.option("--all", "show_all", is_flag=True, help="Show all projects sorted by urgency (not just urgent ones)")
def urgent(filter_str: Optional[str], limit: int, show_all: bool):
    """Show projects with real urgency signals (deadlines, priority 1/2, overdue).

    By default only shows projects that have an actual urgency signal:
    a deadline set, priority Critical/High, or an overdue target date.
    Use --all to see every project ranked by urgency score.
    """
    init_db()
    session = get_session()

    query = session.query(Project).filter(Project.archived == False)

    query = apply_project_filter(query, filter_str)
    projects = query.all()

    # Sort by urgency
    projects_sorted = sorted(projects, key=lambda p: p.urgency_score, reverse=True)

    # Default: only show projects with a real urgency signal
    if not show_all:
        projects_sorted = [
            p for p in projects_sorted
            if p.deadline is not None
            or (p.priority is not None and p.priority <= 2)
            or p.is_overdue
            or (p.target_date is not None and p.days_until_target is not None and p.days_until_target <= 14)
        ]

    if limit > 0:
        projects_sorted = projects_sorted[:limit]

    if not projects_sorted:
        console.print("[yellow]No urgent projects found.[/yellow]")
        console.print("[dim]Set a deadline: pm edit <project> --deadline YYYY-MM-DD[/dim]")
        console.print("[dim]Or boost priority: pm edit <project> --priority 1[/dim]")
        console.print("[dim]Use --all to see all projects ranked by urgency score.[/dim]")
        session.close()
        return

    title = "All Projects by Urgency" if show_all else "Urgent Projects (deadlines · priority 1/2 · overdue)"
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Project")
    table.add_column("Priority")
    table.add_column("Deadline")
    table.add_column("Days Left")
    table.add_column("Urgency")
    table.add_column("Progress")
    table.add_column("Notes")

    for p in projects_sorted:
        # Priority styling
        priority_colors = {1: "red bold", 2: "yellow", 3: "white", 4: "dim", 5: "dim"}
        priority_style = priority_colors.get(p.priority, "white")

        # Deadline styling
        days = p.days_until_deadline
        if days is not None:
            if days < 0:
                deadline_str = f"[red bold]OVERDUE ({abs(days)}d)[/red bold]"
            elif days <= 3:
                deadline_str = f"[red]{p.deadline.strftime('%m/%d')}[/red]"
            elif days <= 7:
                deadline_str = f"[yellow]{p.deadline.strftime('%m/%d')}[/yellow]"
            else:
                deadline_str = p.deadline.strftime("%m/%d")
            days_str = str(days) if days >= 0 else f"[red]{days}[/red]"
        else:
            deadline_str = "—"
            days_str = "—"

        # Urgency bar
        urgency = p.urgency_score
        bar_filled = int(urgency / 10)
        bar = f"[red]{'█' * bar_filled}[/red][dim]{'░' * (10 - bar_filled)}[/dim] {urgency}"

        # Progress
        prog = f"{p.completion_pct:.0f}%" if p.completion_pct else "—"

        # Notes preview
        notes_preview = (p.notes[:30] + "...") if p.notes and len(p.notes) > 30 else (p.notes or "—")

        table.add_row(
            p.name,
            f"[{priority_style}]{p.priority_label}[/{priority_style}]",
            deadline_str,
            days_str,
            bar,
            prog,
            notes_preview,
        )

    console.print(table)
    session.close()


@main.command()
@click.option("--limit", "-n", default=0, help="Limit results (0 = no limit)")
def backlog(limit: int):
    """Show someday/maybe projects (priority 5) and archived."""
    init_db()
    session = get_session()

    # Someday projects
    query = session.query(Project).filter(
        (Project.priority == 5) | (Project.archived == True)
    ).order_by(Project.name)

    if limit > 0:
        query = query.limit(limit)

    projects = query.all()

    if not projects:
        console.print("[green]No backlog projects[/green]")
        session.close()
        return

    table = Table(title="Backlog / Someday Projects", box=box.SIMPLE)
    table.add_column("Project")
    table.add_column("Status")
    table.add_column("Category")
    table.add_column("Progress")
    table.add_column("Notes")

    for p in projects:
        status = "[dim]Archived[/dim]" if p.archived else "[cyan]Someday[/cyan]"
        prog = f"{p.completion_pct:.0f}%" if p.completion_pct else "—"
        notes = (p.notes[:40] + "...") if p.notes and len(p.notes) > 40 else (p.notes or "—")

        table.add_row(p.name, status, p.category, prog, notes)

    console.print(table)
    console.print(f"\n[dim]Total: {len(projects)} projects in backlog[/dim]")
    session.close()


# ── Tags ────────────────────────────────────────────────────────────────────


@main.group()
def tags():
    """Manage project tags."""
    pass


@tags.command("list")
def tags_list():
    """List all tags with project counts."""
    init_db()
    session = get_session()

    projects = session.query(Project).filter(Project.tags.isnot(None)).all()
    tag_counts: dict[str, int] = {}
    for p in projects:
        for t in p.tags_list:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    if not tag_counts:
        console.print("[dim]No tags found across any projects[/dim]")
        session.close()
        return

    table = Table(title="Tags", box=box.SIMPLE)
    table.add_column("Tag")
    table.add_column("Projects", justify="right")

    for tag in sorted(tag_counts.keys()):
        table.add_row(tag, str(tag_counts[tag]))

    console.print(table)
    console.print(f"\n[dim]{len(tag_counts)} unique tags across {sum(tag_counts.values())} assignments[/dim]")
    session.close()


@tags.command("add")
@click.argument("project_name")
@click.argument("tag")
@click.option("--sync/--no-sync", default=True, help="Sync to PM-STATUS.md")
def tags_add(project_name: str, tag: str, sync: bool):
    """Add a tag to a project."""
    init_db()
    session = get_session()

    project = session.query(Project).filter(Project.name.ilike(f"%{project_name}%")).first()
    if not project:
        console.print(f"[red]Project '{project_name}' not found[/red]")
        session.close()
        return

    project.add_tag(tag)
    session.commit()
    console.print(f"[green]✓ Added tag '{tag}' to {project.name}[/green]")
    console.print(f"  Tags: {', '.join(project.tags_list)}")

    if sync:
        _sync_project(project)

    session.close()


@tags.command("remove")
@click.argument("project_name")
@click.argument("tag")
@click.option("--sync/--no-sync", default=True, help="Sync to PM-STATUS.md")
def tags_remove(project_name: str, tag: str, sync: bool):
    """Remove a tag from a project."""
    init_db()
    session = get_session()

    project = session.query(Project).filter(Project.name.ilike(f"%{project_name}%")).first()
    if not project:
        console.print(f"[red]Project '{project_name}' not found[/red]")
        session.close()
        return

    if tag not in project.tags_list:
        console.print(f"[yellow]Tag '{tag}' not on {project.name}[/yellow]")
        session.close()
        return

    project.remove_tag(tag)
    session.commit()
    console.print(f"[green]✓ Removed tag '{tag}' from {project.name}[/green]")
    console.print(f"  Tags: {', '.join(project.tags_list) or '(none)'}")

    if sync:
        _sync_project(project)

    session.close()


@tags.command("bulk")
@click.argument("tag")
@click.argument("project_names", nargs=-1)
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, category:internal")
@click.option("--sync/--no-sync", default=True, help="Sync to PM-STATUS.md")
def tags_bulk(tag: str, project_names: tuple, filter_str: Optional[str], sync: bool):
    """Apply a tag to multiple projects.

    Examples:
        pm tags bulk mobile myapp1 myapp2
        pm tags bulk client-work --filter type:client
    """
    init_db()
    session = get_session()

    if project_names:
        projects = []
        for name in project_names:
            p = session.query(Project).filter(Project.name.ilike(f"%{name}%")).first()
            if p:
                projects.append(p)
            else:
                console.print(f"[yellow]Not found: {name}[/yellow]")
    elif filter_str:
        query = apply_project_filter(session.query(Project), filter_str)
        projects = query.all()
    else:
        console.print("[yellow]Specify project names or --filter[/yellow]")
        session.close()
        return

    if not projects:
        console.print("[red]No projects found[/red]")
        session.close()
        return

    count = 0
    for p in projects:
        if tag not in p.tags_list:
            p.add_tag(tag)
            count += 1
            if sync:
                _sync_project(p)

    session.commit()
    console.print(f"[green]✓ Applied tag '{tag}' to {count} project(s)[/green]")
    session.close()


def _sync_project(project: Project) -> None:
    """Sync project metadata to PM-STATUS.md."""
    sync_project_to_file(project)


main.add_command(tags)


# ── Digest ──────────────────────────────────────────────────────────────────


@main.command()
@click.option("--start", "-s", "start_str", help="Start date YYYY-MM-DD (default: last Sunday)")
@click.option("--end", "-e", "end_str", help="End date YYYY-MM-DD (default: today)")
@click.option("--by-day", is_flag=True, help="Group by day instead of project/client")
@click.option("--client", "-c", help="Filter by client name")
def digest(start_str: Optional[str], end_str: Optional[str], by_day: bool, client: Optional[str]):
    """Activity digest for a date range.

    Default range: week-to-date (last Sunday through today).

    Examples:
        pm digest                              # Week-to-date by project
        pm digest --by-day                     # Week-to-date by day
        pm digest -s 2026-01-01 -e 2026-01-31  # January by project
        pm digest --client "Acme"              # Filter by client
    """

    init_db()
    session = get_session()

    # Parse date range
    default_start, default_end = week_to_date_range()
    start_dt = datetime.strptime(start_str, "%Y-%m-%d") if start_str else default_start
    end_dt = datetime.combine(datetime.strptime(end_str, "%Y-%m-%d").date(), datetime.max.time()) if end_str else default_end

    range_label = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    if by_day:
        results = digest_by_day(session, start_dt, end_dt)
        if not results:
            console.print(f"[dim]No activity found for {range_label}[/dim]")
            session.close()
            return

        table = Table(title=f"Activity by Day — {range_label}", box=box.SIMPLE)
        table.add_column("Date")
        table.add_column("Day")
        table.add_column("#", justify="right")
        table.add_column("Projects")

        for r in results:
            table.add_row(
                r["date"].strftime("%Y-%m-%d"),
                r["day_name"],
                str(r["project_count"]),
                ", ".join(r["project_names"][:10]) + ("..." if len(r["project_names"]) > 10 else ""),
            )

        console.print(table)
        total_projects = len(set(n for r in results for n in r["project_names"]))
        console.print(f"\n[dim]{len(results)} active days, {total_projects} unique projects[/dim]")
    else:
        results = digest_by_project(session, start_dt, end_dt, client_filter=client)
        if not results:
            console.print(f"[dim]No activity found for {range_label}[/dim]")
            session.close()
            return

        table = Table(title=f"Activity by Project — {range_label}", box=box.SIMPLE)
        table.add_column("Project")
        table.add_column("Client")
        table.add_column("Δ%", justify="right")
        table.add_column("Current %", justify="right")
        table.add_column("Last Commit")
        table.add_column("Status")
        table.add_column("Health", justify="right")

        current_client = None
        for r in results:
            # Visual grouping by client
            if r["client"] != current_client:
                current_client = r["client"]
                if current_client:
                    table.add_section()

            delta_str = f"+{r['completion_delta']:.0f}" if r["completion_delta"] > 0 else f"{r['completion_delta']:.0f}"
            if r["completion_delta"] > 0:
                delta_str = f"[green]{delta_str}[/green]"
            elif r["completion_delta"] < 0:
                delta_str = f"[red]{delta_str}[/red]"

            health = r["health"]
            h_color = "green" if health >= 70 else ("yellow" if health >= 40 else "red")

            table.add_row(
                r["name"],
                r["client"] or "",
                delta_str,
                f"{r['current_completion']:.0f}",
                (r["last_commit_msg"][:40] + "...") if len(r["last_commit_msg"]) > 40 else r["last_commit_msg"],
                r["current_status"][:20] if r["current_status"] else "",
                f"[{h_color}]{health}[/{h_color}]",
            )

        console.print(table)
        console.print(f"\n[dim]{len(results)} projects with activity[/dim]")

    session.close()


# ── Brief ────────────────────────────────────────────────────────────────────


@main.command()
@click.option("--days", "-d", default=7, help="Lookback window in days (default: 7)")
@click.option("--verbose", "-v", is_flag=True, help="Show next actions for high-priority projects")
@click.option("--imessage", "-i", is_flag=True, help="Send brief via iMessage (requires cci session)")
@click.option("--only-if-urgent", is_flag=True, help="Suppress output if nothing is urgent")
def brief(days: int, verbose: bool, imessage: bool, only_if_urgent: bool):
    """Daily intelligent briefing: deadlines, anomalies, high-priority, wins.

    Surfaces only what matters — not a dump of all 600 projects.

    Examples:
        pm brief                      # Morning briefing to terminal
        pm brief --verbose            # Include next actions
        pm brief --imessage           # Send to iMessage (+12064962555)
        pm brief --only-if-urgent     # Suppress if nothing needs attention
    """

    init_db()
    session = get_session()

    brief_data = build_brief(session, lookback_days=days)
    session.close()

    has_urgent = (
        len(brief_data["deadlines"]) > 0
        or len(brief_data["anomalies"]) > 0
        or len(brief_data["high_priority"]) > 0
    )

    if only_if_urgent and not has_urgent:
        return

    if imessage:
        # Send via iMessage using AppleScript
        message = format_brief_imessage(brief_data)
        phone = "+12064962555"
        escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
        script = f'tell application "Messages" to send "{escaped}" to buddy "{phone}" of service "SMS"'
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                console.print("[green]Brief sent via iMessage[/green]")
            else:
                console.print(f"[yellow]iMessage send failed: {result.stderr.strip()}[/yellow]")
                console.print("[dim]Falling back to terminal output:[/dim]")
                console.print(format_brief_text(brief_data, verbose=verbose))
        except subprocess.TimeoutExpired:
            console.print("[yellow]iMessage timed out — showing in terminal instead[/yellow]")
            console.print(format_brief_text(brief_data, verbose=verbose))
    else:
        text = format_brief_text(brief_data, verbose=verbose)
        # Render with Rich color coding
        for line in text.split("\n"):
            if line.startswith("PM Brief"):
                console.print(f"[bold cyan]{line}[/bold cyan]")
            elif line.startswith("  ") and brief_data["summary"] in line:
                console.print(f"[dim]{line}[/dim]")
            elif line in ("DEADLINES", "HIGH PRIORITY", "ANOMALIES", "WINS") or line.startswith("NEWLY STALE"):
                console.print(f"\n[bold yellow]{line}[/bold yellow]")
            elif "OVERDUE" in line:
                console.print(f"[red]{line}[/red]")
            elif line.startswith("  ⏰") or line.startswith("  📅"):
                console.print(f"[yellow]{line}[/yellow]")
            elif line.startswith("  🔴"):
                console.print(f"[red]{line}[/red]")
            elif line.startswith("  ⚠️"):
                console.print(f"[yellow]{line}[/yellow]")
            elif line.startswith("  ✅"):
                console.print(f"[green]{line}[/green]")
            elif line.startswith("  💤"):
                console.print(f"[dim]{line}[/dim]")
            elif line:
                console.print(line)
            else:
                console.print()

    if not has_urgent and not only_if_urgent:
        console.print("\n[green]All clear — no urgent items.[/green]")


# ── Stale ───────────────────────────────────────────────────────────────────


@main.command()
@click.option("--days", "-d", default=30, help="Days of inactivity threshold (default: 30)")
@click.option("--action", "-a", is_flag=True, help="Interactive: prompt for action on each project")
def stale(days: int, action: bool):
    """List stale projects (inactive N+ days, not archived, not someday).

    Examples:
        pm stale              # List stale projects (30+ days)
        pm stale --days 60    # 60+ days inactive
        pm stale --action     # Interactive: pick action for each
    """
    init_db()
    session = get_session()

    threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    projects = session.query(Project).filter(
        (Project.archived == False) | (Project.archived == None),
        Project.priority != 5,
        (Project.last_activity < threshold) | (Project.last_activity == None),
    ).order_by(Project.last_activity.asc().nullsfirst()).all()

    if not projects:
        console.print(f"[green]No stale projects (inactive {days}+ days)[/green]")
        session.close()
        return

    table = Table(title=f"Stale Projects (inactive {days}+ days)", box=box.ROUNDED)
    table.add_column("Project")
    table.add_column("Category")
    table.add_column("Last Activity")
    table.add_column("Days", justify="right")
    table.add_column("Priority")
    table.add_column("Done", justify="right")
    table.add_column("Notes")

    for p in projects:
        days_inactive = (datetime.now(timezone.utc).replace(tzinfo=None) - p.last_activity).days if p.last_activity else "—"
        activity = p.last_activity.strftime("%Y-%m-%d") if p.last_activity else "never"
        notes_preview = (p.notes[:30] + "...") if p.notes and len(p.notes) > 30 else (p.notes or "")

        table.add_row(
            p.name,
            p.category or "",
            activity,
            str(days_inactive),
            p.priority_label,
            f"{p.completion_pct:.0f}%" if p.completion_pct else "—",
            notes_preview,
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(projects)} stale projects[/dim]")

    if action:
        for p in projects:
            _prompt_stale_action(session, p)

    session.close()


def _prompt_stale_action(session, project: Project) -> None:
    """Prompt user for action on a stale project (interactive CLI)."""
    console.print(f"\n[bold]{project.name}[/bold] — {project.path}")
    if project.last_activity:
        days_ago = (datetime.now(timezone.utc).replace(tzinfo=None) - project.last_activity).days
        console.print(f"  Last active: {project.last_activity.strftime('%Y-%m-%d')} ({days_ago}d ago)")
    else:
        console.print("  Last active: never")
    console.print(f"  Completion: {project.completion_pct or 0:.0f}% | Priority: {project.priority_label}")
    if project.notes:
        console.print(f"  Notes: {project.notes[:80]}")

    console.print("\n  [1] Archive   [2] Move forward   [3] Pivot")
    console.print("  [4] Plan      [5] Combine        [6] Replace")
    console.print("  [s] Skip")

    choice = click.prompt("  Action", type=str, default="s").strip().lower()

    if choice == "1":
        reason = click.prompt("  Reason (optional)", default="", show_default=False)
        project.archived = True
        if reason:
            project.notes = f"{project.notes or ''}\n\n[Archived {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d')}] {reason}".strip()
        session.commit()
        _sync_project(project)
        console.print(f"  [green]✓ Archived {project.name}[/green]")

    elif choice == "2":
        next_action = click.prompt("  Next action")
        new_pri = click.prompt("  Priority (1-4)", type=int, default=project.priority or 3)
        project.next_action = next_action
        project.priority = min(max(new_pri, 1), 4)
        session.commit()
        _sync_project(project)
        console.print(f"  [green]✓ Updated {project.name}[/green]")

    elif choice == "3":
        direction = click.prompt("  New direction")
        project.notes = f"{project.notes or ''}\n\n[Pivot {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d')}] {direction}".strip()
        session.commit()
        _sync_project(project)
        console.print(f"  [green]✓ Updated notes for {project.name}[/green]")

    elif choice == "4":
        console.print(f"  [blue]Launching Claude Code for {project.name}...[/blue]")
        cmd = f"cd '{project.path}' && claude"
        terminal_launch_single(project.path, project.name, cmd)

    elif choice == "5":
        target_name = click.prompt("  Combine into which project?")
        target = session.query(Project).filter(Project.name.ilike(f"%{target_name}%")).first()
        if target:
            project.archived = True
            project.notes = f"{project.notes or ''}\n\n[Combined into {target.name} on {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d')}]".strip()
            session.commit()
            _sync_project(project)
            console.print(f"  [green]✓ Archived {project.name}, combined into {target.name}[/green]")
        else:
            console.print(f"  [red]Project '{target_name}' not found[/red]")

    elif choice == "6":
        repl_name = click.prompt("  Replacement project name")
        repl = session.query(Project).filter(Project.name.ilike(f"%{repl_name}%")).first()
        if repl:
            project.archived = True
            project.notes = f"{project.notes or ''}\n\n[Replaced by {repl.name} on {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d')}]".strip()
            session.commit()
            _sync_project(project)
            console.print(f"  [green]✓ Archived {project.name}, replaced by {repl.name}[/green]")
        else:
            console.print(f"  [red]Project '{repl_name}' not found[/red]")


# ── Run Prompt ──────────────────────────────────────────────────────────────


@main.command("run")
@click.argument("project_name")
@click.argument("prompt")
@click.option("--budget", "-b", default=0.50, help="Max budget in USD (default: 0.50)")
@click.option("--timeout", "-t", default=300, help="Timeout in seconds (default: 300)")
@click.option("--tools", help="Allowed tools comma-separated (default: Read,Glob,Grep)")
def run_prompt(project_name: str, prompt: str, budget: float, timeout: int, tools: Optional[str]):
    """Run a prompt against a project via headless Claude Code.

    Executes `claude -p` in the project directory, captures output,
    and logs the result to transcripts/<project>/<timestamp>.md.

    Examples:
        pm run myproject "Summarize the architecture"
        pm run myproject "List all TODO items" --budget 0.25
        pm run myproject "Find security issues" --tools Read,Glob,Grep,WebSearch
    """

    init_db()
    session = get_session()

    project = session.query(Project).filter(Project.name.ilike(f"%{project_name}%")).first()
    if not project:
        console.print(f"[red]Project '{project_name}' not found[/red]")
        session.close()
        return

    allowed_tools = [t.strip() for t in tools.split(",")] if tools else ["Read", "Glob", "Grep"]

    console.print(f"[bold blue]Running prompt on {project.name}[/bold blue]")
    console.print(f"  Budget: ${budget:.2f} | Timeout: {timeout}s | Tools: {', '.join(allowed_tools)}")
    console.print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    console.print()

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(budget),
        "--allowedTools", ",".join(allowed_tools),
    ]

    start_time = time.time()

    with console.status("[bold green]Claude is thinking...", spinner="dots"):
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project.path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_time

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
                console.print(f"[red]Error:[/red] {error_msg}")
                output_text = f"ERROR: {error_msg}"
                status = "error"
            else:
                output_text = result.stdout.strip()
                if not output_text:
                    console.print("[yellow]Claude returned empty output[/yellow]")
                    status = "empty"
                else:
                    console.print(Panel(output_text, title="Result", border_style="green"))
                    status = "success"

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            console.print(f"[red]Timed out after {timeout}s[/red]")
            output_text = f"TIMEOUT after {timeout}s"
            status = "timeout"

        except FileNotFoundError:
            duration = time.time() - start_time
            console.print("[red]'claude' command not found. Is Claude Code CLI installed?[/red]")
            output_text = "ERROR: claude command not found"
            status = "error"

    # Log to transcript — sanitize project name to prevent path traversal
    safe_name = re.sub(r'[^\w\-]', '_', project.name)
    transcript_dir = Path(__file__).parent.parent / "transcripts" / safe_name
    transcript_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d-%H%M%S")
    transcript_file = transcript_dir / f"{timestamp}.md"

    transcript_content = f"""# Prompt Run: {project.name}

- **Date:** {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S UTC')}
- **Status:** {status}
- **Duration:** {duration:.1f}s
- **Budget:** ${budget:.2f}
- **Tools:** {', '.join(allowed_tools)}

## Prompt

{prompt}

## Result

{output_text}
"""
    transcript_file.write_text(transcript_content)
    console.print(f"\n[dim]Transcript saved: {transcript_file}[/dim]")
    console.print(f"[dim]Duration: {duration:.1f}s[/dim]")

    session.close()


@main.command("transcripts")
@click.argument("project_name", required=False)
@click.option("--limit", "-n", default=10, help="Number of transcripts to show")
def list_transcripts(project_name: Optional[str], limit: int):
    """List prompt run transcripts.

    Examples:
        pm transcripts                  # All recent transcripts
        pm transcripts myproject        # Transcripts for one project
        pm transcripts -n 20            # Show more
    """
    transcript_base = Path(__file__).parent.parent / "transcripts"

    if not transcript_base.exists():
        console.print("[dim]No transcripts yet. Use 'pm run' to create one.[/dim]")
        return

    if project_name:
        import re as _re
        safe_name = re.sub(r'[^\w\-]', '_', project_name)
        dirs = [transcript_base / safe_name]
    else:
        dirs = [d for d in transcript_base.iterdir() if d.is_dir()]

    files = []
    for d in dirs:
        if d.exists():
            for f in d.glob("*.md"):
                files.append((d.name, f))

    files.sort(key=lambda x: x[1].name, reverse=True)
    files = files[:limit]

    if not files:
        console.print("[dim]No transcripts found[/dim]")
        return

    table = Table(title="Prompt Transcripts", box=box.SIMPLE)
    table.add_column("Project")
    table.add_column("Date")
    table.add_column("Status")
    table.add_column("File")

    for proj_name, f in files:
        # Quick parse status from file
        content = f.read_text()
        status = "unknown"
        for line in content.split("\n"):
            if line.startswith("- **Status:**"):
                status = line.split(":**")[1].strip()
                break

        ts = f.stem  # e.g. 20260201-143000
        try:
            dt = datetime.strptime(ts, "%Y%m%d-%H%M%S")
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date_str = ts

        status_color = {"success": "green", "error": "red", "timeout": "yellow", "empty": "yellow"}.get(status, "dim")
        table.add_row(proj_name, date_str, f"[{status_color}]{status}[/{status_color}]", str(f))

    console.print(table)


@main.command()
@click.argument("target", default="10")
@click.option("--dirty-only", "-d", is_flag=True, help="Only projects with uncommitted changes")
@click.option("--dry-run", is_flag=True, help="Show what would be launched without launching")
@click.option("--terminal", is_flag=True, help="Force Terminal.app instead of iTerm2")
def launch(target: str, dirty_only: bool, dry_run: bool, terminal: bool):
    """Launch Claude Code for projects.

    TARGET can be:
    - A number: Launch the N most recently modified projects
    - A project name: Launch that specific project

    Uses iTerm2 if installed, otherwise falls back to Terminal.app.
    Use --terminal to force Terminal.app.

    Examples:
        pm launch              # Launch top 10 most recent
        pm launch 5            # Launch top 5 most recent
        pm launch myproject    # Launch specific project by name
        pm launch -d           # Only projects with uncommitted changes
        pm launch --terminal   # Force Terminal.app
    """
    init_db()
    session = get_session()

    # Detect terminal once up front
    term = detect_terminal(force_terminal=terminal)

    # Check if target is a number or project name
    try:
        count = int(target)
        # It's a number - launch top N
        query = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None)
        ).order_by(Project.last_activity.desc().nullslast())

        if dirty_only:
            query = query.filter(Project.git_dirty == True)

        projects = query.limit(count).all()
    except ValueError:
        # It's a project name - find and launch it
        project = session.query(Project).filter(
            Project.name.ilike(f"%{target}%")
        ).first()

        if not project:
            console.print(f"[red]Project '{target}' not found[/red]")
            session.close()
            return

        projects = [project]

    if not projects:
        console.print("[yellow]No projects found matching criteria[/yellow]")
        session.close()
        return

    # Display what we're launching
    table = Table(title=f"Launching {len(projects)} Projects", box=box.SIMPLE)
    table.add_column("#", style="dim")
    table.add_column("Project")
    table.add_column("Last Activity")
    table.add_column("Status")
    table.add_column("Path")

    for i, p in enumerate(projects, 1):
        activity = p.last_activity.strftime("%Y-%m-%d %H:%M") if p.last_activity else "—"
        status_parts = []
        if p.git_dirty:
            status_parts.append("[yellow]●[/yellow]")
        if p.has_pending_decision:
            status_parts.append("[red]⚠[/red]")
        status = " ".join(status_parts) or "[green]✓[/green]"

        table.add_row(str(i), p.name, activity, status, str(p.path))

    console.print(table)

    if dry_run:
        console.print(f"\n[dim]Dry run - would use {term.value} - no terminals opened[/dim]")
        session.close()
        return

    console.print(f"\n[bold blue]Opening {len(projects)} sessions via {term.value}...[/bold blue]")

    # Build project tuples and launch via shared terminal module
    project_tuples = [
        (str(p.path), p.name, terminal_build_command(str(p.path)))
        for p in projects
    ]

    try:
        terminal_launch_batch(project_tuples, terminal=term)
        for p in projects:
            console.print(f"  [green]✓[/green] {p.name}")
    except Exception as e:
        console.print(f"  [red]✗[/red] Failed to launch: {e}")

    console.print(f"\n[bold green]Launched {len(projects)} Claude Code sessions[/bold green]")
    session.close()


def _shutdown_terminal_app(no_context: bool, dry_run: bool, context_wait: int) -> None:
    """Shutdown Claude Code sessions in Terminal.app.

    Terminal.app doesn't support session enumeration by name, so this targets all
    open Terminal.app tabs, sends the context command and /exit to each one.
    """
    # Count Terminal.app windows/tabs
    count_script = '''
    tell application "Terminal"
        set total to 0
        repeat with w in windows
            set total to total + (count of tabs of w)
        end repeat
        return total
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", count_script],
            capture_output=True, text=True, check=True
        )
        tab_count = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        tab_count = 0

    if tab_count == 0:
        console.print("[yellow]No Terminal.app tabs found.[/yellow]")
        return

    console.print(f"Found [cyan]{tab_count}[/cyan] Terminal.app tab(s)")

    if dry_run:
        console.print("\n[dim]Dry run - would perform:[/dim]")
        if not no_context:
            console.print(f"  1. Send 'write context to docs/PROJECT-CONTEXT.md' to each tab")
            console.print(f"  2. Wait {context_wait} seconds")
        console.print("  3. Send '/exit' to each tab")
        return

    if not click.confirm(f"Shutdown {tab_count} Terminal.app tab(s)?", default=True):
        console.print("[yellow]Cancelled[/yellow]")
        return

    # Get window/tab structure
    structure_script = '''
    tell application "Terminal"
        set result to ""
        set wIdx to 1
        repeat with w in windows
            set tIdx to 1
            repeat with t in tabs of w
                set result to result & wIdx & "," & tIdx & "\n"
                set tIdx to tIdx + 1
            end repeat
            set wIdx to wIdx + 1
        end repeat
        return result
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", structure_script],
            capture_output=True, text=True, check=True
        )
        tabs = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                parts = line.strip().split(',')
                if len(parts) == 2:
                    tabs.append((int(parts[0]), int(parts[1])))
    except (subprocess.CalledProcessError, ValueError) as e:
        console.print(f"[red]Failed to enumerate Terminal.app tabs: {e}[/red]")
        return

    for w_idx, t_idx in tabs:
        tab_id = f"w{w_idx}t{t_idx}"
        if not no_context:
            ctx_script = f'''
            tell application "Terminal"
                do script "write context to docs/PROJECT-CONTEXT.md" in tab {t_idx} of window {w_idx}
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", ctx_script], capture_output=True, check=True)
                console.print(f"  [green]✓[/green] {tab_id}: Sent context command")
            except subprocess.CalledProcessError:
                console.print(f"  [yellow]![/yellow] {tab_id}: Could not send context command")

    if not no_context:
        console.print(f"[dim]Waiting {context_wait}s for context to be written...[/dim]")
        time.sleep(context_wait)

    for w_idx, t_idx in tabs:
        tab_id = f"w{w_idx}t{t_idx}"
        exit_script = f'''
        tell application "Terminal"
            do script "/exit" in tab {t_idx} of window {w_idx}
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", exit_script], capture_output=True, check=True)
            console.print(f"  [green]✓[/green] {tab_id}: Sent /exit")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]![/yellow] {tab_id}: Could not send /exit")

    console.print("\n[bold green]Terminal.app shutdown complete![/bold green]")
    console.print("[dim]Note: Terminal.app windows remain open — close them manually.[/dim]")


@main.command()
@click.option("--no-context", is_flag=True, help="Skip writing context docs before shutdown")
@click.option("--dry-run", is_flag=True, help="Show what would be done without executing")
@click.option("--context-wait", default=60, help="Seconds to wait after context command (default: 60)")
def shutdown(no_context: bool, dry_run: bool, context_wait: int):
    """Gracefully shutdown all Claude Code sessions.

    For iTerm2 (full support): For each tab:
    1. Send 'write context to docs/PROJECT-CONTEXT.md' (unless --no-context)
    2. Wait for context to be written (default 60s)
    3. Send '/exit' to close Claude
    4. Wait 5 seconds
    5. Close the tab
    Sessions processed in parallel with 2 second stagger.

    For Terminal.app (limited support):
    - Sends context command and /exit to each tab
    - Windows remain open (Terminal.app cannot be closed programmatically)

    Examples:
        pm shutdown              # Graceful shutdown with context save
        pm shutdown --no-context # Quick shutdown, skip context
        pm shutdown --dry-run    # Preview what would happen
    """

    # Detect terminal; dispatch to appropriate shutdown handler
    from .terminal import detect_terminal, TerminalApp
    terminal = detect_terminal()
    if not is_shutdown_supported(terminal):
        _shutdown_terminal_app(no_context, dry_run, context_wait)
        return

    # AppleScript to get all iTerm2 tab info
    get_tabs_script = '''
    tell application "iTerm"
        set tabList to {}
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    set sessionName to name of s
                    set end of tabList to {windowId:id of w, tabIndex:(index of t), sessionId:id of s, sessionName:sessionName}
                end repeat
            end repeat
        end repeat
        return tabList
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", get_tabs_script],
            capture_output=True, text=True, check=True
        )
        raw_output = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "not running" in stderr.lower() or "can't get" in stderr.lower():
            console.print("[yellow]iTerm2 is not currently running.[/yellow]")
            console.print("[dim]Open iTerm2 and launch some Claude Code sessions first.[/dim]")
        else:
            console.print(f"[red]Failed to get iTerm2 tabs: {stderr.strip() or e}[/red]")
        return

    # Parse the AppleScript output to find Claude sessions
    # Look for tabs that likely have Claude running (name contains 'claude' or project path)
    console.print("[bold blue]Scanning iTerm2 for Claude Code sessions...[/bold blue]")

    # Get list of windows/tabs via simpler approach
    count_script = '''
    tell application "iTerm"
        set sessionCount to 0
        repeat with w in windows
            repeat with t in tabs of w
                set sessionCount to sessionCount + (count of sessions of t)
            end repeat
        end repeat
        return sessionCount
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", count_script],
            capture_output=True, text=True, check=True
        )
        session_count = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        session_count = 0

    if session_count == 0:
        console.print("[yellow]No iTerm2 sessions found[/yellow]")
        return

    console.print(f"Found [cyan]{session_count}[/cyan] iTerm2 sessions")

    if dry_run:
        console.print("\n[dim]Dry run - would perform:[/dim]")
        if not no_context:
            console.print(f"  1. Send 'write context to docs/PROJECT-CONTEXT.md' to each session")
            console.print(f"  2. Wait {context_wait} seconds for context to be written")
        console.print("  3. Send '/exit' to close Claude")
        console.print("  4. Wait 5 seconds")
        console.print("  5. Close each tab")
        console.print(f"\n[dim]Sessions would be processed in parallel with 2s stagger[/dim]")
        return

    # Confirm with user
    if not click.confirm(f"Shutdown {session_count} sessions?", default=True):
        console.print("[yellow]Cancelled[/yellow]")
        return

    def shutdown_session(window_idx: int, tab_idx: int, session_idx: int, delay: float):
        """Shutdown a single session with the specified delay before starting."""
        time.sleep(delay)

        session_id = f"w{window_idx}t{tab_idx}s{session_idx}"
        console.print(f"  [cyan]Starting shutdown:[/cyan] {session_id}")

        # Build the shutdown script for this session
        if not no_context:
            # Send context command
            send_text_script = f'''
            tell application "iTerm"
                tell window {window_idx}
                    tell tab {tab_idx}
                        tell session {session_idx}
                            write text "write context to docs/PROJECT-CONTEXT.md"
                        end tell
                    end tell
                end tell
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", send_text_script], capture_output=True, check=True)
                console.print(f"    [green]✓[/green] {session_id}: Sent context command")
            except subprocess.CalledProcessError:
                console.print(f"    [yellow]![/yellow] {session_id}: Could not send context command")

            # Wait for context to be written
            time.sleep(context_wait)

        # Send /exit
        exit_script = f'''
        tell application "iTerm"
            tell window {window_idx}
                tell tab {tab_idx}
                    tell session {session_idx}
                        write text "/exit"
                    end tell
                end tell
            end tell
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", exit_script], capture_output=True, check=True)
            console.print(f"    [green]✓[/green] {session_id}: Sent /exit")
        except subprocess.CalledProcessError:
            console.print(f"    [yellow]![/yellow] {session_id}: Could not send /exit")

        # Wait for exit
        time.sleep(5)

        # Close the tab
        close_script = f'''
        tell application "iTerm"
            tell window {window_idx}
                tell tab {tab_idx}
                    close
                end tell
            end tell
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", close_script], capture_output=True, check=True)
            console.print(f"    [green]✓[/green] {session_id}: Closed tab")
        except subprocess.CalledProcessError:
            console.print(f"    [yellow]![/yellow] {session_id}: Could not close tab (may already be closed)")

    # Get window/tab/session structure
    structure_script = '''
    tell application "iTerm"
        set result to ""
        set wIdx to 1
        repeat with w in windows
            set tIdx to 1
            repeat with t in tabs of w
                set sIdx to 1
                repeat with s in sessions of t
                    set result to result & wIdx & "," & tIdx & "," & sIdx & "\\n"
                    set sIdx to sIdx + 1
                end repeat
                set tIdx to tIdx + 1
            end repeat
            set wIdx to wIdx + 1
        end repeat
        return result
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", structure_script],
            capture_output=True, text=True, check=True
        )
        sessions_raw = result.stdout.strip().split('\n')
        sessions = []
        for line in sessions_raw:
            if line.strip():
                parts = line.strip().split(',')
                if len(parts) == 3:
                    sessions.append((int(parts[0]), int(parts[1]), int(parts[2])))
    except (subprocess.CalledProcessError, ValueError) as e:
        console.print(f"[red]Failed to enumerate sessions: {e}[/red]")
        return

    if not sessions:
        console.print("[yellow]No sessions to shutdown[/yellow]")
        return

    console.print(f"\n[bold blue]Shutting down {len(sessions)} sessions...[/bold blue]")

    # Launch threads with 2 second stagger
    threads = []
    for i, (w_idx, t_idx, s_idx) in enumerate(sessions):
        delay = i * 2.0  # 2 second stagger
        t = threading.Thread(target=shutdown_session, args=(w_idx, t_idx, s_idx, delay))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    console.print(f"\n[bold green]Shutdown complete![/bold green]")


@main.group()
def docs():
    """Document generation using headless Claude Code."""
    pass


@docs.command("list")
def docs_list():
    """List available document templates."""
    from .docgen.templates import BUILTIN_TEMPLATES

    table = Table(
        title="Document Templates",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="bold", width=16)
    table.add_column("Name", width=22)
    table.add_column("Output", width=24)
    table.add_column("Budget", width=8)
    table.add_column("Description", min_width=30)

    for t in BUILTIN_TEMPLATES.values():
        table.add_row(
            t.id,
            t.name,
            t.output_path,
            f"${t.max_budget_usd:.2f}",
            t.description,
        )

    console.print(table)


@docs.command("generate")
@click.argument("templates_str")
@click.argument("project_name", required=False)
@click.option("--all", "gen_all", is_flag=True, help="Generate for all projects")
@click.option("--filter", "-f", "filter_str", help="Filter projects: type:client, category:internal")
@click.option("--top", type=int, help="Top N projects by urgency")
@click.option("--parallel", "-p", default=3, help="Max parallel workers")
@click.option("--dry-run", is_flag=True, help="Show what would be generated")
@click.option("--force", is_flag=True, help="Regenerate even if recent")
@click.option("--max-budget", type=float, help="Override per-project budget cap")
@click.option("--output-dir", help="Override output directory")
def docs_generate(
    templates_str: str,
    project_name: Optional[str],
    gen_all: bool,
    filter_str: Optional[str],
    top: Optional[int],
    parallel: int,
    dry_run: bool,
    force: bool,
    max_budget: Optional[float],
    output_dir: Optional[str],
):
    """Generate documents for projects.

    TEMPLATES is a comma-separated list of template IDs (e.g. roadmap,architecture).

    Examples:

        pm docs generate roadmap myproject

        pm docs generate architecture --all

        pm docs generate code-review --filter type:client

        pm docs generate status-report --top 10

        pm docs generate roadmap,architecture myproject
    """
    from .docgen.templates import BUILTIN_TEMPLATES, get_template
    from .docgen.context import build_context
    from .docgen.executor import run_doc_generation, run_batch_generation, DocResult
    from .database.models import DocGeneration

    # Parse template IDs
    template_ids = [t.strip() for t in templates_str.split(",")]
    templates = []
    for tid in template_ids:
        tmpl = get_template(tid)
        if tmpl is None:
            console.print(f"[red]Unknown template: {tid}[/red]")
            console.print(f"Available: {', '.join(BUILTIN_TEMPLATES.keys())}")
            return
        templates.append(tmpl)

    init_db()
    session = get_session()

    # Find target projects
    if project_name:
        project = session.query(Project).filter(
            Project.name.ilike(f"%{project_name}%")
        ).first()
        if not project:
            console.print(f"[red]Project '{project_name}' not found[/red]")
            session.close()
            return
        projects = [project]
    elif gen_all:
        projects = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None)
        ).all()
    elif filter_str:
        query = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None)
        )
        query = apply_project_filter(query, filter_str)
        projects = query.all()
    elif top:
        all_projects = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None)
        ).all()
        all_projects.sort(key=lambda p: p.urgency_score, reverse=True)
        projects = all_projects[:top]
    else:
        console.print("[yellow]Specify a project name, --all, --filter, or --top[/yellow]")
        session.close()
        return

    if not projects:
        console.print("[yellow]No projects found[/yellow]")
        session.close()
        return

    # Check for staleness (skip recent unless --force)
    stale_days = 7
    tasks_to_run = []

    for project in projects:
        ctx = build_context(project)
        for tmpl in templates:
            # Check if recently generated
            if not force:
                recent = session.query(DocGeneration).filter(
                    DocGeneration.project_id == project.id,
                    DocGeneration.template_id == tmpl.id,
                    DocGeneration.status == "success",
                ).order_by(DocGeneration.generated_at.desc()).first()

                if recent and recent.generated_at:
                    from datetime import timedelta
                    age = datetime.now(timezone.utc).replace(tzinfo=None) - recent.generated_at
                    if age < timedelta(days=stale_days):
                        if not dry_run:
                            console.print(
                                f"[dim]Skipping {project.name}/{tmpl.id} "
                                f"(generated {age.days}d ago, use --force)[/dim]"
                            )
                        continue

            # Resolve output file
            out_dir = output_dir or tmpl.output_dir
            filename = tmpl.output_filename
            if "{date}" in filename:
                filename = filename.replace("{date}", datetime.now().strftime("%Y-%m-%d"))

            output_file = Path(project.path) / out_dir / filename
            budget = max_budget if max_budget else tmpl.max_budget_usd

            # Handle weekly-summary specially (multi-project)
            if tmpl.id == "weekly-summary":
                # Build cross-project context as notes
                summary_lines = []
                for p in projects:
                    pct = p.completion_pct or 0
                    summary_lines.append(
                        f"- {p.name} ({p.category}): {pct:.0f}% complete, "
                        f"health {p.health_score}/100, "
                        f"phase: {p.current_phase or 'unknown'}, "
                        f"next: {p.next_action or 'none'}"
                    )
                ctx.notes = "\n".join(summary_lines)

            prompt = tmpl.render(ctx)

            tasks_to_run.append({
                "project_path": Path(project.path),
                "prompt": prompt,
                "output_file": output_file,
                "max_budget_usd": budget,
                "allowed_tools": tmpl.allowed_tools,
                "project_id": project.id,
                "template_id": tmpl.id,
                "output_rel": f"{out_dir}/{filename}",
            })

    if not tasks_to_run:
        console.print("[yellow]Nothing to generate (all docs are up-to-date)[/yellow]")
        session.close()
        return

    # Dry run - show what would be generated
    if dry_run:
        table = Table(title="Documents to Generate (dry run)", box=box.SIMPLE)
        table.add_column("Project")
        table.add_column("Template")
        table.add_column("Output")
        table.add_column("Budget")

        for task in tasks_to_run:
            table.add_row(
                task["project_path"].name,
                task["template_id"],
                task["output_rel"],
                f"${task['max_budget_usd']:.2f}",
            )

        console.print(table)
        console.print(f"\n[dim]{len(tasks_to_run)} documents would be generated[/dim]")
        session.close()
        return

    # Execute generation
    console.print(f"[bold blue]Generating {len(tasks_to_run)} documents "
                  f"(max {parallel} parallel)...[/bold blue]")

    def on_result(result: DocResult):
        if result.status == "success":
            console.print(
                f"  [green]OK[/green] {result.project_name}/{result.template_id} "
                f"({result.duration_secs:.1f}s, {result.file_size_bytes} bytes)"
            )
        elif result.status == "timeout":
            console.print(
                f"  [yellow]TIMEOUT[/yellow] {result.project_name}/{result.template_id} "
                f"({result.error_message})"
            )
        else:
            console.print(
                f"  [red]ERROR[/red] {result.project_name}/{result.template_id}: "
                f"{result.error_message}"
            )

    results = run_batch_generation(
        tasks=[{k: v for k, v in t.items() if k not in ("project_id", "template_id", "output_rel")}
               for t in tasks_to_run],
        max_workers=parallel,
        progress_callback=on_result,
    )

    # Record results in database
    for task, result in zip(tasks_to_run, results):
        doc_gen = DocGeneration(
            project_id=task["project_id"],
            template_id=task["template_id"],
            output_path=task["output_rel"],
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            duration_secs=result.duration_secs,
            status=result.status,
            error_message=result.error_message if result.status != "success" else None,
            file_size_bytes=result.file_size_bytes,
        )
        session.add(doc_gen)

    session.commit()

    # Summary
    success = sum(1 for r in results if r.status == "success")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")

    console.print()
    console.print(Panel(
        f"[green]Success: {success}[/green]  "
        f"[red]Errors: {errors}[/red]  "
        f"[yellow]Timeouts: {timeouts}[/yellow]",
        title="Generation Complete",
        border_style="green" if errors == 0 else "yellow",
    ))

    session.close()


@docs.command("history")
@click.argument("project_name", required=False)
@click.option("--limit", "-n", default=20, help="Limit results")
def docs_history(project_name: Optional[str], limit: int):
    """Show document generation history."""
    from .database.models import DocGeneration

    init_db()
    session = get_session()

    query = session.query(DocGeneration).order_by(DocGeneration.generated_at.desc())

    if project_name:
        # Find matching project
        project = session.query(Project).filter(
            Project.name.ilike(f"%{project_name}%")
        ).first()
        if not project:
            console.print(f"[red]Project '{project_name}' not found[/red]")
            session.close()
            return
        query = query.filter(DocGeneration.project_id == project.id)

    if limit > 0:
        query = query.limit(limit)

    records = query.all()

    if not records:
        console.print("[yellow]No generation history found[/yellow]")
        session.close()
        return

    table = Table(title="Document Generation History", box=box.ROUNDED)
    table.add_column("Date", width=18)
    table.add_column("Project", width=20)
    table.add_column("Template", width=16)
    table.add_column("Status", width=10)
    table.add_column("Duration", width=10)
    table.add_column("Size", width=10)
    table.add_column("Output", min_width=20)

    for rec in records:
        # Get project name
        proj = session.query(Project).filter_by(id=rec.project_id).first()
        proj_name = proj.name if proj else rec.project_id

        # Status styling
        status_styles = {"success": "green", "error": "red", "timeout": "yellow"}
        style = status_styles.get(rec.status, "white")

        # Format date
        date_str = rec.generated_at.strftime("%Y-%m-%d %H:%M") if rec.generated_at else "—"

        # Format duration
        dur_str = f"{rec.duration_secs:.1f}s" if rec.duration_secs else "—"

        # Format size
        if rec.file_size_bytes:
            if rec.file_size_bytes > 1024:
                size_str = f"{rec.file_size_bytes / 1024:.1f}KB"
            else:
                size_str = f"{rec.file_size_bytes}B"
        else:
            size_str = "—"

        table.add_row(
            date_str,
            proj_name,
            rec.template_id,
            f"[{style}]{rec.status}[/{style}]",
            dur_str,
            size_str,
            rec.output_path or "—",
        )

    console.print(table)
    session.close()


@docs.command("status")
@click.argument("project_name", required=False)
@click.option("--stale-days", default=7, help="Days before a doc is considered stale")
def docs_status(project_name: Optional[str], stale_days: int):
    """Show which documents exist and their freshness.

    Displays a grid of projects vs document types with last-generated timestamps.
    """
    from .docgen.templates import BUILTIN_TEMPLATES
    from .database.models import DocGeneration
    from datetime import timedelta

    init_db()
    session = get_session()

    # Get projects
    query = session.query(Project).filter(
        (Project.archived == False) | (Project.archived == None)
    )
    if project_name:
        query = query.filter(Project.name.ilike(f"%{project_name}%"))

    projects = query.order_by(Project.name).all()

    if not projects:
        console.print("[yellow]No projects found[/yellow]")
        session.close()
        return

    # Template IDs (excluding weekly-summary which is cross-project)
    template_ids = [t.id for t in BUILTIN_TEMPLATES.values() if t.id != "weekly-summary"]

    table = Table(title="Document Status", box=box.ROUNDED)
    table.add_column("Project", style="bold", width=20)

    for tid in template_ids:
        table.add_column(tid, width=14)

    stale_threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=stale_days)

    for proj in projects:
        row = [proj.name]

        for tid in template_ids:
            # Check latest generation
            latest = session.query(DocGeneration).filter(
                DocGeneration.project_id == proj.id,
                DocGeneration.template_id == tid,
                DocGeneration.status == "success",
            ).order_by(DocGeneration.generated_at.desc()).first()

            if latest and latest.generated_at:
                age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - latest.generated_at).days
                if latest.generated_at < stale_threshold:
                    row.append(f"[yellow]{age_days}d ago[/yellow]")
                else:
                    row.append(f"[green]{age_days}d ago[/green]")
            else:
                # Check if file exists on disk
                tmpl = BUILTIN_TEMPLATES[tid]
                doc_path = Path(proj.path) / tmpl.output_dir / tmpl.output_filename
                if doc_path.exists():
                    row.append("[dim]exists*[/dim]")
                else:
                    row.append("[dim]—[/dim]")

        table.add_row(*row)

    console.print(table)
    console.print(f"\n[dim]* = file exists but no generation record  |  "
                  f"Stale threshold: {stale_days} days[/dim]")
    session.close()


# ── Agent Orchestration ──────────────────────────────────────────────────────


def _record_agent_run(
    project_id: str,
    assessment,
    run_result,
    status: str,
    started: datetime,
) -> None:
    """Persist an AgentRun record to the database."""
    from .database.models import AgentRun
    try:
        session = get_session()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        total_duration = (now - started).total_seconds()
        run = AgentRun(
            project_id=project_id,
            started_at=started,
            completed_at=now,
            duration_secs=total_duration,
            confidence=assessment.confidence if assessment else None,
            proposed_action=assessment.proposed_action if assessment else None,
            proposed_prompt=assessment.proposed_prompt if assessment else None,
            reasoning=assessment.reasoning if assessment else None,
            risk_level=assessment.risk_level if assessment else None,
            assess_duration_secs=assessment.duration_secs if assessment else None,
            status=status,
            output=run_result.output[:2000] if run_result and run_result.output else None,
            error_message=run_result.error if run_result else None,
            cost_usd=run_result.cost_usd if run_result else None,
        )
        session.add(run)
        session.commit()
        session.close()
    except Exception:
        pass  # Never let DB writes crash the agent


@main.group()
def agent():
    """Agent orchestration: assess, execute, and escalate project work."""
    pass


@agent.command("assess")
@click.argument("project_name")
@click.option("--context", "-c", help="Focus hint for the assessment (e.g. 'fix failing tests')")
@click.option("--timeout", default=120, help="Seconds before assessment times out (default: 120)")
def agent_assess(project_name: str, context: Optional[str], timeout: int):
    """Assess a project and show the proposed next action.

    Runs read-only Claude to understand current state and returns a JSON assessment
    with confidence score and proposed action. Does NOT execute anything.

    Examples:
        pm agent assess myproject
        pm agent assess myproject --context "fix failing tests"
    """
    from .agent.planner import plan_project

    init_db()
    session = get_session()
    project = session.query(Project).filter(
        Project.name.ilike(f"%{project_name}%")
    ).first()
    session.close()

    if not project:
        console.print(f"[red]No project found matching '{project_name}'[/red]")
        return

    console.print(f"[bold blue]Assessing {project.name}...[/bold blue]")
    console.print(f"[dim]{project.path}[/dim]")

    result = plan_project(project.path, project.name, context_hint=context, timeout=timeout)

    # Display result
    color = "green" if result.confidence >= 80 else "yellow" if result.confidence >= 50 else "red"
    console.print(f"\n[bold]Confidence:[/bold] [{color}]{result.confidence}/100[/{color}]")
    console.print(f"[bold]Risk:[/bold] {result.risk_level}")
    console.print(f"[bold]Action:[/bold] {result.proposed_action}")
    console.print(f"\n[bold]Reasoning:[/bold]\n{result.reasoning}")
    console.print(f"\n[bold]Proposed prompt:[/bold]\n[dim]{result.proposed_prompt}[/dim]")

    if result.should_auto_execute:
        console.print(f"\n[green]✓ Would auto-execute (confidence ≥ 80, risk = safe)[/green]")
        console.print(f"[dim]Run: pm agent run {project.name}[/dim]")
    else:
        reasons = []
        if result.confidence < 80:
            reasons.append(f"confidence {result.confidence} < 80")
        if result.risk_level != "safe":
            reasons.append(f"risk = {result.risk_level}")
        if result.error:
            reasons.append(f"error: {result.error}")
        console.print(f"\n[yellow]Would escalate ({', '.join(reasons)})[/yellow]")

    console.print(f"\n[dim]Assessment took {result.duration_secs:.1f}s[/dim]")


@agent.command("run")
@click.argument("project_name")
@click.option("--context", "-c", help="Focus hint for the assessment")
@click.option("--budget", default=1.00, help="Max budget in USD (default: 1.00)")
@click.option("--timeout", default=300, help="Timeout in seconds (default: 300)")
@click.option("--force", is_flag=True, help="Execute even if confidence < 80 or risk is not safe")
@click.option("--dry-run", is_flag=True, help="Assess only, don't execute")
def agent_run(
    project_name: str,
    context: Optional[str],
    budget: float,
    timeout: int,
    force: bool,
    dry_run: bool,
):
    """Assess and optionally execute work on a project.

    Runs a two-phase protocol:
      1. Assess: read-only analysis, confidence score, proposed action
      2. Execute: if confidence >= 80 and risk = safe (or --force)

    Examples:
        pm agent run myproject                # assess then auto-execute if safe
        pm agent run myproject --dry-run      # assess only
        pm agent run myproject --force        # execute regardless of confidence
    """
    from .agent.planner import plan_project
    from .agent.runner import AgentRunner
    from .database.models import AgentRun

    init_db()
    session = get_session()
    project = session.query(Project).filter(
        Project.name.ilike(f"%{project_name}%")
    ).first()
    session.close()

    if not project:
        console.print(f"[red]No project found matching '{project_name}'[/red]")
        return

    started = datetime.now(timezone.utc).replace(tzinfo=None)

    # Phase 1: Assess
    console.print(f"[bold blue]Phase 1: Assessing {project.name}...[/bold blue]")
    assessment = plan_project(project.path, project.name, context_hint=context)

    color = "green" if assessment.confidence >= 80 else "yellow" if assessment.confidence >= 50 else "red"
    console.print(f"  Confidence: [{color}]{assessment.confidence}/100[/{color}]  "
                  f"Risk: {assessment.risk_level}")
    console.print(f"  Action: {assessment.proposed_action}")

    if dry_run:
        console.print("\n[dim]--dry-run: skipping execution[/dim]")
        _record_agent_run(project.id, assessment, None, "dry_run", started)
        return

    # Phase 2: Execute or escalate
    will_execute = assessment.should_auto_execute or force
    if not will_execute:
        reasons = []
        if assessment.confidence < 80:
            reasons.append(f"confidence {assessment.confidence} < 80")
        if assessment.risk_level != "safe":
            reasons.append(f"risk = {assessment.risk_level}")
        console.print(f"\n[yellow]Escalating ({', '.join(reasons)})[/yellow]")
        console.print(f"[dim]Use --force to execute anyway[/dim]")
        _record_agent_run(project.id, assessment, None, "escalated", started)
        return

    console.print(f"\n[bold blue]Phase 2: Executing...[/bold blue]")
    console.print(f"[dim]{assessment.proposed_prompt[:200]}[/dim]")

    runner = AgentRunner(budget_usd=budget, timeout_secs=timeout)
    run_result = runner.run(
        project_path=project.path,
        project_name=project.name,
        prompt=assessment.proposed_prompt,
        assessment=assessment,
    )

    _record_agent_run(project.id, assessment, run_result, run_result.status, started)

    if run_result.status == "success":
        console.print(f"\n[green]✓ Execution successful ({run_result.duration_secs:.1f}s)[/green]")
        if run_result.output:
            preview = run_result.output[:500]
            if len(run_result.output) > 500:
                preview += f"\n[dim]... ({len(run_result.output)} chars total)[/dim]"
            console.print(f"\n{preview}")
    else:
        console.print(f"\n[red]✗ Execution {run_result.status}[/red]")
        if run_result.error:
            console.print(f"[dim]{run_result.error}[/dim]")


@agent.command("batch")
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, priority:1")
@click.option("--limit", "-n", default=5, help="Max projects to process (default: 5)")
@click.option("--budget", default=1.00, help="Budget per project in USD (default: 1.00)")
@click.option("--workers", default=3, help="Parallel workers (default: 3)")
@click.option("--context", "-c", help="Focus hint for all assessments")
@click.option("--dry-run", is_flag=True, help="Assess only, don't execute")
def agent_batch(
    filter_str: Optional[str],
    limit: int,
    budget: float,
    workers: int,
    context: Optional[str],
    dry_run: bool,
):
    """Run assess/execute/escalate across multiple projects in parallel.

    Processes up to --limit projects concurrently using --workers threads.
    Projects are selected by urgency score (most urgent first).

    Examples:
        pm agent batch --limit 10 --dry-run     # assess top 10 by urgency
        pm agent batch --filter type:client      # clients only
        pm agent batch --budget 0.50             # conservative budget
    """
    from .agent.coordinator import AgentCoordinator

    init_db()
    session = get_session()

    query = session.query(Project).filter(Project.archived == False)
    query = apply_project_filter(query, filter_str)
    projects = query.all()
    session.close()

    # Sort by urgency, take top N
    projects_sorted = sorted(projects, key=lambda p: p.urgency_score, reverse=True)[:limit]

    if not projects_sorted:
        console.print("[yellow]No projects found.[/yellow]")
        return

    console.print(f"[bold blue]Agent batch: {len(projects_sorted)} projects "
                  f"({'dry run' if dry_run else 'assess + execute'})[/bold blue]")

    project_dicts = [{"name": p.name, "path": p.path} for p in projects_sorted]

    coordinator = AgentCoordinator(
        max_workers=workers,
        budget_per_project=budget,
        dry_run=dry_run,
    )

    coord_result = coordinator.run(project_dicts, context_hint=context)

    # Display summary table
    table = Table("Project", "Confidence", "Risk", "Action", "Status")
    for assessment in coord_result.assessments:
        # Find matching execution
        exec_result = next(
            (r for r in coord_result.executions if r.project_name == assessment.project_name),
            None
        )
        status = "dry_run" if dry_run else (
            exec_result.status if exec_result else
            "escalated" if not assessment.should_auto_execute else "queued"
        )
        color = "green" if assessment.confidence >= 80 else "yellow" if assessment.confidence >= 50 else "red"
        table.add_row(
            assessment.project_name,
            f"[{color}]{assessment.confidence}[/{color}]",
            assessment.risk_level,
            assessment.proposed_action[:60],
            status,
        )

    console.print(table)
    console.print(f"\n[dim]{coord_result.summary()}[/dim]")


@agent.command("memory")
@click.argument("project_name")
@click.option("--clear", is_flag=True, help="Delete the AGENT-CONTEXT.md file")
def agent_memory(project_name: str, clear: bool):
    """View or clear the agent memory for a project.

    The agent memory (docs/AGENT-CONTEXT.md) records what agents have done
    and learned about each project, preventing duplicate work.
    """
    from .agent.memory import read_memory, clear_memory as _clear_memory

    session = get_session()
    project = session.query(Project).filter(
        Project.name.ilike(f"%{project_name}%")
    ).first()
    session.close()

    if not project:
        console.print(f"[red]No project found matching '{project_name}'[/red]")
        raise SystemExit(1)

    project_path = Path(project.path)
    mem_file = project_path / "docs" / "AGENT-CONTEXT.md"

    if clear:
        if _clear_memory(project_path):
            console.print(f"[green]Cleared agent memory for {project.name}[/green]")
        else:
            console.print(f"[red]Failed to clear memory for {project.name}[/red]")
        return

    mem = read_memory(project_path)

    if mem.is_empty() and not mem.last_run:
        console.print(f"[dim]No agent memory for {project.name} ({mem_file})[/dim]")
        return

    console.print(f"\n[bold]Agent Memory: {project.name}[/bold]")
    console.print(f"[dim]{mem_file}[/dim]\n")

    if mem.last_run:
        console.print(f"Last run: [cyan]{mem.last_run.strftime('%Y-%m-%d %H:%M')}[/cyan]  "
                      f"Total runs: {mem.runs}  Cost: ${mem.total_cost_usd:.2f}")
        console.print()

    if mem.done:
        console.print("[bold]What I've Done[/bold]")
        for item in mem.done[-15:]:
            console.print(f"  [green]•[/green] {item}")
        console.print()

    if mem.learned:
        console.print("[bold]What I've Learned[/bold]")
        for item in mem.learned:
            console.print(f"  [blue]•[/blue] {item}")
        console.print()

    if mem.dont_repeat:
        console.print("[bold]Don't Repeat[/bold]")
        for item in mem.dont_repeat:
            console.print(f"  [yellow]•[/yellow] {item}")
        console.print()


@agent.command("costs")
@click.option("--days", default=30, help="Lookback window in days (default: 30)")
@click.option("--limit", "-n", default=20, help="Max projects to show (default: 20)")
def agent_costs(days: int, limit: int):
    """Show per-project agent run costs and activity.

    Reads the agent_runs table and summarises spend, run counts, and
    success rates per project over the lookback window.
    """
    from .database.models import AgentRun
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    session = get_session()

    # Aggregate by project
    rows = (
        session.query(
            Project.name,
            Project.client_name,
            func.count(AgentRun.id).label("runs"),
            func.sum(AgentRun.cost_usd).label("total_cost"),
            func.avg(AgentRun.duration_secs).label("avg_duration"),
            func.max(AgentRun.started_at).label("last_run"),
        )
        .join(AgentRun, AgentRun.project_id == Project.id)
        .filter(AgentRun.started_at >= cutoff)
        .group_by(Project.id)
        .order_by(func.sum(AgentRun.cost_usd).desc())
        .limit(limit)
        .all()
    )
    session.close()

    if not rows:
        console.print(f"[dim]No agent runs in the last {days} days.[/dim]")
        return

    table = Table(
        "Project", "Client", "Runs", "Total Cost", "Avg Duration", "Last Run",
        title=f"Agent Costs — Last {days} days",
    )
    total_cost = 0.0
    total_runs = 0
    for row in rows:
        cost = row.total_cost or 0.0
        total_cost += cost
        total_runs += row.runs
        last_run = row.last_run.strftime("%Y-%m-%d") if row.last_run else "—"
        avg_dur = f"{row.avg_duration:.0f}s" if row.avg_duration else "—"
        table.add_row(
            row.name,
            row.client_name or "",
            str(row.runs),
            f"${cost:.3f}",
            avg_dur,
            last_run,
        )

    console.print(table)
    console.print(
        f"\n[bold]Total:[/bold] {total_runs} runs, "
        f"[bold]${total_cost:.3f}[/bold] over {days} days"
    )

    # Budget alert: warn if weekly spend > $10
    weekly_cost = total_cost * (7 / days) if days > 7 else total_cost
    if weekly_cost > 10.0:
        console.print(
            f"\n[yellow]⚠ Estimated weekly spend: ${weekly_cost:.2f} — "
            f"consider reviewing agent batch frequency[/yellow]"
        )


# ── Intelligent Triage ───────────────────────────────────────────────────────

_TRIAGE_SYSTEM_PROMPT = """\
You are an intelligent project manager performing decision triage.
A project has a pending decision that needs resolution.
Your job is to:
1. Read the project files to understand the decision context
2. Analyze the options available
3. Recommend the best option with clear reasoning
4. Estimate confidence in your recommendation

Output ONLY valid JSON in this exact format:
{
  "decision_summary": "<one sentence: what decision needs to be made>",
  "recommended_option": "<Option A|Option B|other label>",
  "recommendation": "<2-3 sentences: why this is the right choice>",
  "confidence": <integer 0-100>,
  "caveats": "<any important conditions or risks — empty string if none>"
}

Be direct. Pick one option. Do not hedge with "it depends" unless the codebase truly has blocking unknowns.
"""


@main.command()
@click.option("--limit", "-n", default=10, help="Max projects to triage (default: 10)")
@click.option("--imessage", "-i", is_flag=True, help="Send recommendations via iMessage")
@click.option("--dry-run", is_flag=True, help="Show which projects would be triaged without running")
@click.option("--timeout", default=120, help="Seconds per assessment (default: 120)")
def triage(limit: int, imessage: bool, dry_run: bool, timeout: int):
    """Assess projects with pending decisions and recommend an option.

    Finds all projects where has_pending_decision=True, runs a read-only
    Claude assessment for each, and outputs a recommendation. Optionally
    sends recommendations via iMessage.

    Example:
        pm triage              # Show recommendations in terminal
        pm triage --imessage   # Send each recommendation via iMessage
    """
    import json as _json
    import re as _re

    init_db()
    session = get_session()
    projects = (
        session.query(Project)
        .filter(
            Project.has_pending_decision == True,
            Project.archived == False,
        )
        .order_by(Project.priority.asc(), Project.name.asc())
        .limit(limit)
        .all()
    )
    session.close()

    if not projects:
        console.print("[dim]No projects with pending decisions.[/dim]")
        return

    console.print(f"[bold]Pending Decisions: {len(projects)} project(s)[/bold]\n")

    if dry_run:
        for p in projects:
            console.print(f"  [cyan]•[/cyan] {p.name}  [dim]{p.path}[/dim]")
        return

    for project in projects:
        console.print(f"[bold blue]Triaging: {project.name}[/bold blue]")

        user_prompt = (
            f"This project has a pending decision that needs resolution.\n"
            f"Project: {project.name}\n"
            f"Path: {project.path}\n\n"
            f"Read CLAUDE.md, TODO.md, PROGRESS.md to find the pending decision(s).\n"
            f"Return ONLY the JSON recommendation."
        )

        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--max-budget-usd", "0.25",
            "--allowedTools", "Read,Glob,Grep",
            "--system-prompt", _TRIAGE_SYSTEM_PROMPT,
            "-p", user_prompt,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout, cwd=project.path,
            )
            raw = result.stdout.strip()

            # Extract JSON
            json_match = _re.search(r'\{.*?"confidence".*?\}', raw, _re.DOTALL)
            if json_match:
                data = _json.loads(json_match.group(0))
                decision = data.get("decision_summary", "Unknown decision")
                option = data.get("recommended_option", "?")
                reasoning = data.get("recommendation", "")
                confidence = data.get("confidence", 0)
                caveats = data.get("caveats", "")

                color = "green" if confidence >= 70 else "yellow" if confidence >= 50 else "red"
                console.print(f"  Decision: [bold]{decision}[/bold]")
                console.print(f"  Recommend: [bold]{option}[/bold]  "
                              f"Confidence: [{color}]{confidence}%[/{color}]")
                console.print(f"  Reasoning: {reasoning}")
                if caveats:
                    console.print(f"  [dim]Caveats: {caveats}[/dim]")

                if imessage:
                    msg = (
                        f"🔀 Decision Needed: {project.name}\n"
                        f"Decision: {decision}\n"
                        f"Recommendation: {option} ({confidence}% confidence)\n"
                        f"{reasoning}"
                    )
                    if caveats:
                        msg += f"\nCaveats: {caveats}"
                    try:
                        _send_imessage_triage(msg)
                        console.print("  [dim]→ Sent via iMessage[/dim]")
                    except Exception as e:
                        console.print(f"  [yellow]iMessage failed: {e}[/yellow]")
            else:
                console.print(f"  [yellow]Could not parse recommendation[/yellow]")
                console.print(f"  [dim]{raw[:200]}[/dim]")

        except subprocess.TimeoutExpired:
            console.print(f"  [red]Timed out after {timeout}s[/red]")
        except FileNotFoundError:
            console.print(f"  [red]claude CLI not found[/red]")
            break
        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")

        console.print()


def _send_imessage_triage(message: str, phone: str = "+12064962555") -> None:
    """Send a triage recommendation via iMessage."""
    escaped_msg = _escape_applescript(message)
    escaped_phone = _escape_applescript(phone)
    script = f'''tell application "Messages"
    set targetBuddy to "{escaped_phone}"
    set targetService to (1st account whose service type = iMessage)
    set targetBuddy to participant targetBuddy of targetService
    send "{escaped_msg}" to targetBuddy
end tell'''
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


# ── Scheduling (launchd) ─────────────────────────────────────────────────────

_SCHEDULE_LABEL = "com.pm.agent-batch"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_SCHEDULE_LABEL}.plist"
_PM_BIN = Path(__file__).parent.parent / "venv" / "bin" / "pm"
_LOG_DIR = Path(__file__).parent.parent / "logs"


def _build_plist(hour: int, limit: int, budget: float, workers: int, dry_run: bool) -> str:
    """Generate the launchd plist XML for nightly agent batch."""
    dry_flag = "        <string>--dry-run</string>\n" if dry_run else ""
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_SCHEDULE_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{_PM_BIN}</string>
        <string>agent</string>
        <string>batch</string>
        <string>--limit</string>
        <string>{limit}</string>
        <string>--budget</string>
        <string>{budget}</string>
        <string>--workers</string>
        <string>{workers}</string>
{dry_flag}    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>{_LOG_DIR}/agent-batch.log</string>

    <key>StandardErrorPath</key>
    <string>{_LOG_DIR}/agent-batch-error.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


@main.group()
def schedule():
    """Manage scheduled agent batch runs (macOS launchd)."""
    pass


@schedule.command("install")
@click.option("--hour", default=2, help="Hour to run (24h, default: 2am)")
@click.option("--limit", default=5, help="Max projects per run (default: 5)")
@click.option("--budget", default=1.00, help="Budget per project USD (default: 1.00)")
@click.option("--workers", default=3, help="Parallel workers (default: 3)")
@click.option("--dry-run-agent", is_flag=True, help="Schedule in dry-run mode (assess only)")
def schedule_install(hour: int, limit: int, budget: float, workers: int, dry_run_agent: bool):
    """Install nightly agent batch launchd job."""
    import platform
    if platform.system() != "Darwin":
        console.print("[red]schedule only supported on macOS (launchd)[/red]")
        raise SystemExit(1)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    plist_content = _build_plist(hour, limit, budget, workers, dry_run_agent)

    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(plist_content)

    # Load into launchd
    try:
        subprocess.run(
            ["launchctl", "load", str(_PLIST_PATH)],
            check=True, capture_output=True,
        )
        console.print(f"[green]Installed and loaded: {_SCHEDULE_LABEL}[/green]")
        console.print(f"  Runs: daily at {hour:02d}:00, up to {limit} projects, ${budget}/project")
        console.print(f"  Logs: {_LOG_DIR}/agent-batch.log")
        console.print(f"  Plist: {_PLIST_PATH}")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Plist written but launchctl load failed:[/yellow] {e.stderr.decode()}")
        console.print(f"  Run manually: launchctl load {_PLIST_PATH}")


@schedule.command("uninstall")
def schedule_uninstall():
    """Remove nightly agent batch launchd job."""
    import platform
    if platform.system() != "Darwin":
        console.print("[red]schedule only supported on macOS (launchd)[/red]")
        raise SystemExit(1)

    if not _PLIST_PATH.exists():
        console.print(f"[dim]Not installed ({_PLIST_PATH})[/dim]")
        return

    try:
        subprocess.run(
            ["launchctl", "unload", str(_PLIST_PATH)],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        pass  # May not be loaded; proceed to delete

    _PLIST_PATH.unlink(missing_ok=True)
    console.print(f"[green]Uninstalled: {_SCHEDULE_LABEL}[/green]")


@schedule.command("status")
def schedule_status():
    """Show current schedule status."""
    if not _PLIST_PATH.exists():
        console.print(f"[dim]Not installed. Run: pm schedule install[/dim]")
        return

    console.print(f"[bold]Schedule: {_SCHEDULE_LABEL}[/bold]")
    console.print(f"  Plist: {_PLIST_PATH}")

    # Check if loaded in launchd
    try:
        result = subprocess.run(
            ["launchctl", "list", _SCHEDULE_LABEL],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print("  Status: [green]loaded[/green]")
        else:
            console.print("  Status: [yellow]plist exists but not loaded[/yellow]")
            console.print(f"  Load with: launchctl load {_PLIST_PATH}")
    except FileNotFoundError:
        console.print("  [dim](launchctl not available)[/dim]")

    # Show log tail if exists
    log_file = _LOG_DIR / "agent-batch.log"
    if log_file.exists():
        lines = log_file.read_text().splitlines()
        if lines:
            console.print(f"\n[dim]Last log entry ({log_file}):[/dim]")
            console.print(f"  {lines[-1]}")


# ── Garbage Collection ───────────────────────────────────────────────────────


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting")
def gc(dry_run: bool):
    """Remove DB records for projects that no longer exist on disk."""
    session = get_session()
    projects = session.query(Project).all()

    removed = []
    for project in projects:
        if not Path(project.path).exists():
            removed.append(project)

    if not removed:
        console.print("[dim]No stale records found.[/dim]")
        session.close()
        return

    table = Table("Name", "Path", "Last Scanned")
    for p in removed:
        scanned = p.last_scanned.strftime("%Y-%m-%d") if p.last_scanned else "never"
        table.add_row(p.name, p.path, scanned)

    console.print(table)

    if dry_run:
        console.print(f"\n[yellow]Dry run: {len(removed)} record(s) would be removed.[/yellow]")
    else:
        for p in removed:
            session.delete(p)
        session.commit()
        console.print(f"\n[green]Removed {len(removed)} stale record(s).[/green]")

    session.close()


if __name__ == "__main__":
    main()
