# Code Quality Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 0 |
| MEDIUM | 3 |
| LOW | 4 |

Overall code quality is solid: no `Any` type sprawl, no broad `except: pass` swallowing, no dead imports. The codebase follows consistent patterns for Rich table rendering, Click option declaration, and SQLAlchemy usage. The primary issues are deferred imports that should be top-level, an unused import carried from a prior refactor, and a few minor naming/consistency gaps.

---

### CQ-001: Deferred `import sys` Inside Command Callback

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:432` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
@main.command()
@click.option("--port", "-p", default=8501, help="Dashboard port")
def dashboard(port: int):
    """Launch the Streamlit dashboard."""
    import sys  # ← deferred import of stdlib module
    dashboard_path = Path(__file__).parent.parent / "dashboard" / "app.py"
```

`sys` is a standard library module with no import cost. Deferring it serves no purpose — it was likely left over from earlier conditional logic. Similarly, `import re as _re` and `import json as _json` appear deferred inside command callbacks at lines 1508, 2891–2892, while `re` and `json` are already imported at the module top (lines 3–4). `import subprocess as _sp` at line 2995 aliases a module already imported as `subprocess` at line 5.

**Recommendation:** Remove the deferred imports at lines 432, 1508, 2891, 2892, and 2995. Use the already-imported top-level names.

---

### CQ-002: `ItemStatus` Imported but Usage Warrants Review

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:20` |
| Status | Open (minor) |
| Effort | 0.5 SP |

**Code:**
```python
from .scanner.parser import ProgressParser, ProjectProgress, ItemStatus
```

`ItemStatus` is used at lines 207–209 for scan history construction — legitimate usage. However, the prior code review (April 9) identified `ItemStatus` as unused. It is now used, but the import also pulls in `ProjectProgress` which appears to only be used as a type hint context; verify that all three symbols are still required in the current code. A quick check confirms:

- `ProgressParser` — used at line 111
- `ProjectProgress` — used at line ~120 (type annotation, implicitly)
- `ItemStatus` — used at lines 207–209

All three are legitimately used. The TD-035 backlog item ("Remove unused ItemStatus import") can be closed — the import is correct.

**Recommendation:** Close TD-035 as no-op. No change needed.

---

### CQ-003: `tags_list` Property Uses Deferred `import json`

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/database/models.py:199` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
@property
def tags_list(self) -> list[str]:
    """Parse tags JSON to list."""
    if self.tags:
        import json  # ← deferred inside a hot property
        try:
            return json.loads(self.tags)
```

`json` is a stdlib module. Importing it inside a hot property (called once per project in every table render, and in every tag filter) adds unnecessary overhead. Python caches module imports after the first call, but the lookup cost is nonzero on every invocation.

**Recommendation:** Move `import json` to the module top of `models.py`.

---

### CQ-004: `sys` Import Missing from `pm/cli.py` Top-Level

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:3–10` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from typing import Optional
```

`sys` is used in the `dashboard` command (line 440: `sys.executable`) but is only imported deferred inside the command (line 432). If the deferred import is removed per CQ-001, `import sys` must be added to the module-level imports.

**Recommendation:** Add `import sys` to the top-level imports block when fixing CQ-001.

---

### CQ-005: Inconsistent `session.commit()` + `session.close()` Sequencing

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | Multiple sites in `pm/cli.py` |
| Status | Open |
| Effort | 2 SP |

**Description:** Most write paths follow `session.commit()` then `session.close()`, but several commands call `session.close()` in an `except` block *without* a preceding `session.rollback()`. This leaves an uncommitted transaction in SQLite's WAL journal, which can cause a `database is locked` error on the next write if the connection is not fully released.

Example (pm/cli.py — tags add):
```python
session = get_session()
try:
    project.tags = json.dumps(new_tags)
    session.commit()
    session.close()
except Exception as e:
    session.close()  # ← no rollback before close
    console.print(f"[red]Error: {e}[/red]")
```

**Recommendation:** Before `session.close()` in any except block, add `session.rollback()`:
```python
except Exception as e:
    session.rollback()
    session.close()
    console.print(f"[red]Error: {e}[/red]")
```
This is also addressed by the ARCH-003 context manager refactor — `db_session()` would handle rollback automatically.

---

### CQ-006: `platform` Imported Twice in Same File

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:3074,3103` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
# Line 3074 (inside one command)
import platform

# Line 3103 (inside another command, same file)
import platform
```

`platform` is imported deferred in two separate command callbacks rather than once at the top level.

**Recommendation:** Add `import platform` to the module-level imports and remove both deferred instances.

---

### CQ-007: No Type Annotations on Helper Functions

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:39,82,2993` |
| Status | Open (low priority) |
| Effort | 1 SP |

**Description:** Helper functions `apply_project_filter()`, `apply_urgency_filter()`, and `_send_imessage_triage()` lack return type annotations. This is a minor gap — the codebase does not use a type checker in CI, so missing annotations don't cause failures. The SQLAlchemy query return type is complex to annotate, but `_send_imessage_triage` at minimum should annotate `-> None`.

**Recommendation:** Low priority. Add when touching these functions for other reasons.

---

## Code Quality Strengths

- **No `except: pass` anti-pattern** — all exception handlers either log or re-raise.
- **Consistent use of `Optional[str]` typing** in Click option signatures.
- **`_utcnow()` helper** used consistently throughout to avoid deprecated `datetime.utcnow()`.
- **Rich table rendering** is consistent: `Table`, column definitions, and `console.print()` are used uniformly.
- **No magic numbers** for priority levels — `PRIORITY_LABELS` dict is the single source of truth.
- **`tags_list` property** cleanly wraps JSON parsing with error handling.
