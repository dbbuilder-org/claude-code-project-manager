# Project Manager - Claude Code Orchestration Dashboard

Multi-project tracking and orchestration tool for managing ~200+ Claude Code projects.

## Quick Start

```bash
# Scan all projects
pm scan ~/dev2

# Launch dashboard
./dashboard.sh
# Or from anywhere: ~/dev2/project-manager/dashboard.sh
# Or from Spotlight: "Project Manager"

# CLI commands
pm status                    # List all projects with health scores
pm urgent                    # Show only projects with real urgency signals (deadlines, priority 1/2)
pm urgent --all              # Show all projects ranked by urgency
pm edit <project> --priority 1 --deadline 2025-02-01
pm someday <project>         # Park a project in the Someday pile (priority 5)
pm backlog                   # Show someday + archived projects
pm health                    # Detailed health report
pm continue [project]        # Generate Claude Code continue prompt
pm summary                   # Quick portfolio summary (counts by type/category/health)
pm tags list                 # See all tags with counts
pm digest                    # Week-to-date activity digest
pm stale                     # Find inactive projects
pm brief                     # Morning briefing: deadlines, anomalies, high-priority, wins
pm brief --imessage          # Send brief via iMessage
pm gc                        # Remove DB records for projects no longer on disk
pm run <project> "prompt"    # Run headless Claude Code on a project
pm agent assess <project>    # Assess project state (read-only, confidence 0-100)
pm agent run <project>       # Assess then auto-execute if confident (≥80, safe)
pm agent batch               # Assess/execute top-N projects in parallel
pm agent memory <project>    # View agent memory (docs/AGENT-CONTEXT.md)
pm agent costs               # Per-project agent run costs + budget alert
pm triage                    # Assess pending decisions and recommend an option
pm schedule install          # Install nightly agent batch (launchd, default 2am)
pm schedule uninstall        # Remove launchd schedule
pm schedule status           # Show schedule status and last log entry
```

## Architecture

```
project-manager/
├── pm/                      # Core Python package
│   ├── cli.py              # Click CLI (pm command)
│   ├── terminal.py         # Terminal detection + AppleScript generation
│   ├── metadata.py         # PM-STATUS.md two-way sync
│   ├── digest.py           # Activity digest queries (shared CLI + dashboard)
│   ├── database/
│   │   └── models.py       # SQLAlchemy models + migration
│   ├── scanner/
│   │   ├── detector.py     # Project type detection
│   │   └── parser.py       # TODO.md/PROGRESS.md parsing
│   ├── generator/
│   │   └── prompts.py      # Claude Code context generation
│   ├── docgen/             # Document generation system
│   │   ├── templates.py    # 7 built-in doc templates
│   │   ├── context.py      # ProjectContext builder
│   │   └── executor.py     # Headless Claude Code runner
│   └── agent/              # Agent orchestration system
│       ├── planner.py      # Assess phase (read-only Claude, confidence 0-100)
│       ├── runner.py       # Execute phase (headless Claude, configurable tools)
│       ├── coordinator.py  # Batch orchestration (ThreadPoolExecutor)
│       └── escalation.py   # iMessage send + chat.db reply polling
├── dashboard/
│   └── app.py              # Streamlit web UI (4 tabs: Projects, Activity, Stale, Docs)
├── transcripts/             # Prompt run transcripts (per-project subdirs)
├── ~/.pm/
│   └── projects.db         # SQLite database (override with PM_DB_PATH env var)
├── dashboard.sh            # Launch script (PM_DASHBOARD_PORT for port override)
└── tests/                  # Tests with coverage
```

## Key Features

### Project Scanning
- Detects project types: node, python, rust, go, swift, etc.
- Parses TODO.md, PROGRESS.md, CLAUDE.md for progress state
- Extracts git state (branch, dirty, last commit)
- Handles `clients/` subfolder with auto-categorization
- Reads PM-STATUS.md for user metadata

### PM Metadata (Two-Way Sync)
Projects can have a `PM-STATUS.md` file with YAML frontmatter:

```markdown
---
priority: 2  # high
deadline: 2025-02-15
target_date: 2025-03-01
tags: [mobile, ios]
client: Acme Corp
budget_hours: 40
hours_logged: 12
archived: false
---

# Project Notes

Free-form notes, decisions, context here...
```

- Scanner reads PM-STATUS.md during `pm scan`
- CLI `pm edit` writes back to PM-STATUS.md (--sync flag, default on)
- Dashboard inline edits sync to PM-STATUS.md automatically

