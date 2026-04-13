# 01 — Security Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 2 HIGH / 3 MEDIUM / 3 LOW |
| Rating | **YELLOW** |

---

### SEC-001: Shell injection via `shell=True` in tmux path

| Field | Value |
|-------|-------|
| Severity | HIGH |
| CWE | CWE-78 |
| Location | `pm/cli.py:511` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
cmd = f"tmux new-session -d -s '{session_name}' -c '{project_path}' 'claude --resume || claude'"
if not dry_run:
    result = subprocess.run(cmd, shell=True, capture_output=True)
```

**Risk:** `session_name` and `project_path` are derived from database values (project name and path). If a project name contains shell metacharacters (`'`, `;`, `$(`, `` ` ``), the `shell=True` call allows arbitrary command execution. An attacker who can write to the SQLite database or craft a malicious project directory name can achieve code execution.

**Recommendation:** Use a list-form command and avoid `shell=True`:
```python
cmd = ["tmux", "new-session", "-d", "-s", session_name, "-c", str(project_path),
       "claude --resume || claude"]
subprocess.run(cmd, capture_output=True)
```

---

### SEC-002: Path traversal in transcript directory

| Field | Value |
|-------|-------|
| Severity | HIGH |
| CWE | CWE-22 |
| Location | `pm/cli.py:1482`, `dashboard/app.py:213` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
# pm/cli.py:1482
transcript_dir = Path(__file__).parent.parent / "transcripts" / project.name
transcript_dir.mkdir(parents=True, exist_ok=True)
```

**Risk:** `project.name` is written directly into a file path without sanitization. A project named `../../etc` or `../scripts` would write transcript files outside the `transcripts/` directory. The `mkdir(parents=True)` call makes this worse by creating arbitrary directories.

**Recommendation:** Sanitize `project.name` before using as a path component:
```python
safe_name = re.sub(r'[^\w\-]', '_', project.name)
transcript_dir = Path(__file__).parent.parent / "transcripts" / safe_name
```

---

### SEC-003: Unauthenticated Streamlit dashboard

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| CWE | CWE-306 |
| Location | `dashboard/app.py` (entire file) |
| Status | Open |
| Effort | 2 SP |

**Risk:** The dashboard exposes full project metadata, inline editing, and headless Claude execution with no authentication. If the Streamlit port (8501) is reachable on the network (not just localhost), any user can read all project metadata, modify priorities/deadlines, run arbitrary prompts via Claude, and launch terminal sessions.

**Recommendation:** Either bind strictly to localhost (`--server.address 127.0.0.1` in `dashboard.sh`) or add Streamlit's built-in authentication. The current `dashboard.sh` should enforce `--server.address localhost`.

---

### SEC-004: Silent exception swallowing in schema migration

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| CWE | CWE-390 |
| Location | `pm/database/models.py:304-308` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
try:
    conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"))
    conn.commit()
except Exception:
    pass  # Column might already exist
```

**Risk:** The bare `except Exception: pass` swallows all errors, including permission errors, disk-full errors, and malformed SQL. A partial migration (some columns added, some not) could corrupt the schema silently, leading to hard-to-diagnose runtime failures.

**Recommendation:** Catch only the specific SQLite error for duplicate columns (`OperationalError` with "duplicate column name"), log all other errors:
```python
from sqlalchemy.exc import OperationalError
try:
    conn.execute(...)
    conn.commit()
except OperationalError as e:
    if "duplicate column name" not in str(e):
        raise  # Re-raise unexpected errors
```

---

### SEC-005: `--dangerously-skip-permissions` hardcoded in subprocess calls

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| CWE | CWE-250 |
| Location | `pm/cli.py:1436`, `dashboard/app.py:178`, `pm/docgen/executor.py:58` |
| Status | Open (by design) |
| Effort | 3 SP |

**Code:**
```python
cmd = [
    "claude", "-p", prompt,
    "--output-format", "text",
    "--dangerously-skip-permissions",
    "--max-budget-usd", str(budget),
]
```

**Risk:** All headless Claude invocations run with `--dangerously-skip-permissions`, meaning spawned agents can write, edit, and execute arbitrary files within the project directory without any permission gates. While intentional for automation, this is a significant blast radius if a malicious or confused prompt causes destructive changes.

**Recommendation:** For the upcoming agent system, use `--permission-mode acceptEdits` for agents that need to write, and reserve `--dangerously-skip-permissions` only for read-only analysis tasks. Document this trade-off in CLAUDE.md.

---

### SEC-006: AppleScript injection via project names (partial mitigation)

| Field | Value |
|-------|-------|
| Severity | LOW |
| CWE | CWE-74 |
| Location | `pm/terminal.py:57-59` |
| Status | Partially mitigated |
| Effort | 1 SP |

**Code:**
```python
def _escape_applescript(text: str) -> str:
    """Escape special characters for AppleScript string literals."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
```

**Risk:** The escaping function only handles `\` and `"`. AppleScript string literals can also be broken by newlines, null bytes, or certain Unicode characters. A project path containing `\n` could break the AppleScript execution.

**Recommendation:** Add newline and null stripping:
```python
return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "").replace("\x00", "")
```

---

### SEC-007: No .gitignore for sensitive data files

| Field | Value |
|-------|-------|
| Severity | LOW |
| CWE | CWE-312 |
| Location | Repository root (no `.gitignore` verified) |
| Status | Open |
| Effort | 0.5 SP |

**Risk:** `data/projects.db` contains all project metadata including notes, client names, deadlines, and budget information. `transcripts/` may contain sensitive project context. Neither is confirmed to be in `.gitignore`.

**Recommendation:** Verify `.gitignore` contains:
```
data/
transcripts/
*.db
.env
```
