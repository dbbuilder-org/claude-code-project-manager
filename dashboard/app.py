"""Streamlit dashboard for project manager."""

import sys
import subprocess
import os
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from pm.database.models import init_db, get_session, Project
from pm.scanner.parser import ProgressParser
from pm.generator.prompts import ContinuePromptGenerator, PromptMode

# Page config
st.set_page_config(
    page_title="Project Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .project-card {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .health-high { background-color: rgba(0, 255, 0, 0.1); }
    .health-medium { background-color: rgba(255, 255, 0, 0.1); }
    .health-low { background-color: rgba(255, 0, 0, 0.1); }
    .stProgress > div > div > div > div {
        background-color: #4CAF50;
    }
    .action-btn {
        padding: 0.25rem 0.5rem;
        font-size: 0.8rem;
    }
    div[data-testid="stExpander"] details summary p {
        font-size: 1.1rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Initialize database
init_db()

# Session state for selections
if "selected_projects" not in st.session_state:
    st.session_state.selected_projects = set()


def get_projects_data(include_archived: bool = False):
    """Load projects with health scores."""
    session = get_session()
    query = session.query(Project)
    if not include_archived:
        query = query.filter((Project.archived == False) | (Project.archived == None))
    projects = query.all()

    data = []
    for p in projects:
        # Calculate days since last activity
        if p.last_activity:
            days_inactive = (datetime.utcnow() - p.last_activity).days
        else:
            days_inactive = None

        data.append({
            "name": p.name,
            "path": p.path,
            "category": p.category,
            "type": p.project_type,
            "completion": p.completion_pct or 0,
            "health": p.health_score,
            "urgency": p.urgency_score,
            "phase": p.current_phase or "",
            "status": p.current_status or "",
            "next_action": p.next_action or "",
            "has_decision": p.has_pending_decision,
            "git_dirty": p.git_dirty,
            "git_branch": p.git_branch or "",
            "last_activity": p.last_activity,
            "days_inactive": days_inactive,
            "last_scanned": p.last_scanned,
            "has_claude_md": p.has_claude_md,
            "has_todo": p.has_todo,
            # PM metadata
            "priority": p.priority or 3,
            "priority_label": p.priority_label,
            "deadline": p.deadline,
            "target_date": p.target_date,
            "days_to_deadline": p.days_until_deadline,
            "is_overdue": p.is_overdue,
            "notes": p.notes or "",
            "tags": p.tags_list,
            "client_name": p.client_name or "",
            "budget_hours": p.budget_hours,
            "hours_logged": p.hours_logged or 0,
            "archived": p.archived or False,
        })

    session.close()
    return pd.DataFrame(data)


def update_project_metadata(name: str, **kwargs):
    """Update project metadata in database."""
    import json
    session = get_session()
    project = session.query(Project).filter(Project.name == name).first()
    if project:
        for key, value in kwargs.items():
            if key == "tags" and isinstance(value, list):
                value = json.dumps(value)
            if hasattr(project, key):
                setattr(project, key, value)
        session.commit()
    session.close()


def open_in_vscode(path: str):
    """Open project in VSCode."""
    subprocess.Popen(["code", path])


def open_in_terminal(path: str):
    """Open new terminal at project path."""
    # macOS: Open in new iTerm2 tab or Terminal
    script = f'''
    tell application "iTerm"
        activate
        tell current window
            create tab with default profile
            tell current session
                write text "cd '{path}'"
            end tell
        end tell
    end tell
    '''
    try:
        subprocess.Popen(["osascript", "-e", script])
    except:
        # Fallback to Terminal.app
        subprocess.Popen(["open", "-a", "Terminal", path])


def open_in_finder(path: str):
    """Open project folder in Finder."""
    subprocess.Popen(["open", path])


def launch_claude_code(path: str, name: str, prompt: str = None):
    """Launch Claude Code for a project."""
    cmd = ["claude"]
    if prompt:
        cmd.extend(["-p", prompt])

    # Open in new iTerm tab
    prompt_arg = f' -p "{prompt}"' if prompt else ""
    script = f'''
    tell application "iTerm"
        activate
        tell current window
            create tab with default profile
            tell current session
                write text "cd '{path}' && claude{prompt_arg}"
            end tell
        end tell
    end tell
    '''
    try:
        subprocess.Popen(["osascript", "-e", script])
        return True
    except Exception as e:
        st.error(f"Failed to launch: {e}")
        return False


def get_project_files(path: str) -> dict:
    """Read project progress files."""
    p = Path(path)
    files = {}

    for filename in ["TODO.md", "PROGRESS.md", "CLAUDE.md", "README.md"]:
        filepath = p / filename
        if filepath.exists():
            try:
                files[filename] = filepath.read_text()[:5000]  # Limit size
            except:
                files[filename] = "(Could not read file)"

    return files


def get_project_context(project_path: str, project_name: str) -> str:
    """Generate context for a project."""
    parser = ProgressParser()
    generator = ContinuePromptGenerator()
    path = Path(project_path)
    progress = parser.parse_project(path)
    prompt = generator.generate(path, project_name, progress, PromptMode.CONTEXT)
    return prompt.prompt_text or ""


def main():
    st.title("📊 Project Manager")

    # Load data
    df = get_projects_data()

    if df.empty:
        st.warning("No projects found. Run `pm scan ~/dev2` first.")
        st.code("pm scan ~/dev2")
        return

    # Sidebar
    with st.sidebar:
        st.header("🔍 Filters")

        # Category filter
        categories = ["All"] + sorted(df["category"].unique().tolist())
        selected_category = st.selectbox("Category", categories)
        if selected_category != "All":
            df = df[df["category"] == selected_category]

        # Health filter
        health_filter = st.selectbox(
            "Health",
            ["All", "Healthy (70+)", "Needs Work (40-69)", "Critical (<40)"]
        )
        if health_filter == "Healthy (70+)":
            df = df[df["health"] >= 70]
        elif health_filter == "Needs Work (40-69)":
            df = df[(df["health"] >= 40) & (df["health"] < 70)]
        elif health_filter == "Critical (<40)":
            df = df[df["health"] < 40]

        # Quick filters
        st.markdown("**Quick Filters**")
        if st.checkbox("Has pending decisions"):
            df = df[df["has_decision"] == True]
        if st.checkbox("Has uncommitted changes"):
            df = df[df["git_dirty"] == True]
        if st.checkbox("Stale (30+ days inactive)"):
            df = df[df["days_inactive"].notna() & (df["days_inactive"] > 30)]
        if st.checkbox("In progress (25-90%)"):
            df = df[(df["completion"] >= 25) & (df["completion"] < 90)]

        # Search
        search = st.text_input("🔎 Search", placeholder="Project name...")
        if search:
            df = df[df["name"].str.contains(search, case=False, na=False)]

        st.divider()

        # Quick stats
        st.header("📈 Stats")
        total = len(df)
        avg_health = df["health"].mean() if total > 0 else 0
        avg_completion = df["completion"].mean() if total > 0 else 0

        col1, col2 = st.columns(2)
        col1.metric("Projects", total)
        col2.metric("Avg Health", f"{avg_health:.0f}")

        # Alerts
        decisions = df[df["has_decision"] == True]
        if len(decisions) > 0:
            st.warning(f"⚠️ {len(decisions)} pending decisions")

        dirty = df[df["git_dirty"] == True]
        if len(dirty) > 0:
            st.info(f"● {len(dirty)} uncommitted changes")

        st.divider()

        # Batch actions
        st.header("🚀 Batch Actions")
        selected = st.session_state.selected_projects
        st.caption(f"{len(selected)} projects selected")

        if len(selected) > 0:
            if st.button("Launch Selected in Claude", type="primary"):
                for name in selected:
                    row = df[df["name"] == name].iloc[0] if len(df[df["name"] == name]) > 0 else None
                    if row is not None:
                        launch_claude_code(row["path"], row["name"])
                st.success(f"Launched {len(selected)} projects!")
                st.session_state.selected_projects = set()
                st.rerun()

            if st.button("Clear Selection"):
                st.session_state.selected_projects = set()
                st.rerun()

    # Main content tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📋 All Projects",
        "🔥 Urgent",
        "🎯 Work Queue",
        "⚠️ Decisions",
        "🟢 Clients",
        "✏️ Edit",
        "📊 Analytics"
    ])

    with tab1:
        render_project_list(df)

    with tab2:
        render_urgent(df)

    with tab3:
        render_work_queue(df)

    with tab4:
        render_decisions(df)

    with tab5:
        client_df = df[df["category"] == "client"]
        if len(client_df) > 0:
            render_project_list(client_df, show_category=False)
        else:
            st.info("No client projects found")

    with tab6:
        render_edit_metadata(df)

    with tab7:
        render_analytics(df)