### Health Score (0-100)
Calculated from:
- Completion progress (0-30 pts)
- Has CLAUDE.md (10 pts)
- Has progress files (10 pts)
- Recent activity (0-20 pts)
- No pending decisions (10 pts)
- Clean git state (10 pts)
- Known project type (10 pts)

### Urgency Score (0-100)
Based on:
- Priority level (1=critical +40, 5=someday +0)
- Days until deadline (overdue +50, <3 days +40, etc.)
- Target date (softer urgency when no deadline)

### Tags
- Gmail-style labels for project categorization
- Stored as JSON list in `tags` column
- Add/remove via CLI (`pm tags add/remove`) or dashboard inline editing
- Bulk apply via CLI (`pm tags bulk <tag> ...`) or dashboard checkbox selection
- Filter by tags in dashboard multiselect

### Activity Digest
- Tracks project activity over a date range (default: week-to-date, Sunday–today)
- Two views: **By Project/Client** (completion delta, status) and **By Day** (project counts)
- Queries both ScanHistory and commit dates for complete picture
- Shared query module (`pm/digest.py`) used by CLI and dashboard

### Stale Detection
- Identifies projects inactive 30+ days, not archived, not priority=5 (someday)
- Interactive action prompts: Archive, Move Forward, Pivot, Plan, Combine, Replace
- Each action updates DB metadata and syncs to PM-STATUS.md

### Prompt Runner
- Run headless Claude Code (`claude -p`) against any project
- Configurable budget, timeout, and allowed tools
- Results logged to `transcripts/<project>/<timestamp>.md`
- View transcripts via CLI (`pm transcripts`) or dashboard

### Dashboard Tabs
- **Projects**: Expandable cards with inline editing, tag filtering, bulk operations
- **Activity**: Digest views with date picker (by project/client or by day)
- **Stale**: Stale project list with 6 action buttons per project
- **Docs**: Document generation and history

Each project card has:
- Quick actions: Claude Code, VSCode, Terminal, Finder
- Inline editing: Priority, Deadline, Target, Notes, Tags (saves to PM-STATUS.md)
- Run Prompt section: text area + Run button, transcript logging
- File previews: TODO.md, PROGRESS.md, CLAUDE.md tabs
- Batch selection for multi-project Claude Code launch and bulk tag apply

### Progress Document Parsing

The parser looks for these patterns:
- `## ✅ Completed Tasks (X of Y)` → completion percentage
- `- [x]` / `- [ ]` → checkbox items
- `**Status**: COMPLETE/IN PROGRESS` → status markers
- `### Next Steps` / `**Next Step**:` → next action extraction
- `### Option A:` / `Option B:` → decision points

### Project Detection

