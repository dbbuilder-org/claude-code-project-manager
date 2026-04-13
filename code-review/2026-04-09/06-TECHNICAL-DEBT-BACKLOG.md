# 06 — Technical Debt Backlog: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Total Items | 47 |
| Total Story Points | ~91 SP |
| Rating | **YELLOW** |

---

## Priority 1: HIGH (Must Fix) — 8 items, ~23 SP

### TD-001: Shell injection via `shell=True` in tmux launch path
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 1 | Security | SEC-001 |
| Files | `pm/cli.py:511` |

Fix `subprocess.run(cmd, shell=True)` by converting to list-form args. The `session_name` and `project_path` values come from the database and could contain shell metacharacters.

**Acceptance Criteria:**
- [ ] `shell=True` removed from tmux path in dead `launch` function (or dead code deleted per TD-003)
- [ ] All `subprocess` calls use list-form commands

---

### TD-002: Path traversal in transcript directory construction
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 1 | Security | SEC-002 |
| Files | `pm/cli.py:1482`, `dashboard/app.py:213` |

`project.name` is used directly as a path component with no sanitization. Projects with names containing `../` could write outside `transcripts/`.

**Acceptance Criteria:**
- [ ] `project.name` sanitized with `re.sub(r'[^\w\-]', '_', name)` before use as path
- [ ] Same fix applied in both `pm/cli.py` and `dashboard/app.py`

---

### TD-003: Dead `launch` command shadows the active one
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 2 | Architecture | ARCH-001, FC-001 |
| Files | `pm/cli.py:390-550` |

Two `@main.command()` registrations named `launch`. The first (lines 390–550) is dead code; the second (lines 1578–1673) is active. The dead code includes a `break` bug that would have silently dropped projects 2..N.

**Acceptance Criteria:**
- [ ] Lines 390–550 deleted
- [ ] CLAUDE.md audited and updated to remove `--filter`, `--parallel`, `--iterm`, `--tmux` flags

---

### TD-004: Thread-unsafe global database state
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 3 | Architecture | ARCH-002 |
| Files | `pm/database/models.py:275-338` |

Module-level `_engine` and `_SessionLocal` are not guarded by a threading lock. The Streamlit dashboard and the upcoming agent orchestrator create concurrent threads that can race `init_db()`.

**Acceptance Criteria:**
- [ ] `threading.Lock()` added around `init_db()` initialization
- [ ] Double-initialization guard (`if _engine is not None: return`) added
- [ ] Tests verify thread-safety via concurrent `get_session()` calls

---

### TD-005: Schema migration not transaction-safe
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 8 | Architecture | ARCH-003 |
| Files | `pm/database/models.py:279-313` |

`_migrate_db()` runs bare `ALTER TABLE` statements with no migration versioning and no rollback on failure. A crashed mid-migration leaves schema in undefined state.

**Short-term acceptance criteria:**
- [ ] All `ALTER TABLE` calls wrapped in a single `BEGIN`/`COMMIT` transaction

**Long-term acceptance criteria:**
- [ ] Alembic adopted for schema versioning
- [ ] Migration version table added
- [ ] Forward/backward migration tested before agent tables added

---

### TD-006: Bare `except:` in `tags_list` property
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 0.5 | Quality | CQ-001 |
| Files | `pm/database/models.py:180-184` |

`except:` (no type) catches `KeyboardInterrupt`, `SystemExit`, `MemoryError`. Change to `except json.JSONDecodeError:`.

**Acceptance Criteria:**
- [ ] `except:` replaced with `except json.JSONDecodeError:`
- [ ] Verified no other bare `except:` clauses in `pm/database/models.py`

---

### TD-007: `pm/metadata.py` at 22% test coverage
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 5 | Testing | TST-001, CQ-005 |
| Files | `tests/` (missing), `pm/metadata.py` |

The PM-STATUS.md two-way sync module — the core persistence feature — is essentially untested. Critical paths with no coverage: `read_pm_status`, `parse_pm_status`, `write_pm_status`, `sync_to_file`.

