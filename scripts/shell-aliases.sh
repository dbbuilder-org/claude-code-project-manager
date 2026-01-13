#!/bin/bash
# Add to ~/.zshrc or ~/.bashrc:
# source ~/dev2/project-manager/scripts/shell-aliases.sh

# Project Manager Directory
export PM_DIR="$HOME/dev2/project-manager"

# ============================================
# Core Aliases
# ============================================

# Project manager CLI
alias pm="cd $PM_DIR && source venv/bin/activate && python -m pm"

# Quick status check
alias pms="pm summary"
alias pmst="pm status --limit 20"

# ============================================
# Claude Code Launchers
# ============================================

# Launch Claude Code for a project
alias ccl="$PM_DIR/scripts/claude-launch.sh"

# tmux-based session management
alias cct="$PM_DIR/scripts/claude-tmux.sh"

# Quick project launch (finds project by partial name)
cc() {
    local project="$1"
    if [ -z "$project" ]; then
        echo "Usage: cc <project-name>"
        return 1
    fi
    $PM_DIR/scripts/claude-launch.sh "$project"
}

# Launch multiple projects
ccm() {
    $PM_DIR/scripts/claude-launch.sh --batch "$(echo "$@" | tr ' ' ',')"
}

# Launch client projects
ccc() {
    $PM_DIR/scripts/claude-launch.sh --filter type:client
}

# Launch projects with pending decisions
ccd() {
    $PM_DIR/scripts/claude-launch.sh --filter decision
}

# ============================================
# Git Worktree Helpers
# ============================================

# Create worktree and launch Claude
ccw() {
    local project="$1"
    local branch="$2"
    if [ -z "$project" ] || [ -z "$branch" ]; then
        echo "Usage: ccw <project> <branch-name>"
        return 1
    fi
    $PM_DIR/scripts/claude-launch.sh --worktree "$project" "$branch"
}

# List worktrees for a project
ccwl() {
    local project="$1"
    if [ -z "$project" ]; then
        echo "Usage: ccwl <project>"
        return 1
    fi
    cd "$HOME/dev2/$project" && git worktree list
}

# Clean up worktree
ccwr() {
    local project="$1"
    local branch="$2"
    if [ -z "$project" ] || [ -z "$branch" ]; then
        echo "Usage: ccwr <project> <branch>"
        return 1
    fi
    cd "$HOME/dev2/$project"
    git worktree remove "$HOME/worktrees/$project/$branch" --force
    echo "Removed worktree: $HOME/worktrees/$project/$branch"
}

# ============================================
# tmux Session Shortcuts
# ============================================

# Create multi-project tmux session
cctm() {
    $PM_DIR/scripts/claude-tmux.sh multi "$@"
}

# Quick attach to session
ccta() {
    $PM_DIR/scripts/claude-tmux.sh attach "${1:-dev}"
}

# List tmux sessions
cctl() {
    $PM_DIR/scripts/claude-tmux.sh list
}

# ============================================
# Daily Workflow
# ============================================

# Morning standup: scan, show status, show priorities
standup() {
    echo "🔄 Scanning projects..."
    pm scan ~/dev2 2>/dev/null
    echo ""
    echo "📊 Portfolio Summary:"
    pm summary
    echo ""
    echo "⚠️  Needs Attention:"
    pm status --filter decision --limit 5
}

# Quick project jump (cd to project)
p() {
    local project="$1"
    if [ -z "$project" ]; then
        echo "Usage: p <project-name>"
        return 1
    fi
    local found=$(find ~/dev2 -maxdepth 2 -type d -name "*$project*" | head -1)
    if [ -n "$found" ]; then
        cd "$found"
        echo "📁 $(pwd)"
    else
        echo "Project not found: $project"
        return 1
    fi
}

# ============================================
# Completion (zsh)
# ============================================

if [ -n "$ZSH_VERSION" ]; then
    # Get project names for completion
    _pm_projects() {
        local projects=($(ls -d ~/dev2/*/ 2>/dev/null | xargs -n1 basename))
        _describe 'projects' projects
    }

    compdef _pm_projects cc ccw ccwl ccwr p
fi

echo "🚀 Claude Code aliases loaded. Try: cc <project>, ccm proj1 proj2, ccd (decisions)"
