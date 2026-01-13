"""CLI interface for project manager."""

import json
import subprocess
from pathlib import Path
from datetime import datetime
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


console = Console()


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
            proj.last_scanned = datetime.utcnow()

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
            proj.has_todo = proj_info.has_todo
            proj.has_progress = proj_info.has_progress
            proj.progress_files = json.dumps(proj_info.progress_files)

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
@click.option("--limit", "-n", default=50, help="Limit results")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(filter_str: Optional[str], sort: str, limit: int, as_json: bool):
    """Show project status summary."""
    init_db()
    session = get_session()

    # Build query
    query = session.query(Project)

    # Apply filters
    if filter_str:
        if filter_str.startswith("type:"):
            category = filter_str.split(":")[1]
            query = query.filter(Project.category == category)
        elif filter_str.startswith("status:"):
            status = filter_str.split(":")[1]
            if status == "active":
                query = query.filter(Project.completion_pct < 100)
            elif status == "complete":
                query = query.filter(Project.completion_pct >= 100)

    # Apply sort
    if sort == "completion":
        query = query.order_by(Project.completion_pct.desc().nullslast())
    elif sort == "activity":
        query = query.order_by(Project.last_activity.desc().nullslast())
    else:
        query = query.order_by(Project.name)

    projects = query.limit(limit).all()

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
    )

    table.add_column("Project", style="bold")
    table.add_column("Type", width=8)
    table.add_column("Progress", width=12)
    table.add_column("Phase/Status", width=25)
    table.add_column("Next Action", width=30)
    table.add_column("Flags", width=10)

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

            # Open in new terminal
            cmd = f"""osascript -e 'tell application "Terminal" to do script "{prompt.command}"'"""
            subprocess.run(cmd, shell=True)
            console.print(f"[green]✓[/green] Launched terminal for {proj.name}")

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


if __name__ == "__main__":
    main()