**Acceptance Criteria:**
- [ ] `tests/test_metadata.py` created
- [ ] `read_pm_status()` tested with real file
- [ ] `parse_pm_status()` tested with all YAML variants (text priorities, multiple date formats, tag lists)
- [ ] `write_pm_status()` tested for correct YAML frontmatter output
- [ ] `sync_to_file()` tested for note preservation
- [ ] Error cases: malformed frontmatter, missing file, permission error
- [ ] Coverage on `pm/metadata.py` reaches ≥ 80%

---

### TD-008: No tests for recently-added CLI commands
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| HIGH | 5 | Testing | TST-002 |
| Files | `tests/test_cli.py` |

`pm shutdown`, `pm stale --action`, `pm launch <name>`, `pm transcripts`, `pm docs generate`, `pm docs history`, `pm docs status` were added in recent commits with no corresponding tests.

**Acceptance Criteria:**
- [ ] `pm shutdown` tested with mocked `osascript`
- [ ] `pm stale --action` tested with mocked `click.prompt`
- [ ] `pm launch <name>` tested with mocked terminal module
- [ ] `pm transcripts` tested with real fixture directories
- [ ] `pm docs generate` tested with mocked executor

---

## Priority 2: MEDIUM — 24 items, ~50 SP

### TD-009: Dashboard unauthenticated on network
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 2 | Security | SEC-003 |
| Files | `dashboard.sh` |

Dashboard must be bound to localhost. Add `--server.address 127.0.0.1` to `dashboard.sh` launch command.

**Acceptance Criteria:**
- [ ] `dashboard.sh` passes `--server.address 127.0.0.1` to Streamlit

---

### TD-010: Silent exception swallowing in schema migration
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Security | SEC-004 |
| Files | `pm/database/models.py:304-308` |

Bare `except Exception: pass` on `ALTER TABLE` swallows real errors. Change to only catch `OperationalError` with "duplicate column name".

**Acceptance Criteria:**
- [ ] `except Exception: pass` replaced with specific `OperationalError` check
- [ ] Other errors re-raised with logging

---

### TD-011: `--dangerously-skip-permissions` on all headless Claude calls
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 3 | Security | SEC-005 |
| Files | `pm/cli.py:1436`, `dashboard/app.py:178`, `pm/docgen/executor.py:58` |

All headless Claude invocations use `--dangerously-skip-permissions`. Agent system should use `--permission-mode acceptEdits` for write agents, reserving full skip for read-only analysis.

**Acceptance Criteria:**
- [ ] `executor.py` accepts `permission_mode` parameter
- [ ] Read-only templates (roadmap, architecture, etc.) use `--permission-mode readonly`
- [ ] Write-capable agents documented explicitly

---

### TD-012: Headless execution logic duplicated in 3 places
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 3 | Architecture | ARCH-004 |
| Files | `pm/cli.py:1433-1503`, `dashboard/app.py:170-241`, `pm/docgen/executor.py:25-135` |

All three build identical `subprocess.run(["claude", "-p", ...])` calls. `pm/docgen/executor.py:run_doc_generation` is canonical. CLI and dashboard should delegate to it.

**Acceptance Criteria:**
- [ ] `pm/cli.py:run_prompt` function removed; replaced with call to `executor.run_doc_generation`
- [ ] `dashboard/app.py:_run_prompt_on_project` removed; replaced with call to `executor.run_doc_generation`
- [ ] Single executor used by all three callers

---

### TD-013: Duplicate `_sync_project` helper in CLI and dashboard
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Architecture | ARCH-005 |
| Files | `pm/cli.py:1135`, `dashboard/app.py:127` |

`_sync_project` (CLI) and `_sync_project_to_file` (dashboard) are identical. Consolidate into `pm/metadata.py:sync_project_to_file(project: Project)`.

**Acceptance Criteria:**
- [ ] Single `sync_project_to_file(project)` function in `pm/metadata.py`
- [ ] CLI and dashboard import and use it

---

### TD-014: Filter parsing repeated 6+ times across CLI commands
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 2 | Architecture | ARCH-006 |
| Files | `pm/cli.py:196-206`, `:336-341`, `:433-448`, `:869-878`, `:1107-1111`, `:2013-2022` |

