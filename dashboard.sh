#!/bin/bash
cd ~/dev2/project-manager
source venv/bin/activate
streamlit run dashboard/app.py --server.headless true