A directory is considered a project if it has:
- `package.json` (Node.js)
- `pyproject.toml` or `setup.py` (Python)
- `Cargo.toml` (Rust)
- `go.mod` (Go)
- `.csproj` or `.sln` (C#/.NET)
- `Package.swift` (Swift)
- `CLAUDE.md` (any Claude Code project)

## Database Schema

### Project Model
```python
id: str (primary key)
path: str (unique)
name: str
project_type: str  # node, python, rust, etc.
category: str      # client, internal, tool

# Scan metadata
last_scanned: datetime
last_activity: datetime

# Progress state (parsed from docs)
completion_pct: float
current_phase: str
current_status: str
current_focus: str
next_action: str
has_pending_decision: bool

# Git state
git_branch: str
git_dirty: bool
last_commit_date: datetime
last_commit_msg: str

# Files found
has_claude_md: bool
has_todo: bool
has_progress: bool
progress_files: str  # JSON list

# PM metadata (user-editable, syncs to PM-STATUS.md)
notes: str
deadline: datetime
target_date: datetime
priority: int        # 1=critical, 2=high, 3=normal, 4=low, 5=someday
tags: str           # JSON list
client_name: str
budget_hours: float
hours_logged: float
archived: bool
```

## Terminal Support

The project manager supports both **iTerm2** and **Terminal.app** for launching Claude Code sessions.

### Detection
- Checks for `/Applications/iTerm.app` directory existence
- If iTerm2 is installed: uses iTerm2 (starts it if not running)
- If not installed: falls back to Terminal.app
- `--terminal` flag on `pm launch` forces Terminal.app

### Shared Module: `pm/terminal.py`
All terminal logic is centralized in `pm.terminal`, used by:
- `pm/cli.py` — CLI launch/shutdown commands
- `dashboard/app.py` — Dashboard launch buttons
- `scripts/claude-launch.sh` — Shell script (has its own equivalent detection)

### Feature Differences

| Feature | iTerm2 | Terminal.app |
|---------|--------|-------------|
| Single launch | Named tab in PM window | Individual window |
| Batch launch | One window, multiple tabs | Multiple individual windows |
| PM window detection | Search by "PM:" prefix | Not possible |
| Session naming | `set name to "PM: ..."` | Not supported |
| Focus preservation | Save/restore frontmost app | `activate` only |
| `pm shutdown` | Full support | Not supported (shows message) |

## CLI Reference

```bash
pm scan <path>              # Scan directory for projects
pm status [--filter X]      # List projects (filter: type:python, category:client)
pm health [--limit N]       # Health report
pm urgent                   # Show only projects with urgency signals (deadlines, priority 1/2, overdue)
    --all                   # Show all projects ranked by urgency score
pm backlog                  # Show someday/archived projects
pm someday <name>           # Move project to Someday pile (priority 5); restore with pm edit --priority 3
pm continue <name>           # Generate Claude Code context prompt

# ── Morning Briefing ──
pm brief                    # Intelligent daily briefing
    --verbose, -v           # Show next actions for high-priority projects
    --imessage, -i          # Send via iMessage (+12064962555)
    --only-if-urgent        # Suppress output if nothing needs attention
    --days N                # Lookback window (default: 7)

pm launch [N|name]          # Launch projects (iTerm2 or Terminal.app)
    pm launch               # Launch 10 most recent (default)
    pm launch 5             # Launch 5 most recent
    pm launch myproject     # Launch specific project by name
    --dirty-only, -d        # Only projects with uncommitted changes
    --dry-run               # Preview without launching
    --terminal              # Force Terminal.app instead of iTerm2

pm shutdown                 # Gracefully shutdown all Claude Code sessions
    --no-context            # Skip writing context docs (quick shutdown)
    --context-wait N        # Seconds to wait for context (default: 60)
    --dry-run               # Preview without executing
    # Sends "write context to docs/PROJECT-CONTEXT.md", waits, sends /exit, closes tabs
    # Sessions processed in parallel with 2s stagger

pm edit <name> [options]    # Edit metadata (syncs to PM-STATUS.md)
    --priority 1-5
    --deadline YYYY-MM-DD
    --target YYYY-MM-DD
    --client "Name"
    --tags tag1,tag2
    --notes "text"
    --budget-hours N
    --hours-logged N
    --archived/--no-archived
    --sync/--no-sync        # Write to PM-STATUS.md (default: sync)

# ── Tags ──
pm tags list                         # All tags with project counts
pm tags add <project> <tag>          # Add tag to project
pm tags remove <project> <tag>       # Remove tag from project
pm tags bulk <tag> [projects...]     # Apply tag to multiple projects
    --filter type:client             # Or by filter
    --sync/--no-sync                 # PM-STATUS.md sync (default: on)

# ── Activity Digest ──
pm digest                              # Week-to-date by project/client
pm digest --by-day                     # Week-to-date grouped by day
pm digest -s 2026-01-01 -e 2026-01-31  # Custom date range
pm digest --client "Acme"              # Filter by client name

# ── Stale Detection ──
pm stale                    # List stale projects (30+ days inactive)
pm stale --days 60          # Custom inactivity threshold
pm stale --action           # Interactive: prompt for action on each project
    # Actions: [1] Archive  [2] Move forward  [3] Pivot
    #          [4] Plan     [5] Combine       [6] Replace

# ── Garbage Collection ──
pm gc                       # Remove DB records for projects no longer on disk
pm gc --dry-run             # Preview which records would be removed

# ── Prompt Runner ──
pm run <project> "<prompt>"              # Run headless Claude Code on project
    --budget 0.50                        # Max budget in USD (default: 0.50)
    --timeout 300                        # Timeout in seconds (default: 300)
    --tools Read,Glob,Grep               # Allowed tools (default: Read,Glob,Grep)
pm transcripts [project]                 # List prompt run transcripts
    --limit 10                           # Number to show (default: 10)

# ── Document Generation ──
pm docs generate <template> [project]  # Generate doc using headless Claude Code
    pm docs generate roadmap myproject           # Single project
    pm docs generate architecture --all          # All projects
    pm docs generate code-review --filter type:client  # Filtered
    pm docs generate status-report --top 10      # Top 10 by urgency
    pm docs generate roadmap,architecture myproject  # Multiple templates
    --parallel N            # Max parallel workers (default 3)
    --dry-run               # Show what would be generated
    --force                 # Regenerate even if recent (<7 days)
    --max-budget N          # Override per-project budget cap

pm docs list               # List available templates
pm docs history [project]  # Show generation history
pm docs status [project]   # Show which docs exist/are stale

# ── Agent Orchestration ──
pm agent assess <name>                    # Read-only assessment: confidence + proposed action
    --context "fix failing tests"         # Focus hint
    --timeout 120                         # Seconds (default: 120)

pm agent run <name>                       # Two-phase: assess then execute if safe
    --force                               # Execute regardless of confidence/risk
    --dry-run                             # Assess only, no execution
    --budget 1.00                         # Max USD (default: 1.00)
    --timeout 300                         # Execution timeout (default: 300)

pm agent batch                            # Parallel assess+execute across top-N projects
    --limit 5                             # Max projects (default: 5)
    --filter type:client                  # Filter: same syntax as pm urgent
    --budget 1.00                         # Budget per project
    --workers 3                           # Parallel workers (default: 3)
    --context "fix tests"                 # Focus hint for all assessments
    --dry-run                             # Assess only

pm agent memory <name>                    # View per-project agent memory (docs/AGENT-CONTEXT.md)
    --clear                               # Delete the AGENT-CONTEXT.md file

pm agent costs                            # Per-project run costs and activity
    --days 30                             # Lookback window (default: 30)
    --limit 20                            # Max rows (default: 20)
    # Warns if estimated weekly spend > $10

# ── Intelligent Triage ──
pm triage                                 # Assess pending decisions, recommend option
    --limit 10                            # Max projects (default: 10)
    --imessage                            # Send recommendations via iMessage
    --dry-run                             # List projects without running
    --timeout 120                         # Seconds per assessment

# ── Scheduling ──
pm schedule install                       # Install nightly agent batch via launchd (default: 2am)
    --hour 3                              # Override run hour
    --limit 5                             # Projects per run
    --budget 1.00                         # USD per project
    --workers 3                           # Parallel workers
    --dry-run-agent                       # Schedule in assess-only mode
pm schedule uninstall                     # Remove launchd job + plist
pm schedule status                        # Show loaded state + last log line
```

### Document Templates

| Template | Output | Budget | Description |
|----------|--------|--------|-------------|
| `roadmap` | `docs/ROADMAP.md` | $0.50 | Phased roadmap with task checklists |
| `architecture` | `docs/ARCHITECTURE.md` | $0.50 | Architecture, dependencies, data flow |
| `code-review` | `docs/CODE-REVIEW.md` | $0.75 | Code quality, security, improvements |
| `test-coverage` | `docs/TEST-COVERAGE.md` | $0.50 | Test gaps and suggested tests |
| `next-phase` | `docs/NEXT-PHASE.md` | $0.50 | Next development phase plan |
| `status-report` | `docs/STATUS-REPORT.md` | $0.25 | Stakeholder status summary |
| `weekly-summary` | `reports/weekly-{date}.md` | $1.00 | Cross-project weekly summary |

Templates use read-only Claude tools (`Read`, `Glob`, `Grep`) - Claude can explore the codebase but cannot modify files. Output is captured from stdout and written by the executor.

### DocGeneration Model
```python
id: int (primary key, autoincrement)
project_id: str (foreign key -> projects.id)
template_id: str    # "roadmap", "architecture", etc.
output_path: str    # Relative path from project root
generated_at: datetime
duration_secs: float
status: str         # "success", "error", "timeout"
error_message: str  # Error details if failed
file_size_bytes: int
```

## Container Folders

The scanner recognizes these as containers (scans subdirectories):
- `clients/` - Auto-categorizes children as "client"
- `archive/` - Skipped by default
- `node_modules/`, `.git/`, `venv/`, `__pycache__/` - Always skipped

## Development

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests (includes coverage)
pytest

# Run dashboard locally
streamlit run dashboard/app.py
```

## macOS App

The dashboard is available as a macOS app:
- Location: `/Applications/Project Manager.app`
- Launch via Spotlight: Cmd+Space, type "Project Manager"
- Creates iTerm2 tabs for Claude Code sessions

## GitHub

https://github.com/dbbuilder-org/claude-code-project-manager
