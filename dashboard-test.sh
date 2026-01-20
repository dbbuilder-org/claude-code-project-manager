#!/bin/bash
# Launch dashboard in a NEW iTerm2 window (not tab) for testing
# Close the window to cleanly shut down without affecting other work

osascript -e '
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        write text "cd ~/dev2/project-manager && source venv/bin/activate && echo \"Dashboard Test Window - Close this window to stop\" && streamlit run dashboard/app.py --server.headless true"
    end tell
end tell
'
