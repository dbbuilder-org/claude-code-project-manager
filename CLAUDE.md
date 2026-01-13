# CLAUDE.md - Project Manager Orchestration System

## Project Overview

This is a multi-project orchestration dashboard for Claude Code development. It scans ~200 projects in `~/dev2`, parses their progress documents (TODO.md, PROGRESS.md, etc.), and enables smart "continue" command generation.

## Quick Commands

```bash
# Activate environment
source venv/bin/activate

# Scan all projects
python -m pm scan ~/dev2

# Show status summary
python -m pm status

# Launch dashboard
python -m pm dashboard

# Continue a specific project
python -m pm continue remoteC

# Batch continue
python -m pm continue --filter type:client --parallel 3
```

## Architecture

```
pm/
├── cli.py           # Click CLI entrypoint
├── scanner/         # Project detection & parsing
│   ├── detector.py  # Find valid projects
│   └── parser.py    # Parse TODO.md, PROGRESS.md
├── database/        # SQLite storage
│   └── models.py    # SQLAlchemy models
├── generator/       # Continue prompt generation
│   └── prompts.py   # Smart context-aware prompts
└── api/             # FastAPI backend
    └── main.py      # REST API
```

## Key Patterns

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
- `CLAUDE.md` (any Claude Code project)

### Continue Prompt Generation

Three modes:
1. **Simple**: Just `claude --resume`
2. **Context-aware**: Parsed state + next action
3. **Decision-point**: Surfaces pending decisions

## Database Schema

```sql
projects (id, path, name, type, completion_pct, current_phase, next_action, ...)
progress_items (id, project_id, type, content, status, priority, ...)
scan_history (id, project_id, scanned_at, completion_pct, ...)
```

## Integration with claudecoderun

This extends ~/dev2/claudecoderun with:
- `--from-dashboard` mode
- Smart prompt injection
- Batch project selection

## Development Notes

- Use SQLite for simplicity (single file, no server)
- Streamlit for rapid dashboard prototyping
- FastAPI for REST API if needed
- Click for CLI interface