def render_work_queue(df: pd.DataFrame):
    """Render prioritized work queue."""
    st.subheader("🎯 Suggested Next Actions")
    st.caption("Projects sorted by priority based on health, decisions, and activity")

    # Score projects for work priority
    work_df = df.copy()

    # Priority score: lower health + decisions + recent activity = higher priority
    work_df["priority"] = (
        (100 - work_df["health"]) * 0.4 +  # Lower health = higher priority
        work_df["has_decision"].astype(int) * 30 +  # Decisions need resolution
        work_df["git_dirty"].astype(int) * 10 +  # Uncommitted work
        ((work_df["completion"] > 25) & (work_df["completion"] < 90)).astype(int) * 20  # In progress
    )

    # Sort by priority descending
    work_df = work_df.sort_values("priority", ascending=False).head(20)

    for idx, row in work_df.iterrows():
        with st.expander(f"{'⚠️ ' if row['has_decision'] else ''}{row['name']} — Health: {row['health']:.0f}, Progress: {row['completion']:.0f}%"):
            col1, col2 = st.columns([3, 1])

            with col1:
                # Why it's prioritized
                reasons = []
                if row["has_decision"]:
                    reasons.append("🔴 Has pending decision")
                if row["health"] < 40:
                    reasons.append("🔴 Critical health score")
                elif row["health"] < 70:
                    reasons.append("🟡 Needs attention")
                if row["git_dirty"]:
                    reasons.append("● Has uncommitted changes")
                if row["completion"] >= 25 and row["completion"] < 90:
                    reasons.append("🔄 In progress")

                if reasons:
                    st.markdown("**Priority reasons:**")
                    for r in reasons:
                        st.markdown(f"- {r}")

                if row["next_action"]:
                    st.markdown(f"**Next action:** {row['next_action']}")

                if row["phase"]:
                    st.markdown(f"**Current phase:** {row['phase']}")

            with col2:
                st.markdown("**Quick Actions**")
                if st.button("🚀 Claude", key=f"wq_claude_{idx}"):
                    context = get_project_context(row["path"], row["name"])
                    launch_claude_code(row["path"], row["name"], context[:500])
                    st.success("Launched!")

                if st.button("📂 VSCode", key=f"wq_vscode_{idx}"):
                    open_in_vscode(row["path"])

                if st.button("💻 Terminal", key=f"wq_term_{idx}"):
                    open_in_terminal(row["path"])