The `filter_str.startswith("type:")` block is copy-pasted across 6 commands. Extract to `apply_project_filter(query, filter_str)`.

**Acceptance Criteria:**
- [ ] `apply_project_filter(query, filter_str)` helper added to `pm/cli.py`
- [ ] All 6 copy-paste sites replaced with the helper

---

### TD-015: FastAPI module is dead structure
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Architecture | ARCH-007, FC-002 |
| Files | `pm/api/__init__.py`, `pyproject.toml` |

`pm/api/` is an empty stub. FastAPI and uvicorn are unnecessary deps. Either delete or convert to the agent coordination API.

**Acceptance Criteria:**
- [ ] Decision made: delete OR stub out for agent API
- [ ] If deleted: FastAPI/uvicorn removed from `pyproject.toml`

---

### TD-016: Priority labels hardcoded in two places with different casing
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Quality | CQ-002 |
| Files | `pm/database/models.py:172`, `pm/metadata.py:141` |

Two `dict` literals with different capitalization. Centralize in `models.py` as `PRIORITY_LABELS`.

**Acceptance Criteria:**
- [ ] `PRIORITY_LABELS: dict[int, str]` defined once in `pm/database/models.py`
- [ ] `pm/metadata.py` imports and uses it

---

### TD-017: Inline imports scattered throughout `pm/cli.py`
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Quality | CQ-003 |
| Files | `pm/cli.py:1415`, `:2055`, `:836`, `:1137`, `:1979` |

`import time`, `from datetime import timedelta`, `from .metadata import ProjectMetadata` inside function bodies. Move to module top.

**Acceptance Criteria:**
- [ ] All deferred imports moved to top of `pm/cli.py`

---

### TD-018: Non-atomic file write in `write_pm_status`
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 2 | Quality | CQ-004 |
| Files | `pm/metadata.py:186-190` |

`Path.write_text()` is not atomic. A crash mid-write destroys the user's notes. Use temp-file + `os.replace()` pattern.

**Acceptance Criteria:**
- [ ] `write_pm_status` uses `tmp.write_text(content); os.replace(tmp, status_file)` pattern
- [ ] `tmp.unlink(missing_ok=True)` in except block

---

### TD-019: No tests for recently-added CLI commands (dashboard coverage)
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 8 | Testing | TST-003 |
| Files | `dashboard/app.py`, `tests/` (missing) |

`dashboard/app.py` is 1,076 lines with 0% test coverage. Business logic functions (`_save_tags`, `_bulk_apply_tag`, `generate_doc`, `_run_prompt_on_project`) are pure Python and can be unit tested.

**Acceptance Criteria:**
- [ ] `tests/test_dashboard_helpers.py` created
- [ ] `_save_tags` tested (with mocked DB session)
- [ ] `_bulk_apply_tag` tested
- [ ] `generate_doc` tested with mocked executor
- [ ] `_run_prompt_on_project` tested with mocked subprocess

---

### TD-020: CI/CD pipeline missing
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 3 | Infra | INFRA-001 |
| Files | Repository root |

No GitHub Actions pipeline. Tests run manually. Regressions go undetected.

**Acceptance Criteria:**
- [ ] `.github/workflows/test.yml` created
- [ ] Runs on `push` and `pull_request`
- [ ] Uses `macos-latest` (for osascript-adjacent tests)
- [ ] Runs `pytest --cov=pm --cov-report=xml`

---

### TD-021: Dashboard port conflict not detected
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Infra | INFRA-002 |
| Files | `dashboard.sh` |

Second instance starts on auto-incremented port silently when port 8501 is occupied.

**Acceptance Criteria:**
- [ ] `lsof -ti:8501` check added to `dashboard.sh`
- [ ] If already running: `open http://localhost:8501` and exit

---

### TD-022: Database stored in project directory
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Infra | INFRA-003 |
| Files | `pm/database/models.py:321` |

`data/projects.db` inside the repo risks accidental git commits and worktree divergence.

**Acceptance Criteria:**
- [ ] Default path changed to `~/.pm/projects.db`
- [ ] `PM_DB_PATH` env var override supported
- [ ] `data/` added to `.gitignore`

---

### TD-023: Pagination state not reset on filter change
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | UX | UX-001 |
| Files | `dashboard/app.py:877-895` |

