"""Streamlit dashboard for project manager."""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from pm.database.models import init_db, get_session, Project, ProgressItem

# Page config
st.set_page_config(
    page_title="Project Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize database
init_db()


def get_projects_df():
    """Load projects into a DataFrame."""
    session = get_session()
    projects = session.query(Project).all()

    data = []
    for p in projects:
        data.append({
            "name": p.name,
            "path": p.path,
            "category": p.category,
            "type": p.project_type,
            "completion": p.completion_pct or 0,
            "phase": p.current_phase or "",
            "status": p.current_status or "",
            "next_action": p.next_action or "",
            "has_decision": p.has_pending_decision,
            "git_dirty": p.git_dirty,
            "git_branch": p.git_branch or "",
            "last_activity": p.last_activity,
            "last_scanned": p.last_scanned,
            "has_claude_md": p.has_claude_md,
        })

    session.close()
    return pd.DataFrame(data)


def main():
    st.title("📊 Project Manager Dashboard")
    st.markdown("*Multi-project Claude Code orchestration*")

    # Load data
    df = get_projects_df()

    if df.empty:
        st.warning("No projects found. Run `pm scan ~/dev2` first.")
        return

    # Sidebar filters
    st.sidebar.header("Filters")

    categories = ["All"] + sorted(df["category"].unique().tolist())
    selected_category = st.sidebar.selectbox("Category", categories)

    if selected_category != "All":
        df = df[df["category"] == selected_category]

    # Completion filter
    completion_range = st.sidebar.slider(
        "Completion %",
        0, 100, (0, 100)
    )
    df = df[(df["completion"] >= completion_range[0]) & (df["completion"] <= completion_range[1])]

    # Flags filter
    show_decisions = st.sidebar.checkbox("Show only pending decisions", False)
    if show_decisions:
        df = df[df["has_decision"] == True]

    show_dirty = st.sidebar.checkbox("Show only uncommitted", False)
    if show_dirty:
        df = df[df["git_dirty"] == True]

    # Search
    search = st.sidebar.text_input("Search project name")
    if search:
        df = df[df["name"].str.contains(search, case=False)]

    # Main content
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Projects", len(df))

    with col2:
        avg_completion = df["completion"].mean() if len(df) > 0 else 0
        st.metric("Avg Completion", f"{avg_completion:.0f}%")

    with col3:
        decisions = df["has_decision"].sum()
        st.metric("Pending Decisions", int(decisions))

    with col4:
        dirty = df["git_dirty"].sum()
        st.metric("Uncommitted", int(dirty))

    st.divider()

    # Category breakdown
    st.subheader("Category Overview")

    col1, col2 = st.columns([1, 2])

    with col1:
        category_counts = df["category"].value_counts()
        st.bar_chart(category_counts)

    with col2:
        # Completion by category
        if len(df) > 0:
            completion_by_cat = df.groupby("category")["completion"].mean()
            st.bar_chart(completion_by_cat)

    st.divider()

    # Project list
    st.subheader(f"Projects ({len(df)})")

    # Sort options
    sort_col = st.selectbox(
        "Sort by",
        ["name", "completion", "last_activity", "category"],
        index=0
    )
    ascending = st.checkbox("Ascending", True)

    if sort_col == "last_activity":
        df = df.sort_values(sort_col, ascending=ascending, na_position="last")
    else:
        df = df.sort_values(sort_col, ascending=ascending)

    # Display as cards
    for idx, row in df.iterrows():
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 3, 2])

            with col1:
                # Name and category badge
                cat_colors = {"client": "🟢", "internal": "🔵", "tool": "🟡"}
                badge = cat_colors.get(row["category"], "⚪")
                st.markdown(f"### {badge} {row['name']}")

            with col2:
                # Progress bar
                completion = row["completion"]
                st.progress(completion / 100)
                st.caption(f"{completion:.0f}% complete")

            with col3:
                # Phase/Status
                if row["phase"]:
                    st.markdown(f"**Phase:** {row['phase'][:40]}")
                if row["next_action"]:
                    st.markdown(f"**Next:** {row['next_action'][:50]}")

            with col4:
                # Flags and actions
                flags = []
                if row["has_decision"]:
                    flags.append("⚠️ Decision")
                if row["git_dirty"]:
                    flags.append("● Dirty")

                if flags:
                    st.markdown(" ".join(flags))

                if st.button("Continue", key=f"continue_{idx}"):
                    st.session_state[f"continue_{row['name']}"] = True
                    st.info(f"Run: `pm continue {row['name']}`")

            st.divider()

    # Projects needing attention
    st.sidebar.divider()
    st.sidebar.subheader("Needs Attention")

    decision_projects = df[df["has_decision"] == True]["name"].tolist()
    if decision_projects:
        st.sidebar.markdown("**Pending Decisions:**")
        for name in decision_projects[:5]:
            st.sidebar.markdown(f"- {name}")

    stale_cutoff = datetime.now() - timedelta(days=30)
    stale_projects = df[
        (df["last_activity"].notna()) &
        (pd.to_datetime(df["last_activity"]) < stale_cutoff)
    ]["name"].tolist()

    if stale_projects:
        st.sidebar.markdown("**Stale (30+ days):**")
        for name in stale_projects[:5]:
            st.sidebar.markdown(f"- {name}")


if __name__ == "__main__":
    main()
