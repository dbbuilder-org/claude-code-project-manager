"""Streamlit dashboard for project manager - Optimized version."""

import sys
import subprocess
import json
import time
import os
import re
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, timezone

from pm.database.models import init_db, get_session, Project, DocGeneration, ScanHistory
from pm.metadata import sync_to_file, sync_project_to_file, PM_STATUS_FILENAME, ProjectMetadata
from pm.digest import week_to_date_range, digest_by_project, digest_by_day
from pm.terminal import (
    launch_single as terminal_launch_single,
    launch_batch as terminal_launch_batch,
    build_command as terminal_build_command,
)

def _utcnow() -> datetime:
    """Naive UTC datetime compatible with SQLite-stored naive datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _bump_cache():
    """Invalidate the load_projects cache by incrementing the version key."""
    st.session_state.cache_version = st.session_state.get("cache_version", 0) + 1


# Page config - must be first
st.set_page_config(
    page_title="Project Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Minimal CSS
st.markdown("""
<style>
    .stExpander { border: 1px solid #ddd; border-radius: 4px; margin-bottom: 4px; }
    .commit-msg { color: #666; font-size: 0.85em; }
</style>
""", unsafe_allow_html=True)

# Initialize
init_db()

# Session state
if "selected" not in st.session_state:
    st.session_state.selected = set()
if "page" not in st.session_state:
    st.session_state.page = 0
if "last_expanded_id" not in st.session_state:
    st.session_state.last_expanded_id = None
if "cache_version" not in st.session_state:
    st.session_state.cache_version = 0
if "_prev_filters" not in st.session_state:
    st.session_state._prev_filters = {}


# ── Data Loading ────────────────────────────────────────────────────────────


@st.cache_data(ttl=120)
def load_projects(_cache_version: int = 0):
    """Load all projects from database with caching."""
    session = get_session()
    try:
        projects = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None)
        ).all()

        data = []
        for p in projects:
            days_inactive = None
            if p.last_activity:
                days_inactive = (_utcnow() - p.last_activity).days

            # Truncate commit message
            commit_msg = p.last_commit_msg or ""
            if len(commit_msg) > 60:
                commit_msg = commit_msg[:57] + "..."

            data.append({
                "name": p.name,
                "path": p.path,
                "id": p.id,
                "category": p.category or "internal",
                "type": p.project_type or "unknown",
                "completion": p.completion_pct or 0,
                "health": p.health_score,
                "urgency": p.urgency_score,
                "next_action": p.next_action or "",
                "has_decision": p.has_pending_decision or False,
                "git_dirty": p.git_dirty or False,
                "last_commit": p.last_commit_date,
                "commit_msg": commit_msg,
                "days_inactive": days_inactive,
                "priority": p.priority or 3,
                "priority_label": p.priority_label,
                "deadline": p.deadline,
                "is_overdue": p.is_overdue,
                "days_to_deadline": p.days_until_deadline,
                "notes": p.notes or "",
                "client_name": p.client_name or "",
                "tags": p.tags_list,
                "target_date": p.target_date,
                "budget_hours": p.budget_hours,
                "hours_logged": p.hours_logged or 0.0,
            })
        return pd.DataFrame(data)
    finally:
        session.close()


# ── Helpers: iTerm2 / Launch ────────────────────────────────────────────────


def launch_claude(path: str, name: str):
    """Launch Claude Code in a terminal, using iTerm2 if available."""
    cmd = terminal_build_command(path)
    terminal_launch_single(path, name, cmd)


def launch_batch(paths_names: list):
    """Launch multiple projects in terminals, using iTerm2 if available."""
    if not paths_names:
        return
    projects = [
        (path, name, terminal_build_command(path))
        for path, name in paths_names
    ]
    terminal_launch_batch(projects)


# ── Helpers: DB Write + Sync ────────────────────────────────────────────────


def _sync_project_to_file(project: Project):
    """Sync all project metadata to PM-STATUS.md."""
    sync_project_to_file(project)


def _save_tags(project_id: str, project_path: str, new_tags: list[str]):
    """Save tags for a project to DB and PM-STATUS.md."""
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.tags = json.dumps(new_tags)
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _save_metadata(project_id: str, priority: int, deadline: date | None,
                   target_date: date | None, notes: str,
                   budget_hours: float | None = None, hours_logged: float | None = None):
    """Save priority, deadline, target date, notes, and hours to DB and PM-STATUS.md."""
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.priority = priority
            project.deadline = datetime.combine(deadline, datetime.min.time()) if deadline else None
            project.target_date = datetime.combine(target_date, datetime.min.time()) if target_date else None
            project.notes = notes
            if budget_hours is not None:
                project.budget_hours = budget_hours if budget_hours > 0 else None
            if hours_logged is not None:
                project.hours_logged = hours_logged
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _bulk_apply_tag(project_ids: list[str], tag: str):
    """Apply a tag to multiple projects."""
    session = get_session()
    try:
        for pid in project_ids:
            project = session.query(Project).filter_by(id=pid).first()
            if project:
                project.add_tag(tag)
                _sync_project_to_file(project)
        session.commit()
    finally:
        session.close()


def _run_prompt_on_project(project_path: str, project_name: str, prompt: str,
                           budget: float = 0.50, timeout_secs: int = 300):
    """Run a headless Claude Code prompt on a project and log transcript."""
    allowed_tools = ["Read", "Glob", "Grep"]

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(budget),
        "--allowedTools", ",".join(allowed_tools),
    ]

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )
        duration = time.time() - start_time

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            output_text = f"ERROR: {error_msg}"
            status = "error"
        else:
            output_text = result.stdout.strip() or "(empty output)"
            status = "success" if result.stdout.strip() else "empty"

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        output_text = f"TIMEOUT after {timeout_secs}s"
        status = "timeout"
    except FileNotFoundError:
        duration = time.time() - start_time
        output_text = "ERROR: claude command not found"
        status = "error"

    # Log transcript
    transcript_dir = Path(__file__).parent.parent / "transcripts" / project_name
    transcript_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    transcript_file = transcript_dir / f"{timestamp}.md"

    transcript_content = f"""# Prompt Run: {project_name}

- **Date:** {_utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
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

    return {
        "status": status,
        "output": output_text,
        "duration": duration,
        "transcript_file": str(transcript_file),
    }


# ── Helpers: Doc Generation ─────────────────────────────────────────────────


def generate_doc(project_path: str, project_name: str, project_id: str, template_id: str):
    """Generate a document for a project using headless Claude Code."""
    from pm.docgen.templates import get_template
    from pm.docgen.context import build_context
    from pm.docgen.executor import run_doc_generation

    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            return None

        tmpl = get_template(template_id)
        if not tmpl:
            return None

        ctx = build_context(project)
        prompt = tmpl.render(ctx)

        filename = tmpl.output_filename
        if "{date}" in filename:
            filename = filename.replace("{date}", datetime.now().strftime("%Y-%m-%d"))

        output_file = Path(project_path) / tmpl.output_dir / filename

        result = run_doc_generation(
            project_path=Path(project_path),
            prompt=prompt,
            output_file=output_file,
            max_budget_usd=tmpl.max_budget_usd,
            allowed_tools=tmpl.allowed_tools,
        )

        doc_gen = DocGeneration(
            project_id=project_id,
            template_id=template_id,
            output_path=f"{tmpl.output_dir}/{filename}",
            generated_at=_utcnow(),
            duration_secs=result.duration_secs,
            status=result.status,
            error_message=result.error_message if result.status != "success" else None,
            file_size_bytes=result.file_size_bytes,
        )
        session.add(doc_gen)
        session.commit()

        return result
    finally:
        session.close()


def generate_report(report_type: str, df: pd.DataFrame):
    """Generate a cross-project report using headless Claude Code."""
    from pm.docgen.templates import get_template
    from pm.docgen.context import ProjectContext
    from pm.docgen.executor import run_doc_generation

    pm_root = Path(__file__).parent.parent

    if report_type == "weekly":
        tmpl = get_template("weekly-summary")
    else:
        tmpl = get_template("status-report")

    if not tmpl:
        return None

    summary_lines = []
    for _, row in df.iterrows():
        summary_lines.append(
            f"- {row['name']} ({row['category']}): {row['completion']:.0f}% complete, "
            f"health {row['health']:.0f}/100, next: {row['next_action'] or 'none'}"
        )

    ctx = ProjectContext(
        name="Portfolio",
        path=pm_root,
        project_type="meta",
        category="internal",
        completion_pct=df["completion"].mean(),
        current_phase="",
        next_action="",
        git_branch="main",
        git_dirty=False,
        last_commit_msg="",
        has_claude_md=True,
        has_todo=False,
        has_progress=False,
        health_score=int(df["health"].mean()),
        urgency_score=0,
        priority=3,
        notes="\n".join(summary_lines),
    )

    prompt = tmpl.render(ctx)

    filename = tmpl.output_filename
    if "{date}" in filename:
        filename = filename.replace("{date}", datetime.now().strftime("%Y-%m-%d"))

    output_file = pm_root / tmpl.output_dir / filename

    result = run_doc_generation(
        project_path=pm_root,
        prompt=prompt,
        output_file=output_file,
        max_budget_usd=tmpl.max_budget_usd,
        allowed_tools=tmpl.allowed_tools,
    )

    if result.status == "success":
        return str(output_file)
    return None


# ── Tab: Docs ───────────────────────────────────────────────────────────────


def render_docs_tab(df: pd.DataFrame):
    """Render the Docs tab with generation grid and controls."""
    from pm.docgen.templates import BUILTIN_TEMPLATES

    st.subheader("Document Generation")

    per_project_templates = {k: v for k, v in BUILTIN_TEMPLATES.items() if k != "weekly-summary"}
    template_ids = list(per_project_templates.keys())

    st.markdown("**Cross-Project Reports**")
    rcol1, rcol2, rcol3 = st.columns([1, 1, 4])
    with rcol1:
        if st.button("Generate Weekly Summary", use_container_width=True):
            with st.spinner("Generating weekly summary..."):
                result = generate_report("weekly", df)
            if result:
                st.success(f"Generated: {result}")
            else:
                st.error("Generation failed")
    with rcol2:
        if st.button("Generate Status Report", use_container_width=True):
            with st.spinner("Generating status report..."):
                result = generate_report("status", df)
            if result:
                st.success(f"Generated: {result}")
            else:
                st.error("Generation failed")

    st.divider()

    st.markdown("**Batch Generation**")
    bcol1, bcol2, bcol3, bcol4 = st.columns([1, 1, 1, 2])
    with bcol1:
        batch_template = st.selectbox(
            "Template",
            template_ids,
            format_func=lambda x: per_project_templates[x].name,
        )
    with bcol2:
        batch_scope = st.selectbox("Scope", ["Top 5 by urgency", "Top 10 by urgency", "All projects"])

    with bcol3:
        batch_running = st.session_state.get("batch_gen_running", False)
        if not batch_running:
            if st.button("Generate Batch", use_container_width=True):
                st.session_state["batch_gen_running"] = True
                st.session_state["batch_gen_cancel"] = False
                st.rerun()
        else:
            if st.button("Cancel Batch", type="secondary", use_container_width=True):
                st.session_state["batch_gen_cancel"] = True

    if st.session_state.get("batch_gen_running"):
        scope_limit = 5 if "5" in batch_scope else (10 if "10" in batch_scope else len(df))
        target_df = df.nlargest(scope_limit, "urgency")

        progress_bar = st.progress(0)
        status_text = st.empty()
        results_ok = 0
        results_err = 0

        for i, (_, row) in enumerate(target_df.iterrows()):
            if st.session_state.get("batch_gen_cancel"):
                status_text.warning(f"Cancelled after {i} of {len(target_df)} documents")
                break
            status_text.text(f"[{i+1}/{len(target_df)}] Generating {batch_template} for {row['name']}...")
            try:
                result = generate_doc(row["path"], row["name"], row["id"], batch_template)
                if result and result.status == "success":
                    results_ok += 1
                else:
                    results_err += 1
            except Exception:
                results_err += 1
            progress_bar.progress((i + 1) / len(target_df))
        else:
            status_text.success(f"Batch complete: {results_ok} succeeded, {results_err} failed")

        st.session_state["batch_gen_running"] = False
        st.session_state["batch_gen_cancel"] = False

    st.divider()

    st.markdown("**Document Status by Project**")

    session = get_session()
    try:
        grid_data = []
        for _, row in df.sort_values("name").iterrows():
            row_data = {"Project": row["name"], "path": row["path"], "id": row["id"]}

            for tid in template_ids:
                latest = session.query(DocGeneration).filter(
                    DocGeneration.project_id == row["id"],
                    DocGeneration.template_id == tid,
                    DocGeneration.status == "success",
                ).order_by(DocGeneration.generated_at.desc()).first()

                if latest and latest.generated_at:
                    age_days = (_utcnow() - latest.generated_at).days
                    row_data[tid] = f"{age_days}d ago"
                else:
                    tmpl = per_project_templates[tid]
                    doc_path = Path(row["path"]) / tmpl.output_dir / tmpl.output_filename
                    if doc_path.exists():
                        row_data[tid] = "exists*"
                    else:
                        row_data[tid] = "—"

            grid_data.append(row_data)

        if grid_data:
            grid_df = pd.DataFrame(grid_data)
            display_cols = ["Project"] + template_ids
            st.dataframe(grid_df[display_cols], use_container_width=True, hide_index=True)
            st.caption("* = file exists but no generation record")

            st.markdown("**Generate for a specific project**")
            gcol1, gcol2, gcol3 = st.columns([2, 1, 1])
            with gcol1:
                selected_project = st.selectbox("Project", df["name"].sort_values().tolist(), key="docs_project_select")
            with gcol2:
                selected_template = st.selectbox("Template", template_ids, format_func=lambda x: per_project_templates[x].name, key="docs_template_select")
            with gcol3:
                if st.button("Generate", key="docs_generate_single"):
                    proj_row = df[df["name"] == selected_project].iloc[0]
                    with st.spinner(f"Generating {selected_template} for {selected_project}..."):
                        result = generate_doc(proj_row["path"], proj_row["name"], proj_row["id"], selected_template)
                    if result and result.status == "success":
                        st.success(f"Generated {selected_template} for {selected_project} ({result.duration_secs:.1f}s, {result.file_size_bytes} bytes)")
                    else:
                        error_msg = result.error_message if result else "Unknown error"
                        st.error(f"Failed: {error_msg}")

            st.divider()
            st.markdown("**View Generated Document**")
            vcol1, vcol2 = st.columns([3, 1])
            with vcol1:
                view_project = st.selectbox("Project", df["name"].sort_values().tolist(), key="docs_view_project")
            with vcol2:
                view_template = st.selectbox("Template", template_ids, format_func=lambda x: per_project_templates[x].name, key="docs_view_template")

            proj_row = df[df["name"] == view_project].iloc[0]
            tmpl = per_project_templates[view_template]
            doc_path = Path(proj_row["path"]) / tmpl.output_dir / tmpl.output_filename

            if doc_path.exists():
                file_size = doc_path.stat().st_size
                if file_size > 50 * 1024:
                    content = doc_path.read_text()
                    st.warning(f"Document is large ({file_size // 1024} KB) — showing as plain text.")
                    st.download_button("Download", content, file_name=doc_path.name, mime="text/markdown")
                    st.code(content[:2000] + f"\n\n... [{file_size // 1024} KB total — download to view full document]", language="markdown")
                else:
                    content = doc_path.read_text()
                    st.markdown(content)
            else:
                st.info(f"No {tmpl.name} document found for {view_project}. Generate one above.")

    finally:
        session.close()


# ── Tab: Activity ───────────────────────────────────────────────────────────


def render_activity_tab():
    """Render the Activity Digest tab."""
    st.subheader("Activity Digest")

    # Date range controls
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    default_start, default_end = week_to_date_range()

    with col1:
        start_date = st.date_input("Start", value=default_start.date(), key="digest_start")
    with col2:
        end_date = st.date_input("End", value=default_end.date(), key="digest_end")
    with col3:
        # Client filter: collect unique client names from DB
        _act_session = get_session()
        try:
            from sqlalchemy import distinct
            client_names = [
                r[0] for r in _act_session.query(distinct(Project.client_name))
                .filter(Project.client_name.isnot(None), Project.client_name != "")
                .order_by(Project.client_name).all()
            ]
        finally:
            _act_session.close()
        filter_client = st.selectbox("Client", ["All"] + client_names, key="digest_client")
    with col4:
        view_mode = st.radio("View", ["By Project/Client", "By Day"], horizontal=True, key="digest_mode")

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    range_label = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    client_filter = filter_client if filter_client != "All" else None

    session = get_session()
    try:
        if view_mode == "By Project/Client":
            results = digest_by_project(session, start_dt, end_dt, client_filter=client_filter)

            if not results:
                st.info(f"No activity found for {range_label}. Run `pm scan` to capture data.")
                return

            st.caption(f"{len(results)} projects with activity — {range_label}")

            # Build display data
            display_data = []
            for r in results:
                delta = r["completion_delta"]
                delta_str = f"+{delta:.0f}%" if delta > 0 else (f"{delta:.0f}%" if delta < 0 else "—")

                display_data.append({
                    "Project": r["name"],
                    "Client": r["client"],
                    "Change": delta_str,
                    "Current %": f"{r['current_completion']:.0f}%",
                    "Last Commit": r["last_commit_msg"][:50],
                    "Status": r["current_status"][:30],
                    "Health": r["health"],
                    "Scans": r["scan_count"],
                })

            st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

        else:
            results = digest_by_day(session, start_dt, end_dt)

            if not results:
                st.info(f"No activity found for {range_label}. Run `pm scan` to capture data.")
                return

            total_unique = len(set(n for r in results for n in r["project_names"]))
            st.caption(f"{len(results)} active days, {total_unique} unique projects — {range_label}")

            display_data = []
            for r in results:
                display_data.append({
                    "Date": r["date"].strftime("%Y-%m-%d"),
                    "Day": r["day_name"],
                    "Projects": r["project_count"],
                    "Active Projects": ", ".join(r["project_names"][:8]) + ("..." if len(r["project_names"]) > 8 else ""),
                })

            st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

    finally:
        session.close()


# ── Tab: Stale ──────────────────────────────────────────────────────────────


def load_stale_projects():
    """Load stale projects (inactive 30+ days, not archived, not someday)."""
    session = get_session()
    try:
        threshold = _utcnow() - timedelta(days=30)
        projects = session.query(Project).filter(
            (Project.archived == False) | (Project.archived == None),
            Project.priority != 5,
            (Project.last_activity < threshold) | (Project.last_activity == None),
        ).order_by(Project.last_activity.asc().nullsfirst()).all()

        data = []
        for p in projects:
            days_inactive = (_utcnow() - p.last_activity).days if p.last_activity else None
            data.append({
                "name": p.name,
                "path": p.path,
                "id": p.id,
                "category": p.category or "internal",
                "completion": p.completion_pct or 0,
                "health": p.health_score,
                "days_inactive": days_inactive,
                "priority": p.priority or 3,
                "priority_label": p.priority_label,
                "notes": p.notes or "",
                "last_commit_msg": p.last_commit_msg or "",
            })
        return data
    finally:
        session.close()


def _stale_action_archive(project_id: str, reason: str):
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.archived = True
            if reason:
                project.notes = f"{project.notes or ''}\n\n[Archived {_utcnow().strftime('%Y-%m-%d')}] {reason}".strip()
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _stale_action_forward(project_id: str, next_action: str, priority: int):
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.next_action = next_action
            project.priority = priority
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _stale_action_pivot(project_id: str, direction: str):
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.notes = f"{project.notes or ''}\n\n[Pivot {_utcnow().strftime('%Y-%m-%d')}] {direction}".strip()
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _stale_action_combine(project_id: str, target_name: str):
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.archived = True
            project.notes = f"{project.notes or ''}\n\n[Combined into {target_name} on {_utcnow().strftime('%Y-%m-%d')}]".strip()
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def _stale_action_replace(project_id: str, replacement_name: str):
    session = get_session()
    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if project:
            project.archived = True
            project.notes = f"{project.notes or ''}\n\n[Replaced by {replacement_name} on {_utcnow().strftime('%Y-%m-%d')}]".strip()
            session.commit()
            _sync_project_to_file(project)
    finally:
        session.close()


def render_stale_tab(all_project_names: list[str]):
    """Render the Stale Projects tab with action prompts."""
    st.subheader("Stale Projects")
    st.caption("Projects inactive for 30+ days (excluding archived and someday)")

    stale_projects = load_stale_projects()

    if not stale_projects:
        st.success("No stale projects. Everything is active or properly categorized.")
        return

    st.metric("Needs Attention", len(stale_projects))
    st.divider()

    for i, proj in enumerate(stale_projects):
        days_str = f"{proj['days_inactive']}d" if proj['days_inactive'] is not None else "unknown"
        with st.expander(
            f"**{proj['name']}** — {days_str} inactive | "
            f"{proj['completion']:.0f}% complete | {proj['category']}",
            expanded=False,
        ):
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Days Inactive", proj["days_inactive"] or "?")
            mc2.metric("Completion", f"{proj['completion']:.0f}%")
            mc3.metric("Health", proj["health"])

            if proj["last_commit_msg"]:
                st.caption(f"Last commit: {proj['last_commit_msg']}")
            if proj["notes"]:
                st.info(proj["notes"])

            st.markdown("**What should happen with this project?**")

            action_cols = st.columns(6)
            with action_cols[0]:
                if st.button("Archive", key=f"sa_{i}", use_container_width=True):
                    st.session_state[f"stale_action_{i}"] = "archive"
            with action_cols[1]:
                if st.button("Move Forward", key=f"sf_{i}", use_container_width=True):
                    st.session_state[f"stale_action_{i}"] = "forward"
            with action_cols[2]:
                if st.button("Pivot", key=f"sp_{i}", use_container_width=True):
                    st.session_state[f"stale_action_{i}"] = "pivot"
            with action_cols[3]:
                if st.button("Plan", key=f"sl_{i}", use_container_width=True):
                    launch_claude(proj["path"], proj["name"])
                    st.success(f"Launched Claude Code for {proj['name']}")
            with action_cols[4]:
                if st.button("Combine", key=f"sc_{i}", use_container_width=True):
                    st.session_state[f"stale_action_{i}"] = "combine"
            with action_cols[5]:
                if st.button("Replace", key=f"sr_{i}", use_container_width=True):
                    st.session_state[f"stale_action_{i}"] = "replace"

            action = st.session_state.get(f"stale_action_{i}")

            if action == "archive":
                reason = st.text_input("Reason for archiving (optional)", key=f"ar_{i}")
                if st.button("Confirm Archive", key=f"ca_{i}"):
                    _stale_action_archive(proj["id"], reason)
                    st.success(f"Archived {proj['name']}")
                    del st.session_state[f"stale_action_{i}"]
                    _bump_cache()
                    st.rerun()

            elif action == "forward":
                na = st.text_input("Next action", key=f"fn_{i}")
                pri = st.selectbox("Priority", [1, 2, 3, 4], index=2, format_func=lambda x: {1: "Critical", 2: "High", 3: "Normal", 4: "Low"}[x], key=f"fp_{i}")
                if st.button("Confirm", key=f"cf_{i}") and na:
                    _stale_action_forward(proj["id"], na, pri)
                    st.success(f"Updated {proj['name']}")
                    del st.session_state[f"stale_action_{i}"]
                    _bump_cache()
                    st.rerun()

            elif action == "pivot":
                direction = st.text_area("New direction / notes", key=f"pn_{i}")
                if st.button("Confirm Pivot", key=f"cp_{i}") and direction:
                    _stale_action_pivot(proj["id"], direction)
                    st.success(f"Updated {proj['name']}")
                    del st.session_state[f"stale_action_{i}"]
                    _bump_cache()
                    st.rerun()

            elif action == "combine":
                targets = [n for n in all_project_names if n != proj["name"]]
                target = st.selectbox("Combine into", targets, key=f"ct_{i}")
                if st.button("Confirm Combine", key=f"cc_{i}"):
                    _stale_action_combine(proj["id"], target)
                    st.success(f"Archived {proj['name']}, combined into {target}")
                    del st.session_state[f"stale_action_{i}"]
                    _bump_cache()
                    st.rerun()

            elif action == "replace":
                targets = [n for n in all_project_names if n != proj["name"]]
                repl = st.selectbox("Replacement project", targets, key=f"rt_{i}")
                if st.button("Confirm Replace", key=f"cr_{i}"):
                    _stale_action_replace(proj["id"], repl)
                    st.success(f"Archived {proj['name']}, replaced by {repl}")
                    del st.session_state[f"stale_action_{i}"]
                    _bump_cache()
                    st.rerun()


# ── Tab: Agents ─────────────────────────────────────────────────────────────


def render_agents_tab(df: pd.DataFrame):
    """Render the Agents tab: assess, run, and view agent history."""
    st.subheader("Agent Orchestration")
    st.caption("Two-phase assess/execute system for automated project work")

    # ── Run controls ──────────────────────────────────────────────────────────
    with st.expander("Run Agent Batch", expanded=False):
        col1, col2, col3 = st.columns(3)
        limit = col1.number_input("Max projects", min_value=1, max_value=20, value=5)
        budget = col2.number_input("Budget per project ($)", min_value=0.10, max_value=5.0,
                                   value=1.00, step=0.25)
        workers = col3.number_input("Parallel workers", min_value=1, max_value=5, value=3)

        context_hint = st.text_input("Focus hint (optional)",
                                     placeholder="e.g. fix failing tests, update docs")

        dry_run = st.checkbox("Dry run (assess only, no execution)", value=True)

        col_run, col_status = st.columns([1, 3])
        if col_run.button("Run Batch", type="primary"):
            from pm.agent.coordinator import AgentCoordinator

            session = get_session()
            projects = session.query(Project).filter(
                Project.archived == False
            ).all()
            session.close()

            # Sort by urgency, take top N
            projects_sorted = sorted(projects, key=lambda p: p.urgency_score, reverse=True)[:limit]
            project_dicts = [{"name": p.name, "path": p.path} for p in projects_sorted]

            if not project_dicts:
                col_status.warning("No projects found.")
            else:
                col_status.info(f"Running on {len(project_dicts)} projects...")
                coordinator = AgentCoordinator(
                    max_workers=workers,
                    budget_per_project=budget,
                    dry_run=dry_run,
                )

                coord_result = coordinator.run(
                    project_dicts,
                    context_hint=context_hint or None,
                )

                # Store results in session state for display
                st.session_state["last_agent_run"] = coord_result
                col_status.success(coord_result.summary())
                st.rerun()

    # ── Last batch results ────────────────────────────────────────────────────
    if "last_agent_run" in st.session_state:
        coord = st.session_state["last_agent_run"]
        st.markdown("### Last Batch Results")

        result_rows = []
        for assessment in coord.assessments:
            exec_result = next(
                (r for r in coord.executions if r.project_name == assessment.project_name),
                None
            )
            status = (
                exec_result.status if exec_result else
                "escalated" if not assessment.should_auto_execute else "dry_run"
            )
            result_rows.append({
                "Project": assessment.project_name,
                "Confidence": assessment.confidence,
                "Risk": assessment.risk_level,
                "Action": assessment.proposed_action[:80],
                "Status": status,
            })

        if result_rows:
            result_df = pd.DataFrame(result_rows)
            st.dataframe(result_df, use_container_width=True, hide_index=True)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Assessed", coord.total_projects)
        col_b.metric("Auto-executed", coord.auto_executed)
        col_c.metric("Escalated", coord.escalated)

        if st.button("Clear Results"):
            del st.session_state["last_agent_run"]
            st.rerun()

    # ── Single project assess ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Assess a Single Project")

    project_names = sorted(df["name"].tolist()) if not df.empty else []
    sel_project = st.selectbox("Project", ["— select —"] + project_names,
                               key="agent_assess_project")

    if sel_project and sel_project != "— select —":
        assess_context = st.text_input("Focus hint", key="agent_assess_context",
                                       placeholder="optional — leave blank for general assessment")
        if st.button("Assess", key="agent_assess_btn"):
            from pm.agent.planner import plan_project

            session = get_session()
            project = session.query(Project).filter_by(name=sel_project).first()
            session.close()

            if project:
                with st.spinner(f"Assessing {sel_project}..."):
                    result = plan_project(project.path, project.name,
                                         context_hint=assess_context or None)

                confidence_color = (
                    "green" if result.confidence >= 80 else
                    "orange" if result.confidence >= 50 else "red"
                )

                col1, col2, col3 = st.columns(3)
                col1.metric("Confidence", f"{result.confidence}/100")
                col2.metric("Risk Level", result.risk_level.title())
                col3.metric("Duration", f"{result.duration_secs:.1f}s")

                st.markdown(f"**Proposed Action:** {result.proposed_action}")
                st.markdown(f"**Reasoning:** {result.reasoning}")

                with st.expander("Proposed Prompt"):
                    st.code(result.proposed_prompt, language="text")

                if result.error:
                    st.error(f"Error: {result.error}")
                elif result.should_auto_execute:
                    st.success("✓ Would auto-execute (confidence ≥ 80, risk = safe)")
                else:
                    reasons = []
                    if result.confidence < 80:
                        reasons.append(f"confidence {result.confidence} < 80")
                    if result.risk_level != "safe":
                        reasons.append(f"risk = {result.risk_level}")
                    st.warning(f"Would escalate: {', '.join(reasons)}")


# ── Tab: Projects ───────────────────────────────────────────────────────────


def render_projects_tab(df: pd.DataFrame):
    """Render the main projects tab."""
    # Controls row
    ctrl1, ctrl2, ctrl3, ctrl4, ctrl5 = st.columns([2, 1, 1, 1, 2])

    with ctrl1:
        sort_options = {
            "Last Commit ↓": ("last_commit", False),
            "Last Commit ↑": ("last_commit", True),
            "Health ↓": ("health", False),
            "Health ↑": ("health", True),
            "Name A-Z": ("name", True),
            "Priority ↓": ("priority", True),
            "Urgency ↓": ("urgency", False),
        }
        sort_choice = st.selectbox("Sort", list(sort_options.keys()), label_visibility="collapsed")
        sort_col, sort_asc = sort_options[sort_choice]

    with ctrl2:
        _prev_cat = st.session_state.get("_sel_cat", "All")
        cat_label = "Category" if _prev_cat == "All" else f"Category ▶ {_prev_cat}"
        filter_cat = st.selectbox(cat_label, ["All"] + sorted(df["category"].unique().tolist()), key="_sel_cat")

    with ctrl3:
        _prev_type = st.session_state.get("_sel_type", "All")
        type_label = "Filter" if _prev_type == "All" else f"Filter ▶ {_prev_type}"
        filter_type = st.selectbox(type_label, ["All", "Dirty", "Decisions", "Overdue"], key="_sel_type")

    with ctrl4:
        # Tag filter
        all_tags = sorted(set(tag for tags in df["tags"] for tag in tags))
        _prev_tags = st.session_state.get("_sel_tags", [])
        tags_label = "Tags" if not _prev_tags else f"Tags ({len(_prev_tags)} active)"
        filter_tags = st.multiselect(tags_label, all_tags, key="_sel_tags", placeholder="Tags...")

    with ctrl5:
        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            if st.button("🚀 Top 10", use_container_width=True):
                sorted_df = df.sort_values(sort_col, ascending=sort_asc, na_position="last").head(10)
                launch_batch([(r["path"], r["name"]) for _, r in sorted_df.iterrows()])
                st.success("Launched 10!")
        with bcol2:
            if st.button("📊 Weekly", use_container_width=True):
                with st.spinner("Generating..."):
                    f = generate_report("weekly", df)
                if f:
                    st.success(f"Generated: {f}")
                else:
                    st.error("Generation failed")
        with bcol3:
            if st.button("📋 Status", use_container_width=True):
                with st.spinner("Generating..."):
                    f = generate_report("status", df)
                if f:
                    st.success(f"Generated: {f}")
                else:
                    st.error("Generation failed")

    # Bulk tag bar (shows when projects are selected)
    if st.session_state.selected:
        btcol1, btcol2, btcol3, btcol4 = st.columns([2, 2, 1, 1])
        with btcol1:
            st.markdown(f"**{len(st.session_state.selected)} selected**")
        with btcol2:
            bulk_tag = st.text_input("Tag to apply", key="bulk_tag_input", label_visibility="collapsed", placeholder="Tag name...")
        with btcol3:
            if st.button("Apply Tag", use_container_width=True) and bulk_tag:
                selected_ids = []
                for _, r in df.iterrows():
                    if r["name"] in st.session_state.selected:
                        selected_ids.append(r["id"])
                _bulk_apply_tag(selected_ids, bulk_tag)
                st.session_state.selected = set()
                _bump_cache()
                st.rerun()
        with btcol4:
            if st.button("Clear", use_container_width=True):
                st.session_state.selected = set()
                st.rerun()

    # Reset page when filters change (TD-023)
    current_filters = {"cat": filter_cat, "type": filter_type, "tags": tuple(sorted(filter_tags))}
    if current_filters != st.session_state._prev_filters:
        st.session_state.page = 0
        st.session_state._prev_filters = current_filters

    # Apply filters
    filtered_df = df.copy()
    if filter_cat != "All":
        filtered_df = filtered_df[filtered_df["category"] == filter_cat]
    if filter_type == "Dirty":
        filtered_df = filtered_df[filtered_df["git_dirty"] == True]
    elif filter_type == "Decisions":
        filtered_df = filtered_df[filtered_df["has_decision"] == True]
    elif filter_type == "Overdue":
        filtered_df = filtered_df[filtered_df["is_overdue"] == True]
    if filter_tags:
        filtered_df = filtered_df[filtered_df["tags"].apply(lambda t: any(ft in t for ft in filter_tags))]

    # Sort
    filtered_df = filtered_df.sort_values(sort_col, ascending=sort_asc, na_position="last")

    st.caption(f"Showing {len(filtered_df)} of {len(df)} projects")

    # Pagination
    PAGE_SIZE = 25
    total_pages = max(1, (len(filtered_df) - 1) // PAGE_SIZE + 1)

    if total_pages > 1:
        pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
        with pcol1:
            if st.button("← Prev") and st.session_state.page > 0:
                st.session_state.page -= 1
                st.rerun()
        with pcol2:
            st.markdown(f"<center>Page {st.session_state.page + 1} of {total_pages}</center>", unsafe_allow_html=True)
        with pcol3:
            if st.button("Next →") and st.session_state.page < total_pages - 1:
                st.session_state.page += 1
                st.rerun()

    # Get current page
    start_idx = st.session_state.page * PAGE_SIZE
    page_df = filtered_df.iloc[start_idx:start_idx + PAGE_SIZE]

    # Column headers
    hdr0, hdr1, hdr2, hdr3, hdr4, hdr5, hdr6, hdr7 = st.columns([0.3, 0.5, 2.5, 0.8, 0.8, 1, 1, 1.2])
    # "Select All" checkbox in header — selects/deselects all visible projects on current page
    page_names = set(page_df["name"].tolist())
    all_selected = page_names and page_names.issubset(st.session_state.selected)
    if hdr0.checkbox("", value=all_selected, key="sel_all", help="Select all on page", label_visibility="collapsed"):
        st.session_state.selected.update(page_names)
    else:
        st.session_state.selected.difference_update(page_names)
    hdr1.markdown("**Flags**")
    hdr2.markdown("**Project**")
    hdr3.markdown("**Health**")
    hdr4.markdown("**Done**")
    hdr5.markdown("**Last Activity**")
    hdr6.markdown("**Last Commit**")
    hdr7.markdown("**Actions**")
    st.caption("Flags: 🔴 Critical · 🟠 High · ⚪ Normal · 🔵 Low · ● Dirty · ⚠️ Decision · ⏰ Overdue")
    st.divider()

    # Collect all tags once for editing dropdowns
    all_known_tags = sorted(set(tag for tags in df["tags"] for tag in tags))

    # Render projects as rows
    for idx, row in page_df.iterrows():
        col0, col1, col2, col3, col4, col5, col6, col7 = st.columns([0.3, 0.5, 2.5, 0.8, 0.8, 1, 1, 1.2])

        # Selection checkbox
        with col0:
            is_selected = row["name"] in st.session_state.selected
            if st.checkbox("", value=is_selected, key=f"sel_{idx}", label_visibility="collapsed"):
                st.session_state.selected.add(row["name"])
            elif row["name"] in st.session_state.selected:
                st.session_state.selected.discard(row["name"])

        # Status icons
        health_icon = "🟢" if row["health"] >= 70 else "🟡" if row["health"] >= 40 else "🔴"
        pri_icon = {1: "🔴", 2: "🟠", 3: "⚪", 4: "🔵", 5: "⚪"}.get(row["priority"], "⚪")
        badges = []
        if row["git_dirty"]:
            badges.append("●")
        if row["has_decision"]:
            badges.append("⚠️")
        if row["is_overdue"]:
            badges.append("⏰")

        col1.markdown(f"{pri_icon} {' '.join(badges)}")

        # Project name with expander for details
        # After a save, keep the edited project's expander open on rerun
        is_expanded = st.session_state.get("last_expanded_id") == row["id"]
        with col2:
            with st.expander(f"**{row['name']}**", expanded=is_expanded):

                if row["commit_msg"]:
                    st.caption(f"💬 {row['commit_msg']}")
                st.caption(f"📁 {row['path']}")
                if row["next_action"]:
                    st.markdown(f"**Next:** {row['next_action']}")

                # ── Inline metadata editing ─────────────────────────────────
                st.markdown("---")
                mcol1, mcol2, mcol3 = st.columns(3)
                priority_map = {1: "Critical", 2: "High", 3: "Normal", 4: "Low", 5: "Someday"}
                with mcol1:
                    new_priority = st.selectbox(
                        "Priority",
                        options=[1, 2, 3, 4, 5],
                        index=[1, 2, 3, 4, 5].index(row["priority"]),
                        format_func=lambda x: priority_map[x],
                        key=f"pri_{idx}",
                    )
                with mcol2:
                    dl_val = row["deadline"].date() if row["deadline"] is not None and not (isinstance(row["deadline"], float) and pd.isna(row["deadline"])) else None
                    new_deadline = st.date_input("Deadline", value=dl_val, key=f"dl_{idx}")
                with mcol3:
                    tgt_raw = row.get("target_date")
                    tgt_val = tgt_raw.date() if tgt_raw is not None and not (isinstance(tgt_raw, float) and pd.isna(tgt_raw)) else None
                    new_target = st.date_input("Target Date", value=tgt_val, key=f"tgt_{idx}")

                hcol1, hcol2 = st.columns(2)
                with hcol1:
                    budget_raw = row.get("budget_hours")
                    budget_val = float(budget_raw) if budget_raw and not pd.isna(budget_raw) else 0.0
                    new_budget = st.number_input("Budget (hrs)", min_value=0.0, step=0.5, value=budget_val, key=f"bud_{idx}")
                with hcol2:
                    logged_raw = row.get("hours_logged", 0.0)
                    logged_val = float(logged_raw) if logged_raw and not pd.isna(logged_raw) else 0.0
                    new_logged = st.number_input("Logged (hrs)", min_value=0.0, step=0.5, value=logged_val, key=f"log_{idx}")

                new_notes = st.text_area("Notes", value=row["notes"], key=f"notes_{idx}", height=80)

                if st.button("Save", key=f"savemeta_{idx}", use_container_width=True):
                    _save_metadata(row["id"], new_priority, new_deadline, new_target, new_notes,
                                   budget_hours=new_budget, hours_logged=new_logged)
                    st.session_state.last_expanded_id = row["id"]
                    _bump_cache()
                    st.rerun()

                # ── Inline tag editing ──────────────────────────────────────
                st.markdown("---")
                tcol1, tcol2 = st.columns([3, 1])
                with tcol1:
                    new_tags = st.multiselect(
                        "Tags",
                        options=all_known_tags,
                        default=row["tags"],
                        key=f"tags_{idx}",
                        placeholder="Add tags...",
                    )
                    new_tag_input = st.text_input("New tag", key=f"newtag_{idx}", label_visibility="collapsed", placeholder="Type new tag...")
                with tcol2:
                    if st.button("Save Tags", key=f"st_{idx}", use_container_width=True):
                        save_list = list(new_tags)
                        if new_tag_input and new_tag_input not in save_list:
                            save_list.append(new_tag_input)
                        _save_tags(row["id"], row["path"], save_list)
                        st.session_state.last_expanded_id = row["id"]
                        _bump_cache()
                        st.rerun()

                # ── Run prompt ──────────────────────────────────────────────
                st.markdown("---")
                st.markdown("**Run Prompt**")
                run_prompt = st.text_area("Prompt", key=f"rp_{idx}", placeholder="Ask Claude something about this project...", label_visibility="collapsed")
                rpcol1, rpcol2 = st.columns([1, 3])
                with rpcol1:
                    if st.button("Run", key=f"rpb_{idx}", use_container_width=True) and run_prompt:
                        with st.spinner("Running..."):
                            result = _run_prompt_on_project(row["path"], row["name"], run_prompt)
                        if result["status"] == "success":
                            st.success(f"Done in {result['duration']:.1f}s")
                            output_preview = result["output"][:500]
                            if len(result["output"]) > 500:
                                output_preview += f"\n\n*... [{len(result['output']) - 500} chars truncated — see transcript]*"
                            st.markdown(output_preview)
                        else:
                            st.error(f"{result['status']}: {result['output'][:200]}")
                        st.caption(f"Transcript: {result['transcript_file']}")
                with rpcol2:
                    safe_name = re.sub(r'[^\w\-]', '_', row["name"])
                    transcript_dir = Path(__file__).parent.parent / "transcripts" / safe_name
                    if transcript_dir.exists():
                        recent = sorted(transcript_dir.glob("*.md"), reverse=True)[:3]
                        if recent:
                            st.caption(f"{len(recent)} recent transcript(s)")

        # Health
        col3.markdown(f"{health_icon} {row['health']:.0f}")

        # Completion
        col4.markdown(f"{row['completion']:.0f}%")

        # Last Activity
        if row["days_inactive"] is not None:
            if row["days_inactive"] == 0:
                col5.markdown("Today")
            elif row["days_inactive"] < 7:
                col5.markdown(f"{row['days_inactive']}d ago")
            elif row["days_inactive"] < 30:
                col5.markdown(f"{row['days_inactive']//7}w ago")
            else:
                col5.markdown(f"{row['days_inactive']//30}mo ago")
        else:
            col5.markdown("—")

        # Last Commit
        if pd.notna(row["last_commit"]):
            col6.markdown(row["last_commit"].strftime("%m/%d %H:%M"))
        else:
            col6.markdown("—")

        # Actions
        with col7:
            ac1, ac2, ac3 = st.columns(3)
            if ac1.button("🚀", key=f"l_{idx}", help="Launch Claude"):
                try:
                    launch_claude(row["path"], row["name"])
                    st.toast(f"Launched {row['name']}", icon="🚀")
                except Exception as e:
                    st.toast(f"Launch failed: {e}", icon="❌")
            if ac2.button("📂", key=f"v_{idx}", help="VSCode"):
                try:
                    subprocess.Popen(["code", row["path"]])
                    st.toast(f"Opened {row['name']} in VSCode", icon="📂")
                except Exception as e:
                    st.toast(f"VSCode failed: {e}", icon="❌")
            if ac3.button("📁", key=f"f_{idx}", help="Finder"):
                try:
                    subprocess.Popen(["open", row["path"]])
                except Exception as e:
                    st.toast(f"Finder failed: {e}", icon="❌")


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    st.title("📊 Project Manager")

    # Load data (cache_version key invalidates cache on mutations)
    with st.spinner("Loading projects..."):
        df = load_projects(st.session_state.get("cache_version", 0))

    if df.empty:
        st.error("No projects found. Run `pm scan ~/dev2` first.")
        return

    # Stats bar
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total", len(df))
    col2.metric("Avg Health", f"{df['health'].mean():.0f}")
    col3.metric("Dirty", len(df[df['git_dirty'] == True]))
    col4.metric("Decisions", len(df[df['has_decision'] == True]))
    col5.metric("Overdue", len(df[df['is_overdue'] == True]))

    st.divider()

    # Tabs
    tab_projects, tab_activity, tab_stale, tab_docs, tab_agents = st.tabs(
        ["Projects", "Activity", "Stale", "Docs", "Agents"]
    )

    with tab_projects:
        render_projects_tab(df)

    with tab_activity:
        render_activity_tab()

    with tab_stale:
        render_stale_tab(df["name"].sort_values().tolist())

    with tab_docs:
        render_docs_tab(df)

    with tab_agents:
        render_agents_tab(df)


if __name__ == "__main__":
    main()