Filter change while on page 3 shows empty page if filtered result has fewer than 3 pages.

**Acceptance Criteria:**
- [ ] Filter/sort change resets `st.session_state.page` to 0

---

### TD-024: Batch doc generation blocks Streamlit UI thread
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 3 | UX | UX-002 |
| Files | `dashboard/app.py:407-420` |

Sequential batch generation with no cancel blocks the browser for potentially hours.

**Acceptance Criteria:**
- [ ] Batch generation uses `run_batch_generation` from `executor.py`
- [ ] Progress bar polls from background thread
- [ ] Cancel button sets session state flag

---

### TD-025: Sort/filter dropdowns have invisible labels
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | UX | UX-003 |
| Files | `dashboard/app.py:798, 802, 805, 810` |

`label_visibility="collapsed"` on all four filter controls.

**Acceptance Criteria:**
- [ ] Labels made visible, or column headers added above controls

---

### TD-026: Column headers use cryptic abbreviations
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 0.5 | UX | UX-004 |
| Files | `dashboard/app.py:899-906` |

"Sel" and "St" column headers. Status column icon legend needed.

**Acceptance Criteria:**
- [ ] "St" renamed to "Status" or icon legend added below headers

---

### TD-027: Cache clear on every edit causes full reload
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 3 | UX | UX-005 |
| Files | `dashboard/app.py:737, 747, 756, 767, 776, 851, 971` |

`st.cache_data.clear()` on every inline edit triggers 200+ project reload.

**Acceptance Criteria:**
- [ ] Inline edits update session state directly
- [ ] Cache invalidated at natural 120s TTL, not after every write

---

### TD-028: FastAPI module / empty API package
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Feature | FC-002 |
| Files | `pm/api/__init__.py` |

Already captured in TD-015. Combined item.

---

### TD-029: `has_readme` detected but not stored
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 1 | Feature | FC-003 |
| Files | `pm/scanner/detector.py:21,141`, `pm/database/models.py` |

README detection result discarded. Add column to DB and consider health score contribution.

**Acceptance Criteria:**
- [ ] `has_readme = Column(Boolean, default=False)` added to Project model
- [ ] Column added to `_migrate_db()`
- [ ] README presence factored into health score

---

### TD-030: Dashboard missing inline editors for `target_date`, `budget_hours`, `hours_logged`
| Priority | SP | Type | Source |
|----------|-----|------|--------|
| MEDIUM | 2 | Feature | FC-004 |
| Files | `dashboard/app.py` |

Three PM-STATUS fields not editable from dashboard.

**Acceptance Criteria:**
- [ ] `target_date`, `budget_hours`, `hours_logged` added to project card inline edit section
- [ ] Saves to DB and syncs to PM-STATUS.md

---

## Priority 3: LOW — 19 items, ~18 SP

### TD-031: AppleScript injection incomplete escaping
| TD | SP | Source |
|----|-----|--------|
| TD-031 | 1 | SEC-006 |

`_escape_applescript` misses newlines/null bytes. Add `\n`, `\r`, `\x00` stripping.

---

### TD-032: No .gitignore for `data/` and `transcripts/`
| TD | SP | Source |
|----|-----|--------|
| TD-032 | 0.5 | SEC-007 |

Verify/add `data/`, `transcripts/`, `*.db` to `.gitignore`.

---

### TD-033: iTerm2 detection duplicated in shell scripts
| TD | SP | Source |
|----|-----|--------|
| TD-033 | 2 | ARCH-008 |

`scripts/claude-launch.sh` and `scripts/claude-tmux.sh` have own iTerm2 detection logic. Shell scripts should call `python -c "from pm.terminal import detect_terminal; print(detect_terminal().value)"`.

---

### TD-034: UTC datetime inconsistency (`utcnow()` deprecated)
| TD | SP | Source |
|----|-----|--------|
| TD-034 | 1 | CQ-007 |

`datetime.utcnow()` deprecated in Python 3.12+. Standardize on `datetime.now(timezone.utc)` and strip timezone info when storing to SQLite.

---

