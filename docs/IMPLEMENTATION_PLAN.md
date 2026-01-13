# Implementation Plan - Project Manager

## Status: Phase 1 Complete ✅

**Current State:** Core functionality working, 169 projects scanned, CLI operational.

---

## Phase 1: Core Scanner & CLI ✅ COMPLETE

- [x] Project detector (finds valid projects by markers)
- [x] Progress parser (TODO.md, PROGRESS.md patterns)
- [x] SQLite database with SQLAlchemy models
- [x] CLI: `pm scan` - scans ~/dev2, populates database
- [x] CLI: `pm status` - shows project table
- [x] CLI: `pm summary` - portfolio overview
- [x] CLI: `pm continue` - generates context prompts
- [x] Shell scripts for macOS terminal management
- [x] Git repository initialized

**Metrics:**
- 169 projects detected
- 91 progress files found
- 36 projects at 90%+ completion
- 1 project with pending decision (remoteC)

---

## Phase 2: Enhanced Scanning & Client Detection 🔄 IN PROGRESS

### 2.1 Fix Client Project Detection
The clients folder has nested projects not being detected.

```bash
# Current: Only 1 client detected
# Expected: ~30+ client projects
```

**Tasks:**
- [ ] Increase max_depth for clients folder
- [ ] Add recursive scanning for ~/dev2/clients
- [ ] Tag projects by parent folder path

### 2.2 Improve Progress Parsing
- [ ] Better phase extraction (handle more formats)
- [ ] Extract time estimates from TODO items
- [ ] Parse "Last Updated" dates more reliably
- [ ] Detect stale projects (no commits in 30+ days)

### 2.3 Add Project Health Scoring
- [ ] Calculate health score (0-100) based on:
  - Completion %
  - Last activity date
  - Pending decisions
  - Git dirty state
  - Has CLAUDE.md

---

## Phase 3: Dashboard & Visualization

### 3.1 Improve Streamlit Dashboard
- [ ] Fix layout/styling
- [ ] Add project cards with action buttons
- [ ] Real-time filtering and search
- [ ] Trend charts (completion over time)

### 3.2 Category Views
- [ ] Client projects view with priority sorting
- [ ] Internal IP portfolio view
- [ ] Tools/utilities view

### 3.3 Quick Actions
- [ ] "Launch Claude" button (calls claude-launch.sh)
- [ ] "Copy context" button
- [ ] "View in Finder" button

---

## Phase 4: Smart Continue & Session Management

### 4.1 Improve Continue Prompts
- [ ] Better decision point detection
- [ ] Include recent git commits in context
- [ ] Summarize last session activity
- [ ] Add project-specific instructions from CLAUDE.md

### 4.2 Session Tracking
- [ ] Track Claude Code session IDs
- [ ] Resume specific sessions
- [ ] Session history per project

### 4.3 Batch Operations
- [ ] Launch multiple projects in parallel
- [ ] Batch status updates
- [ ] Daily/weekly reports

---

## Phase 5: Integration & Automation

### 5.1 claudecoderun Integration
- [ ] Add `--from-dashboard` mode to claudecoderun
- [ ] Share project database
- [ ] Stage-based launching with project manager context

### 5.2 Background Scanning
- [ ] Cron job or launchd for periodic scans
- [ ] File watcher for progress document changes
- [ ] Git hook integration

### 5.3 Notifications
- [ ] Desktop notifications for stale projects
- [ ] Slack/email weekly summary (optional)

---

## Quick Wins for Today

1. **Fix client scanning** - Most impactful
2. **Add shell aliases to ~/.zshrc** - Immediate productivity
3. **Test dashboard** - Visual feedback
4. **Improve status table display** - Better CLI UX

---

## Commands to Verify

```bash
# Activate environment
cd ~/dev2/project-manager
source venv/bin/activate

# Core commands
pm scan ~/dev2           # Scan all projects
pm summary               # Portfolio overview
pm status --limit 20     # Project table
pm status --filter type:client  # Client projects only
pm continue remoteC --dry-run   # Generate continue prompt

# Shell scripts
./scripts/claude-launch.sh remoteC          # Launch in iTerm
./scripts/claude-tmux.sh multi remoteC anterix  # tmux session

# Dashboard
pm dashboard             # Launch Streamlit (port 8501)
```

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Projects detected | 169 | 200+ |
| Client projects | 1 | 30+ |
| Avg completion known | 48% | 90% |
| Projects with health score | 0 | 100% |
| Dashboard load time | N/A | <2s |
