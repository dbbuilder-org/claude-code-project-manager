#!/bin/bash
cd ~/dev2/project-manager
source venv/bin/activate

PORT=${PM_DASHBOARD_PORT:-8501}

# Check if port is already in use
if lsof -ti tcp:$PORT >/dev/null 2>&1; then
    PID=$(lsof -ti tcp:$PORT)
    echo "Port $PORT is already in use by PID $PID."
    echo "If the dashboard is already running, open http://localhost:$PORT"
    echo "To use a different port: PM_DASHBOARD_PORT=8502 ./dashboard.sh"
    exit 1
fi

streamlit run dashboard/app.py --server.port $PORT --server.address 127.0.0.1 --server.headless true
