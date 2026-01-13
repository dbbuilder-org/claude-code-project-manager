# Project Manager - Multi-Project Claude Code Orchestration System

## Executive Summary

A dashboard and orchestration system for managing 200+ development projects built with Claude Code. The system parses progress documents, tracks project state, and enables intelligent "continue" command generation for seamless development workflow resumption.

---

## Problem Statement

With ~200 projects in `~/dev2`:
- **91 progress/status files** (TODO.md, PROGRESS.md, ROADMAP.md, STATUS.md)
- **85 CLAUDE.md files** with project context
- No unified view of project states
- Manual effort to determine "where was I?" for each project
- No way to batch-continue multiple projects efficiently

---

## Research Summary

### Existing Tools Evaluated

| Tool | Approach | Pros | Cons |
|------|----------|------|------|
| [claude-flow](https://github.com/ruvnet/claude-flow) | Hive-mind swarm orchestration | Memory persistence, 64 agents | Overkill for project tracking |
| [Claude-Code-Workflow](https://github.com/catlog22/Claude-Code-Workflow) | JSON-driven state machine | Clean state tracking | Different paradigm (workflows, not projects) |
| [claudecoderun](~/dev2/claudecoderun) | Terminal launcher | Already exists, proven | No dashboard, no state parsing |
| Claude Code Headless Mode | `-p` flag + `--output-format stream-json` | Official, scriptable | No persistence between sessions |

### Key Insight from Anthropic Best Practices

> "Running multiple Claude instances in parallel enables efficient concurrent work... Have one Claude write code while another reviews it."

Multiple git worktrees + parallel Claude sessions is the recommended approach.

---

## Architecture Design

### Layer 1: Project Scanner & Parser

```
project-manager/
├── scanner/
│   ├── project_detector.py      # Detect valid projects (has package.json, pyproject.toml, etc.)
│   ├── progress_parser.py       # Parse TODO.md, PROGRESS.md, STATUS.md
│   ├── claude_md_parser.py      # Extract context from CLAUDE.md
│   └── git_status_checker.py    # Check last commit, dirty state, branches
```

**Progress Document Patterns Detected:**

1. **Completion Tracking:**
   - `## ✅ Completed Tasks (6 of 8)` → 75% complete
   - `- [x]` vs `- [ ]` checkboxes
   - Phase indicators: `Phase 7.1`, `Pre-Phase 7`

2. **Priority Markers:**
   - `**Priority**: CRITICAL`
   - `**Status**: ✅ COMPLETE` / `⏳ IN PROGRESS` / `⬜ NOT STARTED`

3. **Current State:**
   - `## 🎯 Current Status` sections
   - `### Next Steps` / `📝 Notes for Next Session`
   - `**Current Focus**:` / `**Last Updated**:`

4. **Decision Points:**
   - `### Option A: ...` / `Option B: ...`
   - `**Current Recommendation**:`

### Layer 2: State Database

```sql
-- SQLite database for fast local queries
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT,                    -- 'client', 'internal', 'tool'
    last_scanned DATETIME,
    last_activity DATETIME,       -- From git log

    -- Parsed state
    completion_pct REAL,
    current_phase TEXT,
    current_status TEXT,          -- 'active', 'paused', 'blocked', 'complete'
    next_action TEXT,             -- Parsed "next step"
    decision_pending BOOLEAN,

    -- Git state
    git_branch TEXT,
    git_dirty BOOLEAN,
    last_commit_date DATETIME,
    last_commit_msg TEXT
);

CREATE TABLE progress_items (
    id INTEGER PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    type TEXT,                    -- 'todo', 'phase', 'milestone'
    content TEXT,
    status TEXT,                  -- 'pending', 'in_progress', 'complete', 'blocked'
    priority TEXT,                -- 'critical', 'high', 'medium', 'low'
    source_file TEXT,
    line_number INTEGER
);

CREATE TABLE scan_history (
    id INTEGER PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    scanned_at DATETIME,
    completion_pct REAL,
    items_total INTEGER,
    items_complete INTEGER
);
```

### Layer 3: Dashboard Web UI

**Tech Stack:**
- **Backend:** FastAPI (Python) - simple REST API
- **Frontend:** React + Tailwind (or Streamlit for rapid prototyping)
- **Real-time:** WebSocket for live scanning updates

**Dashboard Views:**

1. **Portfolio Overview**
   ```
   ┌─────────────────────────────────────────────────────────────────┐
   │  PROJECT PORTFOLIO          [Scan All] [Filter: Active ▼]      │
   ├─────────────────────────────────────────────────────────────────┤
   │  Client Projects (24)    ████████████░░░░░░░░  62% avg         │
   │  Internal IP (156)       ██████░░░░░░░░░░░░░░  34% avg         │
   │  Tools (20)              ████████████████████  89% avg         │
   └─────────────────────────────────────────────────────────────────┘
   ```

2. **Project Cards**
   ```
   ┌─────────────────────────────────────────────┐
   │  remoteC                 [▶ Continue] [👁]  │
   │  Phase: Pre-7.1 Testing                     │
   │  ████████████████░░░░  75%                  │
   │  ⚠ Decision pending: Option A vs B         │
   │  Next: Execute manual tests (4-6 hrs)      │
   │  Last activity: 2 days ago                 │
   └─────────────────────────────────────────────┘
   ```

3. **Batch Operations**
   - Select multiple projects
   - Generate batch continue commands
   - Parallel terminal launch via claudecoderun

### Layer 4: Continue Command Generator

**Intelligence Levels:**

1. **Simple Continue** (no context):
   ```bash
   claude --resume
   ```

2. **Context-Aware Continue** (parsed state):
   ```bash
   claude -p "Continue from Phase 7.1 testing. Next action: Execute PIN authorization tests.
   Reference TODO.md lines 69-95 for test scenarios."
   ```

3. **Decision-Point Continue** (needs input):
   ```bash
   claude -p "Decision required: Choose Option A (Pre-Phase 7 testing) or Option B (Phase 7 immediate start).
   Recommendation from TODO.md: Option A. Confirm or override?"
   ```

**Prompt Generation Logic:**

```python
def generate_continue_prompt(project: Project) -> str:
    parts = []

    # Current state
    if project.current_phase:
        parts.append(f"Continue from {project.current_phase}.")

    # Pending items
    pending = get_pending_items(project, limit=3)
    if pending:
        parts.append("Immediate tasks:")
        for item in pending:
            parts.append(f"  - {item.content}")

    # Decision points
    if project.decision_pending:
        decision = get_pending_decision(project)
        parts.append(f"\n⚠️ Decision needed: {decision.question}")
        parts.append(f"Options: {', '.join(decision.options)}")
        if decision.recommendation:
            parts.append(f"Recommended: {decision.recommendation}")

    # Reference files
    relevant_files = get_relevant_files(project)
    if relevant_files:
        parts.append(f"\nRelevant context: {', '.join(relevant_files)}")

    return "\n".join(parts)
```

### Layer 5: Integration with claudecoderun

Extend existing `claudecoderun_stage.py`:

```python
# New mode: --from-dashboard
python claudecoderun.py ~/dev2 \
    --from-dashboard \
    --projects "remoteC,github-spec-kit-init,anterix" \
    --prompt-mode context-aware
```

**Flow:**
1. Dashboard UI selects projects
2. API generates continue prompts for each
3. claudecoderun launches terminals with injected prompts
4. Progress reported back to dashboard via file watcher

---

## Implementation Phases

### Phase 1: Core Scanner (Week 1)
- [ ] Project detector (find all valid projects)
- [ ] Progress document parser (TODO.md, PROGRESS.md patterns)
- [ ] SQLite database setup
- [ ] CLI tool: `pm scan` - scan all projects
- [ ] CLI tool: `pm status` - show summary

### Phase 2: Dashboard UI (Week 2)
- [ ] FastAPI backend with REST endpoints
- [ ] Simple Streamlit dashboard (rapid prototype)
- [ ] Project cards with status indicators
- [ ] Filtering and sorting

### Phase 3: Smart Continue (Week 3)
- [ ] Continue prompt generator
- [ ] Decision point detection
- [ ] Integration with claudecoderun
- [ ] Batch launch capability

### Phase 4: Polish & Automation (Week 4)
- [ ] Background scanning daemon
- [ ] Git activity tracking
- [ ] Progress history/trends
- [ ] React dashboard (if Streamlit insufficient)

---

## Quick Start Commands

```bash
# Initialize project manager
cd ~/dev2/project-manager
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# First scan
pm scan ~/dev2

# View dashboard
pm dashboard --port 8080

# Continue specific project
pm continue remoteC

# Batch continue client projects
pm continue --filter type:client --parallel 3
```

---

## File Structure

```
~/dev2/project-manager/
├── DESIGN.md              # This file
├── CLAUDE.md              # Claude Code guidance
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Modern Python packaging
│
├── pm/                    # Main package
│   ├── __init__.py
│   ├── cli.py             # Click-based CLI
│   ├── config.py          # Configuration management
│   │
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── detector.py    # Project detection
│   │   ├── parser.py      # Progress document parsing
│   │   └── git.py         # Git status checking
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py      # SQLAlchemy models
│   │   └── queries.py     # Common queries
│   │
│   ├── generator/
│   │   ├── __init__.py
│   │   └── prompts.py     # Continue prompt generation
│   │
│   └── api/
│       ├── __init__.py
│       ├── main.py        # FastAPI app
│       └── routes.py      # API endpoints
│
├── dashboard/             # Streamlit dashboard
│   └── app.py
│
├── tests/
│   └── ...
│
└── data/
    └── projects.db        # SQLite database
```

---

## Key Metrics to Track

| Metric | Source | Purpose |
|--------|--------|---------|
| Completion % | Parsed from progress docs | Overall health |
| Last Activity | Git log | Stale project detection |
| Pending Decisions | Parsed from TODO.md | Blockers |
| Phase/Stage | Parsed from progress docs | Workflow position |
| Dirty State | Git status | Uncommitted work |
| Items In Progress | Parsed checkboxes | Active work count |

---

## Integration Points

### With claudecoderun
- Extend `--from-dashboard` mode
- Share project database
- Report completion status back

### With CLAUDE.md
- Read for project context
- Inject into continue prompts
- Respect project-specific instructions

### With Git
- Track branch, commits, dirty state
- Auto-detect stale projects
- Suggest stash/commit before continue

---

## Success Criteria

1. **Single command to see all project status:** `pm status`
2. **One-click continue** from dashboard with smart context
3. **Batch operations** for client vs internal projects
4. **Staleness detection** - highlight projects with no activity
5. **Decision tracking** - surface blocked projects needing input

---

## Sources & References

- [claude-flow](https://github.com/ruvnet/claude-flow) - Hive-mind orchestration patterns
- [Claude-Code-Workflow](https://github.com/catlog22/Claude-Code-Workflow) - JSON state machine approach
- [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices) - Headless mode, parallel instances
- [AI Project Management Tools 2025](https://www.stepsize.com/blog/best-ai-project-management-tools) - Dashboard design patterns
- [Multi-Agent Orchestration](https://sjramblings.io/multi-agent-orchestration-claude-code-when-ai-teams-beat-solo-acts/) - Parallel agent patterns
