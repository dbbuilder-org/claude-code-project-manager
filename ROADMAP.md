> **Superseded by:** [docs/ROADMAP-2026-04-12.md](docs/ROADMAP-2026-04-12.md) — Updated 2026-04-12

# Project Manager — Roadmap

**Last Updated:** 2026-04-10 | **Current State:** 465 tests passing, 76% coverage, YELLOW health
**Repository:** https://github.com/dbbuilder-org/claude-code-project-manager
**Code Review:** `/Users/admin/dev2/project-manager/code-review/2026-04-09/`

---

## Vision

A fully autonomous, iMessage-controllable orchestration platform that manages 200+ active development projects using a fleet of headless Claude agents — advancing the highest-value work intelligently, surfacing blockers for human decision, and never doing irreversible things without confirmation.

---

## Tier 1 — Fix What's Broken (Fast Wins)
**Goal:** Make the existing tools actually useful day-to-day.

### 1A. Fix `pm urgent` — output is unusable
**Problem:** Shows all 675 projects with 674 having identical urgency score (30). Completely undifferentiated.
**Fix:** Filter to only projects with actual urgency signals: has deadline, priority 1/2, or overdue. Add `--all` flag for old behavior.

### 1B. Dashboard Priority/Deadline/Notes inline editing — not implemented
**Problem:** CLAUDE.md documents "Inline editing: Priority, Deadline, Target, Notes, Tags" but only Tags is wired up.
**Fix:** Add `_save_metadata()` helper + Priority selectbox, Deadline/Target date inputs, Notes textarea to each project card expander. Fix expander state preservation after save (currently collapses on `st.rerun()`).

### 1C. `pm stale` — ✅ works, present and usable

---

## Tier 2 — Unlock Real Value
**Goal:** The infrastructure exists but has gaps that prevent daily use.

### 2A. `pm shutdown` — needs better error handling
**Problem:** When iTerm2 isn't running, shows cryptic osascript error instead of a clear message.
**Fix:** Catch the AppleScript error, print a user-friendly message.

### 2B. iMessage → Claude control — echo loop resolved
**Problem:** Multiple `cc` sessions with `--channels` flag caused every text to echo back.
**Fix:** ✅ Already resolved by alias split (`cc` = plain, `cci` = with iMessage). Needs single `cci` window test.

### 2C. `pm backlog` — someday pile has no contents
**Problem:** 0 priority=5 projects because there's no easy way to move things to "someday". Only 2 archived projects.
**Fix:** Add `pm someday <project>` shorthand command. Make "Move to Someday" available in `pm stale --action` flow and dashboard.

---

## Tier 3 — Make It Intelligent
**Goal:** The system knows everything about 200+ projects but never proactively surfaces insights.

### 3A. `pm brief` — daily intelligent digest
**What it does:**
- Surfaces only what matters: deadlines this week, projects gone stale, priority 1/2 needing attention
- Anomaly detection: "3 projects went stale this week", "quento hasn't moved in 14 days (has deadline)", "5 new pending decisions"
- Recent velocity: completion delta vs last week
- iMessage flag: `pm brief --imessage` sends to configured number

### 3B. Daily briefing hook
- macOS launchd job at 8am: `pm brief --imessage`
- Only sends if there's something worth sending (smart suppression)

### 3C. Agent foundations
- Pre-work for Phase 3 agent system
- Data model additions: `last_agent_run`, `agent_status`, `total_agent_cost_usd`

---

## Current Capabilities (as of 2026-04-10 session)

- `pm scan` — project detection, PM-STATUS.md two-way sync, health/urgency scoring
- `pm status / urgent [--all] / health / backlog / stale` — CLI views
- `pm launch / shutdown` — iTerm2 + Terminal.app Claude Code session management
- `pm edit / tags / someday` — metadata editing with PM-STATUS.md sync
- `pm run / transcripts` — headless Claude Code prompt runner with transcript logging
- `pm docs generate/list/history/status` — 7 built-in document generation templates
- `pm digest` — week-to-date activity digest
- `pm stale --action` — interactive stale project triage
- `pm brief [--imessage] [--only-if-urgent]` — daily intelligent briefing with anomaly detection
- `pm agent assess/run/batch` — two-phase assess/execute/escalate agent orchestration
- Streamlit dashboard — 4 tabs: Projects, Activity, Stale, Docs (Priority/Deadline/Notes inline editing)
- iMessage channel configured (`cci` alias, `+12064962555` allowlisted)
- launchd job: `com.pm.daily-brief` fires at 8am daily
- DB at `~/.pm/projects.db` (override with `PM_DB_PATH`)

---

