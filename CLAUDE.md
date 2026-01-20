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
pm urgent                    # Show projects by deadline/priority
pm edit <project> --priority 1 --deadline 2025-02-01
pm health                    # Detailed health report
pm context <project>         # Generate Claude Code continue prompt
```

## Architecture

```
project-manager/
├── pm/                      # Core Python package
│   ├── cli.py              # Click CLI (pm command)
│   ├── metadata.py         # PM-STATUS.md two-way sync
│   ├── database/
│   │   └── models.py       # SQLAlchemy models + migration
│   ├── scanner/
│   │   ├── detector.py     # Project type detection
│   │   └── parser.py       # TODO.md/PROGRESS.md parsing
│   └── generator/
│       └── prompts.py      # Claude Code context generation
├── dashboard/
│   └── app.py              # Streamlit web UI
├── data/
│   └── projects.db         # SQLite database
├── dashboard.sh            # Launch script
└── tests/                  # 161 tests, 67% coverage
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

### Dashboard Tabs
- **All Projects**: Expandable cards with inline editing
- **Urgent**: Overdue and upcoming deadlines
- **Work Queue**: AI-prioritized next actions
- **Decisions**: Projects with pending decisions
- **Clients**: Client projects filtered view
- **Edit**: Full metadata editor
- **Analytics**: Charts and tables

Each project card has:
- Quick actions: Claude Code, VSCode, Terminal, Finder
- Inline editing: Priority, Deadline, Target, Notes (saves to PM-STATUS.md)
- File previews: TODO.md, PROGRESS.md, CLAUDE.md tabs
- Batch selection for multi-project Claude Code launch

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

## CLI Reference

```bash
pm scan <path>              # Scan directory for projects
pm status [--filter X]      # List projects (filter: type:python, category:client)
pm health [--limit N]       # Health report
pm urgent                   # Show by urgency score
pm backlog                  # Show someday/low priority items
pm context <name>           # Generate Claude Code context prompt

pm launch [N|name]          # Launch projects in iTerm2 with transcript + Claude Code
    pm launch               # Launch 10 most recent (default)
    pm launch 5             # Launch 5 most recent
    pm launch myproject     # Launch specific project by name
    --dirty-only, -d        # Only projects with uncommitted changes
    --dry-run               # Preview without launching

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
