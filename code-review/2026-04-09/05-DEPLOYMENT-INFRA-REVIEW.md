# 05 — Deployment & Infrastructure Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Severity Summary | 0 CRITICAL / 0 HIGH / 3 MEDIUM / 3 LOW |
| Rating | **YELLOW** |

---

### INFRA-001: No CI/CD pipeline

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | Repository root (no `.github/workflows/`) |
| Status | Open |
| Effort | 3 SP |

There is no GitHub Actions (or equivalent) CI pipeline. Tests run manually via `pytest`. Any commit that breaks tests goes undetected until the next manual test run. This is especially risky given the upcoming agent system additions.

**Recommendation:** Add `.github/workflows/test.yml`:
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: macos-latest  # Required for osascript-adjacent tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: pytest --cov=pm --cov-report=xml
```

---

### INFRA-002: `dashboard.sh` does not check for port conflicts

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard.sh` |
| Status | Open |
| Effort | 1 SP |

`dashboard.sh` runs `streamlit run` on port 8501 without checking if the port is already in use. If the dashboard is already running, a second instance starts silently on an auto-incremented port, which confuses the macOS app launcher.

**Recommendation:** Add a check:
```bash
if lsof -ti:8501 >/dev/null 2>&1; then
    echo "Dashboard already running on :8501 — opening in browser"
    open http://localhost:8501
    exit 0
fi
```

---

### INFRA-003: `data/projects.db` location in project directory

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/database/models.py:321` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```python
db_path = Path(__file__).parent.parent.parent / "data" / "projects.db"
```

The database lives inside the project directory. This has two risks:
1. `git add .` could accidentally commit the database with sensitive project metadata
2. Running `pm scan` from a git worktree would use a different database than the main working tree

**Recommendation:** Use `~/.pm/projects.db` or `~/.local/share/project-manager/projects.db` as the default path, with an override via `PM_DB_PATH` environment variable.

---

### INFRA-004: `setup.sh` installs without venv check

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `setup.sh` |
| Status | Open |
| Effort | 0.5 SP |

`setup.sh` runs `pip install -e .` without checking if it's inside a virtual environment. On macOS with Homebrew Python, this may require `--break-system-packages` or silently install to a non-activated environment.

**Recommendation:** Add a venv guard:
```bash
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Not in a virtual environment. Run: source venv/bin/activate"
    exit 1
fi
```

---

### INFRA-005: Cloudflare Tunnel plist had missing `tunnel run` args

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `~/Library/LaunchAgents/com.cloudflare.cloudflared.plist` |
| Status | Fixed 2026-03-28 |
| Effort | 0 SP |

Fixed in this session. The plist was launching `cloudflared` with no arguments, causing it to print help and exit. The `tunnel run` subcommand was added and the service restarted successfully with 4 edge connections. No further action needed.

---

### INFRA-006: No health check for the claude-notify server

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/terminal.py`, `hooks/notify.sh` |
| Status | Open |
| Effort | 2 SP |

`notify.sh` checks `curl -s -m 1 "${CTRL_LOCAL}/health"` before registering actions, but there is no monitoring or auto-restart for the claude-notify server process itself. If it crashes, notifications arrive without action buttons and the failure is silent.

**Recommendation:** Add a launchd plist for the claude-notify server (similar to cloudflared) so it auto-restarts on crash.