## Phase 1: Foundation Hardening
**Goal:** Fix the code review HIGH-priority items before building anything new on top.
**Effort:** ~23 SP | **Target:** Before any Phase 2 work begins

### 1.1 Security Fixes (Sprint 1, 5.5 SP) — ✅ COMPLETE
- [x] **TD-001**: Remove `shell=True` from tmux subprocess
- [x] **TD-002**: Sanitize `project.name` before use as filesystem path component
- [x] **TD-006**: Fix bare `except:` in `tags_list` → `except json.JSONDecodeError:`
- [x] **TD-010**: Narrow migration error swallowing to `OperationalError("duplicate column")`
- [x] **TD-018**: Atomic write in `write_pm_status` — temp file + `os.replace()`

### 1.2 Architecture Fixes (Sprint 2, 15 SP) — ✅ COMPLETE
- [x] **TD-003**: Delete dead first `launch` command
- [x] **TD-004**: Thread-safe `init_db()` with `threading.Lock()` guard
- [x] **TD-007**: `tests/test_metadata.py` — `pm/metadata.py` at 97% coverage
- [x] **TD-008**: Tests for all new CLI commands (brief, someday, urgent --all, shutdown)

### 1.3 Migration Safety (Sprint 3, 8 SP) — ✅ COMPLETE
- [x] **TD-005**: Wrap migration in a single transaction; `schema_migrations` version tracking table
- [x] `agent_runs` table added via migration registry

---

## Phase 2: Code Quality & Infrastructure
**Goal:** Eliminate duplication and add CI so the codebase is maintainable at scale.
**Effort:** ~30 SP

### 2.1 Refactoring (Sprint 4, 10 SP) — ✅ COMPLETE
- [x] **TD-009**: Bind dashboard to `127.0.0.1` in `dashboard.sh`
- [x] **TD-011**: `--permission-mode` param on executor; readonly templates use `readonly`
- [x] **TD-012/013**: Merged `_sync_project` / `_sync_project_to_file` → `sync_project_to_file()` in `pm/metadata.py`
- [x] **TD-014**: Extracted `apply_project_filter(query, filter_str)` — replaces 6 duplicated filter blocks

### 2.2 Infrastructure (Sprint 3–4, 6 SP) — ✅ COMPLETE
- [x] **TD-019**: `tests/test_dashboard_helpers.py` — 20 tests for dashboard business logic
- [x] **TD-020**: `.github/workflows/test.yml` CI pipeline (macos-latest, pytest --cov, threshold 75%)
- [x] **TD-021**: Port conflict detection in `dashboard.sh` (`PM_DASHBOARD_PORT` env override)
- [x] **TD-022**: DB moved to `~/.pm/projects.db`, `PM_DB_PATH` env override supported

### 2.3 Quality Polish (Sprint 5, 14 SP) — ✅ COMPLETE
- [x] **TD-015**: Deleted `pm/api/` empty stub package
- [x] **TD-016**: Single `PRIORITY_LABELS` constant in `models.py`, imported by `metadata.py`
- [x] **TD-017**: Moved all deferred imports to top of `pm/cli.py`
- [x] **TD-019**: `tests/test_dashboard_helpers.py` — 20 tests for dashboard business logic

---

## Phase 3: Agent Orchestration System
**Goal:** Semi-autonomous multi-agent system that intelligently advances the portfolio.
**Effort:** ~60–80 SP | **Requires:** Phase 1 complete (especially TD-004, TD-005)

### 3.1 Architecture

The agent system uses a two-phase protocol:

**Phase A — Assess (read-only)**
Each agent independently evaluates one project:
1. Read CLAUDE.md, TODO.md, PROGRESS.md, git log, recent transcripts
2. Score confidence: "I know exactly what to do next" (0–100)
3. Classify work type: `code`, `review`, `docs`, `planning`, `blocked`
4. Estimate irreversibility: `safe` / `needs-review` / `human-required`
5. Return assessment without taking any action

**Phase B — Execute or Escalate**
Based on the assessment:
- **Confidence ≥ 80 + work is `safe`**: Execute autonomously (`--permission-mode acceptEdits`)
- **Confidence 50–79 OR work is `needs-review`**: Request approval via iMessage, proceed if approved within 10m
- **Confidence < 50 OR work is `human-required`**: Block and escalate to iMessage with full context
- **Budget/timeout exceeded**: Log and move to next project

### 3.1–3.4 Core Agent System — ✅ COMPLETE (2026-04-10)
- [x] `pm/agent/planner.py` — assess phase (read-only Claude, confidence 0–100, risk level)
- [x] `pm/agent/runner.py` — execution phase (headless Claude with configurable tools/budget)
- [x] `pm/agent/coordinator.py` — ThreadPoolExecutor batch orchestration with escalation hook
- [x] `pm/agent/escalation.py` — iMessage send + chat.db reply polling (10m timeout)
- [x] `agent_runs` table in SQLite (versioned migration)
- [x] `pm agent assess/run/batch` CLI commands

