# 09 — Feature Completeness: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 1 HIGH / 3 MEDIUM / 4 LOW |
| Rating | **YELLOW** |

---

### FC-001: Dead `launch` command definition (first of two)

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/cli.py:390-550` |
| Status | Open |
| Effort | 2 SP |

The first `launch` command registration (line 390) is silently overwritten by the second (line 1578) because Click stores commands by name in a dict. The first definition includes `--filter`, `--parallel`, `--mode`, `--iterm`, `--tmux` flags and a `use_claudecoderun` branch — approximately 160 lines of code — that is completely unreachable. Running `pm launch --help` shows the second definition only.

Additionally, the `elif use_claudecoderun and len(projects) > 1:` branch in the dead code (line ~536) has a `break` statement that exits the loop after processing only the first project, silently dropping projects 2..N. This was never caught because the code is dead.

**Recommendation:** Delete lines 390–550 (the first `launch` definition). Verify CLAUDE.md does not reference the removed `--filter`, `--parallel`, or `--iterm` flags.

---

### FC-002: `pm/api/` module is empty — FastAPI declared but unbuilt

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/api/__init__.py`, `pyproject.toml` |
| Status | Open |
| Effort | 1 SP |

`pm/api/__init__.py` contains only `"""API module."""`. The pyproject.toml depends on `fastapi>=0.100.0` and `uvicorn>=0.23.0`. No routes, models, or server entrypoints exist. This is dead package structure that:
1. Adds ~10MB of unnecessary dependencies (fastapi + uvicorn + starlette)
2. Confuses contributors about whether a REST API is planned or abandoned

**Recommendation:** Either delete `pm/api/` and remove FastAPI/uvicorn from deps, or create a stub `pm/api/routes.py` with a plan comment for the agent coordination API.

---

### FC-003: `has_readme` detected but never stored

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/scanner/detector.py:21,141` vs `pm/database/models.py` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# detector.py:21 — in ProjectInfo dataclass
has_readme: bool = False

# detector.py:141 — detected during scan
project.has_readme = (path / 'README.md').exists()
```

`has_readme` is detected in every scan but the `Project` SQLAlchemy model has no `has_readme` column. The value is computed and then immediately discarded — it never reaches the database, health score, or dashboard. Compare to `has_claude_md` and `has_todo` which are stored and used in health scoring.

**Recommendation:** Add `has_readme = Column(Boolean, default=False)` to the Project model and add it to `_migrate_db()`. Consider incorporating it into health scoring (README presence is a proxy for project maturity).

---

### FC-004: Dashboard missing inline editors for `target_date`, `budget_hours`, `hours_logged`

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py` (no editor exists) |
| Status | Open |
| Effort | 2 SP |

The dashboard expander provides inline editing for priority, deadline, notes, and tags. But three PM-STATUS.md fields have no dashboard UI:
- `target_date` (soft completion target, distinct from deadline)
- `budget_hours` (estimated scope)
- `hours_logged` (time tracking)

These are visible in `pm edit --show` via CLI but cannot be set from the dashboard. Users managing client projects with hour budgets must use the CLI exclusively for these fields.

**Recommendation:** Add `target_date`, `budget_hours`, and `hours_logged` to the inline edit section of each project card expander.

---

### FC-005: No `pm delete` command — only archiving

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py` (missing) |
| Status | Open |
| Effort | 2 SP |

Projects can be archived via `pm edit <name> --archive` or through stale action workflows, but there is no way to permanently delete a project record from the database. If a project directory is deleted from disk, it stays in the database indefinitely and appears in stale reports. This is a data hygiene issue as the portfolio scales.

**Recommendation:** Add `pm delete <project_name> [--confirm]` that removes the DB record (not the directory). Alternatively, add a `pm gc` (garbage collect) command that removes DB records for paths that no longer exist on disk.

---

### FC-006: `pm shutdown` only supported for iTerm2

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:1684-1750`, `pm/terminal.py` |
| Status | Open |
| Effort | 3 SP |

`pm shutdown` works correctly for iTerm2 by finding PM-prefixed tabs via AppleScript and sending `/exit`. For Terminal.app (`--terminal` flag), the command prints a message and exits immediately without attempting any shutdown. This is documented behavior, but means users on macOS Sonoma (where Terminal.app is the default) get no shutdown support.

**Recommendation:** For Terminal.app, implement shutdown via `osascript` window enumeration. Terminal.app allows `tell application "Terminal" to do script ...` but lacks iTerm2's tab naming API — the workaround is to send `/exit` to all Terminal windows running `claude`.

---

### FC-007: ARCH-009 is already resolved — `docs history` and `docs status` exist

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:2188, 2268` |
| Status | **Fixed** |
| Effort | 0 SP |

The previous note that `docs history` and `docs status` were "documented in CLAUDE.md but not implemented" is incorrect. Both commands are fully implemented at lines 2188 and 2268 respectively. The implementations include project filtering, template filtering, and formatted Rich table output. No action needed — ARCH-009 should be marked resolved.

---

### FC-008: No un-scan / remove-project-from-DB operation

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py` (missing) |
| Status | Open |
| Effort | 1 SP |

When a project directory is moved, renamed, or deleted, its DB record becomes stale. The scanner will not remove it (it only adds/updates records for paths it finds). The only resolution is manual SQLite manipulation. A `pm scan --prune` flag that removes DB records for paths that no longer exist on disk would handle this automatically.

**Recommendation:** Add `--prune` flag to `pm scan` that deletes records where `os.path.exists(project.path)` is False after the scan completes.
