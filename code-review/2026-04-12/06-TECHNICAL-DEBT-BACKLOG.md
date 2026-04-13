# Technical Debt Backlog

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |

## Summary

| Priority | Count | Story Points |
|----------|-------|-------------|
| HIGH | 3 | 14.5 SP |
| MEDIUM | 18 | 31.5 SP |
| LOW | 19 | 11 SP |
| **Total** | **40** | **57 SP** |

---

## HIGH Priority (Sprint 1)

### TD-047: Fix AppleScript Injection in `_send_imessage_triage`

| Field | Value |
|-------|-------|
| Priority | HIGH |
| Story Points | 0.5 |
| Type | Security |
| Source | SEC-001 |
| Files | `pm/cli.py:2993–3004` |

**Description:** `message` is interpolated directly into AppleScript at line 3001 with no escaping. AI-generated triage content could break out of the AppleScript string literal.

**Acceptance Criteria:**
- [ ] Import `_escape_applescript` from `pm.terminal` at top of `cli.py`
- [ ] Apply `_escape_applescript(message)` and `_escape_applescript(phone)` before interpolation
- [ ] Add test: `_send_imessage_triage('say "hack"')` — assert script contains `\\"hack\\"`

---

### TD-048: Upgrade Streamlit to ≥1.54.0 (Resolves 3 Tornado HIGH CVEs)

| Field | Value |
|-------|-------|
| Priority | HIGH |
| Story Points | 1 |
| Type | Security |
| Source | SEC-002 |
| Files | `pyproject.toml` |

**Description:** Streamlit 1.52.2 pulls in tornado 6.5.4 which has 3 HIGH CVEs. Upgrading to ≥1.54.0 pins a fixed tornado version and also resolves the streamlit MEDIUM CVE (CVE-2026-33682).

**Acceptance Criteria:**
- [ ] `pyproject.toml` updated: `streamlit = ">=1.54.0"`
- [ ] `pip install streamlit>=1.54.0` completes without conflict
- [ ] All 479 tests pass after upgrade
- [ ] `pip-audit` shows 0 HIGH findings

---

### TD-049: Remove 4 Unused Direct Dependencies

| Field | Value |
|-------|-------|
| Priority | HIGH |
| Story Points | 0.5 |
| Type | Security |
| Source | SEC-004 |
| Files | `pyproject.toml` |

**Description:** `pydantic`, `fastapi`, `uvicorn`, `gitpython` are declared in `pyproject.toml` but unused. They add ~40MB and additional CVE surface.

**Acceptance Criteria:**
- [ ] Remove `pydantic`, `fastapi`, `uvicorn`, `gitpython` from `[project.dependencies]`
- [ ] Verify `pm scan`, `pm status`, `pm agent` all work after removal
- [ ] All 479 tests pass

---

## MEDIUM Priority (Sprint 2)

### TD-050: Fix `pm context` Documentation Drift (CLAUDE.md)

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 0.5 |
| Type | Quality |
| Source | ARCH-002, FC-001 |
| Files | `CLAUDE.md:24,266` |

**Description:** `pm context` appears twice in CLAUDE.md but the actual command is `pm continue`. Causes agent errors.

**Acceptance Criteria:**
- [ ] `CLAUDE.md:24` updated to `pm continue [project]`
- [ ] `CLAUDE.md:266` updated to `pm continue <name>`

---

### TD-051: Add `db_session()` Context Manager to Replace Bare `get_session()`

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 5 |
| Type | Quality |
| Source | ARCH-003 |
| Files | `pm/database/models.py`, `pm/cli.py` (29 sites) |

**Description:** 29 `get_session()` calls without `try/finally` leak connections on exception. Add a context manager helper and apply to all sites.

**Acceptance Criteria:**
- [ ] `db_session()` context manager added to `pm/database/models.py`
- [ ] Handles commit on success, rollback + close on exception
- [ ] Applied to all 29 `get_session()` sites in `pm/cli.py`
- [ ] No regression in test suite

---

### TD-052: Replace Inline Filter Block in `continue` Command

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 1 |
| Type | Quality |
| Source | ARCH-004 |
| Files | `pm/cli.py:370–387` |

**Description:** `continue` command re-implements filter parsing instead of calling `apply_project_filter()`.

**Acceptance Criteria:**
- [ ] Lines 370–387 replaced with `apply_project_filter(query, filter_str)`
- [ ] All filter types still work: `type:client`, `priority:1`, `overdue`, `tagged:x`

---

### TD-053: Fix Missing Rollback in Exception Handlers

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 2 |
| Type | Quality |
| Source | CQ-005 |
| Files | `pm/cli.py` (multiple except blocks) |

**Description:** Exception handlers call `session.close()` without `session.rollback()` first. Can leave uncommitted transactions in WAL journal.

**Acceptance Criteria:**
- [ ] All `except` blocks that call `session.close()` first call `session.rollback()`
- [ ] Or superseded by TD-051 (context manager handles rollback automatically)

---

### TD-054: Add `--server.address 127.0.0.1` to `pm dashboard` CLI Command

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 0.5 |
| Type | Security |
| Source | ARCH-005, INFRA-003, SEC (dashboard binding) |
| Files | `pm/cli.py:440` |