### TD-035: Dead `ItemStatus` import in `pm/cli.py`
| TD | SP | Source |
|----|-----|--------|
| TD-035 | 0.5 | CQ-008 |

`from .scanner.parser import ProgressParser, ProjectProgress, ItemStatus` — `ItemStatus` unused in type annotations. Clean up.

---

### TD-036: `test_tier1.py` purpose unclear
| TD | SP | Source |
|----|-----|--------|
| TD-036 | 1 | TST-004 |

Rename `test_tier1.py` or add module docstring explaining tier structure.

---

### TD-037: Terminal tests need subprocess mocking for osascript
| TD | SP | Source |
|----|-----|--------|
| TD-037 | 2 | TST-005 |

`pm/terminal.py` has 69% coverage. Uncovered lines are the live `subprocess.Popen(["osascript", ...])` calls. Mock `subprocess.Popen` to verify correct AppleScript is generated without executing.

---

### TD-038: `setup.sh` installs without venv check
| TD | SP | Source |
|----|-----|--------|
| TD-038 | 0.5 | INFRA-004 |

Add venv guard: `if [ -z "$VIRTUAL_ENV" ]; then echo "Not in venv" && exit 1; fi`.

---

### TD-039: No health check / auto-restart for claude-notify server
| TD | SP | Source |
|----|-----|--------|
| TD-039 | 2 | INFRA-006 |

Add launchd plist for claude-notify server so it auto-restarts on crash.

---

### TD-040: Action buttons provide no failure feedback
| TD | SP | Source |
|----|-----|--------|
| TD-040 | 1 | UX-006 |

🚀/📂/📁 buttons have no try/except. Wrap in try/except with `st.toast()` feedback.

---

### TD-041: Run Prompt result output unbounded
| TD | SP | Source |
|----|-----|--------|
| TD-041 | 0.5 | UX-007 |

Truncate inline prompt output to 500 chars with "View full transcript" link.

---

### TD-042: No "Select All" shortcut for bulk operations
| TD | SP | Source |
|----|-----|--------|
| TD-042 | 1 | UX-008 |

Add "Select All" header checkbox for bulk tag and launch.

---

### TD-043: Docs tab renders large files without size check
| TD | SP | Source |
|----|-----|--------|
| TD-043 | 0.5 | UX-009 |

Add 50KB size limit before rendering markdown inline; use `st.text_area` for large files.

---

### TD-044: Activity tab missing client filter
| TD | SP | Source |
|----|-----|--------|
| TD-044 | 1 | UX-010 |

Add client filter dropdown to Activity tab (already supported by `digest_by_project(session, start, end, client_filter=...)`).

---

### TD-045: No `pm delete` / `pm gc` for stale DB records
| TD | SP | Source |
|----|-----|--------|
| TD-045 | 2 | FC-005 |

Add `pm delete <name>` or `pm scan --prune` to remove DB records for deleted projects.

---

### TD-046: `pm shutdown` not supported for Terminal.app
| TD | SP | Source |
|----|-----|--------|
| TD-046 | 3 | FC-006 |

Terminal.app shutdown not implemented. Implement via `osascript` window enumeration sending `/exit`.

---

### TD-047: No un-scan / remove-project-from-DB operation
| TD | SP | Source |
|----|-----|--------|
| TD-047 | 1 | FC-008 |

Moved/renamed projects stay in DB. `pm scan --prune` removes records for non-existent paths (combined with TD-045).

---

## Sprint Allocation Guidance

| Sprint | Items | SP | Focus |
|--------|-------|-----|-------|
| Sprint 1 | TD-001, TD-002, TD-006, TD-010, TD-018 | 5.5 | Quick security/quality fixes |
| Sprint 2 | TD-003, TD-004, TD-007, TD-008 | 15 | Architecture + test coverage |
| Sprint 3 | TD-005, TD-019, TD-020 | 19 | Migration safety + dashboard tests + CI |
| Sprint 4 | TD-009, TD-011, TD-012, TD-013, TD-014 | 10 | Security hardening + refactors |
| Sprint 5 | TD-015 through TD-030 | 20 | Quality, UX, feature completeness |
| Backlog | TD-031 through TD-047 | 18 | Low-priority polish |
