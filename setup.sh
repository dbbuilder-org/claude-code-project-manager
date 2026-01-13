#!/bin/bash
# Project Manager - Setup Script
# Installs dependencies and configures the pm CLI tool

set -e

echo "============================================"
echo "  Project Manager - Setup"
echo "============================================"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d" " -f2 | cut -d"." -f1,2)
echo "Python version: $PYTHON_VERSION"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q

# Install package in editable mode
echo "Installing project-manager..."
pip install -e . -q

# Install dev dependencies
echo "Installing development dependencies..."
pip install -e ".[dev]" -q

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "To activate the environment:"
echo "  source venv/bin/activate"
echo ""
echo "Available commands:"
echo "  pm --help           Show all commands"
echo "  pm scan <dir>       Scan directory for projects"
echo "  pm status           Show project status table"
echo "  pm summary          Quick portfolio summary"
echo "  pm health           Show projects by health score"
echo "  pm continue <name>  Generate continue command"
echo "  pm launch <names>   Launch Claude Code sessions"
echo "  pm dashboard        Open Streamlit dashboard"
echo ""
echo "Run tests with:"
echo "  pytest tests/"
echo ""
echo "Quick start:"
echo "  pm scan ~/dev2"
echo "  pm status"
echo ""
