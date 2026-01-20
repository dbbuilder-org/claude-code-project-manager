"""Streamlit dashboard for project manager - Optimized version."""

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
from pm.metadata import sync_to_file, PM_STATUS_FILENAME, ProjectMetadata

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


@st.cache_data(ttl=120)
def load_projects():
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
                days_inactive = (datetime.utcnow() - p.last_activity).days

            # Truncate commit message
            commit_msg = p.last_commit_msg or ""
            if len(commit_msg) > 60:
                commit_msg = commit_msg[:57] + "..."

            data.append({
                "name": p.name,
                "path": p.path,
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
            })
        return pd.DataFrame(data)
    finally:
        session.close()


def launch_claude(path: str, name: str):
    """Launch Claude Code in iTerm2."""
    script = f'''
    tell application "iTerm"
        activate
        tell current window
            create tab with default profile
            tell current session
                write text "cd '{path}' && transcript && claude --dangerously-skip-permissions --continue"
            end tell
        end tell
    end tell
    '''
    subprocess.Popen(["osascript", "-e", script])


def launch_batch(paths_names: list):
    """Launch multiple projects."""
    import time
    for path, name in paths_names:
        launch_claude(path, name)
        time.sleep(0.5)


def generate_report(report_type: str, df: pd.DataFrame):
    """Generate a report using headless Claude."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"~/dev2/project-manager/reports/{report_type}_{timestamp}.md"

    # Create reports directory
    os.makedirs(os.path.expanduser("~/dev2/project-manager/reports"), exist_ok=True)

    # Build project summary for the prompt
    if report_type == "weekly":
        recent = df.nlargest(20, "last_commit") if "last_commit" in df.columns else df.head(20)
        prompt = f"""Generate a weekly project status summary report in markdown format.

Projects with recent activity:
{recent[['name', 'category', 'completion', 'health', 'commit_msg']].to_string()}

Include:
1. Executive summary (2-3 sentences)
2. Projects with significant progress this week
3. Projects needing attention (low health or overdue)
4. Recommended priorities for next week

Save to: {output_file}
"""
    else:  # status
        prompt = f"""Generate a comprehensive project status report in markdown format.

All {len(df)} projects summary:
- By category: {df['category'].value_counts().to_dict()}
- Average health: {df['health'].mean():.0f}
- Average completion: {df['completion'].mean():.0f}%
- Projects with decisions needed: {df['has_decision'].sum()}
- Overdue projects: {df['is_overdue'].sum()}

Top 10 by urgency:
{df.nlargest(10, 'urgency')[['name', 'priority_label', 'health', 'completion']].to_string()}

Save to: {output_file}
"""

    # Launch headless Claude
    cmd = f'claude -p "{prompt}" --output-format text > {output_file}'
    script = f'''
    tell application "iTerm"
        activate
        tell current window
            create tab with default profile
            tell current session
                write text "cd ~/dev2/project-manager && {cmd}"
            end tell
        end tell
    end tell
    '''
    subprocess.Popen(["osascript", "-e", script])
    return output_file


def main():
    st.title("📊 Project Manager")

    # Load data
    with st.spinner("Loading projects..."):
        df = load_projects()

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

    # Controls row
    ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([2, 1, 1, 2])

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
        filter_cat = st.selectbox("Category", ["All"] + sorted(df["category"].unique().tolist()), label_visibility="collapsed")

    with ctrl3:
        filter_type = st.selectbox("Filter", ["All", "Dirty", "Decisions", "Overdue"], label_visibility="collapsed")

    with ctrl4:
        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            if st.button("🚀 Top 10", use_container_width=True):
                sorted_df = df.sort_values(sort_col, ascending=sort_asc, na_position="last").head(10)
                launch_batch([(r["path"], r["name"]) for _, r in sorted_df.iterrows()])
                st.success("Launched 10!")
        with bcol2:
            if st.button("📊 Weekly", use_container_width=True):
                f = generate_report("weekly", df)
                st.info(f"Generating: {f}")
        with bcol3:
            if st.button("📋 Status", use_container_width=True):
                f = generate_report("status", df)
                st.info(f"Generating: {f}")

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
    hdr1, hdr2, hdr3, hdr4, hdr5, hdr6, hdr7 = st.columns([0.5, 2.5, 0.8, 0.8, 1, 1, 1.2])
    hdr1.markdown("**St**")
    hdr2.markdown("**Project**")
    hdr3.markdown("**Health**")
    hdr4.markdown("**Done**")
    hdr5.markdown("**Last Activity**")
    hdr6.markdown("**Last Commit**")
    hdr7.markdown("**Actions**")
    st.divider()

    # Render projects as rows
    for idx, row in page_df.iterrows():
        col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 2.5, 0.8, 0.8, 1, 1, 1.2])

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
        with col2:
            with st.expander(f"**{row['name']}**", expanded=False):
                if row["commit_msg"]:
                    st.caption(f"💬 {row['commit_msg']}")
                st.text(f"📁 {row['path']}")
                if row["next_action"]:
                    st.markdown(f"**Next:** {row['next_action']}")
                if row["notes"]:
                    st.info(row["notes"])

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
                launch_claude(row["path"], row["name"])
            if ac2.button("📂", key=f"v_{idx}", help="VSCode"):
                subprocess.Popen(["code", row["path"]])
            if ac3.button("📁", key=f"f_{idx}", help="Finder"):
                subprocess.Popen(["open", row["path"]])


if __name__ == "__main__":
    main()
