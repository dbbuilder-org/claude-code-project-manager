# Security Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |
| Branch | main |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 2 |

The codebase's primary security surface is macOS-local: AppleScript execution, SQLite writes, and subprocess spawning. No network services are exposed (dashboard is `127.0.0.1`-only). Most high-severity issues from the April 9 review have been resolved (dashboard binding, `shell=True` removal, `_escape_applescript` hardening). Two new HIGH issues were introduced since then: an AppleScript injection vector in `_send_imessage_triage` and a transitive tornado CVE cluster.

---

### SEC-001: AppleScript Injection in `_send_imessage_triage`

| Field | Value |
|-------|-------|
| Severity | HIGH |
| CWE | CWE-78 (OS Command Injection via script interpreter) |
| Location | `pm/cli.py:2996–3003` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```python
def _send_imessage_triage(message: str, phone: str = "+12064962555") -> None:
    """Send a triage recommendation via iMessage."""
    import subprocess as _sp
    script = f'''
tell application "Messages"
    set targetBuddy to "{phone}"
    set targetService to (1st account whose service type = iMessage)
    set targetBuddy to participant targetBuddy of targetService
    send "{message}" to targetBuddy
end tell
'''
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
```

**Risk:** `message` is interpolated directly into the AppleScript string literal at line 3001 (`send "{message}" to targetBuddy`). The `message` content originates from Claude's AI-generated triage recommendation (a `planner.py` response). If the LLM response contains a double-quote, backslash, or newline, the AppleScript string literal terminates prematurely. An adversarially crafted recommendation could inject arbitrary AppleScript — for example, running shell commands via `do shell script`.

**Contrast with existing correct implementations:**
- `pm/agent/escalation.py:152–158` — `_send_imessage` correctly escapes with `replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")`
- `pm/cli.py:1192` — `pm brief --imessage` path also escapes before interpolation
- `pm/terminal.py:57–66` — `_escape_applescript()` canonical helper strips nulls + control chars and escapes backslashes and quotes

**Recommendation:** Use `_escape_applescript` from `pm.terminal`:
```python
from .terminal import _escape_applescript
escaped_msg = _escape_applescript(message)
escaped_phone = _escape_applescript(phone)
script = f'''
tell application "Messages"
    set targetBuddy to "{escaped_phone}"
    ...
    send "{escaped_msg}" to targetBuddy
end tell
'''
```

---

### SEC-002: Transitive Tornado CVEs (HIGH severity, fix via Streamlit upgrade)

| Field | Value |
|-------|-------|
| Severity | HIGH |
| CVEs | GHSA-78cv-mqj4-43f7, CVE-2026-31958, CVE-2026-35536 |
| Location | `pyproject.toml` (transitive via streamlit 1.52.2) |
| Status | Open |
| Effort | 1 SP |

**Code:**
```
streamlit 1.52.2 → tornado 6.5.4 (3 HIGH CVEs, fix: 6.5.5)
```

**Risk:** Three HIGH-severity CVEs in tornado 6.5.4. While the dashboard binds to `127.0.0.1`, the Tornado HTTP server underpins Streamlit's WebSocket and HTTP handling. If any of these CVEs allow unauthenticated code execution or header injection against the local HTTP server, local processes (including other browser tabs or agents running on the same machine) could exploit them.

**Recommendation:** Upgrade Streamlit to ≥1.54.0, which pins tornado ≥6.5.5. Update `pyproject.toml`:
```toml
[project.dependencies]
streamlit = ">=1.54.0"
```
Alternatively, add a direct pin: `tornado>=6.5.5`.

---

### SEC-003: SQL String Interpolation in Schema Migration

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| CWE | CWE-89 (SQL Injection — mitigated by data source) |
| Location | `pm/database/models.py:392,407` |
| Status | Open (low exploitability) |
| Effort | 1 SP |

**Code:**
```python
# Line 392
conn.execute(text(
    f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"
))

# Line 407
conn.execute(text(
    f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
))
```

**Risk:** `col_name`, `col_type`, and `table_name` are sourced exclusively from the hardcoded `_MIGRATIONS` and `_TABLE_MIGRATIONS` registry — not user input. Exploitability is therefore negligible in the current codebase. However, the pattern is dangerous if `_MIGRATIONS` values were ever derived from external input (config file, environment variable, user flag). SQLAlchemy's `text()` does not parameterize DDL statements.

**Recommendation:** Add an allowlist validation guard before executing DDL, or document the design constraint explicitly with a comment:
```python
# col_name and col_type are sourced from _MIGRATIONS only — never user input.
# If this invariant ever changes, use sqlalchemy.schema primitives instead.
conn.execute(text(
    f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"
))
```
Optionally, validate against `re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col_name)` before interpolation.