### 3.2 Core Components (Design Reference)

#### `pm/agent/planner.py` — Portfolio Planner
- Selects which projects to run in a given batch
- Selection criteria: urgency score, days since last agent run, git dirty state, has pending decision
- Avoids selecting projects currently being worked on in live Claude sessions
- Configurable: `pm agent run --limit 5 --filter type:client`

#### `pm/agent/runner.py` — Single Project Agent
- Wraps `executor.py` with the two-phase assess/execute protocol
- Returns `AgentResult` dataclass: `{project, phase, confidence, work_type, status, output, cost}`
- Uses `--permission-mode acceptEdits` for `code`/`docs` work, `readonly` for assessment
- Writes transcript to `transcripts/<project>/<timestamp>-agent.md`
- Updates DB: `last_agent_run`, `agent_status`, `agent_cost_usd`

#### `pm/agent/coordinator.py` — Batch Coordinator
- Runs multiple agents concurrently via `ThreadPoolExecutor`
- Global budget cap: stops new agents once total spend reaches `--max-budget`
- Progress reporting via `progress_callback` (for dashboard polling)
- Human-in-the-loop: blocks execution when any agent escalates, resumes when approved

#### `pm/agent/escalation.py` — iMessage Escalation Handler
- Sends iMessage notification via AppleScript when agent needs human input
- Message format: `[PM] <project>: <why blocked>\nOptions:\n1) Proceed\n2) Skip\n3) Archive`
- Polls `chat.db` for reply (via existing iMessage MCP tools)
- Timeout: if no reply in 10m, agent is marked `waiting` and skipped in current batch

### 3.3 Database Schema Additions

```sql
-- Agent run tracking
CREATE TABLE agent_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES projects(id),
    started_at  DATETIME NOT NULL,
    finished_at DATETIME,
    phase       TEXT,        -- 'assess', 'execute'
    confidence  INTEGER,     -- 0-100
    work_type   TEXT,        -- 'code', 'review', 'docs', 'planning', 'blocked'
    status      TEXT,        -- 'success', 'escalated', 'skipped', 'timeout', 'error'
    cost_usd    FLOAT,
    transcript_path TEXT
);

-- New columns on projects table
ALTER TABLE projects ADD COLUMN last_agent_run DATETIME;
ALTER TABLE projects ADD COLUMN agent_status TEXT;  -- last agent outcome
ALTER TABLE projects ADD COLUMN total_agent_cost_usd FLOAT DEFAULT 0;
```

### 3.4 CLI Commands

```bash
pm agent assess [N]              # Assess top N projects (read-only, no changes)
pm agent run [N]                 # Full assess+execute cycle on top N projects
    --limit N                    # Max projects per batch (default: 5)
    --max-budget 5.00            # Total USD cap for this run
    --filter type:client         # Only client projects
    --dry-run                    # Show what would run, no execution
    --confidence-threshold 80    # Minimum confidence to auto-execute

pm agent status                  # Show recent agent runs
pm agent history [project]       # Per-project agent run history
pm agent cost [--since YYYY-MM-DD]  # Total cost report
```

### 3.5 Dashboard Integration (Agents Tab)
- New "Agents" tab in Streamlit dashboard
- Real-time progress display during batch runs
- Approval queue: pending escalations with Approve/Skip/Archive buttons
- Agent cost tracking: daily/weekly spend chart
- Per-project agent history inline in project cards

### 3.6 iMessage Control Interface
Via `cci` (Claude with iMessage channel), or directly via text to `+12064962555`:

```
pm status              → "14 projects overdue, 3 with decisions pending"
pm run 3               → Run agent on top 3 urgent projects
pm stale               → "8 projects stale >30 days, want to review?"
pm cost                → "This week: $4.23 across 47 agent runs"
pm approve [project]   → Approve blocked agent to proceed
pm skip [project]      → Skip a blocked agent
```

---

## Phase 4: Advanced Intelligence
**Goal:** Move beyond mechanical task execution toward genuine project advancement.
**Effort:** ~40–60 SP | **Requires:** Phase 3 stable

### 4.1 Cross-Project Awareness
- Agent planner builds a global dependency graph (which projects share libraries, clients, etc.)
- Agent knows which other projects are being worked on concurrently
- Avoid conflicting changes to shared packages

