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
from .metadata import read_pm_status, sync_to_file, PM_STATUS_FILENAME


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

            # Open in new terminal
            cmd = f"""osascript -e 'tell application "Terminal" to do script "{prompt.command}"'"""
            subprocess.run(cmd, shell=True)
            console.print(f"[green]✓[/green] Launched terminal for {proj.name}")

    session.close()


@main.command()
@click.argument("project_names", nargs=-1)
@click.option("--filter", "-f", "filter_str", help="Filter projects: type:client, type:internal")
@click.option("--parallel", "-p", default=1, help="Number of projects to launch in parallel")
@click.option("--mode", "-m", default="context", type=click.Choice(["simple", "context", "decision"]))
@click.option("--dry-run", is_flag=True, help="Show what would be launched without executing")
@click.option("--iterm", is_flag=True, default=True, help="Use iTerm2 (default: true)")
@click.option("--tmux", is_flag=True, help="Use tmux instead of separate windows")
def launch(
    project_names: tuple,
    filter_str: Optional[str],
    parallel: int,
    mode: str,
    dry_run: bool,
    iterm: bool,
    tmux: bool,
):
    """Launch Claude Code for one or more projects.

    Examples:
        pm launch remoteC                    # Launch single project
        pm launch remoteC anterix github-spec # Launch multiple
        pm launch --filter type:client -p 3  # Launch clients in parallel
        pm launch --filter type:client --tmux # Use tmux session
    """
    init_db()
    session = get_session()
    parser = ProgressParser()
    generator = ContinuePromptGenerator()
    prompt_mode = PromptMode(mode)

    # Find projects
    if project_names:
        projects = []
        for name in project_names:
            proj = session.query(Project).filter(
                Project.name.ilike(f"%{name}%")
            ).first()
            if proj:
                projects.append(proj)
            else:
                console.print(f"[yellow]Warning:[/yellow] Project not found: {name}")
    elif filter_str:
        query = session.query(Project)
        if filter_str.startswith("type:"):
            category = filter_str.split(":")[1]
            query = query.filter(Project.category == category)
            projects = query.all()
        elif filter_str.startswith("health:"):
            threshold = filter_str.split(":")[1]
            all_projects = query.all()
            if threshold == "low":
                projects = [p for p in all_projects if p.health_score < 40]
            elif threshold == "attention":
                projects = [p for p in all_projects if p.health_score < 70]
            else:
                projects = all_projects
        else:
            projects = query.all()
    else:
        console.print("[yellow]Specify project name(s) or --filter[/yellow]")
        console.print("Examples:")
        console.print("  pm launch remoteC")
        console.print("  pm launch --filter type:client")
        console.print("  pm launch --filter health:low")
        session.close()
        return

    if not projects:
        console.print("[red]No projects found[/red]")
        session.close()
        return

    console.print(f"[bold blue]Launching {len(projects)} project(s)[/bold blue]")

    # Show what will be launched
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Health")
    table.add_column("Phase")

    for p in projects:
        health = p.health_score
        health_color = "green" if health >= 70 else ("yellow" if health >= 40 else "red")
        table.add_row(
            p.name,
            f"[{health_color}]{health}[/{health_color}]",
            p.current_phase or p.current_status or "—",
        )

    console.print(table)

    if dry_run:
        console.print("\n[dim]Dry run - no terminals launched[/dim]")
        session.close()
        return

    # Check for claudecoderun
    claudecoderun_path = Path.home() / "dev2" / "claudecoderun"
    use_claudecoderun = claudecoderun_path.exists()

    # Generate context files and launch
    temp_dir = Path("/tmp/pm_launch")
    temp_dir.mkdir(exist_ok=True)

    launched = 0
    for i, proj in enumerate(projects):
        project_path = Path(proj.path)
        progress = parser.parse_project(project_path)
        prompt = generator.generate(project_path, proj.name, progress, prompt_mode)

        # Create temporary coderun.md with smart context
        if prompt.prompt_text:
            coderun_file = temp_dir / f"{proj.name}_coderun.md"
            coderun_file.write_text(prompt.prompt_text)

        if tmux:
            # Use tmux session
            session_name = f"claude-{proj.name}"
            cmd = f"tmux new-session -d -s '{session_name}' -c '{project_path}' 'claude --resume || claude'"
            if not dry_run:
                result = subprocess.run(cmd, shell=True, capture_output=True)
                if result.returncode == 0:
                    console.print(f"[green]✓[/green] Launched tmux session: {session_name}")
                    launched += 1
                else:
                    console.print(f"[red]✗[/red] Failed to launch {proj.name}")
        elif use_claudecoderun and len(projects) > 1:
            # Use claudecoderun for batch launching
            if i == 0:  # Only launch once with all paths
                project_paths = [p.path for p in projects]
                # Create a temp file listing all projects
                batch_file = temp_dir / "batch_projects.txt"
                batch_file.write_text("\n".join(project_paths))

                run_script = claudecoderun_path / "run.sh"
                if run_script.exists():
                    cmd_parts = [str(run_script)]
                    cmd_parts.extend(project_paths)
                    if parallel > 1:
                        cmd_parts.extend(["--parallel", "--max-parallel", str(parallel)])
                    cmd_parts.append("--delay=2")

                    console.print(f"\n[dim]Calling claudecoderun with {len(projects)} projects[/dim]")
                    subprocess.Popen(cmd_parts, cwd=claudecoderun_path)
                    launched = len(projects)
                break
        else:
            # Use iTerm2 directly via AppleScript
            script_path = Path(__file__).parent.parent / "scripts" / "claude-launch.sh"
            if script_path.exists():
                subprocess.Popen([str(script_path), proj.name])
                console.print(f"[green]✓[/green] Launched iTerm2 for {proj.name}")
                launched += 1
            else:
                # Fallback to basic Terminal
                cmd = f'''osascript -e 'tell application "Terminal" to do script "cd {project_path} && claude --resume || claude"' '''
                subprocess.run(cmd, shell=True)
                console.print(f"[green]✓[/green] Launched Terminal for {proj.name}")
                launched += 1

        # Delay between launches if parallel is 1
        if parallel == 1 and i < len(projects) - 1:
            import time
            time.sleep(1)

    console.print(f"\n[bold green]Launched {launched} project(s)[/bold green]")
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

    # Apply filters
    if filter_str:
        if filter_str.startswith("type:"):
            category = filter_str.split(":")[1]
            query = query.filter(Project.category == category)

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
            days = (datetime.utcnow() - p.last_activity).days
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
@click.option("--filter", "-f", "filter_str", help="Filter: type:client, priority:1, overdue, tagged:foo")
@click.option("--limit", "-n", default=20, help="Limit results")
def urgent(filter_str: Optional[str], limit: int):
    """Show projects by urgency (deadlines + priority)."""
    init_db()
    session = get_session()

    query = session.query(Project).filter(Project.archived == False)

    # Apply filters
    if filter_str:
        if filter_str.startswith("type:"):
            category = filter_str.split(":")[1]
            query = query.filter(Project.category == category)
        elif filter_str.startswith("priority:"):
            p = int(filter_str.split(":")[1])
            query = query.filter(Project.priority == p)
        elif filter_str == "overdue":
            query = query.filter(Project.deadline < datetime.utcnow())
        elif filter_str.startswith("tagged:"):
            tag = filter_str.split(":")[1]
            query = query.filter(Project.tags.ilike(f"%{tag}%"))

    projects = query.all()

    # Sort by urgency
    projects_sorted = sorted(projects, key=lambda p: p.urgency_score, reverse=True)
    if limit > 0:
        projects_sorted = projects_sorted[:limit]

    if not projects_sorted:
        console.print("[yellow]No urgent projects found[/yellow]")
        session.close()
        return

    table = Table(title="Urgent Projects (by deadline & priority)", box=box.ROUNDED)
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


