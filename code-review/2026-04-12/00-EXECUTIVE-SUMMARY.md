# Code Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Repository | https://github.com/dbbuilder-org/claude-code-project-manager |
| Branch | main |
| Commit | 310999f |

## Overall Rating: YELLOW

- **GREEN** = Production-ready with minor polish
- **YELLOW** = Solid foundation, needs targeted fixes before production
- **RED** = Significant issues must be resolved before production

## Summary

The project manager has matured considerably since the April 9 review: all three post-review sprints shipped cleanly, the test suite reached 479 tests at 75% coverage, and the most impactful prior security issues (shell injection, unbound dashboard, `shell=True`) were resolved. The codebase is a well-engineered personal productivity tool with thoughtful agent orchestration architecture, clean module separation, and production-quality operational tooling.

The YELLOW rating reflects two remediable issues: an AppleScript injection vulnerability introduced in the new `_send_imessage_triage()` function (HIGH), and three tornado CVEs that require a Streamlit dependency upgrade (HIGH). Both are 1–2 SP fixes. The architectural concern about `pm/cli.py` as a 3,196-line god file is real but long-term; the security issues are the immediate priority.

Beyond security, the most impactful remaining work is: 13 SP of `db_session()` context manager rollout to protect SQLite connections, targeted test coverage improvements for the agent subsystem (escalation at 29%, coordinator at 44%), and two documentation corrections (`pm context` → `pm continue`) that cause agent confusion.

## Findings by Severity

| Priority | Count | Story Points |
|----------|-------|-------------|
| CRITICAL | 0 | 0 SP |
| HIGH | 3 | 2 SP |
| MEDIUM | 18 | 31.5 SP |
| LOW | 19 | 23.5 SP |
| **Total** | **40** | **57 SP** |

## Critical Items (Must-Fix)

1. **TD-047** (0.5 SP) — AppleScript injection in `_send_imessage_triage`: `message` is interpolated unescaped into AppleScript at `pm/cli.py:3001`. Fix: apply `_escape_applescript()`. See SEC-001.

2. **TD-048** (1 SP) — 3 HIGH tornado CVEs (GHSA-78cv-mqj4-43f7, CVE-2026-31958, CVE-2026-35536): upgrade Streamlit to ≥1.54.0. See SEC-002.

3. **TD-049** (0.5 SP) — 4 unused dependencies (`pydantic`, `fastapi`, `uvicorn`, `gitpython`) add CVE surface and install bloat. Remove from `pyproject.toml`. See SEC-004.

## Document Index

| # | Document | Findings | Rating |
|---|----------|----------|--------|
| 01 | [Security Review](01-SECURITY-REVIEW.md) | 2H / 3M / 2L | YELLOW |
| 02 | [Architecture Review](02-ARCHITECTURE-REVIEW.md) | 1H / 3M / 2L | YELLOW |
| 03 | [Code Quality Review](03-CODE-QUALITY-REVIEW.md) | 0H / 3M / 4L | GREEN |
| 04 | [Testing Review](04-TESTING-REVIEW.md) | 0H / 3M / 2L | YELLOW |
| 05 | [Deployment & Infra Review](05-DEPLOYMENT-INFRA-REVIEW.md) | 0H / 2M / 3L | GREEN |
| 06 | [Technical Debt Backlog](06-TECHNICAL-DEBT-BACKLOG.md) | 40 items / 57 SP | — |
| 07 | [Strengths & Commendations](07-STRENGTHS-AND-COMMENDATIONS.md) | 12 commendations | — |
| 08 | [UI/UX Review](08-UI-UX-REVIEW.md) | 0H / 2M / 3L | GREEN |
| 09 | [Feature Completeness](09-FEATURE-COMPLETENESS.md) | 0H / 2M / 3L | GREEN |
| A | [File Inventory](APPENDIX-A-FILE-INVENTORY.md) | — | — |
| B | [Dependency Audit](APPENDIX-B-DEPENDENCY-AUDIT.md) | 9 CVEs / 4 unused | RED |

## Progress Since April 9 Review

All 40+ items from the prior review are resolved:

| Sprint | Items | Highlights |
|--------|-------|-----------|
| Sprint A (Security) | TD-031–038 | `_escape_applescript()`, venv guard, `_utcnow()`, terminal subprocess mocking |
| Sprint B (Dashboard UX) | TD-023–030, 040–044 | Filter labels, cache invalidation, Select All, 50KB guard, budget/target inline editing |
| Sprint C (CLI + Infra) | TD-033, TD-046 | Terminal detection shared module, Terminal.app shutdown support |

The four prior HIGH/CRITICAL issues are confirmed resolved: `shell=True` removed, dashboard bound to 127.0.0.1, AppleScript injection in launch/shutdown fixed, headless executor has `--permission-mode` parameter.
