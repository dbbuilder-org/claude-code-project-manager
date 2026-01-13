#!/bin/bash
# claude-tmux.sh - Manage Claude Code sessions with tmux
#
# Benefits:
#   - Sessions persist when terminal closes
#   - Split panes for multiple projects
#   - Reconnect to running sessions
#
# Usage:
#   claude-tmux.sh new <session-name> <project>    Create new session
#   claude-tmux.sh add <session-name> <project>    Add project to session
#   claude-tmux.sh attach <session-name>           Attach to session
#   claude-tmux.sh list                            List all sessions
#   claude-tmux.sh kill <session-name>             Kill session

set -e

DEV2_DIR="$HOME/dev2"
SESSION_PREFIX="claude"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Check tmux is installed
check_tmux() {
    if ! command -v tmux &>/dev/null; then
        echo -e "${RED}tmux not installed.${NC} Install with: brew install tmux"
        exit 1
    fi
}

# Create new tmux session with Claude Code
new_session() {
    local session_name="${SESSION_PREFIX}-$1"
    local project="$2"
    local project_path="$DEV2_DIR/$project"

    if [ ! -d "$project_path" ]; then
        echo -e "${RED}Project not found:${NC} $project_path"
        exit 1
    fi

    if tmux has-session -t "$session_name" 2>/dev/null; then
        echo -e "${YELLOW}Session exists:${NC} $session_name"
        echo "Use: $0 attach $1"
        exit 1
    fi

    echo -e "${GREEN}Creating session:${NC} $session_name with $project"

    # Create session
    tmux new-session -d -s "$session_name" -c "$project_path"
    tmux send-keys -t "$session_name" "claude --resume" Enter

    # Rename window
    tmux rename-window -t "$session_name" "$project"

    echo -e "${GREEN}Session created.${NC} Attach with: $0 attach $1"
}

# Add a new window/pane to existing session
add_to_session() {
    local session_name="${SESSION_PREFIX}-$1"
    local project="$2"
    local project_path="$DEV2_DIR/$project"

    if [ ! -d "$project_path" ]; then
        echo -e "${RED}Project not found:${NC} $project_path"
        exit 1
    fi

    if ! tmux has-session -t "$session_name" 2>/dev/null; then
        echo -e "${RED}Session not found:${NC} $session_name"
        echo "Create with: $0 new $1 <first-project>"
        exit 1
    fi

    echo -e "${GREEN}Adding${NC} $project to $session_name"

    # Create new window
    tmux new-window -t "$session_name" -n "$project" -c "$project_path"
    tmux send-keys -t "$session_name:$project" "claude --resume" Enter

    echo -e "${GREEN}Added.${NC} Window created for $project"
}

# Attach to session (iTerm2 control mode for best experience)
attach_session() {
    local session_name="${SESSION_PREFIX}-$1"

    if ! tmux has-session -t "$session_name" 2>/dev/null; then
        echo -e "${RED}Session not found:${NC} $session_name"
        list_sessions
        exit 1
    fi

    # Check if we're in iTerm2
    if [ "$TERM_PROGRAM" = "iTerm.app" ]; then
        echo -e "${BLUE}Attaching with iTerm2 integration...${NC}"
        tmux -CC attach -t "$session_name"
    else
        echo -e "${BLUE}Attaching...${NC}"
        tmux attach -t "$session_name"
    fi
}

# List all Claude sessions
list_sessions() {
    echo -e "${BLUE}Claude Code tmux sessions:${NC}"
    echo ""

    if ! tmux list-sessions 2>/dev/null | grep "^${SESSION_PREFIX}" ; then
        echo "  No active sessions"
        echo ""
        echo "Create one with: $0 new <name> <project>"
    fi
}

# Kill a session
kill_session() {
    local session_name="${SESSION_PREFIX}-$1"

    if ! tmux has-session -t "$session_name" 2>/dev/null; then
        echo -e "${RED}Session not found:${NC} $session_name"
        exit 1
    fi

    tmux kill-session -t "$session_name"
    echo -e "${GREEN}Killed session:${NC} $session_name"
}

# Multi-project session setup
setup_multi() {
    local session_name="${SESSION_PREFIX}-multi"
    local projects=("$@")

    if [ ${#projects[@]} -eq 0 ]; then
        echo "Usage: $0 multi project1 project2 project3 ..."
        exit 1
    fi

    # Kill existing multi session
    tmux kill-session -t "$session_name" 2>/dev/null || true

    echo -e "${GREEN}Creating multi-project session${NC}"

    # Create session with first project
    local first="${projects[0]}"
    local first_path="$DEV2_DIR/$first"

    tmux new-session -d -s "$session_name" -c "$first_path" -n "$first"
    tmux send-keys -t "$session_name:$first" "claude --resume" Enter

    # Add remaining projects
    for project in "${projects[@]:1}"; do
        local project_path="$DEV2_DIR/$project"
        if [ -d "$project_path" ]; then
            tmux new-window -t "$session_name" -n "$project" -c "$project_path"
            tmux send-keys -t "$session_name:$project" "claude --resume" Enter
            sleep 0.5
        else
            echo -e "${YELLOW}Skipping (not found):${NC} $project"
        fi
    done

    # Go to first window
    tmux select-window -t "$session_name:0"

    echo -e "${GREEN}Created session with ${#projects[@]} projects${NC}"
    echo "Attach with: $0 attach multi"
}

# Show help
show_help() {
    echo "Claude Code tmux Session Manager"
    echo ""
    echo "Usage:"
    echo "  $0 new <name> <project>        Create new session"
    echo "  $0 add <name> <project>        Add project to session"
    echo "  $0 attach <name>               Attach to session"
    echo "  $0 list                        List sessions"
    echo "  $0 kill <name>                 Kill session"
    echo "  $0 multi proj1 proj2 ...       Multi-project session"
    echo ""
    echo "Examples:"
    echo "  $0 new dev remoteC             Create 'claude-dev' with remoteC"
    echo "  $0 add dev anterix             Add anterix to 'claude-dev'"
    echo "  $0 attach dev                  Attach to 'claude-dev'"
    echo "  $0 multi remoteC anterix sql2ai   Create session with 3 projects"
    echo ""
    echo "Tips:"
    echo "  - Use in iTerm2 for best experience (tmux -CC control mode)"
    echo "  - Sessions persist when terminal closes"
    echo "  - Use 'tmux ls' to see all tmux sessions"
}

# Main
check_tmux

case "$1" in
    new)
        [ -z "$2" ] || [ -z "$3" ] && { echo "Usage: $0 new <name> <project>"; exit 1; }
        new_session "$2" "$3"
        ;;
    add)
        [ -z "$2" ] || [ -z "$3" ] && { echo "Usage: $0 add <name> <project>"; exit 1; }
        add_to_session "$2" "$3"
        ;;
    attach)
        [ -z "$2" ] && { echo "Usage: $0 attach <name>"; exit 1; }
        attach_session "$2"
        ;;
    list)
        list_sessions
        ;;
    kill)
        [ -z "$2" ] && { echo "Usage: $0 kill <name>"; exit 1; }
        kill_session "$2"
        ;;
    multi)
        shift
        setup_multi "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
