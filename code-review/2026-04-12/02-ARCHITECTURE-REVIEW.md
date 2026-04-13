# Architecture Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 1 |
| MEDIUM | 3 |
| LOW | 2 |

The architecture is well-suited to its single-user, local-first purpose: a SQLite-backed CLI + Streamlit dashboard orchestrating headless Claude Code sessions. The layered structure (scanner → models → CLI / dashboard) is clean. The agent subsystem (planner → runner → coordinator → escalation) has appropriate separation. The primary architectural concern is `pm/cli.py` as a 3,196-line god file with 34+ commands and no separation between command routing and business logic. The remaining issues are documentation drift and resource management patterns.

---

### ARCH-001: `pm/cli.py` is a God File (3,196 LOC, 34 commands)

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/cli.py` |
| Status | Open |
| Effort | 13 SP |

**Description:** All 34 CLI commands plus helper functions, AppleScript generators, iMessage senders, schedule management, and database queries live in a single 3,196-line file. Business logic (triage scoring, filter parsing, brief formatting, digest queries, shutdown orchestration) is inlined inside command callbacks rather than extracted to domain modules.

Notable examples of inlined logic:
- `pm/cli.py:2875–3005` — Triage command: assessment parsing, iMessage dispatch, recommendation rendering (~130 lines inline)
- `pm/cli.py:1660–1765` — `_shutdown_terminal_app()`: Terminal.app enumeration, context dispatch, /exit send (~105 lines)
- `pm/cli.py:39–80` — `apply_project_filter()` and `apply_urgency_filter()` — standalone utilities at module top
- `pm/cli.py:341–425` — `continue` command: 85-line callback that builds prompts, copies to clipboard, and runs subprocess

**Impact:** The file is difficult to navigate, test in isolation, and extend. The 24% line coverage on `cli.py` is partly explained by the difficulty of mocking business logic that is not extracted from Click callbacks.

**Recommendation:** Extract domain logic into dedicated modules over multiple sprints. Priority order:
1. `pm/filtering.py` — `apply_project_filter()`, `apply_urgency_filter()` (~40 lines, easy win)
2. `pm/shutdown.py` — `_shutdown_terminal_app()`, `_send_shutdown_commands()` (~150 lines)
3. `pm/imessage.py` — `_send_imessage_triage()`, consolidate with `pm/agent/escalation._send_imessage`
4. Triage business logic → `pm/triage.py`
5. Brief formatting → already partially in `pm/brief.py`; complete the extraction

---

### ARCH-002: `pm context` Command Referenced in Documentation but Does Not Exist

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `CLAUDE.md:22`, `pm/cli.py:341` |
| Status | Open |
| Effort | 0.5 SP |

**Code (CLAUDE.md:22):**
```markdown
pm context <project>         # Generate Claude Code continue prompt
```

**Code (pm/cli.py:341):**
```python
@main.command("continue")
```

The CLAUDE.md quick reference lists `pm context <project>` but the actual command is `pm continue`. This means any Claude Code session loading CLAUDE.md to orient itself will be given an incorrect command, and `pm context` invoked at the shell will return `No such command 'context'`.

**Recommendation:** Update `CLAUDE.md:22` to match the actual command name:
```markdown
pm continue [project]        # Generate Claude Code continue prompt
```
Or add a `pm context` alias that calls `pm continue` for backwards compatibility.

---

### ARCH-003: Session Lifecycle Not Protected by `try/finally`

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py` (29 `get_session()` calls, 56 `session.close()` calls) |
| Status | Open |
| Effort | 5 SP |

**Code (example from pm/cli.py:237–338):**
```python
session = get_session()
projects = session.query(Project).filter(...)...
# ... 100 lines of logic ...
session.close()  # bare close — not protected by try/finally
```

**Description:** All 29 session-opening sites use the bare pattern `session = get_session()` followed by `session.close()` at the end of happy-path flow. No `try/finally` guards ensure `close()` is called when an exception occurs mid-function. If an exception is raised before `session.close()` (e.g., during a scan loop iteration or a formatting call), the SQLite connection leaks until the process exits.

SQLite's single-writer constraint means a leaked open session can block subsequent write operations, manifesting as `OperationalError: database is locked` in long-running or multi-threaded scenarios (the agent batch coordinator uses `ThreadPoolExecutor`).

**Recommendation:** Use a context manager to guarantee session cleanup. A minimal approach:
```python
# Option A: contextlib.closing
from contextlib import closing
with closing(get_session()) as session:
    projects = session.query(Project)...
    session.commit()

# Option B: Add a context manager helper to models.py
@contextmanager
def db_session():
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```
Apply to all 29 call sites. Can be done file-by-file across sprints without affecting behavior.

---

### ARCH-004: Duplicate Filter Parsing Logic

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:39–80` and `pm/cli.py:370–387` |
| Status | Open |
| Effort | 2 SP |

**Code (cli.py:370–387 — duplicate in `continue` command):**
```python
elif filter_str:
    if filter_str.startswith("type:"):
        category = filter_str.split(":")[1]
        query = query.filter(Project.category == category)
    elif filter_str.startswith("priority:"):
        ...
```

`apply_project_filter()` at line 39 is the canonical filter helper, but the `continue` command at line 373 re-implements a subset of the same logic inline. Any extension to filter syntax must be applied in two places.

**Recommendation:** Replace the inline filter block in `continue` with a call to `apply_project_filter()`.

---

### ARCH-005: `pm dashboard` Command Does Not Pass `--server.address`

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:440` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path),
    "--server.port", str(port)])
```

The `pm dashboard` CLI command launches Streamlit without `--server.address 127.0.0.1`, unlike `dashboard.sh` which correctly passes this flag. Users who launch via `pm dashboard` (rather than `dashboard.sh`) get a dashboard that binds to all interfaces.

**Recommendation:** Add `"--server.address", "127.0.0.1"` to the subprocess args list.

---

### ARCH-006: `pm/digest.py` Shared Module is Under-Used in Dashboard

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `dashboard/app.py`, `pm/digest.py` |
| Status | Open |
| Effort | 2 SP |

**Description:** `pm/digest.py` was extracted as a shared query module for CLI + dashboard use. The dashboard imports `digest_by_project` and `digest_by_day`, but the "Stale" tab in the dashboard duplicates a stale-detection query that is also implemented in `pm/cli.py:1242` (`pm stale`). There is no shared `pm/stale.py` module; both implementations calculate staleness independently.

**Recommendation:** Extract the stale-detection query from `pm/cli.py` into `pm/digest.py` (or a new `pm/queries.py`) and have both the CLI command and the dashboard import from it. This ensures the 30-day threshold and archived exclusion logic stay in sync.

---

## Architecture Strengths (No Changes Needed)

- **Module boundaries are clean.** `pm/scanner/`, `pm/agent/`, `pm/docgen/` are well-contained subsystems with clear interfaces.
- **Agent orchestration pipeline is well-structured.** `planner → runner → coordinator → escalation` follows a sensible two-phase assess-then-execute pattern with a clean `AgentResult` return type.
- **`pm/terminal.py` centralization.** All AppleScript generation is in one place, used by CLI, dashboard, and shell scripts — no duplication of escape logic (except the one new gap in `_send_imessage_triage`).
- **`_bump_cache()` pattern in dashboard** avoids global cache invalidation while ensuring data freshness after mutations.
- **Migration registry pattern** in `models.py` is clean and idempotent — versions are checked before applying, and the migration table is created on first run.