@main.command()
@click.argument("target", default="10")
@click.option("--dirty-only", "-d", is_flag=True, help="Only projects with uncommitted changes")
@click.option("--dry-run", is_flag=True, help="Show what would be launched without launching")
def launch(target: str, dirty_only: bool, dry_run: bool):
    """Launch Claude Code for projects.

    TARGET can be:
    - A number: Launch the N most recently modified projects
    - A project name: Launch that specific project

    Opens iTerm2 tabs with Claude Code using --dangerously-skip-permissions --continue.

    Examples:
        pm launch              # Launch top 10 most recent
        pm launch 5            # Launch top 5 most recent
        pm launch myproject    # Launch specific project by name
        pm launch -d           # Only projects with uncommitted changes
    """
    init_db()
    session = get_session()

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
        console.print("\n[dim]Dry run - no terminals opened[/dim]")
        session.close()
        return

    # Launch each project in iTerm2
    console.print(f"\n[bold blue]Opening {len(projects)} iTerm2 tabs...[/bold blue]")

    for i, p in enumerate(projects):
        # AppleScript to open new iTerm tab and run claude
        script = f'''
        tell application "iTerm"
            activate
            tell current window
                create tab with default profile
                tell current session
                    write text "cd '{p.path}' && transcript && claude --dangerously-skip-permissions --continue"
                end tell
            end tell
        end tell
        '''

        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            console.print(f"  [green]✓[/green] {p.name}")
        except subprocess.CalledProcessError as e:
            console.print(f"  [red]✗[/red] {p.name}: {e}")

        # Small delay to prevent overwhelming iTerm
        if i < len(projects) - 1:
            import time
            time.sleep(0.3)

    console.print(f"\n[bold green]Launched {len(projects)} Claude Code sessions[/bold green]")
    session.close()


@main.command()
@click.option("--no-context", is_flag=True, help="Skip writing context docs before shutdown")
@click.option("--dry-run", is_flag=True, help="Show what would be done without executing")
@click.option("--context-wait", default=60, help="Seconds to wait after context command (default: 60)")
def shutdown(no_context: bool, dry_run: bool, context_wait: int):
    """Gracefully shutdown all Claude Code sessions in iTerm2.

    For each iTerm2 tab:
    1. Send 'write context to docs/PROJECT-CONTEXT.md' (unless --no-context)
    2. Wait for context to be written (default 60s)
    3. Send '/exit' to close Claude
    4. Wait 5 seconds
    5. Close the tab

    Sessions are processed in parallel with 2 second stagger.

    Examples:
        pm shutdown              # Graceful shutdown with context save
        pm shutdown --no-context # Quick shutdown, skip context
        pm shutdown --dry-run    # Preview what would happen
    """
    import threading
    import time

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
        console.print(f"[red]Failed to get iTerm2 tabs: {e}[/red]")
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


if __name__ == "__main__":
    main()