### 4.2 Agent Memory — ✅ COMPLETE
- [x] `pm/agent/memory.py` — `AgentMemory` dataclass, read/write `docs/AGENT-CONTEXT.md`
- [x] Planner reads memory before assessing — injects context block into assess prompt
- [x] Runner appends run entry on successful execution
- [x] `pm agent memory <project> [--clear]` CLI command
- [x] 32 tests covering parse, roundtrip, append, clear, and CLI

### 4.3 Scheduling & Autonomy Modes — ✅ COMPLETE
- [x] `pm schedule install` — writes launchd plist, loads into launchd, creates logs dir
- [x] `pm schedule uninstall` — unloads + deletes plist
- [x] `pm schedule status` — shows loaded state + last log line
- [x] Matches existing `com.pm.daily-brief` plist convention
- [x] 16 tests covering plist generation, install/uninstall/status paths

### 4.4 Intelligent Triage — ✅ COMPLETE
- [x] `pm triage` — finds projects with `has_pending_decision=True`, runs read-only assessment
- [x] Outputs decision summary + recommended option + confidence score
- [x] `--imessage` flag sends each recommendation via iMessage
- [x] `--dry-run` lists projects without running Claude
- [x] `--limit N` caps project count
- [x] Handles timeout, FileNotFoundError, unparseable output gracefully
- [x] 9 tests covering all paths including iMessage send/failure

### 4.5 Budget Intelligence — ✅ COMPLETE
- [x] `cost_usd` column added to `AgentRun` (migration version 2)
- [x] `_record_agent_run()` helper writes to `agent_runs` table after every assess+execute
- [x] `pm agent costs [--days N] [--limit N]` — per-project cost table with run counts, totals, avg duration
- [x] Budget alert: warns when estimated weekly spend exceeds $10
- [x] 8 tests covering empty DB, run count, cost total, client name, days filter, totals line, alert

---

## Technical Notes

### iMessage Channel Status (2026-03-31)
- Plugin: `imessage@claude-plugins-official` installed and enabled
- Alias: `cci` = `claude --dangerously-skip-permissions --continue --channels plugin:imessage@claude-plugins-official`
- Allowlist: `+12064962555` in `~/.claude/channels/imessage/access.json`
- Known issue: actual chat GUID format TBD (will resolve on first live message)
- **Rule**: only ONE `cci` window open at a time to avoid echo/loop

### Cloudflare Tunnel Status (2026-03-28 fixed)
- Service: `com.cloudflare.cloudflared` via launchd
- Endpoint: `claude-notify.servicevision.io` → localhost:3000
- Status: running, 4 connections to Seattle edge nodes
- Fixed: was missing `tunnel run` args in plist

### Headless Claude Invocation Pattern
```python
# Current canonical implementation: pm/docgen/executor.py
result = run_doc_generation(
    project_path=Path(project_path),
    prompt=prompt,
    output_file=output_file,
    max_budget_usd=budget,
    allowed_tools=["Read", "Glob", "Grep"],
)
# All other callers (cli.py, dashboard) should delegate to this
```

### Permission Model for Agents
| Work Type | Permission Mode | Can Write? |
|-----------|----------------|------------|
| Assess / read-only analysis | `--permission-mode readonly` | No |
| Doc generation | `--permission-mode readonly` (writes via executor stdout) | Output file only |
| Code changes | `--permission-mode acceptEdits` | Yes, with review |
| Autonomous execution | `--dangerously-skip-permissions` | Yes (confidence ≥ 80) |

---

## Backlog (Unscheduled)
- [x] `pm gc` — remove DB records for projects that no longer exist on disk (with `--dry-run`)
- `pm shutdown` support for Terminal.app (TD-046)
- Alembic schema versioning (TD-005 long-term)
- REST API via `pm/api/` for dashboard → CLI parity (currently CLI is superset)
- Ghostty / WezTerm support in `pm/terminal.py`
- Per-client billing rollup (hours_logged × rate)
- Export: generate weekly client reports as PDFs
- GitHub integration: link project DB records to repo issues/PRs

---

## Sprint Reference

| Sprint | Phase | Key Items | SP |
|--------|-------|-----------|-----|
| S1 | 1.1 | TD-001, 002, 006, 010, 018 | 5.5 |
| S2 | 1.2 | TD-003, 004, 007, 008 | 15 |
| S3 | 1.3 + 2.2 | TD-005, 019, 020 | 19 |
| S4 | 2.1 | TD-009, 011–014 | 10 |
| S5 | 2.3 | TD-015–030 | 20 |
| S6–S8 | 3.1–3.3 | Agent planner, runner, coordinator | ~40 |
| S9 | 3.4–3.5 | CLI commands, dashboard Agents tab | ~20 |
| S10 | 3.6 | iMessage control interface | ~10 |
| S11+ | 4.x | Advanced intelligence features | ~50 |