---

### SEC-004: Unused Dependencies Increase CVE Surface

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pyproject.toml` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```toml
[project.dependencies]
pydantic = ">=2.0.0"      # Not imported in any pm/ source file
fastapi = ">=0.100.0"     # Not imported anywhere
uvicorn = ">=0.23.0"      # Not imported anywhere
gitpython = ">=3.1.0"     # Not imported; git called via subprocess
```

**Risk:** Four packages add ~40MB install weight and introduce additional CVE exposure area. `fastapi` and `uvicorn` are web server frameworks — their presence implies a web API surface that doesn't exist, and their transitive dependencies (e.g., `anyio`, `httptools`, `starlette`) add more packages to audit. Any future CVE in these packages would trigger security tooling alerts for no benefit.

**Recommendation:** Remove all four from `pyproject.toml`. If a REST API is planned, re-add only when implementation begins.

---

### SEC-005: Phone Number Hardcoded in Source

| Field | Value |
|-------|-------|
| Severity | LOW |
| CWE | CWE-312 (Cleartext Storage of Sensitive Information) |
| Location | `pm/cli.py:2994`, `pm/cli.py:1191`, `pm/agent/escalation.py:15` |
| Status | Open (personal project, low impact) |
| Effort | 1 SP |

**Code:**
```python
# pm/cli.py:2994
def _send_imessage_triage(message: str, phone: str = "+12064962555") -> None:

# pm/cli.py:1191
phone = "+12064962555"

# pm/agent/escalation.py (approximate)
DEFAULT_PHONE = "+12064962555"
```

**Risk:** Phone number is embedded in three places in version-controlled source. For a personal tool this is low severity, but if the repository is ever made public, the number is permanently in git history.

**Recommendation:** Extract to a config constant or environment variable:
```python
# pm/config.py (or top of cli.py)
PM_IMESSAGE_PHONE = os.environ.get("PM_IMESSAGE_PHONE", "+12064962555")
```
Then reference `PM_IMESSAGE_PHONE` at all three call sites. This also makes the tool usable by others without source edits.

---

### SEC-006: Medium-Severity CVEs in Streamlit, requests, pillow, protobuf

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| CVEs | CVE-2026-33682, CVE-2026-25645, CVE-2026-25990, CVE-2026-0994 |
| Location | `pyproject.toml` (transitive dependencies) |
| Status | Open |
| Effort | 1 SP |

**Risk:** Four MEDIUM-severity CVEs in transitive dependencies. All are fixed in newer package versions. While the local-only deployment reduces exploitability, pip-audit flags these in any automated dependency scan.

**Remediation per package:**
| Package | Current | Fix |
|---------|---------|-----|
| streamlit | 1.52.2 | ≥1.54.0 (also resolves tornado CVEs) |
| requests | 2.32.5 | ≥2.33.0 |
| pillow | 12.1.0 | ≥12.1.1 |
| protobuf | 6.33.4 | ≥6.33.5 |

**Recommendation:** A single `pip install streamlit>=1.54.0 requests>=2.33.0 pillow>=12.1.1 protobuf>=6.33.5` resolves all four. Update `pyproject.toml` lower bounds to match.

---

### SEC-007: LOW CVEs in pip and pygments

| Field | Value |
|-------|-------|
| Severity | LOW |
| CVEs | CVE-2026-1703 (pip 25.3), CVE-2026-4539 (pygments 2.19.2) |
| Location | Development environment |
| Status | Open |
| Effort | 0.5 SP |

**Risk:** Low-severity CVEs with no direct exploitation path in this context. `pip` CVE affects package installation behavior; `pygments` CVE affects syntax highlighting edge cases.

**Recommendation:**
```bash
pip install --upgrade pip   # → 26.0
pip install pygments>=2.20.0
```

---

## Resolved Since April 9 Review

The following issues from the prior review are confirmed **resolved**:

| Prior ID | Issue | Resolution |
|----------|-------|-----------|
| SEC-001 (Apr 9) | `shell=True` in subprocess calls | Removed throughout |
| SEC-002 (Apr 9) | AppleScript injection in launch/shutdown commands | `_escape_applescript()` applied in `pm/terminal.py` |
| SEC-003 (Apr 9) | Dashboard not bound to localhost | `--server.address 127.0.0.1` added to `dashboard.sh` |
| SEC-005 (Apr 9) | Headless Claude executed with all tools | `--permission-mode` parameter added to executor |
