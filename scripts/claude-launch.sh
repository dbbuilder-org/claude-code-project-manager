#!/bin/bash
# claude-launch.sh - Launch Claude Code in iTerm2 with project context
#
# Usage:
#   claude-launch.sh <project-name>           # Single project
#   claude-launch.sh --batch project1,project2  # Multiple projects
#   claude-launch.sh --filter type:client      # Filter from database
#   claude-launch.sh --worktree project branch # New worktree

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_MANAGER_DIR="$(dirname "$SCRIPT_DIR")"
DEV2_DIR="$HOME/dev2"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check for iTerm2
check_iterm() {
    if ! osascript -e 'tell application "System Events" to (name of processes) contains "iTerm2"' &>/dev/null; then
        echo -e "${BLUE}Starting iTerm2...${NC}"
        open -a iTerm
        sleep 2
    fi
}

# Launch a single Claude session in a new iTerm2 window
launch_project() {
    local project_path="$1"
    local project_name="$(basename "$project_path")"
    local context="$2"

    echo -e "${GREEN}Launching${NC} $project_name"

    osascript <<EOF
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        set name to "$project_name"
        write text "cd '$project_path'"
        delay 0.5
        write text "claude --resume"
    end tell
end tell
EOF

    # Copy context to clipboard if provided
    if [ -n "$context" ]; then
        echo "$context" | pbcopy
        echo -e "  ${BLUE}Context copied to clipboard${NC}"
    fi
}

# Launch with git worktree
launch_worktree() {
    local project="$1"
    local branch="$2"
    local project_path="$DEV2_DIR/$project"
    local worktree_dir="$HOME/worktrees/$project/$branch"

    if [ ! -d "$project_path" ]; then
        echo -e "${RED}Project not found:${NC} $project_path"
        exit 1
    fi

    # Create worktree if needed
    if [ ! -d "$worktree_dir" ]; then
        echo -e "${BLUE}Creating worktree:${NC} $worktree_dir"
        cd "$project_path"
        git worktree add "$worktree_dir" -b "$branch" 2>/dev/null || \
        git worktree add "$worktree_dir" "$branch"
    fi

    launch_project "$worktree_dir"
}

# Get projects from project-manager database
get_projects_from_filter() {
    local filter="$1"
    cd "$PROJECT_MANAGER_DIR"
    source venv/bin/activate 2>/dev/null || true

    python3 -c "
from pm.database.models import init_db, get_session, Project
init_db()
session = get_session()
query = session.query(Project)

filter_str = '$filter'
if filter_str.startswith('type:'):
    category = filter_str.split(':')[1]
    query = query.filter(Project.category == category)
elif filter_str.startswith('decision'):
    query = query.filter(Project.has_pending_decision == True)
elif filter_str.startswith('dirty'):
    query = query.filter(Project.git_dirty == True)

for p in query.limit(10):
    print(p.path)
session.close()
"
}

# Get context for a project
get_project_context() {
    local project_path="$1"
    cd "$PROJECT_MANAGER_DIR"
    source venv/bin/activate 2>/dev/null || true

    python3 -c "
from pm.scanner.parser import ProgressParser
from pm.generator.prompts import ContinuePromptGenerator, PromptMode
from pathlib import Path

parser = ProgressParser()
generator = ContinuePromptGenerator()
project_path = Path('$project_path')
progress = parser.parse_project(project_path)
prompt = generator.generate(project_path, project_path.name, progress, PromptMode.CONTEXT)
if prompt.prompt_text:
    print(prompt.prompt_text)
" 2>/dev/null || true
}

# Main logic
main() {
    check_iterm

    case "$1" in
        --batch)
            IFS=',' read -ra projects <<< "$2"
            for project in "${projects[@]}"; do
                project_path="$DEV2_DIR/$project"
                if [ -d "$project_path" ]; then
                    context=$(get_project_context "$project_path")
                    launch_project "$project_path" "$context"
                    sleep 2
                else
                    echo -e "${RED}Not found:${NC} $project"
                fi
            done
            ;;

        --filter)
            projects=$(get_projects_from_filter "$2")
            if [ -z "$projects" ]; then
                echo -e "${RED}No projects match filter:${NC} $2"
                exit 1
            fi
            echo "$projects" | while read project_path; do
                if [ -n "$project_path" ] && [ -d "$project_path" ]; then
                    context=$(get_project_context "$project_path")
                    launch_project "$project_path" "$context"
                    sleep 2
                fi
            done
            ;;

        --worktree)
            if [ -z "$2" ] || [ -z "$3" ]; then
                echo "Usage: $0 --worktree <project> <branch>"
                exit 1
            fi
            launch_worktree "$2" "$3"
            ;;

        --help|-h)
            echo "Claude Code Launcher for macOS"
            echo ""
            echo "Usage:"
            echo "  $0 <project-name>                Launch single project"
            echo "  $0 --batch proj1,proj2,proj3     Launch multiple projects"
            echo "  $0 --filter type:client          Launch projects matching filter"
            echo "  $0 --filter decision             Launch projects with pending decisions"
            echo "  $0 --worktree project branch     Create worktree and launch"
            echo ""
            echo "Filters:"
            echo "  type:client    - Client projects"
            echo "  type:internal  - Internal projects"
            echo "  type:tool      - Tool projects"
            echo "  decision       - Projects with pending decisions"
            echo "  dirty          - Projects with uncommitted changes"
            ;;

        *)
            if [ -z "$1" ]; then
                echo "Usage: $0 <project-name> or $0 --help"
                exit 1
            fi

            # Single project
            project_path="$DEV2_DIR/$1"
            if [ ! -d "$project_path" ]; then
                # Try to find it
                found=$(find "$DEV2_DIR" -maxdepth 2 -type d -name "*$1*" | head -1)
                if [ -n "$found" ]; then
                    project_path="$found"
                else
                    echo -e "${RED}Project not found:${NC} $1"
                    exit 1
                fi
            fi

            context=$(get_project_context "$project_path")
            launch_project "$project_path" "$context"
            ;;
    esac
}

main "$@"
