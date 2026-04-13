# Code Review: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |
| Reviewer | Chris Therriault |
| Repository | https://github.com/dbbuilder-org/claude-code-project-manager |
| Branch | main |
| Commit | 7df12fb |

## Overall Rating: YELLOW

- **GREEN** = Production-ready with minor polish
- **YELLOW** = Solid foundation, needs targeted fixes before production
- **RED** = Significant issues must be resolved before production

---

## Summary

The project manager is a capable, well-designed personal developer tool at approximately 3,500 lines of Python (not counting tests). The core architecture — SQLite + SQLAlchemy, Click CLI, Streamlit dashboard, PM-STATUS.md two-way sync — is sound. The parser module has 97% test coverage, the health/urgency scoring model is well-specified, and the terminal abstraction layer is clean. The codebase is in active development with 300 passing tests and 70% overall coverage.

The YELLOW rating reflects two categories of concern. First, there are eight HIGH-priority items that should be resolved before the planned agent orchestration system is built on top of this foundation: specifically, the thread-unsafe global database state (ARCH-002), the non-transactional schema migration (ARCH-003), the duplicate/dead `launch` command (ARCH-001/FC-001), and the metadata module's low test coverage (22%) given its role as the primary user-facing persistence path. These issues will compound significantly under concurrent agent workloads.

Second, there is meaningful technical debt in duplication: headless Claude execution is implemented in three separate places, the `_sync_project` helper appears in both CLI and dashboard, and filter parsing is repeated across six CLI commands. The upcoming agent coordination layer will make this duplication even more expensive if not addressed first. The good news is that `pm/docgen/executor.py` is already the canonical implementation — consolidating the other two callers is a straightforward refactor.

The security posture is acceptable for a local developer tool but requires hardening for the planned multi-agent deployment: the `shell=True` subprocess call, the path traversal in transcript directory construction, and the `--dangerously-skip-permissions` flag on all headless Claude invocations are the most important items to address.

---

## Findings by Severity

| Priority | Count | Story Points |
|----------|-------|-------------|
| CRITICAL | 0 | 0 SP |
| HIGH | 8 | ~23 SP |
| MEDIUM | 24 | ~50 SP |
| LOW | 19 | ~18 SP |
| **Total** | **51** | **~91 SP** |

*(2 items marked Fixed/Moot not counted)*

---

## High Priority Items (Must Fix Before Agent System)

1. **TD-004** (ARCH-002, 3 SP) — Thread-unsafe global database state — Streamlit + agent workers will race `init_db()` without a threading lock
2. **TD-005** (ARCH-003, 8 SP) — Schema migration not transaction-safe — Mid-migration crash leaves undefined schema state; critical before agent tables are added
3. **TD-007** (TST-001, 5 SP) — `pm/metadata.py` at 22% coverage — Core sync feature essentially untested
4. **TD-008** (TST-002, 5 SP) — No tests for recently-added CLI commands (`shutdown`, `stale`, `launch`, `transcripts`, `docs`)
5. **TD-003** (ARCH-001/FC-001, 2 SP) — Dead `launch` command (lines 390–550) silently shadows the active one
6. **TD-002** (SEC-002, 1 SP) — Path traversal in transcript directory via unsanitized `project.name`
7. **TD-001** (SEC-001, 1 SP) — Shell injection via `shell=True` in tmux launch path
8. **TD-006** (CQ-001, 0.5 SP) — Bare `except:` in `tags_list` catches `KeyboardInterrupt`

---

## Document Index

| # | Document | Findings | SP | Rating |
|---|----------|----------|----|--------|
| 01 | Security Review | 2 HIGH / 3 MEDIUM / 3 LOW | 12 SP | YELLOW |
| 02 | Architecture Review | 3 HIGH / 4 MEDIUM / 2 LOW | 26 SP | YELLOW |
| 03 | Code Quality Review | 1 HIGH / 4 MEDIUM / 4 LOW | 10.5 SP | YELLOW |
| 04 | Testing Review | 1 HIGH / 2 MEDIUM / 2 LOW | 21 SP | YELLOW |
| 05 | Deployment & Infra | 0 HIGH / 3 MEDIUM / 3 LOW | 10 SP | YELLOW |
| 06 | Technical Debt Backlog | 51 total items | ~91 SP | — |
| 07 | Strengths & Commendations | 10 items | — | GREEN |
| 08 | UI/UX Review | 0 HIGH / 5 MEDIUM / 5 LOW | 13.5 SP | YELLOW |
| 09 | Feature Completeness | 1 HIGH / 3 MEDIUM / 4 LOW | 13 SP | YELLOW |
| A | File Inventory | — | — | — |
| B | Dependency Audit | 0 CRITICAL / 0 HIGH / 0 MEDIUM | — | GREEN |