**Description:** `pm dashboard` CLI launches Streamlit without address binding, unlike `dashboard.sh`.

**Acceptance Criteria:**
- [ ] `"--server.address", "127.0.0.1"` added to subprocess args at line 440

---

### TD-055: Upgrade requests, pillow, protobuf for MEDIUM CVEs

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 1 |
| Type | Security |
| Source | SEC-006 |
| Files | `pyproject.toml` |

**Description:** Three MEDIUM CVEs in transitive deps, all with available fixes.

**Acceptance Criteria:**
- [ ] `pip install requests>=2.33.0 pillow>=12.1.1 protobuf>=6.33.5`
- [ ] `pyproject.toml` lower bounds updated
- [ ] `pip-audit` shows 0 MEDIUM findings after upgrade

---

### TD-056: Fix CI Double Test Run

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 0.5 |
| Type | Infra |
| Source | INFRA-001 |
| Files | `.github/workflows/test.yml` |

**Description:** CI runs pytest twice — once for output, once for coverage threshold. Merge into one step.

**Acceptance Criteria:**
- [ ] `.github/workflows/test.yml` has a single `pytest` step with `--cov-fail-under=75`
- [ ] CI passes and takes less time

---

### TD-057: Fix Hardcoded Absolute Path in `com.pm.daily-brief.plist`

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 1 |
| Type | Infra |
| Source | INFRA-002 |
| Files | `scripts/com.pm.daily-brief.plist` |

**Description:** Plist hardcodes `/Users/admin/dev2/...` — not portable.

**Acceptance Criteria:**
- [ ] Add `pm brief schedule install` command that generates plist dynamically (like `pm schedule install`)
- [ ] OR replace static plist with template + `sed` substitution in installation docs

---

### TD-058: Surface `has_readme` in CLI and Dashboard Output

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 1 |
| Type | Feature |
| Source | FC-002 |
| Files | `pm/cli.py:229–338`, `dashboard/app.py` |

**Description:** `has_readme` affects health score (5 pts) but is invisible in all output.

**Acceptance Criteria:**
- [ ] `pm status` Flags column shows `📖` indicator when `has_readme=True`
- [ ] `pm health` detail output includes `has_readme: Yes/No`
- [ ] Dashboard Projects tab Flags column includes README indicator

---

### TD-059: Add Tests for `pm/agent/escalation.py` (Currently 29%)

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 5 |
| Type | Testing |
| Source | TST-001 |
| Files | `tests/test_agent_escalation.py` (create) |

**Description:** Escalation module at 29% coverage. Core iMessage send and reply-poll paths untested.

**Acceptance Criteria:**
- [ ] `_send_imessage()` tested with mocked subprocess: verify escaping of quotes, newlines
- [ ] SEC-001 fix (TD-047) covered by tests verifying `_send_imessage_triage` escaping
- [ ] `escalate_for_decision()` tested with mocked subprocess and canned reply
- [ ] Coverage rises to ≥70%

---

### TD-060: Add Tests for `pm/agent/coordinator.py` (Currently 44%)

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 3 |
| Type | Testing |
| Source | TST-002 |
| Files | `tests/test_agent_coordinator.py` (create) |

**Description:** Batch coordination paths untested. ThreadPoolExecutor error aggregation at risk.

**Acceptance Criteria:**
- [ ] `run_batch_assess_execute()` tested with mocked `run_assessment()`
- [ ] Error case tested: one project fails, others succeed — result list is complete
- [ ] Coverage rises to ≥75%

---

### TD-061: Add Tests for `pm shutdown` iTerm2 and `pm schedule` Paths

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 5 |
| Type | Testing |
| Source | TST-003 |
| Files | `tests/test_new_commands.py`, `tests/test_schedule.py` |

**Description:** Shutdown iTerm2 paths and schedule install/uninstall/status commands are uncovered.

**Acceptance Criteria:**
- [ ] `test_shutdown_iterm2_sends_context_command()` — patches subprocess.run, verifies osascript called
- [ ] `test_schedule_install_creates_plist()` — tmp_path fixture, verifies plist written
- [ ] `test_schedule_status_not_installed()` — asserts message when plist absent
- [ ] Overall `pm/cli.py` coverage rises from 68% to ≥75%

---

### TD-062: Add Actionable Buttons to Empty States in Dashboard

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 2 |
| Type | UX |
| Source | UX-001 |
| Files | `dashboard/app.py:603,631,553` |

**Description:** Empty state messages instruct users to run `pm scan` in terminal rather than providing an in-dashboard action.

**Acceptance Criteria:**
- [ ] Activity tab empty state includes "Scan Now" button
- [ ] Docs tab empty state auto-expands the generate section
- [ ] Scan button triggers subprocess `pm scan` and refreshes data

---

### TD-063: Improve Pagination Controls (Disabled State + Remove `unsafe_allow_html`)

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 1 |
| Type | UX |
| Source | UX-002 |
| Files | `dashboard/app.py:1115–1122` |

**Description:** Prev/Next buttons don't visually disable at boundaries; `unsafe_allow_html` used for centering.

