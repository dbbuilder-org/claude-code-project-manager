# Project Manager

Multi-project Claude Code orchestration dashboard for tracking progress across a portfolio of projects.

## Features

- **Scan projects** - Automatically detect projects by marker files (package.json, pyproject.toml, Cargo.toml, etc.)
- **Parse progress** - Extract completion %, phases, and next actions from TODO.md, PROGRESS.md files
- **Health scoring** - Calculate health scores based on completion, activity, documentation, and git state
- **Decision tracking** - Surface pending decisions (Option A/B patterns) that need resolution
- **Claude Code integration** - Generate context-aware continue prompts and launch sessions
- **Batch launching** - Launch multiple Claude Code sessions in parallel with iTerm2/tmux

## Installation

```bash
# Clone the repo
git clone https://github.com/dbbuilder-org/claude-code-project-manager.git
cd claude-code-project-manager

# Run setup script
./setup.sh

# Activate virtual environment
source venv/bin/activate
```

## Quick Start

```bash
# Scan your projects directory
pm scan ~/dev2

# View portfolio summary
pm summary

# View project status table
pm status

# View health scores (best first)
pm health

# View projects needing attention
pm health --asc

# Generate continue prompt for a project
pm continue myproject --dry-run

# Launch Claude Code for a project
pm launch myproject

# Open dashboard
pm dashboard
```

## Commands

### `pm scan <directory>`

Scan a directory for projects and update the database.

```bash
pm scan ~/dev2              # Scan with default settings
pm scan ~/dev2 --verbose    # Show detailed output
```

**Project detection:**
- Node.js: `package.json`
- Python: `pyproject.toml`, `setup.py`
- Rust: `Cargo.toml`
- Go: `go.mod`
- Ruby: `Gemfile`

**Container folders:** Directories named `clients/` are scanned recursively for client projects.

### `pm status`

Show project status table with progress and phase information.

```bash
pm status                           # Show all projects
pm status --filter type:client      # Filter by category
pm status --filter status:active    # Only incomplete projects
pm status --sort completion         # Sort by completion %
pm status --limit 10                # Limit results
pm status --json                    # JSON output
```

### `pm summary`

Quick summary of portfolio health and distribution.

### `pm health`

Show projects sorted by health score.

```bash
pm health                      # Healthiest first
pm health --asc                # Needs attention (lowest first)
pm health --filter type:client # Filter by category
pm health --limit 10           # Limit results
```

**Health score factors:**
- Completion % (40 points max)
- Recent activity (20 points)
- CLAUDE.md present (15 points)
- Clean git state (15 points)
- No pending decisions (10 points)

### `pm continue <project>`

Generate a context-aware continue command for Claude Code.

```bash
pm continue myproject                    # Generate and copy to clipboard
pm continue myproject --dry-run          # Preview without copying
pm continue myproject --mode decision    # Focus on pending decision
pm continue --filter type:client         # Pick from filtered projects
```

### `pm launch <projects...>`

Launch Claude Code sessions for one or more projects.

```bash
pm launch myproject                     # Launch single project
pm launch proj1 proj2 proj3             # Launch multiple projects
pm launch --filter type:client          # Launch all client projects
pm launch --dry-run myproject           # Preview without launching
pm launch --parallel 3 proj1 proj2 proj3 # Limit parallel sessions
```

### `pm dashboard`

Open the Streamlit dashboard for visual project management.

## Progress File Formats

The parser recognizes these patterns in TODO.md and PROGRESS.md files:

### Checkboxes
```markdown
- [x] Completed task
- [ ] Pending task
- [ ] IN PROGRESS task
- [ ] BLOCKED task
```

### Completion Percentage
```markdown
## Completion: 65%
## Progress: 8 of 10 complete
```

### Phase/Status
```markdown
**Status:** Phase 2 in progress
**Current Phase:** Implementation
**Current Focus:** Building the API layer
**Next Step:** Add unit tests
```

### Decision Points
```markdown
## Architecture Decision

### Option A: PostgreSQL
More scalable for production.

### Option B: SQLite
Simpler for development.

Recommended: Option A
```

## Development

```bash
# Run tests
pytest tests/

# Run with coverage
pytest tests/ --cov=pm --cov-report=html

# Run specific test file
pytest tests/test_parser.py -v
```

## Project Structure

```
project-manager/
├── pm/                      # Main package
│   ├── cli.py              # Click CLI commands
│   ├── database/           # SQLAlchemy models
│   ├── scanner/            # Project detection and parsing
│   └── generator/          # Prompt generation
├── dashboard/              # Streamlit dashboard
├── tests/                  # Test suite
│   ├── conftest.py         # Fixtures
│   ├── test_cli.py         # CLI tests
│   ├── test_detector.py    # Scanner tests
│   ├── test_parser.py      # Parser tests
│   ├── test_models.py      # Database tests
│   ├── test_prompts.py     # Generator tests
│   └── test_e2e.py         # End-to-end tests
└── pyproject.toml          # Package configuration
```

## License

MIT
