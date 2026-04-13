#!/bin/bash
# Launch dashboard in a new terminal window for testing
# Close the window to cleanly shut down without affecting other work
#
# Uses iTerm2 if installed, falls back to Terminal.app

CMD="cd ~/dev2/project-manager && source venv/bin/activate && echo \"Dashboard Test Window - Close this window to stop\" && streamlit run dashboard/app.py --server.headless true"

if [ -d "/Applications/iTerm.app" ]; then
    osascript -e '
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        write text "'"$CMD"'"
    end tell
end tell
'
else
    osascript -e '
tell application "Terminal"
    do script "'"$CMD"'"
    activate
end tell
'
fi
