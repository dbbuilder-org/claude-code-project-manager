# 02 — Architecture Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 3 HIGH / 4 MEDIUM / 2 LOW |
| Rating | **YELLOW** |

---

### ARCH-001: Duplicate `launch` command silently shadows the first

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/cli.py:398` and `pm/cli.py:1578` |
| Status | Open |
| Effort | 2 SP |

**Code:**
```python
# First registration at line 398:
@main.command()
@click.option("--filter", "-f", ...)
@click.option("--parallel", "-p", ...)
def launch(project_names: tuple, filter_str, parallel, mode, dry_run, iterm, tmux):
    ...

# Second registration at line 1578 — OVERWRITES the first:
@main.command()
@click.argument("target", default="10")
@click.option("--dirty-only", "-d", ...)
def launch(target: str, dirty_only: bool, dry_run: bool, terminal: bool):
    ...
```

**Risk:** Click stores commands by name in a dict. The second `@main.command()` with name `launch` silently overwrites the first. All CLI options on the original `launch` (`--filter`, `--parallel`, `--mode`, `--iterm`, `--tmux`) are dead code — they are never reachable. The CLAUDE.md documentation refers to the old signature. This is a silent regression.

**Recommendation:** Remove the first `launch` definition (lines 390–550). The second definition (lines 1573–1673) is the current, correct one. Audit CLAUDE.md for any references to the old `--filter`/`--parallel` flags.

---

### ARCH-002: Global mutable database state is not thread-safe

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/database/models.py:275-338` |
| Status | Open |
| Effort | 3 SP |

**Code:**
```python
_engine = None
_SessionLocal = None

def init_db(db_path: Optional[Path] = None) -> None:
    global _engine, _SessionLocal
    ...

def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()
```

**Risk:** Module-level globals for engine and session factory are not thread-safe. The Streamlit dashboard creates multiple threads (one per user interaction), and the agent orchestrator will create many concurrent threads. Two threads calling `init_db()` simultaneously will race, potentially creating duplicate engines or partially initialized state.

**Recommendation:** Use a threading lock and a singleton pattern:
```python
import threading
_lock = threading.Lock()
_engine = None
_SessionLocal = None

def init_db(db_path=None):
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            return
        ...
```

---

### ARCH-003: Manual SQL schema migration without transaction safety

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/database/models.py:279-313` |
| Status | Open |
| Effort | 8 SP |

**Risk:** The `_migrate_db()` function adds columns with raw `ALTER TABLE` SQL in a loop with no transaction wrapping the full migration. If the process is killed mid-migration (e.g., Ctrl+C, OOM), the schema is left partially updated. Subsequent `init_db()` calls will try to add already-added columns, which `except Exception: pass` silently swallows — but the schema state is now undefined.

Additionally, there is no migration version tracking, so there's no way to determine which migrations have been applied or roll back to a known state.

**Recommendation (short-term):** Wrap all `ALTER TABLE` calls in a single `BEGIN`/`COMMIT` transaction block.

**Recommendation (long-term):** Adopt Alembic for proper schema versioning. This is essential before the agent tables are added, as those will require reliable forward/backward migration.

---

### ARCH-004: Headless execution logic duplicated in 3 places

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:1433-1503`, `dashboard/app.py:170-241`, `pm/docgen/executor.py:25-135` |
| Status | Open |
| Effort | 3 SP |

All three files build identical `subprocess.run(["claude", "-p", ...])` command lists, handle `TimeoutExpired` and `FileNotFoundError`, and write transcript files. When a flag changes (e.g., `--output-format` or a new auth option), it must be updated in 3 places.

**Recommendation:** `pm/docgen/executor.py:run_doc_generation` is the canonical implementation. Both `pm/cli.py:run_prompt` and `dashboard/app.py:_run_prompt_on_project` should delegate to it rather than reimplement.

---

### ARCH-005: `_sync_project` helper defined twice

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:1135` and `pm/cli.py:1135` area, also `dashboard/app.py:127` as `_sync_project_to_file` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# pm/cli.py:1135
def _sync_project(project: Project) -> None:
    """Sync project metadata to PM-STATUS.md."""
    from .metadata import ProjectMetadata
    meta = ProjectMetadata(...)
    sync_to_file(Path(project.path), **vars(meta))

# dashboard/app.py:127
def _sync_project_to_file(project: Project):
    """Sync all project metadata to PM-STATUS.md."""
    meta = ProjectMetadata(...)
    sync_to_file(Path(project.path), **vars(meta))
```

These are identical functions. Any change to the sync logic (e.g., adding a new metadata field) must be applied in both places.

**Recommendation:** Move to `pm/metadata.py` as a utility function `sync_project_to_file(project: Project)` that both CLI and dashboard import.

---

### ARCH-006: Filter parsing logic repeated across 6+ commands

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:196-206`, `:336-341`, `:433-448`, `:869-878`, `:1107-1111`, `:2013-2022` |
| Status | Open |
| Effort | 2 SP |

**Code (repeated 6+ times):**
```python
if filter_str.startswith("type:"):
    category = filter_str.split(":")[1]
    query = query.filter(Project.category == category)
elif filter_str.startswith("status:"):
    ...
```

**Recommendation:** Extract to `pm/cli.py`:
```python
def apply_project_filter(query, filter_str: str):
    """Apply a standard filter string to a Project query."""
    if filter_str.startswith("type:"):
        query = query.filter(Project.category == filter_str.split(":")[1])
    elif filter_str.startswith("priority:"):
        query = query.filter(Project.priority == int(filter_str.split(":")[1]))
    ...
    return query
```

---

### ARCH-007: FastAPI surface declared but never built

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/api/__init__.py` (empty), `pyproject.toml` |
| Status | Open |
| Effort | 1 SP |

`pyproject.toml` depends on `fastapi>=0.100.0` and `uvicorn>=0.23.0`, and `pm/api/__init__.py` exists but is empty. This suggests a REST API was planned but never implemented. This is dead structure that confuses contributors.

**Recommendation:** Either delete `pm/api/` and remove FastAPI/uvicorn from deps, or create a stub `pm/api/routes.py` with a plan comment.

---

### ARCH-008: Terminal detection duplicated in shell scripts

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `scripts/claude-launch.sh`, `scripts/claude-tmux.sh` vs `pm/terminal.py` |
| Status | Open |
| Effort | 2 SP |

Both shell scripts contain their own iTerm2 detection logic (`[ -d "/Applications/iTerm.app" ]`). When the detection logic changes (e.g., supporting Ghostty or WezTerm), it must be updated in 3 places.

**Recommendation:** Shell scripts should call `python -c "from pm.terminal import detect_terminal; print(detect_terminal().value)"` to leverage the shared module.

---

### ARCH-009: `docs history` and `docs status` subcommands missing

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | CLAUDE.md documentation vs `pm/cli.py` |
| Status | Open |
| Effort | 3 SP |

CLAUDE.md documents `pm docs history [project]` and `pm docs status [project]` but these commands are not implemented in `pm/cli.py`. The `docs` group only has `list` and `generate`.