def render_urgent(df: pd.DataFrame):
    """Render urgent projects by deadline and priority."""
    st.subheader("🔥 Urgent Projects")
    st.caption("Sorted by urgency score (deadlines + priority)")

    # Sort by urgency
    urgent_df = df.sort_values("urgency", ascending=False)

    # Show overdue first
    overdue = urgent_df[urgent_df["is_overdue"] == True]
    if len(overdue) > 0:
        st.error(f"🚨 {len(overdue)} OVERDUE projects!")
        for idx, row in overdue.iterrows():
            days = abs(row["days_to_deadline"])
            with st.expander(f"🔴 {row['name']} — OVERDUE by {days} days"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Deadline:** {row['deadline'].strftime('%Y-%m-%d')}")
                    st.markdown(f"**Priority:** {row['priority_label']}")
                    if row["notes"]:
                        st.markdown(f"**Notes:** {row['notes']}")
                with col2:
                    if st.button("🚀 Claude", key=f"urg_claude_{idx}"):
                        launch_claude_code(row["path"], row["name"])

    # Show upcoming deadlines
    upcoming = urgent_df[
        (urgent_df["days_to_deadline"].notna()) &
        (urgent_df["days_to_deadline"] >= 0) &
        (urgent_df["days_to_deadline"] <= 14)
    ]
    if len(upcoming) > 0:
        st.warning(f"⏰ {len(upcoming)} projects due within 2 weeks")
        for idx, row in upcoming.iterrows():
            days = row["days_to_deadline"]
            urgency_color = "🔴" if days <= 3 else "🟡" if days <= 7 else "🟢"
            with st.expander(f"{urgency_color} {row['name']} — {days} days left"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Deadline:** {row['deadline'].strftime('%Y-%m-%d')}")
                    st.markdown(f"**Priority:** {row['priority_label']}")
                    st.markdown(f"**Progress:** {row['completion']:.0f}%")
                    if row["notes"]:
                        st.markdown(f"**Notes:** {row['notes']}")
                with col2:
                    if st.button("🚀 Claude", key=f"upc_claude_{idx}"):
                        launch_claude_code(row["path"], row["name"])

    # Show high priority without deadlines
    high_priority = urgent_df[
        (urgent_df["priority"] <= 2) &
        (urgent_df["deadline"].isna())
    ]
    if len(high_priority) > 0:
        st.info(f"⭐ {len(high_priority)} high priority projects (no deadline set)")
        for idx, row in high_priority.head(10).iterrows():
            priority_icon = "🔴" if row["priority"] == 1 else "🟡"
            with st.expander(f"{priority_icon} {row['name']} — {row['priority_label']}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Category:** {row['category']}")
                    st.markdown(f"**Progress:** {row['completion']:.0f}%")
                    if row["notes"]:
                        st.markdown(f"**Notes:** {row['notes']}")
                with col2:
                    if st.button("🚀 Claude", key=f"hp_claude_{idx}"):
                        launch_claude_code(row["path"], row["name"])


def render_edit_metadata(df: pd.DataFrame):
    """Render metadata editing interface."""
    st.subheader("✏️ Edit Project Metadata")

    # Project selector
    project_names = sorted(df["name"].tolist())
    selected_project = st.selectbox("Select Project", [""] + project_names)

    if not selected_project:
        st.info("Select a project to edit its metadata")
        return

    row = df[df["name"] == selected_project].iloc[0]

    st.markdown(f"**Path:** `{row['path']}`")
    st.markdown(f"**Category:** {row['category']} | **Type:** {row['type']}")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        # Priority
        priority_options = {
            "1 - Critical": 1,
            "2 - High": 2,
            "3 - Normal": 3,
            "4 - Low": 4,
            "5 - Someday": 5
        }
        current_priority = [k for k, v in priority_options.items() if v == row["priority"]][0]
        new_priority = st.selectbox("Priority", list(priority_options.keys()),
                                     index=list(priority_options.keys()).index(current_priority))

        # Deadline
        current_deadline = row["deadline"].date() if pd.notna(row["deadline"]) else None
        new_deadline = st.date_input("Deadline", value=current_deadline)

        # Target date
        current_target = row["target_date"].date() if pd.notna(row["target_date"]) else None
        new_target = st.date_input("Target Date", value=current_target)

    with col2:
        # Client name
        new_client = st.text_input("Client Name", value=row["client_name"])

        # Budget hours
        new_budget = st.number_input("Budget Hours", value=row["budget_hours"] or 0.0, min_value=0.0)

        # Hours logged
        new_hours = st.number_input("Hours Logged", value=row["hours_logged"] or 0.0, min_value=0.0)

    # Tags
    current_tags = ", ".join(row["tags"]) if row["tags"] else ""
    new_tags = st.text_input("Tags (comma-separated)", value=current_tags)

    # Notes
    new_notes = st.text_area("Notes / Commentary", value=row["notes"], height=150)

    # Archive toggle
    new_archived = st.checkbox("Archived", value=row["archived"])

    # Save button
    if st.button("💾 Save Changes", type="primary"):
        updates = {}

        if priority_options[new_priority] != row["priority"]:
            updates["priority"] = priority_options[new_priority]

        if new_deadline != current_deadline:
            updates["deadline"] = datetime.combine(new_deadline, datetime.min.time()) if new_deadline else None

        if new_target != current_target:
            updates["target_date"] = datetime.combine(new_target, datetime.min.time()) if new_target else None

        if new_client != row["client_name"]:
            updates["client_name"] = new_client

        if new_budget != (row["budget_hours"] or 0.0):
            updates["budget_hours"] = new_budget

        if new_hours != (row["hours_logged"] or 0.0):
            updates["hours_logged"] = new_hours

        new_tags_list = [t.strip() for t in new_tags.split(",") if t.strip()]
        if new_tags_list != row["tags"]:
            updates["tags"] = new_tags_list

        if new_notes != row["notes"]:
            updates["notes"] = new_notes

        if new_archived != row["archived"]:
            updates["archived"] = new_archived

        if updates:
            update_project_metadata(selected_project, **updates)
            st.success(f"✓ Updated: {', '.join(updates.keys())}")
            st.rerun()
        else:
            st.info("No changes to save")


def render_decisions(df: pd.DataFrame):
    """Render pending decisions."""
    decisions_df = df[df["has_decision"] == True]

    if len(decisions_df) == 0:
        st.success("✅ No pending decisions!")
        return

    st.subheader(f"⚠️ {len(decisions_df)} Projects Need Decisions")

    for idx, row in decisions_df.iterrows():
        with st.expander(f"{row['name']} — {row['category']}"):
            col1, col2 = st.columns([3, 1])

            with col1:
                # Try to show decision from files
                files = get_project_files(row["path"])

                # Look for decision content in TODO or PROGRESS
                decision_content = None
                for fname, content in files.items():
                    if "decision" in content.lower() or "option a" in content.lower():
                        # Extract decision section
                        lines = content.split("\n")
                        in_decision = False
                        decision_lines = []
                        for line in lines:
                            if "decision" in line.lower() or "option" in line.lower():
                                in_decision = True
                            if in_decision:
                                decision_lines.append(line)
                                if len(decision_lines) > 20:
                                    break
                        if decision_lines:
                            decision_content = "\n".join(decision_lines)
                            break

                if decision_content:
                    st.markdown("**Decision needed:**")
                    st.code(decision_content, language="markdown")
                else:
                    st.markdown("*Decision details in project files*")

                st.markdown(f"**Path:** `{row['path']}`")

            with col2:
                if st.button("🚀 Open & Decide", key=f"dec_claude_{idx}"):
                    prompt = f"Review the pending decision in this project and help me make a choice. Look at TODO.md or PROGRESS.md for the decision context."
                    launch_claude_code(row["path"], row["name"], prompt)

                if st.button("📂 Open Files", key=f"dec_vscode_{idx}"):
                    open_in_vscode(row["path"])


def render_project_list(df: pd.DataFrame, show_category: bool = True):
    """Render the project list with expandable details."""

    # Sort options
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        sort_by = st.selectbox(
            "Sort by",
            ["name", "health", "completion", "last_activity"],
            key=f"sort_{id(df)}"
        )
    with col2:
        ascending = not st.checkbox("Descending", key=f"desc_{id(df)}")
    with col3:
        select_all = st.checkbox("Select all", key=f"sel_all_{id(df)}")
        if select_all:
            st.session_state.selected_projects = set(df["name"].tolist())

    df = df.sort_values(sort_by, ascending=ascending, na_position="last")

    st.caption(f"Showing {len(df)} projects")

    # Render expandable cards
    for idx, row in df.iterrows():
        # Health indicator
        health = row["health"]
        if health >= 70:
            health_icon = "🟢"
        elif health >= 40:
            health_icon = "🟡"
        else:
            health_icon = "🔴"

        # Build title
        badges = []
        if show_category:
            cat_emoji = {"client": "👤", "internal": "🏠", "tool": "🔧"}.get(row["category"], "")
            badges.append(cat_emoji)
        if row["has_decision"]:
            badges.append("⚠️")
        if row["git_dirty"]:
            badges.append("●")

        badge_str = " ".join(badges)
        title = f"{badge_str} {row['name']} — {health_icon} {health:.0f} | {row['completion']:.0f}%"

        with st.expander(title):
            # Selection checkbox
            selected = st.checkbox(
                "Select for batch",
                value=row["name"] in st.session_state.selected_projects,
                key=f"sel_{idx}"
            )
            if selected:
                st.session_state.selected_projects.add(row["name"])
            else:
                st.session_state.selected_projects.discard(row["name"])

            # Main content
            col1, col2 = st.columns([3, 1])

            with col1:
                # Project info
                st.markdown(f"**Path:** `{row['path']}`")

                if row["phase"]:
                    st.markdown(f"**Phase:** {row['phase']}")
                if row["next_action"]:
                    st.markdown(f"**Next:** {row['next_action']}")
                if row["git_branch"]:
                    st.markdown(f"**Branch:** `{row['git_branch']}`")

                # Activity
                if row["days_inactive"] is not None:
                    days = row["days_inactive"]
                    if days == 0:
                        st.markdown("**Activity:** Today")
                    elif days < 7:
                        st.markdown(f"**Activity:** {days} days ago")
                    elif days < 30:
                        st.markdown(f"**Activity:** {days // 7} weeks ago")
                    else:
                        st.markdown(f"**Activity:** ⚠️ {days // 30} months ago")

                # Progress files
                st.markdown("---")
                files = get_project_files(row["path"])
                if files:
                    file_tabs = st.tabs(list(files.keys()))
                    for tab, (fname, content) in zip(file_tabs, files.items()):
                        with tab:
                            st.code(content, language="markdown")

            with col2:
                st.markdown("**Actions**")

                if st.button("🚀 Claude Code", key=f"launch_{idx}", use_container_width=True):
                    context = get_project_context(row["path"], row["name"])
                    if launch_claude_code(row["path"], row["name"], context[:500]):
                        st.success("Launched!")

                if st.button("📂 VSCode", key=f"vscode_{idx}", use_container_width=True):
                    open_in_vscode(row["path"])
                    st.success("Opened!")

                if st.button("💻 Terminal", key=f"term_{idx}", use_container_width=True):
                    open_in_terminal(row["path"])
                    st.success("Opened!")

                if st.button("📁 Finder", key=f"finder_{idx}", use_container_width=True):
                    open_in_finder(row["path"])
                    st.success("Opened!")

                st.markdown("---")

                # Copy context
                if st.button("📋 Copy Context", key=f"ctx_{idx}", use_container_width=True):
                    context = get_project_context(row["path"], row["name"])
                    st.code(context, language=None)


def render_analytics(df: pd.DataFrame):
    """Render analytics charts."""

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Projects by Category")
        category_counts = df["category"].value_counts()
        st.bar_chart(category_counts)

    with col2:
        st.subheader("Health Distribution")
        health_bins = pd.cut(df["health"], bins=[0, 40, 70, 100], labels=["Critical", "Needs Work", "Healthy"])
        health_counts = health_bins.value_counts()
        st.bar_chart(health_counts)

    col3, col4 = st.columns(2)

    with col3:
        st.subheader("Completion Distribution")
        comp_bins = pd.cut(df["completion"], bins=[0, 25, 50, 75, 100], labels=["Early", "Quarter", "Half", "Near Done"])
        comp_counts = comp_bins.value_counts()
        st.bar_chart(comp_counts)

    with col4:
        st.subheader("Project Types")
        type_counts = df["type"].value_counts()
        st.bar_chart(type_counts)

    # Tables
    st.subheader("🏆 Top 10 Healthiest")
    top_10 = df.nlargest(10, "health")[["name", "category", "health", "completion"]]
    st.dataframe(top_10, use_container_width=True, hide_index=True)

    st.subheader("⚠️ Bottom 10 (Need Attention)")
    bottom_10 = df.nsmallest(10, "health")[["name", "category", "health", "completion", "days_inactive"]]
    st.dataframe(bottom_10, use_container_width=True, hide_index=True)

    st.subheader("🔥 Most Active (Recent Commits)")
    active = df[df["days_inactive"].notna()].nsmallest(10, "days_inactive")[["name", "category", "days_inactive", "completion"]]
    st.dataframe(active, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
