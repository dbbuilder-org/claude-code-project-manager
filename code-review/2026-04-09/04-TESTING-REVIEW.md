# 04 — Testing Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Tests | 300 passing |
| Coverage | 70% overall |
| Rating | **YELLOW** |

---

### TST-001: `pm/metadata.py` at 22% coverage — core feature barely tested

| Field | Value |
|-------|-------|
| Severity | HIGH |
| Location | `tests/` (missing), `pm/metadata.py` |
| Status | Open |
| Effort | 5 SP |

The metadata sync module is the heart of the PM-STATUS.md two-way sync feature and is one of the most user-facing data paths. With only 22% coverage, the following critical paths are untested:
- `read_pm_status()` with a real file
- `parse_pm_status()` with all supported YAML variants (text priorities, multiple date formats, tag lists)
- `write_pm_status()` generating correct YAML frontmatter
- `sync_to_file()` preserving existing notes while updating fields
- Error cases: malformed frontmatter, missing file, permission error

**Recommendation:** Add `tests/test_metadata.py` covering all public functions with positive and negative cases, including the non-atomic write risk (TST-004 in code quality).

---

### TST-002: No tests for CLI commands added in the most recent commits

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `tests/test_cli.py` |
| Status | Open |
| Effort | 5 SP |

The recent commits added `pm shutdown`, `pm stale`, `pm launch` (new version), `pm transcripts`, `pm backlog`, and `pm docs generate`. The existing `test_cli.py` file tests the older command surface. The new commands are likely untested given the last 5 commits.

**Commands with no test coverage (inferred):**
- `pm shutdown` — threading + AppleScript (mock osascript)
- `pm stale --action` — interactive prompts (mock click.prompt)
- `pm launch <name>` / `pm launch <N>` — terminal launch
- `pm transcripts` — file enumeration and status parsing
- `pm docs generate` / `pm docs history` / `pm docs status`

---

### TST-003: Dashboard has zero test coverage

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `dashboard/app.py` (1,076 lines, 0% coverage) |
| Status | Open |
| Effort | 8 SP |

The Streamlit dashboard contains significant business logic: `_save_tags()`, `_bulk_apply_tag()`, `generate_doc()`, `_run_prompt_on_project()`, and the cache load path. None of it is tested. Bugs introduced in dashboard helpers are invisible until runtime.

**Recommendation:** Extract the business logic functions (`_save_tags`, `_bulk_apply_tag`, `generate_doc`, `_run_prompt_on_project`) from the Streamlit rendering code and test them as pure Python functions via `tests/test_dashboard_helpers.py`. Streamlit rendering itself can't be unit-tested easily but the logic layer can.

---

### TST-004: `test_tier1.py` purpose is unclear

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `tests/test_tier1.py` (847 lines) |
| Status | Open |
| Effort | 1 SP |

`test_tier1.py` is the largest test file at 847 lines but its purpose isn't apparent from its name. There is no corresponding CLAUDE.md entry explaining what "tier 1" means in the testing hierarchy.

**Recommendation:** Rename to reflect content (e.g., `test_integration.py`) or add a module docstring explaining the tier structure.

---

### TST-005: Terminal tests rely on macOS — no cross-platform stubs

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `tests/test_terminal.py` |
| Status | Open |
| Effort | 2 SP |

`pm/terminal.py` has 69% coverage. The uncovered lines are the `subprocess.Popen(["osascript", ...])` calls in `launch_single()` and `launch_batch()`. These cannot run in CI (no macOS GUI, no iTerm2). The tests should mock `subprocess.Popen` to verify the correct AppleScript is generated without actually executing it.

---

### TST-006: Test strengths worth preserving

**Excellent patterns in the current suite:**
- `tests/conftest.py:254` — `autouse=True` `skip_temp_check` fixture prevents tests from accidentally scanning production `~/dev2`
- `tests/conftest.py:265` — `autouse=True` `isolated_database` fixture resets module globals between tests — this is the right way to isolate SQLAlchemy global state
- `tests/test_parser.py` — 97% coverage on the most complex parsing logic; comprehensive edge cases for all regex patterns
- `tests/test_models.py` — all health/urgency score edge cases tested explicitly
- Real filesystem fixtures (no mocking of file I/O) — these catch real path issues
