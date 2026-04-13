# Appendix A: File Inventory — Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Branch | main |
| Commit | 7df12fb2 |

## Project Statistics

| Metric | Count |
|--------|-------|
| Source files (Python) | 19 |
| Shell scripts | 5 |
| Test files | 11 |
| Total source LOC | ~5,870 |
| Total test LOC | ~7,580 (300 tests) |
| Overall coverage | 70% |
| Templates | 7 |
| CLI commands | ~22 |

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.9+ |
| CLI framework | Click | 8.3.1 |
| TUI output | Rich | 14.2.0 |
| Dashboard | Streamlit | 1.52.2 |
| ORM | SQLAlchemy | 2.x |
| Database | SQLite | (via SQLAlchemy) |
| Data validation | Pydantic | 2.12.5 |
| API framework | FastAPI | 0.128.0 (unused) |
| Date parsing | python-dateutil | 2.x |
| Git integration | gitpython | 3.x (dep, not imported) |
| Process mgmt | subprocess / threading | stdlib |
| Terminal control | osascript / AppleScript | macOS |
| Notification | ntfy.sh | (external) |
| Channel | iMessage plugin | claude-plugins-official |
| Test runner | pytest + pytest-cov | 7.x / 4.x |

## Coverage by Module

| Module | Lines | Covered | % |
|--------|-------|---------|---|
| pm/cli.py | 2,343 | — | — |
| pm/database/models.py | 338 | ~85% | HIGH |
| pm/scanner/detector.py | 243 | 80% | MED |
| pm/scanner/parser.py | 391 | 97% | HIGH |
| pm/terminal.py | 293 | 69% | MED |
| pm/metadata.py | 233 | 22% | LOW ⚠️ |
| pm/digest.py | 154 | — | — |
| pm/docgen/executor.py | 191 | — | — |
| pm/docgen/templates.py | 337 | — | — |
| pm/docgen/context.py | 76 | — | — |
| pm/generator/prompts.py | 195 | 100% | HIGH |
| dashboard/app.py | 1,076 | 0% | NONE ⚠️ |
| **TOTAL** | **~5,870** | | **70%** |

## Key File Paths

| Category | Path |
|----------|------|
| CLI entry | `pm/cli.py` |
| DB models | `pm/database/models.py` |
| Schema migration | `pm/database/models.py:279` (`_migrate_db`) |
| Project scanner | `pm/scanner/detector.py` |
| Progress parser | `pm/scanner/parser.py` |
| Terminal launcher | `pm/terminal.py` |
| Metadata sync | `pm/metadata.py` |
| Dashboard | `dashboard/app.py` |
| Headless executor | `pm/docgen/executor.py` |
| Doc templates | `pm/docgen/templates.py` |
| Test fixtures | `tests/conftest.py` |
| Launch scripts | `scripts/claude-launch.sh`, `scripts/claude-tmux.sh` |
| Data directory | `data/projects.db` |
| Transcripts | `transcripts/<project>/<timestamp>.md` |

## Database Schema Summary

| Table | Purpose |
|-------|---------|
| `projects` | Core project registry (51 columns) |
| `progress_items` | Parsed TODO/task items |
| `scan_history` | Historical completion snapshots |
| `doc_generations` | Document generation log |

Missing tables (planned): `work_items`, `agent_runs`, `escalation_requests`
