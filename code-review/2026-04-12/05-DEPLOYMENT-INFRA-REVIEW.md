# Deployment & Infrastructure Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 3 |

Infrastructure is solid for a personal macOS tool. CI runs on `macos-latest`, dashboard is localhost-bound, DB lives in `~/.pm/`, and the venv guard prevents system-Python pollution. The outstanding issues are: the CI workflow runs the full test suite twice (doubling build time), the plist embeds an absolute hardcoded path, and the `pm dashboard` CLI subcommand doesn't match `dashboard.sh` in its server binding.

---

### INFRA-001: CI Runs Tests Twice (2× Build Time)

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `.github/workflows/test.yml:25–33` |
| Status | Open |
| Effort | 0.5 SP |

**Code:**
```yaml
- name: Run tests with coverage
  run: pytest --tb=short -q
  env:
    PM_DB_PATH: /tmp/test-projects.db

- name: Check coverage threshold
  run: pytest --tb=short -q --cov-fail-under=75
  env:
    PM_DB_PATH: /tmp/test-projects.db
```

The workflow runs pytest twice — once for the full test output and once for the coverage threshold check. The `pytest.ini` / `pyproject.toml` config already enables `--cov` by default, so both steps generate a coverage report. On a 479-test suite this adds ~7 seconds per CI run, but more importantly the duplication creates two separate coverage reports and could produce inconsistent results if tests are flaky.

**Recommendation:** Collapse into a single step:
```yaml
- name: Run tests with coverage
  run: pytest --tb=short -q --cov-fail-under=75
  env:
    PM_DB_PATH: /tmp/test-projects.db
```

---

### INFRA-002: `com.pm.daily-brief.plist` Hardcodes Absolute Path

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `scripts/com.pm.daily-brief.plist:10,22,25` |
| Status | Open |
| Effort | 1 SP |

**Code:**
```xml
<string>/Users/admin/dev2/project-manager/scripts/daily-brief.sh</string>
...
<string>/Users/admin/dev2/project-manager/logs/daily-brief.log</string>
<string>/Users/admin/dev2/project-manager/logs/daily-brief-error.log</string>
```

The plist embeds `/Users/admin` as a hardcoded path. This plist is version-controlled, meaning any other user cloning the repo would need to manually edit it before installation. The dynamically generated agent-batch plist (via `_build_plist()` in `pm/cli.py:3015`) correctly uses `Path(__file__)` to derive paths at generation time — the static plist should follow the same pattern.

**Note:** `pm schedule install` (the programmatic path) generates its plist correctly. The static plist in `scripts/` is only used if someone installs it manually. The issue is lower risk but makes the repo non-portable.

**Recommendation:** Either generate this plist dynamically (via a `pm brief schedule install` command analogous to `pm schedule install`), or add a `sed` substitution in the installation instructions. Alternatively, use `$HOME` variable interpolation — launchd supports environment variable expansion in some plist fields.

---

### INFRA-003: `pm dashboard` CLI Does Not Pass `--server.address`

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

Already noted in ARCH-005. When launching via `pm dashboard` (rather than `./dashboard.sh`), the dashboard binds to all interfaces. The `dashboard.sh` script correctly passes `--server.address 127.0.0.1`.

**Recommendation:** Add `"--server.address", "127.0.0.1"` to the subprocess args.

---

### INFRA-004: No Python Version Lower Bound Enforced in `pyproject.toml`

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pyproject.toml` |
| Status | Open |
| Effort | 0.5 SP |

**Description:** The codebase uses `list[str]` return type annotations (lowercase, PEP 585 style), `match` syntax is not used but `timezone.utc` is, and `from __future__ import annotations` is not present. These all require Python ≥3.9. The CI tests with Python 3.12. The `pyproject.toml` should declare this minimum:

```toml
[project]
requires-python = ">=3.9"
```

Without this, `pip install` on Python 3.8 would succeed but the package would crash at runtime.

**Recommendation:** Add `requires-python = ">=3.9"` to `[project]` in `pyproject.toml`. Match the value stated in APPENDIX-A (Python ≥3.9).

---

### INFRA-005: `logs/` Directory Not Created by Setup

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `scripts/com.pm.daily-brief.plist:22`, `pm/cli.py:3012` |
| Status | Open |
| Effort | 0.5 SP |

**Description:** The daily-brief plist writes logs to `project-manager/logs/daily-brief.log`. The agent-batch schedule uses `_LOG_DIR = Path(__file__).parent.parent / "logs"`. Neither `setup.sh` nor the package itself creates the `logs/` directory. If the directory doesn't exist when launchd fires the job, the job output is silently lost.

**Recommendation:** Add `mkdir -p logs` to `setup.sh`, or have `pm schedule install` create the directory with `_LOG_DIR.mkdir(exist_ok=True)` before writing the plist.

---

## Infrastructure Strengths

- **`dashboard.sh` is production-quality**: port conflict detection, `127.0.0.1` binding, headless mode, `PM_DASHBOARD_PORT` override.
- **CI on `macos-latest`**: tests run on the actual target platform, not Linux. AppleScript and macOS path behavior are tested correctly.
- **DB in `~/.pm/`**: clean separation from project source, survives repo updates.
- **`PM_DB_PATH` env override**: test isolation without changing production config.
- **Venv guard in `setup.sh`**: prevents accidental system-Python installs.
- **`pm schedule install` generates plist correctly**: uses `Path(__file__)` for portable paths at install time.
