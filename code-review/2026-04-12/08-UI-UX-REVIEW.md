# UI/UX Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |
| Interface | Streamlit web UI (5 tabs) + Click CLI |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 3 |

The dashboard covers the core project management workflows well. Recent Sprint B improvements added active filter labels, a "Flags" column header with icon legend, Select All checkbox, and inline budget/target date editing. The main gaps are: no keyboard navigation for the project grid, pagination controls that could be improved, and empty states that don't guide the user to the resolution.

---

### UX-001: Empty States Are Informational but Not Actionable

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:603,631,553` |
| Status | Open |
| Effort | 2 SP |

**Code:**
```python
st.info(f"No activity found for {range_label}. Run `pm scan` to capture data.")
st.info(f"No {tmpl.name} document found for {view_project}. Generate one above.")
```

Empty state messages use `st.info()` with text instructions but no direct action buttons. A user seeing "No activity found — run `pm scan`" must navigate to a terminal to act. Similarly, "No document found" shows above the generate section but doesn't scroll or expand it.

**Recommendation:**
1. On the Activity tab empty state, add a `st.button("Scan Now")` that triggers `pm scan` via subprocess and refreshes.
2. On the Docs tab empty state, auto-expand the "Generate Single Doc" section when no doc exists.

---

### UX-002: Pagination Controls Use Basic Text Buttons

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:1115–1122` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
if st.button("← Prev") and st.session_state.page > 0:
    st.session_state.page -= 1
st.markdown(f"<center>Page {st.session_state.page + 1} of {total_pages}</center>", unsafe_allow_html=True)
if st.button("Next →") and st.session_state.page < total_pages - 1:
    st.session_state.page += 1
```

The pagination uses `unsafe_allow_html=True` for centering, which Streamlit discourages in favor of `st.columns`. The `← Prev` / `Next →` buttons don't disable visually when at the first/last page (the guard is in Python but the button still renders as active), which is confusing.

**Recommendation:**
```python
col_prev, col_page, col_next = st.columns([1, 3, 1])
with col_prev:
    st.button("← Prev", disabled=st.session_state.page == 0, ...)
with col_page:
    st.caption(f"Page {st.session_state.page + 1} of {total_pages}")
with col_next:
    st.button("Next →", disabled=st.session_state.page >= total_pages - 1, ...)
```

---

### UX-003: No Confirmation on Destructive Actions (Archive, Combine, Replace)

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:787–849` (Stale tab) |
| Status | Open |
| Effort | 2 SP |

**Description:** The "Archive" action on the Stale tab does show a confirmation form (reason input + "Confirm Archive" button) — this is correct. However, "Combine" and "Replace" actions (lines 838–849) execute the database write immediately on button click without any undo path. These are high-impact operations: combining removes the source project from the DB; replacing marks it as archived.

**Recommendation:** Both "Confirm Combine" and "Confirm Replace" should require a text acknowledgement (similar to the existing Archive flow) before executing. The existing pattern is correct — apply it consistently.

---

### UX-004: Filter Reset Button Not Visible

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py` (Projects tab filter row) |
| Status | Open |
| Effort | 1 SP |

**Description:** The Projects tab has category, type, and tag filters with active-state labels (Sprint B improvement). However, there is no "Clear All Filters" button. A user who has applied multiple filters must individually clear each selectbox/multiselect to reset the view. This is a common UX pattern missing from the filter bar.

**Recommendation:** Add a "Clear Filters" button that resets `_sel_cat`, `_sel_type`, `_sel_tags` session state keys and bumps `_prev_filters` to trigger a page reset.

---

### UX-005: Agent Tab Results Have No Persistent Export

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:944` (Agents tab) |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
if st.button("Clear Results"):
    st.session_state.agent_results = []
```

Agent batch results are stored in session state only — they disappear on browser refresh or when the session ends. A user running a batch assessment at 2am via launchd has no way to view the results after the session expires.

**Recommendation:** Add a "Download Results" button using `st.download_button` that exports the current `agent_results` list as JSON or markdown. Results are already logged to `transcripts/` per project, but a summary export from the dashboard would be convenient for review.

---

## UI/UX Strengths

- **Active filter labels** clearly communicate which filters are applied (`"Category ▶ client"`).
- **"Flags" column** with icon legend (📋, ⚡, 🔀) provides at-a-glance status without cluttering the table.
- **Select All checkbox** in the header row follows the standard table selection pattern.
- **Inline editing** with immediate PM-STATUS.md sync means no "save" button confusion — the change is permanent on commit.
- **50KB doc size guard** prevents the browser from hanging on large generated files; the download button fallback is the correct UX pattern.
- **`st.toast()` on action buttons** provides non-blocking feedback (replaces modal errors).
- **Batch doc generation cancel button** uses the session-state flag pattern correctly — the running loop checks the flag on each iteration, allowing responsive cancellation.