**Acceptance Criteria:**
- [ ] Use `st.columns` for layout instead of `unsafe_allow_html`
- [ ] Prev button has `disabled=True` on page 0
- [ ] Next button has `disabled=True` on last page

---

### TD-064: Add Confirmation Flow to Combine/Replace Actions

| Field | Value |
|-------|-------|
| Priority | MEDIUM |
| Story Points | 2 |
| Type | UX |
| Source | UX-003 |
| Files | `dashboard/app.py:838–849` |

**Description:** Combine and Replace execute immediately; Archive requires confirmation. Apply same pattern.

**Acceptance Criteria:**
- [ ] Combine shows confirmation form identical to Archive flow
- [ ] Replace shows confirmation form with acknowledgement input
- [ ] Both write to DB only on "Confirm" click

---

---

## LOW Priority (Sprint 3 / Backlog)

| ID | SP | Title | Source | Files |
|----|-----|-------|--------|-------|
| TD-035 | 0 | Close TD-035: ItemStatus import is correct, not unused | CQ-002 | (no change) |
| TD-065 | 0.5 | Remove deferred `import sys`, `import re`, `import json`, `import subprocess as _sp` | CQ-001 | `pm/cli.py:432,1508,2891,2892,2995` |
| TD-066 | 0.5 | Move `import json` from `tags_list` property to `models.py` top | CQ-003 | `pm/database/models.py:199` |
| TD-067 | 0.5 | Add `import sys` to top-level imports (part of TD-065 fix) | CQ-004 | `pm/cli.py:3` |
| TD-068 | 0.5 | Consolidate deferred `import platform` to top-level | CQ-006 | `pm/cli.py:3074,3103` |
| TD-069 | 0.5 | Extract stale-detection query to shared module | ARCH-006 | `pm/cli.py:1242`, `dashboard/app.py` |
| TD-070 | 1 | Add `requires-python = ">=3.9"` to `pyproject.toml` | INFRA-004 | `pyproject.toml` |
| TD-071 | 0.5 | Create `logs/` directory in `setup.sh` | INFRA-005 | `setup.sh`, `pm/cli.py:3015` |
| TD-072 | 0.5 | Add phone number to `PM_IMESSAGE_PHONE` env var with default | SEC-005 | `pm/cli.py:1191,2994`, `pm/agent/escalation.py` |
| TD-073 | 0.5 | Upgrade pip + pygments (LOW CVEs) | SEC-007 | dev environment |
| TD-074 | 1 | Add `pm summary` to CLAUDE.md quick reference | FC-005 | `CLAUDE.md:35` |
| TD-075 | 0.5 | Add `test_pm_main_help()` for `pm/__main__.py` 0% coverage | FC-003 | `tests/` |
| TD-076 | 1 | Add parameterized edge-case tests for `_escape_applescript` | TST-004 | `tests/test_terminal.py` |
| TD-077 | 2 | Add unit tests for `format_brief_imessage` all-sections coverage | TST-005 | `tests/test_brief.py` |
| TD-078 | 1 | Add "Clear All Filters" button to Projects tab filter bar | UX-004 | `dashboard/app.py` |
| TD-079 | 1 | Add "Download Results" button to Agent tab | UX-005 | `dashboard/app.py:944` |
| TD-080 | 0.5 | Add type annotations to `apply_project_filter`, `_send_imessage_triage` | CQ-007 | `pm/cli.py:39,2993` |
| TD-081 | 1 | Add SQL migration allowlist validation guard | SEC-003 | `pm/database/models.py:389,406` |
| TD-082 | 0.5 | Begin `pm/cli.py` extraction: move `apply_project_filter/apply_urgency_filter` to `pm/filtering.py` | ARCH-001 | `pm/cli.py:39–80` |

---

## Sprint Plan

### Sprint 1: Security (2 SP) — Do Now
- TD-047: Fix `_send_imessage_triage` AppleScript injection (0.5 SP)
- TD-048: Upgrade Streamlit ≥1.54.0 (1 SP)
- TD-049: Remove unused dependencies (0.5 SP)

### Sprint 2: Quality + Infra (19 SP) — Next Session
- TD-050: Fix `pm context` documentation (0.5 SP)
- TD-051: Add `db_session()` context manager (5 SP)
- TD-052: Fix inline filter duplicate (1 SP)
- TD-054: Fix `pm dashboard` address binding (0.5 SP)
- TD-055: Upgrade requests/pillow/protobuf (1 SP)
- TD-056: Fix CI double test run (0.5 SP)
- TD-058: Surface `has_readme` in output (1 SP)
- TD-059: Escalation tests (5 SP)
- TD-061: Shutdown/schedule tests (partial) (4 SP)

### Sprint 3: Testing + UX (16.5 SP)
- TD-060: Coordinator tests (3 SP)
- TD-062: Dashboard empty states (2 SP)
- TD-063: Pagination controls (1 SP)
- TD-064: Combine/Replace confirmation (2 SP)
- TD-057: Fix hardcoded plist path (1 SP)
- TD-065–TD-082: LOW items as available (~7.5 SP)
