# Session Context - Project Manager Development

**Date:** 2026-01-13
**Project:** ~/dev2/project-manager

## Summary

Built a comprehensive multi-project orchestration dashboard for managing ~200+ Claude Code projects. The tool scans projects, tracks progress, calculates health/urgency scores, and provides batch launching capabilities.

## Key Features Implemented

### CLI Commands (`pm`)

| Command | Description |
|---------|-------------|
| `pm scan ~/dev2` | Scan directory for projects, parse progress docs |
| `pm status` | List all projects with health scores (no limit) |
| `pm health` | Detailed health report |
| `pm urgent` | Show projects by urgency (deadlines + priority) |
| `pm backlog` | Show someday/low priority items |
| `pm launch [N\|name]` | Launch N recent projects or specific project |
| `pm launch -d` | Launch only dirty (uncommitted) projects |
| `pm shutdown` | Graceful shutdown with context save to docs/ |
| `pm shutdown --no-context` | Quick shutdown without saving context |
| `pm edit <name>` | Edit project metadata (syncs to PM-STATUS.md) |
| `pm context <name>` | Generate Claude Code continue prompt |

### Dashboard (Streamlit)

**Launch:** `~/dev2/project-manager/dashboard.sh` or Spotlight "Project Manager"

**Tabs:**
- **All Projects** - Expandable cards with inline editing, batch selection
- **Urgent** - Overdue and upcoming deadlines
- **Work Queue** - AI-prioritized next actions
- **Decisions** - Projects with pending decisions
- **Clients** - Client projects filtered view
- **Edit** - Full metadata editor
- **Analytics** - Charts and tables

**Features:**
- Sort by: Last Commit, Last Activity, Name, Health, Completion, Priority, Urgency
- Quick launch buttons: Top 5, Top 10, Launch Dirty, Launch Selected
- Inline editing: Priority, Deadline, Target Date, Notes (auto-syncs to PM-STATUS.md)
- Loading indicator with step-by-step checklist
- 60-second data caching

### Two-Way PM Metadata Sync

Projects can have `PM-STATUS.md` with YAML frontmatter:

```markdown
---
priority: 2
deadline: 2025-02-15
target_date: 2025-03-01
tags: [mobile, ios]
client: Acme Corp
budget_hours: 40
hours_logged: 12
archived: false
---

# Project Notes

Free-form notes here...
```

- Scanner reads PM-STATUS.md during `pm scan`
- CLI `pm edit` and dashboard edits write back to PM-STATUS.md
- Enables project-local metadata that persists with the repo

### Shell Aliases Added (~/.zshrc)

```bash
# Claude Code
alias cc='claude --dangerously-skip-permissions --continue'
alias ccm='claude --dangerously-skip-permissions'
alias cct='transcript && claude --dangerously-skip-permissions --continue'
alias ccl='pm launch'
alias ccs='pm shutdown'
alias ccsd='pm shutdown --no-context'

# Project Manager
alias pms='pm status'
alias pml='pm launch'
alias pmld='pm launch -d'
alias pmu='pm urgent'
alias pmd='~/dev2/project-manager/dashboard.sh'
```

### Transcript Function

Improved `transcript` function that:
- Stores transcripts centrally in `~/dev2/project-manager/transcripts/`
- Renames iTerm2 tab to `📝 project-name`
- Names files as `projectname_YYYYMMDD_HHMMSS.txt`

## Architecture

```
project-manager/
├── pm/
│   ├── cli.py              # Click CLI with all commands
│   ├── metadata.py         # PM-STATUS.md read/write
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
├── transcripts/            # Central transcript storage
├── dashboard.sh            # Launch script
└── tests/                  # 161 tests, 67% coverage
```

## Health Score Algorithm (0-100)

- Completion progress: 0-30 pts
- Has CLAUDE.md: 10 pts
- Has progress files: 10 pts
- Recent activity: 0-20 pts
- No pending decisions: 10 pts
- Clean git state: 10 pts
- Known project type: 10 pts

## Urgency Score Algorithm (0-100)

- Priority 1 (Critical): +40
- Priority 2 (High): +30
- Priority 3 (Normal): +20
- Priority 4 (Low): +10
- Priority 5 (Someday): +0
- Overdue: +50
- Due in ≤3 days: +40
- Due in ≤7 days: +30
- Due in ≤14 days: +20

## macOS Integration

- **App:** `/Applications/Project Manager.app`
- **Spotlight:** Cmd+Space → "Project Manager"
- **iTerm2:** All launches open new tabs with transcript recording

## Files Modified This Session

- `pm/cli.py` - Added launch, shutdown, edit, urgent, backlog commands
- `pm/metadata.py` - NEW: PM-STATUS.md two-way sync
- `pm/database/models.py` - Added PM metadata fields + migration
- `dashboard/app.py` - Enhanced with inline editing, batch launch, loading indicator
- `~/.zshrc` - Added aliases and transcript function
- `/Applications/Project Manager.app` - Created macOS app bundle

## Next Steps / Ideas

- [ ] Add `pm watch` for file system monitoring
- [ ] Dashboard: Real-time refresh with websockets
- [ ] Integration with Claude Code MCP for direct session control
- [ ] Export reports (PDF/markdown) of project status
- [ ] Time tracking integration with hours_logged
