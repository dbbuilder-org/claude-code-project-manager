# Appendix A: File Inventory

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Commit | 310999f |
| Branch | main |

## Project Statistics

| Metric | Count |
|--------|-------|
| Python source files | 25 (excl. tests) |
| Python test files | 17 |
| Shell scripts | 7 |
| Total Python LOC | ~14,907 |
| Test LOC | ~6,070 |
| Source LOC | ~8,836 |
| Test functions | 479 |
| Test pass rate | 100% (479/479) |
| Line coverage | 75% |
| CI workflow | GitHub Actions (macos-latest) |

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | ≥3.9 (CI: 3.12) |
| CLI framework | Click | 8.3.1 |
| Terminal UI | Rich | 14.2.0 |
| ORM | SQLAlchemy | 2.0.45 |
| Database | SQLite | (stdlib) |
| Dashboard | Streamlit | 1.52.2 |
| Data manipulation | Pandas | (transitive) |
| Data validation | Pydantic | 2.12.5 (listed but unused) |
| Web framework | FastAPI + Uvicorn | 0.128.0 / 0.40.0 (listed but unused) |
| Git integration | GitPython | 3.1.46 (listed but unused — git via subprocess) |
| Date parsing | python-dateutil | 2.9.0 |
| Testing | pytest + pytest-cov | 9.0.2 / 7.0.0 |

## Key File Paths

### Core Package
| File | LOC | Purpose |
|------|-----|---------|
| `pm/cli.py` | 3,196 | All CLI commands (34 commands + subgroups) |
| `pm/database/models.py` | 452 | SQLAlchemy models, migrations, session |
| `pm/terminal.py` | 300 | Terminal detection + AppleScript generation |
| `pm/brief.py` | 283 | Morning briefing logic |
| `pm/metadata.py` | 257 | PM-STATUS.md two-way sync |
| `pm/digest.py` | 154 | Activity digest queries |

### Agent System
| File | LOC | Purpose |
|------|-----|---------|
| `pm/agent/memory.py` | 278 | Per-project AGENT-CONTEXT.md read/write |
| `pm/agent/planner.py` | 235 | Assess phase (read-only Claude) |
| `pm/agent/escalation.py` | 203 | iMessage escalation + reply polling |
| `pm/agent/coordinator.py` | 163 | Batch orchestration (ThreadPoolExecutor) |
| `pm/agent/runner.py` | 163 | Execute phase (headless Claude) |

### Scanner
| File | LOC | Purpose |
|------|-----|---------|
| `pm/scanner/parser.py` | 391 | TODO.md/PROGRESS.md parsing |
| `pm/scanner/detector.py` | 243 | Project type detection + git info |

### DocGen
| File | LOC | Purpose |
|------|-----|---------|
| `pm/docgen/templates.py` | 337 | 7 built-in document templates |
| `pm/docgen/executor.py` | 200 | Headless Claude runner |
| `pm/docgen/context.py` | 76 | ProjectContext builder |

### Dashboard
| File | LOC | Purpose |
|------|-----|---------|
| `dashboard/app.py` | 1,368 | Streamlit UI (5 tabs) |

### Shell / Config
| File | Purpose |
|------|---------|
| `scripts/claude-launch.sh` | Terminal launch for projects |
| `scripts/claude-tmux.sh` | tmux session management |
| `scripts/daily-brief.sh` | Scheduled brief runner |
| `scripts/com.pm.daily-brief.plist` | launchd plist for 8am brief |
| `dashboard.sh` | Dashboard launcher (port guard, 127.0.0.1 binding) |
| `setup.sh` | Installation (with venv guard) |

## Database Schema

### Tables
| Table | Columns | Purpose |
|-------|---------|---------|
| `projects` | 36 | Core project entity (metadata, scan state, git, PM fields) |
| `progress_items` | 8 | Individual TODO/task items per project |
| `scan_history` | 8 | Historical scan snapshots |
| `doc_generations` | 10 | Document generation run log |
| `agent_runs` | 13 | Agent assess/execute run log |
| `schema_migrations` | 2 | Migration version tracking |

### Migration Versions
| Version | Description |
|---------|-------------|
| 1 | PM metadata columns (notes, deadline, priority, tags, etc.) |
| 2 | AgentRun cost_usd column |
| 3 | has_readme column |

## Test Distribution

| Test File | Tests | Coverage Target |
|-----------|-------|----------------|
| `test_tier1.py` | 74 | Core CLI commands |
| `test_docgen.py` | 41 | DocGen system |
| `test_new_commands.py` | 31 | Brief, stale, launch, shutdown, agent |
| `test_terminal.py` | 38 | Terminal detection + AppleScript |
| `test_agent_memory.py` | 32 | Agent memory read/write |
| `test_parser.py` | 34 | Progress document parsing |
| `test_prompts.py` | 25 | Prompt generation |
| `test_cli.py` | 34 | Scan, status, health, edit |
| `test_models.py` | 26 | SQLAlchemy models |
| `test_metadata.py` | 35 | PM-STATUS.md sync |
| `test_e2e.py` | 30 | End-to-end CLI |
| `test_dashboard_helpers.py` | 20 | Dashboard helper functions |
| `test_schedule.py` | 16 | launchd scheduling |
| `test_triage_costs.py` | 19 | Triage + costs commands |
| `test_detector.py` | 14 | Project detection |
