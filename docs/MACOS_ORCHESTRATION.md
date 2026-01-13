# macOS Claude Code Orchestration Guide

## The Current Landscape (January 2025)

### What Happened with Third-Party Tools

**Anthropic's Crackdown (January 9, 2025):**
- Tools like [OpenCode](https://github.com/anomalyco/opencode) and Roo were blocked from using Claude Max subscriptions
- These tools were "spoofing" Claude Code's client identity to access favorable pricing
- [VentureBeat reported](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses) that Anthropic cited technical instability and debugging difficulty
- The economic reality: $200/month Max subscription gave unlimited tokens vs $1,000+/month via API

**Impact:**
- OpenCode pivoted to OpenAI Codex integration
- [Hacker News discussion](https://news.ycombinator.com/item?id=46549823) showed 245+ points of developer frustration
- Users canceling subscriptions, calling forced migration "going back to the stone age"

**What Still Works:**
- Official Claude Code CLI ✅
- Claude Code VS Code/JetBrains extensions ✅
- API access with your own tokens ✅
- Headless mode for automation ✅

---

## Recommended Approaches for macOS

### Approach 1: Git Worktrees + Multiple Terminals (Recommended)

**Best for:** Parallel feature development, multiple concurrent Claude sessions

**How it works:**
Git worktrees create lightweight "clones" that share history but have isolated working directories. Each worktree gets its own Claude Code session.

```bash
# Create a worktree for a feature
git worktree add ../project-feature1 -b feat/feature1

# Open Claude Code in that worktree
cd ../project-feature1 && claude

# List all worktrees
git worktree list

# Cleanup when done
git worktree remove ../project-feature1
```

**Incident.io's `w` function pattern:**
```bash
# ~/.zshrc or ~/.bashrc
w() {
    local project=$1
    local branch=$2
    local worktree_dir=~/projects/worktrees/$project/$branch

    # Create worktree if doesn't exist
    if [ ! -d "$worktree_dir" ]; then
        cd ~/projects/$project
        git worktree add "$worktree_dir" -b "$USER/$branch"
    fi

    cd "$worktree_dir"
    claude  # Start Claude Code
}

# Usage: w myproject new-feature
```

**Pros:**
- Truly isolated environments
- Shared git history
- Less disk space than full clones
- [Incident.io reports](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees) managing 7 concurrent AI conversations

**Cons:**
- Setup overhead per feature
- Mental context-switching between sessions
- Higher token consumption

---

### Approach 2: CCManager (Session Manager Tool)

**Best for:** Managing multiple sessions with visual status indicators

[CCManager](https://github.com/kbwo/ccmanager) is purpose-built for this problem.

**Installation:**
```bash
npm install -g ccmanager
# or
npx ccmanager
```

**Features:**
- Multi-session management across worktrees
- Real-time status indicators (idle/busy/waiting for input)
- Copy Claude Code session data between worktrees
- Automation hooks for worktree creation
- Supports: Claude Code, Gemini CLI, Codex CLI, Cursor Agent, Copilot CLI

**Usage:**
```bash
ccmanager              # Launch session manager
# Ctrl+E to switch between sessions
```

**Configuration:** `~/.config/ccmanager/config.json`

---

### Approach 3: iTerm2 + tmux Integration

**Best for:** Persistent sessions that survive disconnects, multiple panes

iTerm2's [tmux integration](https://iterm2.com/documentation-tmux-integration.html) provides native window management with tmux persistence.

**Setup:**
```bash
# Install tmux if needed
brew install tmux

# Start tmux in control mode (integrates with iTerm2)
tmux -CC

# Or create a persistent session
tmux -CC new-session -s claude-projects
```

**Benefits:**
- Sessions persist when laptop sleeps/disconnects
- Each tmux window = iTerm2 tab
- Each tmux pane = iTerm2 split
- Reconnect with `tmux -CC attach`

**Shell alias for convenience:**
```bash
# ~/.zshrc
alias cc-session="tmux -CC new-session -A -s claude-dev"
```

---

### Approach 4: iTerm2 MCP Server (AI-Controlled Terminals)

**Best for:** AI agents controlling terminal windows programmatically

The [iTerm2 MCP Server](https://www.pulsemcp.com/servers/rishabkoul-iterm2) allows Claude to:
- Execute commands in iTerm2 windows
- Capture terminal output
- Manage multiple sessions
- No context switching required

**Setup:**
```json
// claude_desktop_config.json or mcp settings
{
  "mcpServers": {
    "iterm2": {
      "command": "npx",
      "args": ["@rishabkoul/iterm2-mcp-server"]
    }
  }
}
```

---

### Approach 5: Headless Mode + Custom Dashboard (Our Approach)

**Best for:** Orchestrating many projects programmatically

Using Claude Code's [headless mode](https://code.claude.com/docs/en/headless) with our project-manager:

**Key flags:**
```bash
# Run non-interactively with a prompt
claude -p "Continue from Phase 7.1 testing" --allowedTools "Read,Edit,Bash"

# Get JSON output
claude -p "Summarize progress" --output-format json

# Continue a specific session
claude --resume "$session_id"

# Pipe with system prompt
cat changes.diff | claude -p "Review for security" \
    --append-system-prompt "You are a security engineer"
```

**Integration with project-manager:**
```bash
# Scan projects, generate prompts, launch terminals
pm scan ~/dev2
pm continue remoteC        # Opens iTerm + copies context
pm continue --filter type:client --parallel 3  # Batch launch
```

---

## Practical Scripts for Your Setup

### 1. Launch Multiple Claude Sessions

```bash
#!/bin/bash
# ~/bin/claude-multi.sh

projects=("$@")

for project in "${projects[@]}"; do
    osascript -e "
        tell application \"iTerm\"
            create window with default profile
            tell current session of current window
                write text \"cd ~/dev2/$project && claude --resume\"
            end tell
        end tell
    "
    sleep 1
done
```

**Usage:** `claude-multi.sh remoteC github-spec-kit-init anterix`

### 2. Worktree + Claude Launcher

```bash
#!/bin/bash
# ~/bin/cc-worktree.sh

project=$1
branch=$2
base_dir=~/dev2
worktree_dir=~/worktrees/$project/$branch

if [ ! -d "$worktree_dir" ]; then
    cd "$base_dir/$project"
    git worktree add "$worktree_dir" -b "$branch"
fi

osascript -e "
    tell application \"iTerm\"
        create window with default profile
        tell current session of current window
            write text \"cd $worktree_dir && claude\"
        end tell
    end tell
"
```

**Usage:** `cc-worktree.sh remoteC feat/phase7-testing`

### 3. Project Dashboard Launcher

Integrates with our project-manager:

```bash
#!/bin/bash
# ~/bin/pm-launch.sh

cd ~/dev2/project-manager
source venv/bin/activate

# Get top priority projects
projects=$(python -c "
from pm.database.models import init_db, get_session, Project
init_db()
session = get_session()
for p in session.query(Project).filter(Project.has_pending_decision==True).limit(5):
    print(p.name)
session.close()
")

echo "Launching projects with pending decisions:"
echo "$projects"

for project in $projects; do
    echo "Launching $project..."
    osascript -e "
        tell application \"iTerm\"
            create window with default profile
            tell current session of current window
                write text \"cd ~/dev2/$project && claude --resume\"
            end tell
        end tell
    "
    sleep 2
done
```

---

## Comparison Matrix

| Approach | Setup | Isolation | Persistence | Multi-Session | Best For |
|----------|-------|-----------|-------------|---------------|----------|
| Git Worktrees | Medium | Full | No | Manual | Feature branches |
| CCManager | Low | Full | Yes | Managed | Daily workflow |
| iTerm2 + tmux | Medium | Split panes | Full | Visual | Remote/persistent |
| iTerm2 MCP | Medium | Per-window | No | AI-controlled | Automation |
| Headless + Dashboard | High | Full | Session ID | Programmatic | Large portfolios |

---

## Recommended Setup for Your Workflow

Given your 200+ projects, I recommend a hybrid approach:

1. **Daily management:** Use our `project-manager` dashboard to see status and priorities
2. **Parallel work:** Use git worktrees for concurrent feature development
3. **Session persistence:** iTerm2 + tmux for long-running sessions
4. **Batch operations:** Headless mode scripts for CI/automation

**Quick Start:**
```bash
# Install ccmanager globally
npm install -g ccmanager

# Setup tmux integration
brew install tmux
echo 'alias cc-session="tmux -CC new-session -A -s claude"' >> ~/.zshrc

# Use project-manager for orchestration
cd ~/dev2/project-manager
source venv/bin/activate
pm summary
pm status --filter type:client
pm continue <project-name>
```

---

## Sources

- [Anthropic blocks third-party Claude Code usage](https://venturebeat.com/technology/anthropic-cracks-down-unauthorized-claude-usage-by-third-party-harnesses) - VentureBeat
- [Claude Code Headless Mode Docs](https://code.claude.com/docs/en/headless) - Official
- [Running Multiple Sessions with Git Worktree](https://dev.to/datadeer/part-2-running-multiple-claude-code-sessions-in-parallel-with-git-worktree-165i) - DEV.to
- [Incident.io Git Worktrees Workflow](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees) - Incident.io Blog
- [CCManager GitHub](https://github.com/kbwo/ccmanager) - Session Manager
- [iTerm2 tmux Integration](https://iterm2.com/documentation-tmux-integration.html) - iTerm2 Docs
- [iTerm2 MCP Server](https://www.pulsemcp.com/servers/rishabkoul-iterm2) - PulseMCP
- [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices) - Anthropic Engineering
