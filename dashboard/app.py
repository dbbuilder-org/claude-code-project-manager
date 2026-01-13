"""Streamlit dashboard for project manager."""

import sys
import subprocess
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
</style>
""", unsafe_allow_html=True)

# Initialize database
init_db()


def get_projects_data():
    """Load projects with health scores."""
    session = get_session()
    projects = session.query(Project).all()

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
        })

    session.close()
    return pd.DataFrame(data)


def launch_project(project_path: str, project_name: str):
    """Launch Claude Code for a project."""
    script_path = Path(__file__).parent.parent / "scripts" / "claude-launch.sh"
    if script_path.exists():
        subprocess.Popen([str(script_path), project_name])
        return True
    return False


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
        st.code("cd ~/dev2/project-manager && source venv/bin/activate && pm scan ~/dev2")
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

        # Search
        search = st.text_input("🔎 Search", placeholder="Project name...")
        if search:
            df = df[df["name"].str.contains(search, case=False, na=False)]

        st.divider()

        # Quick stats
        st.header("📈 Quick Stats")
        total = len(df)
        avg_health = df["health"].mean() if total > 0 else 0
        avg_completion = df["completion"].mean() if total > 0 else 0

        st.metric("Projects", total)
        st.metric("Avg Health", f"{avg_health:.0f}/100")
        st.metric("Avg Completion", f"{avg_completion:.0f}%")

        # Alerts
        decisions = df[df["has_decision"] == True]
        if len(decisions) > 0:
            st.warning(f"⚠️ {len(decisions)} pending decisions")

        stale = df[df["days_inactive"].notna() & (df["days_inactive"] > 60)]
        if len(stale) > 0:
            st.error(f"🔴 {len(stale)} projects inactive 60+ days")

    # Main content tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📋 All Projects", "🟢 Clients", "🔥 Needs Attention", "📊 Analytics"])

    with tab1:
        render_project_list(df)

    with tab2:
        client_df = df[df["category"] == "client"]
        if len(client_df) > 0:
            render_project_list(client_df, show_category=False)
        else:
            st.info("No client projects found")

    with tab3:
        # Projects needing attention
        attention_df = df[
            (df["has_decision"] == True) |
            (df["health"] < 40) |
            (df["days_inactive"].notna() & (df["days_inactive"] > 30))
        ].sort_values("health")
        if len(attention_df) > 0:
            render_project_list(attention_df, highlight_issues=True)
        else:
            st.success("✅ All projects are healthy!")

    with tab4:
        render_analytics(df)


def render_project_list(df: pd.DataFrame, show_category: bool = True, highlight_issues: bool = False):
    """Render the project list with cards."""

    # Sort options
    col1, col2 = st.columns([3, 1])
    with col1:
        sort_by = st.selectbox(
            "Sort by",
            ["health", "completion", "name", "last_activity"],
            key=f"sort_{id(df)}"
        )
    with col2:
        ascending = st.checkbox("Ascending", key=f"asc_{id(df)}")

    df = df.sort_values(sort_by, ascending=ascending, na_position="last")

    # Render cards
    for idx, row in df.iterrows():
        # Determine health color
        health = row["health"]
        if health >= 70:
            health_color = "🟢"
            health_class = "health-high"
        elif health >= 40:
            health_color = "🟡"
            health_class = "health-medium"
        else:
            health_color = "🔴"
            health_class = "health-low"

        with st.container():
            cols = st.columns([4, 2, 2, 3, 2])

            # Column 1: Name and badges
            with cols[0]:
                badges = []
                if show_category:
                    cat_emoji = {"client": "🟢", "internal": "🔵", "tool": "🟡"}.get(row["category"], "⚪")
                    badges.append(cat_emoji)
                if row["has_decision"]:
                    badges.append("⚠️")
                if row["git_dirty"]:
                    badges.append("●")

                badge_str = " ".join(badges)
                st.markdown(f"### {badge_str} {row['name']}")

                if row["phase"]:
                    st.caption(f"📍 {row['phase'][:50]}")

            # Column 2: Health
            with cols[1]:
                st.markdown(f"**Health:** {health_color} {health}")
                st.progress(health / 100)

            # Column 3: Completion
            with cols[2]:
                completion = row["completion"]
                st.markdown(f"**Progress:** {completion:.0f}%")
                st.progress(completion / 100)

            # Column 4: Activity
            with cols[3]:
                if row["days_inactive"] is not None:
                    days = row["days_inactive"]
                    if days == 0:
                        activity = "Today"
                    elif days == 1:
                        activity = "Yesterday"
                    elif days < 7:
                        activity = f"{days} days ago"
                    elif days < 30:
                        activity = f"{days // 7} weeks ago"
                    else:
                        activity = f"{days // 30} months ago"

                    if days > 30:
                        st.markdown(f"**Activity:** 🔴 {activity}")
                    elif days > 14:
                        st.markdown(f"**Activity:** 🟡 {activity}")
                    else:
                        st.markdown(f"**Activity:** 🟢 {activity}")
                else:
                    st.markdown("**Activity:** —")

                if row["next_action"]:
                    st.caption(f"Next: {row['next_action'][:40]}")

            # Column 5: Actions
            with cols[4]:
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("🚀", key=f"launch_{idx}", help="Launch Claude Code"):
                        if launch_project(row["path"], row["name"]):
                            st.success("Launched!")
                        else:
                            st.error("Launch failed")

                with col_b:
                    if st.button("📋", key=f"copy_{idx}", help="Copy context"):
                        context = get_project_context(row["path"], row["name"])
                        st.session_state[f"context_{row['name']}"] = context
                        st.info("Context ready - see below")

                # Show context if copied
                if st.session_state.get(f"context_{row['name']}"):
                    st.code(st.session_state[f"context_{row['name']}"], language=None)

            st.divider()


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
        st.subheader("Completion by Category")
        completion_by_cat = df.groupby("category")["completion"].mean()
        st.bar_chart(completion_by_cat)

    with col4:
        st.subheader("Average Health by Category")
        health_by_cat = df.groupby("category")["health"].mean()
        st.bar_chart(health_by_cat)

    # Top projects table
    st.subheader("🏆 Top 10 Healthiest Projects")
    top_10 = df.nlargest(10, "health")[["name", "category", "health", "completion"]]
    st.dataframe(top_10, use_container_width=True)

    st.subheader("⚠️ Projects Needing Attention")
    bottom_10 = df.nsmallest(10, "health")[["name", "category", "health", "completion", "days_inactive"]]
    st.dataframe(bottom_10, use_container_width=True)


if __name__ == "__main__":
    main()
