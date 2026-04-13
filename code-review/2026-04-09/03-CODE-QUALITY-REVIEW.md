# 03 — Code Quality Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 1 HIGH / 4 MEDIUM / 4 LOW |
| Rating | **YELLOW** |

---

### CQ-001: `tags_list` uses bare `except:` swallowing all JSON errors

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `pm/database/models.py:180-184` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
@property
def tags_list(self) -> list[str]:
    if self.tags:
        import json
        try:
            return json.loads(self.tags)
        except:
            return []
    return []
```

**Risk:** `except:` (no exception type) catches `KeyboardInterrupt`, `SystemExit`, and `MemoryError` in addition to `json.JSONDecodeError`. It also masks type errors (e.g., if `self.tags` is an integer from a migration bug) by silently returning `[]` instead of alerting that the data is corrupted.

**Recommendation:**
```python
except json.JSONDecodeError:
    return []
```

---

### CQ-002: Priority labels hardcoded in two places

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/database/models.py:172-173` and `pm/metadata.py:141-142` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# models.py:172
labels = {1: "Critical", 2: "High", 3: "Normal", 4: "Low", 5: "Someday"}

# metadata.py:141
priority_labels = {1: 'critical', 2: 'high', 3: 'normal', 4: 'low', 5: 'someday'}
```

Two different dicts with different capitalization conventions. Adding priority level 6 requires updating both.

**Recommendation:** Define a single `PRIORITY_LABELS: dict[int, str]` constant in `pm/database/models.py` and import it in `pm/metadata.py`.

---

### CQ-003: `import` statements inside function bodies

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:1415`, `:2055`, `:836`, `:1137`, `:1979` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# pm/cli.py:1415
import time

# pm/cli.py:2055
from datetime import timedelta

# pm/cli.py:836
from .metadata import ProjectMetadata
```

Imports inside functions are a code smell — they're harder to discover, slightly slower on repeated calls, and obscure the module's dependency graph. Standard practice is to put all imports at the top of the file.

**Recommendation:** Move all deferred imports to the top of `pm/cli.py`.

---

### CQ-004: Non-atomic file write in `write_pm_status`

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/metadata.py:186-190` |
| Status | Open |
| Effort | 2 SP |

**Code:**
```python
try:
    status_file.write_text(content)
    return True
except Exception as e:
    return False
```

`Path.write_text()` is not atomic — if the process is interrupted during write, the file is left partially written and the original notes content is lost (it was read into memory, modified, and the write started overwriting). This is particularly risky for the `notes` field which can be the user's only copy of project context.

**Recommendation:** Use a temp-file-then-rename pattern:
```python
import tempfile, os
tmp = status_file.with_suffix('.tmp')
try:
    tmp.write_text(content)
    os.replace(tmp, status_file)  # Atomic on POSIX
    return True
except Exception:
    tmp.unlink(missing_ok=True)
    return False
```

---

### CQ-005: `metadata.py` nearly untested (22% coverage)

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/metadata.py` |
| Status | Open |
| Effort | 3 SP |

The metadata sync module is the primary persistence mechanism for user-editable project data (notes, priorities, deadlines). It has only 22% test coverage — meaning `read_pm_status`, `parse_pm_status`, `write_pm_status`, and `sync_to_file` are essentially untested. Bugs in date parsing, tag parsing, and note preservation would not be caught.

---

### CQ-006: `launch` command's `use_claudecoderun` branch breaks after first project

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:517-536` (dead code — shadowed by ARCH-001) |
| Status | Moot (dead code) |
| Effort | 0 SP |

The `elif use_claudecoderun and len(projects) > 1:` branch has a `break` statement at line 536 that exits the `for i, proj in enumerate(projects)` loop after processing only the first project. This means projects 2..N are silently dropped when using `claudecoderun`. This is moot since this entire `launch` function is dead code (shadowed by ARCH-001), but illustrates the value of testing all code paths.

---

### CQ-007: UTC datetime inconsistency

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/database/models.py:63-67`, `pm/cli.py:93` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# models.py — uses datetime.utcnow() (deprecated in Python 3.12+)
return (self.deadline - datetime.utcnow()).days

# cli.py — mixes date sources
proj.last_activity = proj_info.last_commit_date  # This is tz-aware from dateutil.parser
```

`datetime.utcnow()` is deprecated in Python 3.12+ in favor of `datetime.now(timezone.utc)`. Additionally, `last_commit_date` from git log is parsed by `dateutil.parser.parse()` which may return timezone-aware datetimes, while `datetime.utcnow()` returns naive datetimes — comparing the two raises a `TypeError`.

**Recommendation:** Standardize on `datetime.now(timezone.utc)` throughout, and strip timezone info when storing to SQLite (which has no timezone support): `dt.replace(tzinfo=None)`.

---

### CQ-008: Dead code — `ItemStatus` import unused in key locations

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/cli.py:17` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
from .scanner.parser import ProgressParser, ProjectProgress, ItemStatus
```

`ItemStatus` is imported in `cli.py` but used in only one place: the scan loop's `items_complete` counter. `ProjectProgress` is imported but never type-annotated in function signatures (just used internally). These imports can be cleaned up.
