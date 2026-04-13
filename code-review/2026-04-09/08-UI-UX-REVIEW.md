# 08 — UI/UX Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 0 HIGH / 5 MEDIUM / 5 LOW |
| Rating | **YELLOW** |

> **Note:** This is a Streamlit developer tool, not a consumer product. Accessibility and mobile standards are intentionally lower priority than for public apps. Findings are scoped to developer experience and workflow efficiency.

---

### UX-001: Pagination state not reset when filters change

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:877-895` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
st.session_state.page = 0  # Never reset here

# Pagination uses st.session_state.page
start_idx = st.session_state.page * PAGE_SIZE
page_df = filtered_df.iloc[start_idx:start_idx + PAGE_SIZE]
```

When the user applies a category filter or tag filter while on page 3, they remain on page 3 of the filtered result set. If the filtered result has fewer than 3 pages, they see an empty page with no projects. The user must manually click "← Prev" to see results.

**Recommendation:** Reset `st.session_state.page = 0` whenever a filter or sort control changes:
```python
# Before building filtered_df
if "last_filter" not in st.session_state or st.session_state.last_filter != (filter_cat, filter_type, tuple(filter_tags), sort_choice):
    st.session_state.page = 0
    st.session_state.last_filter = (filter_cat, filter_type, tuple(filter_tags), sort_choice)
```

---

### UX-002: Bulk batch doc generation blocks the UI with no cancel

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:414-420` |
| Status | Open |
| Effort | 3 SP |

**Code:**
```python
for i, (_, row) in enumerate(target_df.iterrows()):
    status_text.text(f"Generating {batch_template} for {row['name']}...")
    generate_doc(row["path"], row["name"], row["id"], batch_template)
    progress_bar.progress((i + 1) / len(target_df))
```

Batch generation runs sequentially in the main Streamlit thread. "All projects" scope can queue 200+ Claude Code subprocesses, each with a 300s timeout. The browser tab is unresponsive for the entire duration. There is no cancel button, and if the browser tab is closed, the generation loop continues in the background with no way to stop it.

**Recommendation:** Run batch generation via `ThreadPoolExecutor` (already implemented in `pm/docgen/executor.py:run_batch_generation`). Use `st.empty()` to poll progress from a background thread. Add a session state flag for cancellation.

---

### UX-003: Sort/filter selection UI labels are invisible without hover

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:798, 802, 805, 810` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
sort_choice = st.selectbox("Sort", list(sort_options.keys()), label_visibility="collapsed")
filter_cat = st.selectbox("Category", [...], label_visibility="collapsed")
filter_type = st.selectbox("Filter", [...], label_visibility="collapsed")
filter_tags = st.multiselect("Tags", all_tags, label_visibility="collapsed", placeholder="Tags...")
```

All four control labels use `label_visibility="collapsed"`. The only hint about what each control does is the default selection value or the placeholder text. For `filter_tags`, the only hint is `placeholder="Tags..."`. A first-time user cannot identify which dropdown is for sort vs category vs type filter without trial and error.

**Recommendation:** Use `label_visibility="visible"` or keep labels as column headers above the control row, removing the need to collapse them.

---

### UX-004: Column headers use cryptic abbreviations

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:899-906` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
hdr0.markdown("**Sel**")
hdr1.markdown("**St**")
hdr2.markdown("**Project**")
hdr3.markdown("**Health**")
```

"St" (status icons column) is not self-documenting. The column contains priority colored circles, git dirty dots, decision warning flags, and overdue clocks — none of which "St" prepares the user for. New users cannot decode the status icons without trial and error.

**Recommendation:** Add a legend tooltip or rename the column to "Status" and add a brief key below the headers:
```
● = git dirty  ⚠️ = pending decision  ⏰ = overdue
🔴/🟠/⚪/🔵 = priority (critical/high/normal/low)
```

---

### UX-005: Cache clear on every edit causes full 200+ project reload

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py:737, 747, 756, 767, 776, 851, 971` |
| Status | Open |
| Effort | 3 SP |

**Code:**
```python
st.cache_data.clear()  # Clears ALL cached data, not just the edited project
st.rerun()
```

`st.cache_data.clear()` invalidates the entire `load_projects()` cache. Every single inline edit — saving a tag, archiving a stale project, running a batch tag — triggers a full re-query and re-serialization of all 200+ projects. On a large dataset this causes a noticeable pause after every action.

**Recommendation:** Instead of clearing the cache, update `st.session_state` with the changed project data and merge it into the DataFrame on the next render, deferring cache invalidation to the natural 120s TTL.

---

### UX-006: Action buttons (🚀 📂 📁) provide no feedback on failure

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:1025-1030` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
if ac1.button("🚀", key=f"l_{idx}", help="Launch Claude"):
    launch_claude(row["path"], row["name"])
if ac2.button("📂", key=f"v_{idx}", help="VSCode"):
    subprocess.Popen(["code", row["path"]])
if ac3.button("📁", key=f"f_{idx}", help="Finder"):
    subprocess.Popen(["open", row["path"]])
```

All three action buttons invoke system calls with no try/except and no success/failure feedback. If `code` is not installed, `subprocess.Popen` raises `FileNotFoundError` which surfaces as an unhandled Streamlit exception. If `launch_claude` fails silently, the user has no idea the action wasn't taken.

**Recommendation:** Wrap each in try/except and use `st.toast()` (Streamlit 1.28+) for transient feedback.

---

### UX-007: "Run Prompt" result output has no size limit

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:985-986` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
if result["status"] == "success":
    st.success(f"Done in {result['duration']:.1f}s")
    st.markdown(result["output"])
```

A long Claude response (e.g., a generated roadmap) renders inline in the expander row, potentially pushing all projects below the fold. There is no truncation, scroll container, or expand/collapse for the output.

**Recommendation:** Limit inline display to 500 chars with a "View full transcript" expander or link to the saved transcript file.

---

### UX-008: No "select all visible" shortcut for bulk operations

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:836-856` |
| Status | Open |
| Effort | 1 SP |

The bulk tag and launch operations are the most powerful features of the dashboard, but there is no way to select all visible/filtered projects at once. A user wanting to tag all "client" category projects must click 25+ individual checkboxes.

**Recommendation:** Add a "Select All" checkbox in the `hdr0` column header that toggles all projects on the current page.

---

### UX-009: Docs tab renders arbitrary file content as Markdown with no size check

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:487-489` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
if doc_path.exists():
    content = doc_path.read_text()
    st.markdown(content)
```

`doc_path.read_text()` reads the entire file into memory regardless of size. A large generated document (e.g., a weekly summary with 50 projects) could be 50KB+ of markdown which takes several seconds to render and potentially crashes the browser tab if it contains deeply nested tables.

**Recommendation:** Add a size check: `if doc_path.stat().st_size > 50_000: st.text_area(..., height=400)` to use a scrollable text area for large files.

---

### UX-010: Activity tab has no client filter in the UI (only in CLI)

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py:500-572` |
| Status | Open |
| Effort | 1 SP |

The `digest_by_project` function accepts a `client_filter` parameter (used in `pm digest --client "Acme"`), but the Activity tab UI has no client filter control. Users managing 10+ clients have no way to focus the digest view on a single client's projects without switching to the CLI.

**Recommendation:** Add a `st.selectbox("Client", ["All"] + sorted_clients)` next to the date range controls and pass the selection to `digest_by_project`.
